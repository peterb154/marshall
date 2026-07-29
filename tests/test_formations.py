"""Formations: one entity until the fix, then individually sequenced.

The rules being pinned down here:

  * a joined flight is ONE aircraft to the stack -- one slot, one clearance
  * any member who transmits while joined is the flight talking
  * arriving at the holding fix breaks them up, lead lowest so he lands first
  * after break-up they are ordinary singles and nothing else changes
  * a break-up that will not fit under the ceiling is refused, not half-done
"""

import unittest

from marshall.atc import controller as atc

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


def four_ship(ctl, cs="Pony 1-1", check_in_after=True):
    """Check a four-ship in, bring it to the fix -- which breaks it up -- and
    then check each member in as a single.

    That last step IS the model, and it replaces a different thing entirely.
    The controller used to ask "can you maintain visual separation between your
    aircraft?", and the answer chose between one shared level and a ladder of
    four. Both are gone: separation inside a formation is the flight lead's and
    never the controller's, so the break-up assigns nothing and each aeroplane
    becomes an ordinary arrival.

        "If the flight reports a breakup then 4 pilots check in, they all need
         to ask for the approach. Atc will treat like 4 airplanes."

    check_in_after=False observes the moment in between.
    """
    ctl.check_in(cs, 4)
    ctl.report_beacon(cs, 6000, 4)
    if check_in_after:
        flight = callsign_flight(cs)
        for n in range(1, 5):
            ctl.check_in(f"{flight}-{n}", 1)
            # AND ASKS. Checking in is not requesting an approach, and the
            # break-up no longer assumes he wants one -- "they all need to ask
            # for the approach" is the model, so a member who only checks in
            # is enroute with no level, which is correct and is not what these
            # tests are about.
            ctl.request_approach(f"{flight}-{n}")
    # RETURNED, not discarded. Draining here and asserting afterwards is how a
    # test ends up checking an empty list and passing for the wrong reason.
    return texts(ctl)


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
        self.assertTrue(said(self.ctl, "break up"))
        self.assertIsNone(self.ctl.get("Pony 1-2").assigned_ft)

    def test_a_joined_flight_occupies_one_slot(self):
        self.ctl.report_beacon("Hawk 1", 4000)          # single, cleared
        self.ctl.check_in("Pony 1-1", 4)
        self.ctl.report_beacon("Other 1", 5000)         # another single
        # The four-ship has not been broken up yet, so it is holding one level.
        self.assertEqual(len(self.ctl.aircraft), 3)


class TestBreakUp(unittest.TestCase):
    """The break-up does ONE thing: the flight stops existing.

    It used to assign levels -- one shared, or a ladder of four -- chosen by
    the answer to a question that was never the controller's to ask. Now each
    aeroplane becomes an ordinary arrival separated through the same path as
    any single, which also deletes the capacity problem: there are no longer
    four levels to find before a split may happen.
    """

    def setUp(self):
        self.ctl = atc.Controller(imc_profile())

    def test_the_flight_stops_existing(self):
        four_ship(self.ctl, check_in_after=False)
        self.assertNotIn("Pony 1", self.ctl.aircraft)

    def test_nobody_is_assigned_anything_by_the_break_up(self):
        """They are not aeroplanes the controller is working yet -- they have
        not asked. Pre-assigning four levels to pilots who may not want an
        approach is what let a full stack refuse a break-up outright."""
        four_ship(self.ctl, check_in_after=False)
        self.assertEqual(self.ctl.aircraft, {})

    def test_they_are_told_to_check_in_individually(self):
        call = " ".join(four_ship(self.ctl, check_in_after=False)).lower()
        self.assertIn("break up", call)
        self.assertIn("check in individually", call)

    def test_each_of_them_is_named(self):
        """A pilot who is not named does not know he is expected to call."""
        call = " ".join(four_ship(self.ctl, check_in_after=False)).lower()
        for n in ("one one", "one two", "one three", "one four"):
            self.assertIn(f"pony {n}", call)

    def test_announced_once(self):
        spoken = four_ship(self.ctl, check_in_after=False)
        self.assertEqual(len([t for t in spoken if "break up" in t.lower()]), 1,
                         spoken)

    def test_once_they_ask_they_are_separated_like_singles(self):
        """Distinct levels for the ones HOLDING. Lead is cleared into the
        letdown rather than holding, so he may share a number with the man who
        took the level he left -- that is the stack stepping down, not two
        aeroplanes at one altitude."""
        four_ship(self.ctl)
        holding = [a.assigned_ft for a in self.ctl.aircraft.values()
                   if a.phase is atc.Phase.HOLDING and a.assigned_ft]
        self.assertEqual(len(set(holding)), len(holding), holding)

    def test_explicit_break_up_request(self):
        self.ctl.check_in("Pony 1-1", 4)
        texts(self.ctl)
        self.ctl.request_breakup("Pony 1")
        self.assertNotIn("Pony 1", self.ctl.aircraft)

    def test_requesting_the_approach_breaks_a_flight_up(self):
        """Four ships cannot fly one letdown, whether or not the word is used."""
        self.ctl.check_in("Pony 1-1", 4)
        texts(self.ctl)
        self.ctl.request_approach("Pony 1")
        self.assertNotIn("Pony 1", self.ctl.aircraft)


class TestSeparationInsideAFlightIsNotOurs(unittest.TestCase):
    """The question is gone, and it was the wrong shape.

        "We need to simplify the 'can you maintain visual separation' thing...
         It's the flights choice if they want to break up. Not atc problem."
        "Almost none of that can you maintain separation is actually battle
         tested. Don't feel bad about tossing it."

    It is also the real rule: separation between aircraft WITHIN a formation
    rests with the flight lead and the pilots concerned, never the controller.
    So there was nothing to negotiate -- and the question cost a transmission,
    a tri-state field, an intent kind, two dispatch patterns and a branch in
    every level assignment, to decide something that was never ours.
    """

    def setUp(self):
        self.ctl = atc.Controller(imc_profile())
        self.ctl.check_in("Pony 1-1", 4)
        texts(self.ctl)

    def test_the_controller_does_not_ask(self):
        self.ctl.report_beacon("Pony 1-1", 6000, 4)
        self.assertFalse(said(self.ctl, "maintain visual separation between"))

    def test_the_break_up_needs_no_answer(self):
        """It used to wait for one, so a flight that never replied was never
        broken up at all."""
        self.ctl.report_beacon("Pony 1-1", 6000, 4)
        self.assertNotIn("Pony 1", self.ctl.aircraft)

    def test_the_controller_has_no_opinion_to_record(self):
        self.assertFalse(hasattr(atc.Aircraft("x"), "visual"))


# (TestBreakUpCapacity is gone. It tested refusing a break-up when the stack
# could not hold four more aeroplanes -- a problem that existed only because
# the break-up pre-assigned levels. It assigns nothing now, so there is nothing
# to fit and nothing to refuse.)


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
        ctl.report_beacon("Hawk 2-1", 7000, 2)
        texts(ctl)
        # Nothing is assigned by the break-up itself -- he has not asked for
        # an approach yet, and pre-assigning to a pilot who may not want one is
        # what the old two-step did.
        # Both flights are gone and NEITHER has been given anything: the
        # break-up assigns nothing, and none of these four has asked for an
        # approach. What matters here is that two formations do not become one
        # -- each dissolved into its own members.
        for who in ("Pony 1-2", "Hawk 2-1", "Hawk 2-2"):
            self.assertIsNone(ctl.get(who).assigned_ft, who)
        self.assertNotIn("Pony 1", ctl.aircraft)
        self.assertNotIn("Hawk 2", ctl.aircraft)


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
        # The flight stops existing; its members are ordinary arrivals who have
        # not called yet. There is no second intent to send -- the question
        # that used to be needed here is gone.
        self.assertNotIn("Pony 1", ctl.aircraft)

    def test_unknown_kind_never_raises(self):
        from marshall.atc import intents
        self.assertIs(intents.IntentKind.coerce("report_approach"),
                      intents.IntentKind.UNKNOWN)
        self.assertIs(intents.IntentKind.coerce(""),
                      intents.IntentKind.UNKNOWN)


if __name__ == "__main__":
    unittest.main()


class TestClearAirHolding(unittest.TestCase):
    """Holding above the weather.

    This class used to be mostly about NOT asking the visual-separation
    question when the hold is in clear air -- a special case for a question
    that no longer exists in any air. What is left is the thing the profile
    flag still means: a flight holds as one aeroplane at one level, and the
    levels are spent separating FLIGHTS from each other rather than a formation
    from itself.
    """

    def setUp(self):
        self.ctl = atc.Controller(profile())

    def test_a_flight_holds_as_one(self):
        self.ctl.check_in("Pony 1-1", 4)
        self.assertEqual(len(self.ctl.aircraft), 1)

    def test_the_question_is_never_asked(self):
        self.ctl.check_in("Pony 1-1", 4)
        self.ctl.report_beacon("Pony 1-1", 6000, 4)
        self.assertFalse(said(self.ctl, "maintain visual separation between"))

    def test_two_flights_get_two_levels(self):
        """The levels go to separating flights from other flights, which is
        what they were always for."""
        self.ctl.check_in("Pony 1-1", 4)
        self.ctl.check_in("Hawk 2-1", 2)
        levels = {a.assigned_ft for a in self.ctl.aircraft.values()
                  if a.assigned_ft}
        self.assertEqual(len(self.ctl.aircraft), 2)
        self.assertLessEqual(len(levels), 2)


class TestIdentifyOnBreakUp(unittest.TestCase):
    """Establish who is who BEFORE separating them.

    Until the break-up the flight is one entity and one voice speaks for it,
    which is right. The instant they are separated they are N aircraft the
    controller has to tell apart -- and the only names he has came off the
    radar, which labels tracks by whatever the sim called the units. Live that
    produced two Mustangs addressed as "Pony one" and "Pony one one":
    adjacent, confusable, and never agreed with anybody.
    """

    def ctl(self, size):
        c = atc.Controller(profile())
        c.check_in("Pony 1-1", size)
        c.request_breakup("Pony 1-1")
        return c

    def breakup_call(self, c):
        return next(tx.text for tx in c.out if "break up" in tx.text)

    def test_every_aircraft_is_named_in_order(self):
        call = self.breakup_call(self.ctl(4))
        for name in ("Pony one one", "Pony one two", "Pony one three",
                     "Pony one four"):
            self.assertIn(name, call)
        self.assertLess(call.index("Pony one one"), call.index("Pony one four"),
                        "the ORDER is what binds each voice to each track")

    def test_the_cleared_aircraft_is_named_too(self):
        """The sequencer usually clears lead in the same breath, and lead is
        the one whose identity matters most -- he is about to be talked down."""
        c = self.ctl(2)
        self.assertIn("Pony one one", self.breakup_call(c))

    def test_a_single_ship_is_not_asked_to_identify_itself(self):
        c = atc.Controller(profile())
        c.check_in("Pony 1-1", 1)
        c.request_breakup("Pony 1-1")
        for tx in c.out:
            self.assertNotIn("identify each of you", tx.text)


class TestAskDoNotInferAfterBreakUp(unittest.TestCase):
    """A formation that has been split no longer names an aeroplane.

    Answering it by picking lead is a guess, and the wrong kind: the controller
    cannot actually tell which of two aircraft keyed the mic, and separating men
    he cannot tell apart is the failure this whole feature exists to prevent.
    """

    def setUp(self):
        self.ctl = atc.Controller(profile())
        self.ctl.check_in("Pony 1-1", 2)
        self.ctl.request_breakup("Pony 1-1")
        self.ctl.out.clear()

    def test_the_flight_name_is_ambiguous_once_split(self):
        self.assertTrue(self.ctl.ambiguous_after_breakup("Pony 1"))

    def test_a_member_name_is_not(self):
        for cs in ("Pony 1-1", "Pony 1-2"):
            with self.subTest(cs=cs):
                self.assertFalse(self.ctl.ambiguous_after_breakup(cs))

    def test_another_flight_still_together_is_not(self):
        self.ctl.check_in("Hammer 1-1", 2)
        self.assertFalse(self.ctl.ambiguous_after_breakup("Hammer 1"))

    def test_he_is_asked_who_he_is_and_offered_the_options(self):
        from marshall.atc import intents
        handled = intents.dispatch(
            self.ctl, intents.Intent(kind=intents.IntentKind.REPORT_BEACON,
                                     callsign="Pony 1", altitude_ft=5000))
        self.assertTrue(handled, "silence would be worse than a guess")
        said = " ".join(t.text for t in self.ctl.out).lower()
        self.assertIn("say your callsign", said)
        self.assertIn("pony one one", said)
        self.assertIn("pony one two", said)

    def test_the_ambiguous_call_is_not_acted_on(self):
        from marshall.atc import intents
        before = self.ctl.get("Pony 1-1").assigned_ft
        intents.dispatch(self.ctl,
                         intents.Intent(kind=intents.IntentKind.REPORT_BEACON,
                                        callsign="Pony 1", altitude_ft=9000))
        self.assertEqual(self.ctl.get("Pony 1-1").assigned_ft, before,
                         "a guess about WHO must not become a change to his state")


class TestCheckingInOutOfASplit(unittest.TestCase):
    """"The flight splits, the members check in - response should be - radar
    contact, what are your intentions"

    And that is the whole answer for him. He is not a new arrival to be told
    where to report -- he has been on this frequency for twenty minutes inside
    a formation, so the standard check-in reply briefs him on things he already
    has. What the controller genuinely does not know is what he WANTS, because
    the break-up deliberately assigned him nothing.

    It also stops the controller assuming. Four aeroplanes out of one flight
    may want four different things -- one for the approach, one departing, one
    holding for his wingman -- and the old flow gave all four a level nobody
    asked for.
    """

    def setUp(self):
        self.ctl = atc.Controller(imc_profile())
        self.ctl.check_in("Pony 1-1", 4)
        self.ctl.report_beacon("Pony 1-1", 6000, 4)
        texts(self.ctl)

    def test_he_is_asked_what_he_wants(self):
        self.ctl.check_in("Pony 1-2", 1)
        said_now = " ".join(texts(self.ctl)).lower()
        self.assertIn("radar contact", said_now)
        self.assertIn("say intentions", said_now)

    def test_he_is_not_briefed_as_a_new_arrival(self):
        """He already has the altimeter, the frequency and the fix."""
        self.ctl.check_in("Pony 1-2", 1)
        said_now = " ".join(texts(self.ctl)).lower()
        self.assertNotIn("report ", said_now)

    def test_nothing_is_assigned_until_he_asks(self):
        self.ctl.check_in("Pony 1-2", 1)
        self.assertIsNone(self.ctl.get("Pony 1-2").assigned_ft)

    def test_a_genuinely_new_arrival_still_gets_the_full_check_in(self):
        """The short reply is for somebody coming out of a split, not for
        everybody -- a stranger needs what it leaves out."""
        self.ctl.check_in("Hawk 3-1", 1)
        said_now = " ".join(texts(self.ctl)).lower()
        self.assertNotIn("say intentions", said_now)
