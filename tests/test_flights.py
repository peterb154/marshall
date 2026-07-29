"""A person is his handle; a flight has a name; members have neither.

[ARCH-4] / #42, designed with the pilot on 29 July after looking up what real
formation procedure actually does.

Every identity failure of 28 July came from deriving a member's radio identity
from a flight number. This removes that rather than guarding it: after it there
are exactly two kinds of name on an ATC frequency -- a HANDLE (one person) and a
FLIGHT NAME (one group) -- and both are closed sets.
"""

import unittest

from marshall.atc import flights as F

HERE = ["sockeye", "Andre", "Shooter", "Viper"]     # who is connected


class TestCreatingAFlight(unittest.TestCase):
    """    "approach, request creation of Apex flight of 3"
        "Roger sockeye, you are now the lead of Apex flight of 3. Each member
         of apex flight check in to be joined"
        "approach, Andre, joining apex"  ->  "Roger Andre, joined to apex"

    THE LEAD NAMES NOBODY. An earlier version had him list his members --
    "forming Apex with Shooter and Andre" -- which meant matching several
    spoken names against a roster, reporting the ones it could not place, and
    being wrong about the flight's size whenever it mis-heard one.

    Here the only thing he says about his members is HOW MANY, and each pilot
    joins himself. So the only thing that can be mis-heard is a number, and a
    wrong number is visible at once: the flight never completes.
    """

    def test_just_the_name(self):
        self.assertEqual(
            F.parse_create("Approach, request creation of Apex flight"), "Apex")

    def test_a_count_is_ignored_if_he_says_one_anyway(self):
        """He may well say "of three" out of habit. It is not needed and not
        used -- there is nothing to be wrong about."""
        self.assertEqual(F.parse_create("form Apex flight of two"), "Apex")

    def test_an_ordinary_transmission_is_not_a_request(self):
        for said in ("Batumi Approach, Sockeye, ready for the radar approach",
                     "turn left heading one four zero"):
            with self.subTest(said):
                self.assertEqual(F.parse_create(said), "")


class TestJoiningYourself(unittest.TestCase):
    """A pilot can only join HIMSELF.

    Which is why there is no adoption, no rogue join for the lead to sort out
    afterwards, and no member list for anybody to mis-hear. It is also how a
    broken-out wingman comes back: rejoining is this, not a case of its own.
    """

    def setUp(self):
        self.r = F.Roster()
        self.r.create("Apex", "sockeye", now=1.0)

    def test_he_names_only_the_flight(self):
        """He does not have to say who he is -- the identity ladder already
        knows which aeroplane is transmitting. Saying his handle is good radio
        discipline and a cross-check, not something the system needs."""
        self.assertEqual(
            F.parse_joining("Approach, Andre, joining Apex", self.r.names())[0],
            "Apex")
        self.assertEqual(
            F.parse_joining("approach, joining apex flight", self.r.names())[0],
            "Apex")

    def test_a_flight_that_does_not_exist_is_not_joined(self):
        """...but he still gets an answer. The second value is the name he
        appears to have said, for the refusal and nothing else -- echoing a
        name back is safe in a way that ACTING on one is not."""
        known, said = F.parse_joining("joining Bolt", self.r.names())
        self.assertEqual(known, "")
        self.assertEqual(said, "Bolt")

    def test_silence_would_be_worse_than_unable(self):
        """"shooter, unable, foo flight doesn't exist". Saying nothing reads as
        a controller who did not hear him."""
        _known, said = F.parse_joining("Approach, Shooter joining Foo",
                                       self.r.names())
        self.assertEqual(said, "Foo")

    def test_joining_is_not_inferred_from_any_mention(self):
        self.assertEqual(
            F.parse_joining("Apex, level five thousand", self.r.names()),
            ("", ""))

    def test_he_joins(self):
        _f, why = self.r.join("Apex", "Andre", 0.3)
        self.assertEqual(why, "")
        self.assertTrue(self.r.of("Andre"))

    def test_a_member_of_another_flight_is_refused(self):
        self.r.create("Bolt", "Shooter", now=2.0)
        f, why = self.r.join("Apex", "Shooter", 0.4)
        self.assertIsNone(f)
        self.assertIn("Bolt", why)

    def test_he_must_be_within_a_mile(self):
        """"So if shooter says he's joining apex from 10 miles out, approach
        says negative shooter, you must be within 1 mile to join."

        Joining is the moment the controller STOPS separating him. A man who
        says it from ten miles away would go unseparated and unwatched while
        believing he was somebody's wingman.
        """
        f, why = self.r.join("Apex", "Shooter", 10.0)
        self.assertIsNone(f)
        self.assertIn("negative Shooter", why)
        self.assertIn("within 1 mile", why)

    def test_a_distance_nobody_can_measure_is_not_a_pass(self):
        """"I cannot see you both" and "you are together" are opposite
        answers, and defaulting the first to the second is how an unseen
        aeroplane joins a formation it is nowhere near."""
        f, why = self.r.join("Apex", "Viper", None)
        self.assertIsNone(f)
        self.assertIn("negative Viper", why)

    def test_anybody_may_join_at_any_time(self):
        """No declared size, so no full flight to refuse -- a fourth is as
        welcome as the second provided he is on the wing."""
        for who in ("Andre", "Shooter", "Viper"):
            with self.subTest(who):
                got, why = self.r.join("Apex", who, 0.5)
                self.assertIsNotNone(got, why)

    def test_joining_twice_is_not_an_error(self):
        self.r.join("Apex", "Andre", 0.3)
        _f, why = self.r.join("Apex", "Andre", 0.3)
        self.assertEqual(why, "")


# (TestAFlightIsNotOneUntilItIsComplete is gone with the concept. It guarded
# against the lead naming men who had never spoken -- and once he stopped
# naming anybody, every member joins on his OWN radio, so every member has been
# heard by construction. There was nothing left to protect.)


class TestAMemberNumberNeverReachesTheController(unittest.TestCase):
    """"Maybe apex1-1 is intra flight speak and never lands in atc"

    Which turns the hardest case into the easiest: a member callsign stops
    being something to resolve and becomes evidence the transmission is not
    addressed to the controller.
    """

    def test_a_known_flights_member_number_is_intra_flight(self):
        self.assertTrue(F.is_intra_flight("Apex 1-2", ["Apex"]))

    def test_the_flight_itself_is_not(self):
        self.assertFalse(F.is_intra_flight("Apex", ["Apex"]))

    def test_a_handle_is_not(self):
        self.assertFalse(F.is_intra_flight("Sockeye", ["Apex"]))

    def test_an_unknown_name_in_that_shape_is_still_heard(self):
        """Only for a flight we know. Refusing to hear somebody using the old
        numbering would be worse than the noise it removes."""
        self.assertFalse(F.is_intra_flight("Falcon 1-2", ["Apex"]))


class TestAPilotIsInZeroOrOneFlight(unittest.TestCase):
    def setUp(self):
        self.r = F.Roster()

    def test_creating(self):
        f, why = self.r.create("Apex", "sockeye", now=1.0)
        self.r.join("Apex", "Andre", 0.3)
        self.assertIsNotNone(f)
        self.assertEqual(why, "")
        self.assertEqual(f.lead, "sockeye")

    def test_a_second_flight_may_not_claim_him(self):
        """Refused rather than resolved: a man in two flights is separated
        twice, and the second answer is always wrong."""
        self.r.create("Apex", "sockeye", now=1.0)
        self.r.join("Apex", "Andre", 0.3)
        f, why = self.r.create("Bolt", "Andre", now=2.0)
        self.assertIsNone(f)
        self.assertIn("Andre", why)
        self.assertIn("Apex", why)

    def test_two_flights_with_one_name_is_refused(self):
        self.r.create("Apex", "sockeye", now=1.0)
        self.assertIsNone(self.r.create("Apex", "Shooter", now=2.0)[0])


class TestWhatTheControllerCallsHim(unittest.TestCase):
    def setUp(self):
        self.r = F.Roster()

    def test_a_single_is_his_handle(self):
        self.assertEqual(self.r.speaking_as("sockeye"), "sockeye")

    def test_a_member_is_the_flight(self):
        """While the flight is together the members have no radio identity."""
        self.r.create("Apex", "sockeye", now=1.0)
        self.r.join("Apex", "Andre", 0.3)
        self.assertEqual(self.r.speaking_as("sockeye"), "Apex")
        self.assertEqual(self.r.speaking_as("Andre"), "Apex")

    def test_any_member_may_speak_for_it(self):
        """The flight is not bound to one radio -- if lead goes down another
        member carries on, and the controller hears the same flight."""
        self.r.create("Apex", "sockeye", now=1.0)
        self.r.join("Apex", "Andre", 0.3)
        self.assertEqual(self.r.speaking_as("Andre"),
                         self.r.speaking_as("sockeye"))

    def test_after_the_split_everyone_is_himself_again(self):
        self.r.create("Apex", "sockeye", now=1.0)
        self.r.join("Apex", "Andre", 0.3)
        self.r.dissolve("Apex")
        self.assertEqual(self.r.speaking_as("sockeye"), "sockeye")
        self.assertEqual(self.r.speaking_as("Andre"), "Andre")

    def test_the_flight_name_then_belongs_to_nobody(self):
        self.r.create("Apex", "sockeye", now=1.0)
        self.r.join("Apex", "Andre", 0.3)
        self.r.dissolve("Apex")
        self.assertEqual(self.r.names(), [])


class TestLosingAMember(unittest.TestCase):
    def setUp(self):
        self.r = F.Roster()
        self.r.create("Apex", "sockeye", now=1.0)
        self.r.join("Apex", "Andre", 0.3)
        self.r.join("Apex", "Shooter", 0.4)

    def test_one_man_landing_does_not_end_the_flight(self):
        self.r.leaves("Shooter")
        self.assertEqual(self.r.speaking_as("sockeye"), "Apex")
        self.assertEqual(self.r.speaking_as("Shooter"), "Shooter")

    def test_losing_the_lead_ends_it(self):
        """The one loss a flight does not survive -- see TestLosingTheLead."""
        self.r.leaves("sockeye")
        self.assertEqual(self.r.speaking_as("Andre"), "Andre")

    def test_it_ends_when_nobody_is_left(self):
        for who in ("sockeye", "Andre", "Shooter"):
            self.r.leaves(who)
        self.assertEqual(self.r.names(), [])



# (TestAdoptingSomebody is gone. Nobody adopts anybody now: a pilot can only
# join himself, which removes the rogue-join problem rather than deferring it
# to the debrief, and removes the member list nobody could reliably hear.)


class TestLosingTheLead(unittest.TestCase):
    """    "And maybe if lead dies, the flight is dissolved? And the remaining
         members need to create (or recreate) a new one. Simple simple"

    Simpler than asking who is now, and more honest: the flight's geometry IS
    the lead's track, so when he is gone the flight has no position at all.
    Dissolving says that; promoting somebody pretends otherwise and starts
    vectoring off an aeroplane nobody chose.

    It is also the conservative failure. The survivors revert to individuals,
    so the controller starts separating them -- which is exactly what two men
    whose lead has just gone down need -- and they re-form through the ONE path
    there is for forming.
    """

    def setUp(self):
        self.r = F.Roster()
        self.r.create("Apex", "sockeye", now=1.0)
        self.r.join("Apex", "Andre", 0.3)
        self.r.join("Apex", "Shooter", 0.4)

    def test_the_flight_goes_with_him(self):
        self.assertEqual(self.r.leaves("sockeye"), "Apex")
        self.assertEqual(self.r.names(), [])

    def test_the_survivors_are_individuals_again(self):
        self.r.leaves("sockeye")
        self.assertEqual(self.r.speaking_as("Andre"), "Andre")
        self.assertEqual(self.r.speaking_as("Shooter"), "Shooter")

    def test_they_can_re_form_the_same_way_anybody_does(self):
        """No promotion rule, no special case -- the one path there is."""
        self.r.leaves("sockeye")
        _f, why = self.r.create("Apex", "Andre", now=2.0)
        self.assertEqual(why, "")
        self.r.join("Apex", "Shooter", 0.4)
        self.assertEqual(self.r.speaking_as("Shooter"), "Apex")

    def test_losing_a_wingman_does_not(self):
        """Nothing about the flight's geometry changed, so nothing changes."""
        self.r.leaves("Shooter")
        self.assertEqual(self.r.speaking_as("sockeye"), "Apex")
        self.assertEqual(self.r.speaking_as("Shooter"), "Shooter")



# (TestAdoptingSomebody is gone. Nobody adopts anybody now: a pilot can only
# join himself, which removes the rogue-join problem rather than deferring it
# to the debrief, and removes the member list nobody could reliably hear.)


if __name__ == "__main__":
    unittest.main()


class TestTellingThemTheLeadIsGone(unittest.TestCase):
    """"Apex flight, approach, flight lead sockeye is no longer on radar. Apex
    flight is now dissolved. Andre, what are your intentions?"

    The fact, then the consequence, then the question -- and the order is the
    point. "No longer on radar" is what the controller actually observed;
    "dissolved" is what follows from it; and intentions is the only thing left,
    because the survivors are individuals now and he has no idea what any of
    them wants.

    It also tells them something they may not know. A wingman whose lead has
    just gone down is busy, and being told by name is how he finds out that ATC
    is separating him again.
    """

    def call(self, survivors=("Andre", "Shooter")):
        return F.lead_lost_call("Apex", "sockeye", list(survivors))

    def test_it_says_what_was_observed(self):
        self.assertIn("no longer on radar", self.call())

    def test_it_names_the_lead_who_is_gone(self):
        self.assertIn("sockeye", self.call())

    def test_it_states_the_consequence(self):
        self.assertIn("dissolved", self.call())

    def test_it_asks_each_survivor(self):
        said = self.call()
        self.assertIn("Andre", said)
        self.assertIn("Shooter", said)
        self.assertIn("intentions", said)

    def test_the_fact_comes_before_the_consequence(self):
        said = self.call()
        self.assertLess(said.index("no longer on radar"), said.index("dissolved"))

    def test_a_lone_survivor_is_still_asked(self):
        self.assertIn("intentions", self.call(["Andre"]))

    def test_nobody_left_asks_nothing(self):
        """A two-ship whose lead goes down leaves one man; a single whose lead
        is himself leaves none, and there is nobody to ask."""
        self.assertNotIn("intentions", self.call([]))

if __name__ == "__main__":
    unittest.main()


class TestBreakingYourselfOut(unittest.TestCase):
    """"Approach, shooter separating (breaking out of, etc) apex flight."
    "Roger shooter, you are no longer in apex flight, what are your
     intentions?"

    A member must be able to do this WITHOUT THE LEAD. A lost wingman who
    transmits is otherwise answered as the flight, so the controller vectors
    the lead -- the man who needs help gets none and somebody who did not ask
    gets turned. It is also the case where the lead is least likely to be on
    the ball.
    """

    def setUp(self):
        self.r = F.Roster()
        self.r.create("Apex", "sockeye", now=1.0)
        self.r.join("Apex", "Andre", 0.3)
        self.r.join("Apex", "Shooter", 0.4)

    def test_several_ways_of_saying_it(self):
        """A pilot in trouble says whichever word comes first."""
        for said in ("Approach, Shooter separating from Apex flight",
                     "approach shooter breaking out of apex",
                     "Shooter detaching Apex",
                     "Shooter leaving Apex flight"):
            with self.subTest(said):
                self.assertEqual(F.parse_leaving(said, self.r.names()), "Apex")

    def test_it_is_not_inferred_from_any_mention(self):
        self.assertEqual(
            F.parse_leaving("Apex, level five thousand", self.r.names()), "")

    def test_he_is_out_and_the_flight_survives(self):
        self.r.leaves("Shooter")
        self.assertEqual(self.r.speaking_as("Shooter"), "Shooter")
        self.assertEqual(self.r.speaking_as("Andre"), "Apex")

    def test_he_can_come_back(self):
        """Rejoining is joining -- no separate concept, and the same one-mile
        rule applies to a man who has drifted."""
        self.r.leaves("Shooter")
        got, why = self.r.join("Apex", "Shooter", 0.5)
        self.assertIsNotNone(got, why)
        self.assertEqual(self.r.speaking_as("Shooter"), "Apex")

    def test_he_cannot_come_back_from_ten_miles(self):
        self.r.leaves("Shooter")
        got, why = self.r.join("Apex", "Shooter", 10.0)
        self.assertIsNone(got)
        self.assertIn("within 1 mile", why)

    def test_the_lead_breaking_out_dissolves_it(self):
        """His track is the flight's geometry, so there is no flight left to
        be in -- the same rule as losing him to a crash."""
        self.assertEqual(self.r.leaves("sockeye"), "Apex")
        self.assertEqual(self.r.names(), [])

if __name__ == "__main__":
    unittest.main()
