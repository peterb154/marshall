"""Three frames, one crossing point, and a round trip that proves it.

    "What's the mag/true frame boundary?"

    grid       DCS's own x/z transverse Mercator -- what the sim reports an
               aircraft's HEADING in
    true       what a bearing computed from latitude and longitude is, so every
               RADIAL is one
    magnetic   what a pilot reads off his HSI, and the only frame that may be
               SPOKEN

The formula was never the problem: `geo.magnetic` is one line and has always
been right. What went wrong is that calling it was a step each renderer had to
REMEMBER, and three separate ones forgot -- printing a true bearing and a grid
heading with words that claim a third frame:

    "8.9 nm on the 075 radial, 5,000 ft, heading 123"

It survived because at Batumi the corrections nearly cancel: variation 6 East
against a grid convergence of 0.0. A Nevada controller is 12 degrees out at
Nellis and 16 at Tonopah. [#217]
"""
from __future__ import annotations

import unittest

from marshall.atc import agent_atc as A
from marshall.atc import picture
from marshall.core import geo

BATUMI = (41.6094, 41.5999)


class TheConversionHasOneHome(unittest.TestCase):

    def test_a_spoken_bearing_is_the_true_one_less_the_variation(self):
        self.assertAlmostEqual(geo.spoken_bearing(121.0, 6.0), 115.0, places=3)

    def test_a_spoken_heading_crosses_both_frames(self):
        """Grid to true to magnetic, in one call, because the error was always
        whether somebody remembered to apply them."""
        self.assertAlmostEqual(geo.spoken_heading(215.0, 0.0, 6.0), 209.0,
                               places=3)
        self.assertAlmostEqual(geo.spoken_heading(215.0, 5.74, 6.0), 214.74,
                               places=2)

    def test_the_offsets_come_from_the_FIELD(self):
        """Never a theatre constant: a Caucasus variation applied to a Nevada
        heading is a bug nobody would see in a code review."""
        var, conv = geo.frames_at("Batumi")
        self.assertAlmostEqual(var, 6.0, places=2)
        self.assertAlmostEqual(conv, 0.0, places=2)

    def test_with_no_theatre_it_shifts_nothing(self):
        """A probe or a fixture has no map, and moving its numbers by a made-up
        variation would be worse than leaving them alone."""
        import unittest.mock as mock
        from marshall.core import theatre as t
        with mock.patch.object(t, "current", side_effect=RuntimeError):
            self.assertEqual(geo.frames_at(""), (0.0, 0.0))


class TheRoundTripIsExact(unittest.TestCase):
    """THE INVARIANT THE BOUNDARY RESTS ON, and the one I could not check the
    first time I tried this. The picture is prose for a pilot AND a wire format
    the parsers read back into geometry, so a number that crosses out has to
    cross back to exactly where it started -- otherwise the frame fix quietly
    moves every aeroplane six degrees."""

    def _prose(self, true_brg, nm, grid_hdg):
        lat, lon = geo.project_true(BATUMI, true_brg, nm)
        return picture.picture([{
            "label": "362nd_sockeye", "name": "Viper 1-4", "type": "F-16C_50",
            "manned": True, "lat": lat, "lon": lon, "alt_ft": 4000,
            "heading": grid_hdg, "speed_kt": 300, "category": "airplane"}],
            BATUMI)

    def test_what_goes_out_comes_back(self):
        for brg, hdg in ((121.0, 215.0), (5.0, 355.0), (270.0, 90.0)):
            with self.subTest(bearing=brg, heading=hdg):
                pos = A.radar_fix_by_track(self._prose(brg, 8.0, hdg),
                                           "362nd_sockeye")
                self.assertIsNotNone(pos)
                self.assertAlmostEqual(pos.radial_deg, brg, places=0)
                self.assertAlmostEqual(pos.heading_deg, hdg, places=0)

    def test_and_the_prose_itself_is_magnetic(self):
        """The half a pilot hears. If this ever reads 121 again, a renderer has
        stopped converting."""
        self.assertIn("115 radial", self._prose(121.0, 8.0, 215.0))
        self.assertIn("heading 209", self._prose(121.0, 8.0, 215.0))


class EveryRendererOfThisSentenceConverts(unittest.TestCase):
    """THE FAULT WAS NEVER ONE RENDERER. The same line is built in three places
    -- `atc/picture.py` for the controller, `feed/tracks.py` for the cached
    `/radar`, `feed/dcs.py` for the cold-cache scan -- and fixing one of them
    left the other two emitting the old frame, which is how the first attempt
    at this failed in ways I could not predict."""

    def test_all_three_call_the_boundary(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1] / "src" / "marshall"
        for rel in ("atc/picture.py", "feed/tracks.py", "feed/dcs.py"):
            with self.subTest(renderer=rel):
                src = (root / rel).read_text()
                self.assertIn("radial", src, "this is one of the renderers")
                self.assertIn("spoken_bearing", src,
                              f"{rel} prints a radial without converting it")


if __name__ == "__main__":
    unittest.main()
