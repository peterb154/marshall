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
        # Both sides of north: a correction that runs off either end of the
        # compass has to come back as a heading, not as 365 or -8.
        turn = math.degrees(math.atan2(1.0, asr.LOOKAHEAD_NM))
        self.assertEqual(asr.intercept_heading(5, -1.0), round((5 + turn) % 360))
        self.assertEqual(asr.intercept_heading(355, -1.0), round((355 + turn) % 360))
        for crs in (0, 1, 359, 180):
            for xtk in (-3.0, -0.2, 0.0, 0.2, 3.0):
                h = asr.intercept_heading(crs, xtk)
                self.assertTrue(0 <= h < 360, (crs, xtk, h))

    def test_the_cap_allows_a_perpendicular_turn(self):
        # It used to cap at thirty degrees, which cannot close a large offset --
        # so a separate case flew the aircraft PARALLEL to the course to buy
        # room, and parallel never reduces an offset. A pilot seventeen miles
        # off was sent out to sea at a constant seventeen miles off.
        self.assertGreaterEqual(asr.MAX_INTERCEPT, 90)


class TestGuide(unittest.TestCase):
    def setUp(self):
        self.p = profile()
        self.inbound = (self.p.final_crs + 180) % 360

    def at(self, nm, radial=None, alt=2000, hdg=None):
        # Default to flying the approach course: an aeroplane being talked down
        # is pointing down the centreline, and "established" now checks heading
        # as well as position -- a go-around tracking OUTBOUND used to be called
        # established and told to descend to minimums.
        return asr.guide(
            asr.Position(nm, radial if radial is not None else self.inbound,
                         alt, self.p.final_crs if hdg is None else hdg), self.p)

    VECTORING = ("vector",)

    @staticmethod
    def step(nm, radial, heading, dist):
        """Move an aircraft `dist` miles on `heading`; returns (range, radial)."""
        e = nm * math.sin(math.radians(radial)) + dist * math.sin(math.radians(heading))
        n = nm * math.cos(math.radians(radial)) + dist * math.cos(math.radians(heading))
        return math.hypot(e, n), math.degrees(math.atan2(e, n)) % 360

    def test_far_out_is_vectoring_at_platform(self):
        g = self.at(12)
        self.assertEqual(g.phase, "vector")
        self.assertEqual(g.altitude_ft, self.p.platform_ft)

    def test_inside_the_intercept_range_is_final_on_the_step_down(self):
        # Not straight to minimums: "descend and maintain three hundred" at
        # eight miles is a seventeen-hundred-foot drop as one instruction, and a
        # pilot flying it arrives low and level miles out.
        g = self.at(6)
        self.assertEqual(g.phase, "final")
        self.assertGreater(g.altitude_ft, self.p.mda_ft)
        self.assertLessEqual(g.altitude_ft, self.p.platform_ft)

    def test_the_step_down_descends_as_he_closes(self):
        alts = [self.at(nm).altitude_ft for nm in (6, 4, 2, 1)]
        self.assertEqual(alts, sorted(alts, reverse=True))
        self.assertGreaterEqual(alts[-1], self.p.mda_ft)

    def test_never_below_minimums(self):
        for nm in (2, 1, 0.7):
            self.assertGreaterEqual(self.at(nm).altitude_ft, self.p.mda_ft)

    def test_on_course_tightens_as_he_closes(self):
        # A quarter mile off is fine at eight miles and is a missed runway at
        # one. Judged as a fixed distance it was called "lined up" on short
        # final while the pilot was a quarter mile south of the threshold.
        self.assertGreater(asr.on_course_tolerance(8),
                           asr.on_course_tolerance(1))
        g = self.at(1.0, radial=(self.inbound + 14) % 360)
        self.assertTrue(g.off_course)

    def test_the_missed_approach_point(self):
        self.assertEqual(self.at(0.4).phase, "map")

    def test_off_the_departure_end_gets_the_published_missed_approach(self):
        # Lined up, low, past the threshold: he has just flown the approach and
        # not landed. The plate answers this and we fly the plate -- 330,
        # climbing three thousand, which tracks out over the water. Vectoring
        # him instead floors his altitude at the minimum vectoring altitude for
        # the ground below, which off this departure end is thirteen thousand
        # feet of Caucasus. It was flown live: an aircraft at six hundred feet
        # was sent to climb thirteen thousand into the mountains, and did.
        g = self.at(4, radial=self.p.final_crs)
        self.assertEqual(g.phase, "missed")
        self.assertEqual(g.heading, self.p.missed_hdg)
        self.assertEqual(g.altitude_ft, self.p.missed_climb_ft)
        self.assertFalse(g.established)

    def test_below_the_turn_altitude_he_climbs_straight_ahead_first(self):
        # "At 800 turn left 330" -- so at 500 he is still going straight.
        g = asr.guide(asr.Position(1.0, self.p.final_crs, 500,
                                   self.p.final_crs), self.p)
        self.assertEqual(g.phase, "missed")
        self.assertEqual(g.heading, self.p.final_crs)

    def test_the_far_side_of_the_field_is_vectored_back(self):
        # Past the field but NOT off the departure end -- an arrival from the
        # north-east that has flown nothing. It gets an ordinary vector and the
        # mountain minimum, not a missed approach it never started.
        g = self.at(8, radial=45, hdg=45)
        self.assertIn(g.phase, self.VECTORING)
        self.assertNotEqual(g.phase, "missed")
        self.assertFalse(g.established)

    def test_bearing_is_not_progress(self):
        # A man due north of the field is ninety-odd degrees off the inbound
        # radial and has passed NOTHING. Treating that as an overshoot flew a
        # real pilot straight at the field and then told him he had gone past.
        g = self.at(12, radial=14)
        self.assertIn(g.phase, self.VECTORING)
        self.assertFalse(g.established)

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
        self.assertIn(g.phase, self.VECTORING)

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
        self.assertEqual(self.at(8).heading, self.p.final_crs)   # already on it
        off = self.at(8, radial=self.inbound + 8)
        self.assertTrue(off.off_course)
        self.assertNotEqual(off.heading, self.p.final_crs)

    def test_tracking_outbound_is_not_established(self):
        # A go-around on the centreline heading AWAY was called established and
        # told to descend to minimums. Position is not enough.
        g = self.at(4, hdg=(self.p.final_crs + 180) % 360)
        self.assertFalse(g.established)

    def test_a_large_offset_is_never_flown_away_from_the_course(self):
        # The heading must reduce the cross-track, at every offset. There is no
        # case where turning away from the centreline is the answer.
        for radial in (14, 45, 90, 180, 200, 271):
            for rng in (8, 14, 20):
                with self.subTest(radial=radial, rng=rng):
                    a = self.at(rng, radial=radial, hdg=radial)
                    if a.established:
                        continue
                    moved = self.step(rng, radial, a.heading, 1.0)
                    b = asr.guide(asr.Position(*moved, 2000, a.heading), self.p)
                    self.assertLess(abs(b.xtk_nm), abs(a.xtk_nm) + 0.01,
                                    f"heading {a.heading} did not close "
                                    f"{a.xtk_nm:+.1f} nm of cross-track")

    def test_room_to_intercept_cuts_across_at_the_intercept_angle(self):
        g = self.at(10.9, radial=310, hdg=33)
        self.assertIn(g.phase, self.VECTORING)
        self.assertLessEqual(abs(asr.angle_diff(g.heading, self.p.final_crs)),
                             asr.INTERCEPT_ANGLE + 1)


class TestConvergence(unittest.TestCase):
    """Fly the guidance and check it actually gets there.

    The unit tests all passed while the vectoring was flying a pilot out to sea,
    because each one checked a single look in isolation and the failure was in
    what the looks did in SEQUENCE. Simulating the whole approach is the only
    thing that catches a controller who is individually reasonable and
    collectively useless.
    """

    def setUp(self):
        self.p = R.BATUMI_ASR

    def flies_to_the_field(self, nm, radial, heading, limit=80):
        for _ in range(limit):
            g = asr.guide(asr.Position(nm, radial, 2000, heading), self.p)
            if g.phase == "map":
                return True
            heading = g.heading
            d = 240 / 1.15078 / 240          # miles per 15 s at pattern speed
            e = nm * math.sin(math.radians(radial)) + d * math.sin(math.radians(heading))
            n = nm * math.cos(math.radians(radial)) + d * math.cos(math.radians(heading))
            nm, radial = math.hypot(e, n), math.degrees(math.atan2(e, n)) % 360
        return False

    def test_arrives_from_every_direction(self):
        for radial in range(0, 360, 30):
            for rng in (8, 15, 22):
                with self.subTest(radial=radial, rng=rng):
                    self.assertTrue(
                        self.flies_to_the_field(rng, radial, radial),
                        f"never reached the field from {rng} nm on the "
                        f"{radial:03d} radial")

    def test_arrives_from_where_the_pilot_abandoned_it(self):
        # 18 nm north, 17.5 nm off course: the run that was flown out to sea.
        self.assertTrue(self.flies_to_the_field(18.1, 19, 246))

    def test_does_not_orbit_the_join_point(self):
        # Arriving on the centreline pointing across it must turn him ONTO the
        # course; without that he can never become established, falls through to
        # the pursuit, aims at the point he is sitting on, and circles it.
        self.assertTrue(self.flies_to_the_field(10, 304, 55))


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

    # Read the frequencies off the stations rather than hardcoding them: these
    # tests broke the moment the numbers moved, which is noise, not signal.
    def freq(self, role):
        return self.p.station_for(role).freq_mhz

    def test_identity_by_frequency(self):
        # The bridge listens on every channel at once; the pilot must never be
        # able to hear that.
        for role in ("center", "approach", "tower"):
            s = self.p.station_for(role)
            self.assertEqual(self.p.station_on(s.freq_mhz).name, s.name)

    def test_an_unmanned_frequency_has_nobody_on_it(self):
        unused = 118.25
        self.assertNotIn(unused, [s.freq_mhz for s in self.p.stations])
        self.assertIsNone(self.p.station_on(unused))

    def test_every_controller_is_tunable_by_a_period_set(self):
        # These are the field's real published frequencies, not the airframe's
        # stock buttons, so every one of them has to be WRITTEN into the
        # mission's presets -- a period set has four buttons and no way to dial
        # a frequency in the air. A preset write that silently fails leaves the
        # aircraft unable to talk to anybody, which is how the Jugs spent a
        # sortie mute. The band check is what keeps an untunable number out.
        for s in self.p.stations:
            self.assertGreaterEqual(s.freq_mhz, 100.0, s.name)   # SCR-522 VHF AM
            self.assertLessEqual(s.freq_mhz, 156.0, s.name)
            self.assertEqual(s.freq_mhz, round(s.freq_mhz, 3), s.name)

    def test_the_mission_writes_a_preset_for_every_controller(self):
        from marshall.mission import build as mb
        presets = {mhz for _, mhz in mb.channels_for(self.p)}
        for s in self.p.stations:
            self.assertIn(s.freq_mhz, presets, f"{s.name} has no radio button")

    def test_center_keeps_him_while_he_is_far_out(self):
        self.assertIsNone(self.p.handoff_from(self.freq("center"), 40))

    def test_center_gives_him_to_approach_inside_the_boundary(self):
        nxt = self.p.handoff_from(self.freq("center"),
                                  self.p.approach_hands_over_nm - 2)
        self.assertEqual(nxt.role, "approach")

    def test_approach_gives_him_to_tower_on_final(self):
        nxt = self.p.handoff_from(self.freq("approach"),
                                  self.p.final_intercept_nm - 2)
        self.assertEqual(nxt.role, "tower")

    def test_approach_keeps_him_before_final(self):
        self.assertIsNone(self.p.handoff_from(self.freq("approach"), 25))

    def test_tower_hands_off_to_nobody(self):
        self.assertIsNone(self.p.handoff_from(self.freq("tower"), 3))

    def test_an_unmanned_frequency_hands_off_to_nobody(self):
        self.assertIsNone(self.p.handoff_from(118.25, 10))

class TestTerrain(unittest.TestCase):
    """Vectoring on geometry alone will fly an aircraft into a mountain.

    Batumi has 1,000 ft of sea to the north-west and between seven and eleven
    thousand feet of Caucasus everywhere else. The whole beacon procedure lived
    north-west for that reason; the radar vectoring did not know terrain existed
    and was caught in the air turning a pilot over the ranges at two thousand.
    """

    def setUp(self):
        self.p = R.BATUMI_ASR

    def test_published_sectors_match_the_plate(self):
        # AD 2.UGSB-IAC-12-ILSy: 7,000 from 217 clockwise through north to 038,
        # 13,600 for the rest. An offset lookup put 330 -- the sea, the one
        # bearing it is safe to be low on -- into the mountain bucket.
        self.assertEqual(R.msa_for(330), 7000)
        self.assertEqual(R.msa_for(20), 7000)
        self.assertEqual(R.msa_for(120), 13600)
        self.assertEqual(R.msa_for(230), 7000)

    def test_vectoring_minima_are_below_the_published_msa(self):
        # The published MSA is the pilot's lost-comms figure and is far too
        # blunt to vector to: over the sea it is still 7,000, so honouring it
        # would hold him four thousand feet above platform to the threshold.
        for bearing in (300, 330, 350):
            with self.subTest(bearing=bearing):
                self.assertLess(R.mva_for(bearing), R.msa_for(bearing))
        self.assertEqual(R.mva_for(330), 2000)   # open water

    def test_vectoring_over_terrain_is_above_the_msa(self):
        for radial in (20, 120, 230):
            with self.subTest(radial=radial):
                g = asr.guide(asr.Position(15, radial, 5000, 200), self.p)
                self.assertGreaterEqual(g.altitude_ft, R.mva_for(radial))

    def test_over_the_sea_he_is_not_held_high_by_terrain(self):
        # Nothing under him but water, so the only thing holding him up is the
        # descent profile, not the MSA.
        g = asr.guide(asr.Position(15, 330, 5000, 200), self.p)
        self.assertLess(g.altitude_ft, R.mva_for(20))

    def test_he_reaches_platform_at_the_turn_on_and_not_before(self):
        # "No sense descending so early": platform at twenty miles means flying
        # twelve miles low and slow for nothing.
        far = asr.guide(asr.Position(20, 304, 5500, 124), self.p)
        at_turn_on = asr.guide(
            asr.Position(self.p.final_intercept_nm, 304, 2500, 124), self.p)
        self.assertGreater(far.altitude_ft, self.p.platform_ft)
        self.assertEqual(at_turn_on.altitude_ft, self.p.platform_ft)

    def test_the_descent_is_monotonic(self):
        alt, last = 5500, None
        for nm in (20, 16, 12, 10, 8, 6, 4, 2):
            g = asr.guide(asr.Position(nm, 304, alt, 124), self.p)
            if last is not None:
                self.assertLessEqual(g.altitude_ft, last)
            last = alt = g.altitude_ft

    def test_assigned_altitudes_are_round_numbers(self):
        for nm in (20, 16, 12, 10, 9):
            g = asr.guide(asr.Position(nm, 304, 5500, 124), self.p)
            self.assertEqual(g.altitude_ft % 100, 0, g.altitude_ft)

    def test_he_is_never_told_to_climb_back_onto_the_profile(self):
        # Already low over the water: leave him there rather than bouncing him.
        g = asr.guide(asr.Position(16, 304, 2000, 124), self.p)
        self.assertLessEqual(g.altitude_ft, 2000)

    def test_the_final_is_flown_over_water(self):
        # The approach course itself lies north-west, which is why the descent
        # to minimums is safe at all.
        self.assertEqual(R.mva_for((self.p.final_crs + 180) % 360), 2000)

    def test_a_profile_with_no_terrain_data_still_works(self):
        bare = dataclasses.replace(self.p, msa_sectors=[], mva_sectors=[])
        self.assertEqual(bare.min_safe_ft(20), bare.platform_ft)

    def test_no_survey_falls_back_to_the_published_msa_not_to_batumi(self):
        # A new field must not inherit this one's mountains. With no vectoring
        # survey the published figure is the only defensible floor; borrowing
        # the module default would vector an aircraft over flat ground at
        # thirteen thousand feet for terrain a hundred miles away.
        flat = dataclasses.replace(self.p, mva_sectors=[],
                                   msa_sectors=[(0.0, 360.0, 3000)])
        self.assertEqual(flat.min_safe_ft(120), 3000)
        self.assertEqual(flat.min_safe_ft(330), 3000)

if __name__ == "__main__":
    unittest.main()
