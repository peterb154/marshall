"""Two aerodromes, and everything that was only ever safe because there was one.

    "Makes me think we should add another airport and another set of controllers
     now, to test ownership and assignment."

WHY THIS FILE EXISTS. Adding Kobuleti did not break anything by changing
behaviour -- it broke things by making an ambiguity REACHABLE. Every fault below
had been in the code for weeks, correct by accident, because a question with one
possible answer cannot be answered wrongly:

    station_for("tower")        one Tower existed, so first-match was right
    channels_for()              four presets, so `stations[:4]` lost nothing
    "ABCD"[i]                   four buttons, so the string never ran out
    field_origin(profile)       one field, so the profile's beacon was his

None of those are bugs you can find by reading them. They are bugs you find by
adding the second thing, and then only if something checks -- which is what this
file is. Each test names the wrong answer it prevents, because in every case the
wrong answer is PLAUSIBLE: a real controller, a real frequency, a real distance,
just belonging to the wrong airport.
"""

import unittest

from marshall.core import route as R
from marshall.mission import build as mb

P = R.BATUMI_ASR


class TestARoleBelongsToAField(unittest.TestCase):
    """The ambiguity itself."""

    def test_each_field_resolves_to_its_own_controllers(self):
        for field, role, want in (
                ("Kobuleti", "clearance", "Kobuleti Clearance"),
                ("Kobuleti", "ground", "Kobuleti Ground"),
                ("Kobuleti", "tower", "Kobuleti Tower"),
                ("Kobuleti", "departure", "Kobuleti Departure"),
                ("Kobuleti", "approach", "Kobuleti Departure"),
                ("Batumi", "approach", "Batumi Approach"),
                ("Batumi", "departure", "Batumi Approach"),
                ("Batumi", "tower", "Batumi Tower"),
                ("Batumi", "ground", "Batumi Ground"),
                ("Batumi", "clearance", "Batumi Ground")):
            with self.subTest(field=field, role=role):
                self.assertEqual(P.station_for(role, field=field).name, want)

    def test_a_field_never_borrows_the_other_fields_seat(self):
        """Each field staffs its own, and the answer is HIS -- never the one
        forty miles away."""
        self.assertEqual(P.station_for("tower", field="Kobuleti").name,
                         "Kobuleti Tower")
        self.assertEqual(P.station_for("ground", field="Batumi").name,
                         "Batumi Ground")

    def test_an_unstaffed_role_is_none_rather_than_somebody_elses(self):
        """The failure that has to stay a failure. Returning ANY station here
        is worse than returning nothing: nothing is caught, a wrong controller
        is spoken to."""
        self.assertIsNone(P.station_for("approach", field="Nowhere"))
        self.assertIsNone(P.station_for("nosuchrole", field="Batumi"))

    def test_region_controllers_are_reachable_from_everywhere(self):
        """Center and Sentry own airspace, not an aerodrome. Asking which field
        they belong to is a category error, so they are fieldless and answer
        from either end of the route."""
        for field in ("Batumi", "Kobuleti"):
            with self.subTest(field=field):
                self.assertEqual(P.station_for("center", field=field).name,
                                 "Georgia Center")
        self.assertEqual(R.CENTER.field, "")
        self.assertEqual(R.OVERLORD.field, "")

    def test_an_unqualified_lookup_still_answers_for_the_simple_case(self):
        """Hundreds of call sites pass no field. They must keep working -- the
        default is permissive on purpose, and the docstring says why."""
        self.assertIsNotNone(P.station_for("tower"))
        self.assertIsNotNone(P.station_for("center"))


class TestEveryFrequencyReachesSomebody(unittest.TestCase):
    """A preset that reaches nobody is discovered in the air."""

    def test_every_frequency_the_bridge_monitors_resolves(self):
        for s in P.stations:
            for hz in s.freqs:
                with self.subTest(mhz=hz):
                    self.assertIsNotNone(P.station_on(hz),
                                         f"{hz} reaches nobody")

    def test_no_two_facilities_share_a_frequency(self):
        """Two controllers on one number means one of them is unreachable, and
        which one depends on list order."""
        seen = {}
        for s in P.stations:
            for hz in s.freqs:
                with self.subTest(mhz=hz):
                    self.assertNotIn(hz, seen,
                                     f"{s.name} collides with {seen.get(hz)}")
                    seen[hz] = s.name

    def test_every_frequency_is_tunable_vhf(self):
        for s in P.stations:
            for hz in s.freqs:
                with self.subTest(station=s.name, mhz=hz):
                    self.assertGreaterEqual(hz, 108.0)
                    self.assertLessEqual(hz, 156.0)


class TestTheLadder(unittest.TestCase):
    """Seven rungs, in the order the pilot was promised.

        "k clearance 1, k ground 2, k departure 3, center 4, b approach 5,
         b tower 6, b ground 7"
    """

    # EIGHT RUNGS. Kobuleti gained a Tower when Ground stopped clearing
    # take-offs, and the renumbering is deliberate -- everything that prints a
    # card reads PRESET_LADDER, so the aeroplane, the kneeboard and the
    # controller move together or not at all.
    EXPECTED = [
        (1, "Kobuleti Clearance", 125.100),
        (2, "Kobuleti Ground", 121.800),
        (3, "Kobuleti Tower", 133.000),
        (4, "Kobuleti Departure", 123.300),
        (5, "Georgia Center", 139.000),
        (6, "Batumi Approach", 124.425),
        (7, "Batumi Tower", 118.600),
        (8, "Batumi Ground", 121.900),
    ]

    def test_the_ladder_is_what_was_asked_for(self):
        for n, name, hz in self.EXPECTED:
            with self.subTest(preset=n):
                s = R.PRESET_LADDER[n - 1]
                self.assertEqual(s.name, name)
                self.assertAlmostEqual(s.freq_mhz, hz, places=3)
                self.assertEqual(R.preset_of(s), n)

    def test_the_card_the_mission_writes_matches_the_ladder(self):
        """The card, the aeroplane's radio and the kneeboard come from one
        source. A mismatch is a pilot transmitting to nobody, and it has
        happened."""
        card = mb.channels_for(P)
        for n, _name, hz in self.EXPECTED:
            with self.subTest(preset=n):
                self.assertAlmostEqual(dict(card)[n], hz, places=3)

    def test_sentry_keeps_a_button_above_the_ladder(self):
        """Not a rung -- a commander -- but still reachable. He used to fall off
        the end when the card was sliced to four."""
        self.assertIsNone(R.preset_of(R.OVERLORD))
        last = len(R.PRESET_LADDER) + 1
        self.assertAlmostEqual(dict(mb.channels_for(P))[last], 131.000, places=3)

    def test_the_card_is_no_longer_truncated_to_four(self):
        """The regression this replaces: `stations[:4]` silently dropped Batumi
        Approach, Tower and Ground -- the whole arrival."""
        card = dict(mb.channels_for(P))
        self.assertGreaterEqual(len(card), 7)
        for hz in (124.425, 118.600, 121.900):
            with self.subTest(mhz=hz):
                self.assertIn(hz, card.values())


class TestAShortRadioGetsTheRightFour(unittest.TestCase):
    """An SCR-522 has four buttons and the first four are the wrong four."""

    def test_a_warbird_at_batumi_gets_batumi(self):
        got = [hz for _, hz in mb.channels_for(P, limit=4, home="Batumi")]
        self.assertIn(124.425, got)          # his approach
        self.assertIn(118.600, got)          # his tower
        self.assertIn(139.000, got)          # and the region controller
        self.assertNotIn(125.100, got, "given the other field's clearance")

    def test_a_warbird_at_kobuleti_gets_kobuleti(self):
        got = [hz for _, hz in mb.channels_for(P, limit=4, home="Kobuleti")]
        self.assertIn(125.100, got)          # his clearance
        self.assertIn(121.800, got)          # his ground
        self.assertIn(133.000, got)          # his tower
        self.assertNotIn(124.425, got, "given the other field's approach")

    def test_the_region_controller_always_survives_the_cut(self):
        """He is reachable from anywhere, which is exactly what makes him worth
        one of only four buttons."""
        for home in ("Batumi", "Kobuleti"):
            with self.subTest(home=home):
                got = [hz for _, hz in mb.channels_for(P, limit=4, home=home)]
                self.assertIn(139.000, got)

    def test_a_four_button_radio_is_still_a_preset_panel(self):
        """The bar that replaced "can it hold the WHOLE card".

        All-or-nothing was safe at four rungs and silently disarmed every
        warbird at seven -- no card at all, stock presets, kneeboard printing
        something else. `MIN_PRESET_PANEL` is the smallest real bank."""
        self.assertLessEqual(mb.MIN_PRESET_PANEL, 4)


class TestTheButtonLabel(unittest.TestCase):
    """`"ABCD"[i]` in six files, and a seven-rung ladder."""

    def test_labels_are_numbers_and_do_not_run_out(self):
        self.assertEqual([R.preset_label(n) for n in range(1, 9)],
                         ["1", "2", "3", "4", "5", "6", "7", "8"])

    def test_a_period_card_can_still_ask_for_letters(self):
        self.assertEqual(R.preset_label(1, letters=True), "A")
        self.assertEqual(R.preset_label(4, letters=True), "D")

    def test_a_letter_card_falls_back_rather_than_raising(self):
        """The actual crash. Past D there is no letter, and the answer must be
        a number rather than an IndexError halfway through rendering a page a
        pilot is about to fly with."""
        self.assertEqual(R.preset_label(5, letters=True), "5")


class TestTheKneeboardSurvivesSevenStations(unittest.TestCase):
    """Rendered, not imported. The bug was in an f-string."""

    def test_every_page_renders(self):
        import importlib
        for mod in ("comms", "navlog", "brief", "asr_plate", "plate", "plans"):
            with self.subTest(page=mod):
                m = importlib.import_module(f"marshall.kneeboard.{mod}")
                self.assertTrue(m.build(), f"{mod} rendered nothing")

    def test_the_comms_card_lists_every_rung(self):
        from marshall.kneeboard import comms
        html = comms.build()
        for s in R.PRESET_LADDER:
            with self.subTest(station=s.name):
                self.assertIn(s.name, html)
                self.assertIn(f"{s.freq_mhz:.3f}", html)

    def test_the_comms_card_says_which_field_each_seat_is_at(self):
        from marshall.kneeboard import comms
        html = comms.build()
        self.assertIn(R.DEPARTURE_FIELD, html)
        self.assertIn(R.ARRIVAL_FIELD, html)

    def test_the_nav_log_shows_the_flight_being_flown(self):
        """It has been wrong about the journey twice, both times by continuing
        to show a route somebody used to fly."""
        from marshall.kneeboard import navlog
        html = navlog.build()
        for fix in R.FIXES:
            with self.subTest(fix=fix.name):
                self.assertIn(fix.name, html)


class TestTheWindPicksTheRunways(unittest.TestCase):
    """The runway in use is COMPUTED, and it caught a live bug.

        "'Runway in use' should probably be computed -- based on weather
         (which is measured from the sim)."

    Asked for taxi, Kobuleti Ground cleared an aircraft to runway 25 with the
    wind at 090 -- the downwind end of his own runway. The plate described only
    the field being approached, so the departure field's controllers had a
    frequency and nothing else, and they guessed rather than saying so.
    """

    def test_todays_wind_gives_both_fields_their_into_wind_end(self):
        self.assertEqual(R.BATUMI_FIELD.runway_in_use(), 13)
        self.assertEqual(R.KOBULETI_FIELD.runway_in_use(), 7)

    def test_the_other_end_when_the_wind_turns_round(self):
        self.assertEqual(R.BATUMI_FIELD.runway_in_use(300), 31)
        self.assertEqual(R.KOBULETI_FIELD.runway_in_use(250), 25)

    def test_the_designator_is_published_and_not_derived_from_the_heading(self):
        """Batumi's landing heading is 124 magnetic, which ROUNDS to 12 -- and
        DCS does call it 12 -- while the current plate says 13/31, because
        magnetic drift renamed it. Deriving the name from the number gave
        "runway 12" and "runway 06", which are on nobody's chart."""
        self.assertEqual(R.BATUMI_FIELD.ends, (13, 31))
        self.assertEqual(R.KOBULETI_FIELD.ends, (7, 25))
        self.assertEqual(round(R.BATUMI_FIELD.runway / 10), 12)      # the trap
        self.assertNotEqual(R.BATUMI_FIELD.runway_in_use(), 12)

    def test_a_calm_wind_does_not_flip_the_runway(self):
        """Ties go to the published end. A runway that oscillates on rounding
        is worse than one that is occasionally downwind by a knot."""
        for f in (R.BATUMI_FIELD, R.KOBULETI_FIELD):
            with self.subTest(field=f.name):
                across = (f.runway + 90) % 360
                self.assertEqual(f.runway_in_use(across), f.ends[0])

    def test_the_approach_profile_agrees_with_the_computed_runway(self):
        """The ASR is flown to a runway and the field computes one. If they
        ever disagree, the controller vectors to one and clears to the other.

        COMPARED AS INTEGERS ON PURPOSE, and the reason is a small mess worth
        recording: `ApproachProfile.runway` is the STRING "13" and
        `Field_.ends` are ints. Both print identically and `"13" != 13`, so
        anything comparing them directly is quietly always-unequal. Normalised
        here rather than papered over -- the two should become one type, and
        until they do this is the test that would notice the runway drifting
        apart from the approach flown to it.
        """
        self.assertEqual(int(R.BATUMI_ASR.runway),
                         int(R.BATUMI_FIELD.runway_in_use()))


class TestThePlateKnowsAboutTheDepartureField(unittest.TestCase):
    """Three of seven controllers worked an aerodrome the plate never named."""

    def plate(self):
        from marshall.atc import briefing
        return briefing._departure_field()

    def test_it_names_the_field_and_its_runway_in_use(self):
        txt = " ".join(self.plate())
        self.assertIn("KOBULETI", txt.upper())
        self.assertIn("07", txt)
        self.assertIn(str(R.KOBULETI_FIELD.elevation_ft), txt)

    def test_it_says_ground_is_also_the_tower(self):
        """The one judgement call in the ladder. A controller who does not know
        he issues take-off clearances sends the pilot to a frequency that does
        not exist."""
        txt = " ".join(self.plate()).lower()
        self.assertIn("tower", txt)
        self.assertIn("take-off", txt)

    def test_it_warns_against_reading_batumis_numbers(self):
        """The failure shape this whole day has been about: a real number
        belonging to the wrong airport."""
        self.assertIn("Batumi", " ".join(self.plate()))

    def test_the_runway_on_the_plate_follows_the_wind(self):
        """Not a hardcoded 07. Change the wind and the plate must change."""
        self.assertIn(f"**{R.KOBULETI_FIELD.runway_in_use():02d}**",
                      " ".join(self.plate()))


if __name__ == "__main__":
    unittest.main()
