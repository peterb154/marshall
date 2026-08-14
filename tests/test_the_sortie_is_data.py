"""The mission's own turning points were Python, and that is what published them.

    "There are fixes in core/fixes.py??? Shouldn't all fixes be data in the
     database?"
    "we deleted the domino flight plan that had feet wet... where on earth did
     that come from. It shouldn't be in the database from a flight plan as a
     private fix and it's definitely not a public fix."

Both right, and the second follows from the first. FEET WET, INGRESS,
TSUTSNVATI, EGRESS and REHEARSAL were module-level `Fix` objects in
`core/fixes.py`, with the route, its altitudes and the defended fields as lists
beside them. Deleting the Domino plan could never have removed FEET WET,
because nothing about the plan created it.

WHAT MADE THEM "PRIVATE" WAS WHICH PYTHON MODULE THEY SAT IN, which is not a
property of a name -- it is an accident of where somebody typed it. Nothing
enforced it and nothing could: `theatre.fixes` was once built by scraping every
module-level `Fix` out of `route.py`, so the distinction evaporated the moment
anybody asked for the catalogue.

They are `[sortie]` in `config/theatres/<map>.toml` now, in a section of their
own. `[[fix]]` is what the MAP publishes -- citable, true whoever is flying.
`[sortie]` goes home with the mission that flies it. The separation is a thing
the file STATES rather than a thing a reader infers. [#137]
"""

from __future__ import annotations

import unittest

from marshall.core import catalogue as C
from marshall.core import fixes as F
from marshall.core import route as R
from marshall.core import theatre as T
from tests import theatre as TH

PRIVATE = ("FEET WET", "INGRESS", "TSUTSNVATI", "EGRESS", "REHEARSAL")


def sortie_or_skip():
    got = C.sortie(TH.name())
    if got is None:
        raise unittest.SkipTest(f"{TH.name()} declares no [sortie]")
    return got


class TestTheRouteComesOffTheFile(unittest.TestCase):

    def test_the_map_declares_one(self):
        s = sortie_or_skip()
        self.assertTrue(s.route, "a [sortie] with no route")
        self.assertTrue(s.label, "an unnamed mission is one nobody can cite")

    def test_the_numbered_points_are_built_from_it(self):
        s = sortie_or_skip()
        got = [f.name for _, f in T.sortie_route()]
        self.assertEqual(got, list(s.route))

    def test_the_numbering_starts_at_one(self):
        """"Distance to waypoint three" is how a pilot asks, and he counts from
        one. An off-by-one here is a controller confidently naming the wrong
        place."""
        sortie_or_skip()
        got = T.sortie_route()
        self.assertEqual([n for n, _ in got], list(range(1, len(got) + 1)))

    def test_altitudes_are_per_LEG_so_one_shorter(self):
        s = sortie_or_skip()
        self.assertEqual(len(s.alt_ft), len(s.route) - 1)

    def test_a_point_used_twice_is_one_definition(self):
        """BATUMI opens and closes the strike. Naming points rather than
        embedding them is what makes that one row and two visits."""
        s = sortie_or_skip()
        if len(set(s.route)) == len(s.route):
            self.skipTest("this mission visits nothing twice")
        seen = [f for _, f in T.sortie_route()]
        names = [f.name for f in seen]
        twice = next(n for n in names if names.count(n) > 1)
        same = [f for f in seen if f.name == twice]
        self.assertIs(same[0], same[-1],
                      "two visits to one point produced two objects, which is "
                      "how a route comes to disagree with itself")


class TestThePrivatePointsAreNotPublished(unittest.TestCase):
    """The pilot's complaint, as a check.

    A private point must not appear in the map's published catalogue. That is
    the property that was impossible to state while the only difference between
    the two was a Python module.
    """

    def test_none_of_them_is_a_published_fix(self):
        sortie_or_skip()
        published = {f.name.upper() for f in T.fixes_now()}
        for name in PRIVATE:
            with self.subTest(name):
                self.assertNotIn(name, published,
                                 f"{name} is being published as though an AIP "
                                 f"carried it")

    def test_and_the_catalogue_does_not_read_python_at_all(self):
        """`published_fixes` reads the file. If it ever scrapes a module again
        the distinction dies silently, which is exactly how it died before.

        THE BODY, NOT THE DOCSTRING. The first version searched the whole
        source and tripped on the docstring, which QUOTES the old scraping code
        in order to explain what not to do -- so the text has to contain the
        thing it forbids. That is the same reading error twice in one session
        and the same one as the bug: a string matched without regard to which
        half of the file it was in.
        """
        import ast
        import inspect
        fn = ast.parse(inspect.getsource(C.published_fixes)).body[0]
        body = ast.unparse(ast.Module(
            body=[n for n in fn.body if not (isinstance(n, ast.Expr)
                  and isinstance(n.value, ast.Constant))], type_ignores=[]))
        self.assertNotIn("vars(", body, "the catalogue is scraping a module")
        self.assertIn(".fix", body, "the catalogue is not reading the file's "
                                    "published section")

    def test_the_python_module_no_longer_defines_them(self):
        """The headline complaint, asserted directly. `core/fixes.py` keeps the
        TYPE and the two functions that reason about a route; the route itself
        is data."""
        for name in ("FEET_WET", "INGRESS", "HOMEBOUND", "TARGET_AREA",
                     "AIR_START", "SORTIE", "SORTIE_LEGS", "SORTIE_ALT_FT",
                     "DEFENDED"):
            with self.subTest(name):
                self.assertFalse(hasattr(F, name),
                                 f"core.fixes still defines {name}")

    def test_but_they_are_still_reachable_under_their_old_names(self):
        """`route` is the module every caller imports and is a READER over the
        files. Moving data must not mean editing three hundred call sites."""
        sortie_or_skip()
        for name in ("FEET_WET", "INGRESS", "HOMEBOUND", "TARGET_AREA",
                     "AIR_START"):
            with self.subTest(name):
                got = getattr(R, name)
                self.assertIsNotNone(got, f"R.{name} resolves to nothing")
                self.assertTrue(got.name)


class TestAPointMayBeDeclaredAndNeverFlown(unittest.TestCase):
    """REHEARSAL is the case that broke the first version of the lookup.

    It is a `[[sortie.point]]` and appears nowhere in `route`: the test flights
    spawn there airborne. A search of the ROUTE returned None for it and the
    mission builder lost its air-start -- silently, because `getattr` on a
    missing point is a legitimate None everywhere else.
    """

    def test_it_is_not_on_the_route(self):
        s = sortie_or_skip()
        if "REHEARSAL" not in {p.name for p in s.point}:
            self.skipTest("this map declares no rehearsal point")
        self.assertNotIn("REHEARSAL", [x.upper() for x in s.route])

    def test_and_is_found_anyway(self):
        s = sortie_or_skip()
        if "REHEARSAL" not in {p.name for p in s.point}:
            self.skipTest("this map declares no rehearsal point")
        got = T.sortie_point("REHEARSAL")
        self.assertIsNotNone(got, "a declared point that is not flown was lost")
        self.assertEqual(got.name, "REHEARSAL")

    def test_a_borrowed_public_name_falls_through_to_the_map(self):
        """The route uses BATUMI, which is a published aerodrome and not a
        point the mission defines. Asking for it must give the map's row rather
        than nothing."""
        sortie_or_skip()
        pub = next(iter(T.fixes_now()), None)
        if pub is None:
            self.skipTest("this map publishes no fixes")
        self.assertIsNotNone(T.sortie_point(pub.name))


class TestARouteThatNamesNothingIsRefused(unittest.TestCase):
    """Not skipped, because skipping renumbers everything after it.

    A route point nothing defines would shift every later steerpoint by one, so
    "waypoint four" would mean a different place than the chart shows -- and
    nothing would say so. That is the failure this project keeps finding: an
    absence read as an answer.
    """

    def test_it_raises_naming_the_point(self):
        import types
        real = C.sortie
        broken = types.SimpleNamespace(
            route=["BATUMI", "NOWHERE AT ALL"], alt_ft=[2000],
            point=[], defended=[], label="broken")
        C.sortie = lambda theatre="": broken
        try:
            with self.assertRaises(KeyError) as caught:
                T.sortie_route()
            self.assertIn("NOWHERE AT ALL", str(caught.exception))
        finally:
            C.sortie = real

    def test_and_the_bridge_still_comes_up(self):
        """A malformed mission must not stop a bridge starting: the ladder, the
        approaches and the whole ground half do not touch the strike route. It
        is named on the way past rather than swallowed."""
        import types
        real = C.sortie
        C.sortie = lambda theatre="": types.SimpleNamespace(
            route=["NOWHERE AT ALL"], alt_ft=[], point=[], defended=[],
            label="broken")
        try:
            self.assertEqual(T._sortie_wp(), ())
        finally:
            C.sortie = real


if __name__ == "__main__":
    unittest.main()
