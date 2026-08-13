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
                self.assertEqual(R.station_for(role, field=field).name, want)

    def test_a_field_never_borrows_the_other_fields_seat(self):
        """Each field staffs its own, and the answer is HIS -- never the one
        forty miles away."""
        self.assertEqual(R.station_for("tower", field="Kobuleti").name,
                         "Kobuleti Tower")
        self.assertEqual(R.station_for("ground", field="Batumi").name,
                         "Batumi Ground")

    def test_an_unstaffed_role_is_none_rather_than_somebody_elses(self):
        """The failure that has to stay a failure. Returning ANY station here
        is worse than returning nothing: nothing is caught, a wrong controller
        is spoken to."""
        self.assertIsNone(R.station_for("approach", field="Nowhere"))
        self.assertIsNone(R.station_for("nosuchrole", field="Batumi"))

    def test_region_controllers_are_reachable_from_everywhere(self):
        """Center and Sentry own airspace, not an aerodrome. Asking which field
        they belong to is a category error, so they are fieldless and answer
        from either end of the route."""
        for field in ("Batumi", "Kobuleti"):
            with self.subTest(field=field):
                self.assertEqual(R.station_for("center", field=field).name,
                                 "Georgia Center")
        self.assertEqual(R.CENTER.field, "")
        self.assertEqual(R.OVERLORD.field, "")

    def test_an_unqualified_lookup_still_answers_for_the_simple_case(self):
        """Hundreds of call sites pass no field. They must keep working -- the
        default is permissive on purpose, and the docstring says why."""
        self.assertIsNotNone(R.station_for("tower"))
        self.assertIsNotNone(R.station_for("center"))


class TestEveryFrequencyReachesSomebody(unittest.TestCase):
    """A preset that reaches nobody is discovered in the air."""

    def test_every_frequency_the_bridge_monitors_resolves(self):
        for s in R.STATIONS:
            for hz in s.freqs:
                with self.subTest(mhz=hz):
                    self.assertIsNotNone(R.station_on(hz),
                                         f"{hz} reaches nobody")

    def test_no_two_facilities_share_a_frequency(self):
        """Two controllers on one number means one of them is unreachable, and
        which one depends on list order."""
        seen = {}
        for s in R.STATIONS:
            for hz in s.freqs:
                with self.subTest(mhz=hz):
                    self.assertNotIn(hz, seen,
                                     f"{s.name} collides with {seen.get(hz)}")
                    seen[hz] = s.name

    def test_every_frequency_is_tunable_vhf(self):
        for s in R.STATIONS:
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

    def test_it_names_every_controller_at_the_field_with_his_frequency(self):
        """AND IT AGREES WITH THE STATION TABLE, which it did not.

        This block was hand-written prose and asserted that Kobuleti Ground was
        "on 133.0, who is also its Tower -- he issues taxi AND take-off
        clearance, there is no separate tower frequency". None of that has been
        true since Ground stopped wearing the Tower hat: Ground is 121.800 and
        Kobuleti Tower is a separate controller on 133.000.

        So the plate -- the one document the agent is told to believe -- told
        him Ground owned the runway, which is the exact thing #65 and #88 exist
        to prevent, asserted in his own briefing. The test pinned the stale
        claim rather than catching it, because it was written from the prose.

        Generated from the station table now, so the two cannot drift again.
        """
        txt = " ".join(self.plate())
        for s in R.STATIONS:
            if s.field != "Kobuleti":
                continue
            with self.subTest(station=s.name):
                self.assertIn(s.name, txt)
                self.assertIn(f"{s.freq_mhz:.1f}", txt)
        self.assertNotIn("also its Tower", txt)

    def test_it_warns_against_reading_batumis_numbers(self):
        """The failure shape this whole day has been about: a real number
        belonging to the wrong airport."""
        self.assertIn("Batumi", " ".join(self.plate()))

    def test_the_runway_on_the_plate_follows_the_wind(self):
        """Not a hardcoded 07. Change the wind and the plate must change."""
        self.assertIn(f"**{R.KOBULETI_FIELD.runway_in_use():02d}**",
                      " ".join(self.plate()))


def _foreign_numbers(field: str):
    """Every number belonging to some OTHER aerodrome, CHANNELS INCLUDED.

    The channels are the point. The frequency this bug actually leaked was
    Batumi Tower's 118.000, which is a `channels` entry and not its `freq_mhz`
    of 118.600 -- so a check that walked only `freq_mhz` passed against the
    broken brief and would have guarded nothing. A facility owns several
    numbers and every one of them is wrong at the wrong field.
    """
    for s in R.STATIONS:
        if getattr(s, "field", "") in ("", field):
            continue
        yield s, s.freq_mhz
        for c in getattr(s, "channels", ()) or ():
            yield s, c


class TestTheControllerIsHandedHisOwnFrequencies(unittest.TestCase):
    """The fifth thing that was correct by accident, found 7 August by driving
    the Kobuleti departure through the dry run.

    A controller was never handed ANY frequency except Departure's -- that one
    block having been added after a clearance and a taxi instruction disagreed
    about it. Everything else he said, he invented, and he invented it fluently:

        "Ground is one three three decimal zero"    that is Kobuleti TOWER
        "Tower is one one eight decimal zero"       that is BATUMI Tower

    The second one came out of the brief itself. The YOU ARE block carried a
    worked example of how to correct a pilot on the wrong button, and the
    example contained a literal frequency -- so the model lifted it as fact. An
    example in a prompt is data to a model.
    """

    def compose(self, me):
        from marshall.atc import agent_atc as A
        from marshall.atc import assembly
        return assembly.compose_message(
            A.Bridge(), scope="", known="Viper 1-1", transcript="request taxi",
            profile=R.BATUMI_ASR, me=me, fix=None, nxt=None, directive="",
            stack="", vectoring="", _flight={}, _flight_say="", claim="",
            name_say="")[0]

    def test_every_station_at_his_field_is_named(self):
        for me in (R.KOB_CLEARANCE, R.GROUND):
            msg = self.compose(me)
            for s in R.STATIONS:
                if getattr(s, "field", "") != me.field:
                    continue
                with self.subTest(who=me.name, names=s.name):
                    self.assertIn(s.name, msg,
                                  f"{me.name} is not told about {s.name}")

    def test_no_other_aerodromes_frequency_is_in_the_block(self):
        """The failure is never a nonsense number. It is a REAL frequency
        belonging to the wrong airport, said in perfect phraseology, and the
        pilot has no way to tell."""
        from marshall.atc import controller
        msg = self.compose(R.KOB_CLEARANCE)
        block = [ln for ln in msg.split("\n") if ln.startswith("YOUR FIELD")]
        self.assertTrue(block, "no field frequency block at all")
        for s, hz in _foreign_numbers(R.KOB_CLEARANCE.field):
            with self.subTest(stranger=f"{s.name} {hz}"):
                self.assertNotIn(controller.spell_freq(hz), block[0])

    def test_the_worked_example_carries_no_frequency_of_its_own(self):
        """A number in an example is a number the model will say. This is what
        put Batumi Tower's channel in a Kobuleti clearance."""
        from marshall.atc import controller
        msg = self.compose(R.KOB_CLEARANCE)
        head = msg.split("YOUR FIELD")[0]
        for s, hz in _foreign_numbers(R.KOB_CLEARANCE.field):
            with self.subTest(stranger=f"{s.name} {hz}"):
                self.assertNotIn(controller.spell_freq(hz), head,
                                 f"{s.name}'s {hz} is quoted at Kobuleti")

    def test_departure_is_his_fields_and_not_the_first_in_the_list(self):
        """`station_for` was rewritten to stop taking the first role match;
        this lookup kept doing it. Kobuleti Departure is listed first, so
        Kobuleti was right by accident and Batumi was about to send a pilot
        forty miles up the coast."""
        msg = self.compose(R.GROUND)          # Batumi Ground issues clearances
        want = R.station_for("departure", field="Batumi")
        line = [ln for ln in msg.split("\n")
                if ln.startswith("DEPARTURE FREQUENCY")]
        self.assertTrue(line, "Batumi Ground is told no departure frequency")
        self.assertIn(want.name, line[0])
        self.assertNotIn("Kobuleti", line[0])

    def test_the_atis_of_his_field_travels_with_them(self):
        msg = self.compose(R.KOB_CLEARANCE)
        self.assertIn("Kobuleti ATIS", msg)


class TestTheEngineIsToldWhichControllerItIs(unittest.TestCase):
    """`Controller._me` was read in six places and assigned in none.

    Found on the radio, 9 August, nine minutes before a take-off: Kobuleti
    Tower cleared an aircraft for take-off on RUNWAY ONE THREE. That is
    Batumi's runway. He was holding short of 07, at a field whose runway is 07,
    and had read back 07 twice.

    `_runway_in_use` falls back to ARRIVAL_FIELD when it does not know its own
    station, and it never knew: every read was `getattr(self, "_me", None)` and
    nothing ever set the attribute. `_owns` -- the rule that stops a controller
    issuing a clearance that is not his -- takes an unknown station as "blind by
    design, must not refuse", which is right as a default and wrong as a
    permanent condition.

    Invisible until the same day, because the ground clearances were being
    suppressed before anyone heard them. One fix exposed the other.
    """

    def controller(self, station):
        from marshall.atc import controller as C
        c = C.Controller(R.BATUMI_ASR)
        c._me = station
        return c

    def test_each_field_gets_its_own_runway(self):
        for station, want in ((R.KOB_TOWER, "zero seven"),
                              (R.KOB_GROUND, "zero seven"),
                              (R.TOWER, "one three"),
                              (R.GROUND, "one three")):
            with self.subTest(who=station.name):
                self.assertEqual(self.controller(station)._runway_in_use(), want)

    def test_the_bridge_actually_sets_it(self):
        """The half that was missing. A controller that CAN be told its station
        is worth nothing if the loop never tells it -- which was the state of
        this for as long as `_me` has existed."""
        import pathlib
        from marshall.atc import agent_atc as A
        src = pathlib.Path(A.__file__).read_text()
        self.assertIn("ctl._me = ", src,
                      "nothing in the bridge assigns the engine's station")

    def test_it_is_set_from_the_frequency_and_not_the_profile(self):
        """A role is unique only within an aerodrome, so the button he pressed
        is the only honest source. Taking it from the profile would name the
        arrival field's controller for every call of the sortie."""
        for station in (R.KOB_TOWER, R.KOB_GROUND, R.TOWER, R.GROUND):
            with self.subTest(who=station.name):
                self.assertIs(R.station_on(station.freq_mhz), station)


class TestNobodyIsSentToTheOtherAerodromesTower(unittest.TestCase):
    """The last three unscoped `station_for` calls, found in a live log.

    On final at BATUMI a pilot was told "contact Kobuleti Tower one three three
    decimal zero for landing", and after touchdown at Batumi he was welcomed by
    "Kobuleti Tower" -- the last thing said on the whole sortie. Both took the
    first role match from a list that happens to start with Kobuleti.

    The landing clearance was wrong the other way round: it read
    `profile.runway`, which is the runway of the approach being FLOWN, so
    Kobuleti Tower cleared a landing on runway one three.
    """

    def landed_on(self, station, profile=R.BATUMI_ASR):
        from marshall.atc import controller as C
        c = C.Controller(profile)
        c._me, c.working = station, station.role
        ac = c.get("Sockeye")
        ac.phase = C.Phase.CLEARED
        c.report_landed("Sockeye")
        return " ".join(t.text for t in c.take_out())

    def test_approach_hands_him_to_his_own_fields_tower(self):
        said = self.landed_on(R.APPROACH)
        self.assertIn("Batumi Tower", said)
        self.assertNotIn("Kobuleti", said)

    def test_a_kobuleti_seat_hands_him_to_kobuleti(self):
        self.assertIn("Kobuleti Tower", self.landed_on(R.KOB_DEPARTURE))

    def test_the_landing_clearance_names_HIS_runway(self):
        """Not the approach profile's. All three ground clearances -- taxi,
        take-off and landing -- must name one runway, and it is the one in use
        at the field he is actually at."""
        self.assertIn("runway one three", self.landed_on(R.TOWER))
        self.assertIn("runway zero seven", self.landed_on(R.KOB_TOWER))

    def test_the_welcome_after_touchdown_is_his_own_tower(self):
        from marshall.atc import controller as C
        for station, want, wrong in ((R.TOWER, "Batumi Tower", "Kobuleti"),
                                     (R.KOB_TOWER, "Kobuleti Tower", "Batumi")):
            with self.subTest(who=station.name):
                c = C.Controller(R.BATUMI_ASR)
                c._me = station
                c.get("Sockeye")
                c.report_down("Sockeye")
                said = " ".join(t.text for t in c.take_out())
                self.assertIn(want, said)
                self.assertNotIn(wrong, said)

    def test_no_unscoped_role_lookups_are_left_in_the_engine(self):
        """The class, not the instance. Five of these have been found one at a
        time; this fails on the sixth."""
        import pathlib
        import re
        for mod in ("controller.py", "agent_atc.py", "assembly.py"):
            src = (pathlib.Path(__file__).resolve().parents[1]
                   / "src" / "marshall" / "atc" / mod).read_text()
            bad = re.findall(r'station_for\(\s*"[a-z]+"\s*\)', src)
            with self.subTest(module=mod):
                self.assertEqual(bad, [], f"{mod} resolves a role with no field")


if __name__ == "__main__":
    unittest.main()


class TestAnotherFieldsFrequencyIsLookedUpNotRecalled(unittest.TestCase):
    """His own aerodrome is in the brief; everywhere else is a tool call.

        "giving the agent a tool to look up ANY frequency on demand is more
         scalable and we dont need to waste tokens on every call"

    That is the axis. A controller works ONE field, so its handful of lines is
    cheap and constant; the rest of the map is thirty aerodromes at four to
    eight seats each, carried on every transmission of every sortie to answer a
    question a pilot asks twice a night.
    """

    def brief(self, station):
        from marshall.atc import agent_atc as A
        from marshall.atc import assembly
        return assembly.compose_message(
            A.Bridge(), scope="", known="Sockeye",
            transcript="say the frequency for Batumi Tower", profile=R.BATUMI_ASR,
            me=station, fix=None, nxt=None, directive="", stack="",
            vectoring="", _flight={}, _flight_say="", claim="", name_say="")[0]

    def test_he_is_told_to_call_the_tool_for_anywhere_else(self):
        said = self.brief(R.KOB_CLEARANCE)
        self.assertIn("look_up_frequency", said)
        self.assertIn("must not", said.split("look_up_frequency")[1][:200])

    def test_his_own_fields_frequencies_are_still_handed_to_him(self):
        """Not replaced by the tool. A controller knows his own tower the way he
        knows his own name, and a round trip for it would be latency on the
        commonest question there is."""
        said = self.brief(R.KOB_CLEARANCE)
        self.assertIn("YOUR FIELD — Kobuleti", said)
        self.assertIn("Kobuleti Tower", said)

    def test_and_no_other_aerodromes_numbers_are_carried(self):
        """The scaling half. If another field's frequency is in the prompt, the
        tool has bought nothing."""
        from marshall.atc import controller
        head = self.brief(R.KOB_CLEARANCE)
        for s, hz in _foreign_numbers(R.KOB_CLEARANCE.field):
            with self.subTest(stranger=f"{s.name} {hz}"):
                self.assertNotIn(controller.spell_freq(hz), head)


class TestTheCheckInReplyDependsOnWhichWayHeIsGoing(unittest.TestCase):
    """One seat, two jobs.

        "why would it ask for the field in sight, and why would it be asking
         for information alpha at this field"

    He had just lifted off Kobuleti. Kobuleti Departure wears the approach hat
    -- `also=("approach",)`, correctly, because it works Kobuleti's arrivals too
    -- so `_owns("approach")` was true and a climbing aircraft got the ARRIVAL
    greeting. The seat cannot tell the two jobs apart, because a seat is not
    what tells them apart. The PHASE is, and `phases.py` has said so since it
    was written.
    """

    def greeting(self, station, phase):
        from marshall.atc import controller as C
        c = C.Controller(R.BATUMI_ASR)
        c._me = station
        c.get("Sockeye").sortie_phase = phase
        c.check_in("Sockeye")
        return " ".join(t.text for t in c.take_out())

    def test_a_departing_aircraft_is_not_asked_for_the_field(self):
        said = self.greeting(R.KOB_DEPARTURE, "departure")
        self.assertIn("radar contact", said)
        self.assertNotIn("field in sight", said)

    def test_nor_for_an_information_letter_he_has_already_left_behind(self):
        """The ATIS he needs is the one where he is GOING. He read a clearance
        back four minutes ago; he has said what he wants."""
        self.assertNotIn("information",
                         self.greeting(R.KOB_DEPARTURE, "departure").lower())

    def test_the_same_seat_working_an_arrival_still_asks(self):
        """The half that must not be lost. Kobuleti Departure genuinely does
        work Kobuleti's arrivals."""
        said = self.greeting(R.KOB_DEPARTURE, "arrival")
        self.assertIn("field in sight", said)

    def test_center_does_not_ask_a_man_thirty_miles_out(self):
        said = self.greeting(R.CENTER, "enroute")
        self.assertNotIn("field in sight", said)

    def test_a_ground_seat_asks_for_the_request_and_the_letter(self):
        """Clearance is one of the two positions that genuinely checks the
        ATIS, and a man on the ramp has not said what he wants yet."""
        said = self.greeting(R.KOB_CLEARANCE, "clearance")
        self.assertIn("Say your request", said)
        self.assertNotIn("field in sight", said)

    def test_a_voice_out_of_nowhere_is_still_treated_as_arriving(self):
        """Every sortie looked like this until the ladder grew a ground half:
        no phase, inbound, wanting an approach. Being asked when you are not
        arriving is untidy; NOT being asked when you are is a controller who has
        not understood what you want."""
        self.assertIn("field in sight", self.greeting(R.APPROACH, ""))


class AnArrivalFixIsNotEVIDENCEOFANYTHING(unittest.TestCase):
    """The fifth entry in this file's opening list, found the same way. [#145]

        field_origin(profile)   one field, so the profile's beacon was his
        check_in()              one profile carried an arrival fix, and it had
                                no ground seats to contradict it

    `check_in` opened with a branch that read, entire:

        fix = self._pro(ac).arrival_fix
        if fix is not None and tower_freq and tower_freq != here_freq:
            call = f"..., radar not available, report {fix.name}. ..."

    From the SHAPE of the procedure's fix data it concluded two facts nobody had
    told it -- that the controller has no radar, and that this aeroplane is
    arriving -- and it sat above every branch that asks the questions properly.

    It could not be caught, because the one profile carrying an `arrival_fix`
    was the 1944 letdown, and that profile carries no station list (#140). No
    Clearance seat, no Departure seat, nothing to be wrong AT. Taking INITIAL
    out of the published catalogue meant a laddered procedure could carry its
    own arrival fix for the first time -- and four tests in this file and in
    test_atis.py went red at once, none of them naming this line.

    The radar half was wrong on the air already. `SeeingHimAndSteeringHimAreTwo\
Capabilities` below asserts `R.BATUMI_APPROACH.atc.radar` is True on purpose --
    "he can see him" -- so the engine told a pilot the radar was out while the
    same profile told the rest of the system it was up. `agent_atc` string-
    replaced the phrase back out on the way to the radio, using the BRIDGE's
    profile to correct a claim about somebody else's aeroplane.
    """

    def greeting(self, station, phase, profile=None):
        from marshall.atc import controller as C
        c = C.Controller(profile or self.laddered())
        c._me = station
        c.get("Sockeye").sortie_phase = phase
        c.check_in("Sockeye")
        return " ".join(t.text for t in c.take_out())

    def laddered(self, **over):
        """A procedure with BOTH an arrival fix and a full station ladder --
        the combination that did not exist while INITIAL was published."""
        import dataclasses
        return dataclasses.replace(R.BATUMI_ASR, arrival_fix=R.INITIAL, **over)

    def test_a_departing_aircraft_is_not_given_an_arrival_briefing(self):
        said = self.greeting(R.KOB_DEPARTURE, "departure")
        self.assertIn("radar contact", said)
        self.assertNotIn("report INITIAL", said)

    def test_nor_is_a_man_who_has_not_started_his_engine(self):
        said = self.greeting(R.KOB_CLEARANCE, "")
        self.assertNotIn("report", said.lower())

    def test_but_the_arrival_still_gets_it(self):
        """The half that must not be lost: on a procedure that homes a fix
        enroute, THAT is what he reports, and the handoff is a trigger he flies
        to rather than a channel change now."""
        said = self.greeting(R.KOB_DEPARTURE, "arrival")
        self.assertIn("report INITIAL", said)
        self.assertIn("At INITIAL contact Batumi Tower", said)

    def test_a_controller_who_can_see_him_does_not_say_the_radar_is_out(self):
        """The claim is `atc.radar`'s, and nothing else's. This is the assertion
        that replaces the string-replace deleted from `agent_atc`: a plaster
        applied downstream cannot know whose aeroplane it is."""
        self.assertTrue(R.BATUMI_APPROACH.atc.radar)
        said = self.greeting(R.APPROACH, "arrival", R.BATUMI_APPROACH)
        self.assertIn("report INITIAL", said)
        self.assertNotIn("radar not available", said)

    def test_and_one_who_genuinely_cannot_see_him_still_does(self):
        """The other direction, which is the one that gets somebody hurt. A
        blind controller must say so -- and used to have it stripped whenever
        the BRIDGE's own procedure had radar."""
        import dataclasses
        blind = self.laddered(
            atc=dataclasses.replace(R.BATUMI_ASR.atc, radar=False))
        said = self.greeting(R.APPROACH, "arrival", blind)
        self.assertIn("radar not available", said)


class SeeingHimAndSteeringHimAreTwoCapabilities(unittest.TestCase):
    """`AtcCapability.radar` was answering two questions. [#53]

    The 1944 Batumi letdown carries `radar=True` ON PURPOSE -- "Radar ON (you
    wanted eyes)" -- because the controller reads ranges off his own scope while
    the pilot, with no DME, flies the published pattern himself.

    So the obvious key for "does he vector?" is `atc.radar`, and it is wrong. It
    would give a period letdown radar phraseology: turning an aeroplane round a
    procedure the pilot is flying on a beacon. `_vectored` dodged that by naming
    the procedure KINDS instead -- a workaround with a comment explaining itself,
    which is why it survived since 2 August.
    """

    def _ctl(self, profile):
        from marshall.atc import controller as atc
        return atc.Controller(profile)

    def test_the_beacon_letdown_has_eyes_and_does_not_steer(self):
        self.assertTrue(R.BATUMI_APPROACH.atc.radar, "he can see him")
        self.assertFalse(self._ctl(R.BATUMI_APPROACH)._vectored,
                         "and must not vector him round his own letdown")

    def test_and_says_so_rather_than_leaving_it_to_be_inferred(self):
        self.assertIs(R.BATUMI_APPROACH.atc.vectors, False)

    def test_the_surveillance_approach_still_vectors(self):
        self.assertTrue(self._ctl(R.BATUMI_ASR)._vectored)

    def test_a_profile_that_says_nothing_is_asked_of_its_procedure(self):
        """`None` means "ask the procedure", which is what this did all along --
        an ASR or an ILS is vectored by construction."""
        self.assertIsNone(R.BATUMI_ASR.atc.vectors)
        self.assertTrue(self._ctl(R.BATUMI_ASR)._vectored)

    def test_the_name_of_the_approach_follows_from_it(self):
        self.assertEqual(self._ctl(R.BATUMI_APPROACH)._approach_name(),
                         "beacon approach")
        self.assertEqual(self._ctl(R.BATUMI_ASR)._approach_name(),
                         "radar approach")


class TheTalkdownSaysOnceThatSilenceIsExpected(unittest.TestCase):
    """#99, from the cockpit.

        "on an ASR approach, you should tell me at the beginning of the
         approach not to read back"

    Real procedure. On a surveillance approach the controller reads a course and
    a range every mile, and acknowledging each one puts the pilot on the air over
    the next instruction. The phrase belongs ONCE, with the clearance.

    NOT ON AN ILS, which is the distinction worth having. There the controller
    says almost nothing after the clearance and the pilot DOES report
    established -- telling him not to acknowledge would suppress the one call the
    procedure needs.
    """

    def _said(self, profile):
        from marshall.atc import controller as atc
        return atc.Controller(profile)._no_acknowledgement_phrase()

    def test_the_surveillance_approach_says_it(self):
        self.assertIn("do not acknowledge", self._said(R.BATUMI_ASR).lower())

    def test_the_ils_does_not(self):
        self.assertEqual(self._said(R.KOBULETI_ILS), "")

    def test_and_neither_does_the_beacon_letdown(self):
        """He is not being talked down -- he flies the pattern and reports the
        beacon, which is an acknowledgement the procedure wants."""
        self.assertEqual(self._said(R.BATUMI_APPROACH), "")

    def test_it_is_attached_to_the_clearance_and_nowhere_else(self):
        """Once, with the approach clearance. A phrase repeated every mile is
        the chatter it exists to prevent."""
        import inspect
        from marshall.atc import controller as atc
        src = inspect.getsource(atc.Controller)
        # The empty parens match the CALL, not the `def`.
        self.assertEqual(src.count("self._no_acknowledgement_phrase()"), 1,
                         "said more than once, which is the chatter it exists "
                         "to prevent")
