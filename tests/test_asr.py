"""Surveillance-radar approach geometry.

This is the arithmetic that puts an aeroplane on a runway, so it is exactly the
part an LLM must never be doing. The sign conventions are the whole risk: get
cross-track backwards and the controller confidently turns a man away from the
field, in cloud, while sounding completely correct.
"""

import dataclasses
import math
import unittest

from marshall.atc import asr
from marshall.core import route as R


def profile(**over):
    base = dataclasses.replace(R.BATUMI_APPROACH, kind="asr")
    return dataclasses.replace(base, **over) if over else base


def right_of_course_nm(range_nm, radial, final_crs):
    """Independent check: build the position as a vector and measure how far it
    lies to the right of the inbound heading. Deliberately a different method
    from the one under test, so a shared mistake cannot pass both."""
    def vec(deg):
        return (math.sin(math.radians(deg)), math.cos(math.radians(deg)))
    inbound_radial = (final_crs + 180) % 360
    ce, cn = vec(inbound_radial)
    ae, an = vec(radial)
    de, dn = (ae - ce) * range_nm, (an - cn) * range_nm
    re, rn = vec((final_crs + 90) % 360)        # "right" of the inbound heading
    return de * re + dn * rn


class TestCrossTrack(unittest.TestCase):
    def test_on_the_centreline_is_zero(self):
        p = profile()
        pos = asr.Position(8, (p.final_crs + 180) % 360, 2000)
        self.assertAlmostEqual(asr.cross_track(pos, p.final_crs), 0, places=6)

    def test_agrees_with_an_independent_vector_calculation(self):
        p = profile()
        for rng in (2, 6, 12):
            for radial in (290, 296, 300, 304, 308, 314, 320):
                with self.subTest(rng=rng, radial=radial):
                    got = asr.cross_track(asr.Position(rng, radial, 2000),
                                          p.final_crs)
                    want = right_of_course_nm(rng, radial, p.final_crs)
                    self.assertAlmostEqual(got, want, places=6)

    def test_sign_is_right_of_course_positive(self):
        # Radial 296 sits clockwise-of-nothing: it is to the RIGHT of a 124
        # inbound. Hand-checked with vectors; this pins the convention.
        p = profile()
        self.assertGreater(asr.cross_track(asr.Position(6, 296, 2000), 124), 0)
        self.assertLess(asr.cross_track(asr.Position(6, 312, 2000), 124), 0)

    def test_error_grows_with_range_for_a_fixed_angle(self):
        p = profile()
        near = asr.cross_track(asr.Position(2, 310, 2000), p.final_crs)
        far = asr.cross_track(asr.Position(10, 310, 2000), p.final_crs)
        self.assertLess(abs(near), abs(far))


class TestInterceptHeading(unittest.TestCase):
    def test_on_course_flies_the_course(self):
        self.assertEqual(asr.intercept_heading(124, 0.0), 124)

    def test_right_of_course_turns_left(self):
        self.assertLess(asr.angle_diff(asr.intercept_heading(124, 1.0), 124), 0)

    def test_left_of_course_turns_right(self):
        self.assertGreater(asr.angle_diff(asr.intercept_heading(124, -1.0), 124), 0)

    def test_correction_is_capped(self):
        # A huge error must not produce a heading that loses the field.
        for xtk in (5, 20, -20):
            h = asr.intercept_heading(124, xtk)
            self.assertLessEqual(abs(asr.angle_diff(h, 124)), asr.MAX_INTERCEPT)

    def test_heading_wraps(self):
        self.assertEqual(asr.intercept_heading(5, -1.0), 17)
        self.assertEqual(asr.intercept_heading(355, -1.0), 7)


class TestGuide(unittest.TestCase):
    def setUp(self):
        self.p = profile()
        self.inbound = (self.p.final_crs + 180) % 360

    def at(self, nm, radial=None, alt=2000):
        return asr.guide(asr.Position(nm, radial if radial is not None
                                      else self.inbound, alt), self.p)

    def test_far_out_is_vectoring_at_platform(self):
        g = self.at(12)
        self.assertEqual(g.phase, "vector")
        self.assertEqual(g.altitude_ft, self.p.platform_ft)

    def test_inside_the_intercept_range_is_final_at_minimums(self):
        g = self.at(6)
        self.assertEqual(g.phase, "final")
        self.assertEqual(g.altitude_ft, self.p.mda_ft)

    def test_the_missed_approach_point(self):
        self.assertEqual(self.at(0.4).phase, "map")

    def test_the_far_side_of_the_field_is_vectored_back(self):
        # He has genuinely flown through: vector him round to the join point,
        # which means turning him AWAY from the field first.
        g = self.at(4, radial=self.p.final_crs)
        self.assertEqual(g.phase, "vector")
        inbound = (self.p.final_crs + 180) % 360
        # The heading must point back toward the inbound side, not at the field.
        self.assertLess(abs(asr.angle_diff(g.heading, inbound)), 90)

    def test_bearing_is_not_progress(self):
        # A man due north of the field is ninety-odd degrees off the inbound
        # radial and has passed NOTHING. Treating that as an overshoot flew a
        # real pilot straight at the field and then told him he had gone past.
        g = self.at(12, radial=14)
        self.assertEqual(g.phase, "vector")
        self.assertNotEqual(g.heading, self.p.final_crs)

    def test_on_the_centreline_outside_the_turn_on_continues_inbound(self):
        # It must not send him back OUT to the join point: he is already on the
        # course, he just is not down yet.
        inbound = (self.p.final_crs + 180) % 360
        g = self.at(self.p.final_intercept_nm + 2, radial=inbound)
        self.assertEqual(g.heading, self.p.final_crs)
        self.assertEqual(g.altitude_ft, self.p.platform_ft)

    def test_well_off_the_inbound_sector_is_still_vectoring(self):
        # Close in range but 60 degrees off: he has not intercepted yet.
        g = self.at(6, radial=(self.inbound + 60) % 360)
        self.assertEqual(g.phase, "vector")

    def test_deviation_wording(self):
        self.assertEqual(self.at(6).deviation, "on course")
        self.assertEqual(self.at(6, radial=296).deviation, "right of course")
        self.assertEqual(self.at(6, radial=312).deviation, "left of course")

    def test_a_small_error_is_still_on_course(self):
        # Chasing tenths of a mile would have the controller talking constantly.
        g = self.at(6, radial=self.inbound + 1)
        self.assertLess(abs(g.xtk_nm), 0.3)
        self.assertEqual(g.deviation, "on course")
        self.assertFalse(g.off_course)

    def test_a_closing_aircraft_is_steered_back_to_the_course(self):
        # The loop must converge: each correction reduces the error.
        p, xtk = self.p, 1.5
        radial = self.inbound
        pos = asr.Position(8, radial, 2000)
        first = asr.guide(pos, p)
        self.assertEqual(first.heading, p.final_crs)     # already on it
        off = asr.guide(asr.Position(8, self.inbound + 8, 2000), p)
        self.assertTrue(off.off_course)
        self.assertNotEqual(off.heading, p.final_crs)


class TestVectoredFlag(unittest.TestCase):
    def test_asr_is_vectored_and_ndb_is_not(self):
        # The two guidance modes are mutually exclusive: a homing adapter points
        # the nose at the beacon, so a vector heading destroys the only course
        # reference the pilot has.
        self.assertTrue(profile().vectored)
        self.assertFalse(R.BATUMI_APPROACH.vectored)


class TestSpokenRange(unittest.TestCase):
    def test_whole_miles_in_words(self):
        self.assertEqual(asr.spoken_range(6.0), "six")
        self.assertEqual(asr.spoken_range(5.6), "six")
        self.assertEqual(asr.spoken_range(10.0), "one zero")

    def test_no_digits_reach_polly(self):
        for nm in (1, 3.4, 7.8, 10):
            self.assertFalse(any(c.isdigit() for c in asr.spoken_range(nm)))

class TestStations(unittest.TestCase):
    """Who the controller is, and when he lets go."""

    def setUp(self):
        self.p = R.BATUMI_ASR

    def test_identity_by_frequency(self):
        # The bridge listens on every channel at once; the pilot must never be
        # able to hear that.
        self.assertEqual(self.p.station_on(119.0).name, "Georgia Center")
        self.assertEqual(self.p.station_on(120.0).name, "Batumi Approach")
        self.assertEqual(self.p.station_on(131.0).name, "Batumi Tower")

    def test_an_unmanned_frequency_has_nobody_on_it(self):
        # 124 is a leftover beacon, not a controller.
        self.assertIsNone(self.p.station_on(124.0))

    def test_center_keeps_him_while_he_is_far_out(self):
        self.assertIsNone(self.p.handoff_from(119.0, 40))

    def test_center_gives_him_to_approach_inside_the_boundary(self):
        nxt = self.p.handoff_from(119.0, self.p.approach_hands_over_nm - 2)
        self.assertEqual(nxt.role, "approach")

    def test_approach_gives_him_to_tower_on_final(self):
        nxt = self.p.handoff_from(120.0, self.p.final_intercept_nm - 2)
        self.assertEqual(nxt.role, "tower")

    def test_approach_keeps_him_before_final(self):
        self.assertIsNone(self.p.handoff_from(120.0, 25))

    def test_tower_hands_off_to_nobody(self):
        self.assertIsNone(self.p.handoff_from(131.0, 3))

    def test_an_unmanned_frequency_hands_off_to_nobody(self):
        self.assertIsNone(self.p.handoff_from(124.0, 10))

if __name__ == "__main__":
    unittest.main()
