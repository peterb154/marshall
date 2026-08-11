"""Formations: one entity, for as long as the flight lead wants to be one.

REWRITTEN 30 July, and the rule that moved is whose decision it is:

    "if a flight wants to fly an approach in formation - they can. That's up to
     the flight lead. But only the lead's a/c is used for vectors."
    "if they want to fly individual approaches, they request/announce breakup -
     then each check in with an intention."
    "ATC should NEVER initiate a breakup."

The engine used to break a formation up by itself in three places -- on arrival
at the fix, on a request for the approach, and on a request for a visual -- each
with the same reasoning in the comment: four ships cannot fly one letdown,
therefore split them. The premise is a controller's opinion about somebody
else's formation, and acting on it dissolved four aeroplanes on the board while
four pilots were still flying in them.

It also forced a second wrong thing. Having created N aircraft, the engine had
to name them, and all it had was the flight key -- so it minted "Pony 1-1"
through "Pony 1-4" and read them out. That worked only while the key happened to
look like a callsign; the day identity started keying on handles it began
announcing "Sockeye one" through "Sockeye four", four aeroplanes nobody has.

So the rules now:

  * a joined flight is ONE aircraft to the stack -- one slot, one clearance --
    and it stays one through the hold and the letdown if that is what lead wants
  * any member who transmits while joined is the flight talking
  * only the LEAD's aeroplane is used for vectors, whoever keyed the mic
  * a break-up happens when the flight says so, and never otherwise
  * the break-up names nobody: it asks each of them to check in as himself
  * out of the split they are ordinary singles, and nothing else changes

The one exception, and it is not really a break-up: if the lead DIES or leaves
the sim, the flight has stopped existing and the controller says so. That is an
observation reported to the survivors, not a manoeuvre asked of them, and it
lives in `flights.Roster` rather than here.
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
    """Check a four-ship in, bring it to the fix, and have LEAD ask to split.

    THAT MIDDLE STEP IS THE CHANGE. It used to be enough to reach the fix --
    `report_beacon` broke the flight up on arrival, every time -- so every test
    below inherited an ATC-initiated split without asking for one. The flight
    now holds as a flight until its lead says otherwise, so the request is
    explicit here, which is also a fair picture of the sortie: four ships in
    cloud, lead decides he would rather have four separate approaches, says so.

        "If the flight reports a breakup then 4 pilots check in, they all need
         to ask for the approach. Atc will treat like 4 airplanes."

    check_in_after=False observes the moment in between.
    """
    ctl.check_in(cs, 4)
    ctl.report_beacon(cs, 6000, 4)
    ctl.request_breakup(callsign_flight(cs))
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

    def test_reaching_the_fix_does_not_break_the_flight_up(self):
        """INVERTED 30 July. This asserted that any member reaching the fix
        split the formation, whoever said so -- and that was the controller
        deciding a four-ship could not hold as one. It can, and holding as one
        is the easy case for everybody: one level, one clearance, one aeroplane
        to sequence."""
        self.ctl.check_in("Pony 1-1", 4)
        texts(self.ctl)
        self.ctl.report_beacon("Pony 1-3", 6000)
        self.assertFalse(said(self.ctl, "break up"))
        self.assertIn("Pony 1", self.ctl.aircraft)

    def test_a_flight_may_fly_the_whole_approach_as_a_flight(self):
        """The case that used to be unreachable: nobody asks to split, so
        nobody splits, and the formation is worked to the runway as one."""
        self.ctl.check_in("Pony 1-1", 4)
        self.ctl.report_beacon("Pony 1-1", 6000, 4)
        self.ctl.request_approach("Pony 1")
        ac = self.ctl.get("Pony 1")
        self.assertTrue(ac.is_flight)
        self.assertEqual(ac.phase, atc.Phase.CLEARED)
        self.assertEqual(len(self.ctl.aircraft), 1)

    def test_a_joined_flight_occupies_one_slot(self):
        self.ctl.report_beacon("Hawk 1", 4000)          # single, cleared
        self.ctl.check_in("Pony 1-1", 4)
        self.ctl.report_beacon("Other 1", 5000)         # another single
        # The four-ship has not been broken up, so it is holding one level.
        self.assertEqual(len(self.ctl.aircraft), 3)


class TestOnlyTheFlightMaySplitItself(unittest.TestCase):
    """The three doors that used to do it for them, each now shut.

        "ATC should NEVER initiate a breakup."

    Separation WITHIN a formation rests with the flight lead and the pilots
    concerned (FAA JO 7110.65), and so does the decision to stop being one --
    it is a manoeuvre, flown in cloud, by people whose spacing is their own
    business. A controller may say what he can and cannot do for them. He does
    not reach in and dissolve them.
    """

    def setUp(self):
        self.ctl = atc.Controller(imc_profile())
        self.ctl.check_in("Pony 1-1", 4)
        texts(self.ctl)

    def test_arriving_at_the_fix_does_not(self):
        self.ctl.report_beacon("Pony 1-1", 6000, 4)
        self.assertIn("Pony 1", self.ctl.aircraft)

    def test_asking_for_the_approach_does_not(self):
        self.ctl.request_approach("Pony 1")
        self.assertIn("Pony 1", self.ctl.aircraft)

    def test_asking_for_a_visual_does_not(self):
        self.ctl.request_visual("Pony 1", field_in_sight=True)
        self.assertIn("Pony 1", self.ctl.aircraft)

    def test_the_word_break_up_is_never_spoken_unprompted(self):
        """A pilot who hears it and did not ask for it has been told his
        formation no longer exists by somebody who is not in it."""
        self.ctl.report_beacon("Pony 1-1", 6000, 4)
        self.ctl.request_approach("Pony 1")
        self.assertFalse(said(self.ctl, "break up"))

    def test_asking_does(self):
        self.ctl.request_breakup("Pony 1")
        self.assertNotIn("Pony 1", self.ctl.aircraft)


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

    def test_nobody_is_named_because_nobody_is_known(self):
        """REPLACES `test_each_of_them_is_named`, which is the test that made
        the minting necessary. A flight report is a NUMBER -- "flight of four"
        -- and the engine turned it into four names off the flight key so it
        would have something to read out. Those names were never agreed with
        anybody; the day the key became a handle they became "Sockeye one"
        through "Sockeye four", which no pilot would answer to.

        The only thing that produces a name is a man keying his own microphone,
        so the call asks for exactly that.
        """
        call = " ".join(four_ship(self.ctl, check_in_after=False)).lower()
        self.assertIn("your own callsign", call)
        for invented in ("pony one two", "pony one three", "pony one four"):
            self.assertNotIn(invented, call)

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

    def test_a_wingman_may_ask_and_it_is_the_flight_asking(self):
        """He is inside the formation, so it is the flight that has spoken --
        the same rule as every other transmission while they are joined."""
        self.ctl.check_in("Pony 1-1", 4)
        texts(self.ctl)
        self.ctl.request_breakup("Pony 1-3")
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
        self.ctl.request_breakup("Pony 1")
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

    def test_the_flight_name_belongs_to_nobody_now(self):
        """REPLACES `test_the_flight_name_now_means_lead`, which resolved
        "Pony 1" to "Pony 1-1" -- and could only do so because the engine had
        minted that name at the split. It knows the flight is broken up; it
        does not know who lead turned out to be, and guessing is the failure
        `ambiguous_after_breakup` exists to prevent."""
        self.assertTrue(self.ctl.ambiguous_after_breakup("Pony 1"))

    def test_a_late_size_report_does_not_re_merge_them(self):
        """A stale "flight of four" arriving after the split must not put four
        individually-sequenced aeroplanes back into one entity."""
        self.ctl.check_in("Pony 1-1", 4)
        self.assertNotIn("Pony 1", self.ctl.aircraft)
        self.assertFalse(self.ctl.get("Pony 1-1").is_flight)


class TestFormationWithOtherTraffic(unittest.TestCase):
    def test_a_single_stacks_above_a_broken_up_flight(self):
        ctl = atc.Controller(imc_profile())
        four_ship(ctl)                       # 1-1 cleared at 4000; 2/3/4 at 5/6/7000
        ctl.report_beacon("Hawk 1", 9000)
        self.assertEqual(ctl.get("Hawk 1").assigned_ft, 8000)

    def test_a_single_is_not_swallowed_by_the_flight(self):
        ctl = atc.Controller(imc_profile())
        four_ship(ctl)
        ctl.report_beacon("Hawk 1", 9000)
        texts(ctl)
        ctl.report_landed("Pony 1-1")
        # Everyone steps down ONE, including the unrelated single -- onto the
        # levels that are free, which is 8,000 -> 7,000 now that the aircraft
        # cleared into the letdown keeps the one below. [#108]
        self.assertEqual(ctl.get("Hawk 1").assigned_ft, 7000)

    def test_a_formation_and_a_single_share_the_stack(self):
        """A four-ship that stays together is ONE aeroplane to the stack, so a
        single arriving behind it takes the next level rather than the fifth."""
        ctl = atc.Controller(imc_profile())
        ctl.check_in("Pony 1-1", 4)
        ctl.report_beacon("Pony 1-1", 6000, 4)
        ctl.report_beacon("Hawk 1", 9000)
        self.assertEqual(len(ctl.aircraft), 2)
        # 5,000: the flight is cleared and keeps 4,000 until it leaves it. The
        # point of the row is that a four-ship costs ONE level, not four, and
        # that still holds one rung higher. [#108]
        self.assertEqual(ctl.get("Hawk 1").assigned_ft, 5000)

    def test_two_formations(self):
        ctl = atc.Controller(imc_profile())
        ctl.check_in("Pony 1-1", 2)
        ctl.check_in("Hawk 2-1", 2)
        self.assertEqual(len(ctl.aircraft), 2)
        ctl.report_beacon("Pony 1-1", 6000, 2)
        ctl.report_beacon("Hawk 2-1", 7000, 2)
        ctl.request_breakup("Pony 1")
        ctl.request_breakup("Hawk 2")
        texts(ctl)
        # Nothing is assigned by the break-up itself -- none of these four has
        # asked for an approach, and pre-assigning to a pilot who may not want
        # one is what the old two-step did. What matters here is that two
        # formations do not become one: each dissolved into its own members.
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
    controller has to tell apart -- and he has no names for them at all. He
    never did: the ones he used to read out were minted from the flight key,
    agreed with nobody, and live that produced two Mustangs addressed as "Pony
    one" and "Pony one one" -- adjacent and confusable.

    So the identification is a QUESTION now rather than a roll-call, which is
    both honest and what actually binds a voice to a track: the man says his
    own callsign on his own radio, and that is a fact rather than a guess.
    """

    def ctl(self, size):
        c = atc.Controller(profile())
        c.check_in("Pony 1-1", size)
        c.request_breakup("Pony 1-1")
        return c

    def breakup_call(self, c):
        return next(tx.text for tx in c.out if "break up" in tx.text)

    def test_each_of_them_is_asked_for_his_own_callsign(self):
        call = self.breakup_call(self.ctl(4))
        self.assertIn("check in individually", call.lower())
        self.assertIn("your own callsign", call.lower())

    def test_no_callsign_is_invented(self):
        """The regression that matters. Any member designation in this call is
        a name the engine made up -- there is nothing else it could be, since
        nobody has spoken as an individual yet."""
        call = self.breakup_call(self.ctl(4)).lower()
        for invented in ("pony one two", "pony one three", "pony one four"):
            self.assertNotIn(invented, call)

    def test_a_single_ship_is_not_asked_to_identify_itself(self):
        c = atc.Controller(profile())
        c.check_in("Pony 1-1", 1)
        c.request_breakup("Pony 1-1")
        for tx in c.out:
            self.assertNotIn("identify", tx.text)


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

    def test_he_is_asked_who_he_is(self):
        """The OPTIONS half of this test is gone with the minting. It used to
        assert that both member callsigns were offered back to him -- names the
        engine had invented, so offering them was inviting a pilot to adopt one.
        The question stands on its own: say your callsign."""
        from marshall.atc import intents
        handled = intents.dispatch(
            self.ctl, intents.Intent(kind=intents.IntentKind.REPORT_BEACON,
                                     callsign="Pony 1", altitude_ft=5000))
        self.assertTrue(handled, "silence would be worse than a guess")
        said_now = " ".join(t.text for t in self.ctl.out).lower()
        self.assertIn("say your callsign", said_now)
        self.assertIn("intentions", said_now)

    def test_no_empty_list_is_read_out(self):
        """It said "I have ." -- with nothing after the "have" -- the moment
        the engine stopped minting members and this phrase went on formatting
        the list anyway."""
        from marshall.atc import intents
        intents.dispatch(
            self.ctl, intents.Intent(kind=intents.IntentKind.REPORT_BEACON,
                                     callsign="Pony 1", altitude_ft=5000))
        said_now = " ".join(t.text for t in self.ctl.out).lower()
        self.assertNotIn("i have .", said_now)
        self.assertNotIn("i have ,", said_now)

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
        self.ctl.request_breakup("Pony 1")
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


if __name__ == "__main__":
    unittest.main()
