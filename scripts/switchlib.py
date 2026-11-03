"""A small standard-library client for the Switch and Mattermost APIs.

Need-to-Know Room talks to three surfaces of a local Switch stack:
  * the Switch gateway API (``/gateway/...``), as the seeded admin, to create
    rooms, mint keys and set addressing policies;
  * the Switch agent bridge (``/agents/...``, ``/agent-sessions/...``), with an
    agent's own API key, which is how keeper receives and answers messages;
  * Mattermost's REST API, as the demo people (Alex, Sam, Dana), to post
    messages and press approval buttons the way a human would.

Only the Python standard library is used so the demo runs on a stock python3 (3.9+).
"""
import json
import os
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAND = os.path.join(ROOT, ".stand")
STATE_PATH = os.path.join(STAND, "state.json")


class ApiError(Exception):
    def __init__(self, method, url, status, body):
        super().__init__(f"{method} {url} -> {status}: {str(body)[:500]}")
        self.status = status
        self.body = body


def load_env(path=os.path.join(STAND, ".env")):
    """Read the stack's .env written by scripts/up.sh."""
    env = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key] = value
    return env


def load_state():
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH) as fh:
        return json.load(fh)


def save_state(state):
    fd = os.open(STATE_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)


def call(method, url, body=None, headers=None, timeout=30):
    """One HTTP request. Returns (status, response headers, parsed body)."""
    data = None
    hdrs = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            status, resp_headers = resp.status, resp.headers
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = raw
        raise ApiError(method, url, exc.code, parsed) from None
    try:
        parsed = json.loads(raw) if raw else None
    except ValueError:
        parsed = raw
    return status, resp_headers, parsed


class Stand:
    """Endpoints and credentials of the local stack started by scripts/up.sh."""

    def __init__(self, env=None):
        self.env = env or load_env()
        self.api = "http://127.0.0.1:" + self.env.get("API_HOST_PORT", "8000")
        self.mm = "http://127.0.0.1:" + self.env.get("MATTERMOST_HOST_PORT", "8065")
        self._admin_cookie = None

    # Switch gateway, as the seeded admin ------------------------------------
    def admin_login(self):
        if self._admin_cookie:
            return
        _, headers, _ = call("POST", self.api + "/gateway/auth/login", {
            "email": self.env["GATEWAY_ADMIN_EMAIL"],
            "password": self.env["GATEWAY_ADMIN_PASSWORD"],
        })
        for header in headers.get_all("Set-Cookie") or []:
            if header.startswith("switch_auth="):
                self._admin_cookie = header.split(";", 1)[0]
        if not self._admin_cookie:
            raise RuntimeError("gateway login issued no switch_auth cookie")

    def gw(self, method, path, body=None):
        self.admin_login()
        return call(method, self.api + "/gateway" + path, body,
                    {"Cookie": self._admin_cookie})[2]

    # Switch agent bridge, as an agent ---------------------------------------
    def agent(self, method, path, api_key, body=None, timeout=30):
        return call(method, self.api + path, body,
                    {"Authorization": "Bearer " + api_key}, timeout=timeout)[2]

    # Mattermost -------------------------------------------------------------
    def mm_login(self, username, password):
        _, headers, _ = call("POST", self.mm + "/api/v4/users/login",
                             {"login_id": username, "password": password})
        return headers["Token"]

    def mm_call(self, method, path, token, body=None):
        return call(method, self.mm + "/api/v4" + path, body,
                    {"Authorization": "Bearer " + token})[2]
