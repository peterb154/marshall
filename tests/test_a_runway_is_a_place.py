"""Occupancy as an OBSERVATION rather than an inference from what was said.

    "since the sim exposes runway geometry - we ought to have a deterministic
     check to see if anyone is on the runway"

The corners here are the real ones, pulled from the running sim on 31 August
and checked against the dimensions it reported for each strip:

    Batumi   31   sim 2070.4 x 60.0 m    polygon 2056.2 x 59.6
    Kobuleti 25   sim 2257.6 x 60.0 m    polygon 2238.2 x 59.7

The 0.7% is great-circle against the sim's planar metres, not an error worth
chasing on a rectangle sixty metres wide.
"""
from __future__ import annotations

import math
import unittest

from marshall.core.runways import Runway, who_is_on

BATUMI = Runway(
    field_name="Batumi", name="31", length_m=2070.4, width_m=60.0,
    heading_true=131.4,
    corners=((41.5911965, 41.6159133), (41.5907246, 41.6155100),
             (41.6092755, 41.6032801), (41.6097475, 41.6036833)))

KOBULETI = Runway(
    field_name="Kobuleti", name="25", length_m=2257.6, width_m=60.0,
    heading_true=75.9,
    corners=((41.8500666, 41.9277311), (41.8502402, 41.9272102),
             (41.8764838, 41.9321051), (41.8763104, 41.9326260)))


def _bearing(a, b) -> float:
    (lat1, lon1), (lat2, lon2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = (math.cos(p1) * math.sin(p2)
         - math.sin(p1) * math.cos(p2) * math.cos(dl))
    return math.degrees(math.atan2(y, x)) % 360


def centre(r: Runway):
    return (sum(p[1] for p in r.corners) / 4.0,     # lat
            sum(p[0] for p in r.corners) / 4.0)     # lon


def metres(a, b) -> float:
    (lat1, lon1), (lat2, lon2) = a, b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    return 2 * 6371000.0 * math.asin(math.sqrt(
        math.sin(dp / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))


def along(r: Runway, metres_from_centre: float):
    """A point down the runway's own axis, from its centre."""
    lat, lon = centre(r)
    h = math.radians(r.heading_true)
    dlat = (metres_from_centre * math.cos(h)) / 111_320.0
    dlon = (metres_from_centre * math.sin(h)) / (
        111_320.0 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def across(r: Runway, metres_from_centre: float):
    lat, lon = centre(r)
    h = math.radians(r.heading_true + 90.0)
    dlat = (metres_from_centre * math.cos(h)) / 111_320.0
    dlon = (metres_from_centre * math.sin(h)) / (
        111_320.0 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


class TheGeometryIsTheSimS(unittest.TestCase):
    """Asserted so a wrong course convention cannot pass as a plausible
    rectangle at the wrong angle -- which is how it would fail."""

    def test_the_polygon_has_the_dimensions_the_sim_reported(self):
        for r in (BATUMI, KOBULETI):
            with self.subTest(field=r.field_name):
                sides = [metres((r.corners[i][1], r.corners[i][0]),
                                (r.corners[(i + 1) % 4][1],
                                 r.corners[(i + 1) % 4][0]))
                         for i in range(4)]
                short, long_ = min(sides), max(sides)
                self.assertAlmostEqual(short, r.width_m, delta=2.0)
                self.assertAlmostEqual(long_, r.length_m, delta=25.0)

    def test_the_long_axis_matches_the_surveyed_approach_course(self):
        """THE CHECK A WRONG ANGLE CANNOT PASS, and the only one that catches
        it: a rectangle of the right SIZE at the wrong angle measures perfectly.
        Six degrees walks the ends of a 2 km strip a hundred metres sideways,
        clear of a rectangle sixty metres wide.

        `final_crs_true` is surveyed and lives in `route.py`, so this is the
        sim's geometry checked against a number that came from somewhere else
        entirely."""
        from marshall.core import route as R
        for r, pro in ((BATUMI, R.BATUMI_ASR), (KOBULETI, R.KOBULETI_ILS)):
            with self.subTest(field=r.field_name):
                axis = _bearing((r.corners[1][1], r.corners[1][0]),
                                (r.corners[2][1], r.corners[2][0]))
                off = abs(((axis - pro.final_crs_true + 180) % 360) - 180)
                off = min(off, abs(180 - off))       # either way down the strip
                self.assertLess(off, 1.5,
                                f"polygon axis {axis:.1f} vs surveyed "
                                f"{pro.final_crs_true:.1f}")

    def test_both_thresholds_are_on_it(self):
        for r in (BATUMI, KOBULETI):
            with self.subTest(field=r.field_name):
                self.assertTrue(r.holds(*along(r, r.length_m / 2 - 30)))
                self.assertTrue(r.holds(*along(r, -(r.length_m / 2 - 30))))


class WhoIsStandingOnIt(unittest.TestCase):

    def test_the_centre_is_on_it(self):
        for r in (BATUMI, KOBULETI):
            with self.subTest(field=r.field_name):
                self.assertTrue(r.holds(*centre(r)))

    def test_beyond_the_threshold_is_not(self):
        for r in (BATUMI, KOBULETI):
            with self.subTest(field=r.field_name):
                self.assertFalse(r.holds(*along(r, r.length_m / 2 + 150)))

    def test_beside_it_is_not(self):
        """A holding point is metres from the edge, and counting it would
        deadlock the field -- neither aeroplane could ever be cleared."""
        for r in (BATUMI, KOBULETI):
            with self.subTest(field=r.field_name):
                self.assertFalse(r.holds(*across(r, 80)))

    def test_the_other_field_is_not_his(self):
        self.assertFalse(BATUMI.holds(*centre(KOBULETI)))
        self.assertFalse(KOBULETI.holds(*centre(BATUMI)))


class OnlyAeroplanesThatAreDown(unittest.TestCase):
    """An aeroplane crossing the threshold at fifty feet is OVER the runway and
    not on it. Counting him would refuse a take-off to everybody underneath an
    approach."""

    def _at(self, r, in_air):
        lat, lon = centre(r)
        return [{"label": "Shooter", "lat": lat, "lon": lon, "in_air": in_air}]

    def test_a_man_on_the_ground_is_reported(self):
        self.assertEqual(who_is_on(BATUMI, self._at(BATUMI, False)), ["Shooter"])

    def test_one_flying_over_it_is_not(self):
        self.assertEqual(who_is_on(BATUMI, self._at(BATUMI, True)), [])

    def test_and_NULL_is_not_evidence_he_is_down(self):
        """The sim's third state -- nobody has asked. Reading it as "on the
        ground" is what told a parked Mustang it was flying, one module over."""
        self.assertEqual(who_is_on(BATUMI, self._at(BATUMI, None)), [])

    def test_a_contact_with_no_position_is_skipped(self):
        self.assertEqual(who_is_on(BATUMI, [{"label": "X", "in_air": False}]), [])


if __name__ == "__main__":
    unittest.main()
