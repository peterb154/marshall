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
from marshall.atc import geometry as G
from marshall.atc import handoff as H
from marshall.core import route as R
from tests import theatre as T


def profile(**over):
    """A SURVEILLANCE APPROACH, on whichever map is loaded.

    `profile()` stood here at module scope, so the geometry that puts an
    aeroplane on a runway was only ever checked against one runway, at one
    field, at sea level, on one bearing. It is built off `T.letdown()` now --
    the same object on the Caucasus, so no number below moves -- with `kind`
    forced to "asr" exactly as before, because what this file is about is a
    controller who navigates rather than a particular aerodrome.
    """
    base = dataclasses.replace(T.letdown(), kind="asr")
    return dataclasses.replace(base, **over) if over else base


def vectored():
    """The map's radar arrival, where these tests want the bridge's procedure
    rather than a constructed one."""
    return T.the_arrival()


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
        self.inbound = (self.p.final_crs_true + 180) % 360

    def at(self, nm, radial=None, alt=2000, hdg=None):
        # Default to flying the approach course: an aeroplane being talked down
        # is pointing down the centreline, and "established" now checks heading
        # as well as position -- a go-around tracking OUTBOUND used to be called
        # established and told to descend to minimums.
        return asr.guide(
            asr.Position(nm, radial if radial is not None else self.inbound,
                         alt, self.p.final_crs_true if hdg is None else hdg), self.p)

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
        g = self.at(4, radial=self.p.final_crs_true)
        self.assertEqual(g.phase, "missed")
        self.assertEqual(g.heading, self.p.missed_hdg)
        self.assertEqual(g.altitude_ft, self.p.missed_climb_ft)
        self.assertFalse(g.established)

    def test_below_the_turn_altitude_he_climbs_straight_ahead_first(self):
        # "At 800 turn left 330" -- so at 500 he is still going straight.
        g = asr.guide(asr.Position(1.0, self.p.final_crs_true, 500,
                                   self.p.final_crs_true), self.p)
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
        inbound = (self.p.final_crs_true + 180) % 360
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


class TestRoomToFly(unittest.TestCase):
    """Being near the centreline is not the same as being able to fly it.

    A P-47 on the go-around, three miles out and pointing away from the field,
    was told to turn a hundred and thirty degrees onto a three-mile final:
    "he turned me around way, way, way too soon, and that left me way south of
    the field". The angle test said he was in position because a mile and a
    third at three miles is only twenty-five degrees. Closing it costs a mile
    and a third of centreline, and rolling out costs the turn-in distance on
    top, which is more approach than was left.
    """

    def setUp(self):
        self.p = vectored()

    def test_close_in_and_off_the_centreline_is_not_in_position(self):
        """The RULE: inside a few miles, a mile and a bit off the line is not a
        base leg, it is a squeeze. Closing it costs the cross-track and rolling
        out costs the turn-in distance on top, which is more approach than is
        left."""
        pos = asr.Position(range_nm=3.2, radial_deg=336, alt_ft=2898,
                           heading_deg=296)
        xtk = asr.cross_track(pos, self.p.final_crs_true)
        along = asr.along_track(pos, self.p.final_crs_true)
        self.assertGreater(abs(xtk), 1.3)
        self.assertLess(along, 3.2)
        self.assertFalse(asr.in_position(along, xtk, self.p),
                         "squeezed onto a three-mile final it cannot fly")

    def test_the_recorded_P47_position_reads_differently_now(self):
        """The radar fix from the sortie this class was written for.

        The complaint was "he turned me around way, way, way too soon, and that
        left me way south of the field", and the position was 1.35 nm off the
        centreline as we then drew it. Measured against the corrected course it
        is 0.99 nm off, and that IS in position -- so by today's geometry the
        turn was reasonable.

        Which is the point of keeping it. That centreline was six degrees off
        and sat SOUTH of the runway, which is both the direction he said he
        ended up and the likeliest reason the turn felt early. The incident is
        therefore unexplained again rather than fixed, and wants re-flying.
        """
        pos = asr.Position(range_nm=3.2, radial_deg=329, alt_ft=2898,
                           heading_deg=296)
        xtk = asr.cross_track(pos, self.p.final_crs_true)
        along = asr.along_track(pos, self.p.final_crs_true)
        self.assertAlmostEqual(abs(xtk), 0.99, delta=0.1)
        self.assertAlmostEqual(along, 3.05, delta=0.1)


    def test_the_run_has_to_fit_the_offset_plus_the_roll_out(self):
        # Just enough room, and just too little, either side of the same rule.
        self.assertTrue(asr.in_position(asr.TURN_IN_NM + 1.0, 0.9, self.p))
        self.assertFalse(asr.in_position(asr.TURN_IN_NM + 0.5, 0.9, self.p))

    def test_nearly_on_the_centreline_well_out_is_still_in_position(self):
        """The rule must not undo the case it was written around -- an aircraft
        established twelve miles out was once sent back to reposition."""
        self.assertTrue(asr.in_position(12.0, 0.2, self.p))
        self.assertTrue(asr.in_position(8.0, 0.2, self.p))


class TestOnTheGround(unittest.TestCase):
    """The approach ends when the wheels are down, and the scope knows.

    "I'm sitting on the ground at Batumi, and Batumi Tower thinks I'm on the
    missed approach." Nothing was reading the one source that knew.
    """

    def setUp(self):
        self.p = vectored()

    def at(self, nm, radial, alt):
        return asr.Position(range_nm=nm, radial_deg=radial, alt_ft=alt,
                            heading_deg=self.p.final_crs_true)

    def test_parked_on_the_aerodrome(self):
        self.assertTrue(asr.on_the_ground(self.at(0.0, 124, 30), self.p))

    def test_rolling_out_at_the_far_end(self):
        self.assertTrue(asr.on_the_ground(self.at(0.9, 124, 40), self.p))

    def test_short_final_is_still_flying(self):
        """The one that must not fire early -- two hundred feet at a mile and a
        half is an aeroplane being talked down, not a parked one."""
        self.assertFalse(asr.on_the_ground(self.at(1.5, 304, 200), self.p))

    def test_going_around_over_the_threshold_is_still_flying(self):
        self.assertFalse(asr.on_the_ground(self.at(0.3, 304, 900), self.p))


class TestConvergence(unittest.TestCase):
    """Fly the guidance and check it actually gets there.

    The unit tests all passed while the vectoring was flying a pilot out to sea,
    because each one checked a single look in isolation and the failure was in
    what the looks did in SEQUENCE. Simulating the whole approach is the only
    thing that catches a controller who is individually reasonable and
    collectively useless.
    """

    def setUp(self):
        self.p = vectored()

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
        self.assertTrue(profile().vectored)          # kind="asr"
        self.assertFalse(T.letdown().vectored)       # the beacon letdown


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
        self.p = vectored()

    # Read the frequencies off the stations rather than hardcoding them: these
    # tests broke the moment the numbers moved, which is noise, not signal.
    def freq(self, role):
        return R.station_for(role).freq_mhz

    def test_identity_by_frequency(self):
        # The bridge listens on every channel at once; the pilot must never be
        # able to hear that.
        for role in ("center", "approach", "tower"):
            s = R.station_for(role)
            self.assertEqual(R.station_on(s.freq_mhz).name, s.name)

    def test_an_unmanned_frequency_has_nobody_on_it(self):
        unused = 118.25
        self.assertNotIn(unused, [s.freq_mhz for s in R.STATIONS])
        self.assertIsNone(R.station_on(unused))

    def test_every_controller_is_tunable_by_a_period_set(self):
        # These are the field's real published frequencies, not the airframe's
        # stock buttons, so every one of them has to be WRITTEN into the
        # mission's presets -- a period set has four buttons and no way to dial
        # a frequency in the air. A preset write that silently fails leaves the
        # aircraft unable to talk to anybody, which is how the Jugs spent a
        # sortie mute. The band check is what keeps an untunable number out.
        for s in R.STATIONS:
            self.assertGreaterEqual(s.freq_mhz, 100.0, s.name)   # SCR-522 VHF AM
            self.assertLessEqual(s.freq_mhz, 156.0, s.name)
            self.assertEqual(s.freq_mhz, round(s.freq_mhz, 3), s.name)

    def test_the_mission_writes_a_preset_for_every_controller(self):
        from marshall.mission import build as mb
        presets = {mhz for _, mhz in mb.channels_for(self.p)}
        for s in R.STATIONS:
            self.assertIn(s.freq_mhz, presets, f"{s.name} has no radio button")

    # MIGRATED OFF `handoff_from`, which is deleted -- see route.py. These
    # asked a second set of handoff rules that only applied when the pilot
    # transmitted; `atc/handoff.py` is the one table now. The tests are the
    # same questions with the facts the old call could not express: whether he
    # is INBOUND, and whether he is DOWN. Both were being assumed. [#51]

    def _due(self, role, nm, inbound=True, on_ground=False, field="Batumi"):
        me = R.station_for(role, field=field) if role else None
        v = H.due(self.p, me, H.State(on_ground=on_ground, range_nm=nm,
                                      inbound=inbound))
        return None if (v is None or v.same_station) else v.station

    def test_center_keeps_him_while_he_is_far_out(self):
        self.assertIsNone(self._due("center", 40))

    def test_center_gives_him_to_approach_inside_the_boundary(self):
        """The row that did not exist in the OTHER table, which is why nothing
        could move a live sortie off Center at 44 nm. [#51]"""
        nxt = self._due("center", H.CENTER_NM - 2)
        self.assertIsNotNone(nxt, "Center still cannot hand anybody over")
        self.assertEqual(nxt.role, "approach")

    def test_center_does_not_hand_over_somebody_going_the_other_way(self):
        """The fact the old call could not see. Same range, opposite event."""
        self.assertIsNone(self._due("center", H.CENTER_NM - 2, inbound=False))

    def test_approach_keeps_him_through_the_talkdown(self):
        """He is not handed away in the middle of the procedure.

        This went the other way live, in cloud: "contact Batumi Tower now" at
        ten miles, from the same controller that was reading his range every
        mile. The pilot was told to leave the frequency flying his approach.

        ALL THE WAY DOWN NOW, not just to five miles. On a talkdown the
        controller IS the approach aid, so landing is the trigger rather than a
        distance -- see `_inbound_within`. The rule used to live as an `if` in
        the bridge, so only the half of the system that answers transmissions
        obeyed it.
        """
        self.assertEqual(self.p.guidance, "talkdown")
        for rng in (self.p.final_intercept_nm - 2, 8, 6, 4, 1):
            with self.subTest(nm=rng):
                self.assertIsNone(self._due("approach", rng),
                                  f"handed off at {rng} nm, mid-talkdown")

    def test_landing_is_what_gives_him_to_tower(self):
        """And it still happens -- suppressing the distance would be a bug if
        nothing else fired.

            "on touchdown ... approach didnt hand me off to tower"
        """
        nxt = self._due("approach", 0.3, inbound=False, on_ground=True)
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt.role, "tower")

    def test_where_the_pilot_flies_his_own_approach_the_distance_applies(self):
        """An ILS is not a talkdown: once established there is nothing left for
        Approach to do. The row that must not break when Kobuleti's ILS lands.
        """
        ils = dataclasses.replace(self.p, guidance="intercept")
        me = R.station_for("approach", field="Batumi")
        v = H.due(ils, me, H.State(False, 4.0, True))
        self.assertIsNotNone(v)
        self.assertEqual(v.station.role, "tower")

    def test_approach_keeps_him_before_final(self):
        self.assertIsNone(self._due("approach", 25))

    def test_tower_hands_off_to_nobody_inbound(self):
        """Tower's only rule is OUTBOUND -- an arrival is the end of the line.
        """
        self.assertIsNone(self._due("tower", 3, inbound=True))

    def test_an_unmanned_frequency_hands_off_to_nobody(self):
        self.assertIsNone(self._due(None, 10))

    def test_the_boundary_is_the_same_on_every_approach(self):
        """REPLACES a test that asserted an ILS hands off at the intercept and a
        talkdown at the missed approach point -- 11 nm against 0.6 nm, derived
        from which AID the pilot happened to be flying.

            "Don't treat the ASR different for handoffs at this time. Just make
             2 mile radius the tower airspace"

        Whose airspace the last two miles are is a fact about the FIELD. It does
        not change because the pilot has an ILS, or because the controller is
        reading him ranges every mile.
        """
        ils = dataclasses.replace(self.p, guidance="intercept")
        self.assertEqual(ils.hands_to_tower_nm, self.p.hands_to_tower_nm)
        self.assertEqual(self.p.hands_to_tower_nm, self.p.tower_takes_nm)

class TestTerrain(unittest.TestCase):
    """Vectoring on geometry alone will fly an aircraft into a mountain.

    Batumi has 1,000 ft of sea to the north-west and between seven and eleven
    thousand feet of Caucasus everywhere else. The whole beacon procedure lived
    north-west for that reason; the radar vectoring did not know terrain existed
    and was caught in the air turning a pilot over the ranges at two thousand.
    """

    def setUp(self):
        self.p = vectored()

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
                self.assertLess(R.mva_for(bearing, 15), R.msa_for(bearing))
        self.assertLessEqual(R.mva_for(330, 15), 2000)   # open water

    def test_vectoring_over_terrain_is_above_the_msa(self):
        for radial in (20, 120, 230):
            with self.subTest(radial=radial):
                g = asr.guide(asr.Position(15, radial, 5000, 200), self.p)
                self.assertGreaterEqual(g.altitude_ft, R.mva_for(radial, 15))

    def test_over_the_sea_he_is_not_held_high_by_terrain(self):
        # Nothing under him but water, so the only thing holding him up is the
        # descent profile, not the MSA.
        g = asr.guide(asr.Position(15, 330, 5000, 200), self.p)
        self.assertLess(g.altitude_ft, R.mva_for(75, 20))

    def test_he_reaches_platform_at_the_turn_on_and_not_before(self):
        """"No sense descending so early" -- but early is now a computed point.

        It used to be a fixed feet-per-mile gradient, which is only right at one
        groundspeed. What decides it now is how long the descent TAKES: 1,000 ft
        at 500 fpm is two minutes, which is five miles at 150 knots, so an
        aeroplane with nine miles to run keeps its altitude. See descent.py.
        """
        inbound = (self.p.final_crs_true + 180) % 360
        far = asr.guide(asr.Position(20, inbound, 3000, self.p.final_crs_true,
                                     speed_kt=150), self.p)
        at_turn_on = asr.guide(
            asr.Position(self.p.final_intercept_nm, inbound, 2500,
                         self.p.final_crs_true, speed_kt=150), self.p)
        self.assertGreater(far.altitude_ft, self.p.platform_ft,
                           "sent to platform with nine miles still to run")
        self.assertEqual(at_turn_on.altitude_ft, self.p.platform_ft)

    def test_a_fast_aeroplane_starts_down_earlier_than_a_slow_one(self):
        """The whole reason this stopped being a gradient. Same height, same
        distance, same 500 fpm -- and the jet needs twice the room."""
        from marshall.atc import descent as D
        slow = D.top_of_descent_nm(6000, 2000, 150)
        fast = D.top_of_descent_nm(6000, 2000, 300)
        self.assertGreater(fast, slow * 1.8)

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
        self.assertLessEqual(R.mva_for((self.p.final_crs + 180) % 360, 15), 2000)

    def test_a_profile_with_no_terrain_data_still_works(self):
        bare = dataclasses.replace(self.p, msa_sectors=[], mva_cells=[])
        self.assertEqual(bare.min_safe_ft(20), bare.platform_ft)

    def test_no_survey_falls_back_to_the_published_msa_not_to_batumi(self):
        # A new field must not inherit this one's mountains. With no vectoring
        # survey the published figure is the only defensible floor; borrowing
        # the module default would vector an aircraft over flat ground at
        # thirteen thousand feet for terrain a hundred miles away.
        flat = dataclasses.replace(self.p, mva_cells=[],
                                   msa_sectors=[(0.0, 360.0, 3000)])
        self.assertEqual(flat.min_safe_ft(120), 3000)
        self.assertEqual(flat.min_safe_ft(330), 3000)

if __name__ == "__main__":
    unittest.main()


class TestLeavingMyAirspace(unittest.TestCase):
    """Handing a flight back as it departs -- and never mid-approach.

    Range cannot express "keep him until he leaves my airspace", because range
    does not know whether he is arriving or departing. A flight leaving Batumi
    on a CAS sortie was given to Approach at 25 miles and never handed back.

    The dangerous direction is the other one: Tower's volume has a 4,000 ft
    ceiling, so an aircraft descending a talkdown sits inside it. Letting
    geography vote there would re-create the exact bug that took a pilot off
    the frequency flying his approach.
    """

    def setUp(self):
        from marshall.atc import agent_atc
        self.A = agent_atc
        self.p = vectored()
        self.approach = R.station_for("approach")

    def at(self, nm):
        return asr.Position(range_nm=nm, radial_deg=304, alt_ft=2000,
                            heading_deg=self.p.final_crs)

    def test_a_talkdown_inside_the_final_is_never_handed_over(self):
        """No HTTP call is even made -- the guard returns first."""
        for nm in (10.0, 6.0, 2.0, 1.0):
            with self.subTest(nm=nm):
                self.assertIsNone(
                    self.A.leaving_my_airspace(
                        "http://127.0.0.1:1",      # would fail if reached
                        "s", "Pony 1-1", self.approach, self.p, self.at(nm)))

    def test_a_broken_director_does_not_break_the_handoff(self):
        """Airspace is an improvement, not a crutch: unreachable means no
        opinion, and route.py's rules still stand."""
        self.assertIsNone(
            self.A.leaving_my_airspace("http://127.0.0.1:1", "s", "Pony 1-1",
                                       self.approach, self.p, self.at(40.0)))


class TestHandoffPhraseWithoutARadarFix(unittest.TestCase):
    """A handoff must never depend on having our own radar fix.

    An airspace handoff is answered from the PostGIS view and needs no fix. The
    phrase read one anyway and took the whole bridge down mid-rehearsal -- a
    crash, not a bad call, from a piece of wording, leaving pilots on a silent
    frequency. Nothing in a sentence should be able to do that.
    """

    def setUp(self):
        from marshall.atc import agent_atc
        self.A = agent_atc
        self.tower = R.station_for("tower", field=R.ARRIVAL_FIELD)

    def test_with_no_fix_it_still_hands_him_over(self):
        said = self.A.handoff_phrase(self.tower, None)
        self.assertIn("Batumi Tower", said)
        self.assertIn("left your airspace", said)

    def test_with_a_fix_it_says_the_range(self):
        pos = asr.Position(range_nm=12.0, radial_deg=304, alt_ft=3000,
                           heading_deg=124)
        self.assertIn("12 miles out", self.A.handoff_phrase(self.tower, pos))


class TestClimbingOutOnTheMissed(unittest.TestCase):
    """An aircraft flying the published missed must not be vectored back.

    Reported on the first night and true for three sessions:

        "pny flight is outbound after the missed and the atc is saying that he
         is left of course (thinking he is inbound)"

    The mechanism, found by measuring rather than reading: the missed branch sat
    BELOW the in-position test, and the second leg of the procedure -- the
    climbing turn onto 330 -- puts the aeroplane on the approach SIDE of the
    field with positive along-track. It read as "in position" and was handed an
    intercept, turning it back towards the field it was climbing away from.

    The fix is not a cleverer geometric test. Four were tried and every one
    flickered, because the procedure commands a two-hundred-degree turn and half
    way round it the aeroplane is on nobody's track. Whether a man is flying the
    missed approach is a fact about his HISTORY, so the caller holds it.
    """

    def setUp(self):
        self.p = vectored()

    def climbing_out(self, nm, alt):
        return asr.Position(range_nm=nm, radial_deg=self.p.missed_hdg,
                            alt_ft=alt, heading_deg=self.p.missed_hdg)

    def test_he_is_left_to_fly_the_procedure(self):
        for nm, alt in ((3.0, 1500), (5.0, 2000), (8.0, 2600)):
            with self.subTest(nm=nm):
                g = asr.guide(self.climbing_out(nm, alt), self.p, on_missed=True)
                self.assertEqual(g.phase, "missed",
                                 f"vectored to {g.heading} while climbing out")
                self.assertEqual(g.heading, self.p.missed_hdg)

    def test_he_is_not_told_he_is_off_course(self):
        """He is flying the heading he was given and is exactly where he should
        be. 'Left of course' is not true in any useful sense."""
        g = asr.guide(self.climbing_out(5.0, 2000), self.p, on_missed=True)
        self.assertEqual(g.deviation, "")

    def test_the_procedure_ends_at_the_missed_approach_altitude(self):
        """A latch with no release is a worse bug than the one it fixes."""
        g = asr.guide(self.climbing_out(9.0, self.p.missed_climb_ft + 200),
                      self.p, on_missed=True)
        self.assertNotEqual(g.phase, "missed")

    def test_and_when_he_flies_out_of_the_terminal_area(self):
        g = asr.guide(
            asr.Position(range_nm=self.p.final_intercept_nm + 5,
                         radial_deg=self.p.missed_hdg, alt_ft=2000,
                         heading_deg=self.p.missed_hdg),
            self.p, on_missed=True)
        self.assertNotEqual(g.phase, "missed")

    def test_geometry_alone_cannot_know_and_does_not_pretend_to(self):
        """Unlatched, the same position is an ordinary vectoring problem -- and
        that is correct, not a bug. Nothing in where he IS says he went around;
        four attempts to infer it from position all produced reversals."""
        g = asr.guide(self.climbing_out(5.0, 2000), self.p)
        self.assertNotEqual(g.phase, "missed")



class TestTheReversalHooverFlew(unittest.TestCase):
    """#19, from the aeroplane, at last.

    Four fix attempts across two sessions never reproduced this, because the
    sweep flies a pilot who OBEYS -- `--sloppy` lags and overshoots and still
    complies -- and the bug needs the geometry to keep getting worse while the
    controller keeps talking. Hoover produced exactly that by accident: he was
    outbound at 320, five to eight miles northwest, reading a bug report to
    engineering and not turning.

        "when I'm in this range between the inner, basically near the runway,
         going the opposite direction. This is where he gets very, very
         confused."

    His radar trace, and what the engine said to it:

        4.9 nm  r305  hdg 318   ->  turn to 126   xtk -0.09
        6.1 nm  r310  hdg 320   ->  turn to 142   xtk -0.64
        6.7 nm  r312  hdg 322   ->  turn to 149   xtk -0.93
        7.7 nm  r315  hdg 324   ->  turn to 160   xtk -1.47
        8.5 nm  r316  hdg 324   ->  turn to 165   xtk -1.77
       10.0 nm  r318  hdg 324   ->  turn to 309   xtk -2.42     <-- 144 degrees

    Two faults in one trace. The engine hands an aircraft flying AWAY from the
    field the intercept heading it would give one flying towards it -- 126 to a
    man on 318 is an instant one-eighty at five miles, not a vector -- and then,
    somewhere past two miles of cross-track, it gives up and sends him outbound
    instead, in a single 144-degree reversal with no downwind and no base leg.
    """

    TRACE = [(4.9, 305, 2032, 318), (6.1, 310, 1976, 320), (6.7, 312, 1907, 322),
             (7.7, 315, 1848, 324), (8.5, 316, 1800, 324), (10.0, 318, 1800, 324)]

    def headings(self):
        p = vectored()
        return [asr.guide(G.Position(rng, rad, alt, hdg), p).heading
                for rng, rad, alt, hdg in self.TRACE]

    def test_the_headings_progress_instead_of_reversing(self):
        """It was 126, 142, 149, 160, 165, then 309 -- a 144-degree flip. It is
        now 111, 122, 128, 140, 145, 156: the same trace, walking round.

        The cause was never the vectoring logic. The centreline was drawn six
        degrees off because the course was in the DCS grid frame and the radials
        were true, and this trace sat exactly where that error changed which
        side of the course he was on -- so the engine kept switching its mind
        about which way to send him. Fix the frame and the flip has nothing to
        stand on."""
        got = self.headings()
        biggest = max(abs(G.angle_diff(b, a)) for a, b in zip(got, got[1:]))
        self.assertLessEqual(biggest, 20, f"reversing again: {got}")

    def test_a_vector_should_never_reverse_on_a_man_holding_his_heading(self):
        """What SHOULD happen. Nothing about his flying changed between one call
        and the next -- same heading, a mile further out -- so nothing about the
        instruction should change by 144 degrees. Turning him around is a
        decision to re-sequence him, and that is a downwind and a base leg, not
        one word."""
        got = self.headings()
        for a, b in zip(got, got[1:]):
            self.assertLessEqual(abs(G.angle_diff(b, a)), 90,
                                 f"reversed from {a} to {b} in one call: {got}")


class TestTheDescentPlanner(unittest.TestCase):
    """When to start down. Its own engine, because a RATE is not a GRADIENT.

        "It should try to time my altitude so I arrive at the if 2000 from
         wherever I was... take current alt, ground speed and distance from IF
         to calculate a 500fpm descent and start down point."

    500 fpm is a comfortable descent in anything; what it costs in MILES depends
    entirely on how fast he is going. The old code used a fixed feet-per-mile
    figure, which is correct at exactly one groundspeed and wrong for every
    other aeroplane.
    """

    def test_the_distance_a_descent_takes_scales_with_speed(self):
        from marshall.atc import descent as D
        self.assertAlmostEqual(D.miles_to_lose(1000, 150), 5.0, places=1)
        self.assertAlmostEqual(D.miles_to_lose(1000, 300), 10.0, places=1)

    def test_high_and_far_keeps_his_altitude(self):
        from marshall.atc import descent as D
        d = D.plan(alt_ft=6000, target_ft=2000, to_go_nm=40, groundspeed_kt=150)
        self.assertFalse(d.descending)
        self.assertEqual(d.assign_ft, 6000)

    def test_past_the_top_of_descent_he_is_sent_down(self):
        from marshall.atc import descent as D
        d = D.plan(alt_ft=6000, target_ft=2000, to_go_nm=10, groundspeed_kt=150)
        self.assertTrue(d.descending)
        self.assertEqual(d.assign_ft, 2000)

    def test_the_start_point_is_where_the_descent_actually_fits(self):
        """Arrive AT the fix at the target, not five miles before it."""
        from marshall.atc import descent as D
        d = D.plan(alt_ft=4000, target_ft=2000, to_go_nm=99, groundspeed_kt=180)
        self.assertAlmostEqual(d.needed_nm, 12.0, places=1)
        self.assertGreater(d.start_nm, d.needed_nm)     # a little lead

    def test_already_low_is_left_alone(self):
        """An aeroplane below the profile is not asked to climb back onto it."""
        from marshall.atc import descent as D
        d = D.plan(alt_ft=1500, target_ft=2000, to_go_nm=5, groundspeed_kt=150)
        self.assertFalse(d.descending)
        self.assertEqual(d.assign_ft, 1500)

    def test_an_unknown_speed_is_assumed_SLOW(self):
        """Guessing low starts him down early, which costs fuel. Guessing high
        starts him late, which does not work."""
        from marshall.atc import descent as D
        unknown = D.miles_to_lose(2000, 0)
        self.assertAlmostEqual(unknown, D.miles_to_lose(2000, D.ASSUMED_KT))
        self.assertLess(unknown, D.miles_to_lose(2000, 300))
