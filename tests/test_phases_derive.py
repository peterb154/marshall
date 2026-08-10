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


class TestItRefusesTheImpossible(unittest.TestCase):

    def test_an_illegal_transition_is_refused_and_the_phase_kept(self):
        """`follows` says what may come next. "landed while enroute" is not a
        thing, and the one place that knows is the table."""
        self.assertFalse(P.may_follow("enroute", "landed"))
        self.assertEqual(P.derive("enroute", separation="landed"), "enroute")

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
        from marshall.core import route as R
        from marshall.atc.geometry import Position
        pos = Position(range_nm=1.0, radial_deg=76.0, alt_ft=950,
                       heading_deg=71.0, speed_kt=403.0)
        self.assertIsNone(P.guide("departure", pos, R.BATUMI_ASR))
        self.assertIsNotNone(P.guide("approach", pos, R.BATUMI_ASR))




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
        from marshall.core import route as R
        ctl = C.Controller(R.BATUMI_ASR)
        ctl.get("Sockeye").sortie_phase = phase
        return A.settle(A.Bridge(), "", "", "", pos, R.BATUMI_ASR, "Sockeye",
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
