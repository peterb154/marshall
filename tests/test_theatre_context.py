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
        out here, and a vector is the one place that shows.

        Nellis, because the default Nevada sortie recovers at Nellis: a range
        flight goes out and comes HOME, and the recovery field is the one a
        controller measures from.
        """
        from marshall.feed import dcs as D
        self.assertAlmostEqual(D.home_field()[2], 12.0, places=1)

    def test_the_field_by_the_names_a_pilot_uses(self):
        from marshall.feed import tracks as TR
        got = TR._field_aliases()
        self.assertIn("nellis", got)
        self.assertNotIn("batumi", got)


class EitherNevadaSortieCanBeSelected(_OnTheMap):
    """One arrival profile at a time is the bridge's real limit (#111). The
    CHOICE at least being explicit is what stops a pilot flying home to Nellis
    while the bridge has Tonopah's ILS loaded."""
    theatre = "nevada"

    def test_the_default_is_out_of_nellis_and_home_again(self):
        # A SORTIE, NOT AN ARRIVAL. The middle assertion was
        # `approach_key == "nellis-ils-21"`, and a sortie choosing a
        # PROCEDURE is what #162 deleted: it says where you depart and
        # where you recover, and Approach issues the approach.
        self.assertEqual(self.th.arrival, "Nellis")
        self.assertEqual(self.th.bootstrap_plan, "nevada-nellis-nellis")
        self.assertFalse(hasattr(self.th, "approach_key"))

    def test_the_one_way_transit_is_a_flag_away(self):
        was = os.environ.get("MARSHALL_SORTIE")
        os.environ["MARSHALL_SORTIE"] = "tonopah"
        try:
            th = self._theatre()
            self.assertEqual(th.arrival, "Tonopah")
            self.assertEqual(th.bootstrap_plan, "nevada-nellis-tonopah")
        finally:
            if was is None:
                os.environ.pop("MARSHALL_SORTIE", None)
            else:
                os.environ["MARSHALL_SORTIE"] = was

    def test_both_profiles_are_published_either_way(self):
        """A Nellis-recovery bridge still has to know Tonopah exists -- the
        route turns over it and the pilot may divert."""
        self.assertEqual(len(self.th.approaches), 2)


if __name__ == "__main__":
    unittest.main()


class OnTheGroundMeansOnTHISGround(_OnTheMap):
    """`GROUND_ALT_FT = 200` was compared against altitude above SEA level.

    That works at Batumi, 32 feet up, and is nonsense anywhere with terrain: the
    RAMP at Nellis is 1,849 feet and Tonopah's is 5,550, so every parked
    aeroplane read as airborne.

    Everything gated on "is he down" was wrong with it -- the ramp guard, the
    phase branch of `handoff.due`, the silence that keeps approach guidance off
    a taxiing aircraft. Measured: Clearance handed a stationary F-16 to Los
    Angeles Center before it had asked for anything, because the airspace branch
    decided it had left the terminal area.

    The sim's own land/takeoff event is checked first and is authoritative; this
    only decides for aircraft no event has covered. [#114]
    """
    theatre = "nevada"

    def _parked(self, alt_ft):
        from marshall.atc import agent_atc as A
        from marshall.atc import asr
        A._ELEV = None
        return A.is_on_the_ground(
            "", "", asr.Position(0.9, 236.0, alt_ft, 129.0, speed_kt=0.0))

    def test_parked_on_the_nellis_ramp_is_on_the_ground(self):
        self.assertTrue(self._parked(1849))

    def test_parked_at_tonopah_is_too(self):
        """A mile and a half up, and stationary."""
        self.assertTrue(self._parked(5550))

    def test_but_a_thousand_feet_over_the_highest_field_is_not(self):
        """The threshold still has to mean something. Generous, because being
        wrong towards "on the ground" only defers to the sim's own event."""
        self.assertFalse(self._parked(9000))


class AndTheCaucasusIsUnchanged(_OnTheMap):

    def test_a_taxiing_mustang_is_still_on_the_ground(self):
        from marshall.atc import agent_atc as A
        from marshall.atc import asr
        A._ELEV = None
        self.assertTrue(A.is_on_the_ground(
            "", "", asr.Position(0.4, 90.0, 65, 70.0, speed_kt=12.0)))

    def test_and_one_at_five_hundred_feet_is_not(self):
        from marshall.atc import agent_atc as A
        from marshall.atc import asr
        A._ELEV = None
        self.assertFalse(A.is_on_the_ground(
            "", "", asr.Position(2.0, 90.0, 500, 70.0, speed_kt=140.0)))
