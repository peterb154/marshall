"""Nothing renders another map's world.

    "the fallback renderer in `feed/dcs.py` and `feed/tracks.py` still uses
     Batumi coordinates and a fixed 6 degree Caucasus magnetic variation. A
     fallback must be conservatively unavailable, not confidently wrong on
     another map."
                                                    -- CODEX_NTTR_AUDIT.md

Three Caucasus facts were compiled into theatre-neutral paths, and each is the
same mistake: a constant standing in for something the loaded theatre knows.

    push_fixes        read `core.route`'s module globals for every `Fix`, so on
                      Nevada it published KOBULETI and BATUMI and never NELLIS
                      -- whose own filed plan is `NELLIS, TONOPAH`, and
                      clearance delivery refuses a plan naming a fix the table
                      does not hold.
    stt_prompt        primed Whisper with the Caucasus strike route, biasing the
                      transcript towards words that cannot occur on this map.
    the radar origin  bearing and range measured from Batumi, with a fixed 6
                      degrees of variation, wherever the aeroplanes were.

A wrong theatre is not subtle: Batumi's coordinates on the Nevada map are about
a hundred and fifty degrees and a thousand miles from anything.
"""

from __future__ import annotations

import importlib
import os
import unittest


class _OnTheMap(unittest.TestCase):
    """Load a theatre and put back whatever was there before."""

    theatre = "caucasus"

    def setUp(self):
        self._was = os.environ.get("MARSHALL_THEATRE")
        os.environ["MARSHALL_THEATRE"] = self.theatre
        from marshall.feed import dcs as D
        D._HOME = None                      # the origin is cached on purpose
        self.th = self._theatre()

    def tearDown(self):
        from marshall.feed import dcs as D
        D._HOME = None
        if self._was is None:
            os.environ.pop("MARSHALL_THEATRE", None)
        else:
            os.environ["MARSHALL_THEATRE"] = self._was

    def _theatre(self):
        from marshall.core import theatre as T
        importlib.reload(T)
        return T.current()


class TheTheatreOwnsItsFixes(_OnTheMap):

    def test_caucasus_publishes_its_own(self):
        names = {f.name for f in self.th.fixes}
        self.assertIn("KOBULETI", names)
        self.assertIn("BATUMI", names)


class NevadaPublishesNellis(_OnTheMap):
    theatre = "nevada"

    def test_the_field_the_bootstrap_plan_routes_via(self):
        """`nevada-nellis-tonopah` is `NELLIS, TONOPAH`. If NELLIS is not in the
        catalogue the bridge publishes, delivery refuses its own plan."""
        names = {f.name for f in self.th.fixes}
        self.assertIn("NELLIS", names)
        self.assertIn("TONOPAH", names)

    def test_and_none_of_the_caucasus_ones(self):
        names = {f.name for f in self.th.fixes}
        self.assertFalse(names & {"KOBULETI", "BATUMI", "INGRESS", "FEET WET"},
                         "a Nevada bridge is publishing Caucasus fixes")

    def test_the_route_is_numbered_for_steerpoints(self):
        self.assertEqual([(n, f.name) for n, f in self.th.waypoints],
                         [(1, "NELLIS"), (2, "TONOPAH"), (3, "NELLIS")])


class TheRadarPictureIsMeasuredFromThisMap(_OnTheMap):

    def test_caucasus_measures_from_batumi_with_six_degrees(self):
        """Batumi's `magvar_deg` is 0.0, which means "use the theatre default",
        and the default is 6 East. Reading the raw attribute instead of
        `variation()` would swap one wrong constant for another."""
        from marshall.feed import dcs as D
        lat, _lon, var = D.home_field()
        self.assertAlmostEqual(lat, 41.6103, places=3)
        self.assertAlmostEqual(var, 6.0, places=1)


class NevadaMeasuresFromNevada(_OnTheMap):
    theatre = "nevada"

    def test_not_from_georgia(self):
        from marshall.feed import dcs as D
        lat, lon, _var = D.home_field()
        self.assertGreater(lat, 30.0)
        self.assertLess(lon, -100.0, "the origin is still in the Caucasus")

    def test_the_variation_is_the_field_s_own(self):
        """12 East at Nellis, 16 at Tonopah -- surveyed per aerodrome, exactly
        like the terrain minima. A theatre-wide constant is six to ten degrees
        out here, and a vector is the one place that shows."""
        from marshall.feed import dcs as D
        self.assertAlmostEqual(D.home_field()[2], 16.0, places=1)

    def test_the_field_by_the_names_a_pilot_uses(self):
        from marshall.feed import tracks as TR
        got = TR._field_aliases()
        self.assertIn("tonopah", got)
        self.assertNotIn("batumi", got)


if __name__ == "__main__":
    unittest.main()
