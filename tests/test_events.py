"""The sim's own account of what happened, instead of our inference.

    "for landing - isn't there a dcs event that we can use to determine if the
     pilot landed or not?"
    "Landing / takeoff event should be triggers to switch to/from tower"
    "Player leaving slot event can clear database for slot association to
     callsign"

[ARCH-3] / #41. Three inferences the sim would simply state, each a threshold
on a continuous quantity standing in for a discrete fact, and each one having
already needed a special case.

The consumer itself lives in the director and needs PostGIS and the gRPC stubs,
so what is tested here is the half that decides BEHAVIOUR: how the picture is
read, and what the bridge does about it.
"""

import unittest

from marshall.atc import agent_atc as A
from marshall.atc import identity
from marshall.core import route as R

DOWN = ("362nd_sockeye [Falcon 1-1] (F-16C_50, manned, on the ground): 0.5 nm "
        "on the 112 radial, 40 ft, heading 216, 8 knots")
AIRBORNE = ("362nd_sockeye [Falcon 1-1] (F-16C_50, manned): 2.0 nm on the 112 "
            "radial, 1,200 ft, heading 216, 220 knots")
ENROUTE = ("362nd_sockeye [Falcon 1-1] (F-16C_50, manned): 8.0 nm on the 300 "
           "radial, 3,000 ft, heading 130, 250 knots")


class _Me:
    def __init__(self, role):
        self.role = role


class TestThePictureCarriesIt(unittest.TestCase):
    def test_on_the_ground_is_read_off_the_scope(self):
        u = identity.units_on(DOWN)[0]
        self.assertTrue(u.on_ground)
        self.assertTrue(u.manned)

    def test_the_airframe_survives_a_third_marker(self):
        """Two markers now ride in the same brackets as the type. The first one
        broke the equipment lookup and told a Mustang it had TACAN; a third
        must not do it again."""
        self.assertEqual(identity.units_on(DOWN)[0].type, "F-16C_50")
        self.assertEqual(A.aircraft_type_on_scope(DOWN, "Falcon 1-1"), "F-16C_50")

    def test_silence_is_not_a_negative(self):
        """False here means EITHER airborne or nothing reported, and the
        difference is why the old inference stays as the fallback."""
        self.assertFalse(identity.units_on(AIRBORNE)[0].on_ground)


class TestTheEventOutranksTheGuess(unittest.TestCase):
    def _ctx(self, scope):
        return A.asr_context(R.BATUMI_ASR, scope, "Falcon 1-1", "362nd_sockeye")

    def test_a_landed_aeroplane_gets_no_guidance(self):
        self.assertEqual(self._ctx(DOWN), "")

    def test_it_beats_the_altitude_and_speed_test(self):
        """The case that proves it is doing the work: 900 feet at 140 knots
        reads as FLYING to the old rule, and the sim says he is down."""
        odd = DOWN.replace("40 ft", "900 ft").replace("8 knots", "140 knots")
        self.assertEqual(self._ctx(odd), "")

    def test_an_airborne_aeroplane_still_gets_guidance(self):
        self.assertTrue(self._ctx(ENROUTE))

    def test_the_old_guess_still_works_when_nothing_was_reported(self):
        """A dropped stream must not resurrect the bug it replaced. The sim
        pauses when empty and a director restart begins knowing nothing."""
        taxi = AIRBORNE.replace("1,200 ft", "45 ft").replace("220 knots", "10 knots")
        self.assertEqual(self._ctx(taxi), "")


class TestTouchingDownEndsTheApproach(unittest.TestCase):
    """A range could never express this: a go-around at half a mile is closer
    than a landing at one, so the two states that most need telling apart are
    exactly the two a distance cannot separate."""

    def _next(self, scope, role):
        return A.handoff_on_the_event(scope, "362nd_sockeye", _Me(role),
                                      R.BATUMI_ASR)

    def test_landing_hands_him_to_tower(self):
        got = self._next(DOWN, "approach")
        self.assertIsNotNone(got)
        self.assertIn("tower", got.name.lower())

    def test_getting_airborne_hands_him_back(self):
        """Only one direction was ever wired, which is how a departing flight
        was given to Approach at twenty-five miles and never handed back."""
        got = self._next(AIRBORNE, "tower")
        self.assertIsNotNone(got)
        self.assertIn("approach", got.name.lower())

    def test_nothing_happens_in_the_middle_of_an_approach(self):
        self.assertIsNone(self._next(ENROUTE, "approach"))

    def test_an_unknown_track_hands_nobody_anywhere(self):
        self.assertIsNone(
            A.handoff_on_the_event(ENROUTE, "", _Me("approach"), R.BATUMI_ASR))
        self.assertIsNone(
            A.handoff_on_the_event(ENROUTE, "somebody-else", _Me("approach"),
                                   R.BATUMI_ASR))


if __name__ == "__main__":
    unittest.main()


class TestZeroIsTheCommonestGroundSpeed(unittest.TestCase):
    """The guard let through the case it most obviously exists for.

    It read `0 < speed < 60`, to stop a MISSING speed being taken as slow. A
    parked aeroplane reports exactly zero, so sitting on the ramp at
    thirty-nine feet he was told he had gone around and to fly the missed
    approach -- the same failure the guard was written to fix, an hour after
    writing it, found by looking at a real radar line rather than a test.

    Below two hundred feet the ambiguity does not arise: nothing in the air at
    that height is doing zero knots.
    """

    RAMP = ("362nd_sockeye (F-16C_50, manned): 0.5 nm on the 116 radial, "
            "39 ft, heading 214, 0 knots")

    def test_a_parked_aeroplane_is_left_alone(self):
        self.assertEqual(
            A.asr_context(R.BATUMI_ASR, self.RAMP, "", "362nd_sockeye"), "")

    def test_a_taxiing_one_still_is(self):
        rolling = self.RAMP.replace("0 knots", "15 knots")
        self.assertEqual(
            A.asr_context(R.BATUMI_ASR, rolling, "", "362nd_sockeye"), "")

    def test_and_flying_slow_and_low_is_still_flying(self):
        """Over the threshold at a hundred and forty knots is not parked."""
        slow = self.RAMP.replace("0 knots", "140 knots")
        self.assertTrue(A.asr_context(R.BATUMI_ASR, slow, "", "362nd_sockeye"))


class TestATouchAndGoIsNotALanding(unittest.TestCase):
    """Caught from a real recording before it was ever reported.

    A landing raised `runway_touch` seventeen seconds before `land`, so the two
    are genuinely different moments -- and a touch-and-go raises the first
    without ever reaching the second. Treating a touch as "down" would hand a
    man flying a low approach to Tower for the seconds until `takeoff` put it
    right, which is the same failure the range rule was just fixed for.
    """

    def test_only_land_means_he_is_staying(self):
        import pathlib
        src = (pathlib.Path(__file__).resolve().parents[1]
               / "director" / "tools" / "events.py").read_text(encoding="utf-8")
        ns: dict = {}
        for line in src.splitlines():
            if line.startswith(("DOWN =", "UP =")):
                exec(line, ns)
        self.assertEqual(ns["DOWN"], ("land",))
        self.assertNotIn("runway_touch", ns["DOWN"])
        self.assertIn("takeoff", ns["UP"])


class TestLeavingTheAeroplaneClearsTheBoard(unittest.TestCase):
    """One stale callsign turned a single-ship approach into a sequencing
    problem between a pilot and his own former self.

    He flew as Falcon 1-1, landed, left the slot. An hour later he came back as
    Pony 1-1 -- and Falcon 1-1 was still on the board. TWO entries are what
    makes the deterministic engine engage, so it began separating him from
    himself: assigned ten thousand, held at five, banished to Kobuleti. Every
    one of those is a correct answer to a question about two aeroplanes, asked
    about one, and all of it went out over vectors that were right.

    The sim had already said so -- `player_leave_unit`, an hour earlier. The
    board simply had no way to hear it.
    """

    def _ctl(self):
        from marshall.atc.controller import Controller
        from marshall.core import route as R2
        c = Controller(R2.BATUMI_ASR)
        c.get("Falcon 1-1")
        c.get("Pony 1-1")
        c.note_radar_contact("Pony 1-1")
        return c

    def test_he_comes_off_the_board(self):
        c = self._ctl()
        self.assertTrue(c.release("Falcon 1-1"))
        self.assertEqual(sorted(c.aircraft), ["Pony 1-1"])

    def test_releasing_twice_is_not_an_error(self):
        """The event may be replayed, and the poll is repeated."""
        c = self._ctl()
        c.release("Falcon 1-1")
        self.assertFalse(c.release("Falcon 1-1"))

    def test_the_letdown_is_freed_if_he_owned_it(self):
        """Otherwise the next arrival queues behind somebody who went home."""
        c = self._ctl()
        c._letdown = "Falcon 1-1"
        c.release("Falcon 1-1")
        self.assertIsNone(c._letdown)

    def test_one_aeroplane_left_means_the_engine_stays_out(self):
        """The whole point. Engagement is `len(aircraft) >= 2`, so removing the
        ghost is what stops a lone pilot being sequenced at all."""
        c = self._ctl()
        c.release("Falcon 1-1")
        self.assertLess(len(c.aircraft), 2)


class TestDownIsNotAGuessAnyMore(unittest.TestCase):
    """"Pretty sure it called me 'down' before the landed event"

    He was right: the goodbye went out nineteen seconds before the sim's own
    `land`, because the trigger was `asr.on_the_ground` -- geometry that reads
    "at the aerodrome, low" and is therefore true in the flare.

    The replacement asks the event first and falls back to altitude AND speed
    together, which cannot fire at a hundred and forty knots.
    """

    FLARE = ("362nd_sockeye [Pony 1-1] (P-51D-30-NA, manned): 0.3 nm on the "
             "116 radial, 60 ft, heading 130, 120 knots")
    STOPPED = ("362nd_sockeye [Pony 1-1] (P-51D-30-NA, manned): 0.4 nm on the "
               "116 radial, 45 ft, heading 130, 5 knots")

    def _pos(self, scope):
        return A.radar_fix_by_track(scope, "362nd_sockeye", R.BATUMI_ASR)

    def test_still_flying_in_the_flare(self):
        self.assertFalse(
            A.is_on_the_ground(self.FLARE, "362nd_sockeye", self._pos(self.FLARE)))

    def test_down_once_he_has_stopped(self):
        self.assertTrue(
            A.is_on_the_ground(self.STOPPED, "362nd_sockeye",
                               self._pos(self.STOPPED)))

    def test_the_event_beats_the_geometry_outright(self):
        """At a hundred and twenty knots the fallback says flying. If the sim
        has said `land`, that wins."""
        said = self.FLARE.replace("manned)", "manned, on the ground)")
        self.assertTrue(
            A.is_on_the_ground(said, "362nd_sockeye", self._pos(said)))


class TestABoardEntryNeedsEvidence(unittest.TestCase):
    """Replaces an event-driven release that misfired live.

    `player_leave_unit` names the UNIT ("Pony 1-1"); the radar picture labels a
    manned contact by PLAYER ("362nd_sockeye"), and that is what identity
    resolves a track to. The two do not join, and matching on the player
    instead released a pilot's live identity every two seconds -- his callsign
    flickered between the one he had an hour ago and the one he was using, and
    the board emptied under a live approach.

    This asks the question that needs no join: is there any evidence this
    aeroplane still exists? It cannot misfire on somebody flying, because
    flying is what the evidence IS.
    """

    def _ctl(self):
        from marshall.atc.controller import Controller
        from marshall.core import route as R2
        c = Controller(R2.BATUMI_ASR)
        c.get("Falcon 1-1")
        c.get("Pony 1-1")
        c.note_radar_contact("Pony 1-1")
        return c

    def test_the_leftover_goes_and_the_live_one_stays(self):
        c = self._ctl()
        A._seen_at.clear()
        A.release_stale(c, "", now=0.0)                 # seed
        gone = A.release_stale(c, "", now=A.STALE_BOARD_SEC + 1)
        self.assertEqual(gone, ["Falcon 1-1"])
        self.assertIn("Pony 1-1", c.aircraft)

    def test_nobody_goes_while_radar_still_sees_him(self):
        c = self._ctl()
        A._seen_at.clear()
        scope = ("Falcon 1-1 (P-51D-30-NA, manned): 4.0 nm on the 300 radial, "
                 "3,000 ft, heading 130, 200 knots")
        A.release_stale(c, scope, now=0.0)
        self.assertEqual(A.release_stale(c, scope, now=A.STALE_BOARD_SEC + 1), [])

    def test_a_recent_transmission_keeps_him(self):
        c = self._ctl()
        A._seen_at.clear()
        A.release_stale(c, "", now=0.0)
        A.note_alive("Falcon 1-1", now=A.STALE_BOARD_SEC)
        self.assertEqual(A.release_stale(c, "", now=A.STALE_BOARD_SEC + 1), [])
