"""Where he is along a route, and when to say something.

Pure geometry -- no radio, no board, no database -- so every case below is
testable without a sortie. [#217]
"""
from __future__ import annotations

import unittest

from marshall.core.following import Along, Leg, guide, next_index, off_course

# A real route off the Caucasus theatre rather than invented numbers: Kobuleti,
# out to BAR, back into Batumi. Legs that are 18 and 41 nm long, at an angle to
# each other, which is what makes passage and cross-track mean anything.
KOB = Leg("KOBULETI", 41.9299, 41.8633, 59)
BAR = Leg("BAR", 42.1858, 42.0941, 10000)
BAT = Leg("BATUMI", 41.6094, 41.5999, 33)
ROUTE = [BAR, BAT]


def at(lat, lon, index=0):
    return guide(ROUTE, lat, lon, index, start=KOB)


class HeIsToldWhereToGo(unittest.TestCase):

    def test_a_heading_a_distance_and_a_level(self):
        g = at(41.99, 41.95)
        self.assertEqual(g.fix, "BAR")
        self.assertEqual(g.alt_ft, 10000)
        self.assertGreater(g.distance_nm, 10)
        self.assertTrue(0 <= g.heading_true < 360)

    def test_the_heading_is_to_the_FIX_and_not_down_the_leg(self):
        """A man three miles off course who flies the leg's course stays three
        miles off course for ever."""
        on_line = at(42.05, 41.97)
        wide = at(42.05, 42.15)
        self.assertNotAlmostEqual(on_line.heading_true, wide.heading_true,
                                  places=0)

    def test_the_route_ends(self):
        self.assertIsNone(guide(ROUTE, 41.6, 41.6, 2, start=KOB))

    def test_an_empty_route_is_not_a_crash(self):
        self.assertIsNone(guide([], 41.6, 41.6, 0, start=KOB))


class PassageIsThePerpendicular(unittest.TestCase):
    """Not a radius. A fast jet cutting the corner may never come inside any
    distance worth picking."""

    def test_short_of_the_fix_he_has_not_passed_it(self):
        self.assertFalse(at(42.15, 42.06).passed)

    def test_beyond_it_he_has(self):
        self.assertTrue(at(42.21, 42.12).passed)

    def test_and_cutting_the_corner_still_counts(self):
        """Two miles to one side and past the perpendicular. A radius of one
        mile would have missed him entirely."""
        g = at(42.22, 42.03)
        self.assertGreater(abs(g.xtk_nm), 1.5, "genuinely wide of the fix")
        self.assertTrue(g.passed)

    def test_the_latch_advances_once_and_only_forwards(self):
        past = at(42.21, 42.12)
        self.assertEqual(next_index(past, 0), 1)
        # ...and a wobble back does not undo it: the caller holds the latch and
        # `next_index` never decreases.
        back = at(42.15, 42.06, index=1)
        self.assertEqual(next_index(back, 1), 1)


class TheFirstLegNeedsSomewhereToHaveComeFrom(unittest.TestCase):
    """A route's fixes are its ENDS. `legs[0]` is somewhere to go, not
    somewhere he has been."""

    def test_with_no_start_he_still_gets_a_bearing_and_a_range(self):
        """Which is the whole of "direct BAR"."""
        g = guide(ROUTE, 41.99, 41.95, 0, start=None)
        self.assertEqual(g.fix, "BAR")
        self.assertGreater(g.distance_nm, 10)

    def test_but_no_cross_track_and_no_passage(self):
        """Both need a line and there is not one. Claiming zero cross-track as
        a measurement would read as 'on course' to a man who has no course."""
        g = guide(ROUTE, 41.99, 41.95, 0, start=None)
        self.assertEqual(g.xtk_nm, 0.0)
        self.assertFalse(g.passed)


class OffCourseHasThreeSuppressions(unittest.TestCase):

    def _off(self, xtk, along=20.0, leg=41.0):
        return Along(1, "BATUMI", 200.0, 20.0, 5000, xtk, along, leg)

    def test_it_takes_the_band_to_start(self):
        self.assertFalse(off_course(self._off(1.5), alerting=False))
        self.assertTrue(off_course(self._off(2.5), alerting=False))

    def test_and_coming_back_inside_to_stop(self):
        """Hysteresis. Without it he is nagged on the boundary -- measured on
        the approach sweep, where rounding without it took dithering from 0 to
        7 and turns from 581 to 1614."""
        self.assertTrue(off_course(self._off(1.5), alerting=True),
                        "still out, still being told")
        self.assertFalse(off_course(self._off(0.5), alerting=True))

    def test_it_is_silent_through_the_turn(self):
        """At 400 knots and 30 degrees of bank the radius is about 4 nm, so a
        ninety-degree turn swings four miles wide before it settles. A 2 nm
        alert would fire on EVERY turn."""
        self.assertFalse(off_course(self._off(4.0, along=1.0), alerting=False))
        self.assertTrue(off_course(self._off(4.0, along=20.0), alerting=False))

    def test_either_side_counts(self):
        for xtk in (3.0, -3.0):
            with self.subTest(xtk=xtk):
                self.assertTrue(off_course(self._off(xtk), alerting=False))

    def test_nothing_to_judge_is_not_a_complaint(self):
        self.assertFalse(off_course(None, alerting=True))
        self.assertFalse(off_course(self._off(9.0, leg=0.0), alerting=False))


class TheHeadingsAreTrue(unittest.TestCase):
    """Stated so the boundary stays visible. Converting to magnetic belongs in
    ONE place at the point of speech -- three renderers in this codebase already
    forget, and unlike a radial these numbers are FLOWN."""

    def test_the_field_says_so(self):
        self.assertIn("heading_true", Along.__dataclass_fields__)
        self.assertNotIn("heading", Along.__dataclass_fields__)


if __name__ == "__main__":
    unittest.main()
