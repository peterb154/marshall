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
        """None, and no missed elements -- a man who has not been cleared has
        nothing to have got wrong. `verify` returns WHICH facts went missing and
        that list now travels with the verdict, so the engine can name them
        instead of the agent guessing which element was fumbled."""
        from marshall.atc import agent_atc
        b = agent_atc.Bridge()
        ok, missed = agent_atc._read_back_correct(b, "Sockeye 1-1", "anything")
        self.assertIsNone(ok)
        self.assertEqual(missed, [])


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


class ReadingBackTheTaxiClearanceIsNotArrivingAtTheHold(unittest.TestCase):
    """Ground handed him to Tower twice, while he was still moving.

        "Kobuleti Ground is transferring me to tower again while I'm still
         taxiing"

    "Taxi to zero seven, holding short of zero seven" is a READ-BACK of the
    clearance he was just given. "Holding short of runway zero seven" from a man
    who has arrived there is a REPORT. The words are identical and the
    classifier cannot tell them apart -- reasonably, because nothing in them
    differs. It called both `report_holding_short`, the phase moved, and Tower
    got him mid-taxi.

    THE SIM CAN TELL. Reporting himself stopped at the runway edge while radar
    shows twenty-four knots in the middle of the taxiway is a claim the scope
    contradicts -- exactly like a beacon report from eight miles out, which this
    engine has refused to believe since the guard beside it was written. No new
    mechanism, the same rule applied to the same kind of claim.
    """

    def setUp(self):
        from marshall.atc import agent_atc as A, bedrock_intent, controller as atc, intents
        from marshall.core import route as R
        self.A, self.intents, self.bedrock = A, intents, bedrock_intent
        self.ctl = atc.Controller(R.BATUMI_ASR)
        self.ctl._me = R.BATUMI_ASR.station_on(121.800)     # Kobuleti Ground
        self._real = bedrock_intent.classify

    def tearDown(self):
        self.bedrock.classify = self._real

    def scope_at(self, speed_kt):
        return self.A.Scope("", contacts=[{
            "name": "362nd_sockeye", "label": "362nd_sockeye",
            "callsign": "sockeye", "type": "F-16C_50",
            "lat": 41.93, "lon": 41.87, "alt_ft": 65, "heading": 339.0,
            "speed_kt": speed_kt, "manned": True, "on_ground": True}],
            origin=(41.609594, 41.600234),
            bullseye={"blue": {"lat": 42.18, "lon": 41.67}})

    def call(self, speed_kt):
        self.bedrock.classify = lambda _t: self.intents.Intent(
            self.intents.IntentKind.REPORT_HOLDING_SHORT, "sockeye")
        return self.A.separation_context(
            self.A.Bridge(), self.ctl, "taxi to zero seven, holding short of "
            "zero seven, sockeye", self.scope_at(speed_kt),
            known="sockeye", track="362nd_sockeye")

    def test_still_rolling_is_a_read_back_not_a_report(self):
        directive, _stack = self.call(24.0)
        self.assertIn("POSITION REJECTED", directive)
        ac = self.ctl.aircraft.get(self.ctl._resolve("sockeye"))
        self.assertNotEqual(getattr(ac, "sortie_phase", ""), "holding_short",
                            "Tower got him while he was still taxiing")

    def test_stopped_at_the_edge_is_believed(self):
        directive, _stack = self.call(0.0)
        self.assertNotIn("POSITION REJECTED", directive)
        ac = self.ctl.aircraft.get(self.ctl._resolve("sockeye"))
        self.assertEqual(getattr(ac, "sortie_phase", ""), "holding_short",
                         "a genuine hold-short report must still hand him over")


class DeliveryAsksAboutTheWeatherToo(unittest.TestCase):
    """The one seat that never confirmed the pilot had the information.

        "Clearance ... never did ask that I had information [alpha]"

    Every other controller asked, because `check_in` composes the advisory and
    they are the seats a pilot checks in with. He does not check in with
    Delivery -- he asks for a clearance -- and `request_clearance` moved the
    phase and said nothing at all.

    Which is backwards: delivery is where it matters most. The letter says which
    runway and which approach to expect, and it is the transmission immediately
    before the numbers he writes down.
    """

    def clearance_with(self, letter, on_air=True):
        import unittest.mock as mock
        from marshall.atc import controller as atc
        from marshall.atis import store
        from marshall.core import route as R
        c = atc.Controller(R.BATUMI_ASR)
        with mock.patch.object(store, "current",
                               return_value=mock.Mock(on_the_air=on_air,
                                                      letter=letter)):
            c.request_clearance("Sockeye 1-1")
        return c.take_out()

    def test_he_asks(self):
        out = self.clearance_with("Bravo")
        self.assertTrue(out, "Clearance said nothing at all")
        self.assertIn("information Bravo", " ".join(t.text for t in out))

    def test_it_carries_a_decision_so_a_dropped_letter_is_caught(self):
        # Prose alone can be dropped by the agent and nothing notices -- which
        # is exactly what happened to the check-in advisory before #90.
        kinds = [t.decision.kind for t in self.clearance_with("Bravo") if t.decision]
        self.assertIn("advise_atis", kinds)

    def test_a_field_with_no_broadcast_is_not_asked_about(self):
        # Asking a pilot to confirm an ATIS that does not exist is how you get a
        # confused read-back -- the rule `_atis_phrase` already states.
        self.assertEqual(self.clearance_with("", on_air=False), [])

    def test_the_words_come_from_the_one_place(self):
        # `_atis_phrase` has four shapes -- current, superseded, not yet
        # advised, no broadcast. Writing them twice is how two controllers come
        # to describe one letter differently.
        import inspect
        from marshall.atc import controller as atc
        self.assertIn("self._atis_phrase(ac)",
                      inspect.getsource(atc.Controller.request_clearance))


class OnlyOneThingJudgesTheReadBack(unittest.TestCase):
    """FILED, ISSUED and ACKNOWLEDGED are three states, and a model decided one.

        PILOT: Nellis Clearance, Sockeye, request clearance.
        ATC:   Sockeye, you are already cleared as filed and your read-back was
               correct.

    On a board that had just been emptied, to a man who had said six words. He
    had been read nothing and had agreed to nothing.

    The cause was two judges of one question. The bridge verifies the read-back
    against the clearance on the board -- `decision.verify`, the same function
    that checks the controller said what the engine decided -- and the director's
    tool ALSO took `correct: bool = True` from the model and wrote `clearance_ack`
    from it. The durable record of the one thing that distinguishes "we read him
    a clearance" from "he has it" came from the guess, defaulting to yes.

    So: the verifier decides, the bridge records, the agent phrases. Which is
    the rule everywhere else here and had been skipped in the one place where
    being wrong is unarguable -- "readback correct" is what ends clearance
    delivery's business and hands him to Ground. [#105]
    """

    def test_the_verdict_carries_what_he_missed(self):
        """`verify` has always returned WHICH facts went missing and the bridge
        threw the list away, so the only thing that knew what was wrong was the
        agent, inventing it. It guessed "altitude" at a pilot who had read the
        altitude back perfectly."""
        from marshall.atc import decision as D
        d = D.Decision(kind="clearance", to="Sockeye", altitude_ft=24000,
                       frequency_mhz=135.1, squawk="4620")
        missed = D.verify(d, "cleared as filed, maintain two four thousand, "
                             "departure one three five decimal one, sockeye")
        self.assertTrue(missed, "the squawk was never said")
        self.assertTrue(any("four six two zero" in m for m in missed))

    def test_the_engine_names_the_missed_element(self):
        ctl = atc.Controller(P)
        ctl.request_clearance("Sockeye")
        ctl.out.clear()
        ctl.clearance_read_back("Sockeye", correct=False,
                                missed=("four six two zero",))
        said = " | ".join(t.text for t in ctl.out).lower()
        self.assertIn("say again", said)
        self.assertIn("four six two zero", said)

    def test_a_wrong_read_back_still_moves_nobody(self):
        ctl = atc.Controller(P)
        ctl.request_clearance("Sockeye")
        ctl.clearance_read_back("Sockeye", correct=False, missed=("squawk",))
        ac = ctl.aircraft[ctl._resolve("Sockeye")]
        self.assertEqual(ac.sortie_phase, "clearance")

    def test_the_agent_has_no_way_to_declare_it_correct(self):
        """The tool that took the verdict from the model is gone. What replaces
        it REPORTS the state and cannot set it."""
        import inspect

        import sys
        sys.path.insert(0, "director")
        from tools import clearance as C
        src = inspect.getsource(C.clearance_tools)
        self.assertNotIn("def clearance_read_back", src)
        self.assertIn("def clearance_state", src)
        # ...and nothing in the tool list can stamp the acknowledgement.
        self.assertNotIn("ack(f[\"id\"])", src)

    def test_the_rules_no_longer_ask_the_agent_to_judge_it(self):
        from pathlib import Path
        rules = (Path(__file__).resolve().parent.parent / "src" / "marshall"
                 / "atc" / "agent" / "prompts" / "rules.md").read_text()
        self.assertIn("You do not judge the read-back", rules)
        self.assertNotIn("clearance_read_back(callsign, correct)", rules)


class GroundIsTheEndOfTheLadder(GroundCase):
    """A rung that hands BACKWARDS. [#100]

        PILOT: Taxi to parking my discretion, sockeye.
        ATC:   Sockeye, contact Batumi Tower one one eight decimal six.
        PILOT: Batumi Ground, don't you own parking instructions?

    He does. Two faults, and they compound.

    `landed` is TOWER's phase, correctly -- the roll is over and he is still on
    the strip. Nothing moved him off it, so Ground looked at a landed aeroplane,
    read Tower's phase, and handed him back to a controller who had finished with
    him. And parking was owned by nobody: Tower stopped saying it, correctly,
    because the taxiways are not his, and Ground never started -- so the last
    instruction of the sortie fell down the gap between two seats.

    `taxi_in` is Ground's and nothing follows it. `taxi` could not be reused: it
    means "to the holding point AND NO FURTHER", it leads to a runway, and
    `holding_short` follows it. Two journeys across the same tarmac in opposite
    directions, and one name for them is what made the ladder circular.
    """

    def _landed(self, station_name):
        me = station(station_name)
        self.ctl._me = me
        self.ctl.report_down("Sockeye")
        self.ctl.out.clear()
        return me

    def test_ground_gives_the_parking_instruction(self):
        self._landed("Kobuleti Ground")
        I.dispatch(self.ctl, I.Intent(kind=I.IntentKind.REQUEST_TAXI,
                                      callsign="Sockeye"))
        said = " | ".join(t.text for t in self.ctl.out).lower()
        self.assertIn("parking", said)
        self.assertNotIn("contact", said)

    def test_and_nothing_hands_him_anywhere_after_it(self):
        """The whole point. `taxi_in` has no successor and Ground owns it."""
        me = self._landed("Kobuleti Ground")
        I.dispatch(self.ctl, I.Intent(kind=I.IntentKind.REQUEST_TAXI,
                                      callsign="Sockeye"))
        ac = self.ctl.aircraft[self.ctl._resolve("Sockeye")]
        self.assertEqual(ac.sortie_phase, "taxi_in")
        self.assertEqual(PH.get("taxi_in").follows, ())
        self.assertIsNone(H.due(P, me, H.State(True, 0.2, False,
                                               phase=ac.sortie_phase)))

    def test_tower_does_not_answer_for_parking(self):
        """Symmetric with Ground refusing a take-off: a seat answers for what it
        owns and names the man who owns the rest."""
        self._landed("Kobuleti Tower")
        I.dispatch(self.ctl, I.Intent(kind=I.IntentKind.REQUEST_TAXI,
                                      callsign="Sockeye"))
        said = " | ".join(t.text for t in self.ctl.out).lower()
        self.assertIn("ground", said)
        self.assertNotIn("taxi to parking, your discretion", said)

    def test_a_landed_aeroplane_is_still_towers_until_he_asks_to_move(self):
        """He is stopped on the runway, which is Tower's, and Tower keeps him.

        THE HANDOFF IS THE TAXI REQUEST, not the touchdown. `landed` is Tower's
        by design -- the aeroplane is on his strip and "exit the runway when
        able" is his to say -- and the rung that belongs to Ground is `taxi_in`,
        which the pilot enters by asking for a stand. That is #77's criterion
        reached through the ladder rather than as a special case.
        """
        me = station("Kobuleti Tower")
        self.ctl._me = me
        self.ctl.report_down("Sockeye")
        ac = self.ctl.aircraft[self.ctl._resolve("Sockeye")]
        self.assertEqual(ac.sortie_phase, "landed")
        self.assertIsNone(H.due(P, me, H.State(True, 0.2, False,
                                               phase=ac.sortie_phase)),
                          "handed off the runway before he had left it")
        # ...and asking for a stand is what gives him to Ground.
        self.ctl.out.clear()
        I.dispatch(self.ctl, I.Intent(kind=I.IntentKind.REQUEST_TAXI,
                                      callsign="Sockeye"))
        v = H.due(P, me, H.State(True, 0.2, False, phase=ac.sortie_phase))
        self.assertEqual(v.station.name, "Kobuleti Ground")

    def test_taxiing_OUT_is_untouched(self):
        """The same words, the other direction, from a man who has not flown."""
        phase, _nxt, said = self.turn("Kobuleti Ground",
                                      I.IntentKind.REQUEST_TAXI)
        self.assertEqual(phase, "taxi")
        self.assertIn("hold short", said.lower())


class GroundDoesNotMoveAnAircraftOnAnUnagreedClearance(unittest.TestCase):
    """#135 -- "why does he let me go. Talk about swallowing an error."

    `clearance_agreed` has three states and only one of them refuses:

        None    nobody has cleared him, or nobody knows -- VFR passes through
        False   ISSUED and not read back correctly
        True    ACKNOWLEDGED

    On 12 August the read-back loop of #134 could not terminate, so this sat at
    False for a whole sortie and cost nothing: taxi, take-off, and a flight to
    another aerodrome on a clearance the board recorded as never agreed.
    """

    def ground(self):
        ctl = atc.Controller(profile=R.BATUMI_ASR)
        ctl._me = R.BATUMI_ASR.station_for("ground", field="Kobuleti")
        return ctl

    def test_taxi_is_refused_until_the_clearance_is_read_back(self):
        ctl = self.ground()
        ctl.get("Sockeye").clearance_agreed = False
        ctl.request_taxi("Sockeye")
        said = " ".join(t.text for t in ctl.out)
        self.assertIn("has not been read back", said)
        self.assertNotIn("taxi to runway", said.lower())

    def test_and_it_says_who_to_call(self):
        """A refusal that names no frequency is a refusal with no way out."""
        ctl = self.ground()
        ctl.get("Sockeye").clearance_agreed = False
        ctl.request_taxi("Sockeye")
        self.assertIn("contact", " ".join(t.text for t in ctl.out))

    def test_an_agreed_clearance_taxis_normally(self):
        ctl = self.ground()
        ctl.get("Sockeye").clearance_agreed = True
        ctl.request_taxi("Sockeye")
        self.assertIn("taxi to runway",
                      " ".join(t.text for t in ctl.out).lower())

    def test_nobody_cleared_him_at_all_still_taxis(self):
        """VFR, and everyone the engine has never been told about. Unknown
        never blocks -- a guard that fires on missing information silences a
        controller the first time the board is quiet."""
        ctl = self.ground()
        ctl.request_taxi("Sockeye")
        self.assertIn("taxi to runway",
                      " ".join(t.text for t in ctl.out).lower())

    def test_a_correct_read_back_agrees_it(self):
        ctl = self.ground()
        ctl.clearance_read_back("Sockeye", correct=True)
        self.assertIs(ctl.get("Sockeye").clearance_agreed, True)
