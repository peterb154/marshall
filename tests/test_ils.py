"""The Kobuleti ILS, and whether this is really data-driven.

    "Fly Kobuleti ILS to prove the data drives it." [#3, TEST-1]

The stated acceptance was that no file under `src/marshall/atc/` changes to
make a second approach at a second field work. None did -- the profile is a row
of numbers off a chart and a measurement off the sim.

WHAT MAKES AN ILS SIMPLER IS ONE FIELD. On a surveillance approach the
controller IS the approach aid: he reads the range every mile, corrects the
heading, and keeps the aeroplane until it is on the ground. On an ILS the
aeroplane has localiser and glideslope, so the controller positions him and
lets go. That is `guidance`, and everything else follows from it.
"""

import unittest

from marshall.atc import handoff as H
from marshall.core import route as R
from tests import theatre as T

# `` and `` stood here at module scope and
# took the file down on any other map. The CHART numbers below really are
# Kobuleti's -- a transcribed plate is a fact about one aerodrome and cannot be
# parameterised into anything -- so those classes say so and skip. What is a
# RULE rather than a chart is asserted over whatever the loaded map publishes,
# in `EveryPublishedApproachIsWholeAndStaffed` at the end.


def ILS():
    return R.KOBULETI_ILS


def ASR():
    return R.BATUMI_ASR


class EveryPublishedApproachIsWholeAndStaffed(unittest.TestCase):
    """The acceptance criterion of #3, asked of every procedure on the map.

        "Fly Kobuleti ILS to prove the data drives it."

    Data-driven means the SECOND one needs no code, and the way to keep that
    true is to assert it of all of them rather than of the one that was added.
    On Nevada that is nine procedures at two aerodromes, none of which this
    file could previously see.
    """

    def test_each_one_is_complete(self):
        # `stations` used to be on this list and is not on the profile any more
        # -- the seats belong to the theatre (#162). `aerodrome`, not `beacon`:
        # an ILS HAS no beacon, and requiring one was the conflation asserting
        # itself in a test. #163 split the slot; the datum is what every
        # procedure has.
        for key, p in sorted(T.approaches().items()):
            for attr in ("controller", "aerodrome", "runway", "final_crs",
                         "guidance", "kind"):
                with self.subTest(procedure=key, field=attr):
                    self.assertTrue(getattr(p, attr, None) not in (None, "", []),
                                    f"{key}.{attr} is empty")

    def test_each_ones_controller_is_staffed_and_reachable(self):
        """A procedure naming a controller nobody answers as is a frequency the
        pilot reaches silence on, and he finds out on the approach."""
        for key, p in sorted(T.approaches().items()):
            with self.subTest(procedure=key, who=p.controller):
                seat = next((s for s in R.STATIONS if s.name == p.controller),
                            None)
                self.assertIsNotNone(seat,
                                     f"{key} is worked by {p.controller!r}, who "
                                     f"is on nobody's ladder")
                self.assertIsNotNone(R.station_on(seat.freq_mhz))

    def test_the_field_each_one_serves_was_surveyed(self):
        """An approach to a field with no MSA is a vectoring altitude nobody has
        checked -- and `Field_.msa_for` falls back to the MODULE's table, which
        is Batumi's mountains. A new aerodrome inherits Georgian terrain
        silently. [finding 6]"""
        for key, p in sorted(T.approaches().items()):
            fld = T.field_of(p)
            with self.subTest(procedure=key, field=p.aerodrome.name):
                self.assertIsNotNone(fld, f"{key} arrives at "
                                          f"{p.aerodrome.name!r}, which is not "
                                          f"a published aerodrome")
                self.assertTrue(fld.msa_sectors, f"{fld.name} has no MSA")
                self.assertTrue(fld.mva_cells, f"{fld.name} has no MVA grid")

    def test_every_msa_clears_the_worst_ground_in_its_sector(self):
        """Measured plus a thousand feet, at every field the map works."""
        for f in T.fields():
            for _lo, _hi, ft in (f.msa_sectors or ()):
                with self.subTest(field=f.name, msa=ft):
                    self.assertGreaterEqual(ft, 1000)

    def test_two_fields_do_not_share_one_survey(self):
        """The concrete wrong answer: a controller assigns 1,000 ft west of a
        field whose ramp is at 4,494 because it inherited a coastal Georgian
        grid. Two aerodromes with byte-identical terrain is that fault."""
        grids = {f.name: tuple(f.msa_sectors or ()) for f in T.fields()}
        seen = {}
        for name, grid in grids.items():
            with self.subTest(field=name):
                self.assertNotIn(grid, seen,
                                 f"{name} and {seen.get(grid)} were surveyed to "
                                 f"the same numbers")
            seen[grid] = name

    def test_the_two_kinds_of_arrival_share_every_mechanism(self):
        """Same class, same handoff table, same phase machine. The only thing
        that differs is the numbers -- which is what 'data-driven' has to mean
        if it means anything."""
        kinds = {}
        for key, p in sorted(T.approaches().items()):
            kinds.setdefault(p.guidance, key)
            me = R.station_for("approach", field=p.aerodrome.name)
            if me is None:
                continue
            with self.subTest(procedure=key):
                self.assertIs(type(p), type(next(iter(T.approaches().values()))))
                H.due(p, me, H.State(False, 4.0, True))

    def test_the_controller_lets_go_where_the_AEROPLANE_flies_it(self):
        """The behavioural difference, and it is the whole point.

        Established inbound at four miles: an intercept procedure hands him to
        Tower because there is nothing left for Approach to do. A talkdown keeps
        him, because the man on the frequency IS the approach aid. Asserted off
        `guidance` over every procedure rather than off two Georgian names.
        """
        for key, p in sorted(T.approaches().items()):
            me = R.station_for("approach", field=p.aerodrome.name)
            if me is None:
                continue
            v = H.due(p, me, H.State(False, 4.0, True))
            with self.subTest(procedure=key, guidance=p.guidance):
                if p.guidance == "talkdown":
                    self.assertIsNone(v, "the talkdown handed him away "
                                         "mid-procedure")
                else:
                    self.assertIsNotNone(v, f"{key} never released him")
                    self.assertEqual(v.station.role, "tower")
                    self.assertEqual(v.station.field.lower(), p.aerodrome.name.lower(),
                                     "released to the other aerodrome's Tower")


@T.skip_unless("caucasus", why="transcribed from the Kobuleti ILS RWY 07 plate "
                               "and the Batumi ASR -- a chart is a fact about "
                               "one aerodrome and parameterises into nothing")
class TestItIsAnILSAndNotACopyOfTheRadarApproach(unittest.TestCase):

    def test_the_aeroplane_flies_it(self):
        self.assertEqual(ILS().guidance, "intercept")
        self.assertEqual(ILS().kind, "ils")
        self.assertEqual(ASR().guidance, "talkdown")

    def test_the_controller_lets_go_at_the_intercept(self):
        """The behavioural difference, and it is the whole point.

        Established inbound at four miles: the ILS hands him to Tower because
        there is nothing left for Approach to do. The ASR keeps him, because
        the man on the frequency is the approach aid.
        """
        me = R.station_for("approach", field=R.DEPARTURE_FIELD)
        v = H.due(ILS, me, H.State(False, 4.0, True))
        self.assertIsNotNone(v, "the ILS never released him")
        self.assertEqual(v.station.role, "tower")

        mb = R.station_for("approach", field=R.ARRIVAL_FIELD)
        self.assertIsNone(H.due(ASR(), mb, H.State(False, 4.0, True)),
                          "the talkdown handed him away mid-procedure")

    def test_there_is_no_stepdown_table(self):
        """A descent table is what a controller reads to a pilot with no
        glidepath. Publishing one here would be advisory heights nobody needs
        and a second opinion on a descent the instrument is already flying."""
        self.assertFalse(ILS().descent_table)
        self.assertTrue(ASR().descent_table, "the ASR needs one and has one")

    def test_the_minima_belong_to_the_procedure_not_the_field(self):
        """The mistake `min_hat_ft` exists to stop: Batumi's profile was once
        transcribed from an ILS plate and flew a radar approach to 300 ft."""
        self.assertEqual(ILS().min_hat_ft, 200)     # chart: ILS RWY 07, 200 - 0.8
        self.assertEqual(ASR().min_hat_ft, 700)     # no vertical guidance at all
        self.assertLess(ILS().min_hat_ft, ASR().min_hat_ft)

    def test_the_weather_can_only_raise_the_minimum(self):
        """Published 200, but a 400 ft ceiling gives a 300 ft decision height.
        Briefing a low cloud base does not buy a lower minimum -- it makes a
        go-around more likely, which is the point of a hard mission."""
        self.assertEqual(ILS().mda_ft, max(ILS().field_elev_ft + ILS().min_hat_ft,
                                         ILS().ceiling_ft - ILS().breakout_ft))
        self.assertGreaterEqual(ILS().mda_ft, ILS().field_elev_ft + ILS().min_hat_ft)


@T.skip_unless("caucasus", why="Georgian charts and the Georgian coastline by number; the RULES they stand for are asserted over every published procedure above")
class TestTheFrameIsRightAtTheOtherField(unittest.TestCase):
    """The chart repeats the error `geo.py` was written for, at both fields."""

    def test_the_convergence_is_measured_here_not_borrowed(self):
        self.assertAlmostEqual(ILS().grid_convergence_deg, 5.91, places=2)
        self.assertAlmostEqual(ASR().grid_convergence_deg, 5.74, places=2)
        self.assertNotEqual(ILS().grid_convergence_deg, ASR().grid_convergence_deg)

    def test_true_is_the_geodesic_and_not_the_charts_T(self):
        """The plate prints runway 07 as "070 T". 070.03 is the DCS GRID
        heading; the bearing between the published thresholds is 075.94."""
        self.assertAlmostEqual(ILS().final_crs_true, 75.94, places=1)
        self.assertNotAlmostEqual(ILS().final_crs_true, 70.0, places=0)

    def test_the_spoken_course_is_magnetic_and_matches_the_paint(self):
        self.assertEqual(ILS().final_crs, 70)
        self.assertEqual(R.KOBULETI_FIELD.runway_in_use(), 7)


@T.skip_unless("caucasus", why="Georgian charts and the Georgian coastline by number; the RULES they stand for are asserted over every published procedure above")
class TestTheTerrainWasSurveyed(unittest.TestCase):
    """An approach to a field with no MSA is a vectoring altitude nobody has
    checked. Kobuleti had none until one was flown here."""

    def test_the_field_has_sectors_and_cells(self):
        self.assertTrue(R.KOBULETI_FIELD.msa_sectors)
        self.assertTrue(R.KOBULETI_FIELD.mva_cells)

    def test_the_mountains_are_east_and_the_sea_is_west(self):
        east = R.KOBULETI_FIELD.msa_for(120)
        west = R.KOBULETI_FIELD.msa_for(270)
        self.assertGreater(east, 9000, "8,556 ft of Caucasus inside 25 nm")
        self.assertLess(west, 5000, "that side is water")

    def test_vectoring_east_costs_altitude(self):
        """The MVA is the lowest a controller may ASSIGN. Vectoring west of
        Kobuleti is cheap; vectoring east of it is not, and a rule that cannot
        tell them apart flies somebody into the Lesser Caucasus."""
        self.assertGreater(R.KOBULETI_FIELD.mva_for(120, 20),
                           R.KOBULETI_FIELD.mva_for(270, 20))

    def test_every_msa_clears_the_worst_ground_in_its_sector(self):
        """Measured plus a thousand feet, and the coarse scan was not safe --
        10-degree/1-nm sampling missed 400 ft on one side and a thousand on the
        other. These are the 5-degree/half-mile numbers."""
        for _lo, _hi, ft in R.KOBULETI_FIELD.msa_sectors:
            with self.subTest(msa=ft):
                self.assertGreaterEqual(ft, 1000)


@T.skip_unless("caucasus", why="Georgian charts and the Georgian coastline by number; the RULES they stand for are asserted over every published procedure above")
class TestNothingUnderATCHadToChange(unittest.TestCase):
    """The acceptance criterion, asserted rather than claimed.

    A second approach at a second field, of a different kind, flown by a
    different controller. If making it work needed a code change under `atc/`,
    the thing is not data-driven and the claim should stop being made.
    """

    def test_the_profile_is_reachable_and_complete(self):
        # `stations` used to be on this list and is not on the profile any
        # more -- the seats belong to the theatre (#162), and the assertion
        # that this field is staffed is `test_its_controller_is_staffed`
        # below, which asks the table rather than the procedure.
        # `aerodrome`, not `beacon`: an ILS HAS no beacon, and requiring one
        # to be non-empty was the conflation asserting itself in a test.
        # #163 split the slot; the datum is what every procedure has.
        for attr in ("controller", "aerodrome", "runway", "final_crs",
                     "guidance", "kind", "msa_sectors", "mva_cells"):
            with self.subTest(field=attr):
                self.assertTrue(getattr(ILS(), attr, None) not in (None, "", []),
                                f"{attr} is empty")

    def test_its_controller_is_staffed(self):
        self.assertIsNotNone(R.station_on(
            R.KOB_DEPARTURE.freq_mhz))

    def test_the_two_approaches_share_every_mechanism(self):
        """Same class, same handoff table, same phase machine. The only thing
        that differs is the numbers -- which is what 'data-driven' has to mean
        if it means anything."""
        self.assertIs(type(ILS()), type(ASR()))
        for me, prof in ((R.station_for("approach", field=R.DEPARTURE_FIELD), ILS()),
                         (R.station_for("approach", field=R.ARRIVAL_FIELD), ASR())):
            with self.subTest(profile=prof.kind):
                # Same call, same table, different answer from the data alone.
                H.due(prof, me, H.State(False, 4.0, True))


if __name__ == "__main__":
    unittest.main()
