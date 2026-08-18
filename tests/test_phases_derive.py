"""What phase he is in, from facts rather than from what anybody said.

`phases.py` has held a complete, correct table since it was written: fifteen
phases, each declaring who works him, what the geometry aims at, and what may
legally follow. Two modules read it. FIVE of the fifteen were ever set, all by
ground intents -- so once an aeroplane rotated, its phase froze on "departure"
for the rest of the sortie and every other component guessed instead.

On 9 August the approach geometry was asked about an F-16 one mile off Kobuleti
at 950 feet and 403 knots, climbing away on runway heading, and answered "he has
gone around, one miles. Missed approach: fly heading 330, climb 3000."

The cases below are that sortie, in order.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marshall.atc import phases as P
from marshall.core import route as R
from tests import theatre as T


class TestTheSortieInOrder(unittest.TestCase):

    def test_on_the_ramp_the_conversation_drives_it(self):
        """No geometry on the ground, so a clearance and a taxi request are the
        only things that can move him -- which is what already happens."""
        for phase in ("clearance", "taxi", "holding_short"):
            with self.subTest(phase=phase):
                self.assertEqual(P.derive(phase, on_ground=True), phase)

    def test_leaving_the_ground_makes_him_departing(self):
        """The transition nothing has ever made. He was holding short; he is
        now airborne; he is departing."""
        self.assertEqual(P.derive("holding_short", on_ground=False), "departure")

    def test_a_departing_aeroplane_is_not_on_an_approach(self):
        """The whole point. `departure` has its own geometry -- the same
        intercept flown the other way -- and it is not the arrival's."""
        self.assertFalse(P.derive("holding_short", on_ground=False) in
                         ("approach", "missed", "arrival"))

    def test_being_cleared_for_the_approach_is_what_makes_it_an_approach(self):
        """Not proximity, and not what the geometry would say if asked. A
        clearance is a thing that was ISSUED, by the engine, and it is the only
        honest signal that he is flying one."""
        self.assertEqual(P.derive("arrival", separation="cleared"), "approach")

    def test_going_around(self):
        self.assertEqual(P.derive("approach", separation="missed"), "missed")

    def test_stopped_on_the_aerodrome_after_flying_is_landed(self):
        self.assertEqual(
            P.derive("approach", on_ground=True, was_airborne=True), "landed")

    def test_stopped_on_the_aerodrome_having_never_flown_is_not(self):
        """A jet on the ramp before start-up is not an aeroplane that has
        landed, and calling it one welcomes him and sends him to parking."""
        self.assertNotEqual(P.derive("clearance", on_ground=True), "landed")

    def test_a_fresh_aeroplane_on_the_ramp_starts_at_the_first_rung(self):
        """Not `taxi`, which is where this used to put him.

        Clearance, taxi and holding short are the same range, the same
        direction and the same zero knots; radar cannot tell them apart. So a
        parked aeroplane nobody has spoken to yet is at the START of the
        ladder, and everything after that is driven by what he says.
        """
        self.assertEqual(P.derive("", on_ground=True), "clearance")

    def test_and_that_is_why_a_read_back_could_not_hand_him_to_ground(self):
        """The consequence, which is what was actually observed.

        Derived as `taxi` from the first word, he was Ground's before he had
        asked anybody for anything -- so `clearance_read_back` setting `taxi`
        moved him nowhere, there was no transition, and Delivery kept him.
        """
        started = P.derive("", on_ground=True)
        self.assertNotEqual(started, "taxi")
        self.assertEqual(P.owner_of(started), "delivery")
        self.assertEqual(P.owner_of("taxi"), "ground")


class TestItRefusesTheImpossible(unittest.TestCase):

    def test_an_illegal_transition_is_refused_and_the_phase_kept(self):
        """`follows` says what may come next, and the one place that knows is
        the table.

        THIS USED TO BE `enroute` WANTING `landed`, which is no longer illegal
        and never should have been: touching down is an observation, not a
        transition, and refusing it welded an aeroplane out of the last two
        rungs of the ladder (#151). `taxi_in` is the end of the ladder --
        nothing follows it -- so a clearance still sitting in the separation
        engine must not pull a man on a stand back onto an approach.
        """
        self.assertFalse(P.may_follow("taxi_in", "approach"))
        self.assertEqual(P.derive("taxi_in", separation="cleared"), "taxi_in")

    def test_a_legal_one_is_allowed(self):
        self.assertTrue(P.may_follow("arrival", "approach"))
        self.assertEqual(P.derive("arrival", separation="cleared"), "approach")

    def test_nothing_known_changes_nothing(self):
        """A deriver that invents a transition on missing information is worse
        than one that waits -- the scope drops, and a controller must not
        conclude anything from silence."""
        for phase in ("enroute", "approach", "taxi"):
            with self.subTest(phase=phase):
                self.assertEqual(P.derive(phase), phase)

    def test_an_unknown_phase_can_start_anywhere(self):
        """Nothing to transition FROM. A pilot may call up already airborne and
        already on an approach, which is how every sortie began for weeks."""
        self.assertEqual(P.derive("", separation="cleared"), "approach")
        self.assertEqual(P.derive("unknown", separation="holding"), "holding")


class TestWhichPhasesHaveGuidanceAtAll(unittest.TestCase):
    """`guide` -- the dispatcher written to prevent exactly the 9 August bug --
    has never been called by anything. This is the question it asks."""

    def test_the_approach_phases_fly(self):
        for phase in ("approach", "missed"):
            with self.subTest(phase=phase):
                self.assertTrue(P.flies_geometry(phase))

    def test_the_ground_phases_do_not(self):
        for phase in ("clearance", "taxi", "holding_short", "landed"):
            with self.subTest(phase=phase):
                self.assertFalse(P.flies_geometry(phase))

    def test_nor_does_departing_or_enroute(self):
        """Both are declared with geometry they aim at -- a course and a point
        -- and neither has a handler yet. Silent is the honest answer; being
        flown by the ARRIVAL's geometry is not."""
        for phase in ("departure", "enroute"):
            with self.subTest(phase=phase):
                self.assertFalse(P.flies_geometry(phase))

    def test_the_dispatcher_returns_nothing_for_them(self):
        from marshall.atc.geometry import Position
        pos = Position(range_nm=1.0, radial_deg=76.0, alt_ft=950,
                       heading_deg=71.0, speed_kt=403.0)
        self.assertIsNone(P.guide("departure", pos, T.the_arrival()))
        self.assertIsNotNone(P.guide("approach", pos, T.the_arrival()))




class TestTheDepartureFromTheNinthOfAugust(unittest.TestCase):
    """The exact transmission, end to end through `settle`.

        PILOT: Going to departure  [1.0 nm, 950 ft, heading 071, 403 knots]
        ASR:   he has gone around, one miles. Missed approach: fly heading
               330, climb 3000.

    He had lifted off Kobuleti eight seconds earlier.
    """

    def settle(self, phase, pos):
        from marshall.atc import agent_atc as A
        from marshall.atc import controller as C
        ctl = C.Controller(T.the_arrival())
        ctl.get("Sockeye").sortie_phase = phase
        return A.settle(A.Bridge(), "", "", "", pos, "Sockeye",
                        ctl, scope="", track="")

    def climbing_out(self):
        from marshall.atc.geometry import Position
        return Position(range_nm=1.0, radial_deg=76.0, alt_ft=950,
                        heading_deg=71.0, speed_kt=403.0)

    def test_a_departing_jet_is_not_told_he_has_gone_around(self):
        _d, _s, _v, guide, _dropped = self.settle("departure", self.climbing_out())
        self.assertIsNone(guide,
                          "the arrival's geometry was flown for a departure")

    def test_the_same_aeroplane_on_an_approach_still_gets_it(self):
        """The guard must not cost the case it sits beside. Identical position
        and speed; only the phase differs."""
        _d, _s, _v, guide, _dropped = self.settle("approach", self.climbing_out())
        self.assertIsNotNone(guide)

    def test_and_the_arrival_gets_it_too_before_any_clearance(self):
        """Being vectored towards the final is the half of the arrival that
        most needs guidance, and it happens before anybody is cleared."""
        _d, _s, _v, guide, _dropped = self.settle("arrival", self.climbing_out())
        self.assertIsNotNone(guide)

    def test_handed_to_approach_makes_him_arriving(self):
        """The handoff MEANT something. Without this he sits in `departure`
        until the clearance and gets nothing for the whole descent."""
        self.assertEqual(P.derive("departure", worked_by="approach"), "arrival")
        self.assertEqual(P.derive("enroute", worked_by="approach"), "arrival")

    def test_but_being_worked_by_ground_does_not_move_an_airborne_phase(self):
        """Deriving every phase from its owner would invert the table --
        `handoff.due` reads the phase to choose the controller -- and two rules
        pointing at each other is how three ideas of "what is happening" got
        loose in the first place."""
        self.assertEqual(P.derive("approach", worked_by="ground"), "approach")
        self.assertEqual(P.derive("enroute", worked_by="tower"), "enroute")


if __name__ == "__main__":
    unittest.main()


class TheApproachGeometryStaysOffTheDeparture(unittest.TestCase):
    """A whole departure was flown on approach vectors. Live, 10 August.

    Ninety seconds after rotating off Kobuleti, on his way to Batumi:

        ASR: he has gone around, two miles. Missed approach: fly heading 125,
             climb 3000.
        ASR: vectoring, nine miles. Turn left. Fly heading 250, maintain 3000.
        ATC: Sockeye, Kobuleti Departure, radar contact, turn left heading
             three zero five, maintain three thousand.

    He was turned through six headings and descended to two thousand while
    climbing out to five, thirty miles from either aerodrome, and he flew it --
    the instructions were confident, in correct phraseology, and wrong.

    TWO PATHS TO ONE GEOMETRY, ONE OF THEM GATED. `settle` asks
    `flies_geometry(phase)` before calling `phases.guide`, and `departure` says
    False, so the structured guide was correctly None. But `decide` had already
    built the PROSE from `asr_context`, which calls `asr.guide` directly and
    checks only three things -- vectored approach, a fix, not on the ground.
    No phase.

    And `reconcile` could not save it: it arbitrates only when there IS a guide,
    so `g is None` returned everything untouched, the ungated vectoring
    included. The same shape as #76 -- a fix applied to one call site and not
    its sibling -- found by flying it.
    """

    def phases_that_fly(self):
        from marshall.atc import phases
        return {n for n in phases.PHASES if phases.flies_geometry(n)}

    def test_only_the_arrival_phases_fly_the_approach(self):
        self.assertEqual(self.phases_that_fly(), {"arrival", "approach", "missed"})

    def test_departure_does_not(self):
        from marshall.atc import phases
        self.assertFalse(phases.flies_geometry("departure"),
                         "a climbing aeroplane is not on the approach")

    def test_enroute_does_not(self):
        from marshall.atc import phases
        self.assertFalse(phases.flies_geometry("enroute"))

    def test_the_gate_is_applied_to_the_prose_too(self):
        # THE ACTUAL REGRESSION. The structured guide was already gated; the
        # string the agent reads was not, and the string is what reached the
        # air. A test on `flies_geometry` alone would have passed throughout.
        import inspect
        from marshall.atc import agent_atc
        src = inspect.getsource(agent_atc.settle)
        self.assertIn("if vectoring and not flies:", src,
                      "the ASR prose must be suppressed for a phase that does "
                      "not fly the approach, not only the structured guide")

    def test_reconcile_cannot_be_relied_on_for_this(self):
        # Documented as a test because it is the reason the gate must be in
        # `settle`: with no guide, reconcile passes everything through.
        from marshall.atc import agent_atc
        _d, _s, v, dropped, _kept = agent_atc.reconcile(
            "", "", "ASR: vectoring, nine miles. Fly heading 250.", None, [])
        self.assertTrue(v, "reconcile does not filter vectoring without a guide")
        self.assertEqual(dropped, "")


class ARefusedTransitionIsNotSilent(unittest.TestCase):
    """A phase that will not move looks exactly like one nothing is moving.

    `derive` correctly refuses an illegal transition and keeps the current
    phase -- "landed while enroute" is not a thing. Refusing SILENTLY is how a
    phase gets welded in place: one bad input once, and the aeroplane stays
    there for the rest of the sortie with nothing anywhere saying why.

    On 10 August an aircraft sat in `departure` from rotation to thirteen miles
    on the approach -- through Center, through the hand-off to Batumi Approach,
    through "I'll take the surveillance approach" -- and the only trace was the
    consequence, twenty times over:

        .. ASR guidance suppressed: he is in the departure phase

    which says what happened and nothing about why. The refusal that caused it
    left no record at all. Same rule as `check.py`: skipped is reported, never
    silent.
    """

    def test_an_illegal_transition_calls_back(self):
        from marshall.atc import phases
        seen = []
        # `taxi_in` is the END OF THE LADDER: `follows` is empty, so nothing
        # legally comes after a man on a stand.
        #
        # THIS HAS NOW BEEN REWRITTEN TWICE, and both times for the same reason
        # -- it was pinned on a transition that turned out to be legal after
        # all. First `departure` on the ground wanting `taxi`, which the deriver
        # should never have proposed; then `enroute` wanting `landed`, which the
        # TABLE should never have refused (#151). The example has to be a
        # transition that is genuinely impossible rather than merely unwired.
        got = phases.derive("taxi_in", separation="cleared",
                            refused=lambda cur, want: seen.append((cur, want)))
        self.assertEqual(got, "taxi_in", "an illegal transition must not happen")
        self.assertEqual(seen, [("taxi_in", "approach")],
                         "the refusal that pins the phase left no trace")

    def test_a_legal_transition_does_not(self):
        from marshall.atc import phases
        seen = []
        got = phases.derive("departure", on_ground=False, worked_by="approach",
                            refused=lambda c, w: seen.append((c, w)))
        self.assertEqual(got, "arrival")
        self.assertEqual(seen, [], "a transition that happened is not a refusal")

    def test_no_callback_is_fine(self):
        from marshall.atc import phases
        self.assertEqual(phases.derive("taxi_in", separation="cleared"),
                         "taxi_in")

    def test_the_bridge_reports_who_is_working_him(self):
        # The verdict without its inputs is what made this undiagnosable: the
        # log said "he is in the departure phase" and nothing about the two
        # facts that decide it.
        import inspect
        from marshall.atc import agent_atc
        # `phase_now`, not `settle`: the derivation moved so that the half of
        # the turn which MUTATES the engine could ask before it acts.
        src = inspect.getsource(agent_atc.phase_now)
        self.assertIn("phase REFUSED", src)
        self.assertIn("worked by", src)


class TakingOffIsNotBeingEstablishedOnFinal(unittest.TestCase):
    """Six seconds after take-off, the engine cleared him for an approach.

        .. sockeye is already on final per radar; not stacking him
        .. phase REFUSED: departure cannot lead to approach — he stays in
           departure

    `separation_context` asked the APPROACH geometry about an aeroplane at
    0.6 nm and 472 feet climbing off Kobuleti. The geometry answered about the
    numbers it was given, obligingly, and `seen_on_final` -- which sets
    `Phase.CLEARED` and hands him the letdown -- did the rest. `derive` then
    wanted `approach`; `departure` cannot lead there; the transition was refused
    and the phase welded to `departure` for the whole flight.

    THE FOURTH CALLER OF `asr.guide`, and the only one that mutates. #86 gated
    two of them. This is the one that changes the engine, so it is the one where
    an ungated question costs most.
    """

    def setUp(self):
        from marshall.atc import agent_atc as A, controller as atc
        from marshall.core import route as R
        self.A, self.R, self.atc = A, R, atc
        self.p = T.the_arrival()
        self.ctl = atc.Controller(self.p)

    def climbing_off_kobuleti(self):
        """The radar line from the recorder, as data."""
        return {"name": "362nd_sockeye", "label": "362nd_sockeye",
                "callsign": "sockeye", "type": "F-16C_50",
                "lat": 41.94, "lon": 41.90, "alt_ft": 472,
                "heading": 71.0, "speed_kt": 341.0, "manned": True,
                "on_ground": False}

    def test_the_seed_is_refused_for_a_departing_aircraft(self):
        from marshall.atc import intents
        self.ctl._me = R.station_on(133.000)      # Kobuleti Tower
        self.ctl.check_in("sockeye")
        ac = self.ctl.get("sockeye")
        ac.sortie_phase = "departure"
        self.ctl.out.clear()
        scope = self.A.Scope("", contacts=[self.climbing_off_kobuleti()],
                             origin=(41.609594, 41.600234),
                             bullseye={"blue": {"lat": 42.18, "lon": 41.67}})
        self.A.separation_context(
            self.A.Bridge(), self.ctl, "sockeye airborne", scope,
            known="sockeye", track="362nd_sockeye",
            intent=intents.Intent(intents.IntentKind.CHECK_IN, "sockeye"))
        # ASSERTED AS "NOT IN THE LETDOWN", which is what the name says and
        # what the incident was. It used to read `phase == before`, and that
        # was a proxy that worked only because `check_in` set ENROUTE for
        # everybody -- so "unchanged" and "not cleared" were the same
        # sentence. #184 stopped admitting a man who has never flown, `before`
        # became UNKNOWN, and the proxy started failing on a transition that
        # is correct: this fixture is airborne (472 ft, 341 kt, climbing off
        # Kobuleti), so becoming ENROUTE is right and being put on an approach
        # is not.
        self.assertNotIn(ac.phase, (self.atc.Phase.CLEARED,
                                    self.atc.Phase.HOLDING),
                         "he was cleared for an approach he had not started")
        self.assertEqual(ac.sortie_phase, "departure")

    def test_an_unknown_aircraft_is_still_seeded(self):
        """The case the seed was BUILT for must keep working.

        A flight established on the final at ten miles that the engine has never
        heard of: blocking on "no phase" would fix today's bug by reopening the
        original one.
        """
        from marshall.atc import phases
        self.assertFalse(phases.flies_geometry(""),
                         "an empty phase flies nothing, which is why the gate "
                         "has to treat it as UNKNOWN rather than as a refusal")

    def test_the_phase_is_derived_before_anything_acts(self):
        import inspect
        from marshall.atc import agent_atc
        src = inspect.getsource(agent_atc.separation_context)
        i_phase = src.index("_phase = phase_now(")
        i_seed = src.index("ctl.seen_on_final(")
        self.assertLess(i_phase, i_seed,
                        "the engine is mutated before the phase is known")

    def test_one_function_answers_the_phase_question(self):
        # `settle` used to derive it separately, after this. Two derivations of
        # one fact is how the three disagreeing ideas of "what is happening"
        # got loose to begin with.
        import inspect
        from marshall.atc import agent_atc
        self.assertIn("phase_now(", inspect.getsource(agent_atc.settle))
        self.assertEqual(
            inspect.getsource(agent_atc.settle).count("_phases.derive("), 0)


class HavingFlownIsAPhaseAndNotACounter(unittest.TestCase):
    """"He is stopped on the aerodrome" means two opposite things.

    LANDED for an aeroplane that has flown, STILL ON THE RAMP for one that has
    not, and `derive` has taken a `was_airborne` argument to tell them apart
    since it was written. The bridge answered it with `bool(ac.approaches)` --
    a counter of GO-AROUNDS, incremented by `Controller._do_missed` and by
    nothing else. So every pilot who flew one approach and landed off it, which
    is every normal recovery, was reported as never having been airborne.

    The same shape as #146 one module over: a fact taken from a side-effect of
    one particular way of it being true, rather than read from the thing that
    holds it. The phase holds it -- `approach` IS an airborne phase -- and the
    counter only ever agreed by accident.

    WHAT IT COST is the ground half of the end of a sortie. `sortie_phase` never
    reached `landed` unless the separation engine had already called it, so
    `handoff.due` had no phase to hand a landed aeroplane to Ground with (#77),
    and `intents` reads the same field to tell "taxi to parking" from "ready to
    taxi" (#100) -- so the last request of a flight was answered as the first.
    """

    def test_an_airborne_phase_says_he_has_flown(self):
        for phase in ("enroute", "rtb", "arrival", "holding",
                      "approach", "missed", "tasked", "on_station"):
            with self.subTest(phase=phase):
                self.assertTrue(P.has_flown(phase))

    def test_but_DEPARTURE_does_not_because_it_straddles(self):
        """The one phase that is a ground phase and an air phase, in that
        order. It was in the list above and it cost a sortie.

        18 August, live: a pilot read back a take-off clearance at 0 knots on
        the runway, `derive("departure", on_ground=True)` returned `landed`,
        and for thirteen miles Departure posted him back to Tower because a
        landed aeroplane is Tower's. He had never left the ground.

        You are in `departure` from Tower's first word, through the roll,
        until Departure lets you go -- so the phase genuinely cannot say
        whether a man holding on the runway has already flown. That is what
        the `was_airborne` latch is for. [#178]
        """
        self.assertFalse(P.has_flown("departure"))
        self.assertEqual(
            P.derive("departure", on_ground=True, worked_by="tower"),
            "departure", "holding on the runway is not a landing")
        self.assertEqual(
            P.derive("departure", on_ground=True, was_airborne=True,
                     worked_by="tower"),
            "landed", "but a man radar HAS seen airborne has landed")

    def test_a_ground_phase_does_not(self):
        for phase in ("clearance", "taxi", "holding_short", "landed", "taxi_in"):
            with self.subTest(phase=phase):
                self.assertFalse(P.has_flown(phase))

    def test_and_neither_does_not_knowing(self):
        """`unknown` is a man on the radio and nothing more; `filed` is a plan
        with no aeroplane under it. Reading either as "he has flown" would
        welcome a cold-start jet home."""
        for phase in ("", "unknown", "filed"):
            with self.subTest(phase=phase):
                self.assertFalse(P.has_flown(phase))

    def test_stopped_after_an_approach_is_landed_without_being_told(self):
        """THE REGRESSION. No `was_airborne`, no separation verdict -- just the
        phase he was in and the sim saying he is down."""
        self.assertEqual(P.derive("approach", on_ground=True), "landed")

    def test_the_guard_it_must_not_break(self):
        """A jet on the ramp before start-up has not landed, and calling it one
        welcomes him and sends him to parking."""
        for phase in ("", "clearance", "taxi", "holding_short"):
            with self.subTest(phase=phase):
                self.assertNotEqual(P.derive(phase, on_ground=True), "landed")

    def test_a_caller_may_still_add_evidence(self):
        """`was_airborne` survives for a caller that knows something the phase
        does not -- a flight row that outlived a bridge restart. It may only
        ADD: withholding is what the counter was doing."""
        self.assertEqual(P.derive("approach", on_ground=True,
                                  was_airborne=False), "landed")

    def test_the_bridge_no_longer_answers_it_with_go_arounds(self):
        """Source, because the fault was the ARGUMENT and not the arithmetic.
        A behavioural test on `derive` alone passed throughout: the wrong
        answer was computed one layer up and handed in.

        THE COUNTER IS STILL FORBIDDEN; `was_airborne` IS NOT. This asserted
        that the bridge passes no `was_airborne` at all, which was right while
        the only thing it could pass was `bool(ac.approaches)` -- a count of
        GO-AROUNDS standing in for "has he left the ground". Unwiring it was
        the fix then.

        It made the phase the sole answer, and the phase cannot answer for
        `departure`. So the argument is back, fed by a LATCH set on positive
        radar evidence and persisted in `flights.has_been_airborne`. The
        original intent stands and is what is still asserted: no proxy, no
        counter, no inference from a number that means something else. [#178]
        """
        import inspect
        from marshall.atc import agent_atc
        src = inspect.getsource(agent_atc.phase_now)
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith("#"))
        self.assertNotIn("approaches", code,
                         "the go-around counter must not decide whether he "
                         "has been airborne")
        self.assertIn("has_been_airborne", code,
                      "the latch is how `departure` is answered; without it "
                      "an aeroplane that flew a circuit cannot be landed")
        self.assertIn("down is False", code,
                      "the latch must be set on POSITIVE evidence -- `not "
                      "down` is not `airborne`, which is #164's scar")


class TouchingDownIsObservedAndNotProposed(unittest.TestCase):
    """The table used to argue with the sim, and this class used to record it.

    It was written as `LandingOutOfAnArrivalIsRefusedByTheTable`, and what it
    asserted was the DEFECT: `may_follow(phase, "landed")` false for arrival,
    departure, enroute, holding and missed, and `derive("arrival",
    on_ground=True)` keeping `arrival` with a refusal in the log. A test that
    records a fault is not a test that guards a fix, and it is what #151 was
    filed to remove.

    Every one of those five is a thing an aeroplane does. A straight-in nobody
    formally cleared is in `arrival` when the wheels touch; a departure that
    comes straight back is in `departure`; a pilot who breaks off a hold and
    lands is in `holding`. In each case the sim stated the fact, `derive` wanted
    `landed`, and the table refused.

    What it COST is the end of the sortie. `landed` is Tower's and `taxi_in`
    follows it, so a phase that never reaches `landed` cannot hand him to Ground
    (#77), and `intents` reads the same field to tell "taxi to parking" from
    "ready to taxi" (#100) -- so the last request of a flight was answered as
    though it were the first.
    """

    # `has_flown` is the existing predicate for "he has been off the ground on
    # this sortie", and it is the one the deriver already uses. Naming the nine
    # here would be a second list to drift.
    AIRBORNE = tuple(n for n in P.PHASES if P.has_flown(n))
    # `landed` itself is left out: he HAS flown, and an aeroplane already in it
    # who is still down is in exactly the right phase.
    ON_THE_GROUND = tuple(n for n in P.PHASES
                          if not P.has_flown(n) and n != "landed")

    def test_every_airborne_phase_may_land(self):
        """Acceptance 1. `approach` was the only one, and touching down is not
        a procedural transition that can be illegal."""
        self.assertIn("arrival", self.AIRBORNE)     # the sweep is not empty
        for phase in self.AIRBORNE:
            with self.subTest(phase=phase):
                self.assertTrue(P.may_follow(phase, "landed"))

    def test_and_the_table_says_so_where_a_reader_looks(self):
        """THE DRIFT GUARD, and the reason this is data rather than a special
        case inside `may_follow`. A phase added later is airborne or it is not,
        and either way its `follows` has to agree with `has_flown` -- otherwise
        the next `arrival` is one nobody notices for a fortnight.

        `departure` IS EXEMPT AND IT IS THE ONLY ONE, because for it the two
        questions genuinely differ:

            can you land from here?   YES -- an aborted take-off, a circuit
            have you flown?           UNKNOWN -- you are in this phase from
                                      Tower's first word, stationary

        Every other phase answers both the same way, which is what makes this
        guard worth having. Asserting the exemption is only ONE phase wide is
        the half that keeps it from becoming a hole: a second straddler is a
        design change and should fail here. [#178]
        """
        STRADDLES = set(P.STRADDLES)
        self.assertEqual(STRADDLES, {"departure"},
                         "a second straddling phase appeared; the exemption "
                         "below was written for exactly one")
        for name, phase in P.PHASES.items():
            if name in STRADDLES:
                # It may land, and it is not evidence of having flown.
                self.assertIn("landed", phase.follows)
                self.assertFalse(P.has_flown(name))
                continue
            with self.subTest(phase=name):
                self.assertEqual(P.has_flown(name), "landed" in phase.follows,
                                 "an airborne phase must lead to `landed`, and "
                                 "a ground phase must not")

    def test_the_sims_fact_is_not_refused(self):
        """Acceptance 3. No `phase REFUSED: ... cannot lead to landed` in a
        normal recovery -- and the refusal callback is how that is heard."""
        for phase in self.AIRBORNE:
            with self.subTest(phase=phase):
                seen: list = []
                got = P.derive(phase, on_ground=True,
                               refused=lambda cur, want, s=seen:
                                   s.append((cur, want)))
                self.assertEqual(got, "landed")
                self.assertEqual(seen, [])

    def test_a_parked_aeroplane_that_has_never_flown_still_does_not_land(self):
        """Acceptance 2, and the case `follows` was written to protect. It is
        the same fact -- he is stopped on an aerodrome -- and the opposite
        phase."""
        for phase in self.ON_THE_GROUND:
            with self.subTest(phase=phase):
                self.assertNotEqual(P.derive(phase, on_ground=True), "landed",
                                    "a jet on the ramp before start-up has not "
                                    "landed")

    def test_and_no_ground_phase_may_lead_there_at_all(self):
        for phase in ("clearance", "taxi", "holding_short", "taxi_in"):
            with self.subTest(phase=phase):
                self.assertFalse(P.may_follow(phase, "landed"))
