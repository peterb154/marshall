"""What he wants is a fact, whatever else the transmission was. [#177]

A pilot's first call to Approach is one breath:

    "Batumi Approach, Probe88, 23 miles northwest, descending eight thousand,
     information Alpha, request the ILS runway one three."

The classifier reads that as CHECK_IN -- it is one -- and extracts
`wants='ILS runway 13'` at the same time. `wants` was read only inside the
REQUEST_APPROACH branch, so the engine replied:

    "report the field in sight ... Say your request."

Asking for a request it was holding. And the first half is the damaging one:
with no procedure assigned `_pro(ac)` is None, `may_vector(None)` is False, so
an ILS arrival is told to look out of the window AND the proactive monitor
skips him for the rest of the approach -- no vectors, no mile calls, silence.

The ATIS letter was hoisted out of the branch for the same reason in #180.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from marshall.atc import controller as C  # noqa: E402
from marshall.core import route as R  # noqa: E402


class ACheckInCanNameAnApproach(unittest.TestCase):

    def setUp(self):
        self.c = C.Controller()
        self.c.check_in("Sockeye")

    def test_a_check_in_that_names_one_assigns_it(self):
        self.assertIsNone(self.c._pro(self.c.get("Sockeye")),
                          "nothing assigned before he asks")
        self.c.note_wants_approach("Sockeye", "ILS runway 13")
        self.assertIsNotNone(self.c._pro(self.c.get("Sockeye")),
                             "he named it; the engine must hold it")

    def test_and_he_is_then_a_vectored_aircraft(self):
        """The consequence that mattered: un-assigned reads as un-vectored, and
        an un-vectored ILS arrival is told to look out of the window."""
        self.c.note_wants_approach("Sockeye", "ILS runway 13")
        ac = self.c.get("Sockeye")
        self.assertTrue(self.c._vectored(ac),
                        "an ILS is vectored to intercept by construction")

    def test_words_that_match_nothing_assign_nothing(self):
        self.c.note_wants_approach("Sockeye", "the visual to the golf course")
        self.assertIsNone(self.c._pro(self.c.get("Sockeye")))

    def test_it_does_not_overrule_an_approach_he_is_already_on(self):
        self.c.note_wants_approach("Sockeye", "ILS runway 13")
        was = self.c._pro(self.c.get("Sockeye"))
        self.c.note_wants_approach("Sockeye", "radar approach runway 13")
        self.assertIs(self.c._pro(self.c.get("Sockeye")), was,
                      "his choice stands until he asks to change it")

    def test_it_does_not_sequence_him(self):
        """A check-in is not the moment to be entered in a stack or cleared --
        he has just arrived on the frequency."""
        # The check-in in setUp has already spoken -- with the very sentence
        # this issue is about, "report the field in sight. Say your request."
        # Measure only what assigning adds.
        self.c.out.clear()
        self.c.note_wants_approach("Sockeye", "ILS runway 13")
        self.assertEqual(self.c.out, [], "assigning is silent")


if __name__ == "__main__":
    unittest.main()
