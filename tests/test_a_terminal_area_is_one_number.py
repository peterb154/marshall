"""How far a terminal area reaches has ONE author, and the ladder is not it.

`handoff.CENTER_NM` imports `airspace.TERMINAL_NM` and says why:

    "AND IT IS THE SAME NUMBER AS THE EDGE OF APPROACH'S VOLUME, so it is
     imported rather than restated ... holding them separately is one edit away
     from a ladder that hands a man over at twenty-five miles into airspace
     that stops at twenty."

The comment is right and the code stopped satisfying it, because the halving
was added later and inside `sectors_for`:

    reach = min(TERMINAL_NM, nearest_other_field_nm / 2)

Kobuleti and Batumi are 22.6 nm apart, so each area is 11.3 -- and a constant
imported from a module is not the function that module uses. The ladder had the
CAP while the map drew the boundary. Measured on the live sortie: a rule firing
at 25 over a volume ending at 11.3.

`terminal_reach_nm` exists so there is one place to ask. This file checks that
the number is derived rather than assumed, on whatever map is loaded.

WHAT THIS FILE DELIBERATELY DOES NOT DO is make the ladder follow the volume.
That was tried and is wrong in the current geometry -- see the last class, which
records the arithmetic so the next person does not have to rediscover it. [#130]
"""

from __future__ import annotations

import unittest

from marshall.core import airspace as A
from marshall.core import theatre as T
from tests import theatre as TH


def fields():
    got = list(T.fields_now())
    if len(got) < 2:
        raise unittest.SkipTest(f"{TH.name()} works one aerodrome; there is no "
                                "neighbour to halve to")
    return got


class TestTheReachIsDerivedNotAssumed(unittest.TestCase):

    def test_two_close_fields_do_not_each_own_the_cap(self):
        got = fields()
        for f in got:
            with self.subTest(f.name):
                reach = A.terminal_reach_nm(f, [o for o in got if o is not f])
                self.assertLessEqual(reach, A.TERMINAL_NM)

    def test_the_areas_meet_and_do_not_overlap(self):
        """The halving's whole purpose, asserted rather than assumed. Two
        fields d apart get d/2 each, so the circles touch."""
        a, b = fields()[:2]
        d = A._nm_between(a, b)
        ra = A.terminal_reach_nm(a, [b])
        rb = A.terminal_reach_nm(b, [a])
        self.assertAlmostEqual(ra + rb, min(d, 2 * A.TERMINAL_NM), places=3)

    def test_a_field_alone_gets_the_cap(self):
        """Not a degenerate case -- it is the single-aerodrome map, and a
        reach that collapsed to zero there would hand every aeroplane over the
        instant it left the ground."""
        a = fields()[0]
        self.assertEqual(A.terminal_reach_nm(a, []), A.TERMINAL_NM)

    def test_the_map_uses_this_function_rather_than_its_own_copy(self):
        """`sectors_for` had the three lines inline, which is how the ladder
        came to import a constant believing it had imported the boundary."""
        import inspect
        src = inspect.getsource(A.sectors_for)
        self.assertIn("terminal_reach_nm(f, others)", src)
        self.assertNotIn("nearest / 2.0", src)

    def test_the_published_sector_carries_the_derived_reach(self):
        """End to end: what the function says and what the map publishes are
        the same number, which is the only claim that matters to a caller."""
        got = fields()
        secs = A.sectors_for(got, list(T.stations_now()))
        for f in got:
            want = A.terminal_reach_nm(f, [o for o in got if o is not f])
            row = next((s for s in secs
                        if s["field"] == f.name and s["role"] == "approach"),
                       None)
            if row is None:
                continue          # a field with no terminal seat publishes none
            with self.subTest(f.name):
                self.assertAlmostEqual(row["radius_nm"], want, places=3)


class TestTheVolumeDoesNotContainItsOwnApproach(unittest.TestCase):
    """The arithmetic that stops #130 being fixed by aligning the two numbers.

    The obvious repair for "the ladder says 25 and the map says 11" is to make
    the ladder read the map. It was tried, on 14 August, and it is wrong in
    this geometry -- because the map is the half that is wrong:

        Batumi terminal area   11.3 nm
        batumi-ils-13 outer hold at KOBULETI, which is  22.6 nm out

    The procedure begins at DOUBLE the radius of the airspace that owns it. So
    `Rule("center", "approach", "inbound_within", ...)` reading the derived
    reach would keep an arrival on Center until eleven miles -- inside the
    final approach, later than the rule that #51 was filed to fix, and for a
    man flying the approach exactly as published.

    #139 is that fix: a terminal area derived from the procedure it serves,
    which needs fixes that carry lat/lon, which is #137. So the chain is
    #137 -> #139 -> #130 and aligning the constants first would be a
    regression wearing the shape of a cleanup.

    This test fails -- and should be deleted -- on the day #139 lands.
    """

    def test_the_approach_reaches_outside_the_area_that_owns_it(self):
        got = fields()
        approaches = T.approaches_now()
        outside = []
        for key, p in approaches.items():
            fld = getattr(getattr(p, "aerodrome", None), "name", "")
            f = next((x for x in got if x.name.lower() == fld.lower()), None)
            if f is None:
                continue
            reach = A.terminal_reach_nm(f, [o for o in got if o is not f])
            hold = getattr(p, "outer_hold", None) or getattr(p, "iaf", None)
            if hold is None or not hasattr(hold, "lat"):
                continue
            from marshall.core import geo
            nm, _ = geo.range_bearing_true((f.lat, f.lon), hold.lat, hold.lon)
            if nm > reach:
                outside.append((key, round(nm, 1), round(reach, 1)))
        self.assertTrue(
            outside,
            "every published approach now fits inside its own terminal area -- "
            "#139 has landed, so delete this class and align handoff.CENTER_NM "
            "with airspace.terminal_reach_nm as #130 asks")


if __name__ == "__main__":
    unittest.main()
