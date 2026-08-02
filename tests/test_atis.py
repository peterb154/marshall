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
