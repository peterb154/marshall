"""Two aircraft, two fields, two approaches, at the same time.

    "One approach profile per flight, not per bridge -- THIS IS THE WALL IN
     FRONT OF MULTIPLE AIRPORTS. Everything else on this list makes one field
     work better; nothing else lets there be a second one."
                                                        -- #2, filed on day one

`Controller` held ONE `profile` and every arrival fact was read off it: the
beacon he homes, the levels in his stack, the runway he is cleared to, his
minima, his missed approach, and the name of the controller working him. That is
correct for one aerodrome and wrong for two -- and not subtly wrong. It is one
aeroplane being given another airport's runway and minima, and every number is
real, so nothing looks wrong until somebody flies it.

The same shape as `station_for` before it took a field, one layer down.

THREE THINGS HAD TO BECOME PER-FLIGHT, not one:

    the numbers      `_pro(ac)` -- the procedure he is actually flying
    the stack        two aerodromes are two stacks. A hold over Nellis and a
                     hold over Tonopah are 120 nm apart and share no airspace
    the letdown      single-occupancy is about ONE approach, not about the
                     bridge. One string meant an aeroplane on the Nellis ILS
                     blocked the approach at Tonopah for no reason anybody
                     could explain on the radio
"""

from __future__ import annotations

import unittest

from marshall.atc import controller as atc
from marshall.core import nevada as N
from marshall.core import route as RT


class TwoFieldsAtOnce(unittest.TestCase):
    """Nellis and Tonopah, worked concurrently by one Controller."""

    def setUp(self):
        # The bridge is started on ONE of them, exactly as it is today.
        self.c = atc.Controller(N.TONOPAH_ILS)
        self.c.t = 0.0
        for cs in ("Home 1", "Away 1"):
            self.c.check_in(cs)
        self.c.assign_approach("Home 1", N.NELLIS_ILS)
        self.c.assign_approach("Away 1", N.TONOPAH_ILS)
        self.home = self.c.aircraft[self.c._resolve("Home 1")]
        self.away = self.c.aircraft[self.c._resolve("Away 1")]

    def test_each_gets_his_own_runway(self):
        """21 at Nellis, 15 at Tonopah. The bridge loaded Tonopah."""
        self.assertEqual(str(self.c._pro(self.home).runway), "21")
        self.assertEqual(str(self.c._pro(self.away).runway), "15")

    def test_and_his_own_minima(self):
        """2,069 ft at Nellis against 5,750 at Tonopah -- the fields are three
        and a half thousand feet apart. Reading one to the other is not a
        rounding error, it is flying an approach into the ground or breaking
        off a mile and a half high."""
        self.assertNotEqual(self.c._pro(self.home).mda_ft,
                            self.c._pro(self.away).mda_ft)
        self.assertEqual(self.c._pro(self.home).mda_ft, N.NELLIS_ILS.mda_ft)

    def test_an_unassigned_aeroplane_still_gets_the_bridges_profile(self):
        """Which is what everything did before, and is right for an aircraft
        nobody has cleared for anything."""
        self.c.check_in("Nobody 1")
        ac = self.c.aircraft[self.c._resolve("Nobody 1")]
        self.assertIs(self.c._pro(ac), N.TONOPAH_ILS)


class TwoStacksDoNotContend(TwoFieldsAtOnce):
    """A hold over Nellis and a hold over Tonopah share no airspace."""

    def test_both_may_hold_at_the_same_level(self):
        self.c.report_beacon("Home 1", 20000)
        self.c.report_beacon("Away 1", 20000)
        # Each is the first arrival at HIS field, so each takes his own bottom.
        self.assertEqual(self.home.assigned_ft, N.NELLIS_ILS.stack_ft[0])
        self.assertEqual(self.away.assigned_ft, N.TONOPAH_ILS.stack_ft[0])

    def test_and_a_second_arrival_stacks_above_his_OWN_field(self):
        self.c.report_beacon("Home 1", 20000)      # cleared at Nellis
        self.c.check_in("Home 2")
        self.c.assign_approach("Home 2", N.NELLIS_ILS)
        self.c.report_beacon("Home 2", 20000)
        two = self.c.aircraft[self.c._resolve("Home 2")]
        self.assertEqual(two.assigned_ft, N.NELLIS_ILS.stack_ft[1],
                         "held above the man on the Nellis approach")

    def test_a_tonopah_arrival_does_not_reserve_a_nellis_level(self):
        """The bug this prevents: an aeroplane on another field's approach
        taking a level out of a stack it will never enter."""
        self.c.report_beacon("Away 1", 20000)      # cleared at Tonopah
        self.c.report_beacon("Home 1", 20000)
        self.assertEqual(self.home.assigned_ft, N.NELLIS_ILS.stack_ft[0],
                         "Nellis's bottom level was reserved by a Tonopah "
                         "aeroplane 120 miles away")


class TwoLetdownsDoNotBlockEachOther(TwoFieldsAtOnce):
    """Single-occupancy is about ONE approach, not about the bridge."""

    def test_both_are_cleared(self):
        self.c.report_beacon("Home 1", 20000)
        self.c.report_beacon("Away 1", 20000)
        self.assertEqual(self.home.phase, atc.Phase.CLEARED)
        self.assertEqual(self.away.phase, atc.Phase.CLEARED,
                         "held behind an approach at another aerodrome")

    def test_and_each_letdown_names_its_own_man(self):
        self.c.report_beacon("Home 1", 20000)
        self.c.report_beacon("Away 1", 20000)
        self.assertEqual(self.c._in_letdown(self.home), "Home 1")
        self.assertEqual(self.c._in_letdown(self.away), "Away 1")

    def test_a_second_arrival_at_ONE_field_still_waits(self):
        """The invariant is not weakened -- it is scoped. Two aircraft on ONE
        approach still contend, which is the whole reason it exists."""
        self.c.report_beacon("Home 1", 20000)
        self.c.check_in("Home 2")
        self.c.assign_approach("Home 2", N.NELLIS_ILS)
        self.c.report_beacon("Home 2", 20000)
        two = self.c.aircraft[self.c._resolve("Home 2")]
        self.assertEqual(two.phase, atc.Phase.HOLDING)
        self.assertEqual(self.c._in_letdown(two), "Home 1")


class TheBoardSaysWhichLetdownHeIsIn(TwoFieldsAtOnce):

    def test_in_letdown_is_per_approach(self):
        self.c.report_beacon("Home 1", 20000)
        self.c.report_beacon("Away 1", 20000)
        rows = {r["callsign"]: r for r in self.c.board()}
        self.assertTrue(rows["Home 1"]["in_letdown"])
        self.assertTrue(rows["Away 1"]["in_letdown"],
                        "the board can only see one letdown again")


if __name__ == "__main__":
    unittest.main()


class TestTheBoardSaysWhichApproach(unittest.TestCase):
    """The one fact answering "which approach am I flying", where a human is.

        "for the cleared_approach - shouldnt that be on the board i am looking
         at? Isnt it in the database?"

    It is. `assigned_plans.approach` has named it since the plans table existed,
    migration 025 put it on the strip, and the bridge read it on EVERY
    transmission -- to look up the profile, and then dropped it. So it existed
    in the database, in the view, in the HTTP response and in a local variable,
    at every layer except the one anybody looks at.

    That is the shape this project keeps finding, one layer further out each
    time: 023 said it about the squawk, 025 rediscovered it about the approach,
    026 about the sortie phase. The lesson each of them wrote down is the same
    -- a fact that stops before the surface is a fact nothing can reach -- and
    this is the fourth time, which is why the assertion is here and not in a
    comment.
    """

    def setUp(self):
        self.ctl = atc.Controller(RT.BATUMI_ASR)
        self.ctl.request_approach("Sockeye")

    def test_assigning_it_puts_it_on_the_board(self):
        self.ctl.assign_approach("Sockeye", RT.KOBULETI_ILS, named="kobuleti-ils")
        row, = [r for r in self.ctl.board() if r["callsign"] == "Sockeye"]
        self.assertEqual(row["cleared_approach"], "kobuleti-ils")

    def test_blank_until_somebody_assigns_one(self):
        # Different from "he is flying the bridge's default", which is what an
        # aeroplane with no assignment actually gets -- and the distinction is
        # invisible from the cockpit any other way.
        row, = [r for r in self.ctl.board() if r["callsign"] == "Sockeye"]
        self.assertEqual(row["cleared_approach"], "")

    def test_it_survives_a_restart(self):
        # The board is a cache of the table (#120), so the name has to come back
        # off the row -- otherwise a bridge restarted mid-approach shows a blank
        # beside an aeroplane it is actively vectoring down an ILS.
        self.ctl.hydrate(
            [{"callsign": "Sockeye", "track_name": "362nd_sockeye",
              "cleared_approach": "kobuleti-ils"}],
            approach_named=lambda k: RT.KOBULETI_ILS if k == "kobuleti-ils" else None)
        row, = [r for r in self.ctl.board() if r["callsign"] == "Sockeye"]
        self.assertEqual(row["cleared_approach"], "kobuleti-ils")
