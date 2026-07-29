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


class TestReadingTheDeclaration(unittest.TestCase):
    """"Georgia Center, Sockeye -- forming Apex flight of three with Shooter
    and Andre" """

    def test_the_flight_and_its_members(self):
        name, members, unknown = F.parse_forming(
            "forming Apex flight of three with Shooter and Andre",
            "sockeye", HERE)
        self.assertEqual(name, "Apex")
        self.assertEqual(members, ["sockeye", "Shooter", "Andre"])
        self.assertEqual(unknown, [])

    def test_the_speaker_is_always_a_member(self):
        """A flight formed without the man who called it in would be nobody's."""
        _n, members, _u = F.parse_forming(
            "forming Apex with Shooter", "sockeye", HERE)
        self.assertIn("sockeye", members)

    def test_a_name_nobody_here_answers_to_is_reported(self):
        """Returned rather than dropped: a flight that quietly forms with two
        of the three asked for is worse than one that fails, because the
        controller would be separating a group whose size he is wrong about."""
        name, members, unknown = F.parse_forming(
            "forming Apex flight of three with Shooter and Bandit",
            "sockeye", HERE)
        self.assertEqual(name, "Apex")
        self.assertEqual(members, ["sockeye", "Shooter"])
        self.assertEqual(unknown, ["Bandit"])

    def test_a_mangled_handle_matches_nobody(self):
        """The closed set is the whole safety argument. Whisper turning a name
        into something that is nobody's handle yields nothing, which is the
        correct answer -- matching against every word English can produce is
        the mistake this project spent two days undoing."""
        _n, members, unknown = F.parse_forming(
            "forming Apex with Maintained", "sockeye", HERE)
        self.assertEqual(members, ["sockeye"])
        self.assertEqual(unknown, ["Maintained"])

    def test_an_ordinary_transmission_is_not_a_declaration(self):
        for said in ("Batumi Approach, Sockeye, request the radar approach",
                     "turn left heading one four zero",
                     "Apex, level five thousand"):
            with self.subTest(said):
                self.assertEqual(F.parse_forming(said, "sockeye", HERE)[0], "")


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

    def test_forming(self):
        f, why = self.r.form("Apex", ["sockeye", "Andre"], now=1.0)
        self.assertIsNotNone(f)
        self.assertEqual(why, "")
        self.assertEqual(f.lead, "sockeye")

    def test_a_second_flight_may_not_claim_him(self):
        """Refused rather than resolved: a man in two flights is separated
        twice, and the second answer is always wrong."""
        self.r.form("Apex", ["sockeye", "Andre"], now=1.0)
        f, why = self.r.form("Bolt", ["Andre", "Shooter"], now=2.0)
        self.assertIsNone(f)
        self.assertIn("Andre", why)
        self.assertIn("Apex", why)

    def test_two_flights_with_one_name_is_refused(self):
        self.r.form("Apex", ["sockeye"], now=1.0)
        self.assertIsNone(self.r.form("Apex", ["Shooter"], now=2.0)[0])


class TestWhatTheControllerCallsHim(unittest.TestCase):
    def setUp(self):
        self.r = F.Roster()

    def test_a_single_is_his_handle(self):
        self.assertEqual(self.r.speaking_as("sockeye"), "sockeye")

    def test_a_member_is_the_flight(self):
        """While the flight is together the members have no radio identity."""
        self.r.form("Apex", ["sockeye", "Andre"], now=1.0)
        self.assertEqual(self.r.speaking_as("sockeye"), "Apex")
        self.assertEqual(self.r.speaking_as("Andre"), "Apex")

    def test_any_member_may_speak_for_it(self):
        """The flight is not bound to one radio -- if lead goes down another
        member carries on, and the controller hears the same flight."""
        self.r.form("Apex", ["sockeye", "Andre"], now=1.0)
        self.assertEqual(self.r.speaking_as("Andre"),
                         self.r.speaking_as("sockeye"))

    def test_after_the_split_everyone_is_himself_again(self):
        self.r.form("Apex", ["sockeye", "Andre"], now=1.0)
        self.r.dissolve("Apex")
        self.assertEqual(self.r.speaking_as("sockeye"), "sockeye")
        self.assertEqual(self.r.speaking_as("Andre"), "Andre")

    def test_the_flight_name_then_belongs_to_nobody(self):
        self.r.form("Apex", ["sockeye", "Andre"], now=1.0)
        self.r.dissolve("Apex")
        self.assertEqual(self.r.names(), [])


class TestLosingAMember(unittest.TestCase):
    def setUp(self):
        self.r = F.Roster()
        self.r.form("Apex", ["sockeye", "Andre", "Shooter"], now=1.0)

    def test_one_man_landing_does_not_end_the_flight(self):
        self.r.leaves("Shooter")
        self.assertEqual(self.r.speaking_as("sockeye"), "Apex")
        self.assertEqual(self.r.speaking_as("Shooter"), "Shooter")

    def test_losing_the_lead_does_not_end_it_either(self):
        """Any member may speak for the flight, so it does not end because one
        aeroplane went home -- which is the case the pilot raised.

        It used to promote the next man silently. It does not: the lead's track
        is what the flight's geometry is computed from, so ATC asks instead.
        See TestLosingTheLead.
        """
        self.r.leaves("sockeye")
        self.assertEqual(self.r.speaking_as("Andre"), "Apex")
        self.assertTrue(self.r.of("Andre").needs_lead)

    def test_it_ends_when_nobody_is_left(self):
        for who in ("sockeye", "Andre", "Shooter"):
            self.r.leaves(who)
        self.assertEqual(self.r.names(), [])


if __name__ == "__main__":
    unittest.main()


class TestAdoptingSomebody(unittest.TestCase):
    """"Approach, Apex flight adopting Shooter"

    ANY MEMBER MAY DO IT, not only the lead:

        "I think that's harder than any member can adopt and it's fragile if
         lead dies (combat sim after all). So I think any member can do it.
         Lead will deal with rouge joins in debrief."

    Which is the right call: an ATC that enforces a flight's internal
    discipline is solving a problem that is not its own, and a rule depending
    on one particular aeroplane still being alive is a poor rule in a combat
    simulator.
    """

    def setUp(self):
        self.r = F.Roster()
        self.r.form("Apex", ["sockeye", "Andre"], now=1.0)

    def test_the_declaration_reads(self):
        name, who, unknown = F.parse_adopting(
            "Approach, Apex flight adopting Shooter", HERE)
        self.assertEqual((name, who, unknown), ("Apex", ["Shooter"], []))

    def test_several_at_once(self):
        _n, who, _u = F.parse_adopting("Apex adopts Shooter and Viper", HERE)
        self.assertEqual(who, ["Shooter", "Viper"])

    def test_a_name_nobody_answers_to_is_reported(self):
        """A flight that quietly grows by one fewer than was asked for leaves
        the controller wrong about its size."""
        _n, who, unknown = F.parse_adopting("Apex adopting Bandit", HERE)
        self.assertEqual((who, unknown), ([], ["Bandit"]))

    def test_he_joins(self):
        _f, why = self.r.join("Apex", "Shooter")
        self.assertEqual(why, "")
        self.assertEqual(self.r.speaking_as("Shooter"), "Apex")

    def test_a_member_of_another_flight_is_refused(self):
        self.r.form("Bolt", ["Shooter"], now=2.0)
        f, why = self.r.join("Apex", "Shooter")
        self.assertIsNone(f)
        self.assertIn("Bolt", why)

    def test_adopting_somebody_already_aboard_is_not_an_error(self):
        f, why = self.r.join("Apex", "Andre")
        self.assertIsNotNone(f)
        self.assertEqual(why, "")

    def test_rejoining_after_a_break_out_is_just_adoption(self):
        """The lost wingman case, and it needs no machinery of its own: he
        broke himself out to get vectors, and comes back the same way anybody
        joins."""
        self.r.leaves("Andre")
        self.assertEqual(self.r.speaking_as("Andre"), "Andre")
        self.r.join("Apex", "Andre")
        self.assertEqual(self.r.speaking_as("Andre"), "Apex")


class TestLosingTheLead(unittest.TestCase):
    """"lead crashes or de slots. Atc needs to see that even and ask apex
    flight who is the new lead."

    Not promoted silently. The lead's track is what the flight's geometry is
    computed from, so choosing his replacement without being told means
    vectoring off a position nobody agreed to -- and the flight would have no
    way to know it had happened.
    """

    def setUp(self):
        self.r = F.Roster()
        self.r.form("Apex", ["sockeye", "Andre", "Shooter"], now=1.0)

    def test_the_flight_survives_him(self):
        self.r.leaves("sockeye")
        self.assertEqual(self.r.speaking_as("Andre"), "Apex")

    def test_but_it_knows_it_has_no_lead(self):
        self.r.leaves("sockeye")
        self.assertTrue(self.r.of("Andre").needs_lead)

    def test_nobody_is_promoted_behind_their_backs(self):
        self.r.leaves("sockeye")
        self.assertEqual(self.r.of("Andre").lead, "sockeye")

    def test_the_answer_settles_it(self):
        self.r.leaves("sockeye")
        f, why = self.r.set_lead("Apex", "Shooter")
        self.assertEqual(why, "")
        self.assertEqual(f.lead, "Shooter")
        self.assertFalse(f.needs_lead)

    def test_somebody_outside_the_flight_cannot_be_made_lead(self):
        self.r.leaves("sockeye")
        f, why = self.r.set_lead("Apex", "Viper")
        self.assertIsNone(f)
        self.assertIn("not in", why)

    def test_losing_a_wingman_asks_nothing(self):
        self.r.leaves("Shooter")
        self.assertFalse(self.r.of("sockeye").needs_lead)
