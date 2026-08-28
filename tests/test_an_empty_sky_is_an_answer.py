"""An empty scope is not a broken scope. [#207]

`accounted_for` decides whether a board entry is still a real aeroplane, and
`radar_identified` -- which is history, not observation -- was allowed to keep
an entry alive whenever the picture was empty. That is right for a radar
hiccup and wrong for the ordinary state of an aerodrome with nobody flying,
and the two were the same value.

28 August, live: the last pilot deslotted, the scope went empty, and the entry
was therefore accounted for on every tick for ever. The last aeroplane to
leave could never be reaped, because HIS OWN DEPARTURE was what emptied the
picture. He sat on the board as LANDED, owned by a controller who could not
see him, waiting for the next sortie under that callsign to inherit him.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from marshall.atc.agent_atc import Scope, accounted_for  # noqa: E402


class _AC:
    def __init__(self, radar_identified=True, track=""):
        self.radar_identified = radar_identified
        self.track = track


class AnEmptySkyIsAnAnswer(unittest.TestCase):

    def test_the_last_aeroplane_to_leave_can_be_released(self):
        """The exact shape that kept Sockeye on the board after he deslotted."""
        self.assertFalse(
            accounted_for(_AC(), "Sockeye", set(), set(), True),
            "radar answered and did not hold him -- that is evidence he is gone")

    def test_a_failed_poll_still_buys_the_benefit_of_the_doubt(self):
        """The hiccup this protection exists for is unchanged."""
        self.assertTrue(
            accounted_for(_AC(), "Sockeye", set(), set(), False),
            "radar did not answer, so his absence proves nothing")

    def test_radar_that_holds_him_always_accounts_for_him(self):
        self.assertTrue(accounted_for(_AC(), "Sockeye", {"sockeye"}, set(), True))
        self.assertTrue(accounted_for(_AC(), "Sockeye", set(), {"sockeye"}, True))

    def test_a_scope_says_whether_it_answered(self):
        """Empty and failed are different Scopes, which is the whole fix."""
        self.assertFalse(Scope("").ok, "a bare Scope has polled nothing")
        self.assertTrue(Scope("", ok=True).ok)
        # An answer that found nobody is still an answer.
        self.assertEqual(Scope("", ok=True).contacts, [])


if __name__ == "__main__":
    unittest.main()
