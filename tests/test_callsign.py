"""Callsign parsing: the flight/member split everything else is built on."""

import unittest

from marshall.atc import callsign as C


class TestParse(unittest.TestCase):
    def test_member_callsign(self):
        c = C.parse("Pony 1-2")
        self.assertEqual(c.flight, "Pony 1")
        self.assertEqual(c.member, 2)
        self.assertFalse(c.is_flight)
        self.assertEqual(c.canonical, "Pony 1-2")

    def test_lead_is_member_one(self):
        c = C.parse("Pony 1-1")
        self.assertEqual((c.flight, c.member), ("Pony 1", 1))

    def test_flight_address_has_no_member(self):
        for text in ("Pony 1", "Pony 1 flight", "Pony one flight",
                     "Pony one one flight"):
            with self.subTest(text=text):
                c = C.parse(text)
                self.assertEqual(c.flight, "Pony 1", text)
                self.assertIsNone(c.member, text)
                self.assertTrue(c.is_flight, text)

    def test_spoken_digits_parse_like_numerals(self):
        self.assertEqual(C.parse("Pony one one"), C.parse("Pony 1-1"))
        self.assertEqual(C.parse("Pony niner two"), C.parse("Pony 9-2"))

    def test_single_number_is_a_flight_designator(self):
        # A lone ship is simply a flight of one -- "Pony 2" names the whole
        # (one-aircraft) flight, not member 2 of some flight "Pony".
        c = C.parse("Pony 2")
        self.assertEqual((c.flight, c.member), ("Pony 2", None))

    def test_bare_name(self):
        c = C.parse("Sockeye")
        self.assertEqual((c.flight, c.member), ("Sockeye", None))
        self.assertEqual(c.canonical, "Sockeye")

    def test_empty(self):
        self.assertEqual(C.parse("").flight, "")
        self.assertEqual(C.parse(None).flight, "")

    def test_dcs_unit_name(self):
        # DCS names a group's units Enfield11, Enfield12... which happens to be
        # exactly the flight/member reading. Radar labels correlate for free.
        c = C.parse("Enfield11")
        self.assertEqual((c.flight, c.member), ("Enfield 1", 1))


class TestSpoken(unittest.TestCase):
    def test_digits_never_merge(self):
        # "Pony eleven" would be a different aeroplane.
        self.assertEqual(C.parse("Pony 1-1").spoken, "Pony one one")

    def test_no_dash_reaches_polly(self):
        for text in ("Pony 1-1", "Pony 1-4", "Pony 2"):
            self.assertNotIn("-", C.parse(text).spoken)

    def test_flight_form_is_opt_in(self):
        # Whether a callsign names a formation is not knowable from the string,
        # so `spoken` never guesses -- only the controller, which knows the size,
        # asks for the flight form.
        c = C.parse("Pony 2")
        self.assertEqual(c.spoken, "Pony two")
        self.assertEqual(c.spoken_flight, "Pony two flight")


class TestMembers(unittest.TestCase):
    def test_members_lead_first(self):
        self.assertEqual(C.parse("Pony 1").members(4),
                         ["Pony 1-1", "Pony 1-2", "Pony 1-3", "Pony 1-4"])

    def test_members_of_a_member_callsign(self):
        # Lead asking on behalf of the flight still enumerates the flight.
        self.assertEqual(C.parse("Pony 1-1").members(2), ["Pony 1-1", "Pony 1-2"])

    def test_flight_of_and_same_flight(self):
        self.assertEqual(C.flight_of("Pony 1-3"), "Pony 1")
        self.assertTrue(C.same_flight("Pony 1-1", "Pony 1-4"))
        self.assertFalse(C.same_flight("Pony 1-1", "Pony 2-1"))
        self.assertFalse(C.same_flight("", "Pony 1-1"))


if __name__ == "__main__":
    unittest.main()


class TestOrdinarySpeechIsNotAnAeroplane(unittest.TestCase):
    """Every one of these produced a ghost in a live separation stack, where
    real aircraft were then sequenced behind something nobody had flown."""

    def test_verbs_that_take_a_number(self):
        for said in ("I need two more minutes",
                     "I have two aircraft in sight",
                     "give me two minutes",
                     "I see two contacts",
                     "about three miles",
                     "just one more turn"):
            with self.subTest(said=said):
                self.assertEqual(C.extract(said), "")

    def test_real_callsigns_still_extract(self):
        self.assertEqual(C.extract("Pony one one, checking in"), "Pony 1-1")
        self.assertEqual(C.extract("Hoover one two, level five"), "Hoover 1-2")
        self.assertEqual(C.extract("Hammer one, flight of two"), "Hammer 1")


class TestWhoIsTalkingByConvention(unittest.TestCase):
    """"[who you are calling], [who you are], [message]" -- the ORDER carries
    meaning, and taking the first callsign bound a pilot's radio to the wingman
    he was calling.

    Found live: "Hoover one two, Hoover one one, join up" rebound the speaker to
    Hoover 1-2, which then made the ship-to-ship check compare him with himself
    and answer a call that was never his.
    """

    def test_two_callsigns_means_the_second_is_him(self):
        self.assertEqual(C.speaker_in("Hoover one two, Hoover one one, join up"),
                         "Hoover 1-1")
        self.assertEqual(
            C.speaker_in("Pony one two, Pony one one, you are cleared to cross"),
            "Pony 1-1")

    def test_one_callsign_is_his_own(self):
        self.assertEqual(C.speaker_in("Hoover one one, request the approach"),
                         "Hoover 1-1")

    def test_a_station_does_not_count_as_a_callsign(self):
        for said in ("Batumi Approach, Hoover one one, checking in",
                     "Sentry, Hammer one one, request a target"):
            with self.subTest(said=said):
                self.assertEqual(len(C.extract_all(said)), 1)

    def test_nothing_said_is_nobody(self):
        self.assertEqual(C.speaker_in("four thousand level"), "")
