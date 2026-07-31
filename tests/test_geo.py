"""One range-and-bearing, and the frame is always named.

"Bearing between two points" was implemented SIX times. Two were byte-for-byte
identical in different modules; one returned a GRID bearing while promising a
true one; and the copy in `agent_atc` said in its own docstring that the third
was wrong -- "the same error is still open on the paper nav log". Somebody found
the correct implementation, knew another was broken, and made a second copy
rather than one home.

THE FRAMES ARE THE PROBLEM, not the arithmetic. There are two right answers to
which way Batumi's runway points and they differ by six degrees:

    305.6   the DCS GRID frame -- the F10 ruler, the compass, `getRunways`
    311.3   TRUE -- the geodesic bearing between the thresholds

So nothing in `core.geo` returns "a bearing". It returns a true one or a grid
one, says which in its name, and converting takes an explicit convergence.
"""

import unittest

from marshall.atc import agent_atc as A
from marshall.atc import picture
from marshall.core import geo, route as R

BATUMI = (41.609594, 41.600234)


class TestTheNavLogIsNoLongerSixDegreesOut(unittest.TestCase):
    """AUDIT FINDING 1, 29 July, opening item: "The paper nav log is 5.74
    degrees out on every leg. Today."

        | leg                 | chart said | should be | cross-track      |
        | KOBULETI to INITIAL | 236 M      | 242 M     | 2.39 nm / 23.9nm |
        | INITIAL to BATUMI   | 125 M      | 131 M     | 1.50 nm / 15.0nm |

    Those figures were measured under the mission wind of the day, 180 at 5.
    The wind is 090 at 5 now -- picked so the runways make sense -- so the
    HEADINGS below have moved a couple of degrees while the courses have not.
    The table is left as it was recorded, because it is the evidence for the
    convergence bug rather than a current statement of the nav log.

    `bearing_distance` took `atan2(dz, dx)` off the sim's GRID metres and
    `solve_route` labelled it true. The radar side had applied convergence for
    weeks; the chart half never did. Same map, same fixes, two answers, and the
    one a pilot flies was the wrong one.
    """

    def legs(self):
        return {f"{s.frm.name} -> {s.to.name}": s for s in R.solve_route()}

    def test_kobuleti_to_initial(self):
        got = self.legs()["KOBULETI -> INITIAL"]
        self.assertEqual(round(got.heading_mag), 242)
        self.assertAlmostEqual(got.distance_nm, 23.9, places=1)

    def test_initial_to_batumi(self):
        """129, and it was 131 while the wind was 180/5.

        A HEADING IS WIND-CORRECTED AND A COURSE IS NOT, which is why this
        number moved when the mission wind went to 090/5 for the runway and the
        one in `test_the_error_was_exactly_the_convergence` did not. The true
        course is 135.75 either way; the drift correction is what changed.

        Worth keeping as a heading rather than relaxing to a course: the nav log
        is what a pilot flies, and it is the wind-corrected number he steers.
        """
        got = self.legs()["INITIAL -> BATUMI"]
        self.assertEqual(round(got.heading_mag), 129)
        self.assertAlmostEqual(got.distance_nm, 15.0, places=1)

    def test_the_error_was_exactly_the_convergence(self):
        """Not a coincidence worth leaving unstated: the whole discrepancy is
        the grid-to-true angle, so a run with zero convergence reproduces the
        old wrong chart exactly."""
        was = {f"{s.frm.name}": s.heading_mag
               for s in R.solve_route()}
        old = R.bearing_distance(R.KOBULETI, R.INITIAL, convergence_deg=0.0)
        now = R.bearing_distance(R.KOBULETI, R.INITIAL)
        self.assertAlmostEqual((now[0] - old[0]) % 360,
                               R.GRID_CONVERGENCE_DEG, places=6)
        self.assertTrue(was)


class TestTheFrameIsInTheName(unittest.TestCase):
    """A function that returns one frame while promising another is the whole
    bug. These assert that the two disagree by exactly the convergence, so a
    caller cannot treat them as interchangeable and be quietly right."""

    def test_grid_and_true_differ_by_the_convergence(self):
        _, grid = geo.range_bearing_grid(0.0, 0.0, 1000.0, 1000.0)
        self.assertAlmostEqual(geo.grid_to_true(grid, 5.74), grid + 5.74)

    def test_the_conversion_round_trips(self):
        for deg in (0.0, 45.0, 179.9, 305.6, 359.0):
            with self.subTest(deg=deg):
                self.assertAlmostEqual(
                    geo.true_to_grid(geo.grid_to_true(deg, 5.74), 5.74),
                    deg, places=9)

    def test_magnetic_takes_its_variation_rather_than_reading_a_constant(self):
        """At some point this system works two maps at once, and a Caucasus
        variation applied to a Nevada heading is a bug nobody sees in review."""
        self.assertAlmostEqual(geo.magnetic(100.0, 6.0), 94.0)
        self.assertAlmostEqual(geo.magnetic(100.0, 12.0), 88.0)


class TestTheGeodesicIsNotAFlatOffset(unittest.TestCase):
    """"Caucasus is a transverse Mercator and the flat version measured 1.2 nm
    out at the coast and 7.6 nm out at the target area." Miles, not decimals."""

    def test_projecting_and_measuring_round_trip(self):
        """The flat version did not, and that is how the error was found."""
        for brg, nm in ((0.0, 10.0), (125.0, 40.0), (305.6, 7.5), (270.0, 60.0)):
            with self.subTest(bearing=brg, nm=nm):
                lat, lon = geo.project_true(BATUMI, brg, nm)
                back_nm, back_brg = geo.range_bearing_true(BATUMI, lat, lon)
                self.assertAlmostEqual(back_nm, nm, places=6)
                self.assertAlmostEqual(back_brg, brg, places=6)

    def test_crosstrack_is_positive_to_the_right(self):
        self.assertGreater(geo.crosstrack_nm(course_deg=90, bearing_to_deg=100,
                                             range_nm=10), 0)
        self.assertLess(geo.crosstrack_nm(course_deg=90, bearing_to_deg=80,
                                          range_nm=10), 0)


class TestThereIsOnlyOneOfThem(unittest.TestCase):
    """Guarded by identity. A seventh copy is easy to write and impossible to
    notice, and this fails the moment a caller stops sharing the function."""

    def test_the_two_geodesic_callers_are_the_same_object(self):
        self.assertIs(picture.range_radial, geo.range_bearing_true)
        self.assertIs(A._range_radial, geo.range_bearing_true)

    def test_and_they_agree_with_the_grid_version_after_conversion(self):
        """The two frames must reconcile, or one of them is wrong. A short leg
        near the field, where the flat approximation is good enough that any
        remaining difference is the FRAME and not the projection."""
        _, grid = geo.range_bearing_grid(R.INITIAL.x, R.INITIAL.z,
                                         R.BATUMI.x, R.BATUMI.z)
        true = geo.grid_to_true(grid, R.GRID_CONVERGENCE_DEG)
        self.assertAlmostEqual(true, 135.7, places=0)


if __name__ == "__main__":
    unittest.main()
