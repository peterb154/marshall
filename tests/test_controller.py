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

    def test_check_in_hands_him_over_to_the_beacon_frequency(self):
        self.ctl.check_in("Pony 1-1")
        self.assertTrue(said(self.ctl, "contact", "one three two"))

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
