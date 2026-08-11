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

    def test_every_aerodrome_station_knows_which_field_it_is_at(self):
        """The lesson the second aerodrome taught, on a second map: a role is
        only unique within an aerodrome.

        CENTER IS THE EXCEPTION AND IT IS NOT A LOOPHOLE. Approach and Tower
        belong to an aerodrome; a Center owns a REGION and hands you between
        aerodromes, so there is one for the theatre and it has no field. Giving
        it one would make `station_for("center", field=...)` answer for a
        controller who does not belong to that airport -- which is the exact
        failure the field argument was added to prevent, arrived at backwards.
        """
        for s in N.NEVADA_STATIONS:
            with self.subTest(station=s.name):
                if s.role == "center":
                    self.assertEqual(s.field, "", "a Center owns a region")
                    continue
                self.assertIn(s.field, ("Nellis", "Tonopah"))

    def test_a_role_resolves_to_its_own_field(self):
        for field, want in (("Nellis", "Nellis Tower"),
                            ("Tonopah", "Silverbow Tower")):
            with self.subTest(field=field):
                got = N.NELLIS_ILS.station_for("tower", field=field)
                self.assertEqual(got.name, want)


class TestTheGroundWasActuallyMeasured(unittest.TestCase):
    """Surveyed 10 August with `land.getHeight` over a polar grid -- the same
    heightmap the aeroplane hits -- and the numbers are the argument for having
    done it rather than borrowing Batumi's."""

    def test_both_fields_have_a_full_grid(self):
        for f in N.NEVADA_FIELDS:
            with self.subTest(field=f.name):
                self.assertEqual(len(f.mva_cells), 48)   # 12 spokes x 4 rings

    def test_no_cell_is_below_the_ground_it_covers(self):
        """A minimum vectoring altitude that does not clear the terrain is
        worse than none: it is an instruction to descend into it."""
        for f in N.NEVADA_FIELDS:
            for lo, hi, rng, alt in f.mva_cells:
                with self.subTest(field=f.name, sector=(lo, hi), nm=rng):
                    self.assertGreater(alt, f.elevation_ft)

    def test_tonopah_has_no_low_ground_at_all(self):
        """The ramp is at 5,550 ft and the lowest cell within twenty-five miles
        is 6,500. A controller there manoeuvres above Batumi's highest terrain
        all the time, which is exactly why borrowed cells would have been
        fiction rather than merely imprecise."""
        self.assertGreaterEqual(min(c[3] for c in N.TONOPAH_FIELD.mva_cells),
                                6500)

    def test_nellis_varies_hugely_by_bearing(self):
        """2,000 ft under the approach, 9,416 ft twenty-five miles north-west.
        One number for the whole terminal area is either useless or lethal
        depending which way he is pointing."""
        f = N.NELLIS_FIELD
        self.assertLess(f.mva_for(180, 5), f.mva_for(330, 25) - 5000)

    def test_grid_convergence_was_measured_at_each_field(self):
        for f in N.NEVADA_FIELDS:
            with self.subTest(field=f.name):
                self.assertNotEqual(f.grid_convergence_deg, 0.0)

    def test_the_two_measurements_agree_on_one_central_meridian(self):
        """The cross-check that makes them trustworthy rather than merely
        produced. Convergence on a transverse Mercator is
        (lambda - lambda0) * sin(phi), so each field implies a central meridian
        -- and two fields a hundred and twenty miles apart both give -117.

        Batumi's single recorded value never had this check available."""
        import math
        for f, lat, lon in ((N.NELLIS_FIELD, 36.2352, -115.0330),
                            (N.TONOPAH_FIELD, 37.7979, -116.7803)):
            with self.subTest(field=f.name):
                lam0 = lon - f.grid_convergence_deg / math.sin(math.radians(lat))
                self.assertAlmostEqual(lam0, -117.0, delta=0.05)


class TestWhatIsHonestlyStillMissing(unittest.TestCase):
    """Stated as a test so it cannot be quietly forgotten."""

    def test_only_one_approach_per_field_is_modelled(self):
        """Tonopah has an ILS to BOTH ends in the sim -- I-RVP to 15 and I-UVV
        to 33 -- and only 15 is built. SIDs and STARs are not modelled at all."""
        self.assertEqual(N.TONOPAH_ILS.runway, "15")


if __name__ == "__main__":
    unittest.main()


class TestTheKneeboardTakesACardNotATheatre(unittest.TestCase):
    """Seven of nine pages took a `profile` argument and then read the theatre
    out of module constants anyway, so the parameter was decoration -- which is
    why twenty-four of the twenty-nine surviving Caucasus references in this
    system are kneeboard prose."""

    def comms(self, theatre):
        import os
        from marshall.kneeboard import card, comms
        os.environ["MARSHALL_THEATRE"] = theatre
        try:
            return comms.build(card.current())
        finally:
            os.environ.pop("MARSHALL_THEATRE", None)

    def test_the_nevada_card_has_nevada_frequencies_and_no_others(self):
        from marshall.core import route as R
        said = self.comms("nevada")
        self.assertIn("120.900", said)
        self.assertIn("Silverbow Approach", said)
        for s in R.STATIONS:
            with self.subTest(stranger=s.name):
                self.assertNotIn(s.name, said)

    def test_the_caucasus_card_is_unchanged(self):
        said = self.comms("caucasus")
        self.assertIn("Kobuleti Clearance", said)
        self.assertIn("Batumi", said)
        self.assertNotIn("Nellis", said)

    def test_the_headings_follow_the_theatre(self):
        """A page whose DATA moves and whose PROSE does not is worse than one
        that fails: correct frequencies under the wrong airport's title."""
        self.assertIn("<title>Comms &amp; Tonopah", self.comms("nevada"))
        self.assertIn("<title>Comms &amp; Batumi", self.comms("caucasus"))

    def test_the_ladder_is_the_cards_own_station_order(self):
        """This intersected `route.PRESET_LADDER`, which names Caucasus
        stations, so a Nevada card came out EMPTY -- a comms page with no
        frequencies at all."""
        import re
        rows = re.findall(r"<td class='ch'>(\d+)</td>", self.comms("nevada"))
        # NINE. Eight aerodrome positions plus Los Angeles Center, which a pilot
        # leaving Nellis for the range needs a button for -- without it the
        # ladder simply stopped at Departure and he stayed there. [#110]
        self.assertEqual(len(rows), 9)

    def test_the_arrival_fields_approach_comes_before_its_tower(self):
        """The order the buttons are pressed coming home. Written tower-first,
        the recovery controller sat below the man who takes you at four miles."""
        said = self.comms("nevada")
        self.assertLess(said.index("Silverbow Approach"),
                        said.index("Silverbow Tower"))


class TestTheHoldingStackIsNotAWarbirdsCeiling(unittest.TestCase):
    """`hold_top_ft` defaults to 10,000 -- "P-51: oxygen, not airspace" -- which
    is right for a Mustang and meaningless for an F-16 over Nevada."""

    def test_every_approach_can_actually_hold_somebody(self):
        """`stack_ft` is `range(base, top + 1)`, so a base above the ceiling is
        an EMPTY list: a controller with no level to give and `_free_slot`
        returning None to the first arrival. Tonopah's base is 12,000."""
        for p in (N.NELLIS_ILS, N.TONOPAH_ILS, R.BATUMI_ASR, R.KOBULETI_ILS):
            with self.subTest(approach=p.chart_name[:30]):
                self.assertTrue(p.stack_ft, "nowhere to hold anybody")

    def test_the_stack_clears_the_ground_it_sits_over(self):
        """Nellis's own survey reaches 10,500 ft north-west, which is above the
        default ceiling. A holding level below the terrain is not a hold."""
        for p, f in ((N.NELLIS_ILS, N.NELLIS_FIELD),
                     (N.TONOPAH_ILS, N.TONOPAH_FIELD)):
            with self.subTest(field=f.name):
                self.assertGreaterEqual(max(p.stack_ft),
                                        max(c[3] for c in f.mva_cells))
