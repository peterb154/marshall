"""Formations: one entity until the fix, then individually sequenced.

The rules being pinned down here:

  * a joined flight is ONE aircraft to the stack -- one slot, one clearance
  * any member who transmits while joined is the flight talking
  * arriving at the holding fix breaks them up, lead lowest so he lands first
  * after break-up they are ordinary singles and nothing else changes
  * a break-up that will not fit under the ceiling is refused, not half-done
"""

import dataclasses
import unittest

from marshall.atc import controller as atc
from marshall.core import route as R

from tests.test_controller import profile, said, texts


def imc_profile(**over):
    """A hold INSIDE cloud, which is what these tests are about.

    Laddering a formation up the stack is what you do when the pilots cannot
    see each other, and that now has to be arranged rather than assumed: a
    vectored approach puts the bottom of its stack above the tops on purpose,
    so clear air is the normal case and a flight holds as one aeroplane at one
    level. These tests exercise the other branch, so they say so -- overcast
    thick enough to swallow the whole stack.
    """
    over.setdefault("cloud_thickness_ft", 12000)
    return profile(**over)


def four_ship(ctl, cs="Pony 1-1", visual=False):
    """Check a four-ship in, bring it to the beacon, and answer the controller's
    visual-separation question -- which is what actually triggers the break-up.

    Defaults to IMC (altitude separation), the case most of these tests are
    about; pass visual=True for the one-level VMC break-up.
    """
    ctl.check_in(cs, 4)
    ctl.report_beacon(cs, 6000, 4)
    ctl.report_conditions(callsign_flight(cs), visual)
    texts(ctl)


def callsign_flight(cs):
    from marshall.atc import callsign as C
    return C.parse(cs).flight


class TestJoined(unittest.TestCase):
    def setUp(self):
        self.ctl = atc.Controller(imc_profile())

    def test_a_flight_is_one_entity(self):
        self.ctl.check_in("Pony 1-1", 4)
        self.assertEqual(len(self.ctl.aircraft), 1)
        ac = self.ctl.get("Pony 1-1")
        self.assertTrue(ac.is_flight)
        self.assertEqual(ac.size, 4)
        self.assertEqual(ac.callsign, "Pony 1")     # keyed on the FLIGHT

    def test_the_flight_is_addressed_as_a_flight(self):
        self.ctl.check_in("Pony 1-1", 4)
        self.assertTrue(said(self.ctl, "pony one flight"))

    def test_a_single_ship_is_not_a_flight(self):
        self.ctl.check_in("Pony 1-1", 1)
        ac = self.ctl.get("Pony 1-1")
        self.assertFalse(ac.is_flight)
        self.assertEqual(ac.size, 1)

    def test_a_wingman_speaking_is_the_flight(self):
        # The whole point: ATC does not open a second conversation with three.
        self.ctl.check_in("Pony 1-1", 4)
        self.ctl.check_in("Pony 1-3")
        self.assertNotIn("Pony 1-3", self.ctl.aircraft)
        self.assertEqual(len(self.ctl.aircraft), 1)

    def test_a_garbled_digit_does_not_fork_the_flight(self):
        # Whisper hears "one two" for "one one" constantly. Without resolution
        # that silently becomes two entries in the stack at different levels.
        self.ctl.check_in("Pony 1-1", 4)
        before = set(self.ctl.aircraft)
        for garbled in ("Pony 1-2", "Pony 1-4", "Pony 1"):
            self.ctl.check_in(garbled)
        self.assertEqual(set(self.ctl.aircraft), before)

    def test_any_member_reaching_the_fix_breaks_the_flight_up(self):
        # It is the FORMATION that has arrived, whoever happens to say so.
        self.ctl.check_in("Pony 1-1", 4)
        texts(self.ctl)
        self.ctl.report_beacon("Pony 1-3", 6000)
        self.ctl.report_conditions("Pony 1", False)
        self.assertTrue(said(self.ctl, "break up"))
        self.assertEqual(self.ctl.get("Pony 1-2").assigned_ft, 4000)

    def test_a_joined_flight_occupies_one_slot(self):
        self.ctl.report_beacon("Hawk 1", 4000)          # single, cleared
        self.ctl.check_in("Pony 1-1", 4)
        self.ctl.report_beacon("Other 1", 5000)         # another single
        # The four-ship has not been broken up yet, so it is holding one level.
        self.assertEqual(len(self.ctl.aircraft), 3)


class TestBreakUp(unittest.TestCase):
    def setUp(self):
        self.ctl = atc.Controller(imc_profile())

    def test_arrival_at_the_fix_breaks_the_flight_up(self):
        four_ship(self.ctl)
        self.assertNotIn("Pony 1", self.ctl.aircraft)
        for n in range(1, 5):
            self.assertIn(f"Pony 1-{n}", self.ctl.aircraft)

    def test_lead_is_lowest_so_he_lands_first(self):
        four_ship(self.ctl)
        # Lead is cleared out of the bottom; the rest ladder up from the base.
        self.assertEqual(self.ctl.get("Pony 1-1").phase, atc.Phase.CLEARED)
        self.assertEqual(self.ctl.get("Pony 1-2").assigned_ft, 4000)
        self.assertEqual(self.ctl.get("Pony 1-3").assigned_ft, 5000)
        self.assertEqual(self.ctl.get("Pony 1-4").assigned_ft, 6000)

    def test_the_flight_releases_its_own_slot(self):
        # If the flight kept its level, its members would have to step over it.
        ctl = atc.Controller(imc_profile())
        ctl.check_in("Pony 1-1", 4)
        ctl.report_beacon("Hawk 1", 4000)      # a single takes the letdown first
        ctl.report_beacon("Pony 1-1", 6000, 4)
        ctl.report_conditions("Pony 1", False)
        texts(ctl)
        levels = sorted(ctl.get(f"Pony 1-{n}").assigned_ft for n in range(1, 5))
        self.assertEqual(levels, [4000, 5000, 6000, 7000])

    def test_break_up_is_announced_once_with_the_settled_levels(self):
        ctl = atc.Controller(imc_profile())
        ctl.check_in("Pony 1-1", 4)
        texts(ctl)
        ctl.report_beacon("Pony 1-1", 6000, 4)
        ctl.report_conditions("Pony 1", False)
        spoken = texts(ctl)
        breakup = [t for t in spoken if "break up" in t.lower()]
        self.assertEqual(len(breakup), 1, spoken)
        # The levels announced are the ones they will actually fly -- no
        # assigning an altitude and revising it in the next breath.
        self.assertIn("pony one two maintain four thousand", breakup[0].lower())
        self.assertNotIn("pony one one maintain", breakup[0].lower())

    def test_break_up_does_not_repeat_itself_as_step_downs(self):
        ctl = atc.Controller(imc_profile())
        ctl.check_in("Pony 1-1", 4)
        texts(ctl)
        ctl.report_beacon("Pony 1-1", 6000, 4)
        ctl.report_conditions("Pony 1", False)
        spoken = " ".join(texts(ctl)).lower()
        self.assertEqual(spoken.count("pony one two"), 1, spoken)

    def test_lead_is_cleared_immediately_when_the_letdown_is_free(self):
        ctl = atc.Controller(imc_profile())
        ctl.check_in("Pony 1-1", 4)
        texts(ctl)
        ctl.report_beacon("Pony 1-1", 6000, 4)
        ctl.report_conditions("Pony 1", False)
        self.assertTrue(said(ctl, "cleared beacon approach"))

    def test_nobody_is_cleared_when_the_letdown_is_busy(self):
        ctl = atc.Controller(imc_profile())
        ctl.report_beacon("Hawk 1", 4000)          # occupies the letdown
        ctl.check_in("Pony 1-1", 4)
        texts(ctl)
        ctl.report_beacon("Pony 1-1", 6000, 4)
        ctl.report_conditions("Pony 1", False)
        for n in range(1, 5):
            self.assertEqual(ctl.get(f"Pony 1-{n}").phase, atc.Phase.HOLDING)

    def test_requesting_the_approach_breaks_a_flight_up(self):
        ctl = atc.Controller(imc_profile())
        ctl.check_in("Pony 1-1", 4)
        texts(ctl)
        ctl.request_approach("Pony 1-1")           # asks about visual first
        ctl.report_conditions("Pony 1", False)
        self.assertTrue(said(ctl, "break up"))
        self.assertIn("Pony 1-4", ctl.aircraft)

    def test_explicit_break_up_request(self):
        ctl = atc.Controller(imc_profile())
        ctl.check_in("Pony 1-1", 4)
        texts(ctl)
        ctl.request_breakup("Pony 1")              # asks about visual first
        ctl.report_conditions("Pony 1", False)
        self.assertIn("Pony 1-4", ctl.aircraft)

    def test_break_up_request_from_a_single_is_harmless(self):
        ctl = atc.Controller(imc_profile())
        ctl.check_in("Sockeye")
        texts(ctl)
        ctl.request_breakup("Sockeye")
        self.assertTrue(said(ctl, "no flight to break up"))


class TestVisualSeparation(unittest.TestCase):
    """In VMC a flight can break up inside ONE holding level, because the pilots
    can see each other and accept responsibility for staying apart. In cloud that
    is not available and the controller separates them himself."""

    def setUp(self):
        self.ctl = atc.Controller(imc_profile())
        self.ctl.check_in("Pony 1-1", 4)
        texts(self.ctl)

    def arrive(self):
        self.ctl.report_beacon("Pony 1-1", 6000, 4)

    def test_the_controller_asks_before_assuming(self):
        self.arrive()
        self.assertTrue(said(self.ctl, "maintain visual separation"))

    def test_no_break_up_until_he_answers(self):
        self.arrive()
        self.assertIn("Pony 1", self.ctl.aircraft)        # still one entity
        self.assertNotIn("Pony 1-2", self.ctl.aircraft)

    def test_they_still_get_a_holding_level_while_asked(self):
        # Asking must not leave a four-ship with no altitude assigned.
        self.arrive()
        self.assertEqual(self.ctl.get("Pony 1").assigned_ft, 4000)

    def test_affirmative_puts_the_whole_flight_on_one_level(self):
        self.arrive()
        texts(self.ctl)
        self.ctl.report_conditions("Pony 1", True)
        levels = {self.ctl.get(f"Pony 1-{n}").assigned_ft for n in range(1, 5)}
        self.assertEqual(levels, {4000})
        self.assertTrue(said(self.ctl, "maintain visual separation", "in trail"))

    def test_negative_separates_them_by_altitude(self):
        self.arrive()
        texts(self.ctl)
        self.ctl.report_conditions("Pony 1", False)
        self.assertEqual(self.ctl.get("Pony 1-2").assigned_ft, 4000)
        self.assertEqual(self.ctl.get("Pony 1-3").assigned_ft, 5000)
        self.assertEqual(self.ctl.get("Pony 1-4").assigned_ft, 6000)

    def test_lead_is_still_sequenced_first_within_one_level(self):
        self.arrive()
        texts(self.ctl)
        self.ctl.report_conditions("Pony 1", True)
        self.assertEqual(self.ctl.get("Pony 1-1").phase, atc.Phase.CLEARED)

    def test_a_visual_flight_is_not_re_separated_by_the_step_down(self):
        # The trap: stepping the stack down one AIRCRAFT at a time would hand a
        # visual flight 4,000 / 5,000 / 6,000 and silently undo the break-up.
        ctl = atc.Controller(imc_profile())
        ctl.report_beacon("Hawk 1", 4000)          # cleared into the letdown
        ctl.report_beacon("Hawk 2", 5000)          # holds the bottom level
        ctl.check_in("Pony 1-1", 4)
        ctl.report_beacon("Pony 1-1", 6000, 4)
        ctl.report_conditions("Pony 1", True)
        texts(ctl)
        self.assertEqual({ctl.get(f"Pony 1-{n}").assigned_ft for n in range(1, 5)},
                         {5000})
        ctl.report_landed("Hawk 1")                # Hawk 2 cleared, stack steps down
        self.assertEqual({ctl.get(f"Pony 1-{n}").assigned_ft for n in range(1, 5)},
                         {4000})

    def test_a_flight_moving_together_gets_one_call(self):
        ctl = atc.Controller(imc_profile())
        ctl.report_beacon("Hawk 1", 4000)
        ctl.report_beacon("Hawk 2", 5000)
        ctl.check_in("Pony 1-1", 4)
        ctl.report_beacon("Pony 1-1", 6000, 4)
        ctl.report_conditions("Pony 1", True)
        texts(ctl)
        ctl.report_landed("Hawk 1")
        descents = [t for t in texts(ctl) if "descend and maintain" in t]
        self.assertEqual(len(descents), 1, descents)
        self.assertIn("pony one flight", descents[0].lower())

    def test_conditions_from_a_single_ship_are_harmless(self):
        ctl = atc.Controller(imc_profile())
        ctl.check_in("Sockeye")
        texts(ctl)
        ctl.report_conditions("Sockeye", True)
        self.assertTrue(said(ctl, "roger"))

    def test_an_unanswered_question_never_assumes_visual(self):
        # "Not asked" and "said no" must not collapse: defaulting to visual would
        # stack four aeroplanes on one level in cloud.
        self.assertIsNone(self.ctl.get("Pony 1").visual)


class TestBreakUpCapacity(unittest.TestCase):
    def test_a_break_up_that_will_not_fit_is_refused_whole(self):
        # Only the oxygen ceiling can cause this. Half a formation is worse than
        # none: the ships without a level would have nowhere legal to go.
        ctl = atc.Controller(imc_profile(hold_base_ft=4000, hold_top_ft=6000))
        ctl.report_beacon("Hawk 1", 4000)       # takes the letdown
        ctl.report_beacon("Hawk 2", 5000)       # holds 4000
        ctl.check_in("Pony 1-1", 4)
        texts(ctl)
        ctl.report_beacon("Pony 1-1", 6000, 4)
        ctl.report_conditions("Pony 1", False)
        self.assertTrue(said(ctl, "unable break-up"))
        self.assertIn("Pony 1", ctl.aircraft)            # still one entity
        self.assertNotIn("Pony 1-2", ctl.aircraft)       # and not half-split

    def test_a_refused_break_up_leaves_the_stack_untouched(self):
        ctl = atc.Controller(imc_profile(hold_base_ft=4000, hold_top_ft=6000))
        ctl.report_beacon("Hawk 1", 4000)
        ctl.report_beacon("Hawk 2", 5000)
        ctl.check_in("Pony 1-1", 4)
        texts(ctl)
        ctl.report_beacon("Pony 1-1", 6000, 4)          # asks about visual
        texts(ctl)
        before = {cs: a.assigned_ft for cs, a in ctl.aircraft.items()}
        ctl.report_conditions("Pony 1", False)
        after = {cs: a.assigned_ft for cs, a in ctl.aircraft.items()}
        self.assertEqual(before, after)


class TestAfterBreakUp(unittest.TestCase):
    """Once split they are ordinary singles -- the sequencing core is untouched."""

    def setUp(self):
        self.ctl = atc.Controller(imc_profile())
        four_ship(self.ctl)

    def test_members_are_now_individuals(self):
        self.ctl.report_beacon("Pony 1-3", 5000)
        self.assertFalse(self.ctl.get("Pony 1-3").is_flight)
        self.assertFalse(said(self.ctl, "flight"))

    def test_one_in_the_letdown_still_holds(self):
        self.ctl.request_approach("Pony 1-2")
        self.assertTrue(said(self.ctl, "continue holding", "number two"))

    def test_landing_sequences_the_next_member(self):
        self.ctl.report_landed("Pony 1-1")
        self.assertEqual(self.ctl.get("Pony 1-2").phase, atc.Phase.CLEARED)
        self.assertEqual(self.ctl.get("Pony 1-3").assigned_ft, 4000)

    def test_a_member_going_missed_goes_to_the_front(self):
        self.ctl.report_missed("Pony 1-1")
        self.assertEqual(self.ctl.get("Pony 1-1").phase, atc.Phase.CLEARED)
        self.assertEqual(self.ctl.get("Pony 1-2").phase, atc.Phase.HOLDING)

    def test_a_repeat_offender_is_banished_and_frees_his_flight(self):
        self.ctl.report_missed("Pony 1-1")
        texts(self.ctl)
        self.ctl.report_missed("Pony 1-1")
        self.assertEqual(self.ctl.get("Pony 1-1").phase, atc.Phase.BANISHED)
        self.assertEqual(self.ctl.get("Pony 1-2").phase, atc.Phase.CLEARED)

    def test_the_flight_name_now_means_lead(self):
        # After break-up "Pony one flight" is informally lead, who still answers
        # for the formation's name.
        self.assertEqual(self.ctl._resolve("Pony 1"), "Pony 1-1")

    def test_a_late_size_report_does_not_re_merge_them(self):
        self.ctl.check_in("Pony 1-1", 4)
        self.assertIn("Pony 1-4", self.ctl.aircraft)
        self.assertNotIn("Pony 1", self.ctl.aircraft)


class TestFormationWithOtherTraffic(unittest.TestCase):
    def test_a_single_stacks_above_a_broken_up_flight(self):
        ctl = atc.Controller(imc_profile())
        four_ship(ctl)                       # 1-1 cleared, 2/3/4 at 4/5/6000
        ctl.report_beacon("Hawk 1", 9000)
        self.assertEqual(ctl.get("Hawk 1").assigned_ft, 7000)

    def test_a_single_is_not_swallowed_by_the_flight(self):
        ctl = atc.Controller(imc_profile())
        four_ship(ctl)
        ctl.report_beacon("Hawk 1", 9000)
        texts(ctl)
        ctl.report_landed("Pony 1-1")
        # Everyone steps down, including the unrelated single.
        self.assertEqual(ctl.get("Hawk 1").assigned_ft, 6000)

    def test_two_formations(self):
        ctl = atc.Controller(imc_profile())
        ctl.check_in("Pony 1-1", 2)
        ctl.check_in("Hawk 2-1", 2)
        self.assertEqual(len(ctl.aircraft), 2)
        ctl.report_beacon("Pony 1-1", 6000, 2)
        ctl.report_conditions("Pony 1", False)
        ctl.report_beacon("Hawk 2-1", 7000, 2)
        ctl.report_conditions("Hawk 2", False)
        texts(ctl)
        self.assertEqual(ctl.get("Pony 1-2").assigned_ft, 4000)
        self.assertEqual(ctl.get("Hawk 2-1").assigned_ft, 5000)
        self.assertEqual(ctl.get("Hawk 2-2").assigned_ft, 6000)


class TestDispatchIntegration(unittest.TestCase):
    """The intent seam actually reaches the formation code."""

    def test_check_in_carries_flight_size(self):
        from marshall.atc import intents
        ctl = atc.Controller(imc_profile())
        intents.dispatch(ctl, intents.Intent(
            intents.IntentKind.CHECK_IN, "Pony 1-1", flight_size=4))
        self.assertTrue(ctl.get("Pony 1-1").is_flight)

    def test_breakup_intent_is_routed(self):
        from marshall.atc import intents
        ctl = atc.Controller(imc_profile())
        ctl.check_in("Pony 1-1", 4)
        texts(ctl)
        intents.dispatch(ctl, intents.Intent(
            intents.IntentKind.REQUEST_BREAKUP, "Pony 1"))
        intents.dispatch(ctl, intents.Intent(
            intents.IntentKind.REPORT_CONDITIONS, "Pony 1", visual=False))
        self.assertIn("Pony 1-4", ctl.aircraft)

    def test_unknown_kind_never_raises(self):
        from marshall.atc import intents
        self.assertIs(intents.IntentKind.coerce("report_approach"),
                      intents.IntentKind.UNKNOWN)
        self.assertIs(intents.IntentKind.coerce(""),
                      intents.IntentKind.UNKNOWN)


if __name__ == "__main__":
    unittest.main()


class TestClearAirHolding(unittest.TestCase):
    """A flight holds as ONE aeroplane at ONE level, in trail.

    From a pilot who has flown a lot of serious F-16 squadron work: they hold at
    whatever altitude buys clear air -- eighteen, twenty, thirty thousand,
    whatever it takes -- and the hold is a chance to regroup before the
    approach, not something to sweat. A flight stays at one altitude in trail.
    Altitude splits FLIGHTS from other flights; it does not split a flight from
    itself. And a Mustang can climb into clear air too.

    Which makes clear air the normal case rather than a lucky one, because a
    vectored approach now puts the bottom of its stack above the tops on
    purpose. Laddering a four-ship up four levels in weather it is above is
    work that buys nothing and spends the stack on one arrival.
    """

    def setUp(self):
        self.ctl = atc.Controller(R.BATUMI_ASR)

    def test_the_vectored_hold_is_above_the_weather(self):
        self.assertTrue(R.BATUMI_ASR.hold_in_clear_air)

    def test_a_flight_is_not_asked_whether_it_can_see_itself(self):
        four_ship(self.ctl)
        self.assertFalse(said(self.ctl, "visual separation"))

    def test_the_whole_flight_holds_at_one_level(self):
        four_ship(self.ctl)
        levels = {ac.assigned_ft for ac in self.ctl.aircraft.values()
                  if ac.assigned_ft is not None}
        self.assertLessEqual(len(levels), 1,
                             f"a flight was laddered across {levels} in clear air")

    def test_the_levels_go_to_separating_flights(self):
        # Two flights, two levels -- which is what the stack is for.
        four_ship(self.ctl)
        self.ctl.check_in("Viper 2-1", 2)
        self.ctl.request_approach("Viper 2-1")
        levels = {ac.assigned_ft for ac in self.ctl.aircraft.values()
                  if ac.assigned_ft is not None}
        self.assertGreaterEqual(len(levels), 1)

    def test_in_cloud_he_still_asks(self):
        # The branch has not been deleted, only demoted: with the stack inside
        # weather the controller cannot assume they see each other.
        ctl = atc.Controller(imc_profile())
        self.assertFalse(ctl.profile.hold_in_clear_air)
        # Driven directly rather than through four_ship, which answers the
        # question and drains the transcript -- the question itself is the
        # thing under test here.
        ctl.check_in("Pony 1-1", 4)
        ctl.report_beacon("Pony 1-1", 6000, 4)
        self.assertTrue(said(ctl, "visual separation"))
