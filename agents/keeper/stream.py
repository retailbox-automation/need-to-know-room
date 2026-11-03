"""Keeper's live connection to the Switch agent bridge.

Switch delivers an agent's events over a Server-Sent Events stream, and the
agent proves it is alive by posting a heartbeat every couple of seconds. This
module holds that connection: it opens the stream, keeps the heartbeat going,
reopens with the same connection id when the stream drops, and hands every
domain event to a callback.
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


class EventStream:
    def __init__(self, api, agent_id, api_key, on_event, log=print):
        self.api = api
        self.agent_id = agent_id
        self.api_key = api_key
        self.on_event = on_event
        self.log = log
        self.connection_id = str(uuid.uuid4())  # kept for the life of the process
        self.generation = None
        self.interval = 2.0
        self.last_seq = None
        self._attached = threading.Event()
        self._stop = threading.Event()

    def _auth(self):
        return {"Authorization": "Bearer " + self.api_key}

    def _beat_forever(self):
        url = "%s/agents/%s/connection/beat" % (self.api, self.agent_id)
        while not self._stop.is_set():
            if self._attached.wait(1.0):
                body = {"connection_id": self.connection_id, "generation": self.generation}
                req = urllib.request.Request(
                    url, data=json.dumps(body).encode(), method="POST",
                    headers=dict(self._auth(), **{"Content-Type": "application/json"}))
                try:
                    urllib.request.urlopen(req, timeout=5).read()
                except urllib.error.HTTPError as exc:
                    # 404/409 mean the server no longer holds this stream: reopen.
                    self.log("heartbeat refused (%s); reopening the stream" % exc.code)
                    self._attached.clear()
                except OSError as exc:
                    self.log("heartbeat failed: %s" % exc)
                time.sleep(self.interval)

    def _open(self):
        query = {"connection_id": self.connection_id, "scope": "all",
                 "filter": "addressed", "client": "need-to-know-keeper",
                 "client_version": "0.1.0"}
        query["start_from"] = str(self.last_seq) if self.last_seq is not None else "head"
        url = "%s/agents/%s/events?%s" % (self.api, self.agent_id, urllib.parse.urlencode(query))
        headers = dict(self._auth(), Accept="text/event-stream")
        if self.last_seq is not None:
            headers["Last-Event-ID"] = str(self.last_seq)
        # Switch writes a keepalive comment every 15 s, so 60 s of silence means a dead socket.
        return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60)

    def _read(self, resp):
        event, data, seq = "message", [], None
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if self._stop.is_set():
                return
            if line == "":
                if data:
                    self._dispatch(event, "\n".join(data), seq)
                event, data, seq = "message", [], None
            elif line.startswith(":"):
                continue  # keepalive comment
            elif line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].lstrip())
            elif line.startswith("id:"):
                seq = line[3:].strip()

    def _dispatch(self, event, data, seq):
        try:
            payload = json.loads(data)
        except ValueError:
            self.log("unparseable %s frame: %s" % (event, data[:200]))
            return
        if event == "connection_state":
            self.generation = payload.get("generation")
            self.interval = float(payload.get("heartbeat_interval_seconds") or 2)
            self._attached.set()
            self.log("connected: %d rooms, heartbeat every %ss"
                     % (len(payload.get("rooms") or []), self.interval))
            return
        if event == "evicted":
            self.log("evicted by the server: %s" % payload.get("reason"))
            self._attached.clear()
            return
        if seq is not None:
            self.last_seq = seq
        try:
            self.on_event(event, payload)
        except Exception as exc:  # one bad event must not take the agent down
            self.log("error handling %s event: %r" % (event, exc))

    def run_forever(self):
        threading.Thread(target=self._beat_forever, daemon=True).start()
        backoff = 1
        while not self._stop.is_set():
            try:
                with self._open() as resp:
                    backoff = 1
                    self._read(resp)
            except (urllib.error.URLError, OSError) as exc:
                self.log("stream dropped: %s" % exc)
            self._attached.clear()
            time.sleep(backoff)
            backoff = min(backoff * 2, 15)

    def stop(self):
        self._stop.set()
