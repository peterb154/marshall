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
        for cs in ("A 1", "B 1", "C 1"):
            self.ctl.report_beacon(cs, 9000)
        # First is cleared into the letdown; the rest stack from the base up.
        self.assertEqual(self.ctl.get("B 1").assigned_ft, 4000)
        self.assertEqual(self.ctl.get("C 1").assigned_ft, 5000)

    def test_stack_grows_past_four(self):
        # The stack used to be a fixed four-element list. A formation break-up
        # alone can want four levels, so it has to keep going.
        for i in range(6):
            self.ctl.report_beacon(f"Ship {i}", 9000)
        levels = sorted(a.assigned_ft for a in self.ctl.aircraft.values()
                        if a.phase is atc.Phase.HOLDING)
        self.assertEqual(levels, [4000, 5000, 6000, 7000, 8000])

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
        self.ctl.report_beacon("Three 1", 6000)
        texts(self.ctl)
        self.assertEqual(self.ctl.get("Three 1").assigned_ft, 5000)
        self.ctl.report_landed("Lead 1")
        # Two is cleared out of 4000; Three drops into the bottom slot.
        self.assertEqual(self.ctl.get("Three 1").assigned_ft, 4000)


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
        ctl.report_beacon("Lead 1", 4000)       # cleared
        ctl.report_beacon("Two 1", 5000)        # holding at 4000
        texts(ctl)
        ctl.report_beacon("Two 1", 7000)        # reports a level he was not given
        self.assertTrue(said(ctl, "negative", "assigned four thousand"))

    def test_a_matching_level_is_acknowledged(self):
        ctl = atc.Controller(profile())
        ctl.report_beacon("Lead 1", 4000)
        ctl.report_beacon("Two 1", 5000)
        texts(ctl)
        ctl.report_beacon("Two 1", 4000)
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
        self.assertEqual(atc.spell_freq(132.0), "one three two")
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
        self.assertIn("final approach course", self.asr._report_phrase())

    def test_nothing_the_vectored_controller_says_names_the_beacon(self):
        # The belt-and-braces check: drive a whole arrival and read every
        # transmission. A single leftover literal is a fix named to an aircraft
        # that cannot find it.
        c = atc.Controller(R.BATUMI_ASR)
        said = []
        c.say = lambda cs, text: said.append(text)
        c.check_in("Pony 1-1")
        c.request_approach("Pony 1-1")
        c.report_conditions("Pony 1-1", visual=True)
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
        self.c.say = lambda cs, text: self.said.append(text)

    def test_an_aircraft_on_final_is_not_put_in_the_holding_stack(self):
        self.assertTrue(self.c.seen_on_final("Pony 1-1", size=3))
        ac = self.c.get("Pony 1-1")
        self.assertEqual(ac.phase, atc.Phase.CLEARED)
        self.assertIsNone(ac.assigned_ft, "he was given a holding level anyway")

    def test_he_owns_the_letdown_rather_than_queueing_for_it(self):
        self.c.seen_on_final("Pony 1-1")
        self.assertEqual(self.c._letdown, "Pony 1-1")

    def test_checking_in_afterwards_does_not_stack_him(self):
        self.c.seen_on_final("Pony 1-1")
        self.c.request_approach("Pony 1-1")
        for line in self.said:
            self.assertNotIn("hold", line.lower(), line)

    def test_seeding_twice_is_harmless(self):
        self.assertTrue(self.c.seen_on_final("Pony 1-1"))
        self.assertFalse(self.c.seen_on_final("Pony 1-1"))

    def test_a_second_aircraft_still_gets_separated(self):
        # Seeding must not switch the engine off: the one behind still holds.
        self.c.seen_on_final("Pony 1-1")
        self.c.check_in("Viper 2-1")
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
        from marshall.atc.agent_atc import may_be_vectored
        self.may = may_be_vectored
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
        from marshall.atc.agent_atc import may_be_vectored
        self.ctl.request_visual("Pony 1-1")
        self.assertFalse(may_be_vectored(self.ctl, "Pony 1-1"))

    def test_a_formation_is_broken_up_first(self):
        self.ctl.check_in("Pony 1-1", 2)
        self.ctl.out.clear()
        self.ctl.request_visual("Pony 1-1")
        self.assertTrue(any("break up" in tx.text.lower() for tx in self.ctl.out))


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
        self.A._heard_on.clear()
        self.ctl = atc.Controller(profile())
        self.ctl.report_beacon("Pony 1-1", 4000)     # known, cleared, being worked
        texts(self.ctl)
        self.approach_hz = 124.0e6
        self.center_hz = 139.0e6

    def test_not_worked_before_he_has_said_a_word_here(self):
        self.assertFalse(
            self.A.may_be_vectored(self.ctl, "Pony 1-1", freq_hz=self.approach_hz))

    def test_not_worked_while_he_is_still_on_the_previous_frequency(self):
        """The handoff has been issued; he has not switched yet."""
        self.A._heard_on["Pony 1-1"] = self.center_hz
        self.assertFalse(
            self.A.may_be_vectored(self.ctl, "Pony 1-1", freq_hz=self.approach_hz))

    def test_worked_as_soon_as_he_checks_in(self):
        self.A._heard_on["Pony 1-1"] = self.approach_hz
        self.assertTrue(
            self.A.may_be_vectored(self.ctl, "Pony 1-1", freq_hz=self.approach_hz))

    def test_the_rule_is_off_when_no_frequency_is_given(self):
        """Callers that do not care about channels must not be broken by it."""
        self.assertTrue(self.A.may_be_vectored(self.ctl, "Pony 1-1"))
