"""How far a terminal area reaches has ONE author, and it is the procedure.

`handoff.CENTER_NM` imports `airspace.TERMINAL_NM` and says why:

    "AND IT IS THE SAME NUMBER AS THE EDGE OF APPROACH'S VOLUME, so it is
     imported rather than restated ... holding them separately is one edit away
     from a ladder that hands a man over at twenty-five miles into airspace
     that stops at twenty."

The comment was right and the code stopped satisfying it, because the halving
was added later and inside `sectors_for`:

    reach = min(TERMINAL_NM, nearest_other_field_nm / 2)

Kobuleti and Batumi are 22.6 nm apart, so each area was 11.3 -- and a constant
imported from a module is not the function that module uses. The ladder had the
CAP while the map drew the boundary.

BOTH HALVES ARE FIXED NOW AND THEY WERE FIXED IN THAT ORDER, which mattered.
`terminal_reach_nm` became the one place to ask (#130's investigation); then the
answer it gave became right (#139). Aligning the ladder to the map FIRST would
have been a regression wearing the shape of a cleanup -- Center holding an
arrival to eleven miles, inside the final -- and the intervening commit says so
with the arithmetic.

The area is derived from the procedures it serves now: the furthest fix any of
this field's approaches uses, plus room to manoeuvre onto it, floored at the
conventional twenty-five. Areas may overlap, because real terminal areas do;
the tie is broken where two volumes are compared, in migration 034, and checked
against the live view by `tools/airspace_check.py`. [#130, #139]
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

    def test_no_area_is_smaller_than_the_conventional_twenty_five(self):
        """`TERMINAL_NM` became the FLOOR when #139 landed. It was the cap, and
        as a cap it produced eleven-mile areas around twenty-two-mile
        approaches."""
        got = fields()
        for f in got:
            with self.subTest(f.name):
                reach = A.terminal_reach_nm(f, [o for o in got if o is not f])
                self.assertGreaterEqual(reach, A.TERMINAL_NM)

    def test_an_area_holds_its_own_procedures(self):
        """The claim #139 is about, in one line."""
        got = fields()
        for f in got:
            with self.subTest(f.name):
                reach = A.terminal_reach_nm(f, [o for o in got if o is not f])
                need = A.procedure_reach_nm(
                    f, list(T.approaches_now().values()))
                self.assertGreaterEqual(reach, need)

    def test_a_field_whose_procedures_cannot_be_LOCATED_keeps_the_default(self):
        """Zero rather than a small number, so an unsurveyed map behaves
        exactly as it did. An area sized from a procedure nobody could place
        would be a figure with no evidence behind it."""
        a = fields()[0]
        self.assertEqual(A.procedure_reach_nm(a, []), 0.0)
        self.assertEqual(A.terminal_reach_nm(a, [], approaches=[]),
                         A.TERMINAL_NM)

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


class TestEveryApproachFitsInsideItsOwnArea(unittest.TestCase):
    """What this file asserted the OPPOSITE of, twelve hours ago.

    The class here was `TestTheVolumeDoesNotContainItsOwnApproach`, written
    when #130 was found to be blocked, and its docstring ended:

        "This test fails -- and should be deleted -- on the day #139 lands."

    It landed, it failed, and this is the replacement. Keeping the shape of the
    old claim would have been the easy thing and the wrong one: a test that
    records a defect is only worth having while the defect is there.

        Batumi     area 27.5 nm    furthest fix KOBULETI at 22.5
        Kobuleti   area 28.8 nm    furthest fix INITIAL  at 23.8
    """

    def test_no_published_approach_starts_outside_its_terminal_area(self):
        from marshall.core import geo
        got = fields()
        outside = []
        for key, p in T.approaches_now().items():
            fld = next((x for x in got if x.name.lower()
                        == getattr(p.aerodrome, "name", "").lower()), None)
            if fld is None or fld.lat is None:
                continue
            reach = A.terminal_reach_nm(fld, [o for o in got if o is not fld])
            for attr in ("outer_hold", "iaf"):
                fix = getattr(p, attr, None)
                if fix is None or getattr(fix, "lat", None) is None:
                    continue
                nm, _ = geo.range_bearing_true((fld.lat, fld.lon),
                                               fix.lat, fix.lon)
                if nm > reach:
                    outside.append(f"{key} {attr} {nm:.1f} nm > {reach:.1f}")
        self.assertEqual(outside, [],
                         "an approach begins outside the airspace that works "
                         "it, so 'he is outside my airspace' will fire on a "
                         "man flying it exactly as published")

    def test_and_every_fix_it_needs_can_be_LOCATED(self):
        """The prerequisite, asserted so that the test above cannot pass by
        being unable to measure anything. Every fix carrying no position is a
        silent exemption."""
        blind = [f.name for f in T.fixes_now() if f.lat is None]
        blind += [f.name for _, f in T.sortie_route() if f.lat is None]
        self.assertEqual(blind, [],
                         "these fixes have no position, so nothing above "
                         "measured them -- run tools/seed_fixes.py")


if __name__ == "__main__":
    unittest.main()
