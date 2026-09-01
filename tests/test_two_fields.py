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
from tests import theatre as T

# THE MISSION BUILDER CANNOT BE IMPORTED ON EVERY MAP, and that is a fact about
# `src/`, not about this file. `mission/build.py:74` reads `R.TOWER.freq_mhz` in
# a CLASS BODY -- evaluated at import -- so the module raises on any theatre
# that does not publish a station called "Batumi Tower". It is finding 3's table
# row in the 13 August inventory and it belongs to #137.
#
# Caught rather than left to explode, because an ImportError at module scope
# takes the whole file down and this file's other 70 assertions have nothing to
# do with the mission builder. `_mb()` skips, by name, with the line number.
try:
    from marshall.mission import build as mb
except AttributeError as _e:                        # pragma: no cover - per map
    mb, _MB_WHY = None, str(_e)


def _mb():
    if mb is None:
        raise unittest.SkipTest(
            f"`marshall.mission.build` will not import on {T.name()}: "
            f"{_MB_WHY} -- a module constant bound at import "
            f"(mission/build.py:74), src-side, #137")
    return mb

# `P = R.BATUMI_ASR` used to stand here, at module scope, and it is why this
# file -- the two-aerodrome guard, of all of them -- could not be COLLECTED on
# the second map. A module constant resolved at import chooses the theatre
# before the runner does. It is a function now, and every use of it is inside a
# test, where a map has been chosen.


def P():
    """The procedure this map's bridge is started on."""
    return T.the_arrival()


class TestARoleBelongsToAField(unittest.TestCase):
    """The ambiguity itself -- and it is the same ambiguity on every map."""

    def test_every_staffed_role_resolves_to_the_field_that_staffs_it(self):
        """THE RULE, on whichever map is loaded. Walked off the station table
        rather than written out, so a third aerodrome is covered the day it is
        added -- and so the guard travels to Nevada, where `Silverbow Tower` and
        `Nellis Tower` are the pair that can be confused.

        Both the primary role and the hats a seat also wears, because
        `role_at`'s two-pass search is exactly where first-match used to hide.
        """
        for s in R.STATIONS:
            if not s.field:
                continue
            for role in (s.role, *(getattr(s, "also", ()) or ())):
                with self.subTest(field=s.field, role=role):
                    got = R.station_for(role, field=s.field)
                    self.assertIsNotNone(got, f"{s.field} staffs no {role}")
                    self.assertEqual(got.field, s.field,
                                     f"{s.field}'s {role} is answered by a seat "
                                     f"at {got.field}")

    def test_no_field_is_answered_with_another_fields_seat(self):
        """The wrong answer is never nonsense: it is a real controller at a real
        aerodrome, forty miles (or a hundred and twenty) from this one."""
        names = [f.name for f in T.fields()]
        self.assertGreaterEqual(len(names), 2, "one aerodrome cannot be confused")
        for fld in names:
            for role in ("tower", "ground", "approach", "clearance", "departure"):
                got = R.station_for(role, field=fld)
                if got is None:
                    continue                    # unstaffed, which is its own test
                with self.subTest(field=fld, role=role):
                    self.assertIn(got.field, (fld, ""),
                                  f"{fld} {role} answered by {got.name}")

    @T.skip_unless("caucasus", why="the Georgian ladder by name; the same rule "
                                   "is asserted off the station table above")
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
                ("Batumi", "clearance", "Batumi Clearance")):
            with self.subTest(field=field, role=role):
                self.assertEqual(R.station_for(role, field=field).name, want)

    @T.skip_unless("caucasus", why="Kobuleti Tower and Batumi Ground by name; "
                                   "the rule is asserted off the table above")
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
        self.assertIsNone(R.station_for("nosuchrole", field=T.arrival().name))

    def test_region_controllers_are_reachable_from_everywhere(self):
        """Center and Sentry own airspace, not an aerodrome. Asking which field
        they belong to is a category error, so they are fieldless and answer
        from either end of the route -- Georgia Center on one map, Los Angeles
        Center on the other, and the same one from both ends of either."""
        got = {f.name: R.station_for("center", field=f.name) for f in T.fields()}
        self.assertTrue(all(got.values()), f"a field reaches no Center: {got}")
        self.assertEqual(len({s.name for s in got.values()}), 1,
                         f"two fields on one map reach different Centers: {got}")
        for s in got.values():
            with self.subTest(who=s.name):
                self.assertEqual(s.field, "", "a region controller owns no field")
        # ...and so does the airborne commander, wherever the map has one. Not
        # every map staffs a Sentry, so this asserts about the seats that exist
        # rather than naming one that may not.
        for s in R.STATIONS:
            if s.role in ("center", "overlord"):
                with self.subTest(who=s.name):
                    self.assertEqual(s.field, "",
                                     f"{s.name} owns a region and was given a field")

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

    def test_every_frequency_is_in_a_band_an_aeroplane_can_tune(self):
        """VHF airband or UHF military. A number outside both is not a channel
        anybody reaches -- it is a typo that looks like a frequency."""
        for s in R.STATIONS:
            for hz in s.freqs:
                with self.subTest(station=s.name, mhz=hz):
                    self.assertTrue(108.0 <= hz <= 156.0 or 225.0 <= hz <= 400.0,
                                    f"{s.name} is on {hz}, which is neither VHF "
                                    f"airband nor UHF")

    @T.skip_unless("caucasus", why="the SCR-522 is a Caucasus problem: Nevada "
                                   "has no warbird on its ladder")
    def test_a_warbird_can_still_reach_every_rung(self):
        """WHAT THIS USED TO SAY, and why it changed.

        It asserted every Caucasus frequency was VHF, on the premise that "the
        period theatre flies SCR-522s and every seat on it is VHF". That
        premise expired: this map now launches F-16s, F-100Ds and Phantoms off
        Kobuleti, and a Phantom's ARC-164 cannot reach a VHF airband seat at
        all -- so the map needed UHF and the old rule forbade it.

        The invariant underneath survives, and it is the one worth keeping: a
        Mustang must still be able to reach EVERY rung. Adding a band for one
        aeroplane must not take a seat away from another, which is exactly what
        `Station.channels` is for -- one controller, one conversation, reachable
        by both sets."""
        for s in R.STATIONS:
            with self.subTest(station=s.name):
                self.assertTrue(
                    any(108.0 <= hz <= 156.0 for hz in s.freqs),
                    f"{s.name} has no VHF frequency, so an SCR-522 cannot "
                    f"reach him at all: {s.freqs}")

    @T.skip_unless("caucasus", why="Nevada's UHF is real and predates this")
    def test_and_a_single_UHF_radio_can_reach_every_rung_too(self):
        """The other half, and the reason any of this was added.

            "learned yesterday that the F4 only has 1 UHF radio"

        One radio means he retunes at every handoff rather than monitoring two
        at once -- which the ladder already asks of everybody. What it cannot
        survive is a rung with no UHF on it, because that is a controller he
        can never talk to."""
        for s in R.STATIONS:
            with self.subTest(station=s.name):
                self.assertTrue(
                    any(225.0 <= hz <= 400.0 for hz in s.freqs),
                    f"{s.name} has no UHF frequency, so a Phantom cannot "
                    f"reach him at all: {s.freqs}")


class TestTheLadderIsWholeAndOrdered(unittest.TestCase):
    """The ladder's SHAPE, which is a rule, on whichever map is loaded.

    The literal eight rungs below are the Caucasus's and stay the Caucasus's.
    What is asserted here is what made `stations[:4]` and `"ABCD"[i]` bugs: the
    card carries every rung, the numbering has no holes, and a seat's preset is
    the position it occupies. Nevada's ladder is nine rungs and had none of this
    checked.
    """

    def test_every_preset_seat_is_on_the_ladder_exactly_once(self):
        ladder = list(R.PRESET_LADDER)
        self.assertEqual(len(ladder), len({s.name for s in ladder}),
                         "a seat appears twice on the ladder")
        for n, s in enumerate(ladder, 1):
            with self.subTest(preset=n, who=s.name):
                self.assertEqual(R.preset_of(s), n)

    def test_the_card_the_mission_writes_carries_the_whole_ladder(self):
        """The regression this replaces: `stations[:4]` silently dropped the
        whole arrival. Asserted against the ladder's LENGTH rather than against
        four, because four was the number that made it invisible."""
        card = dict(_mb().channels_for(P()))
        for n, s in enumerate(R.PRESET_LADDER, 1):
            with self.subTest(preset=n, who=s.name):
                self.assertIn(n, card, f"{s.name} is not on the card")
                self.assertAlmostEqual(card[n], s.freq_mhz, places=3)

    def test_a_seat_the_ladder_skips_still_gets_a_button_above_it(self):
        """Sentry is not a rung -- he is a commander -- but he is still
        reachable, and he used to fall off the end when the card was sliced.
        Only asserted where the map staffs one."""
        extra = [s for s in R.STATIONS
                 if R.preset_of(s) is None and getattr(s, "preset", False)]
        card = dict(_mb().channels_for(P()))
        for s in extra:
            with self.subTest(who=s.name):
                self.assertIsNone(R.preset_of(s))
                self.assertIn(s.freq_mhz, card.values(),
                              f"{s.name} is reachable from nowhere")

    def test_the_short_card_is_HIS_fields_four_at_every_field(self):
        """An SCR-522 has four buttons and the first four are the wrong four --
        the other aerodrome's, in table order. Asserted at EVERY field the map
        works, which is the only way the guard survives a third one."""
        for f in T.fields():
            got = [hz for _, hz in _mb().channels_for(P(), limit=4, home=f.name)]
            mine = {s.freq_mhz for s in R.STATIONS if s.field == f.name}
            theirs = {s.freq_mhz for s in R.STATIONS
                      if s.field not in ("", f.name)} - mine
            with self.subTest(home=f.name):
                self.assertTrue(mine & set(got),
                                f"a warbird at {f.name} is given nobody at "
                                f"{f.name}: {got}")
                self.assertFalse(theirs & set(got),
                                 f"a warbird at {f.name} is given another "
                                 f"aerodrome's frequency: "
                                 f"{sorted(theirs & set(got))}")

    def test_the_region_controller_always_survives_the_cut(self):
        """He is reachable from anywhere, which is exactly what makes him worth
        one of only four buttons."""
        ctr = R.station_for("center")
        for f in T.fields():
            with self.subTest(home=f.name):
                got = [hz for _, hz in _mb().channels_for(P(), limit=4, home=f.name)]
                self.assertIn(ctr.freq_mhz, got)

    def test_a_four_button_radio_is_still_a_preset_panel(self):
        """The bar that replaced "can it hold the WHOLE card".

        All-or-nothing was safe at four rungs and silently disarmed every
        warbird at seven -- no card at all, stock presets, kneeboard printing
        something else. `MIN_PRESET_PANEL` is the smallest real bank."""
        self.assertLessEqual(_mb().MIN_PRESET_PANEL, 4)


@T.skip_unless("caucasus", why="the Georgian ladder rung by rung; its SHAPE is "
                               "asserted on every map above")
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
        card = _mb().channels_for(P())
        for n, _name, hz in self.EXPECTED:
            with self.subTest(preset=n):
                self.assertAlmostEqual(dict(card)[n], hz, places=3)

    def test_sentry_keeps_a_button_above_the_ladder(self):
        """Not a rung -- a commander -- but still reachable. He used to fall off
        the end when the card was sliced to four."""
        self.assertIsNone(R.preset_of(R.OVERLORD))
        # A BUTTON, NOT THE LAST BUTTON. This asserted he sat at
        # `len(PRESET_LADDER) + 1`, which was true only while he was the sole
        # seat off the ladder. Batumi Clearance is another -- a facility the
        # aerodrome has and this sortie never climbs to -- and it takes that
        # index, which says nothing about whether Sentry is reachable. The
        # regression being guarded is him FALLING OFF, so that is what is
        # asserted. [#218]
        card = dict(_mb().channels_for(P()))
        self.assertIn(131.000, [round(hz, 3) for hz in card.values()],
                      f"Sentry is not on the card at all: {card}")
        self.assertTrue(all(n <= max(card) for n in card),
                        "the card has a hole in it")

    def test_the_card_is_no_longer_truncated_to_four(self):
        """The regression this replaces: `stations[:4]` silently dropped Batumi
        Approach, Tower and Ground -- the whole arrival."""
        card = dict(_mb().channels_for(P()))
        self.assertGreaterEqual(len(card), 7)
        for hz in (124.425, 118.600, 121.900):
            with self.subTest(mhz=hz):
                self.assertIn(hz, card.values())


@T.skip_unless("caucasus", why="Georgian frequencies by number; the same cut is "
                               "asserted at every field on every map above")
class TestAShortRadioGetsTheRightFour(unittest.TestCase):
    """An SCR-522 has four buttons and the first four are the wrong four."""

    def test_a_warbird_at_batumi_gets_batumi(self):
        got = [hz for _, hz in _mb().channels_for(P(), limit=4, home="Batumi")]
        self.assertIn(124.425, got)          # his approach
        self.assertIn(118.600, got)          # his tower
        self.assertIn(139.000, got)          # and the region controller
        self.assertNotIn(125.100, got, "given the other field's clearance")

    def test_a_warbird_at_kobuleti_gets_kobuleti(self):
        got = [hz for _, hz in _mb().channels_for(P(), limit=4, home="Kobuleti")]
        self.assertIn(125.100, got)          # his clearance
        self.assertIn(121.800, got)          # his ground
        self.assertIn(133.000, got)          # his tower
        self.assertNotIn(124.425, got, "given the other field's approach")


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


# THE CHART PAGES WENT, AND SO DID THEIR TESTS.
#
# `TestTheKneeboardSurvivesSevenStations` rendered the comms card, the nav log,
# the brief and the plates to prove a seven-rung ladder did not crash an
# f-string. The DTC gives a pilot his frequencies and his plate in the
# aeroplane now, so those pages are deleted and there is nothing to render.
#
# The INVARIANT they were guarding is not deleted with them: `preset_label`
# past D is asserted directly by `TestThePresetsGoBeyondFour` above, which is
# where the "ABCD"[i] bug actually lived. What is gone is the rendering, not
# the rule.

class TestEveryFieldPicksItsOwnRunway(unittest.TestCase):
    """The computed runway, at EVERY aerodrome the map works.

    The Georgian numbers below are Georgia's. What is asserted here is the rule
    that made "cleared for take-off runway one three" come out of Kobuleti
    Tower: the end in use is one of THIS field's published ends, it follows
    THIS field's wind, and it never comes from the other aerodrome.
    """

    def test_the_end_in_use_is_one_this_field_publishes(self):
        for f in T.fields():
            with self.subTest(field=f.name):
                self.assertIn(f.runway_in_use(), f.ends,
                              f"{f.name} is using a runway it does not have")

    def test_the_wind_turns_it_round_and_nothing_else_does(self):
        """Reciprocal wind, reciprocal end. Two fields on one map may sit at
        different angles, so each is asked about its own."""
        for f in T.fields():
            with self.subTest(field=f.name):
                into = f.runway_in_use()
                other_end = [e for e in f.ends if e != into]
                self.assertTrue(other_end, f"{f.name} publishes one end")
                self.assertEqual(f.runway_in_use((into * 10 + 180) % 360),
                                 other_end[0])

    def test_a_calm_wind_does_not_flip_the_runway(self):
        """Ties go to the published end. A runway that oscillates on rounding
        is worse than one that is occasionally downwind by a knot."""
        for f in T.fields():
            with self.subTest(field=f.name):
                across = (f.runway + 90) % 360
                self.assertEqual(f.runway_in_use(across), f.ends[0])

    def test_no_two_fields_are_answered_with_one_runway(self):
        """The wrong answer here is a real runway at a real aerodrome. If two
        fields share an end designator the test is uninformative rather than
        wrong, so it says which case it is looking at."""
        by_field = {f.name: f.runway_in_use() for f in T.fields()}
        for f in T.fields():
            with self.subTest(field=f.name):
                self.assertEqual(by_field[f.name], f.runway_in_use(),
                                 "a field's runway depends on who asked")


@T.skip_unless("caucasus", why="Batumi's 13/31 and Kobuleti's 07/25 by number; "
                               "the rule holds at every field on every map above")
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


@T.skip_unless("caucasus", why="`atc.briefing` binds R.BATUMI_ASR as a default "
                               "argument at import and cannot be loaded on "
                               "another map at all -- finding 3, src-side, #137")
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
            profile=P(), me=me, fix=None, nxt=None, directive="",
            stack="", vectoring="", _flight={}, _flight_say="", claim="",
            name_say="")[0]

    def ground_seats(self):
        """One clearance-issuing seat per aerodrome the map staffs, so this runs
        against BOTH fields rather than against whichever one is listed first --
        which is the very mistake the class is about."""
        out = []
        for f in T.fields():
            for role in ("clearance", "ground"):
                s = R.station_for(role, field=f.name)
                if s is not None:
                    out.append(s)
                    break
        self.assertTrue(out, "the map staffs no ground seat anywhere")
        return out

    def test_every_station_at_his_field_is_named(self):
        for me in self.ground_seats():
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
        for me in self.ground_seats():
            msg = self.compose(me)
            block = [ln for ln in msg.split("\n") if ln.startswith("YOUR FIELD")]
            self.assertTrue(block, f"{me.name} gets no field frequency block")
            for s, hz in _foreign_numbers(me.field):
                with self.subTest(who=me.name, stranger=f"{s.name} {hz}"):
                    self.assertNotIn(controller.spell_freq(hz), block[0])

    def test_the_worked_example_carries_no_frequency_of_its_own(self):
        """A number in an example is a number the model will say. This is what
        put Batumi Tower's channel in a Kobuleti clearance."""
        from marshall.atc import controller
        for me in self.ground_seats():
            msg = self.compose(me)
            head = msg.split("YOUR FIELD")[0]
            for s, hz in _foreign_numbers(me.field):
                with self.subTest(who=me.name, stranger=f"{s.name} {hz}"):
                    self.assertNotIn(controller.spell_freq(hz), head,
                                     f"{s.name}'s {hz} is quoted at {me.field}")

    def test_departure_is_his_fields_and_not_the_first_in_the_list(self):
        """`station_for` was rewritten to stop taking the first role match;
        this lookup kept doing it. Kobuleti Departure is listed first, so
        Kobuleti was right by accident and Batumi was about to send a pilot
        forty miles up the coast.

        Asked of every field, because "first in the list" is only wrong for the
        fields that are not first."""
        for me in self.ground_seats():
            want = R.station_for("departure", field=me.field)
            if want is None:
                continue
            msg = self.compose(me)
            line = [ln for ln in msg.split("\n")
                    if ln.startswith("DEPARTURE FREQUENCY")]
            with self.subTest(who=me.name):
                self.assertTrue(line, f"{me.name} is told no departure frequency")
                self.assertIn(want.name, line[0])
                for f in T.fields():
                    if f.name != me.field:
                        self.assertNotIn(f.name, line[0])

    def test_the_atis_of_his_field_travels_with_them(self):
        for me in self.ground_seats():
            with self.subTest(who=me.name):
                self.assertIn(f"{me.field} ATIS", self.compose(me))


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
        c = C.Controller(P())
        c._me = station
        return c

    def test_each_field_gets_its_own_runway(self):
        """Spoken, and it must be HIS field's end -- on a bridge started on the
        other field's approach, which is the condition that produced "cleared
        for take-off runway one three" out of Kobuleti Tower."""
        from marshall.core.say import spell_rwy
        for s in R.STATIONS:
            if s.role not in ("tower", "ground") or not s.field:
                continue
            fld = R.field_named(s.field)
            if fld is None:
                continue
            with self.subTest(who=s.name):
                self.assertEqual(self.controller(s)._runway_in_use(),
                                 spell_rwy(fld.runway_in_use()),
                                 f"{s.name} named a runway that is not "
                                 f"{s.field}'s")

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
        for station in R.STATIONS:
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

    def landed_on(self, station, profile=None):
        from marshall.atc import controller as C
        c = C.Controller(profile if profile is not None else P())
        c._me, c.working = station, station.role
        ac = c.get("Sockeye")
        ac.phase = C.Phase.CLEARED
        c.report_landed("Sockeye")
        return " ".join(t.text for t in c.take_out())

    def approach_seats(self):
        """One seat working arrivals at each aerodrome. Not `station_for` with
        no field -- that is the bug."""
        out = []
        for f in T.fields():
            s = R.station_for("approach", field=f.name)
            if s is not None:
                out.append((f, s))
        self.assertGreaterEqual(len(out), 2,
                                "fewer than two aerodromes work arrivals; "
                                "there is nothing here to confuse")
        return out

    def test_approach_hands_him_to_his_own_fields_tower(self):
        """Findings 1 and 2 of the 13 August inventory, from the inside. The
        wrong answer is a real Tower on a real frequency at the other end of the
        map -- and it is what a pilot on final at Batumi was actually told."""
        for f, s in self.approach_seats():
            tower = R.station_for("tower", field=f.name)
            if tower is None:
                continue
            said = self.landed_on(s)
            with self.subTest(who=s.name):
                self.assertIn(tower.name, said)
                for g in T.fields():
                    if g.name != f.name:
                        self.assertNotIn(g.name, said,
                                         f"{s.name} sent him to {g.name}")

    def test_the_landing_clearance_names_HIS_runway(self):
        """Not the approach profile's. All three ground clearances -- taxi,
        take-off and landing -- must name one runway, and it is the one in use
        at the field he is actually at."""
        from marshall.core.say import spell_rwy
        for s in R.STATIONS:
            if s.role != "tower" or not s.field:
                continue
            fld = R.field_named(s.field)
            if fld is None:
                continue
            with self.subTest(who=s.name):
                self.assertIn(f"runway {spell_rwy(fld.runway_in_use())}",
                              self.landed_on(s))

    def test_the_welcome_after_touchdown_is_his_own_tower(self):
        from marshall.atc import controller as C
        for s in R.STATIONS:
            if s.role != "tower" or not s.field:
                continue
            with self.subTest(who=s.name):
                c = C.Controller(P())
                c._me = s
                c.get("Sockeye")
                c.report_down("Sockeye")
                said = " ".join(t.text for t in c.take_out())
                self.assertIn(s.name, said)
                for g in T.fields():
                    if g.name != s.field:
                        self.assertNotIn(g.name, said)

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

    def seat(self):
        """A seat at the aerodrome that is NOT the arrival, because the question
        is what he is told about somewhere else."""
        fld = T.other()
        for role in ("clearance", "ground", "tower"):
            s = R.station_for(role, field=fld.name)
            if s is not None:
                return s
        raise AssertionError(f"{fld.name} is unstaffed")

    def brief(self, station):
        from marshall.atc import agent_atc as A
        from marshall.atc import assembly
        return assembly.compose_message(
            A.Bridge(), scope="", known="Sockeye",
            transcript=f"say the frequency for {T.station('tower').name}",
            profile=P(), me=station, fix=None, nxt=None, directive="", stack="",
            vectoring="", _flight={}, _flight_say="", claim="", name_say="")[0]

    def test_he_is_told_to_call_the_tool_for_anywhere_else(self):
        said = self.brief(self.seat())
        self.assertIn("look_up_frequency", said)
        self.assertIn("must not", said.split("look_up_frequency")[1][:200])

    def test_his_own_fields_frequencies_are_still_handed_to_him(self):
        """Not replaced by the tool. A controller knows his own tower the way he
        knows his own name, and a round trip for it would be latency on the
        commonest question there is."""
        me = self.seat()
        said = self.brief(me)
        self.assertIn(f"YOUR FIELD — {me.field}", said)
        for s in R.STATIONS:
            if s.field == me.field:
                with self.subTest(names=s.name):
                    self.assertIn(s.name, said)

    def test_and_no_other_aerodromes_numbers_are_carried(self):
        """The scaling half. If another field's frequency is in the prompt, the
        tool has bought nothing."""
        from marshall.atc import controller
        me = self.seat()
        head = self.brief(me)
        for s, hz in _foreign_numbers(me.field):
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
        c = C.Controller(P())
        c._me = station
        c.get("Sockeye").sortie_phase = phase
        c.check_in("Sockeye")
        return " ".join(t.text for t in c.take_out())

    def two_hatted(self):
        """A seat wearing BOTH the departure and the approach hat, which is the
        only kind that can confuse the two jobs. Kobuleti Departure on one map;
        the test says so rather than skipping silently if a map has none."""
        for s in R.STATIONS:
            hats = {s.role, *(getattr(s, "also", ()) or ())}
            if {"departure", "approach"} <= hats:
                return s
        raise unittest.SkipTest(
            f"{T.name()} staffs no seat that works departures and arrivals both, "
            f"so the two jobs cannot be confused here")

    def test_a_departing_aircraft_is_not_asked_for_the_field(self):
        said = self.greeting(self.two_hatted(), "departure")
        self.assertIn("radar contact", said)
        self.assertNotIn("field in sight", said)
        self.assertNotIn(self.trigger(), said)

    def test_nor_for_an_information_letter_he_has_already_left_behind(self):
        """The ATIS he needs is the one where he is GOING. He read a clearance
        back four minutes ago; he has said what he wants."""
        self.assertNotIn("information",
                         self.greeting(self.two_hatted(), "departure").lower())

    def trigger(self):
        """WHAT THIS PROCEDURE'S ARRIVAL IS ASKED TO REPORT, which is not a
        constant and is not the map's business either. On a talkdown it is the
        field in sight -- a pilot with no localiser cannot know when he is
        established; on an ILS it is the final approach course. Asked of the
        engine so the test cannot drift from the rule it is guarding."""
        from marshall.atc import controller as C
        c = C.Controller(P())
        return c._report_phrase(None)

    def test_the_same_seat_working_an_arrival_still_asks(self):
        """The half that must not be lost. Kobuleti Departure genuinely does
        work Kobuleti's arrivals."""
        said = self.greeting(self.two_hatted(), "arrival")
        self.assertIn(self.trigger(), said)

    def test_center_does_not_ask_a_man_thirty_miles_out(self):
        said = self.greeting(R.station_for("center"), "enroute")
        self.assertNotIn("field in sight", said)
        self.assertNotIn(self.trigger(), said)

    def test_a_ground_seat_asks_for_the_request_and_the_letter(self):
        """Clearance is one of the two positions that genuinely checks the
        ATIS, and a man on the ramp has not said what he wants yet."""
        said = self.greeting(T.station("clearance", T.other()), "clearance")
        self.assertIn("Say your request", said)
        self.assertNotIn("field in sight", said)
        self.assertNotIn(self.trigger(), said)

    def test_a_voice_out_of_nowhere_is_still_treated_as_arriving(self):
        """Every sortie looked like this until the ladder grew a ground half:
        no phase, inbound, wanting an approach. Being asked when you are not
        arriving is untidy; NOT being asked when you are is a controller who has
        not understood what you want."""
        self.assertIn(self.trigger(), self.greeting(T.station("approach"), ""))


@T.skip_unless("caucasus", why="the 1944 beacon letdown and the INITIAL fix; "
                               "no other published map has a procedure that "
                               "homes a navaid enroute")
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


@T.skip_unless("caucasus", why="the 1944 letdown is the only published "
                               "procedure that has eyes and does not steer")
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
        self.assertFalse(self._ctl(R.BATUMI_APPROACH)._vectored(None),
                         "and must not vector him round his own letdown")

    def test_and_says_so_rather_than_leaving_it_to_be_inferred(self):
        self.assertIs(R.BATUMI_APPROACH.atc.vectors, False)

    def test_the_surveillance_approach_still_vectors(self):
        self.assertTrue(self._ctl(R.BATUMI_ASR)._vectored(None))

    def test_a_profile_that_says_nothing_is_asked_of_its_procedure(self):
        """`None` means "ask the procedure", which is what this did all along --
        an ASR or an ILS is vectored by construction."""
        self.assertIsNone(R.BATUMI_ASR.atc.vectors)
        self.assertTrue(self._ctl(R.BATUMI_ASR)._vectored(None))

    def test_the_name_of_the_approach_follows_from_it(self):
        self.assertEqual(self._ctl(R.BATUMI_APPROACH)._approach_name(None),
                         "beacon approach")
        self.assertEqual(self._ctl(R.BATUMI_ASR)._approach_name(None),
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
        return atc.Controller(profile)._no_acknowledgement_phrase(None)

    def test_a_talkdown_says_it_and_nothing_else_does(self):
        """Over every procedure the map publishes, keyed on the two facts the
        engine keys on -- is the CONTROLLER navigating, and does he keep
        navigating past the intercept. Both are facts about a procedure, not
        about an aerodrome or a map, so this is the same assertion on Nevada
        against nine ILS/letdown combinations that never ran there.

        The beacon letdown is the case that makes it worth writing this way: it
        is a talkdown AND is not vectored, so a rule keyed on `guidance` alone
        would tell a man flying a published pattern not to report his beacon.
        """
        from marshall.atc import controller as atc
        for key, p in sorted(T.approaches().items()):
            c = atc.Controller(p)
            wants = c._vectored(None) and p.guidance == "talkdown"
            with self.subTest(procedure=key, guidance=p.guidance,
                              vectored=c._vectored(None)):
                said = self._said(p).lower()
                if wants:
                    self.assertIn("do not acknowledge", said)
                else:
                    self.assertEqual(said, "",
                                     "the one call the procedure needs is "
                                     "being suppressed")

    @T.skip_unless("caucasus", why="the Batumi ASR; the rule is asserted over "
                                   "every published procedure above")
    def test_the_surveillance_approach_says_it(self):
        self.assertIn("do not acknowledge", self._said(R.BATUMI_ASR).lower())

    @T.skip_unless("caucasus", why="the Kobuleti ILS by name")
    def test_the_ils_does_not(self):
        self.assertEqual(self._said(R.KOBULETI_ILS), "")

    @T.skip_unless("caucasus", why="the 1944 beacon letdown, which no other "
                                   "published map has")
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
        # `self.` matches the CALL, not the `def`. The argument is the
        # AEROPLANE now (#162) -- whether silence is expected is a fact about
        # the procedure HE is flying, and two aircraft on one frequency get
        # opposite answers.
        self.assertEqual(src.count("self._no_acknowledgement_phrase(ac)"), 1,
                         "said more than once, which is the chatter it exists "
                         "to prevent")
