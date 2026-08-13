"""The separation engine, single ships.

This is the part of the system an LLM is never allowed to guess at, and until
now nothing guarded it. These are the rules the letdown geometry forces: enter
at the top, step down on vacate, one in the letdown at a time, a go-around goes
to the front of the line, and a repeat offender is banished so he cannot block
the field.
"""

import dataclasses
import unittest

from marshall.atc import controller as atc
from marshall.atc import equipment as E
from marshall.core import route as R


def profile(**over):
    return dataclasses.replace(R.BATUMI_APPROACH, **over)


def texts(ctl):
    """Drain what the controller just said."""
    out = [tx.text for tx in ctl.out]
    ctl.out.clear()
    return out


def said(ctl, *fragments):
    joined = " ".join(texts(ctl)).lower()
    return all(f.lower() in joined for f in fragments)


class TestStackEntry(unittest.TestCase):
    def setUp(self):
        self.ctl = atc.Controller(profile())

    def test_check_in_does_not_assign_a_level(self):
        self.ctl.check_in("Sockeye")
        self.assertEqual(self.ctl.get("Sockeye").phase, atc.Phase.ENROUTE)
        self.assertIsNone(self.ctl.get("Sockeye").assigned_ft)

    def test_first_arrival_takes_the_bottom_and_is_cleared(self):
        self.ctl.report_beacon("Sockeye", 5000)
        ac = self.ctl.get("Sockeye")
        # Nobody ahead, so he is cleared straight out of the hold.
        self.assertEqual(ac.phase, atc.Phase.CLEARED)
        self.assertEqual(ac.assigned_ft, self.ctl.profile.hold_base_ft)

    def test_arrivals_fill_bottom_up(self):
        """...ABOVE THE AIRCRAFT ON THE APPROACH, who is still at the base.

        This used to expect B at 4,000 -- the level A had just been cleared
        from and is still flying. Both numbers were written from the code
        rather than decided, and the first stack rehearsal ever flown put two
        aeroplanes at one altitude on its first run. On a radar approach the
        level IS the separation: there is no beacon, no pattern, and nothing
        else keeping them apart. See `_spoken_for` and #108.
        """
        for cs in ("A 1", "B 1", "C 1"):
            self.ctl.report_beacon(cs, 9000)
        self.assertEqual(self.ctl.get("A 1").assigned_ft, 4000)   # the letdown
        self.assertEqual(self.ctl.get("B 1").assigned_ft, 5000)
        self.assertEqual(self.ctl.get("C 1").assigned_ft, 6000)

    def test_stack_grows_past_four(self):
        # The stack used to be a fixed four-element list. A formation break-up
        # alone can want four levels, so it has to keep going.
        for i in range(6):
            self.ctl.report_beacon(f"Ship {i}", 9000)
        levels = sorted(a.assigned_ft for a in self.ctl.aircraft.values()
                        if a.phase is atc.Phase.HOLDING)
        # 4,000 belongs to the aircraft in the letdown until he leaves it, so
        # the holders start one level higher than they used to. [#108]
        self.assertEqual(levels, [5000, 6000, 7000, 8000, 9000])

    def test_stack_is_capped_by_oxygen(self):
        p = profile(hold_base_ft=4000, hold_top_ft=6000)
        ctl = atc.Controller(p)
        self.assertEqual(p.stack_ft, [4000, 5000, 6000])
        for i in range(5):
            ctl.report_beacon(f"Ship {i}", 9000)
        self.assertTrue(said(ctl, "no holding available"))


class TestOneInTheLetdown(unittest.TestCase):
    def setUp(self):
        self.ctl = atc.Controller(profile())
        self.ctl.report_beacon("Lead 1", 4000)      # cleared into the letdown
        self.ctl.report_beacon("Two 1", 5000)       # holds
        texts(self.ctl)

    def test_second_aircraft_is_not_cleared(self):
        self.assertEqual(self.ctl.get("Two 1").phase, atc.Phase.HOLDING)

    def test_requesting_while_occupied_is_held(self):
        self.ctl.request_approach("Two 1")
        self.assertTrue(said(self.ctl, "continue holding", "number two"))
        self.assertEqual(self.ctl.get("Two 1").phase, atc.Phase.HOLDING)

    def test_landing_frees_the_letdown_and_clears_the_next(self):
        self.ctl.report_landed("Lead 1")
        self.assertEqual(self.ctl.get("Two 1").phase, atc.Phase.CLEARED)

    def test_step_down_on_vacate(self):
        """Everybody moves down one, onto levels that are actually free.

        Lead holds 4,000 in the letdown; Two holds 5,000; Three holds 6,000.
        When Lead lands, Two is cleared -- and takes 5,000 with him, because
        the level he flies the approach at is the one he was holding. So Three
        steps down to 6,000... which is where he already is.

        The old expectation was that Three dropped to 4,000, onto the level Two
        was still at. That is the collision from the other direction, and it is
        why `_step_down` compresses onto the FREE levels rather than onto the
        bottom of the stack. [#108]
        """
        self.ctl.report_beacon("Three 1", 6000)
        texts(self.ctl)
        self.assertEqual(self.ctl.get("Three 1").assigned_ft, 6000)
        self.ctl.report_landed("Lead 1")
        self.assertEqual(self.ctl.get("Two 1").phase, atc.Phase.CLEARED)
        # Nobody is left at a level anybody else is at.
        levels = [a.assigned_ft for a in self.ctl.aircraft.values()
                  if a.assigned_ft is not None
                  and a.phase is not atc.Phase.LANDED]
        self.assertEqual(len(levels), len(set(levels)),
                         "two aircraft ended up at one altitude")


class TestMissedApproach(unittest.TestCase):
    def setUp(self):
        self.ctl = atc.Controller(profile())
        self.ctl.report_beacon("Lead 1", 4000)
        self.ctl.report_beacon("Two 1", 5000)
        texts(self.ctl)

    def test_missed_goes_to_the_missed_altitude(self):
        self.ctl.report_missed("Lead 1")
        ac = self.ctl.get("Lead 1")
        self.assertEqual(ac.assigned_ft, self.ctl.profile.missed_ft)
        self.assertEqual(ac.approaches, 1)

    def test_missed_goes_to_the_front_of_the_line(self):
        # He climbs BELOW the stack, so he can never re-enter it -- front of the
        # line is the only clean option on a single beacon.
        self.ctl.report_missed("Lead 1")
        self.assertEqual(self.ctl.get("Lead 1").phase, atc.Phase.CLEARED)
        self.assertEqual(self.ctl.get("Two 1").phase, atc.Phase.HOLDING)

    def test_second_miss_is_banished(self):
        self.ctl.report_missed("Lead 1")
        texts(self.ctl)
        self.ctl.report_missed("Lead 1")
        self.assertEqual(self.ctl.get("Lead 1").phase, atc.Phase.BANISHED)
        # And the field is freed for whoever was waiting.
        self.assertEqual(self.ctl.get("Two 1").phase, atc.Phase.CLEARED)

    def test_banished_is_sent_to_the_outer_hold(self):
        self.ctl.report_missed("Lead 1")
        texts(self.ctl)
        self.ctl.report_missed("Lead 1")
        self.assertTrue(said(self.ctl, self.ctl.profile.outer_hold.name))


class TestTimedMissedApproachPoint(unittest.TestCase):
    def test_beam_clock_calls_the_missed(self):
        # DCS produces no usable cone of silence, so ATC times the final and
        # calls the missed as backup for the pilot's own watch.
        ctl = atc.Controller(profile())
        ctl.report_beacon("Lead 1", 4000)          # cleared
        ctl.report_beacon("Lead 1")                 # established -> clock starts
        texts(ctl)
        ctl.tick(ctl.profile.final_approach_sec + 1)
        self.assertEqual(ctl.get("Lead 1").approaches, 1)
        self.assertTrue(said(ctl, "go missed"))

    def test_landing_stops_the_clock(self):
        ctl = atc.Controller(profile())
        ctl.report_beacon("Lead 1", 4000)
        ctl.report_beacon("Lead 1")
        ctl.report_landed("Lead 1")
        texts(ctl)
        ctl.tick(ctl.profile.final_approach_sec + 1)
        self.assertEqual(ctl.get("Lead 1").approaches, 0)


class TestAltitudeDeviation(unittest.TestCase):
    def test_a_wrong_level_is_corrected_not_echoed(self):
        ctl = atc.Controller(profile())
        ctl.report_beacon("Lead 1", 4000)       # cleared, and keeps 4,000
        ctl.report_beacon("Two 1", 5000)        # holds ABOVE him, at 5,000
        texts(ctl)
        ctl.report_beacon("Two 1", 7000)        # reports a level he was not given
        self.assertTrue(said(ctl, "negative", "assigned five thousand"))

    def test_a_matching_level_is_acknowledged(self):
        ctl = atc.Controller(profile())
        ctl.report_beacon("Lead 1", 4000)
        ctl.report_beacon("Two 1", 5000)
        texts(ctl)
        # 5,000, not 4,000 -- 4,000 is the letdown aircraft's now. [#108]
        ctl.report_beacon("Two 1", 5000)
        self.assertFalse(said(ctl, "negative"))


class TestSpokenOutput(unittest.TestCase):
    def test_transmissions_never_contain_a_digit_dash(self):
        # Polly reads "Pony 1-1" as "Pony one dash one".
        ctl = atc.Controller(profile())
        ctl.check_in("Pony 1-1")
        ctl.report_beacon("Pony 1-1", 4000)
        for t in texts(ctl):
            self.assertNotIn("1-1", t)

class TestSpokenNumbers(unittest.TestCase):
    def test_altitudes(self):
        self.assertEqual(atc.spell_alt(4000), "four thousand")
        self.assertEqual(atc.spell_alt(3500), "three thousand five hundred")

    def test_five_figure_altitudes_are_read_digit_by_digit(self):
        # Reachable since the ceiling became the P-51's oxygen limit; used to
        # come out as the literal "10 thousand".
        self.assertEqual(atc.spell_alt(10000), "one zero thousand")
        self.assertEqual(atc.spell_alt(12000), "one two thousand")

    def test_no_bare_digits_reach_polly(self):
        for ft in (4000, 7000, 10000, 12000, 3500):
            self.assertFalse(any(c.isdigit() for c in atc.spell_alt(ft)),
                             atc.spell_alt(ft))

    def test_frequencies(self):
        # A whole number keeps its decimal now. It used to be dropped, on the
        # reasoning that nobody says "one three two decimal zero" -- and the
        # pilot asked for it twice, because a bare number has to be recognised
        # as a frequency from context and he is busy flying. See
        # tests/test_frequency.py.
        self.assertEqual(atc.spell_freq(132.0), "one three two decimal zero")
        self.assertEqual(atc.spell_freq(128.5), "one two eight decimal five")
        self.assertEqual(atc.spell_freq(121.75),
                         "one two one decimal seven five")


class TestChannels(unittest.TestCase):
    """A phase's controller lives on the beacon flown in that phase -- the set
    has four presets and the ARA-8 homes on whatever it is tuned to, so working
    the beacon and hearing the controller are the same act."""

    def setUp(self):
        self.ctl = atc.Controller(profile())

    def test_enroute_is_worked_on_the_arrival_fix(self):
        self.ctl.check_in("Pony 1-1")
        self.assertEqual(self.ctl.out[0].freq_mhz, R.INITIAL.freq_mhz)

    def test_the_handoff_happens_AT_the_arrival_fix_not_immediately(self):
        # Switching to Tower on check-in takes him off the frequency of the fix
        # he is still navigating to -- the set homes whatever it is tuned to, so
        # an early switch removes the needle he is steering on.
        self.ctl.check_in("Pony 1-1")
        spoken = " ".join(texts(self.ctl)).lower()
        self.assertIn("report initial", spoken)
        self.assertIn("at initial contact batumi tower one three two", spoken)

    def test_he_is_not_told_to_report_the_beacon_he_cannot_yet_home(self):
        self.ctl.check_in("Pony 1-1")
        self.assertNotIn("report batumi", " ".join(texts(self.ctl)).lower())

    def test_the_letdown_is_worked_on_the_beacon(self):
        self.ctl.check_in("Pony 1-1")
        texts(self.ctl)
        self.ctl.report_beacon("Pony 1-1", 4000)
        self.assertTrue(all(tx.freq_mhz == R.BATUMI.freq_mhz for tx in self.ctl.out),
                        [str(t) for t in self.ctl.out])

    def test_a_banished_aircraft_is_worked_on_the_outer_hold(self):
        self.ctl.report_beacon("Hawk 1", 4000)
        self.ctl.report_missed("Hawk 1")
        texts(self.ctl)
        self.ctl.report_missed("Hawk 1")            # second miss -> banished
        banish = [tx for tx in self.ctl.out if "proceed" in tx.text]
        self.assertEqual(banish[0].freq_mhz, R.KOBULETI.freq_mhz)

    def test_a_single_controller_field_needs_no_handoff(self):
        one = dataclasses.replace(R.BATUMI_APPROACH, arrival_fix=None)
        ctl = atc.Controller(one)
        ctl.check_in("Pony 1-1")
        self.assertEqual(ctl.out[0].freq_mhz, R.BATUMI.freq_mhz)
        self.assertFalse(said(ctl, "contact"))     # drains ctl.out

class TestProfileRoundTrip(unittest.TestCase):
    """Approaches are stored, so a profile outlives the code that wrote it."""

    def test_every_nested_fix_is_rebuilt(self):
        rt = R.profile_from_dict(R.profile_to_dict(R.BATUMI_APPROACH))
        for key in ("beacon", "outer_hold", "arrival_fix"):
            self.assertIsInstance(getattr(rt, key), R.Fix, key)

    def test_stations_survive_the_round_trip(self):
        # A list of dicts passes every check and fails only when something asks
        # a Station for its name -- which for a stored profile is during bridge
        # start-up, in front of a waiting pilot. It did exactly that.
        rt = R.profile_from_dict(R.profile_to_dict(R.BATUMI_ASR))
        self.assertTrue(rt.stations)
        for s in rt.stations:
            self.assertIsInstance(s, R.Station)
        twr, ctr = R.TOWER, R.CENTER
        self.assertEqual(rt.station(), (twr.name, twr.freq_mhz))
        self.assertEqual(rt.station(enroute=True), (ctr.name, ctr.freq_mhz))

    def test_a_round_tripped_profile_can_still_pick_a_channel(self):
        # The failure this guards: a dict left in arrival_fix passes every other
        # check and only breaks when the controller asks which frequency to use.
        rt = R.profile_from_dict(R.profile_to_dict(R.BATUMI_APPROACH))
        self.assertEqual(rt.station(enroute=True), ("Batumi Approach", 128.0))
        self.assertEqual(rt.station(), ("Batumi Tower", 132.0))
        self.assertEqual(rt.station(banished=True), ("Kobuleti Departure", 124.0))

    def test_a_legacy_row_without_arrival_fix_still_loads(self):
        d = R.profile_to_dict(R.BATUMI_APPROACH)
        d.pop("arrival_fix")
        rt = R.profile_from_dict(d)
        self.assertIsNone(rt.arrival_fix)
        self.assertEqual(rt.station(enroute=True), rt.station())

if __name__ == "__main__":
    unittest.main()


class TestApproachVocabulary(unittest.TestCase):
    """The words have to match the procedure, not the one it grew out of.

    Every clearance, hold and report used to be the beacon letdown's literal
    text. Flown on the radar approach, a pilot was cleared for a "beacon
    approach", told he was "not at the beacon" and asked to "report beacon
    inbound" -- on a procedure with no beacon, in an aircraft with no receiver
    to find one. Naming a fix the aeroplane cannot navigate to is worse than
    saying nothing: it sounds like an instruction.
    """

    def setUp(self):
        self.asr = atc.Controller(R.BATUMI_ASR)
        self.ndb = atc.Controller(R.BATUMI_APPROACH)

    def test_the_radar_approach_is_not_called_a_beacon_approach(self):
        self.assertIn("radar", self.asr._approach_name())
        self.assertNotIn("beacon", self.asr._approach_name())
        self.assertIn("beacon", self.ndb._approach_name())

    def test_vectored_holding_is_an_altitude_not_a_fix(self):
        hold = self.asr._hold_phrase(6000)
        self.assertNotIn(R.BATUMI_ASR.beacon.name.lower(), hold.lower())
        self.assertIn("six thousand", hold)
        # and he is told the wait ends with a call from the controller, since
        # there is no fix for him to arrive at and report
        self.assertIn("call you", hold)

    def test_the_letdown_still_holds_at_its_beacon(self):
        hold = self.ndb._hold_phrase(6000)
        self.assertIn(R.BATUMI_APPROACH.beacon.name, hold)

    def test_no_beacon_report_is_ever_asked_for_on_a_radar_approach(self):
        self.assertNotIn("beacon", self.asr._report_phrase().lower())

    def test_AND_NOT_ESTABLISHED_EITHER_ON_A_TALKDOWN(self):
        """This test used to assert the opposite, which is how the bug lived.

            "A pilot doesn't know when he is established -- everything he gets
             he gets from the talk down. That instruction belongs in the ils
             module."

        On a surveillance approach he has no localiser to be established ON.
        Asking hands him a trigger he has no instrument to detect, so he holds
        his altitude forever or guesses -- and guessing on final in cloud is
        what the procedure exists to prevent.

        It is the same rule the function's own docstring already stated, just
        written too narrowly: it said "never a fix he cannot navigate to" and
        meant "never a trigger he cannot detect".
        """
        self.assertEqual(self.asr.profile.guidance, "talkdown")
        self.assertNotIn("established", self.asr._report_phrase().lower())

    def test_he_reports_what_he_can_SEE(self):
        """The window is the only instrument the procedure gives him."""
        self.assertIn("field in sight", self.asr._report_phrase())

    def test_but_an_ILS_pilot_IS_asked_to_report_established(self):
        """He has a localiser, so the trigger is one he can detect -- and this
        is the half that must not be lost while fixing the other."""
        import dataclasses
        ils = atc.Controller(dataclasses.replace(self.asr.profile,
                                                 guidance="intercept"))
        self.assertTrue(ils._vectored, "an ILS is vectored onto the localiser")
        self.assertIn("established", ils._report_phrase().lower())

    def test_nothing_the_vectored_controller_says_names_the_beacon(self):
        # The belt-and-braces check: drive a whole arrival and read every
        # transmission. A single leftover literal is a fix named to an aircraft
        # that cannot find it.
        c = atc.Controller(R.BATUMI_ASR)
        said = []
        c.say = lambda cs, text, ref=None, decided=None: said.append(text)
        c.check_in("Pony 1-1")
        c.request_approach("Pony 1-1")
        # The controller is CALLED "Batumi Approach", so the bare word proves
        # nothing -- what must not appear is the beacon used as a place: a fix
        # to fly to, hold at, or report over. Strip his own name, then look.
        beacon = R.BATUMI_ASR.beacon.name.lower()
        for line in said:
            bare = line.lower().replace(R.BATUMI_ASR.controller.lower(), "")
            self.assertNotIn("beacon", bare, line)
            self.assertNotIn(beacon, bare, line)


class TestVectoredHoldingIsVisual(unittest.TestCase):
    """Without a beacon, a hold is only real if the pilot can see.

    The letdown held everyone over one fix, and the fix was the separation:
    a published pattern, a level each. A radar approach has no fix, and most of
    these aircraft have no receiver to find one with, so the hold becomes "stay
    where you are" -- which in cloud is not an instruction, it is a hope. The
    levels still keep them apart; being in clear air is what makes each level
    holdable.
    """

    def test_the_vectored_stack_starts_above_the_cloud_tops(self):
        p = R.BATUMI_ASR
        self.assertGreater(p.stack_ft[0], p.tops_ft,
                           "aircraft told to hold present position inside cloud")
        self.assertGreaterEqual(p.stack_ft[0] - p.tops_ft, p.vmc_margin_ft)

    def test_the_beacon_letdown_may_hold_lower(self):
        # It has a fix to hold over, so cloud does not stop it.
        self.assertLess(R.BATUMI_APPROACH.stack_ft[0], R.BATUMI_ASR.stack_ft[0])

    def test_a_higher_ceiling_pushes_the_vectored_stack_up(self):
        low = dataclasses.replace(R.BATUMI_ASR, ceiling_ft=400)
        high = dataclasses.replace(R.BATUMI_ASR, ceiling_ft=6000)
        self.assertGreater(high.stack_ft[0], low.stack_ft[0])
        self.assertGreater(high.stack_ft[0], high.tops_ft)

    def test_the_levels_still_separate(self):
        p = R.BATUMI_ASR
        gaps = {b - a for a, b in zip(p.stack_ft, p.stack_ft[1:])}
        self.assertEqual(gaps, {p.hold_step_ft})


class TestTheBlindEngineIsToldWhatRadarSees(unittest.TestCase):
    """The sequencing brain cannot see, so somebody has to tell it.

    Heard on the radio: a flight established on the final approach course at
    ten miles and two thousand feet checked in. The vectoring half was talking
    it down; the separation half had never heard the callsign, filed it as a
    fresh arrival and assigned it the bottom of the stack -- climb to five
    thousand and hold. The agent voiced both in one transmission: "you are on
    final" and "hold present position, maintain five thousand".

    Neither half was wrong about its own job. The gap was that the half making
    the decision was blind and nobody handed it the picture.
    """

    def setUp(self):
        self.c = atc.Controller(R.BATUMI_ASR)
        self.said = []
        self.c.say = lambda cs, text, ref=None, decided=None: self.said.append(text)

    def test_an_aircraft_on_final_is_not_put_in_the_holding_stack(self):
        self.assertTrue(self.c.seen_on_final("Pony 1-1", size=3))
        ac = self.c.get("Pony 1-1")
        self.assertEqual(ac.phase, atc.Phase.CLEARED)
        self.assertIsNone(ac.assigned_ft, "he was given a holding level anyway")

    def test_he_owns_the_letdown_rather_than_queueing_for_it(self):
        self.c.seen_on_final("Pony 1-1")
        self.assertEqual(self.c._in_letdown(), "Pony 1-1")

    def test_checking_in_afterwards_does_not_stack_him(self):
        self.c.seen_on_final("Pony 1-1")
        self.c.request_approach("Pony 1-1")
        for line in self.said:
            self.assertNotIn("hold", line.lower(), line)

    def test_seeding_twice_is_harmless(self):
        self.assertTrue(self.c.seen_on_final("Pony 1-1"))
        self.assertFalse(self.c.seen_on_final("Pony 1-1"))

    def _seen(self, c, *callsigns):
        """What the bridge does on every transmission: tell the blind engine
        what the scope shows. Without it nothing can be sequenced on a radar
        approach, which is the point -- see Controller.may_be_sequenced."""
        for cs in callsigns:
            c.get(cs)
            c.note_radar_contact(cs, True)

    def test_a_second_aircraft_still_gets_separated(self):
        # Seeding must not switch the engine off: the one behind still holds.
        self.c.seen_on_final("Pony 1-1")
        self.c.check_in("Viper 2-1")
        # Radar has them both. On a radar approach that is what makes them
        # aircraft rather than callsigns, and the bridge says so on every
        # transmission.
        self._seen(self.c, "Pony 1-1", "Viper 2-1")
        self.c.request_approach("Viper 2-1")
        self.assertTrue(any("hold" in l.lower() for l in self.said),
                        "the following aircraft was not separated")


class TestHeadingsAreSpokenLikeHeadings(unittest.TestCase):
    def test_north_is_three_six_zero(self):
        # "Zero zero zero" is not a heading anyone flies, and a pilot hearing it
        # wonders what was garbled. It reached the air in a holding clearance:
        # "one eight zero outbound, zero zero zero inbound".
        self.assertEqual(atc.spell_hdg(0), "three six zero")
        self.assertEqual(atc.spell_hdg(360), "three six zero")

    def test_ordinary_headings_are_unchanged(self):
        self.assertEqual(atc.spell_hdg(127), "one two seven")
        self.assertEqual(atc.spell_hdg(90), "zero nine zero")

    def test_the_holding_racetrack_reads_back_sensibly(self):
        c = atc.Controller(R.BATUMI_ASR)
        hold = c._hold_phrase(8000)
        self.assertIn("one eight zero outbound", hold)
        self.assertIn("three six zero inbound", hold)


class TestStationsAreChosenByRole(unittest.TestCase):
    """Who works an arrival is a fact about their job, not their list index.

    Picking the last station was correct while the list happened to end at
    Tower. Appending a mission commander made it silently wrong -- a landing
    aircraft would have been sent to the overlord's frequency -- and nothing
    about the change looked like it touched approaches.
    """

    def test_the_landing_goes_to_tower_not_to_whoever_is_last(self):
        self.assertEqual(R.BATUMI_ASR.station(), (R.TOWER.name, R.TOWER.freq_mhz))

    def test_enroute_goes_to_center(self):
        self.assertEqual(R.BATUMI_ASR.station(enroute=True),
                         (R.CENTER.name, R.CENTER.freq_mhz))

    def test_the_overlord_is_never_an_arrival_station(self):
        for kwargs in ({}, {"enroute": True}, {"banished": True}):
            self.assertNotEqual(R.BATUMI_ASR.station(**kwargs)[0], R.OVERLORD.name)

    def test_a_field_with_no_tower_falls_back_to_approach(self):
        no_twr = dataclasses.replace(
            R.BATUMI_ASR, stations=[R.CENTER, R.APPROACH, R.OVERLORD])
        self.assertEqual(no_twr.station()[0], R.APPROACH.name)


class TestNobodyClearedNobodyVectored(unittest.TestCase):
    """The radar thread may only turn the aircraft that owns the approach.

    The state that was wrong is the ordinary one: a stack with nobody cleared
    yet. The filter applied only when somebody DID own the approach, so with
    nobody cleared it switched itself off and vectored the lot. Two Mustangs
    holding at five and six thousand were each told to turn onto the intercept
    and climb to twelve, seconds after being told to hold where they were --
    reported from the cockpit as "we have duplicate controllers again". It was
    one controller disagreeing with itself, which is worse.
    """

    def setUp(self):
        from marshall.atc import agent_atc as A
        _b = A.Bridge()

        def may(*a, **k):
            return A.may_be_vectored(_b, *a, **k)
        self.may = may
        self.ctl = atc.Controller(profile())

    def test_a_single_ship_is_always_vectored(self):
        self.ctl.report_beacon("Pony 1-1", 4000)
        texts(self.ctl)
        self.assertTrue(self.may(self.ctl, "Pony 1-1"))

    def test_a_full_stack_with_nobody_cleared_vectors_nobody(self):
        self.ctl.check_in("Pony 1-1")
        self.ctl.check_in("Pony 1-2")
        texts(self.ctl)
        for a in self.ctl.aircraft.values():
            a.phase = atc.Phase.HOLDING
        self.assertIsNone(self.ctl.owns_the_approach())
        self.assertFalse(self.may(self.ctl, "Pony 1-1"))
        self.assertFalse(self.may(self.ctl, "Pony 1-2"))

    def test_only_the_one_who_owns_it_is_vectored(self):
        self.ctl.report_beacon("Pony 1-1", 4000)     # cleared into the letdown
        self.ctl.report_beacon("Pony 1-2", 5000)     # holds
        texts(self.ctl)
        self.assertTrue(self.may(self.ctl, "Pony 1-1"))
        self.assertFalse(self.may(self.ctl, "Pony 1-2"))

    def test_radar_traffic_counts_even_with_an_empty_stack(self):
        """The blind engine forgets over a restart. Radar does not.

        Two Mustangs were on the scope and neither had spoken since the bridge
        came back, so the stack held nobody -- and both were vectored, at
        different headings and different altitudes, on one frequency.
        """
        self.assertEqual(len(self.ctl.aircraft), 0)
        self.assertFalse(self.may(self.ctl, "Pony 1-1", traffic=True))
        self.assertFalse(self.may(self.ctl, "Pony 1", traffic=True))
        # ...and a lone contact the controller has never heard of is not
        # vectored either. He has not asked for an approach, so he is not on
        # one -- see the CAS flight that was vectored onto the Batumi final
        # the whole way to its ingress point.
        self.assertFalse(self.may(self.ctl, "Pony 1-1", traffic=False))


class TestVisualApproach(unittest.TestCase):
    """Asking for a visual should be enough.

    "the controllers have to be forced to give us a visual approach. need to
     make that more natural."

    Backwards, as it stood: the surveillance approach is the hard,
    weather-driven case and a visual is what everybody flies on a clear day.
    The agent was refusing outright -- "I have no visual approach published
    here, only the surveillance radar approach."
    """

    def setUp(self):
        self.ctl = atc.Controller(profile())

    def said(self, i=0):
        return self.ctl.out[i].text.lower()

    def test_asking_is_enough(self):
        self.ctl.request_visual("Pony 1-1")
        self.assertIn("cleared visual approach", self.said())
        self.assertEqual(self.ctl.get("Pony 1-1").phase, atc.Phase.CLEARED)

    def test_he_is_asked_to_report_the_field_if_he_has_not(self):
        self.ctl.request_visual("Pony 1-1")
        self.assertIn("report the field in sight", self.said())

    def test_with_the_field_in_sight_he_gets_the_wind_instead(self):
        self.ctl.request_visual("Pony 1-1", field_in_sight=True)
        self.assertIn("wind", self.said())
        self.assertNotIn("report the field", self.said())

    def test_a_visual_does_not_jump_the_queue(self):
        """Spacing is the one thing the controller still owns once the pilot is
        flying his own approach."""
        self.ctl.request_visual("Pony 1-1")
        self.ctl.request_visual("Hammer 1-1")
        self.assertEqual(self.ctl.get("Hammer 1-1").phase, atc.Phase.HOLDING)
        self.assertIn("expect the visual", self.said(1))

    def test_the_talkdown_stops(self):
        """Reading ranges to a man looking at the runway is chatter over
        somebody busy -- and it is the difference between a visual approach and
        a talkdown he did not ask for."""
        from marshall.atc import agent_atc as _A

        def may_be_vectored(*a, **k):
            return _A.may_be_vectored(_A.Bridge(), *a, **k)
        self.ctl.request_visual("Pony 1-1")
        self.assertFalse(may_be_vectored(self.ctl, "Pony 1-1"))

    def test_a_formation_flies_the_visual_as_a_formation(self):
        """INVERTED 30 July. This asserted that asking for a visual broke the
        flight up first -- the controller deciding a two-ship could not fly one
        visual approach. It can, and a section joining up for the overhead is
        about the most ordinary thing two aeroplanes do.

            "if a flight wants to fly an approach in formation - they can.
             That's up to the flight lead."
        """
        self.ctl.check_in("Pony 1-1", 2)
        self.ctl.out.clear()
        self.ctl.request_visual("Pony 1-1")
        self.assertFalse(any("break up" in tx.text.lower() for tx in self.ctl.out))
        self.assertIn("Pony 1", self.ctl.aircraft)
        self.assertTrue(self.ctl.get("Pony 1").on_visual)


class TestWaitForTheCheckIn(unittest.TestCase):
    """A controller works the men on HIS frequency, and nobody else.

    "when we got a handoff from center to approach, by the time I switched
     over, approach was already half done with the first instruction"

    He arrives mid-sentence, has missed a heading and an altitude, and has no
    way of knowing what he missed. Waiting is what the check-in is FOR.
    """

    def setUp(self):
        from marshall.atc import agent_atc
        self.A = agent_atc
        # A fresh store IS the reset -- this used to be `_heard_on.clear()` on a
        # module global, which every case had to remember. See [LAYERS.md] step 2.
        self.bridge = agent_atc.Bridge()
        self.ctl = atc.Controller(profile())
        self.ctl.report_beacon("Pony 1-1", 4000)     # known, cleared, being worked
        texts(self.ctl)
        self.approach_hz = 124.0e6
        self.center_hz = 139.0e6

    def test_not_worked_before_he_has_said_a_word_here(self):
        self.assertFalse(
            self.A.may_be_vectored(self.bridge, self.ctl, "Pony 1-1", freq_hz=self.approach_hz))

    def test_not_worked_while_he_is_still_on_the_previous_frequency(self):
        """The handoff has been issued; he has not switched yet."""
        self.bridge.heard_on["Pony 1-1"] = self.center_hz
        self.assertFalse(
            self.A.may_be_vectored(self.bridge, self.ctl, "Pony 1-1", freq_hz=self.approach_hz))

    def test_worked_as_soon_as_he_checks_in(self):
        self.bridge.heard_on["Pony 1-1"] = self.approach_hz
        self.assertTrue(
            self.A.may_be_vectored(self.bridge, self.ctl, "Pony 1-1", freq_hz=self.approach_hz))

    def test_the_rule_is_off_when_no_frequency_is_given(self):
        """Callers that do not care about channels must not be broken by it."""
        self.assertTrue(self.A.may_be_vectored(self.bridge, self.ctl, "Pony 1-1"))


class TestTheMissedApproachLatch(unittest.TestCase):
    """Who is flying the published missed, held by the side that can know.

    A latch is a liability unless it releases, so the release is tested harder
    than the set: an aircraft stuck on the missed approach for ever would be a
    worse bug than the reversals it was built to stop.
    """

    def setUp(self):
        from marshall.atc import agent_atc
        from marshall.atc import asr
        from marshall.core import route as R
        self.A, self.asr, self.p = agent_atc, asr, R.BATUMI_ASR
        # A fresh store IS the reset -- `_flying_missed.clear()` on a module
        # global was the old way. See [LAYERS.md] step 2.
        self.bridge = agent_atc.Bridge()
        self.ctl = atc.Controller(self.p)

    def at(self, nm, alt, radial=None):
        return self.asr.Position(range_nm=nm, alt_ft=alt,
                                 radial_deg=radial or self.p.missed_hdg,
                                 heading_deg=self.p.missed_hdg)

    def test_it_starts_when_the_geometry_hands_out_the_procedure(self):
        self.A.note_missed(self.bridge, "Pony 1-1", "missed", self.ctl)
        self.assertTrue(
            self.A.flying_the_missed(self.bridge, "Pony 1-1", self.at(4, 1800), self.p, self.ctl))

    def test_it_also_starts_when_he_SAYS_he_is_going_around(self):
        """The two ways a controller finds out. Either is enough."""
        self.ctl.report_missed("Pony 1-1")
        self.assertTrue(
            self.A.flying_the_missed(self.bridge, "Pony 1-1", self.at(4, 1800), self.p, self.ctl))

    def test_it_releases_at_the_missed_approach_altitude(self):
        self.A.note_missed(self.bridge, "Pony 1-1", "missed", self.ctl)
        self.assertFalse(
            self.A.flying_the_missed(self.bridge, "Pony 1-1",
                                     self.at(6, self.p.missed_climb_ft), self.p,
                                     self.ctl))

    def test_it_releases_outside_the_terminal_area(self):
        self.A.note_missed(self.bridge, "Pony 1-1", "missed", self.ctl)
        self.assertFalse(
            self.A.flying_the_missed(self.bridge, "Pony 1-1",
                                     self.at(self.p.final_intercept_nm + 2, 2000),
                                     self.p, self.ctl))

    def test_it_does_not_leak_between_aircraft(self):
        self.A.note_missed(self.bridge, "Pony 1-1", "missed", self.ctl)
        self.assertFalse(
            self.A.flying_the_missed(self.bridge, "Hammer 1-1", self.at(4, 1800), self.p,
                                     self.ctl))

    def test_an_ordinary_vector_does_not_set_it(self):
        self.A.note_missed(self.bridge, "Pony 1-1", "vector", self.ctl)
        self.assertFalse(
            self.A.flying_the_missed(self.bridge, "Pony 1-1", self.at(4, 1800), self.p, self.ctl))


class TestTheEndOfAnApproachIsAudible(unittest.TestCase):
    """A pilot must be able to tell "he has me down" from "he has crashed".

        "B7 — how will I know he has me down and stopped?"

    He could not. The controller composes a farewell and the bridge dropped it,
    so the observable end of every approach was silence -- the same bug as an
    engineering channel that says nothing, and worse here because it is the last
    thing that happens on every flight.
    """

    def setUp(self):
        self.ctl = atc.Controller(profile())
        self.ctl.report_beacon("Hoover 1-1", 4000)
        self.ctl.out.clear()

    def test_a_stopped_aeroplane_is_never_cleared_to_land(self):
        """The live failure, and both rehearsal runs found it too.

        Radar sees him stop and `report_down` says the right thing. Eight
        seconds later he reports it himself -- "on the ground, runway one
        tree" -- the taxonomy routes that to `report_landed`, and the engine
        answered a stationary aeroplane with a landing clearance.

        The agent hid it: with nothing sensible to voice it said "go ahead",
        so the transcript read as merely unhelpful rather than wrong. Only the
        recorder showed the controller had gone backwards a whole leg.
        """
        self.ctl.report_down("Hoover 1-1")
        self.ctl.out.clear()
        self.ctl.report_landed("Hoover 1-1")
        said = " ".join(x.text for x in self.ctl.out).lower()
        self.assertNotIn("cleared to land", said)
        self.assertIn("runway", said, "he is still told to get off it")

    def test_and_he_is_still_cleared_when_he_is_actually_flying(self):
        """The other half. A man with the field in sight and still airborne is
        owed the clearance and the wind -- the guard must not eat that."""
        self.ctl.report_landed("Hoover 1-1")
        self.assertIn("cleared to land",
                      " ".join(x.text for x in self.ctl.out).lower())

    def test_he_says_something_when_you_are_down(self):
        self.ctl.report_down("Hoover 1-1")
        said = " ".join(t.text for t in self.ctl.out).lower()
        self.assertTrue(said.strip(), "silence is the bug")
        self.assertIn("hoover one one", said, "and it has to be addressed to him")

    def test_it_tells_him_to_get_off_the_runway(self):
        """"Landing assured, good day" is what you say to somebody still in the
        air. Said to a man sitting on the runway it is a controller who has not
        noticed the aeroplane arrive; what a tower says after the roll is where
        to go.

        CHANGED 10 August: it used to end "taxi to parking", and this asserted
        it. A pilot reported it from the cockpit -- *"Batumi Tower just gave me
        clearance to taxi to parking when that's ground's job"* -- and he is
        right. Tower owns the RUNWAY; the taxiways are Ground's. It is the same
        fault as Ground clearing an aircraft for take-off, in the other
        direction, and the same invariant refuses both.

        So what Tower owes him is the runway: get off it. Where to go afterwards
        is the next controller's, and `sortie_phase = "landed"` is what hands
        him over.
        """
        self.ctl.report_down("Hoover 1-1")
        said = " ".join(t.text for t in self.ctl.out).lower()
        self.assertIn("runway", said)
        self.assertNotIn("parking", said,
                         "Tower issued a taxi clearance that is not his")

    def test_being_down_moves_the_sortie_phase(self):
        """Without this nothing can hand a landed aeroplane to Ground (#77).

        `Phase.LANDED` is the SEPARATION engine's enum -- where he sits in the
        arrival queue. `sortie_phase` is what he is DOING, and it is the one the
        ladder reads.
        """
        self.ctl.report_down("Hoover 1-1")
        ac = self.ctl.get("Hoover 1-1")
        self.assertEqual(ac.sortie_phase, "landed")

    def test_reporting_a_landing_from_the_air_still_reads_that_way(self):
        """The other case must not become a taxi instruction to an aeroplane on
        short final."""
        self.ctl.report_landed("Hoover 1-1")
        said = " ".join(t.text for t in self.ctl.out).lower()
        self.assertNotIn("taxi", said)

    def test_he_is_out_of_the_letdown_afterwards(self):
        """The goodbye is not decoration -- it is the moment the runway frees
        for whoever is holding behind him."""
        self.assertEqual(self.ctl.owns_the_approach(), "Hoover 1-1")
        self.ctl.report_down("Hoover 1-1")
        self.assertNotEqual(self.ctl.owns_the_approach(), "Hoover 1-1")


class TestPhraseologyIsAControllersNotAPilots(unittest.TestCase):
    """"Landing assured" is the PILOT's determination, not a controller's.

    It is not a phrase a real controller uses, and having one say it puts a
    judgement in his mouth that was never his to make. What he owes a man with
    the field in sight is the clearance and the wind.
    """

    def setUp(self):
        self.ctl = atc.Controller(profile())
        self.ctl.report_beacon("Hoover 1-1", 4000)
        self.ctl.out.clear()

    def test_the_controller_never_assures_a_landing(self):
        self.ctl.report_landed("Hoover 1-1")
        said = " ".join(t.text for t in self.ctl.out).lower()
        self.assertNotIn("assured", said)

    def test_field_in_sight_earns_a_clearance_and_the_wind(self):
        self.ctl.report_landed("Hoover 1-1")
        said = " ".join(t.text for t in self.ctl.out).lower()
        self.assertIn("cleared to land", said)
        self.assertIn("wind", said)


class TestAHoldHeCanActuallyFly(unittest.TestCase):
    """An aeroplane with no navaid cannot hold OVER anything.

        "When ATC asks an airplane with no navaids to hold, it's going to need
         to help him... 'turn 180 heading fly 2 mins, then right turn to 360 and
         fly 2 minutes'. Right now he just says to hold."

    So the hold is a shape and a clock. A heading with no leg time is not a
    hold at all -- it is a vector he flies until somebody stops him, and he ends
    up wherever that put him.
    """

    def setUp(self):
        self.radar = atc.Controller(R.BATUMI_ASR)          # no navaid
        self.beacon = atc.Controller(R.BATUMI_APPROACH)    # he can find the fix

    def test_it_carries_both_headings_and_the_time_on_each(self):
        said = self.radar._hold_phrase(6000)
        self.assertIn("one eight zero outbound", said)
        self.assertIn("three six zero inbound", said)
        self.assertEqual(said.count("one minute"), 2, said)

    def test_it_says_which_way_he_turns(self):
        """Everybody turning the same way keeps the pattern predictable when the
        only thing separating them is altitude."""
        self.assertIn("right turns", self.radar._hold_phrase(6000))

    def test_it_still_carries_the_level(self):
        self.assertIn("six thousand", self.radar._hold_phrase(6000))

    def test_no_bare_digits_reach_the_voice(self):
        said = self.radar._hold_phrase(6000)
        self.assertNotRegex(said, r"\d")

    def test_a_field_with_a_beacon_holds_as_published(self):
        """He can find the place, so describing a racetrack at him is noise."""
        said = self.beacon._hold_phrase(6000)
        self.assertIn("as published", said)
        self.assertNotIn("outbound", said)

    def test_the_leg_length_is_spoken_as_words(self):
        self.assertEqual(atc.spell_minutes(1), "one minute")
        self.assertEqual(atc.spell_minutes(2), "two minutes")
        self.assertEqual(atc.spell_minutes(1.5), "one and a half minutes")


class TestEveryHoldGoesThroughOnePhrase(unittest.TestCase):
    """There were two ways to say "hold", and one of them was wrong.

    A second path wrote its own "hold at BATUMI as published" instead of asking
    `_hold_phrase`, so on a RADAR approach -- where the pilot has no receiver
    for that beacon -- he was told to hold over something he cannot find. Two
    ways of saying the same thing is how one of them ends up wrong.
    """

    def test_the_second_aircraft_gets_a_hold_he_can_fly(self):
        c = atc.Controller(R.BATUMI_ASR)
        c.report_beacon("Pony 1-1", 6000)
        c.out.clear()
        c.report_beacon("Hammer 1-2", 5000)
        said = " ".join(str(t) for t in c.out)
        self.assertIn("outbound", said)
        self.assertIn("turns", said)
        self.assertNotIn("as published", said)

    def test_on_a_beacon_field_it_is_still_the_published_hold(self):
        c = atc.Controller(R.BATUMI_APPROACH)
        c.report_beacon("Pony 1-1", 6000)
        c.out.clear()
        c.report_beacon("Hammer 1-2", 5000)
        self.assertIn("as published", " ".join(str(t) for t in c.out))


class TestWhatHeIsFlyingDecidesTheHold(unittest.TestCase):
    """The equipment suffix, except the sim states it and nobody can lie.

        "somehow we need to infer or request what equipment a pilot has. IRL
         it's in the IFR flight plan. In DCS, we could make a module table?"

        "there are some aircraft that can use a vortac or tacan station."

    And that second remark is why capability is a SET rather than a rating. The
    DCS F-16 carries TACAN, ILS and an inertial platform and NO ADF: better
    equipped than a Mustang in every respect except the one that matters for
    homing this field's NDB.
    """

    def hold_for(self, kit, profile=None):
        c = atc.Controller(profile or R.BATUMI_APPROACH)
        c.report_beacon("Pony 1-1", 6000)
        c.note_equipment("Pony 1-1", kit)
        return c._hold_phrase(6000, c.aircraft["Pony 1-1"].kit)

    def test_a_homer_may_hold_at_the_beacon(self):
        self.assertIn("as published", self.hold_for(E.receivers("P-51D-30-NA")))

    def test_dead_reckoning_gets_the_pattern_instead(self):
        said = self.hold_for(E.receivers("P-47D-30"))
        self.assertNotIn("as published", said)
        self.assertIn("outbound", said)
        self.assertIn("minute", said)

    def test_an_inertial_platform_can_hold_anywhere(self):
        """He knows where he is; the ground does not have to help him."""
        self.assertIn("as published", self.hold_for(E.receivers("F-16C_50")))

    def test_a_jet_with_no_ADF_cannot_home_the_NDB_itself(self):
        """The asymmetry, stated on its own so it cannot be lost in a refactor.
        Take the inertial platform away and the F-16 is worse off than the
        Mustang at this particular field."""
        kit = E.receivers("F-16C_50") - {"ins"}
        self.assertFalse(E.can_use(kit, "ndb"))
        self.assertTrue(E.can_use(E.receivers("P-51D-30-NA"), "ndb"))

    def test_a_vortac_answers_to_either_receiver(self):
        self.assertTrue(E.can_use(frozenset({"vor"}), "vortac"))
        self.assertTrue(E.can_use(frozenset({"tacan"}), "vortac"))
        self.assertFalse(E.can_use(frozenset({"adf"}), "vortac"))

    def test_nobody_has_told_us_at_a_beacon_field_means_able(self):
        """It is flying a beacon letdown; it has already shown it can home the
        beacon by being in the procedure at all."""
        self.assertIn("as published", self.hold_for(None))

    def test_at_a_radar_field_nobody_holds_at_a_fix(self):
        """There is nothing to hold over, whatever he is carrying."""
        for t in ("P-51D-30-NA", "P-47D-30", "F-16C_50"):
            with self.subTest(t=t):
                said = self.hold_for(E.receivers(t), R.BATUMI_ASR)
                self.assertNotIn("as published", said)

    def test_the_equipment_is_remembered_on_the_aircraft(self):
        c = atc.Controller(R.BATUMI_ASR)
        c.report_beacon("Pony 1-1", 6000)
        c.note_equipment("Pony 1-1", E.receivers("P-51D-30-NA"))
        self.assertEqual(c.aircraft["Pony 1-1"].kit, frozenset({"adf"}))

    def test_noting_equipment_for_somebody_not_on_the_board_is_harmless(self):
        c = atc.Controller(R.BATUMI_ASR)
        c.note_equipment("Ghost 9-9", frozenset())
        self.assertNotIn("Ghost 9-9", c.aircraft)


class TestNobodyIsSequencedUntilRadarHasHim(unittest.TestCase):
    """"That aircraft hasn't been positively ID'd and assigned an association.
    Something is fundamentally broken here."

    It was, and this is it. "Radar contact" is a specific thing a controller
    says, and in a radar environment EVERYTHING depends on it: a pilot cannot be
    vectored, sequenced or cleared for the approach until he has been identified.
    The engine had no such precondition -- anything with a callsign got a level
    in the stack -- so a mis-heard read-back became an aircraft called
    "Maintained 2", took the letdown, and held a real pilot as number two behind
    a sentence.

    The deeper reason it was so damaging: the engine is BLIND. A real aeroplane
    lands or leaves radar cover, and something removes it. A thing that was
    never on radar cannot leave it, so nothing could ever contradict it.
    """

    def out(self, c):
        return " | ".join(str(t) for t in c.out)

    def seen(self, c, cs):
        c.get(cs)
        c.note_radar_contact(cs, True)

    def test_an_unidentified_callsign_gets_no_place_in_the_queue(self):
        c = atc.Controller(R.BATUMI_ASR)
        c.request_approach("Maintained 2")
        said = self.out(c)
        self.assertIn("not radar identified", said)
        self.assertNotIn("hold at", said)
        self.assertIsNone(c.aircraft["Maintained 2"].assigned_ft)

    def test_and_holds_nobody_behind_it(self):
        """The whole cost of the bug: a real pilot queued behind a sentence."""
        c = atc.Controller(R.BATUMI_ASR)
        c.request_approach("Maintained 2")
        c.out.clear()
        self.seen(c, "Falcon 1-1")
        c.request_approach("Falcon 1-1")
        said = self.out(c)
        self.assertIn("cleared", said)
        self.assertNotIn("number two", said)

    def test_a_radar_identified_aircraft_is_worked_normally(self):
        c = atc.Controller(R.BATUMI_ASR)
        self.seen(c, "Falcon 1-1")
        c.request_approach("Falcon 1-1")
        self.assertIn("cleared", self.out(c))

    def test_losing_radar_contact_is_as_visible_as_finding_it(self):
        c = atc.Controller(R.BATUMI_ASR)
        self.seen(c, "Falcon 1-1")
        c.note_radar_contact("Falcon 1-1", False)
        self.assertFalse(c.may_be_sequenced(c.aircraft["Falcon 1-1"]))

    def test_a_procedural_field_is_untouched(self):
        """A beacon letdown has no radar at all. Being unseen is the NORMAL
        condition there and this rule must not apply, or the controller refuses
        to work anybody."""
        c = atc.Controller(R.BATUMI_APPROACH)
        c.request_approach("Pony 1-1")
        said = self.out(c)
        self.assertNotIn("not radar identified", said)
        self.assertTrue("hold" in said.lower() or "cleared" in said.lower())


class TestAHoldNobodyWillFly(unittest.TestCase):
    """"then issued me a hold for some reason" -- and he was right.

    Not a mis-heard callsign and not a ghost: the engine meant it. Entering the
    stack is how an arrival gets sequenced even when the sequence is one
    aeroplane long, and SAYING so was the same statement as doing so. A lone
    arrival with the letdown free therefore got a full holding pattern and a
    clearance for the approach in one breath.

    That is worse than noise. A pattern nobody will fly, read to a pilot who
    has just been cleared, makes him choose which of two instructions to obey.
    """

    def setUp(self):
        self.ctl = atc.Controller(R.BATUMI_ASR)

    def _admit(self, *names):
        for cs in names:
            self.ctl.get(cs)
            self.ctl.note_radar_contact(cs)

    def test_a_lone_arrival_is_cleared_and_not_told_to_hold(self):
        self._admit("Pony 1-1")
        self.ctl.request_approach("Pony 1-1")
        said = " | ".join(t.text for t in self.ctl.out)
        self.assertIn("cleared", said.lower())
        self.assertNotIn("outbound one minute", said)

    def test_the_hold_survives_where_it_is_real(self):
        """Silencing it must not delete it: the second arrival genuinely has to
        hold, and he needs the pattern -- headings and leg times -- because he
        may have no navaid to hold on."""
        self._admit("Pony 1-1", "Pony 1-2")
        self.ctl.request_approach("Pony 1-1")
        self.ctl.out.clear()
        self.ctl.request_approach("Pony 1-2")
        said = " | ".join(t.text for t in self.ctl.out).lower()
        self.assertIn("minute", said)
        self.assertIn("number two", said)

    def test_the_pattern_comes_before_the_sequence_number(self):
        """"Continue holding, number two" has to follow the instructions it
        refers to. Reversed, the controller numbers him in a queue before
        telling him what the queue is."""
        self._admit("Pony 1-1", "Pony 1-2")
        self.ctl.request_approach("Pony 1-1")
        self.ctl.out.clear()
        self.ctl.request_approach("Pony 1-2")
        said = " | ".join(t.text for t in self.ctl.out).lower()
        self.assertLess(said.index("minute"), said.index("number two"))

    def test_he_is_still_holding_even_though_nobody_said_so(self):
        """The state change is not what was removed -- only the transmission.
        A third arrival must still be stacked above him."""
        self._admit("Pony 1-1")
        self.ctl.request_approach("Pony 1-1")
        self.assertIs(self.ctl.aircraft["Pony 1-1"].phase, atc.Phase.CLEARED)


class TestACheckInDoesNotUndoAClearance(unittest.TestCase):
    """THE CAUSE of #50, as opposed to the symptom below.

    A pilot checks in every time he changes frequency, and the ladder gives him
    six or seven of those in a sortie. `check_in` set the phase to ENROUTE
    unconditionally -- including after he had been cleared for the approach and
    put in the letdown. Nothing there touches `_letdown`, so he became an
    ENROUTE aircraft holding the approach slot, and the next `request_approach`
    walked him into the stack, which only admits UNKNOWN and ENROUTE.

    From there he was simultaneously the aircraft on the approach and one
    waiting for it, and every request came back "number two". He held at 44 nm
    and declared an emergency.

    `seed_from_radar` had exactly this guard already. Two functions doing the
    same job from different evidence, and only one protected the clearance.
    """

    def setUp(self):
        self.ctl = atc.Controller(R.BATUMI_ASR)
        self.ctl.t = 0.0

    def cleared(self, cs="Sockeye"):
        self.ctl.check_in(cs)
        self.ctl.note_radar_contact(cs)
        ac = self.ctl.aircraft[self.ctl._resolve(cs)]
        ac.phase = atc.Phase.CLEARED
        self.ctl._set_letdown(None, cs)
        self.ctl.out.clear()
        return ac

    def test_checking_in_again_does_not_demote_a_cleared_aircraft(self):
        ac = self.cleared()
        self.ctl.check_in("Sockeye")
        self.assertIs(ac.phase, atc.Phase.CLEARED)

    def test_the_whole_live_chain_no_longer_deadlocks(self):
        """Cleared, changes frequency, asks again -- which is just flying the
        ladder. He must not end up holding behind himself."""
        ac = self.cleared()
        self.ctl.check_in("Sockeye")          # the frequency change
        self.ctl.request_approach("Sockeye")
        self.assertIsNot(ac.phase, atc.Phase.HOLDING)
        said = " | ".join(t.text for t in self.ctl.out).lower()
        self.assertNotIn("number two", said)

    def test_a_landed_aircraft_is_not_put_back_in_the_arrival_flow(self):
        """Held for the same reason. A jet taxiing in that says something is
        not an enroute arrival."""
        self.ctl.check_in("Sockeye")
        ac = self.ctl.aircraft[self.ctl._resolve("Sockeye")]
        ac.phase = atc.Phase.LANDED
        self.ctl.check_in("Sockeye")
        self.assertIs(ac.phase, atc.Phase.LANDED)

    def test_a_genuine_new_arrival_still_becomes_enroute(self):
        """The guard must not stop the thing check_in is FOR."""
        self.ctl.check_in("Hoover")
        self.assertIs(self.ctl.aircraft[self.ctl._resolve("Hoover")].phase,
                      atc.Phase.ENROUTE)

    def test_reaching_the_impossible_state_is_recorded_not_absorbed(self):
        """The repair below is right on the radio and must never be silent --
        a corrected symptom with no trace is how the cause survived."""
        ac = self.cleared()
        ac.phase = atc.Phase.HOLDING          # force it, as the bug used to
        self.ctl._try_clear(requested_by="Sockeye")
        self.assertTrue(self.ctl.anomalies, "an impossible state was repaired "
                                            "with nothing recorded")


class TestNobodyIsNumberTwoBehindHimself(unittest.TestCase):
    """The deadlock that ended a live sortie in a Mayday, 31 July.

    Sockeye was cleared for the approach, which put him in the letdown. He was
    then returned to HOLDING while he still held the slot -- so he was at once
    the aircraft ON the approach and an aircraft waiting for it.

    Every request after that reached the "letdown is occupied" branch, found it
    occupied, and told him he was number two behind the only other aeroplane in
    the sky, which was him. `_next_up` would have returned him immediately; on
    that branch it is never asked. Four transmissions of it, forty-four miles
    out, and then he declared an emergency to get out of the hold. From the
    cockpit it is indistinguishable from having been forgotten.

    The bug is one aircraft in two places at once, and the check is cheap:
    the man in the letdown is not queued behind the letdown.
    """

    def setUp(self):
        self.ctl = atc.Controller(R.BATUMI_ASR)
        self.ctl.t = 0.0

    def _stuck(self, cs="Sockeye"):
        """Him, in the letdown and in the stack simultaneously."""
        self.ctl.get(cs)
        self.ctl.note_radar_contact(cs)
        ac = self.ctl.aircraft[self.ctl._resolve(cs)]
        ac.phase, ac.assigned_ft = atc.Phase.HOLDING, 5000
        self.ctl._set_letdown(None, cs)
        self.ctl.out.clear()
        return ac

    def test_he_is_told_he_is_cleared_rather_than_held(self):
        ac = self._stuck()
        self.ctl._try_clear(requested_by="Sockeye")
        said = " | ".join(t.text for t in self.ctl.out).lower()
        self.assertIn("cleared", said)
        self.assertNotIn("number two", said)
        self.assertNotIn("continue holding", said)
        self.assertIsNot(ac.phase, atc.Phase.HOLDING)

    def test_the_board_is_put_back_in_step_with_his_clearance(self):
        """Not just the words. Leaving him HOLDING while he holds the letdown
        is the state that produced the loop, so the phase has to move too or
        the next request deadlocks again."""
        ac = self._stuck()
        self.ctl._try_clear(requested_by="Sockeye")
        self.assertIs(ac.phase, atc.Phase.CLEARED)

    def test_asking_repeatedly_never_deadlocks(self):
        """He asked four times. Every one has to come back cleared."""
        self._stuck()
        for attempt in range(4):
            self.ctl.out.clear()
            self.ctl._try_clear(requested_by="Sockeye")
            with self.subTest(attempt=attempt + 1):
                said = " | ".join(t.text for t in self.ctl.out).lower()
                self.assertNotIn("number two", said)

    def test_A_REAL_SECOND_AIRCRAFT_IS_STILL_NUMBER_TWO(self):
        """The half that must not regress. This is separation: somebody else in
        the letdown means you wait, and the fix must not have bought the
        deadlock off by letting everyone through."""
        self.ctl.get("Sockeye")
        self.ctl.note_radar_contact("Sockeye")
        self.ctl.get("Hoover")
        self.ctl.note_radar_contact("Hoover")
        self.ctl._set_letdown(None, "Sockeye")
        self.ctl.out.clear()
        self.ctl._try_clear(requested_by="Hoover")
        said = " | ".join(t.text for t in self.ctl.out).lower()
        self.assertIn("number two", said)

    def test_the_letdown_is_not_handed_to_somebody_else(self):
        """Re-affirming his clearance must not release the slot -- that would
        let a second aircraft into the letdown behind him, which is the exact
        thing the block exists to prevent."""
        self._stuck()
        self.ctl._try_clear(requested_by="Sockeye")
        self.assertEqual(self.ctl._in_letdown(), "Sockeye")


class NoTwoAircraftAtOneAltitude(unittest.TestCase):
    """The promise the deterministic half exists to keep, asserted directly.

    Every stack test in this file checks a NUMBER -- B is at five thousand, C is
    at six -- and each of those is a consequence of the invariant rather than the
    invariant itself. So when the engine started handing the aircraft cleared for
    the approach's level to the next arrival, the numbers still matched what had
    been written down and nothing said two aeroplanes were at one altitude.

    It took `tools/stack_rehearsal.py` -- three synthetic arrivals over real SRS,
    checking the board rather than a number -- to see it, on its first run, after
    sixteen turns of two-or-more holding in this project's entire recorded life.
    That is the argument for asserting the rule and not only its arithmetic.

    On a radar approach the level IS the separation: `ApproachProfile.stack_ft`
    says so about itself -- no beacon, no pattern, nothing to hold over, "the
    levels still provide the separation". Sharing one is not a tighter margin.
    See #108.
    """

    def _levels(self, ctl):
        """Everybody who is somewhere, and where. Landed aircraft are gone."""
        return [(a.callsign, a.assigned_ft) for a in ctl.aircraft.values()
                if a.assigned_ft is not None and a.phase is not atc.Phase.LANDED]

    def _assert_all_apart(self, ctl, what):
        got = self._levels(ctl)
        levels = [ft for _cs, ft in got]
        dupes = {ft for ft in levels if levels.count(ft) > 1}
        self.assertFalse(
            dupes, f"{what}: "
                   + "; ".join(f"{cs} at {ft:,}" for cs, ft in sorted(got))
                   + f"  -- {', '.join(f'{d:,}' for d in sorted(dupes))} shared")

    def test_three_arriving_together(self):
        """The case that found it. One is cleared, two hold, nobody shares."""
        ctl = atc.Controller(profile())
        for cs in ("Alpha 1", "Bravo 1", "Charlie 1"):
            ctl.report_beacon(cs, 9000)
        self._assert_all_apart(ctl, "three arrivals")

    def test_a_full_stack(self):
        ctl = atc.Controller(profile())
        for i in range(5):
            ctl.report_beacon(f"Ship {i} 1", 9000)
        self._assert_all_apart(ctl, "a full stack")

    def test_through_a_landing_and_the_step_down(self):
        """The step-down is the other direction the collision can come from:
        compressing the holders onto the bottom of the stack walks the lowest
        one straight into the aircraft who was just cleared from it."""
        ctl = atc.Controller(profile())
        for cs in ("Alpha 1", "Bravo 1", "Charlie 1", "Delta 1"):
            ctl.report_beacon(cs, 9000)
        texts(ctl)
        ctl.report_landed("Alpha 1")
        self._assert_all_apart(ctl, "after the bottom one lands")
        ctl.report_landed("Bravo 1")
        self._assert_all_apart(ctl, "and after the next one")

    def test_a_missed_approach_does_not_land_on_a_holder(self):
        ctl = atc.Controller(profile())
        for cs in ("Alpha 1", "Bravo 1", "Charlie 1"):
            ctl.report_beacon(cs, 9000)
        texts(ctl)
        ctl.report_missed("Alpha 1")
        self._assert_all_apart(ctl, "after a missed approach")
