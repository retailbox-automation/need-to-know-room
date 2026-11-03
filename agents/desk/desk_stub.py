#!/usr/bin/env python3
"""desk (scripted stand-in): the contractors' helper, without a language model.

The real desk is a Claude Code agent started by Switch's agent controller
(see agents/desk/README.md). This stand-in does the same job in a fixed way so
the whole workflow runs with no model account: it holds no customer data, so
when someone in #contractors asks it about a customer it passes the question
to @keeper in the same room.

Run:  python3 agents/desk/desk_stub.py
"""
import datetime
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "agents", "keeper"))
from stream import EventStream  # noqa: E402
from switchlib import Stand, load_state  # noqa: E402


def log(msg):
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    print("%s desk: %s" % (stamp, msg), flush=True)


def main():
    stand, state = Stand(), load_state()
    me = state["desk"]

    def say(room_id, text):
        stand.agent("POST", "/agents/%s/message" % me["id"], me["api_key"],
                    {"room_id": room_id, "content": text})

    def on_event(kind, event):
        payload = event.get("payload") or {}
        if kind != "message" or not payload.get("addressed"):
            return
        text = re.sub(r"@desk\b", "", payload.get("body") or "", flags=re.I).strip()
        log("from @%s: %s" % (payload.get("sender_name"), text))
        say(event["room_id"], "I don't hold customer data. Asking the owner's data agent.")
        say(event["room_id"], "@keeper %s" % text)

    stream = EventStream(stand.api, me["id"], me["api_key"], on_event, log=log)
    log("ready in #contractors")
    stream.run_forever()


if __name__ == "__main__":
    main()
