"""One altitude, two owners, and a controller who must not be wrong about it.

    PILOT:  Georgia Center, sockeye level 5000.
    ATC:    Sockeye, Georgia Center. Assigned altitude is five thousand five
            hundred, not five thousand -- climb...
    PILOT:  "I was clearly assigned to 5,000. Don't know why you said that"

He was. [#98]

TWO FIELDS, BECAUSE THERE ARE TWO OWNERS. `assigned_ft` is the separation
engine's -- a stack slot, a vectoring altitude, a missed-approach level, a
number chosen to keep aeroplanes apart, where `None` genuinely means "not in the
stack" and `_free_slot` depends on it. `cleared_ft` is the clearance's cruise
level, which this engine never issued and had nowhere to put.

Collapsing them was not an option: a cruise level written into `assigned_ft`
becomes a holding slot the first time somebody enters the pattern, and that is a
separation bug -- the one class an LLM must never be near.

AND THE NUMBER IS VERIFIED ON THE WAY OUT, because fixing where it comes from
would not have caught either incident. In #95 the engine said 8,000 and the
agent voiced five thousand five hundred; in #98 the clearance said 5,000 and the
agent voiced five thousand five hundred. Two different correct answers, the same
invented figure. The engine's number was right both times.
"""

from __future__ import annotations

import unittest

from marshall.atc import controller as C
from marshall.atc import decision as D
from marshall.atc import phrasebook


def _ctl():
    from tests.support import profile_for_tests          # noqa: F401
    raise unittest.SkipTest("unused")


class TheTwoAltitudesStayApart(unittest.TestCase):

    def setUp(self):
        self.ac = C.Aircraft(callsign="Sockeye 1-1")

    def test_a_clearance_alone_governs(self):
        """En route, the engine has assigned nothing and the clearance stands.
        This is the case that had no answer at all."""
        self.ac.cleared_ft = 5000
        self.assertEqual(self.ac.governing_ft, 5000)

    def test_an_engine_assignment_outranks_the_clearance(self):
        """A stack slot was issued to keep him away from another aeroplane. It
        supersedes a cruise level agreed on the ramp."""
        self.ac.cleared_ft = 5000
        self.ac.assigned_ft = 3000
        self.assertEqual(self.ac.governing_ft, 3000)

    def test_neither_is_no_answer_rather_than_zero(self):
        """`None` is not a level. A controller with no number must assert none,
        not assert nought."""
        self.assertIsNone(self.ac.governing_ft)

    def test_the_clearance_never_touches_the_stack_field(self):
        """The reason there are two fields. `_free_slot` reads `assigned_ft`
        and `None` means "not in the stack"; a cruise level written there
        becomes this pilot's holding slot."""
        ctl = C.Controller.__new__(C.Controller)
        ctl.aircraft = {"sockeye 1-1": self.ac}
        ctl._resolve = lambda cs: "sockeye 1-1"
        ctl.note_cleared_level("Sockeye 1-1", 5000)
        self.assertEqual(self.ac.cleared_ft, 5000)
        self.assertIsNone(self.ac.assigned_ft,
                          "a cruise level must never look like a stack slot")


class TheAssertedAltitudeIsChecked(unittest.TestCase):
    """#98 criterion 3: a pilot level at his cleared altitude is never
    corrected onto another."""

    def _level(self, ft):
        return D.Decision(kind="level", to="Sockeye 1-1", altitude_ft=ft)

    def test_the_right_number_survives_being_spoken(self):
        self.assertFalse(D.verify(self._level(5000),
                                  "Sockeye, roger, five thousand."))

    def test_grouped_digits_are_the_same_number(self):
        """`5,000` is a controller saying the right thing -- see
        `accepted_forms`, which is why this carries a value and not a string."""
        self.assertFalse(D.verify(self._level(5000), "Sockeye, roger, 5,000."))

    def test_the_invented_number_is_caught(self):
        """The actual transmission, from the sortie that filed #98."""
        missed = D.verify(
            self._level(5000),
            "Sockeye, Georgia Center. Assigned altitude is five thousand five "
            "hundred, not five thousand — climb and maintain five thousand "
            "five hundred.")
        self.assertTrue(missed, "an asserted altitude that is not the one he "
                                "is held to must not pass")

    def test_and_the_repair_is_the_bare_number(self):
        """He is already at it, or being put back onto it. A repair that reads
        like a new instruction is worse than the miss."""
        said = phrasebook.render(self._level(5000))
        self.assertIn("five thousand", said)
        self.assertNotIn("climb", said)
        self.assertNotIn("descend", said)


class TheCorrectionUsesTheGoverningNumber(unittest.TestCase):
    """It used to be blind to the clearance: en route `assigned_ft` is None, so
    a pilot reporting his level fell through to a bare `roger` and nothing in
    the engine had an opinion about his altitude -- which is what left the agent
    free to invent one."""

    def test_the_gate_reads_the_governing_altitude(self):
        import inspect
        src = inspect.getsource(C.Controller.report_beacon)
        self.assertIn("ac.governing_ft", src)
        self.assertNotIn("altitude_ft != ac.assigned_ft", src,
                         "the correction is blind to the clearance again")


if __name__ == "__main__":
    unittest.main()
