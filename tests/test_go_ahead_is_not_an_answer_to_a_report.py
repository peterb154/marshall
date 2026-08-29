"""Refusing the model's handoff must not throw away the engine's answer.

    "the 'rattler, go aheads' on final i suspect are split brain issues where
     one side is being told to shut up. not a very useful thing or response"

He was right, and the flight recorder shows it one turn before the one he
noticed:

    controller   Ratler, Georgia Center, radar contact.   <- the engine
    atc/pilot    Ratler, Georgia Center, go ahead.        <- the air
"""
import unittest

from marshall.atc import agent_atc as A
from marshall.atc.voice import strip_unauthorised_handoff


class _Bridge:
    directive_now = ""


class _Seat:
    name = "Batumi Approach"


class GoAheadIsNotAnAnswerToAReport(unittest.TestCase):

    def setUp(self):
        self.b, self.seat = _Bridge(), _Seat()

    def test_the_engines_line_goes_out_not_a_stock_phrase(self):
        self.b.directive_now = "Ratler, Georgia Center, radar contact."
        keep = A._keep_him_here(self.b, "Ratler", self.seat)
        self.assertIn("radar contact", keep)
        self.assertNotIn("go ahead", keep.lower())

    def test_the_whole_reply_being_a_handoff_is_the_case_that_bit(self):
        """The commonest shape: nothing survives the strip, so the fallback IS
        the transmission."""
        self.b.directive_now = "Ratler, descend and maintain three thousand."
        out, gone = strip_unauthorised_handoff(
            "Ratler, contact Batumi Tower one one eight decimal six, good day.",
            None, keep_him=A._keep_him_here(self.b, "Ratler", self.seat))
        self.assertIn("three thousand", out)
        self.assertIn("Tower", gone)

    def test_go_ahead_survives_for_when_it_is_true(self):
        """Nothing from the engine and nothing left of the reply -- then "go
        ahead" is the honest answer, and it stays."""
        self.b.directive_now = ""
        self.assertEqual(A._keep_him_here(self.b, "Ratler", self.seat),
                         "Ratler, Batumi Approach, go ahead.")

    def test_an_authorised_handoff_is_still_untouched(self):
        out, gone = strip_unauthorised_handoff(
            "Ratler, contact Batumi Tower one one eight decimal six.",
            "Batumi Tower", keep_him="unused")
        self.assertIn("Tower", out)
        self.assertEqual(gone, "")


if __name__ == "__main__":
    unittest.main()
