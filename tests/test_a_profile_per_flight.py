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

    def test_an_unassigned_aeroplane_falls_back_to_whatever_the_radio_holds(self):
        """THE BEHAVIOUR BEING RETIRED, kept as one test and named as such.

        This used to be called `..._still_gets_the_bridges_profile` and read as
        an endorsement. It is not one. `_pro` falling back to `self.profile` is
        a transitional arrangement with an issue against it: there is no such
        thing as the theatre's approach, a pilot flies the one his CLEARANCE
        names, and #162 step 1 deletes the `default_approach` that fills this
        slot. What survives after that is `None`, which is what
        `AControllerWithNoArrivalAtAll` below asserts.

        Kept rather than deleted for one reason -- it is still the behaviour,
        and a test that stops matching the code silently is worse than one that
        is honest about being temporary. The pair of them is the whole state of
        the migration: the fallback works, and the absence of it works too.
        """
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


class AControllerWithNoArrivalAtAll(unittest.TestCase):
    """`Controller()`. No profile. THE CRITERION #2 DID NOT HAVE. [#162]

        "I don't understand what this whole business about a theater default
         approach is. There should be no such thing"

    #2 was marked FIXED on 11 August with all four of its acceptance criteria
    met, and it was 2 call sites out of 28. Every criterion was about whether a
    FLIGHT gets its own profile, and one does; none of them asks what fraction
    of the code reads it. So the mechanism landed beside the singleton it was
    meant to replace and satisfied the lot -- which is the finding worth
    generalising: **a criterion a parallel implementation can satisfy does not
    retire the thing it was replacing.**

    This is the one that cannot be satisfied in parallel. It does not count
    call sites and it does not grep; it removes the radio-wide profile
    entirely, and then asks whether a controller still works. Nothing
    radio-wide can be being consulted if there is nothing radio-wide to
    consult, and no amount of `Aircraft.profile` beside a live `self.profile`
    will make it pass.

    WHAT MUST WORK IS EVERYTHING THAT IS NOT AN APPROACH, which is most of a
    sortie: the whole ground ladder from clearance to the stand, the enroute
    greeting, the runway in use, the wind, refusing a clearance that is not
    this seat's, and the channel every one of those goes out on. An approach is
    the one thing that genuinely needs a procedure, because a procedure is what
    an approach IS.

    WHAT MUST NOT HAPPEN IS AN INVENTED NUMBER. A missing procedure is not a
    reason to read the dataclass's defaults back out as though they were data
    -- 180 and one minute belong to a procedure that declined to say, not to
    the absence of one. #109 settled this for a picture with no origin and it
    is the same rule here: a value with no owner renders NOTHING. A heading
    invented for a hold is a real heading over real terrain.
    """

    def setUp(self):
        self.c = atc.Controller()
        self.assertIsNone(self.c.profile, "the fixture is the point of it")

    # -- it comes up at all ------------------------------------------------
    def test_it_constructs_with_no_arguments(self):
        self.assertEqual(atc.Controller().aircraft, {})

    def test_an_aeroplane_nobody_cleared_has_no_procedure(self):
        self.c.check_in("Pony 1-1")
        ac = self.c.aircraft[self.c._resolve("Pony 1-1")]
        self.assertIsNone(self.c._pro(ac),
                          "there is no such thing as the theatre's approach")

    # -- the whole ground ladder, which is where a sortie starts and ends ---
    def test_the_ground_ladder_runs_end_to_end(self):
        """Clearance, taxi, hold short, take-off, landing, roll-out, stand.

        Driven as a pilot drives it, through the public entry points, because
        the question is whether a CONTROLLER works rather than whether a method
        does. Nothing here is an approach and nothing here needs one.
        """
        self.c.check_in("Pony 1-1")
        for step, args in (("request_clearance", ()),
                           ("clearance_read_back", (True,)),
                           ("request_taxi", ()),
                           ("report_holding_short", ()),
                           ("request_takeoff", ()),
                           ("report_landed", ()),
                           ("report_down", ()),
                           ("taxi_in", ())):
            with self.subTest(step):
                getattr(self.c, step)("Pony 1-1", *args)
        self.assertEqual(self.c.anomalies, [])
        said = " ".join(tx.text for tx in self.c.out)
        self.assertIn("taxi to runway", said)
        self.assertIn("cleared for take-off", said)
        self.assertIn("taxi to parking", said)

    def test_the_runway_and_the_wind_come_off_the_broadcast(self):
        """Neither is the profile's, and neither ever was -- they belong to the
        field the speaking controller is at.

        SO THERE HAS TO BE ONE. This asked with no profile AND no seat, and was
        answered because both lookups fell back to `ARRIVAL_FIELD` -- the
        literal "Batumi", which is a real aerodrome on one map and nothing at
        all on the other (#162, #137). The seat is what names the field, and
        the live bridge always has one: `_me` comes off the frequency the
        transmission arrived on.
        """
        self.c._me = RT.KOB_TOWER
        self.assertNotIn("in use", self.c._runway_in_use())
        self.assertIn("wind", self.c._wind_phrase())

    def test_and_with_no_seat_the_runway_is_not_named_from_a_literal(self):
        """The complement. No arrival and no seat is no aerodrome, and the
        runway in use at an aerodrome nobody named is not a thing that can be
        said -- "in use" commits to nothing, which is what a controller says
        when the runway is not his to name."""
        self.assertEqual("in use", self.c._runway_in_use())
        self.assertIn("wind", self.c._wind_phrase(),
                      "he is still answered; the wind is simply not a field's")

    def test_a_transmission_still_has_a_channel(self):
        """`say` chose the frequency off the radio's arrival. A comms ladder
        belongs to the MAP -- you do not need an arrival to be told who works
        Tower -- so it comes off the theatre and the aeroplane is still
        reachable.

        BUT A LADDER IS LOOKED UP AT AN AERODROME, which is what this asked
        for without saying so. It used to be answered at `ARRIVAL_FIELD`, a
        module constant, so a seatless controller with no arrival named Batumi
        Tower on a map that may not have one -- see #162 and the sibling test
        below. The seat is the aerodrome here, and the live bridge always has
        one: `_me` is set from the frequency the transmission arrived on.
        """
        self.c._me = RT.KOB_TOWER
        self.c.check_in("Pony 1-1")
        self.assertTrue(all(tx.freq_mhz for tx in self.c.out))
        self.assertTrue(all(tx.controller for tx in self.c.out))
        for tx in self.c.out:
            with self.subTest(tx.text):
                # His, or nobody's -- `role_at`'s own rule. A Center owns a
                # region and is reachable from anywhere; ANOTHER AERODROME's
                # seat is never an answer, and used to be the only answer.
                self.assertIn(RT.station_on(tx.freq_mhz).field, ("Kobuleti", ""),
                              "his own field's ladder, not the other one's")

    def test_and_with_no_seat_either_no_aerodrome_is_invented(self):
        """The complement, and the reason the one above needed a seat.

        No arrival and no seat is no aerodrome at all, and a comms ladder
        cannot be read without one -- "who works Tower" has as many answers as
        the map has fields. The old answer was Batumi's, from a constant, and
        it was a REAL controller on a REAL frequency at the wrong airport,
        which is the failure shape that cannot announce itself. Zero is what
        `Tx` has always carried for "not decided". [#109 #162]
        """
        self.assertIsNone(self.c._me if hasattr(self.c, "_me") else None)
        self.c.check_in("Pony 1-1")
        self.assertTrue(self.c.out, "he is still answered")
        self.assertEqual([0.0], sorted({tx.freq_mhz for tx in self.c.out}))
        self.assertEqual([""], sorted({tx.controller for tx in self.c.out}))
        self.assertNotIn(", ,", " ".join(tx.text for tx in self.c.out))

    def test_a_clearance_that_is_not_his_is_still_refused(self):
        """The aerodrome half of the invariant does not need a procedure: only
        Tower puts an aeroplane on a runway, whatever anybody is flying."""
        self.c._me = RT.KOB_GROUND
        self.c.check_in("Pony 1-1")
        self.c.request_takeoff("Pony 1-1")
        self.assertIn("Tower's", " ".join(tx.text for tx in self.c.out))

    # -- and the separation engine, which is this file's whole job ----------
    def test_nobody_is_stacked_on_levels_that_do_not_exist(self):
        """AN APPROACH IS THE ONE THING THAT GENUINELY NEEDS A PROCEDURE, and
        the engine says so out loud instead of guessing.

        A holding stack is `stack_ft` -- published levels above one aerodrome.
        With no arrival there are none, so there is nothing to sequence anybody
        into, and the honest answer is the one a real controller gives: no
        holding available, remain clear. Two aircraft, two refusals, nobody
        assigned an altitude and nobody cleared.

        The alternative is the whole reason this test exists. Inventing a stack
        would put two aeroplanes on levels no chart supports, over a field
        nobody named, and it would LOOK exactly like working separation.
        """
        for cs in ("Pony 1-1", "Pony 2-1"):
            self.c.check_in(cs)
            self.c.note_radar_contact(cs, True)
            self.c.report_beacon(cs, 6000)
        for ac in self.c.aircraft.values():
            with self.subTest(ac.callsign):
                self.assertIsNone(ac.assigned_ft)
                self.assertNotEqual(ac.phase, atc.Phase.CLEARED)
        self.assertEqual(self.c._letdown_by, {})
        self.assertEqual(
            2, " ".join(tx.text for tx in self.c.out).count("no holding available"),
            "a refusal that is not said is indistinguishable from a hold")

    def test_a_go_around_still_gets_a_climb_and_no_altitude(self):
        """The climb is the controller's and goes out; the missed-approach
        altitude is the chart's and there is no chart."""
        self.c.check_in("Pony 1-1")
        self.c.report_missed("Pony 1-1")
        said = " ".join(tx.text for tx in self.c.out)
        self.assertIn("climb", said)
        self.assertIn("say your intentions", said)
        self.assertNotIn("thousand", said)

    # -- nothing is invented -----------------------------------------------
    def test_the_hold_carries_a_LEVEL_and_no_racetrack(self):
        """The level is the engine's and keeps him off the others. The heading
        and the leg time are published geometry at a field, and there is no
        field -- so they are not said, rather than said from a default."""
        said = self.c._hold_phrase(None, 6000)
        self.assertIn("six thousand", said)
        for invented in ("outbound", "inbound", "turns", "one eight zero"):
            with self.subTest(invented):
                self.assertNotIn(invented, said)

    def test_no_navaid_is_named_anywhere(self):
        """A fix nobody published is a real place a pilot can be sent to."""
        self.c.check_in("Pony 1-1")
        self.c.note_radar_contact("Pony 1-1", True)
        self.c.report_beacon("Pony 1-1", 6000)
        self.c.report_missed("Pony 1-1")
        said = " ".join(tx.text for tx in self.c.out)
        for fix in ("BATUMI", "KOBULETI", "INITIAL", "NELLIS", "TONOPAH"):
            with self.subTest(fix):
                self.assertNotIn(fix, said)

    def test_he_is_not_cleared_for_a_1944_letdown_by_default(self):
        """The fallback said "beacon approach", which is the over-fit this
        whole issue is about arriving through a default."""
        self.assertEqual(self.c._approach_name(None), "approach")

    def test_an_anonymous_controller_does_not_introduce_himself(self):
        """And does not leave the comma behind either -- "Pony one one, ,
        report position" is what a format string does with an empty slot."""
        self.assertEqual(self.c._introduce(None), "")
        self.c.check_in("Pony 1-1")
        self.c.note_radar_contact("Pony 1-1", True)
        self.c.report_beacon("Pony 1-1", 6000)
        self.c.tick(atc.REPORT_OVERDUE_SEC + 1)
        self.assertNotIn(", ,", " ".join(tx.text for tx in self.c.out))


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
        self.ctl.assign_approach("Sockeye", RT.KOBULETI_ILS, named="kobuleti-ils-07")
        row, = [r for r in self.ctl.board() if r["callsign"] == "Sockeye"]
        self.assertEqual(row["cleared_approach"], "kobuleti-ils-07")

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
              "cleared_approach": "kobuleti-ils-07"}],
            approach_named=lambda k: RT.KOBULETI_ILS if k == "kobuleti-ils-07" else None)
        row, = [r for r in self.ctl.board() if r["callsign"] == "Sockeye"]
        self.assertEqual(row["cleared_approach"], "kobuleti-ils-07")
