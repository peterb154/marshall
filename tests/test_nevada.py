"""A second map, and whether any of this was ever about the Caucasus.

    "How well do you think this system is going to transport to a totally
     different map and field?"

Every number in `core/nevada.py` comes from the sim's own Beacons.lua and
Radio.lua, cross-checked against the published plate. The two agree, which is
the useful part: DCS models Nellis Tower on 132.550 and that IS the real Tower
frequency, and the localiser antenna bearings reproduce the painted runway
numbers once you remember the antenna points back up the approach.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marshall.core import nevada as N
from marshall.core import route as R


class TestTheFieldsAgreeWithThePlate(unittest.TestCase):

    def test_elevations(self):
        """Nellis is a mile above Batumi and Tonopah three. Nothing in this
        system had ever been flown anywhere but sea level."""
        self.assertEqual(N.NELLIS_FIELD.elevation_ft, 1869)
        self.assertEqual(N.TONOPAH_FIELD.elevation_ft, 5550)

    def test_variation_is_per_field_and_differs(self):
        """12E at Nellis, 16E at Tonopah -- four degrees apart on one map. A
        single theatre-wide MAGVAR was always going to be wrong somewhere."""
        self.assertEqual(N.NELLIS_FIELD.variation(), 12.0)
        self.assertEqual(N.TONOPAH_FIELD.variation(), 16.0)

    def test_a_caucasus_field_still_falls_back_to_the_theatre(self):
        from marshall.core.units import MAGVAR
        self.assertEqual(R.BATUMI_FIELD.variation(), MAGVAR)

    def test_the_localiser_bearing_reproduces_the_published_course(self):
        """The antenna sits beyond the stop end and radiates back up the
        approach, so its bearing is the RECIPROCAL of the course flown. Getting
        that backwards would put every ILS on its opposite end.

        THE COURSE, NOT THE DESIGNATOR -- and the first draft of this test
        asserted the designator, which is the derivation this codebase exists to
        warn against. 157 true at 16 east is 141 magnetic, which rounds to 14 on
        a runway painted 15. The arithmetic was right and the rule was wrong.
        """
        for profile, antenna_true, course_mag in ((N.NELLIS_ILS, 40.11, 209),
                                                  (N.TONOPAH_ILS, 337.08, 141)):
            with self.subTest(runway=profile.runway):
                course_true = (antenna_true + 180) % 360
                self.assertAlmostEqual(profile.final_crs_true_measured,
                                       course_true, places=1)
                mag = (course_true - profile.magvar_deg) % 360
                self.assertAlmostEqual(mag, course_mag, delta=1.0)
                self.assertEqual(profile.final_crs, course_mag)


class TestTheEndsPairIsInTheRightOrder(unittest.TestCase):
    """`ends[0]` is the end whose heading is `runway`. Written the other way
    round, Nellis named runway 03 with the wind from 210 -- the downwind end of
    its own ILS runway, which is the fault that put a Kobuleti departure on 25
    in a 090 wind."""

    def test_every_field_names_its_into_wind_end(self):
        for f in (*N.NEVADA_FIELDS, R.BATUMI_FIELD, R.KOBULETI_FIELD):
            with self.subTest(field=f.name):
                self.assertEqual(f.runway_in_use(f.runway), f.ends[0])
                self.assertEqual(f.runway_in_use((f.runway + 180) % 360),
                                 f.ends[1])

    def test_a_designator_is_not_the_rounded_heading(self):
        """Tonopah is painted 15/33 and its heading is 141 -- which rounds to
        14. The same trap as Batumi's 124 rounding to 12 on a strip painted 13,
        proving itself on a second map."""
        self.assertEqual(round(N.TONOPAH_FIELD.runway / 10), 14)
        self.assertEqual(N.TONOPAH_FIELD.ends[0], 15)


class TestTheLadderTransports(unittest.TestCase):

    def test_the_card_is_in_ladder_order_on_a_map_with_no_ladder(self):
        """`PRESET_LADDER` names Caucasus stations, so every Nellis controller
        fell into the leftovers and the card came out in whatever order the list
        happened to be built in -- the same inaudibility as a dropped rung,
        reached from the other side."""
        from marshall.mission.build import channels_for
        card = [hz for _, hz in channels_for(N.NELLIS_ILS)]
        self.assertEqual(card[:5], [120.900, 121.800, 132.550, 135.100, 118.125])

    def test_the_caucasus_card_is_unchanged(self):
        from marshall.mission.build import channels_for
        card = [hz for _, hz in channels_for(R.BATUMI_ASR)]
        self.assertEqual(card[:4], [125.1, 121.8, 133.0, 123.3])

    def test_every_station_knows_which_field_it_is_at(self):
        """The lesson the second aerodrome taught, on a second map: a role is
        only unique within an aerodrome."""
        for s in N.NEVADA_STATIONS:
            with self.subTest(station=s.name):
                self.assertIn(s.field, ("Nellis", "Tonopah"))

    def test_a_role_resolves_to_its_own_field(self):
        for field, want in (("Nellis", "Nellis Tower"),
                            ("Tonopah", "Silverbow Tower")):
            with self.subTest(field=field):
                got = N.NELLIS_ILS.station_for("tower", field=field)
                self.assertEqual(got.name, want)


class TestWhatIsHonestlyMissing(unittest.TestCase):
    """Stated as a test so it cannot be quietly forgotten."""

    def test_the_vectoring_altitudes_are_not_surveyed(self):
        """Batumi's MVA cells were surveyed out of the sim over a polar grid.
        Nevada has none yet, and Batumi's numbers over Nevada would be fiction
        -- the field alone is a mile up. Empty means `mva_for` falls back to the
        published MSA, which is the safe direction to be wrong in."""
        for f in N.NEVADA_FIELDS:
            with self.subTest(field=f.name):
                self.assertEqual(f.mva_cells, [], "survey done -- update this")

    def test_grid_convergence_is_not_measured_either(self):
        for p in (N.NELLIS_ILS, N.TONOPAH_ILS):
            with self.subTest(approach=p.chart_name):
                self.assertEqual(p.grid_convergence_deg, 0.0)


if __name__ == "__main__":
    unittest.main()
