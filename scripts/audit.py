#!/usr/bin/env python3
"""Who opened what, and when: Switch's approval record next to keeper's log.

Switch keeps every approval card it showed in a room: who answered, what and
when (GET /gateway/chats/{room}/activity, kept for 7 days). keeper writes
.stand/grants.jsonl when it acts on an answer. This joins the two by request id,
one row per request. A row where they disagree is marked MISMATCH and the exit
code is 1, so the record can be checked, not just printed.

  python3 scripts/audit.py           table
  python3 scripts/audit.py --json    one JSON object per row
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from switchlib import ROOT, Stand, load_state  # noqa: E402

GRANTS = os.path.join(ROOT, ".stand", "grants.jsonl")
RETENTION = datetime.timedelta(days=7)          # how long Switch keeps approvals
SETTLE_GRACE = datetime.timedelta(seconds=30)   # keeper polls outcomes every 2 s
EXPECTED = {"open": "released", "keep": "declined"}  # card answer -> keeper result


def parse_time(value):
    if not value:
        return None
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


def join(approvals, grants, keeper_id, now):
    """Rows of the audit table. Pure function: no network, no files."""
    by_id = {a["requestId"]: a for a in approvals if a.get("agentId") == keeper_id}
    rows, seen = [], set()
    for g in grants:
        rid = g["request_id"]
        seen.add(rid)
        card = by_id.get(rid)
        row = {"request": rid, "asked_by": g["requester"], "customer": g["customer"],
               "field": g["field"], "keeper": g["result"], "approver": g.get("approver"),
               "card": None, "answered_at": g.get("answered_at"), "check": "ok"}
        if card is None:
            settled = parse_time(g.get("settled_at"))
            old = settled is not None and now - settled > RETENTION
            row["check"] = "older than Switch keeps" if old else "MISMATCH: not in Switch's record"
        else:
            row["card"] = card["answer"] or card["state"]
            if card["state"] == "answered":
                if EXPECTED.get(card["answer"]) != g["result"]:
                    row["check"] = "MISMATCH: card says %s, keeper %s" % (card["answer"], g["result"])
                elif card.get("answeredAt") != g.get("answered_at"):
                    row["check"] = "MISMATCH: answer times differ"
            elif g["result"] == "released":
                row["check"] = "MISMATCH: released without an answered card"
        rows.append(row)
    for rid, card in by_id.items():
        if rid in seen:
            continue
        row = {"request": rid, "asked_by": None, "customer": None, "field": None,
               "keeper": None, "approver": None, "card": card["answer"] or card["state"],
               "answered_at": card.get("answeredAt"), "check": "waiting for an answer"}
        answered = parse_time(card.get("answeredAt"))
        if card["state"] == "answered" and answered and now - answered > SETTLE_GRACE:
            row["check"] = "MISMATCH: answered, but keeper never acted"
        elif card["state"] == "answered":
            row["check"] = "keeper is settling it"
        elif card["state"] != "open":
            row["check"] = "closed without an answer (%s)" % card["state"]
        rows.append(row)
    return sorted(rows, key=lambda r: r["answered_at"] or "")


def main():
    stand, state = Stand(), load_state()
    approvals = []
    for room_id in state["rooms"].values():
        approvals += stand.gw("GET", "/chats/%s/activity" % room_id)["approvals"]
    grants = []
    if os.path.exists(GRANTS):
        with open(GRANTS) as fh:
            grants = [json.loads(line) for line in fh if line.strip()]
    now = datetime.datetime.now(datetime.timezone.utc)
    rows = join(approvals, grants, state["keeper"]["id"], now)
    if "--json" in sys.argv:
        for row in rows:
            print(json.dumps(row, sort_keys=True))
    else:
        cols = ["answered_at", "asked_by", "customer", "field", "card", "approver", "keeper", "check"]
        table = [cols] + [[str(r[c] if r[c] is not None else "-") for c in cols] for r in rows]
        widths = [max(len(line[i]) for line in table) for i in range(len(cols))]
        for line in table:
            print("  ".join(cell.ljust(w) for cell, w in zip(line, widths)).rstrip())
        print("\n%d request(s): %d in Switch's record, %d in keeper's log"
              % (len(rows), sum(1 for r in rows if r["card"]), len(grants)))
    bad = [r for r in rows if r["check"].startswith("MISMATCH")]
    if bad:
        print("%d MISMATCH row(s)" % len(bad), file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
