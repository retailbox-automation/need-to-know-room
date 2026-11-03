#!/usr/bin/env python3
"""keeper: the agent that holds the customer list.

keeper is a scripted Switch agent with no language model. Switch decides who
may talk to it in which room (its addressing policy, set by scripts/seed.py)
and who may answer its approval cards (only people who may address it). keeper
itself decides one thing: which single field to release, and that it is
released once.

  #core         employees ask directly; keeper answers.
  #contractors  only the owner and the owner's agents (desk) reach keeper.
                A field request on someone else's behalf becomes an approval
                card; when the owner presses "Open once", keeper posts that one
                field, once.
  #owner-desk   only the owner reaches keeper; keeper answers.

Run:  python3 agents/keeper/keeper.py
"""
import csv
import datetime
import json
import os
import re
import sys
import threading
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, HERE)
from stream import EventStream  # noqa: E402
from switchlib import ApiError, Stand, load_state  # noqa: E402

DATA = os.path.join(ROOT, "data", "customers.csv")
GRANTS = os.path.join(ROOT, ".stand", "grants.jsonl")
APPROVAL_MINUTES = 15
CONTEXT_SECONDS = 15 * 60   # "and their phone?" refers to the last customer asked about
FIELDS = {  # field -> words people use for it
    "region": ["region", "territory"],
    "city": ["city", "town"],
    "phone": ["phone", "phone number", "number"],
    "email": ["email", "e-mail", "mail"],
    "plan": ["plan", "tier"],
    "annual_value_usd": ["annual value", "revenue", "spend", "contract value"],
    "customer_since": ["customer since", "since when", "start date"],
}
FULL_LIST = re.compile(r"\b(full|whole|entire|all|every)\b.*\b(customers?|clients?|list)\b"
                       r"|\bcustomer list\b|\bclient list\b", re.I)


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def log(msg):
    print("%s keeper: %s" % (now_iso(), msg), flush=True)


class Keeper:
    def __init__(self, stand, state, rows):
        self.stand = stand
        self.me = state["keeper"]
        self.rooms = state["rooms"]                      # name -> id
        self.room_names = {v: k for k, v in self.rooms.items()}
        self.owner = state.get("owner", "alex")
        self.rows = {r["customer"].lower(): r for r in rows}
        self.pending = {}    # request_id -> what was asked, until the owner answers
        self.context = {}    # requester -> (customer, time) for follow-up questions
        self.lock = threading.Lock()

    # Switch I/O ------------------------------------------------------------
    def say(self, room_id, text):
        self.stand.agent("POST", "/agents/%s/message" % self.me["id"], self.me["api_key"],
                         {"room_id": room_id, "content": text})

    def humans_in(self, room_id):
        parts = self.stand.agent("GET", "/agents/rooms/%s/participants" % room_id,
                                 self.me["api_key"])["participants"]
        return {p["name"] for p in parts if p["type"] == "user"}

    def requester_behind(self, room_id):
        """Who an agent is asking for: the last person who spoke in the room.

        The agent's own text is written by a model and could name anyone, so
        keeper never takes the requester from it. Switch's room history says
        who actually spoke.
        """
        humans = self.humans_in(room_id)
        history = self.stand.agent(
            "GET", "/agents/%s/rooms/%s/history?limit=20" % (self.me["id"], room_id),
            self.me["api_key"])["events"]
        for event in reversed(history):
            if event.get("sender_name") in humans:
                return event["sender_name"], event.get("body", "")
        return None, ""

    # Understanding a request -----------------------------------------------
    def find_customer(self, text):
        low = text.lower()
        exact = [row for name, row in self.rows.items() if name in low]
        if exact:
            return max(exact, key=lambda r: len(r["customer"])), []
        # Partial names ("Acme Bakery") match several companies: list them, pick none.
        words = re.findall(r"[a-z]+", low)
        partial = [row["customer"] for name, row in self.rows.items()
                   if len(words) > 1 and any(" ".join(words[i:i + 2]) in name
                                             for i in range(len(words) - 1))]
        return None, sorted(partial)[:5]

    @staticmethod
    def find_field(text):
        low = text.lower()
        hits = [(len(word), field) for field, words in FIELDS.items()
                for word in words if re.search(r"\b%s\b" % re.escape(word), low)]
        return max(hits)[1] if hits else None

    # Handling messages -----------------------------------------------------
    def on_event(self, kind, event):
        payload = event.get("payload") or {}
        if kind != "message" or not payload.get("addressed"):
            return
        room_id = event.get("room_id")
        room = self.room_names.get(room_id)
        sender = payload.get("sender_name") or "?"
        text = re.sub(r"@keeper\b", "", payload.get("body") or "", flags=re.I).strip()
        log("from @%s in #%s: %s" % (sender, room, text))
        if room is None:
            self.say(room_id, "I only work in #core, #contractors and #owner-desk.")
            return
        on_behalf = sender not in self.humans_in(room_id)
        requester = sender
        if on_behalf:
            requester, _ = self.requester_behind(room_id)
            if requester is None:
                self.say(room_id, "@%s I can't tell who is asking, so I won't open anything." % sender)
                return
        self.handle(room, room_id, requester, sender if on_behalf else None, text)

    def handle(self, room, room_id, requester, via, text):
        if FULL_LIST.search(text) and not self.find_field(text):
            if room == "core":
                sample = list(self.rows.values())[:3]
                lines = ["%d customers in #core. First rows below." % len(self.rows), "",
                         "| Customer | Region | City | Plan |", "|---|---|---|---|"]
                lines += ["| %s | %s | %s | %s |" % (r["customer"], r["region"], r["city"], r["plan"])
                          for r in sample]
                self.say(room_id, "\n".join(lines))
            else:
                self.say(room_id, "Full lists stay in #core. I can open one field of one "
                                  "customer, once, if @%s approves." % self.owner)
            return
        customer, maybe = self.find_customer(text)
        field = self.find_field(text)
        if customer is None:
            with self.lock:
                remembered = self.context.get(requester)
            if remembered and time.time() - remembered[1] < CONTEXT_SECONDS:
                customer = remembered[0]
        if customer is None:
            hint = (" Did you mean: %s?" % "; ".join(maybe)) if maybe else ""
            self.say(room_id, "Which customer? Use the full name.%s" % hint)
            return
        if field is None:
            self.say(room_id, "Which field of %s? I can open one of: %s."
                     % (customer["customer"], ", ".join(f.replace("_usd", "") for f in FIELDS)))
            return
        with self.lock:
            self.context[requester] = (customer, time.time())
        if room == "core" or requester == self.owner:
            self.say(room_id, "%s: %s = %s" % (customer["customer"], field, customer[field]))
            return
        self.ask_owner(room_id, requester, via, customer, field)

    def ask_owner(self, room_id, requester, via, customer, field):
        request_id = "n2k-" + uuid.uuid4().hex[:12]
        expires = (datetime.datetime.now(datetime.timezone.utc)
                   + datetime.timedelta(minutes=APPROVAL_MINUTES))
        detail = "Customer: %s · Field: %s · Asked by @%s%s" % (
            customer["customer"], field, requester, (" via @%s" % via) if via else "")
        with self.lock:
            self.pending[request_id] = {"room_id": room_id, "requester": requester, "via": via,
                                        "customer": customer["customer"], "field": field,
                                        "asked_at": now_iso()}
        self.stand.agent("POST", "/agent-sessions/keeper/approvals", self.me["api_key"], {
            "request_id": request_id, "turn_id": request_id, "kind": "approval",
            "title": "Open 1 field for @%s, once?" % requester, "detail": detail,
            "options": [{"id": "open", "label": "Open once", "decision": "accept"},
                        {"id": "keep", "label": "Keep closed", "decision": "decline"}],
            "questions": [], "room_id": room_id, "thread_id": None,
            "expires_at": expires.isoformat()})
        log("approval %s opened: %s" % (request_id, detail))

    # Approval outcomes -----------------------------------------------------
    def poll_outcomes(self):
        while True:
            try:
                outcomes = self.stand.agent("GET", "/agent-sessions/approvals/outcomes",
                                            self.me["api_key"])
                for outcome in outcomes or []:
                    self.settle(outcome)
            except (ApiError, OSError) as exc:
                log("could not read approval outcomes: %s" % exc)
            time.sleep(2)

    def settle(self, outcome):
        request_id = outcome["requestId"]
        with self.lock:
            ask = self.pending.pop(request_id, None)
        if ask is not None:
            approver = self.name_of(ask["room_id"], outcome.get("answeredBy"))
            room_id = ask["room_id"]
            if outcome["state"] == "answered" and outcome.get("answer") == "open":
                value = self.rows[ask["customer"].lower()][ask["field"]]
                self.say(room_id, "%s: %s = %s. Opened once for @%s by @%s."
                         % (ask["customer"], ask["field"], value, ask["requester"], approver))
                result = "released"
            elif outcome["state"] == "answered":
                self.say(room_id, "Kept closed by @%s. Nothing was shared." % approver)
                result = "declined"
            else:
                self.say(room_id, "No answer in %d minutes, so it stays closed. Ask again for a "
                                  "new approval." % APPROVAL_MINUTES)
                result = outcome["state"]
            self.record(dict(ask, request_id=request_id, result=result, approver=approver,
                             answered_at=outcome.get("answeredAt"), settled_at=now_iso()))
        # Acknowledge even unknown ones (e.g. from before a restart) so they stop coming back.
        self.stand.agent("POST", "/agent-sessions/%s/approvals/%s/delivered"
                         % (outcome["sessionId"], request_id), self.me["api_key"], {})

    def name_of(self, room_id, participant):
        """The name behind an opaque participant id.

        Switch's room history pairs each sender id with a name. Someone who has
        only pressed a button may not be in it yet; then the Mattermost account
        name at the end of the id is the fallback.
        """
        if not participant:
            return "nobody"
        history = self.stand.agent(
            "GET", "/agents/%s/rooms/%s/history?limit=50" % (self.me["id"], room_id),
            self.me["api_key"])["events"]
        for event in history:
            if event.get("sender") == participant and event.get("sender_name"):
                return event["sender_name"]
        for name in self.humans_in(room_id):
            if participant.split(":", 1)[0].endswith("-" + name):
                return name
        return participant

    @staticmethod
    def record(entry):
        fd = os.open(GRANTS, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as fh:
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
        log("%s %s/%s for @%s (approver @%s)" % (entry["result"], entry["customer"],
                                                  entry["field"], entry["requester"],
                                                  entry["approver"]))


def main():
    with open(DATA, newline="") as fh:
        rows = list(csv.DictReader(fh))
    state = load_state()
    keeper = Keeper(Stand(), state, rows)
    threading.Thread(target=keeper.poll_outcomes, daemon=True).start()
    stream = EventStream(keeper.stand.api, keeper.me["id"], keeper.me["api_key"],
                         keeper.on_event, log=log)
    log("holding %d customers; waiting for messages" % len(rows))
    stream.run_forever()


if __name__ == "__main__":
    main()
