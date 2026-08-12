"""The fixture's own geometry, because an arrival flown outbound looks fine.

`tools/ghost_flight.py` marched strictly outward until tonight: `while nm <
args.to`, along the departure runway's heading, with the aeroplane's heading
equal to its radial. Every rehearsal in the repo therefore departed, and the
four rungs an ARRIVAL climbs had never been flown by anything -- which is where
both of the last two real sorties went wrong.

WHAT THIS GUARDS IS THE HARNESS, NOT THE LADDER. `test_the_ladder_has_a_direction`
already holds the rules; this holds the fixture that feeds them, because the way
to get an arrival wrong is silent:

    range decreasing, heading unchanged  ->  an outbound flight with a smaller
                                             number on it

Every distance in `handoff.py` would be satisfied and `inbound` would be False
in all of them, so nothing would fire and the log would read like a controller
who had gone quiet. So the assertion is not "the numbers shrink", it is that the
row this tool paints reads as INBOUND to the same function the bridge uses --
`_handoff_state`, over `range_bearing_true`, the way a radar fix is actually
built.

No sim, no director, no radio: a lat/lon is computed, converted back to a range
and a radial, and handed to the conditions.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import ghost_flight as G

from marshall.atc import asr
from marshall.atc import handoff as H
from marshall.core import geo as _geo
from marshall.core import route as R

BATUMI = (41.6103, 41.5997)          # the field, from the theatre file


class Field:
    """Just the two attributes the fixture reads off a theatre's field."""
    def __init__(self, lat, lon, runway):
        self.lat, self.lon, self.runway = lat, lon, runway


class TheGhostArrivesFacingTheField(unittest.TestCase):

    def setUp(self):
        self.field = Field(*BATUMI, runway=124)
        self.profile = R.BATUMI_ILS

    def flown_to(self, nm: float):
        """The state the bridge would build from the row the tool paints."""
        radial, hdg = G.arrival_geometry(self.field, self.profile)
        lat, lon = G._step(self.field.lat, self.field.lon, radial, nm)
        got_nm, got_radial = _geo.range_bearing_true(BATUMI, lat, lon)
        pos = asr.Position(range_nm=got_nm, radial_deg=got_radial,
                           alt_ft=int(G.arrival_alt(nm)), heading_deg=hdg)
        inbound = abs(asr.angle_diff((got_radial + 180) % 360, hdg)) < 90
        return H.State(on_ground=False, range_nm=pos.range_nm,
                       inbound=inbound), pos

    def test_the_heading_is_the_reciprocal_of_the_radial(self):
        """The one thing that makes him an arrival rather than a departure."""
        radial, hdg = G.arrival_geometry(self.field, self.profile)
        self.assertAlmostEqual((radial + 180) % 360, hdg, places=6)

    def test_he_flies_the_published_final_approach_course_in_true(self):
        """Magnetic here would be six degrees off his own centreline, and every
        range in the log would still look right."""
        _, hdg = G.arrival_geometry(self.field, self.profile)
        self.assertAlmostEqual(hdg, self.profile.final_crs_true, places=6)

    def test_every_range_on_the_way_in_reads_as_inbound(self):
        for nm in (32.0, 27.0, 25.0, 11.0, 5.0, 4.0, 2.0):
            with self.subTest(nm=nm):
                st, _ = self.flown_to(nm)
                self.assertTrue(st.inbound, f"{nm} nm did not read as inbound")

    def test_the_range_that_comes_back_is_the_range_asked_for(self):
        """A flat-earth step and a geodesic measurement, reconciled -- because a
        fixture that thinks it is at 25 nm while radar reads 26 crosses the
        Center threshold a mile late and nobody would ever know."""
        for nm in (32.0, 25.0, 5.0):
            with self.subTest(nm=nm):
                st, _ = self.flown_to(nm)
                self.assertAlmostEqual(st.range_nm, nm, delta=0.2)

    def test_center_gives_him_to_approach_inside_the_terminal_area(self):
        st, _ = self.flown_to(24.0)
        self.assertTrue(H.CONDITIONS["inbound_within"](st, H.CENTER_NM,
                                                       self.profile, None))

    def test_approach_gives_him_to_tower_inside_five(self):
        st, _ = self.flown_to(4.0)
        self.assertTrue(H.CONDITIONS["inbound_within"](st, H.ARRIVAL_NM,
                                                       self.profile, None))

    def test_and_nothing_reads_him_as_outbound_at_any_range(self):
        """The failure this whole file exists for: an arrival that satisfies
        `outbound_beyond` is a departure, and would be handed to Center at
        twenty-five miles on his way IN."""
        for nm in (32.0, 27.0, 25.0, 6.0):
            with self.subTest(nm=nm):
                st, _ = self.flown_to(nm)
                self.assertFalse(
                    H.CONDITIONS["outbound_beyond"](st, H.CENTER_NM,
                                                    self.profile, None))
                self.assertFalse(
                    H.CONDITIONS["outbound_beyond"](st, H.DEPARTURE_NM,
                                                    self.profile, None))


class TheDirectionIsDeclaredOrImplied(unittest.TestCase):
    """`--to 2 --from-nm 32` is an arrival in any language."""

    def test_the_flag_says_so(self):
        self.assertTrue(G.flying_inbound(True, None, None))

    def test_and_so_do_two_ranges_that_shrink(self):
        self.assertTrue(G.flying_inbound(False, 32.0, 2.0))

    def test_the_old_defaults_are_still_a_departure(self):
        self.assertFalse(G.flying_inbound(False, 3.0, 32.0))

    def test_and_ranges_nobody_gave_decide_nothing(self):
        self.assertFalse(G.flying_inbound(False, None, None))


class TheJudgingReadsTheRecorder(unittest.TestCase):
    """The verdicts are predicates over `flight-*.jsonl`, so they are testable
    without flying at all -- the same bargain `ladder_rehearsal.py` makes."""

    def test_a_handoff_back_to_center_fails_the_inbound_check(self):
        ok, why = G.kept_inbound(
            [{"kind": "atc/handoff", "t": 10.0, "to": "center",
              "text": "Talon, contact Georgia Center one three nine."}], 0.0)
        self.assertIs(ok, False)
        self.assertIn("Center", why)

    def test_tower_giving_him_back_fails_even_though_the_handoff_fired(self):
        ok, why = G.kept_inbound(
            [{"kind": "atc/handoff", "t": 10.0, "to": "tower", "text": "..."},
             {"kind": "atc/handoff", "t": 20.0, "to": "approach",
              "text": "Talon, contact Batumi Approach one two four."}], 0.0)
        self.assertTrue(ok)          # nobody went back to Center...
        line = G.Timeline()
        line.at(10.0, 5.0)
        line.at(20.0, 2.0)
        ok, why = G.handed_to_tower(
            [{"kind": "atc/handoff", "t": 10.0, "to": "tower", "text": "..."},
             {"kind": "atc/handoff", "t": 20.0, "to": "approach",
              "text": "Talon, contact Batumi Approach one two four."}], line)
        self.assertIs(ok, False)     # ...but Tower gave him back, which is #138
        self.assertIn("back to", why)

    def test_nothing_decided_is_not_a_pass(self):
        """`None` is NOT EXERCISED, and a run that provoked no decision must
        not be reported as one that survived it."""
        self.assertIsNone(G.kept_inbound([], 0.0)[0])
        self.assertIsNone(G.handed_to_tower([], G.Timeline())[0])
        self.assertIsNone(G.refused_the_approach([], 139.0)[0])

    def test_the_read_back_loop_is_counted_not_merely_noticed(self):
        ok, why = G.a_readback_loop(
            [{"kind": "atc/pilot", "text": "Talon, negative -- say again one "
                                           "zero thousand."}] * 8)
        self.assertIs(ok, False)
        self.assertIn("8", why)

    def test_and_an_arrival_with_none_of_them_passes(self):
        self.assertTrue(G.a_readback_loop(
            [{"kind": "atc/pilot", "text": "Talon, roger."}])[0])

    def test_a_refusal_counts_when_the_agent_puts_it_in_his_own_words(self):
        """Verbatim from the run of 12 August, and the first version of this
        predicate scored it NOT EXERCISED. The engine's phrase and the
        controller's are not the same sentence and must not have to be."""
        got = G.refused_the_approach([
            {"kind": "pilot", "freq_mhz": 139.0,
             "text": "Georgia Center, Dagger16, request the ILS."},
            {"kind": "controller", "text": "Dagger one six, the approach "
                                           "clearance is Approach's, contact "
                                           "Batumi Approach one two four "
                                           "decimal four two five."},
            {"kind": "atc/pilot", "freq_mhz": 139.0,
             "text": "Dagger one six, that clearance belongs to Batumi "
                     "Approach, contact them one two four decimal four two "
                     "five."}], 139.0)
        self.assertTrue(got[0])

    def test_but_a_refusal_nobody_heard_is_a_failure(self):
        """The exact shape this fix replaced: a controller who silently does
        nothing is indistinguishable from one who agreed."""
        ok, why = G.refused_the_approach([
            {"kind": "pilot", "freq_mhz": 139.0, "text": "request the ILS."},
            {"kind": "controller", "text": "the approach clearance is "
                                           "Approach's."},
            {"kind": "atc/pilot", "freq_mhz": 139.0, "text": "Dagger, roger."},
        ], 139.0)
        self.assertIs(ok, False)
        self.assertIn("did not carry it", why)

    def test_and_a_center_that_clears_him_anyway_fails(self):
        ok, why = G.refused_the_approach([
            {"kind": "pilot", "freq_mhz": 139.0, "text": "request the ILS."},
            {"kind": "atc/pilot", "freq_mhz": 139.0,
             "text": "Sockeye, cleared I-L-S approach runway one three."},
        ], 139.0)
        self.assertIs(ok, False)
        self.assertIn("issued a clearance", why)


if __name__ == "__main__":
    unittest.main()
