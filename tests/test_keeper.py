"""Tests for keeper's decision: who is asking, and when the owner must be asked.

Run:  python3 -m unittest discover -s tests
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agents", "keeper"))
from keeper import Keeper  # noqa: E402

ACME = {"customer": "Acme Bakery Co.", "region": "North-East", "city": "Boston", "plan": "Growth",
        "phone": "555-0100", "email": "a@example.test", "contact": "A. Baker", "mrr_usd": "100"}


class FakeStand:
    """Answers keeper's calls from a scripted room; records what it posts."""

    def __init__(self, history):
        self.history = history
        self.said, self.cards = [], []

    def agent(self, method, path, key=None, body=None):
        if path.endswith("/participants"):
            return {"participants": [{"name": "alex", "type": "user"}, {"name": "dana", "type": "user"},
                                     {"name": "desk", "type": "agent"}, {"name": "keeper", "type": "agent"}]}
        if "/history" in path:
            return {"events": self.history}
        if path.endswith("/message"):
            self.said.append(body["content"])
            return {}
        if path.endswith("/approvals"):
            self.cards.append(body)
            return {}
        raise AssertionError(path)


def keeper_with(history):
    stand = FakeStand([{"sender_name": who, "body": body} for who, body in history])
    state = {"keeper": {"id": "k", "api_key": "x"}, "rooms": {"contractors": "r1", "core": "r2"}, "owner": "alex"}
    return Keeper(stand, state, [ACME]), stand


def event(sender, body):
    return {"room_id": "r1", "payload": {"addressed": True, "sender_name": sender, "body": body}}


class WhoIsAsking(unittest.TestCase):
    def test_the_person_who_addressed_the_agent_not_whoever_spoke_last(self):
        k, _ = keeper_with([("dana", "@desk what's the region of Acme Bakery Co.?"), ("alex", "morning all")])
        self.assertEqual(k.requester_behind("r1", "desk")[0], "dana")

    def test_nobody_addressed_it_falls_back_to_the_last_person(self):
        k, _ = keeper_with([("dana", "hello"), ("alex", "morning all")])
        self.assertEqual(k.requester_behind("r1", "desk")[0], "alex")

    def test_nobody_in_the_history(self):
        k, _ = keeper_with([])
        self.assertIsNone(k.requester_behind("r1", "desk")[0])


class OwnerMustBeAsked(unittest.TestCase):
    def test_alex_talking_while_desk_thinks_does_not_skip_the_card(self):
        k, stand = keeper_with([("dana", "@desk what's the region of Acme Bakery Co.?"), ("alex", "morning all")])
        k.on_event("message", event("desk", "@keeper region of Acme Bakery Co."))
        self.assertEqual(stand.said, [])
        self.assertEqual(len(stand.cards), 1)
        self.assertIn("Asked by @dana via @desk", stand.cards[0]["detail"])

    def test_a_request_through_desk_gets_a_card_even_if_alex_asked(self):
        k, stand = keeper_with([("alex", "@desk what's the region of Acme Bakery Co.?")])
        k.on_event("message", event("desk", "@keeper region of Acme Bakery Co."))
        self.assertEqual(stand.said, [])
        self.assertEqual(len(stand.cards), 1)

    def test_alex_asking_keeper_directly_gets_the_field(self):
        k, stand = keeper_with([])
        k.on_event("message", event("alex", "@keeper region of Acme Bakery Co."))
        self.assertEqual(stand.cards, [])
        self.assertEqual(stand.said, ["Acme Bakery Co.: region = North-East"])


if __name__ == "__main__":
    unittest.main()
