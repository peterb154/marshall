"""ATIS: the observation, the letter, and who owns the runway.

    "Atis should probably determine the active runway. Controllers should query
     the db for that info. One source of truth for that."

That last line is the architectural one and most of this file is about it. The
wind is a MEASUREMENT and the runway is a DECISION; a decision has one author.
`Field_.runway_in_use()` being a pure function of the wind is what makes it
tempting to call everywhere, and calling it twice is how the broadcast and the
taxi clearance come to name different strips -- both correct, both defensible,
and an aeroplane lined up the wrong way.
"""

import unittest

from marshall.atis import broadcast as B
from marshall.atis import observation as O
from marshall.core import route as R

K = R.KOBULETI_FIELD
BAT = R.BATUMI_FIELD


def obs(field=K, wind=90, kt=5, base_m=300, density=0, vis=80000, temp=20,
        qfe_hpa=1010.9):
    return O.observe(field, wind, kt, base_m, density, vis, temp,
                     29.92, O.hpa_to_inhg(qfe_hpa))


class TestTheCeilingIsAboveTheFIELD(unittest.TestCase):
    """The sim's cloud base is metres above SEA LEVEL. A ceiling is feet above
    the GROUND. Same class of error as grid versus true: two real quantities,
    one name."""

    def test_the_field_elevation_comes_off_the_base(self):
        o = obs(field=K, base_m=1000, density=9)
        # 1000 m MSL over a 59 ft field: 3281 - 59 = 3222 ft AGL.
        self.assertAlmostEqual(o.ceiling_ft_agl, 3222, delta=2)

    def test_two_fields_at_one_moment_report_different_ceilings(self):
        """Which is the whole point of doing it per aerodrome."""
        hi = obs(field=K, base_m=1000, density=9).ceiling_ft_agl
        lo = obs(field=BAT, base_m=1000, density=9).ceiling_ft_agl
        self.assertNotEqual(hi, lo)
        self.assertLess(hi, lo, "Kobuleti is the higher field")

    def test_a_field_inside_the_cloud_reports_zero_not_a_negative(self):
        o = obs(field=K, base_m=5, density=9)
        self.assertEqual(o.ceiling_ft_agl, 0)


class TestOnlyBrokenOrOvercastIsACeiling(unittest.TestCase):
    """Reporting a ceiling for scattered cloud sends a pilot for an instrument
    approach when he can see the runway from ten miles."""

    def test_scattered_is_cover_with_no_ceiling(self):
        o = obs(density=5, base_m=1000)
        self.assertEqual(o.sky, "scattered")
        self.assertIsNone(o.ceiling_ft_agl)
        self.assertNotIn("Ceiling", B.spoken(o, "Alpha", "1200"))

    def test_broken_is_a_ceiling(self):
        o = obs(density=8, base_m=1000)
        self.assertEqual(o.sky, "broken")
        self.assertIsNotNone(o.ceiling_ft_agl)
        self.assertIn("Ceiling", B.spoken(o, "Alpha", "1200"))

    def test_clear_says_so_and_reports_nothing(self):
        o = obs(density=0)
        self.assertEqual(o.sky, "sky clear")
        self.assertIsNone(o.ceiling_ft_agl)


class TestDewpointIsDerivedNotInvented(unittest.TestCase):
    """Cloud base in feet AGL is about 400 times the spread in Celsius, so the
    base the sim gives us fixes the spread. That makes the number agree with
    what the pilot can see out of the window."""

    def test_a_low_base_means_a_small_spread(self):
        low = obs(density=9, base_m=200, temp=20)
        high = obs(density=9, base_m=2000, temp=20)
        self.assertLess(low.temp_c - low.dewpoint_c,
                        high.temp_c - high.dewpoint_c)

    def test_it_is_never_above_the_temperature(self):
        for base in (0, 5, 50, 500, 5000):
            with self.subTest(base_m=base):
                o = obs(density=9, base_m=base, temp=10)
                self.assertLessEqual(o.dewpoint_c, o.temp_c)

    def test_with_no_cloud_a_dry_day_is_assumed(self):
        o = obs(density=0, temp=20)
        self.assertEqual(o.temp_c - o.dewpoint_c,
                         int(O.CLEAR_DAY_SPREAD_C))


class TestTheLetterMeansSomething(unittest.TestCase):
    """A letter that changed every minute would train pilots to ignore it, and
    then the one time it mattered nobody would notice."""

    def test_it_rotates(self):
        self.assertEqual(B.next_letter(None), "Alpha")
        self.assertEqual(B.next_letter("Alpha"), "Bravo")
        self.assertEqual(B.next_letter("Zulu"), "Alpha")

    def test_a_degree_of_wind_is_not_new_information(self):
        self.assertTrue(obs(wind=90).same_as(obs(wind=95)))

    def test_a_runway_change_is(self):
        east, west = obs(wind=90), obs(wind=270)
        self.assertNotEqual(east.runway, west.runway)
        self.assertFalse(east.same_as(west))

    def test_so_is_the_cloud_arriving(self):
        self.assertFalse(obs(density=0).same_as(obs(density=9, base_m=400)))

    def test_and_the_visibility_collapsing(self):
        self.assertFalse(obs(vis=80000).same_as(obs(vis=2000)))


class TestWhatItSaysOutLoud(unittest.TestCase):
    def test_it_names_the_field_the_letter_and_the_runway(self):
        said = B.spoken(obs(), "Bravo", "1450")
        self.assertIn("Kobuleti information Bravo", said)
        self.assertIn("Runway zero seven in use", said)
        self.assertTrue(said.rstrip().endswith("information Bravo."))

    def test_calm_is_a_word_not_three_noughts(self):
        self.assertIn("Wind calm", B.spoken(obs(kt=0), "Alpha", "1200"))

    def test_a_freezing_day_says_minus(self):
        self.assertIn("minus", B.spoken(obs(temp=-4), "Alpha", "1200"))

    def test_the_altimeter_is_four_digits(self):
        said = B.spoken(obs(), "Alpha", "1200")
        self.assertRegex(said, r"Altimeter (\w+ ){3}\w+\.")


class TestValidatingWhatThePilotHas(unittest.TestCase):
    """Forgiving about the phrasing, strict about the letter."""

    def test_every_way_a_pilot_says_it(self):
        for said in ("with Bravo", "information Bravo", "I have Bravo",
                     "Bravo", "we have information bravo."):
            with self.subTest(said=said):
                self.assertTrue(B.matches(said, "Bravo"))

    def test_THE_WRONG_LETTER_IS_NOT_ACCEPTED(self):
        """The whole reason this exists."""
        self.assertFalse(B.matches("with Alpha", "Bravo"))

    def test_saying_nothing_is_not_the_same_as_saying_the_wrong_one(self):
        """They get different answers on the radio: one is a prompt, the other
        is a correction with the current weather attached."""
        self.assertIsNone(B.said_letter("Kobuleti Clearance, Viper one one"))
        self.assertEqual(B.said_letter("with Alpha"), "Alpha")


class TestTheRunwayHasOneAuthor(unittest.TestCase):
    """The architectural one.

    `runway_in_use()` is a pure function of the wind, so any caller CAN compute
    it -- and two callers agree only while they read the same wind at the same
    instant. ATIS decides; everybody else asks.
    """

    def test_the_controller_follows_the_BROADCAST_not_the_wind(self):
        """The proof, and it has to be behavioural.

        The published runway is set to the one the wind does NOT favour. If the
        controller computes, he says the into-wind runway and disagrees with
        the recording; if he asks, he says what is on the air. That divergence
        is the actual failure and it only ever appears when the weather has
        moved since the recording -- which no amount of reading the code shows.
        """
        import unittest.mock as mock
        from marshall.atc import controller as atc

        into_wind = K.runway_in_use(90)          # 07 with an easterly
        published = K.ends[1]                    # 25, deliberately the other one
        self.assertNotEqual(into_wind, published)

        ctl = atc.Controller(R.BATUMI_ASR)
        ctl._me = R.KOB_GROUND
        with mock.patch("marshall.atis.store.runway_in_use",
                        return_value=published):
            said = ctl._runway_in_use()
        self.assertEqual(said, atc.spell_rwy(published),
                         "the controller ignored the broadcast and recomputed")

    def test_a_field_with_no_broadcast_still_gets_a_runway(self):
        """Most aerodromes have no ATIS. That is an arrangement, not an error,
        and a controller there still has to clear somebody to taxi."""
        from marshall.atis import store
        got = store.Current(field="Nowhere", letter=None, runway=7,
                            on_the_air=False)
        self.assertFalse(got.on_the_air)
        self.assertEqual(got.spoken_letter, "")


if __name__ == "__main__":
    unittest.main()


class TestTheLetterRotatesHourly(unittest.TestCase):
    """On this map it is the only thing that ever advances it.

        "Weather doesn't currently change in dcs missions. Rotate it hourly."

    Which is what a real ATIS does anyway -- re-recorded with the hourly
    observation whether anything moved or not. A broadcast that rotated on
    change alone would sit on Alpha all session, and a letter that never
    changes carries no information: a pilot who heard Alpha once never needs to
    listen again, which is the opposite of the point.
    """

    def test_an_hour_rotates_it_even_with_identical_weather(self):
        now, before = obs(), obs()
        self.assertTrue(now.same_as(before), "the weather did move; fix the test")
        self.assertTrue(B.due_for_rotation(now, before, B.ROTATE_AFTER_SEC))

    def test_within_the_hour_it_does_not(self):
        self.assertFalse(B.due_for_rotation(obs(), obs(), 60.0))

    def test_a_material_change_does_not_wait_for_the_hour(self):
        self.assertTrue(B.due_for_rotation(obs(wind=270), obs(wind=90), 60.0))

    def test_the_first_recording_is_not_a_rotation(self):
        """Nothing on the air yet means Alpha, not Bravo."""
        self.assertFalse(B.due_for_rotation(obs(), None, None))


class TestApproachConfirmsAndAsks(unittest.TestCase):
    """What a controller does with the letter, and what he must NOT do.

        "Atc should not gate the approach. In fact, approach should confirm
         they have information bravo and ask what approach they want."

    The second half fixes a complaint from the air -- "approach just assumed I
    was flying the ASR" -- and it is the same fault as everywhere else in this
    system: a controller answering a question the pilot did not ask. Batumi
    publishes two approaches and a visual is always available; which one he
    wants is his to say.
    """

    def setUp(self):
        import unittest.mock as mock
        from marshall.atis import store
        self.mock = mock.patch.object(
            store, "current",
            return_value=store.Current(field="Batumi", letter="Bravo",
                                       runway=13, on_the_air=True))
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def said(self, station, letter=""):
        from marshall.atc import controller as atc
        from marshall.atc import intents as I
        ctl = atc.Controller(R.BATUMI_ASR)
        ctl.t = 0.0
        ctl._me = station
        I.dispatch(ctl, I.Intent(kind=I.IntentKind.CHECK_IN,
                                 callsign="Sockeye", atis_letter=letter))
        return " ".join(t.text for t in ctl.out)

    def test_the_right_letter_is_confirmed(self):
        self.assertIn("Bravo is current", self.said(R.APPROACH, "Bravo"))

    def test_the_wrong_letter_is_corrected_and_NOT_refused(self):
        """He is working from weather that has moved, which is the entire point
        of the letter existing. He is told, and the sortie continues."""
        got = self.said(R.APPROACH, "Alpha")
        self.assertIn("Bravo", got)
        self.assertIn("not Alpha", got)
        for refusal in ("unable", "denied", "cannot", "before I can"):
            with self.subTest(word=refusal):
                self.assertNotIn(refusal, got.lower())

    def test_saying_nothing_is_a_prompt_not_a_telling_off(self):
        got = self.said(R.APPROACH, "")
        self.assertIn("Advise you have information Bravo", got)

    def test_HE_IS_ALWAYS_ASKED_WHAT_HE_WANTS(self):
        """Never assumed. Two approaches are published here and a visual is
        always available."""
        for letter in ("Bravo", "Alpha", ""):
            with self.subTest(letter=letter):
                self.assertIn("Say your request", self.said(R.APPROACH, letter))

    def test_tower_does_not_ask_about_the_atis(self):
        """Asking a man on short final which information he has is noise at the
        worst possible moment."""
        got = self.said(R.TOWER, "")
        self.assertNotIn("information", got.lower())

    def test_a_controller_greets_as_HIMSELF(self):
        """This read the enroute station unconditionally, so Batumi Approach
        greeted a pilot as "Georgia Center". The engine is blind by design and
        that was right while it had no idea who it was -- it has known since
        `_me` arrived."""
        self.assertIn("Batumi Approach", self.said(R.APPROACH, "Bravo"))
        self.assertIn("Kobuleti Clearance", self.said(R.KOB_CLEARANCE, ""))

    def test_a_ground_seat_does_not_ask_for_a_position_report(self):
        """"Report BATUMI inbound" from Clearance, to a man who has not started
        his engine, is a radar controller's line out of the wrong mouth."""
        self.assertNotIn("report", self.said(R.KOB_CLEARANCE, "").lower())
