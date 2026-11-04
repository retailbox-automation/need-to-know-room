"""Tests for scripts/audit.py's join: Switch's approval record vs keeper's log.

Run:  python3 -m unittest discover -s tests
"""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from audit import join  # noqa: E402

NOW = datetime.datetime(2026, 11, 5, 15, 0, tzinfo=datetime.timezone.utc)
KEEPER = "agent-keeper"


def card(rid, state="answered", answer="open", at="2026-11-05T14:59:00Z", agent=KEEPER):
    return {"requestId": rid, "agentId": agent, "state": state, "answer": answer, "answeredAt": at}


def grant(rid, result="released", at="2026-11-05T14:59:00Z", settled="2026-11-05T14:59:02Z"):
    return {"request_id": rid, "requester": "dana", "customer": "Acme Bakery Co.", "field": "region",
            "result": result, "approver": "alex", "answered_at": at, "settled_at": settled}


def checks(approvals, grants):
    return {r["request"]: r["check"] for r in join(approvals, grants, KEEPER, NOW)}


class JoinTest(unittest.TestCase):
    def test_released_and_declined_agree(self):
        got = checks([card("r1"), card("r2", answer="keep")],
                     [grant("r1"), grant("r2", result="declined")])
        self.assertEqual(got, {"r1": "ok", "r2": "ok"})

    def test_answer_and_result_disagree(self):
        got = checks([card("r1", answer="keep")], [grant("r1", result="released")])
        self.assertTrue(got["r1"].startswith("MISMATCH"))

    def test_answer_times_disagree(self):
        got = checks([card("r1")], [grant("r1", at="2026-11-05T14:58:00Z")])
        self.assertTrue(got["r1"].startswith("MISMATCH"))

    def test_release_without_any_card(self):
        self.assertTrue(checks([], [grant("r1")])["r1"].startswith("MISMATCH"))

    def test_release_while_card_still_pending(self):
        got = checks([card("r1", state="pending", answer=None, at=None)], [grant("r1")])
        self.assertTrue(got["r1"].startswith("MISMATCH"))

    def test_grant_older_than_switch_retention_is_not_a_mismatch(self):
        got = checks([], [grant("r1", settled="2026-10-20T10:00:00Z")])
        self.assertEqual(got["r1"], "older than Switch keeps")

    def test_answered_card_keeper_never_acted_on(self):
        got = checks([card("r1", at="2026-11-05T14:50:00Z")], [])
        self.assertTrue(got["r1"].startswith("MISMATCH"))

    def test_answered_card_keeper_is_still_settling(self):
        got = checks([card("r1", at="2026-11-05T14:59:50Z")], [])
        self.assertEqual(got["r1"], "keeper is settling it")

    def test_pending_and_expired_cards(self):
        got = checks([card("r1", state="pending", answer=None, at=None),
                      card("r2", state="expired", answer=None, at=None)], [])
        self.assertEqual(got["r1"], "waiting for an answer")
        self.assertEqual(got["r2"], "closed without an answer (expired)")

    def test_other_agents_cards_are_left_out(self):
        self.assertEqual(checks([card("r9", agent="agent-desk")], []), {})


if __name__ == "__main__":
    unittest.main()
