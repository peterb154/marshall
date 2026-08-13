"""The controller is handed his situation and remembers only the conversation.

[CTX-1] / #43. Measured before this existed: the average user message sent to
Sonnet was 2,522 characters of which 74 were the pilot's words. The rest was the
situation block, and it was not merely sent -- it was kept, so the window filled
with radar pictures that were true when written and wrong by the time the model
read them.

The tests that matter here are not the arithmetic. They are:

  * that the message a turn is CURRENTLY using is never scrubbed, because
    `apply_management` runs between the tool calls inside one turn and stripping
    the scope mid-turn would have the model answer without the picture it was
    given -- a guidance bug that would look like the model ignoring radar;
  * that a tool result is left alone, because an orphaned or mangled
    tool_use/tool_result pair is a hard API error and a dead radio;
  * that scrubbing is idempotent, since it runs on every cycle.
"""

import unittest
from pathlib import Path

from marshall.atc.agent.context import WINDOW, RadioContext, scrub, strip_situation

SITUATION = (
    "RADAR: 362nd_sockeye [Pony 1-1] (P-51D-30-NA, manned): 8.0 nm on the 281 "
    "radial, 4,659 ft, heading 026\n"
    "TRANSMITTER: the radio calling itself Pony 1-1.\n"
    "STRIP: Pony 1-1, inbound Batumi, cleared: approach, assigned 10,000 ft.\n"
    "YOU ARE: Batumi Approach on 124.0.\n"
)


def call(words: str) -> dict:
    return {"role": "user", "content": [{"text": SITUATION + f"PILOT: {words}"}]}


def reply(words: str) -> dict:
    return {"role": "assistant", "content": [{"text": words}]}


def tool_use() -> dict:
    return {"role": "assistant",
            "content": [{"toolUse": {"toolUseId": "t1", "name": "vector",
                                     "input": {}}}]}


def tool_result() -> dict:
    return {"role": "user",
            "content": [{"toolResult": {"toolUseId": "t1",
                                        "content": [{"text": "heading 120"}]}}]}


class TestWhatSurvivesInHistory(unittest.TestCase):
    def test_the_pilots_words_are_kept_and_the_scope_is_not(self):
        got = strip_situation(SITUATION + "PILOT: request the approach")
        self.assertEqual(got, "PILOT: request the approach")
        self.assertNotIn("RADAR:", got)

    def test_an_older_turn_loses_its_scope(self):
        msgs = [call("request the approach"), reply("Pony 1-1, roger"),
                call("level four thousand"), reply("Pony 1-1, descend three")]
        scrub(msgs)
        self.assertNotIn("RADAR:", msgs[0]["content"][0]["text"])
        self.assertIn("PILOT: request the approach", msgs[0]["content"][0]["text"])

    def test_THE_NEWEST_TURN_KEEPS_ITS_SCOPE(self):
        """The hazard. `apply_management` runs between the tool calls inside a
        turn, so the newest situation-bearing message is the one in flight --
        scrub it and the model answers having lost the picture it was handed."""
        msgs = [call("request the approach"), reply("roger"),
                call("say my position")]
        scrub(msgs)
        self.assertIn("RADAR:", msgs[-1]["content"][0]["text"],
                      "the in-flight turn was stripped of its radar picture")

    def test_mid_turn_after_a_tool_call_the_scope_is_still_there(self):
        """The same hazard in the shape it actually occurs: user, toolUse,
        toolResult -- and the model has yet to compose its reply."""
        msgs = [call("request the approach"), reply("roger"),
                call("vector me to final"), tool_use(), tool_result()]
        scrub(msgs)
        self.assertIn("RADAR:", msgs[2]["content"][0]["text"])
        self.assertNotIn("RADAR:", msgs[0]["content"][0]["text"])

    def test_tool_messages_are_untouched(self):
        """An orphaned or mangled tool pair is a hard API error, which on a
        radio is silence."""
        msgs = [call("a"), tool_use(), tool_result(), reply("b"), call("c")]
        before = [dict(m) for m in (msgs[1], msgs[2])]
        scrub(msgs)
        self.assertEqual(msgs[1], before[0])
        self.assertEqual(msgs[2], before[1])

    def test_assistant_replies_are_untouched(self):
        """His own words are the half of the conversation worth keeping."""
        msgs = [call("a"), reply("Pony 1-1, descend and maintain three thousand"),
                call("b")]
        scrub(msgs)
        self.assertEqual(msgs[1]["content"][0]["text"],
                         "Pony 1-1, descend and maintain three thousand")

    def test_scrubbing_twice_changes_nothing(self):
        """It runs on every event loop cycle."""
        msgs = [call("a"), reply("x"), call("b"), reply("y"), call("c")]
        first = scrub(msgs)
        snapshot = [m["content"][0].get("text") for m in msgs]
        second = scrub(msgs)
        self.assertGreater(first, 0)
        self.assertEqual(second, 0)
        self.assertEqual([m["content"][0].get("text") for m in msgs], snapshot)

    def test_a_hook_event_keeps_its_promise_and_loses_its_scope(self):
        """A fired hook is the other shape the bridge sends. The reason it was
        set is the part that must survive; the radar line is situation."""
        ev = {"role": "user", "content": [{"text":
              "EVENT -- your scheduled hook just fired. Reason you set it: "
              "call Sockeye back about Kobuleti\nRADAR: no contacts\n"
              "Make the radio call now if it is warranted."}]}
        msgs = [ev, reply("Sockeye, Batumi Approach"), call("go ahead")]
        scrub(msgs)
        text = msgs[0]["content"][0]["text"]
        self.assertIn("call Sockeye back about Kobuleti", text)
        self.assertNotIn("RADAR:", text)

    def test_nothing_to_scrub_is_not_an_error(self):
        msgs = [reply("a"), reply("b")]
        self.assertEqual(scrub(msgs), 0)
        self.assertEqual(scrub([]), 0)


class TestTheWindowIsSizedAgainstTheScenario(unittest.TestCase):
    """"I think it needs to be just long enough for a pilot to have a
    conversation with atc" -- and the conversation he wrote is the measure."""

    def test_the_standby_scenario_fits_with_a_tool_call_in_it(self):
        # question, standby, the other aeroplane vectored (with a tool call),
        # his read-back, and the promise honoured.
        msgs = [
            call("approach, sockeye, i have a question"), reply("sockeye, standby"),
            call("andre, turn left 120 descend 2000"), tool_use(), tool_result(),
            reply("Andre, turn left one two zero, descend two thousand"),
            call("descend 2000 turn 120"), reply("Andre, readback correct"),
            reply("sockeye, go ahead with your questions"),
        ]
        self.assertLessEqual(len(msgs), WINDOW,
                             "the scenario the window exists for does not fit in it")

    def test_it_is_bigger_than_the_number_it_replaced(self):
        """16 held 6.3 transmissions and sat on the edge of failing the
        scenario. Scrubbing is what makes a larger window cheaper than the
        smaller one was."""
        self.assertGreater(WINDOW, 16)

    def test_the_trimming_itself_is_inherited_not_reimplemented(self):
        """SlidingWindow preserves tool-use pairs and refuses invalid window
        states. Reimplementing that to count exchanges would risk the radio to
        gain a tidier unit.

        Skipped off the container, where strands is not installed -- the shim in
        context.py is what makes the rest of this file runnable there, and
        asserting against the shim would prove nothing.
        """
        try:
            from strands.agent.conversation_manager import (
                SlidingWindowConversationManager)
        except ImportError:
            self.skipTest("strands not installed here; runs in the director image")
        self.assertTrue(issubclass(RadioContext, SlidingWindowConversationManager))
        self.assertEqual(RadioContext().window_size, WINDOW)


class TestWhatItSaves(unittest.TestCase):
    def test_a_remembered_turn_is_far_smaller(self):
        """Measured on the real sessions: 2,522 chars a turn, 74 of them the
        pilot's words."""
        full = SITUATION + "PILOT: request the approach"
        self.assertLess(len(strip_situation(full)) * 5, len(full))


if __name__ == "__main__":
    unittest.main()


class TestTheFixSurvivesTheLabelBeingStale(unittest.TestCase):
    """Audit finding 1.3, fixed 30 July. `_fix` was computed track-first and
    then rebound by callsign, which needs a BRACKETED tag the picture only
    carries once `identify` has bound him. From check-in until that landed --
    and again whenever the label went stale -- guidance was None for a pilot
    radar could see perfectly, so `reconcile` returned with the holding
    directive AND the talkdown both attached.

    Guarded here rather than in the bridge's own tests because the receive loop
    has none: this asserts on the SOURCE, which is the only thing that can see
    a rebind that undoes an earlier assignment.
    """

    def test_fix_is_not_recomputed_by_callsign_after_being_found_by_track(self):
        import re
        src = (Path(__file__).resolve().parent.parent
               / "src" / "marshall" / "atc" / "agent_atc.py").read_text()
        assigns = re.findall(r"^        _fix = (.+)$", src, re.M)
        self.assertEqual(len(assigns), 1,
                         f"_fix is assigned {len(assigns)} times in the receive "
                         f"loop; the second one discarded the track-first "
                         f"answer: {assigns}")
        self.assertIn("radar_fix_by_track", assigns[0])
