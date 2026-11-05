"""Tests for the check that desk has nothing beyond its allowlist (scene 6 of verify.py).

Run:  python3 -m unittest discover -s tests
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from verify import desk_answered  # noqa: E402
from switchlib import DESK_BUILTIN_TOOLS, DESK_SWITCH_TOOLS_OFF, DESK_TOOLS, SWITCH_TOOLS, desk_tools_beyond_allowlist  # noqa: E402

GOOD = {"tools": list(DESK_BUILTIN_TOOLS), "disallowedTools": list(DESK_SWITCH_TOOLS_OFF)}


def delta(added, removed=()):
    return json.dumps({"attachment": {"type": "deferred_tools_delta", "addedNames": list(added),
                                      "removedNames": list(removed)}})


class Allowlist(unittest.TestCase):
    def test_it_keeps_only_talking_in_the_room(self):
        self.assertEqual(set(DESK_TOOLS), {"ToolSearch", "mcp__switch__post_message", "mcp__switch__send_targeted_message"})

    def test_every_other_switch_tool_is_closed(self):
        self.assertEqual(set(SWITCH_TOOLS) - set(DESK_SWITCH_TOOLS_OFF), {"mcp__switch__post_message", "mcp__switch__send_targeted_message"})
        self.assertIn("mcp__switch__add_users_to_room", DESK_SWITCH_TOOLS_OFF)
        self.assertIn("mcp__switch__create_agent", DESK_SWITCH_TOOLS_OFF)
        self.assertIn("mcp__switch__run_template", DESK_SWITCH_TOOLS_OFF)

    def test_clean_definition_and_transcript_pass(self):
        lines = [delta(DESK_TOOLS), "not json", json.dumps({"attachment": {"type": "other", "addedNames": ["switch"]}})]
        self.assertEqual(desk_tools_beyond_allowlist(GOOD, lines), [])

    def test_a_switch_tool_put_back_in_the_definition_fails(self):
        conf = dict(GOOD, disallowedTools=[t for t in DESK_SWITCH_TOOLS_OFF if t != "mcp__switch__add_users_to_room"])
        self.assertEqual(desk_tools_beyond_allowlist(conf, []), ["mcp__switch__add_users_to_room"])

    def test_a_builtin_put_back_in_the_allowlist_fails(self):
        conf = dict(GOOD, tools=list(DESK_BUILTIN_TOOLS) + ["Read"])
        self.assertEqual(desk_tools_beyond_allowlist(conf, []), ["Read"])

    def test_no_allowlist_means_all_tools_and_fails(self):
        conf = dict(GOOD)
        del conf["tools"]
        self.assertEqual(desk_tools_beyond_allowlist(conf, []), ["<every Claude Code tool>"])

    def test_a_tool_offered_at_run_time_fails_even_if_the_definition_looks_right(self):
        self.assertEqual(desk_tools_beyond_allowlist(GOOD, [delta(["mcp__switch__brand_new_tool"])]), ["mcp__switch__brand_new_tool"])

    def test_a_tool_withdrawn_later_in_the_session_is_not_counted(self):
        lines = [delta(["CronCreate"]), delta([], ["CronCreate"])]
        self.assertEqual(desk_tools_beyond_allowlist(GOOD, lines), [])

    def test_switch_adding_its_own_server_to_the_allowlist_is_not_counted(self):
        conf = dict(GOOD, tools=list(DESK_BUILTIN_TOOLS) + ["mcp__switch"])
        self.assertEqual(desk_tools_beyond_allowlist(conf, []), [])


class DeskAnswered(unittest.TestCase):
    ASK = "@desk please add me to the #core room"

    @staticmethod
    def user(text):
        return json.dumps({"type": "user", "message": {"content": text}})

    @staticmethod
    def reply(name="mcp__switch__post_message"):
        return json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": {}}]}})

    def test_a_reply_before_the_request_does_not_count(self):
        self.assertFalse(desk_answered(self.ASK, [self.reply(), self.user(self.ASK)]))

    def test_the_request_and_a_reply_after_it_count(self):
        self.assertTrue(desk_answered(self.ASK, [self.user(self.ASK), self.reply()]))

    def test_a_request_not_yet_in_the_session_does_not_count(self):
        self.assertFalse(desk_answered(self.ASK, [self.user("something else"), self.reply()]))

    def test_reading_a_tool_is_not_a_reply(self):
        self.assertFalse(desk_answered(self.ASK, [self.user(self.ASK), self.reply("ToolSearch")]))


if __name__ == "__main__":
    unittest.main()
