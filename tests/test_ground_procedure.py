"""The ground half of a sortie, and who is allowed to say what.

    "Clearance should handoff to ground for taxi clearance. Ground should clear
     to the runway only, telling them to hold short of the runway. Once they
     check in and report holding short they should be handed off to tower.
     Ground should not clear for takeoff. That's tower."

NONE OF THIS IS GEOMETRY, which is why it is here rather than in the handoff
rules. Two aircraft parked side by side, one waiting for a clearance and one
waiting for the runway, are the same range and the same direction and belong to
different controllers. A distance cannot see the difference and never could.

So the transitions are PHASE ownership -- a phase with no geometry is owned
outright by the controller the phase table names, and moving into it IS the
handoff. The tests below are the procedure walked in order, plus the two
refusals, which are the part that matters: a controller who answers for a
clearance that is not his is not being helpful.
"""

import unittest

from marshall.atc import controller as atc
from marshall.atc import handoff as H
from marshall.atc import intents as I
from marshall.atc import phases as PH
from marshall.core import route as R

P = R.BATUMI_ASR
DEP = R.DEPARTURE_FIELD


def station(name):
    return next(s for s in P.stations if s.name == name)


class GroundCase(unittest.TestCase):
    def setUp(self):
        self.ctl = atc.Controller(P)
        self.ctl.t = 0.0

    def turn(self, station_name, kind):
        """One transmission, on one frequency, and what follows from it."""
        me = station(station_name)
        self.ctl._me = me
        self.ctl.out.clear()
        I.dispatch(self.ctl, I.Intent(kind=kind, callsign="Sockeye"))
        ac = self.ctl.aircraft[self.ctl._resolve("Sockeye")]
        v = H.due(P, me, H.State(True, 0.3, False, phase=ac.sortie_phase))
        nxt = None if (v is None or v.same_station) else v.station.name
        said = " | ".join(t.text for t in self.ctl.out)
        return ac.sortie_phase, nxt, said


class TestTheLadderDownToTheRunway(GroundCase):
    """Clearance, Ground, Tower -- in that order and no other."""

    def test_clearance_keeps_him_until_the_readback(self):
        phase, nxt, _ = self.turn("Kobuleti Clearance",
                                  I.IntentKind.REQUEST_CLEARANCE)
        self.assertEqual(phase, "clearance")
        self.assertIsNone(nxt, "handed on before the clearance was read back")

    def test_a_correct_readback_hands_him_to_ground(self):
        self.turn("Kobuleti Clearance", I.IntentKind.REQUEST_CLEARANCE)
        self.ctl.clearance_read_back("Sockeye", correct=True)
        ac = self.ctl.aircraft[self.ctl._resolve("Sockeye")]
        self.assertEqual(ac.sortie_phase, "taxi")
        v = H.due(P, station("Kobuleti Clearance"),
                  H.State(True, 0.3, False, phase=ac.sortie_phase))
        self.assertEqual(v.station.name, "Kobuleti Ground")

    def test_A_WRONG_READBACK_MOVES_NOBODY(self):
        """The whole point of reading it back. He does not go anywhere until
        the numbers agree, and a controller who hands him on regardless has
        turned the read-back into a formality."""
        self.turn("Kobuleti Clearance", I.IntentKind.REQUEST_CLEARANCE)
        self.ctl.clearance_read_back("Sockeye", correct=False)
        ac = self.ctl.aircraft[self.ctl._resolve("Sockeye")]
        self.assertEqual(ac.sortie_phase, "clearance")
        self.assertIsNone(H.due(P, station("Kobuleti Clearance"),
                                H.State(True, 0.3, False,
                                        phase=ac.sortie_phase)))

    def test_ground_clears_him_to_the_runway_and_says_hold_short(self):
        _, _, said = self.turn("Kobuleti Ground", I.IntentKind.REQUEST_TAXI)
        self.assertIn("taxi to runway", said.lower())
        self.assertIn("hold short", said.lower())

    def test_reporting_holding_short_hands_him_to_tower(self):
        phase, nxt, _ = self.turn("Kobuleti Ground",
                                  I.IntentKind.REPORT_HOLDING_SHORT)
        self.assertEqual(phase, "holding_short")
        self.assertEqual(nxt, "Kobuleti Tower")

    def test_tower_clears_the_take_off(self):
        phase, _, said = self.turn("Kobuleti Tower",
                                   I.IntentKind.REQUEST_TAKEOFF)
        self.assertEqual(phase, "departure")
        self.assertIn("cleared for take-off", said.lower())


class TestNobodyIssuesSomebodyElsesClearance(GroundCase):
    """The half that is separation rather than tidiness.

    The runway is one controller's. A ground controller who answers a take-off
    request is not being helpful -- he is issuing a clearance that is not his,
    and on a real aerodrome that is how two aeroplanes end up on one strip.
    """

    def test_GROUND_MAY_NOT_CLEAR_A_TAKE_OFF(self):
        _, _, said = self.turn("Kobuleti Ground", I.IntentKind.REQUEST_TAKEOFF)
        self.assertNotIn("cleared for take-off", said.lower())
        self.assertIn("tower", said.lower())

    def test_and_he_says_which_frequency(self):
        """Naming the position alone leaves a taxiing pilot hunting for a
        number. The frequency is what makes it a handoff rather than a hint."""
        _, _, said = self.turn("Kobuleti Ground", I.IntentKind.REQUEST_TAKEOFF)
        self.assertIn("one three three", said)

    def test_clearance_does_not_issue_taxi(self):
        _, _, said = self.turn("Kobuleti Clearance", I.IntentKind.REQUEST_TAXI)
        self.assertNotIn("taxi to runway", said.lower())
        self.assertIn("ground", said.lower())

    def test_a_seat_that_covers_both_may_do_both(self):
        """A field that genuinely combines them is legal -- what is not legal
        is one that does not, doing it anyway. Batumi Ground covers clearance
        and delivery, so a clearance request is his."""
        self.assertIn("clearance", R.GROUND.also)
        self.ctl._me = R.GROUND
        self.assertTrue(self.ctl._owns("clearance"))
        self.assertFalse(self.ctl._owns("tower"))

    def test_an_engine_that_was_not_told_who_it_is_still_works(self):
        """`_me` is None in the dry runs and the unit tests. The engine is
        blind by design and must not start refusing work because nobody told
        it which seat it is sitting in."""
        self.ctl._me = None
        self.assertTrue(self.ctl._owns("tower"))
        self.assertTrue(self.ctl._owns("ground"))


class TestTheRunwayIsTheFIELDS(GroundCase):
    """Read from the field, computed from the wind, said the same way twice."""

    def test_ground_and_tower_name_the_same_runway(self):
        """A taxi instruction and a take-off clearance that disagree is a jet
        lined up on the wrong strip."""
        _, _, taxi = self.turn("Kobuleti Ground", I.IntentKind.REQUEST_TAXI)
        _, _, dep = self.turn("Kobuleti Tower", I.IntentKind.REQUEST_TAKEOFF)
        rwy = atc.spell_rwy(R.KOBULETI_FIELD.runway_in_use())
        self.assertIn(rwy, taxi)
        self.assertIn(rwy, dep)

    def test_it_is_the_departure_fields_runway_not_the_profiles(self):
        """The profile describes the approach at the OTHER end of the route and
        its runway is 13. A jet at Kobuleti must not be sent to it."""
        _, _, taxi = self.turn("Kobuleti Ground", I.IntentKind.REQUEST_TAXI)
        self.assertIn(atc.spell_rwy(7), taxi)
        self.assertNotIn(atc.spell_rwy(13), taxi)


class TestItIsSaidTheWayItIsSaid(unittest.TestCase):
    """It goes over a radio, through text to speech."""

    def test_a_runway_is_two_digits_spoken_singly(self):
        self.assertEqual(atc.spell_rwy(7), "zero seven")
        self.assertEqual(atc.spell_rwy(13), "one three")
        self.assertEqual(atc.spell_rwy(31), "three one")

    def test_a_wind_speed_is_a_number_and_not_a_bearing(self):
        """"wind zero nine zero at zero five" is five knots dressed as a
        heading. A direction is three digits; a speed is a quantity."""
        self.assertEqual(atc.spell_count(6), "six")
        self.assertEqual(atc.spell_count(5), "five")

    def test_the_wind_phrase_says_both_correctly(self):
        said = atc.Controller(P)._wind_phrase()
        self.assertIn("zero nine zero", said)
        self.assertNotIn("at zero", said)


class TestThePhaseTableIsCoherent(unittest.TestCase):
    """The procedure is data, so the data has to hold together."""

    def test_the_ground_phases_have_no_geometry(self):
        """Which is what makes phase ownership safe for them. A phase that aims
        at something must be handed over by distance instead."""
        for name in ("clearance", "taxi", "holding_short", "landed"):
            with self.subTest(phase=name):
                self.assertEqual(PH.get(name).aims_at, "none")

    def test_the_departure_walks_clearance_ground_tower(self):
        self.assertEqual(PH.owner_of("clearance"), "delivery")
        self.assertEqual(PH.owner_of("taxi"), "ground")
        self.assertEqual(PH.owner_of("holding_short"), "tower")
        self.assertIn("holding_short", PH.get("taxi").follows)
        self.assertIn("departure", PH.get("holding_short").follows)

    def test_ground_never_leads_straight_to_departure(self):
        """It used to. `taxi` followed `departure` directly, so the model said
        Ground handed a jet to the radar controller and the runway had no owner
        at all in between."""
        self.assertNotIn("departure", PH.get("taxi").follows)

    def test_every_phase_leads_somewhere_real(self):
        for name, p in PH.PHASES.items():
            for nxt in p.follows:
                with self.subTest(phase=name, follows=nxt):
                    self.assertIsNotNone(PH.get(nxt),
                                         f"{name} follows unknown {nxt!r}")

    def test_every_ground_phase_is_staffed_at_the_departure_field(self):
        """A phase whose owner nobody staffs is an aeroplane with nowhere to
        go, and it would strand him on the ramp rather than in the air."""
        for name in ("clearance", "taxi", "holding_short"):
            with self.subTest(phase=name):
                self.assertIsNotNone(
                    P.station_for(PH.owner_of(name), field=DEP),
                    f"nobody at {DEP} works {name}")


if __name__ == "__main__":
    unittest.main()


class TestAParkedAeroplaneHasNoApproachGeometry(unittest.TestCase):
    """Found live, 9 August, on the Kobuleti ramp.

    `asr.guide` answers where an aircraft is on the letdown. Asked about a jet
    parked on a ramp -- 65 ft, 0 knots, a few hundred yards from the field -- it
    answers "map": through the missed approach point, below minimums, past the
    threshold. Every number true, nothing about it true of the aeroplane.

    `reconcile` reads that phase and suppresses the engine's directive, so the
    deterministic TAXI CLEARANCE was dropped while he sat on the ramp and the
    agent improvised one instead. It happened to say runway zero seven, which is
    correct, and it was correct by luck -- nothing had handed it a runway.

    `asr_context` has guarded exactly this since a pilot "sitting on the ramp at
    thirty-nine feet was told he had gone around and to fly the missed
    approach". The guard was one function; this path did not call it.
    """

    def pos(self, alt_ft, speed_kt, range_nm):
        """The REAL Position, not a stub. A stub with the three fields this
        test cares about passes the ground case and then explodes in the
        geometry, which is a test that only exercises its own happy path."""
        from marshall.atc.geometry import Position
        return Position(range_nm=range_nm, radial_deg=125.0, alt_ft=alt_ft,
                        heading_deg=305.0, speed_kt=speed_kt)

    def settle(self, pos, phase=""):
        """`ctl` is real now, because the phase is what decides whether any
        geometry is flown at all -- see `phases.derive`. Passing None meant
        "no controller", which since 9 August correctly means "no idea what
        phase he is in" and therefore no guidance."""
        from marshall.atc import agent_atc as A
        from marshall.atc import controller as C
        from marshall.core import route as R
        ctl = C.Controller(R.BATUMI_ASR)
        ac = ctl.get("Sockeye")
        ac.sortie_phase = phase
        return A.settle(A.Bridge(), "taxi to runway zero seven", "", "",
                        pos, R.BATUMI_ASR, "Sockeye", ctl, scope="", track="")

    def test_a_jet_on_the_ramp_gets_no_guidance_and_keeps_its_clearance(self):
        directive, _stack, _v, guide, dropped = self.settle(
            self.pos(alt_ft=65, speed_kt=0, range_nm=0.3), phase="taxi")
        self.assertIsNone(guide, "approach geometry was computed on the ramp")
        self.assertEqual(dropped, "", f"something was suppressed: {dropped}")
        self.assertIn("zero seven", directive,
                      "the engine's taxi clearance was dropped on the ground")

    def test_an_aeroplane_actually_flying_the_approach_still_gets_guidance(self):
        """The guard must not cost the case it sits next to. Same low altitude,
        but moving, and further out."""
        _d, _s, _v, guide, _dropped = self.settle(
            self.pos(alt_ft=1200, speed_kt=180, range_nm=6.0), phase="approach")
        self.assertIsNotNone(guide, "guidance was suppressed for a live approach")


if __name__ == "__main__":
    unittest.main()
