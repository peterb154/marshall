"""A controller who cannot see must not vouch for an aeroplane.

`bridge.seen_at` is one dict shared by every controller thread; `radar_on` is
per thread. A procedural seat polls with an unread scope, which `accounted_for`
answers with the #207 benefit of the doubt -- so the blind seat refreshed the
shared staleness clock for every ghost the seeing seat was running down.

On the sortie of 29 August `362nd_andre` and `Apex` stayed on the board for two
hours while `Shooter` came off in eight minutes.
"""
import unittest

from marshall.atc import agent_atc as A
from marshall.atc.agent_atc import Scope


class _AC:
    def __init__(self):
        self.track, self.radar_identified = "", True
        self.callsign = "Andre"


class _Ctl:
    def __init__(self):
        self.aircraft = {"Andre": _AC()}

    def release(self, cs):
        return self.aircraft.pop(cs, None) is not None


class ABlindTickHasNoOpinion(unittest.TestCase):

    def setUp(self):
        self.b, self.c = A.Bridge(), _Ctl()
        self.stale = A.STALE_BOARD_SEC

    def test_a_blind_tick_does_not_refresh_the_clock(self):
        """The bug: the blind seat kept resetting it, so he never aged."""
        self.b.seen_at["Andre"] = 1000.0
        A.release_stale(self.b, self.c, Scope(""), now=1000.0 + self.stale / 2)
        self.assertEqual(self.b.seen_at["Andre"], 1000.0,
                         "a seat that cannot see must leave the clock alone")

    def test_and_does_not_expire_him_either(self):
        """It has no opinion in EITHER direction -- dropping an aeroplane radar
        simply failed to poll is a separation event."""
        self.b.seen_at["Andre"] = 1000.0
        gone = A.release_stale(self.b, self.c, Scope(""),
                               now=1000.0 + self.stale + 60)
        self.assertEqual(gone, [])
        self.assertIn("Andre", self.c.aircraft)

    def test_the_countdown_survives_a_hiccup_instead_of_resetting(self):
        """The point of the fix: a blind tick in the middle must not buy him
        another full window."""
        self.b.seen_at["Andre"] = 1000.0
        A.release_stale(self.b, self.c, Scope(""), now=1000.0 + self.stale / 2)
        gone = A.release_stale(self.b, self.c, Scope("", ok=True),
                               now=1000.0 + self.stale + 1)
        self.assertEqual(gone, ["Andre"])

    def test_an_entry_nothing_ever_saw_still_ages_out(self):
        """The other half, and the reason the guard is not simply "return
        early when blind". A leftover that was never radar-identified has no
        countdown to preserve -- there was never any evidence to run down -- so
        a blind tick still removes him. Two entries are what makes the
        separation engine engage, which is what makes a leftover dangerous."""
        ac = _AC()
        ac.radar_identified = False
        self.c.aircraft = {"Falcon 1-1": ac}
        self.b.seen_at["Falcon 1-1"] = 1000.0
        gone = A.release_stale(self.b, self.c, Scope(""),
                               now=1000.0 + self.stale + 1)
        self.assertEqual(gone, ["Falcon 1-1"])

    def test_a_seeing_tick_with_an_empty_sky_still_reaps(self):
        """#207 must not regress: an empty sky IS an answer."""
        self.b.seen_at["Andre"] = 1000.0
        gone = A.release_stale(self.b, self.c, Scope("", ok=True),
                               now=1000.0 + self.stale + 1)
        self.assertEqual(gone, ["Andre"])


if __name__ == "__main__":
    unittest.main()
