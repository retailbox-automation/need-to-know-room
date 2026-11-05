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
# desk's working directory (Tier B). Deliberately outside your home folder:
# Claude Code reads .claude/CLAUDE.md and .claude/rules/ from every parent
# folder of its working directory, so a folder under ~ would hand desk your
# personal instructions, whatever HOME it runs with.
DESK_DIR = os.environ.get("N2K_DESK_DIR") or "/tmp/need-to-know-room-desk-%d" % os.getuid()
DESK_HOME = os.path.join(STAND, "desk-home")

# What desk (Tier B) may use: talking in its room, and nothing else. A contractor
# can address desk, so whatever desk can do, a contractor can ask for, and a sentence
# in its prompt is the only thing that says no. desk's owner is the Switch admin and
# Switch gives an agent its owner's rights, so the room-admin tools must be gone.
DESK_BUILTIN_TOOLS = ("ToolSearch",)                  # loads the two below; Claude Code keeps them deferred
DESK_TOOLS = DESK_BUILTIN_TOOLS + ("mcp__switch__post_message", "mcp__switch__send_targeted_message")
# Every tool of Switch 0.31.0's own server. Switch always adds that server to a
# `tools` allowlist, so the rest can only be closed by name. A newer Switch may add
# more: scene 6 of verify.py fails on anything desk is offered beyond DESK_TOOLS.
SWITCH_TOOLS = tuple("mcp__switch__" + name for name in """
    add_users_to_room archive_room assume_role attach_reference_to_room connect_to_room create_agent
    create_reference create_room create_room_document create_room_from_yaml create_room_group define_role
    delete_role delete_room_document delete_template download_attachment edit_role get_advanced_config
    get_agent_detail get_my_context get_role_detail get_room_detail get_room_group_detail get_template
    get_template_guide invite_agent_to_room link_rooms list_agents list_all_references list_all_rooms
    list_bridges list_linked_rooms list_machines list_managed_agents list_participants list_reference_types
    list_references list_roles list_room_groups list_rooms list_templates load_internal_documents post_message
    read_context release_role remove_agent_from_room remove_agent_service request_agent_deletion run_template
    save_template send_attachment send_targeted_message set_agent_service unarchive_room unlink_rooms
    update_agent_detail update_room update_room_document update_template""".split())
DESK_SWITCH_TOOLS_OFF = tuple(t for t in SWITCH_TOOLS if t not in DESK_TOOLS)


def desk_tools_beyond_allowlist(advanced_config, transcript_lines):
    """What desk could use beyond DESK_TOOLS: from its definition and from what Claude Code offered it."""
    extra = set()
    allowed = advanced_config.get("tools")
    if not allowed:
        extra.add("<every Claude Code tool>")   # no allowlist means all tools
    else:
        extra.update(set(allowed) - set(DESK_TOOLS) - {"mcp__switch"})  # Switch adds its server itself
    extra.update(set(DESK_SWITCH_TOOLS_OFF) - set(advanced_config.get("disallowedTools") or []))
    deferred, sent = set(), set()
    for line in transcript_lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        attachment = event.get("attachment")
        if isinstance(attachment, dict) and attachment.get("type") == "deferred_tools_delta":
            deferred.update(attachment.get("addedNames") or [])
            deferred.difference_update(attachment.get("removedNames") or [])
        if event.get("type") == "api-request-shape":   # the tools the latest request carried
            sent = {tool.get("name") for tool in (event.get("shape") or {}).get("tools") or []}
    return sorted(extra | ((deferred | sent) - set(DESK_TOOLS)))


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
