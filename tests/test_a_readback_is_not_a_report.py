"""Two transmissions the engine acted on that it should not have. [#82]

    PILOT: Kobuleti Ground, sockeye, taxi to runway 07, holding short of
           runway 07.
    ATC:   Sockeye, contact Kobuleti Tower one three three decimal zero.

He read the taxi clearance back and it was heard as "I am holding short", so the
phase moved and the ladder handed him to Tower before he had moved an inch. His
own debug note said it better than any diagnosis:

    "clearly, Kobuleti Ground thinks that I'm telling her that I'm holding short
     of runway 07 when actually I'm just doing a read back"

And the second, at nineteen hundred feet on final:

    PILOT: Debug log, that's not correct. You should be sending me to tower now
           on a visual approach.
      .. phase: approach -> landed
      .. ASR guidance suppressed: phase landed does not fly the approach

A note to the project, classified as "I have landed". The engine believed he was
down and suppressed the approach for the rest of the sortie.
"""

from __future__ import annotations

import time
import unittest

from marshall.atc import talkdown as T


class Bridge:
    def __init__(self):
        self.issued: dict = {}
        self.said_to: dict = {}


class TimeIsTheDiscriminator(unittest.TestCase):
    """Word overlap alone cannot separate them, and that is the whole
    difficulty: a genuine "holding short of runway zero seven" is a SUBSET of
    "taxi to runway zero seven, hold short of runway zero seven". A read-back
    FOLLOWS its instruction; the report of complying with it comes minutes
    later, after he has taxied there."""

    def setUp(self):
        self.b = Bridge()
        T.note_issued(self.b, "Sockeye",
                      "taxi to runway zero seven, hold short of runway zero seven")

    def test_the_read_back_is_recognised(self):
        self.assertTrue(T.is_read_back(
            self.b, "Sockeye",
            "Kobuleti Ground, sockeye, taxi to runway 07, holding short of runway 07."))

    def test_whether_he_says_the_digits_or_the_words(self):
        self.assertTrue(T.is_read_back(
            self.b, "Sockeye",
            "taxi to runway zero seven, hold short of runway zero seven, sockeye"))

    def test_the_same_words_much_later_are_a_REPORT(self):
        """He has taxied there. Twenty seconds is one exchange on a radio and
        nowhere near enough time to reach a holding point."""
        self.b.said_to["Sockeye"] = (self.b.said_to["Sockeye"][0],
                                     time.monotonic() - 300.0)
        self.assertFalse(T.is_read_back(
            self.b, "Sockeye", "Kobuleti Ground, sockeye, holding short of runway 07."))

    def test_a_partial_echo_is_not_a_read_back(self):
        """The report says one fact; the read-back repeats the instruction."""
        self.assertFalse(T.is_read_back(
            self.b, "Sockeye", "Kobuleti Ground, sockeye, holding short."))

    def test_an_unrelated_call_in_the_window_is_not_swallowed(self):
        self.assertFalse(T.is_read_back(
            self.b, "Sockeye", "Kobuleti Ground, sockeye, request the current altimeter."))

    def test_and_nothing_said_to_him_means_nothing_to_read_back(self):
        self.assertFalse(T.is_read_back(Bridge(), "Sockeye", "holding short of 07"))


class ItIsWiredWhereItCanStopTheEngine(unittest.TestCase):
    """`reads_back_what_we_said` has existed for weeks and only ever decorated
    the AGENT's prompt -- it could tell a model not to say "negative" and could
    not stop the engine acting on the words."""

    def test_the_report_kinds_are_the_ones_that_move_the_board(self):
        from marshall.atc import agent_atc as A
        from marshall.atc import intents as I
        self.assertIn(I.IntentKind.REPORT_HOLDING_SHORT, A._REPORTS)
        self.assertIn(I.IntentKind.REPORT_LANDED, A._REPORTS)
        # A pilot ASKING for something is never a read-back of what he was told.
        self.assertNotIn(I.IntentKind.REQUEST_TAXI, A._REPORTS)
        self.assertNotIn(I.IntentKind.REQUEST_TAKEOFF, A._REPORTS)

    def test_the_downgrade_happens_before_the_engine_is_told(self):
        import inspect
        from marshall.atc import agent_atc as A
        src = inspect.getsource(A.separation_context)
        i_check = src.index("is_read_back(bridge, known, transcript)")
        i_act = src.index("intents.dispatch(")
        self.assertLess(i_check, i_act, "the board moves before anybody asks")


class ADebugNoteReachesNothing(unittest.TestCase):
    """#82. It ran two hundred and forty lines after `decide`, which had already
    classified the words and let the engine act on them."""

    def test_it_is_the_first_thing_in_the_turn(self):
        import inspect
        from marshall.atc import agent_atc as A
        src = inspect.getsource(A)
        i_note = src.index("note = debug_note(transcript)")
        i_decide = src.index("directive, stack, vectoring = decide(")
        self.assertLess(i_note, i_decide,
                        "the engine acts on a note to the project again")

    def test_and_there_is_only_one_of_them(self):
        import inspect
        from marshall.atc import agent_atc as A
        self.assertEqual(
            inspect.getsource(A).count("note = debug_note(transcript)"), 1)

    def test_the_transmission_that_did_it(self):
        from marshall.atc import voice
        got = voice.debug_note(
            "Debug log, that's not correct. You should be sending me to tower "
            "now on a visual approach.")
        self.assertIsNotNone(got, "this reached the classifier and moved the board")


if __name__ == "__main__":
    unittest.main()
