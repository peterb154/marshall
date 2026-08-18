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
                     "AIR_START",
                     "DEFENDED"):
            with self.subTest(name):
                self.assertFalse(hasattr(F, name),
                                 f"core.fixes still defines {name}")

    def test_but_they_are_still_reachable_under_their_old_names(self):
        """`route` is the module every caller imports and is a READER over the
        files. Moving data must not mean editing three hundred call sites."""
        sortie_or_skip()
        # ONE LEFT. The other four aliased the 1944 strike's turning points
        # and went with the route in #188 -- a dead alias to a mission that no
        # longer exists is how a controller describes somebody else's route to
        # a pilot holding his own. REHEARSAL is not a turning point: it is
        # where a test aeroplane spawns, which is a fact about this map.
        for name in ("AIR_START",):
            with self.subTest(name):
                got = getattr(R, name)
                self.assertIsNotNone(got, f"R.{name} resolves to nothing")
                self.assertTrue(got.name)
        for gone in ("FEET_WET", "INGRESS", "HOMEBOUND", "TARGET_AREA"):
            with self.subTest(gone):
                self.assertIsNone(
                    getattr(R, gone, None),
                    f"R.{gone} is back. It names a point in somebody's flight "
                    f"plan, not a place on the map.")


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
        # NOTHING TO BE ON. #188 removed theatre-level routes outright, so a
        # declared point cannot be on one -- which is this test's claim,
        # arrived at by deletion rather than by discipline.
        self.assertFalse(hasattr(s, "route"))

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




class TestThePublishedFixesHaveOneAuthorToo(unittest.TestCase):
    """The same defect one level up, caught before it cost anything.

    KOBULETI, BATUMI and KUTAISI were module constants in `core/fixes.py` AND
    `[[fix]]` rows in the theatre file, holding identical coordinates. They
    agreed only because nobody had edited one without the other -- which is not
    a property, it is luck, and it is the shape every foundational bug this
    month has had.

    INITIAL was worse: a THIRD copy. #143 moved it onto the approaches that use
    it, as an `iaf`, precisely so it would stop being published -- and the
    module constant went on existing beside it, so the move that was supposed
    to make it private left it declared in two places at once.
    """

    def test_the_module_defines_no_places_at_all(self):
        """What is left in `core/fixes.py` is the TYPE and two functions that
        reason about a route. Numbers in the data, rules in code."""
        for name in ("KOBULETI", "BATUMI", "KUTAISI", "INITIAL", "FIXES",
                     "LEGS"):
            with self.subTest(name):
                self.assertFalse(hasattr(F, name),
                                 f"core.fixes still defines {name}")

    def test_the_published_ones_come_off_the_map(self):
        for name in ("KOBULETI", "BATUMI", "KUTAISI"):
            with self.subTest(name):
                got = getattr(R, name, None)
                if got is None:
                    continue          # a map need not publish these names
                self.assertIn(got.name.upper(),
                              {f.name.upper() for f in T.fixes_now()})

    def test_and_they_are_THE_SAME_OBJECT_as_the_catalogue_holds(self):
        """Identity, not equality. Two objects that happen to match are what
        this whole change is about -- an `is` check is the cheapest way to say
        "the same fix, not a copy that agrees today"."""
        pub = {f.name.upper(): f for f in T.fixes_now()}
        for name in ("KOBULETI", "BATUMI", "KUTAISI"):
            got = getattr(R, name, None)
            if got is None or got.name.upper() not in pub:
                continue
            with self.subTest(name):
                self.assertIs(got, pub[got.name.upper()])

    def test_INITIAL_is_a_procedure_point_and_not_published(self):
        """#143's whole point. If it reappears in `[[fix]]`, a real cartridge's
        steerpoint of the same name collides with our fiction again."""
        got = getattr(R, "INITIAL", None)
        if got is None:
            self.skipTest("this map declares no INITIAL")
        self.assertNotIn("INITIAL", {f.name.upper() for f in T.fixes_now()})
        self.assertIsNotNone(T.procedure_point("INITIAL"))

    def test_the_transit_is_built_from_those_readers(self):
        """`FIXES` was `[KOBULETI, INITIAL, BATUMI]` as module constants, so
        the transit and the catalogue were separate objects that agreed. Now
        the transit IS them."""
        got = getattr(R, "FIXES", None)
        if not got:
            self.skipTest("this map declares no transit")
        self.assertIs(got[0], R.KOBULETI)
        self.assertIs(got[-1], R.BATUMI)

    def test_a_name_the_map_does_not_publish_raises(self):
        """Not None. A typo that answered None becomes a plausible number three
        layers away; `__getattr__` says which name and which file to look in."""
        # Through the module hook directly: ruff refuses both `R.NAME` (a
        # useless expression) and `getattr(R, "NAME")` (a constant attribute),
        # and it is right about both -- the thing under test is the hook.
        with self.assertRaises(AttributeError) as caught:
            R.__getattr__("NOWHERE_AT_ALL")
        self.assertIn("NOWHERE_AT_ALL", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
