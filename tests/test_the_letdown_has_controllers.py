"""A bridge on the 1944 flavour had a controller who could name no frequency.

`theatre_stations = false` is the mode switch that keeps a beacon letdown off
the modern ladder, and it was read as "has no controllers at all":

    if procedure is not None and not procedure.theatre_stations:
        return ()

So every role lookup through that procedure answered None. No handoff could be
spoken, no departure frequency issued, and the refusals that name a frequency --
*"Take-off is Tower's, contact Kobuleti Tower one three three decimal zero"* --
lost the half that tells a pilot what to do. The procedure is SELECTABLE and
nobody had flown it, which is the only reason it went unnoticed. [#140]

BOTH OTHER ANSWERS ARE WRONG, and the tempting one is worse than the bug. Giving
it `stations_now()` would tell a Mustang to contact Batumi Tower on 118.6 while
his ARA-8 is homing 132.0 -- a real controller, on a frequency the aeroplane
physically cannot tune, which is the failure shape this project keeps meeting.

WHAT HE ACTUALLY HAS was already in the data, and `Station`'s own docstring says
why it must be:

    "They were the same thing while the approach was a beacon letdown -- the
     controller had to sit on the beacon you were homing, because the ARA-8
     tunes and homes on one frequency at a time."

Each fix a period procedure uses carries the seat that owns its frequency.
INITIAL is Batumi Approach on 128.0, BATUMI is Batumi Tower on 132.0, KOBULETI
is Kobuleti Departure on 124.0. `theatre.beacon_seats` reads them.
"""

from __future__ import annotations

import unittest

from marshall.atc import handoff as H
from marshall.core import theatre as T
from tests import theatre as TH


def letdown():
    got = TH.letdown()
    if got is None or getattr(got, "theatre_stations", True):
        raise unittest.SkipTest(
            f"{TH.name()} publishes no off-ladder letdown, so there is no mode "
            f"switch here to exercise")
    return got


class TestHeCanNameAFrequencyAtAll(unittest.TestCase):
    """The bug, directly: a controller who could say nothing."""

    def setUp(self):
        self.p = letdown()

    def test_the_procedure_staffs_somebody(self):
        self.assertTrue(T.seats_now(self.p),
                        "the 1944 controller has no seats at all, so he can "
                        "speak no handoff and issue no frequency")

    def test_every_seat_carries_a_real_frequency(self):
        for s in T.seats_now(self.p):
            with self.subTest(s.name):
                self.assertTrue(s.freq_mhz)
                self.assertTrue(s.name)

    def test_and_a_role_and_a_field_that_a_lookup_can_use(self):
        """A seat with no role answers no `station_for`, which would be the
        same silence in a different shape."""
        for s in T.seats_now(self.p):
            with self.subTest(s.name):
                self.assertTrue(s.role, f"{s.name} has no role")
                self.assertTrue(s.field, f"{s.name} belongs to no aerodrome")


class TestTheyAreHisBEACONSAndNotTheModernLadder(unittest.TestCase):
    """The half that keeps the period flavour honest."""

    def setUp(self):
        self.p = letdown()
        self.modern = {s.freq_mhz for s in T.stations_now()}

    def test_not_one_of_them_is_a_modern_frequency(self):
        for s in T.seats_now(self.p):
            with self.subTest(s.name):
                self.assertNotIn(
                    s.freq_mhz, self.modern,
                    f"{s.name} was given {s.freq_mhz}, which is on the modern "
                    f"ladder and which an ARA-8 cannot tune")

    def test_a_modern_frequency_resolves_to_NOBODY_through_this_procedure(self):
        """The guard that was always the point of the mode switch."""
        for hz in sorted(self.modern):
            with self.subTest(hz):
                self.assertIsNone(T.station_on(hz, procedure=self.p))

    def test_each_seat_is_a_fix_this_procedure_actually_USES(self):
        """Not any beacon on the map -- the ones he tunes. A seat drawn from a
        fix he never flies to would be a frequency he has no reason to be on."""
        mine = set()
        for attr in ("arrival_fix", "outer_hold", "navaid", "iaf", "aerodrome"):
            f = getattr(self.p, attr, None)
            if f is not None and getattr(f, "sector", ""):
                mine.add((f.sector, f.freq_mhz))
        for s in T.seats_now(self.p):
            with self.subTest(s.name):
                self.assertIn((s.name, s.freq_mhz), mine)

    def test_the_controller_he_answers_as_is_among_them(self):
        """`profile.station()` is the seat and frequency the enroute phase is
        worked on, and it must be one he actually staffs -- otherwise the man
        speaking is not on the list of men who exist."""
        name, hz = self.p.station()
        self.assertIn((name, hz), {(s.name, s.freq_mhz)
                                   for s in T.seats_now(self.p)})


class TestTheLadderCanNowBeSPOKEN(unittest.TestCase):
    """What the seats are FOR: a handoff with a frequency in it."""

    def setUp(self):
        self.p = letdown()
        self.me = T.station_for("approach", field=TH.arrival().name,
                                procedure=self.p)
        if self.me is None:
            self.skipTest("this letdown staffs no approach seat")

    def test_a_landing_is_handed_to_a_tower_with_a_frequency(self):
        got = H.due(self.p, self.me,
                    H.State(on_ground=True, range_nm=0.2, inbound=False,
                            phase="landed"))
        self.assertIsNotNone(got, "nothing hands him over at all")
        self.assertEqual(got.role, "tower")
        self.assertTrue(got.station.freq_mhz,
                        "he is told to contact a controller with no frequency")

    def test_and_it_is_a_frequency_he_can_TUNE(self):
        got = H.due(self.p, self.me,
                    H.State(on_ground=True, range_nm=0.2, inbound=False,
                            phase="landed"))
        self.assertNotIn(got.station.freq_mhz,
                         {s.freq_mhz for s in T.stations_now()})


class TestTheModernProceduresAreUntouched(unittest.TestCase):
    """The switch is one procedure's, and the rest of the map must not move."""

    def test_every_other_approach_still_staffs_the_whole_ladder(self):
        whole = len(T.stations_now())
        self.assertTrue(whole, "this map staffs nobody at all")
        for key, p in T.approaches_now().items():
            if not getattr(p, "theatre_stations", True):
                continue
            with self.subTest(key):
                self.assertEqual(len(T.seats_now(p)), whole)

    def test_and_a_procedure_of_None_is_still_the_whole_ladder(self):
        """Every caller that is not asking about a specific approach."""
        self.assertEqual(len(T.seats_now(None)), len(T.stations_now()))


if __name__ == "__main__":
    unittest.main()
