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


class TestTheBriefSaysWhatIsNotYours(unittest.TestCase):
    """The card calls this the most serious finding it can record: "Ground
    owning the runway is the one thing on an aerodrome that must not be shared."

    On 9 August Kobuleti Ground cleared an aircraft for take-off, was challenged
    by the pilot, and doubled down twice:

        "negative ... there is no separate tower here, I am also your tower,
         cleared for takeoff runway zero seven"
        "negative, Kobuleti has no separate tower, I am Ground and Tower both
         on one two one decimal eight"

    Kobuleti Ground's `also` is empty and the YOUR FIELD block lists Kobuleti
    Tower on 133.000, so the brief already held both facts. It asserted the
    opposite anyway. Every block told the controller what he IS; none told him
    what he is NOT, and the model reasoned its way into the gap.
    """

    def brief(self, station):
        from marshall.atc import agent_atc as A
        from marshall.atc import assembly
        from marshall.core import route as R
        return assembly.compose_message(
            A.Bridge(), scope="", known="Sockeye",
            transcript="ready for departure", profile=R.BATUMI_ASR, me=station,
            fix=None, nxt=None, directive="", stack="", vectoring="",
            _flight={}, _flight_say="", claim="", name_say="")[0]

    def test_a_ground_seat_is_told_the_runway_is_not_his(self):
        from marshall.core import route as R
        for st in (R.KOB_GROUND, R.KOB_CLEARANCE, R.GROUND):
            with self.subTest(who=st.name):
                said = self.brief(st)
                self.assertIn("NOT YOURS: THE RUNWAY", said)
                self.assertIn("do not agree that you are also Tower", said)

    def test_and_told_which_frequency_to_send_him_to(self):
        """Naming only the position leaves him hunting for a number while
        holding short."""
        from marshall.core import route as R
        self.assertIn("Kobuleti Tower", self.brief(R.KOB_GROUND))
        self.assertIn("one three three decimal zero", self.brief(R.KOB_GROUND))

    def test_a_tower_seat_is_not_told_the_runway_is_not_his(self):
        from marshall.core import route as R
        for st in (R.KOB_TOWER, R.TOWER):
            with self.subTest(who=st.name):
                self.assertNotIn("NOT YOURS: THE RUNWAY", self.brief(st))

    def test_the_radar_seat_keeps_its_talkdown_relay(self):
        """On a GCA the radar controller flies the whole approach on his own
        frequency and relays Tower's landing clearance rather than sending a man
        in cloud to another radio. Telling Approach it may not clear a landing
        would break the procedure."""
        from marshall.core import route as R
        self.assertNotIn("NOT YOURS: THE RUNWAY", self.brief(R.APPROACH))

    def test_a_tower_seat_is_told_the_ramp_is_not_his(self):
        """Batumi Tower cleared a pilot to taxi to parking after landing, which
        is Ground's."""
        from marshall.core import route as R
        said = self.brief(R.TOWER)
        self.assertIn("NOT YOURS: THE GROUND", said)
        self.assertIn("one two one decimal nine", said)

    def test_a_field_that_really_does_fold_them_together_says_the_opposite(self):
        """Read off the station table, not written into the prose. A seat whose
        `also` includes tower genuinely owns the runway and must not be told
        otherwise."""
        import dataclasses
        from marshall.core import route as R
        both = dataclasses.replace(R.KOB_GROUND, also=("tower",))
        self.assertNotIn("NOT YOURS: THE RUNWAY", self.brief(both))


class AReadBackIsATransmissionTheSystemCanHear(unittest.TestCase):
    """The fifth ground intent, and it was missing.

    `Controller.clearance_read_back` has existed since the ground procedure was
    written, with a docstring calling it *"the transition, not the words"* --
    and nothing on the radio path could ever call it, because the taxonomy had
    no way to say "he read something back". Only these tests reached it.

    So a read-back was filed as a check-in, the controller answered *"advise you
    have information Alpha"* to a man reciting a squawk, and Delivery could
    never finish with him. Live, twice, on 10 August:

        "Clearance did not hand me off to ground"

    Exactly the failure `intents.py` already describes for holding short --
    *"classified as check_in or unknown, so the controller heard 'somebody said
    something' and the phase never moved"* -- in the transmission that happens
    on every IFR flight.
    """

    def setUp(self):
        from marshall.atc import controller as atc, intents
        from marshall.core import route as R
        self.intents = intents
        self.ctl = atc.Controller(R.BATUMI_ASR)
        self.ctl.check_in("Sockeye 1-1")
        self.ctl.out.clear()

    def fire(self, correct):
        i = self.intents.Intent(self.intents.IntentKind.READ_BACK,
                                "Sockeye 1-1", correct=correct)
        self.intents.dispatch(self.ctl, i)
        return self.ctl.get("Sockeye 1-1")

    def test_the_kind_exists(self):
        self.assertTrue(hasattr(self.intents.IntentKind, "READ_BACK"))

    def test_a_correct_read_back_ends_delivery_s_business(self):
        self.assertEqual(self.fire(True).sortie_phase, "taxi")

    def test_a_wrong_one_leaves_him_where_he_is(self):
        # "He does not move until the numbers agree" -- the whole point of
        # reading it back.
        before = self.ctl.get("Sockeye 1-1").sortie_phase
        self.assertEqual(self.fire(False).sortie_phase, before)

    def test_an_UNJUDGED_read_back_leaves_him_where_he_is(self):
        """None is not False, and it is not True either.

        None means nothing could judge it -- no clearance on the board to
        compare against. Treating that as correct would hand a pilot to Ground
        in the same breath as being told his squawk is wrong, which is exactly
        the transmission that happened on 10 August.
        """
        before = self.ctl.get("Sockeye 1-1").sortie_phase
        self.assertEqual(self.fire(None).sortie_phase, before)

    def test_the_classifier_is_told_about_it(self):
        # A kind the schema does not describe is a kind the model cannot return.
        schema = str(self.intents.SCHEMA if hasattr(self.intents, "SCHEMA")
                     else self.intents.__dict__)
        self.assertIn("read_back", schema)


class TheReadBackIsJudgedAgainstTheClearance(unittest.TestCase):
    """One verifier, both directions.

    `decision.verify` asks whether every fact of a decision survived being
    spoken. A read-back is that question with the speakers swapped, so it is the
    same function -- not a second opinion, and not a model asked "was that
    correct?", which would answer confidently either way and decide whether an
    aircraft changes controller.
    """

    def clearance(self):
        from marshall.atc import decision as D
        return D.Decision(kind="clearance", to="Sockeye 1-1", altitude_ft=5000,
                          frequency_mhz=123.3, squawk="6521")

    def test_the_real_wrong_read_back_is_caught(self):
        # 10 August, verbatim: altitude and frequency right, squawk wrong.
        # Anything short of the WHOLE clearance would have called this correct
        # and handed him on mid-correction.
        from marshall.atc import decision as D
        said = ("cleared to Batumi as filed, climb maintain 5000, "
                "squawk 1256, frequencies 123.3")
        self.assertEqual(D.verify(self.clearance(), said), ["six five two one"])

    def test_the_corrected_read_back_passes(self):
        from marshall.atc import decision as D
        said = ("cleared to Batumi, maintain five thousand, departure one two "
                "three decimal three, squawk six five two one")
        self.assertEqual(D.verify(self.clearance(), said), [])

    def test_digits_are_the_same_clearance(self):
        from marshall.atc import decision as D
        self.assertEqual(
            D.verify(self.clearance(), "Batumi, 5000, 123.3, squawk 6521"), [])

    def test_a_squawk_is_spoken_digit_by_digit(self):
        from marshall.core import say
        self.assertEqual(say.spell_squawk("6521"), "six five two one")
        self.assertEqual(say.spell_squawk(6521), "six five two one")

    def test_no_clearance_on_the_board_means_no_judgement(self):
        from marshall.atc import agent_atc
        b = agent_atc.Bridge()
        self.assertIsNone(agent_atc._read_back_correct(b, "Sockeye 1-1", "anything"))


class TheAtisLetterCrossesTheSeam(unittest.TestCase):
    """A directive the engine issued can still vanish, if it carries no decision.

        "he never once said 'advise you have information alpha'"

    The engine asked on three consecutive transmissions and the agent dropped it
    every time, silently -- because the check-in path composes PROSE, and only a
    `Decision` is verified. #79 built the mechanism; this path did not use it.
    """

    def test_the_letter_is_a_fact_the_verifier_checks(self):
        from marshall.atc import decision as D
        d = D.Decision(kind="advise_atis", to="Sockeye 1-1", atis_letter="Alpha")
        self.assertEqual(D.verify(d, "Sockeye, say your request."),
                         ["information Alpha"])
        self.assertEqual(
            D.verify(d, "Sockeye, advise you have information Alpha."), [])

    def test_a_dropped_letter_is_restored(self):
        from marshall.atc import decision as D
        d = D.Decision(kind="advise_atis", to="Sockeye 1-1", atis_letter="Alpha")
        self.assertIn("information Alpha", D.repair(d, "Sockeye, go ahead."))

    def test_check_in_attaches_it(self):
        import unittest.mock as mock
        from marshall.atc import controller as atc
        from marshall.atis import store
        from marshall.core import route as R
        c = atc.Controller(R.BATUMI_ASR)
        with mock.patch.object(store, "current",
                               return_value=mock.Mock(on_the_air=True,
                                                      letter="Alpha")):
            c.check_in("Sockeye 1-1")
        kinds = [t.decision.kind for t in c.take_out() if t.decision]
        self.assertIn("advise_atis", kinds)

    def test_no_broadcast_means_no_decision(self):
        # Asking a pilot to confirm an ATIS that does not exist is how you get a
        # confused read-back; a decision with no letter would be worse still.
        import unittest.mock as mock
        from marshall.atc import controller as atc
        from marshall.atis import store
        from marshall.core import route as R
        c = atc.Controller(R.BATUMI_ASR)
        with mock.patch.object(store, "current",
                               return_value=mock.Mock(on_the_air=False,
                                                      letter="")):
            c.check_in("Sockeye 1-1")
        self.assertEqual([t.decision for t in c.take_out() if t.decision], [])


class TheClearanceIsReadFromTheBoardNotACacheATurnBehind(unittest.TestCase):
    """The read-back had nothing to be judged against on the turn it happened.

        "after getting clearance, I did not get switched over to ground"

    The clearance facts were cached from the flight row AFTER `decide` had run,
    and the clearance itself is assigned by the agent's tool LATER STILL. So on
    the turn the clearance goes out, the row has no level and no squawk yet and
    the cache stays empty -- and the read-back on the very NEXT transmission
    found nothing, returned None, and left the phase alone. Clearance could
    never let go.

    Every piece worked in isolation: the intent classified as READ_BACK, the
    squawk was on the board, the verifier judged correctly. They were one turn
    out of step.
    """

    def test_the_lookup_does_not_depend_on_the_cache(self):
        import inspect
        from marshall.atc import agent_atc
        src = inspect.getsource(agent_atc._read_back_correct)
        self.assertIn("_cleared_plan_now(known)", src,
                      "it still trusts a cache that is filled a turn late")

    def test_a_missing_board_is_no_judgement_rather_than_a_wrong_one(self):
        from marshall.atc import agent_atc
        self.assertEqual(agent_atc._cleared_plan_now(""), {})

    def test_the_classifier_knows_the_kind(self):
        # Belt and braces on the taxonomy: a kind the schema does not describe
        # is a kind the model cannot return, and this one was missing entirely.
        from pathlib import Path as _P
        src = (_P(__file__).resolve().parent.parent / "src" / "marshall" /
               "atc" / "intents.py").read_text()
        self.assertIn("read_back: REPEATING something he was just given", src)
