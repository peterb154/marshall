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

    def test_the_name_and_the_count(self):
        self.assertEqual(
            F.parse_create("Approach, request creation of Apex flight of 3"),
            ("Apex", 3))

    def test_spoken_numbers_too(self):
        self.assertEqual(F.parse_create("form Apex flight of two"), ("Apex", 2))

    def test_an_ordinary_transmission_is_not_a_request(self):
        for said in ("Batumi Approach, Sockeye, request the radar approach",
                     "turn left heading one four zero"):
            with self.subTest(said):
                self.assertEqual(F.parse_create(said)[0], "")


class TestJoiningYourself(unittest.TestCase):
    """A pilot can only join HIMSELF.

    Which is why there is no adoption, no rogue join for the lead to sort out
    afterwards, and no member list for anybody to mis-hear. It is also how a
    broken-out wingman comes back: rejoining is this, not a case of its own.
    """

    def setUp(self):
        self.r = F.Roster()
        self.r.create("Apex", "sockeye", 3, now=1.0)

    def test_he_names_only_the_flight(self):
        """He does not have to say who he is -- the identity ladder already
        knows which aeroplane is transmitting. Saying his handle is good radio
        discipline and a cross-check, not something the system needs."""
        self.assertEqual(
            F.parse_joining("Approach, Andre, joining Apex", self.r.names()),
            "Apex")
        self.assertEqual(
            F.parse_joining("approach, joining apex flight", self.r.names()),
            "Apex")

    def test_a_flight_that_does_not_exist_is_not_joined(self):
        self.assertEqual(F.parse_joining("joining Bolt", self.r.names()), "")

    def test_joining_is_not_inferred_from_any_mention(self):
        self.assertEqual(
            F.parse_joining("Apex, level five thousand", self.r.names()), "")

    def test_he_joins(self):
        _f, why = self.r.join("Apex", "Andre")
        self.assertEqual(why, "")
        self.assertTrue(self.r.of("Andre"))

    def test_a_member_of_another_flight_is_refused(self):
        self.r.create("Bolt", "Shooter", 2, now=2.0)
        f, why = self.r.join("Apex", "Shooter")
        self.assertIsNone(f)
        self.assertIn("Bolt", why)

    def test_a_full_flight_is_refused(self):
        """He said three. A fourth is either a mis-hearing or somebody else's
        aeroplane, and quietly growing the flight makes the controller wrong
        about how many he is separating."""
        self.r.join("Apex", "Andre")
        self.r.join("Apex", "Shooter")
        f, why = self.r.join("Apex", "Viper")
        self.assertIsNone(f)
        self.assertIn("flight of 3", why)

    def test_joining_twice_is_not_an_error(self):
        self.r.join("Apex", "Andre")
        _f, why = self.r.join("Apex", "Andre")
        self.assertEqual(why, "")


class TestAFlightIsNotOneUntilItIsComplete(unittest.TestCase):
    """Between "flight of three" and the third man joining, the ones who HAVE
    joined are still individuals to the controller.

    A flight that ATC treats as one aeroplane while a member has never been
    heard is exactly what this design removes -- it would be separating three
    aeroplanes on the word of one man, one of whom might not be on frequency,
    or might not exist because a name came out of Whisper wrong.
    """

    def setUp(self):
        self.r = F.Roster()
        self.r.create("Apex", "sockeye", 3, now=1.0)

    def test_the_lead_alone_is_still_a_single(self):
        self.assertFalse(self.r.of("sockeye").complete)
        self.assertEqual(self.r.speaking_as("sockeye"), "sockeye")

    def test_part_way_is_still_singles(self):
        self.r.join("Apex", "Andre")
        self.assertEqual(self.r.speaking_as("Andre"), "Andre")

    def test_the_last_man_makes_it_a_flight(self):
        self.r.join("Apex", "Andre")
        self.r.join("Apex", "Shooter")
        self.assertTrue(self.r.of("sockeye").complete)
        for who in ("sockeye", "Andre", "Shooter"):
            self.assertEqual(self.r.speaking_as(who), "Apex")


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
        f, why = self.r.create("Apex", "sockeye", 2, now=1.0)
        self.r.join("Apex", "Andre")
        self.assertIsNotNone(f)
        self.assertEqual(why, "")
        self.assertEqual(f.lead, "sockeye")

    def test_a_second_flight_may_not_claim_him(self):
        """Refused rather than resolved: a man in two flights is separated
        twice, and the second answer is always wrong."""
        self.r.create("Apex", "sockeye", 2, now=1.0)
        self.r.join("Apex", "Andre")
        f, why = self.r.create("Bolt", "Andre", 2, now=2.0)
        self.assertIsNone(f)
        self.assertIn("Andre", why)
        self.assertIn("Apex", why)

    def test_two_flights_with_one_name_is_refused(self):
        self.r.create("Apex", "sockeye", 1, now=1.0)
        self.assertIsNone(self.r.create("Apex", "Shooter", 1, now=2.0)[0])


class TestWhatTheControllerCallsHim(unittest.TestCase):
    def setUp(self):
        self.r = F.Roster()

    def test_a_single_is_his_handle(self):
        self.assertEqual(self.r.speaking_as("sockeye"), "sockeye")

    def test_a_member_is_the_flight(self):
        """While the flight is together the members have no radio identity."""
        self.r.create("Apex", "sockeye", 2, now=1.0)
        self.r.join("Apex", "Andre")
        self.assertEqual(self.r.speaking_as("sockeye"), "Apex")
        self.assertEqual(self.r.speaking_as("Andre"), "Apex")

    def test_any_member_may_speak_for_it(self):
        """The flight is not bound to one radio -- if lead goes down another
        member carries on, and the controller hears the same flight."""
        self.r.create("Apex", "sockeye", 2, now=1.0)
        self.r.join("Apex", "Andre")
        self.assertEqual(self.r.speaking_as("Andre"),
                         self.r.speaking_as("sockeye"))

    def test_after_the_split_everyone_is_himself_again(self):
        self.r.create("Apex", "sockeye", 2, now=1.0)
        self.r.join("Apex", "Andre")
        self.r.dissolve("Apex")
        self.assertEqual(self.r.speaking_as("sockeye"), "sockeye")
        self.assertEqual(self.r.speaking_as("Andre"), "Andre")

    def test_the_flight_name_then_belongs_to_nobody(self):
        self.r.create("Apex", "sockeye", 2, now=1.0)
        self.r.join("Apex", "Andre")
        self.r.dissolve("Apex")
        self.assertEqual(self.r.names(), [])


class TestLosingAMember(unittest.TestCase):
    def setUp(self):
        self.r = F.Roster()
        self.r.create("Apex", "sockeye", 3, now=1.0)
        self.r.join("Apex", "Andre")
        self.r.join("Apex", "Shooter")

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
        self.r.create("Apex", "sockeye", 3, now=1.0)
        self.r.join("Apex", "Andre")
        self.r.join("Apex", "Shooter")

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
        _f, why = self.r.create("Apex", "Andre", 2, now=2.0)
        self.assertEqual(why, "")
        self.r.join("Apex", "Shooter")
        self.assertEqual(self.r.speaking_as("Shooter"), "Apex")

    def test_losing_a_wingman_does_not(self):
        """Nothing about the flight's geometry changed, so nothing changes."""
        self.r.leaves("Shooter")
        self.assertEqual(self.r.speaking_as("sockeye"), "Apex")
        self.assertEqual(self.r.speaking_as("Shooter"), "Shooter")


if __name__ == "__main__":
    unittest.main()


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
