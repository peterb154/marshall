"""Every board row is measured from the seat working THAT aeroplane.

A datum is one per `Scope` and a board is not. The picture is drawn from a
single origin, so `datum_of(scope)` is one answer for every row on the page --
and it is the SPEAKING seat's, which on a metronome tick is nobody's: the tick
fetches radar with no field at all. Most refreshes are that tick.

WHY IT WAS HARMLESS AND WHY THAT IS THE TRAP. Center is fieldless anyway, so
the fallback is what he would have used, and the number and the "why" both
happened to be right. With two aerodromes up, the four Kobuleti seats work
aeroplanes twenty-two miles from the point the page quotes them against -- a
real distance to a real airport, belonging to the wrong one. The same shape as
`station_for`, `channels_for` and `field_origin` before each of them took a
field.

`worked_from` resolves it per row and landed in `392f961` WITH NO TEST, which
is the half #169 actually asks for:

    "The datum a board row shows is the one the controller working him would
     use, on a tick with no transmission in it -- ASSERTED, because the failure
     is invisible while the two answers agree."

That is this file. It drives the metronome case directly: a picture fetched
with no field, and a row whose seat is at the other aerodrome. [#169]
"""

from __future__ import annotations

import unittest

from marshall.atc import agent_atc as A
from marshall.core import theatre as T
from tests import theatre as TH


def project():
    """What `push_fixes` leaves behind, which `field_origin` reads.

    A host test process has never pushed anything, so `PROJECTED` is empty and
    every datum comes back blank -- which would make every assertion below pass
    for the wrong reason.
    """
    A.PROJECTED.update({f.name.upper(): (f.lat, f.lon)
                        for f in T.fixes_now() if f.lat is not None})


def picture(datum, contacts=()):
    """The real `Scope`, not a stand-in.

    A first version subclassed it and tripped on `origin`, which `Scope.__new__`
    ASSIGNS -- so a property shadowing it has no setter. Building the genuine
    object is both simpler and the only way this test exercises the same `of()`
    the board does.
    """
    return A.Scope("radar: one contact", contacts=list(contacts),
                   origin=getattr(datum, "point", None), datum=datum)


def contact(track: str, lat, lon) -> dict:
    """One radar contact as the picture holds them."""
    return {"name": track, "label": track, "lat": lat, "lon": lon,
            "alt_ft": 8000.0, "heading": 0.0, "speed_kt": 300.0,
            "type": "F-16C_50", "category": "airplane", "coalition": 2,
            "manned": True, "player": track, "on_ground": False,
            "callsign": track, "formation": ""}


class TestTheRowIsRemeasuredFromHisOwnSeat(unittest.TestCase):
    """The metronome case: a fieldless picture, a seat at the other field."""

    def setUp(self):
        project()
        if len(list(T.fields_now())) < 2:
            self.skipTest(f"{TH.name()} works one aerodrome, so every seat "
                          f"measures from the same point")
        self.pro = TH.the_arrival()
        self.here = TH.arrival()
        self.there = TH.other()
        self.away = TH.station("tower", self.there)
        if self.away is None:
            self.skipTest(f"{self.there.name} publishes no tower")
        # THE TICK'S PICTURE. `fetch_radar(session_id)` with
        # no `field=`, so the datum is the fallback nobody chose.
        self.fallback = A.field_origin("")
        # A contact sitting on the OTHER field, so the two answers cannot
        # coincide: zero miles from his own seat, twenty-two from the page's.
        self.scope = picture(self.fallback,
                             [contact("Away 1", self.there.lat,
                                      self.there.lon)])

    def test_the_datum_is_his_seats_field_not_the_pictures(self):
        d, _nm, _rad = A.worked_from(self.away.name, self.scope,
                                     "Away 1", None)
        self.assertIsNotNone(d, "the row published no datum at all")
        self.assertEqual(d["name"], self.there.name.upper())
        self.assertEqual(d["why"], A.WHY_FIELD)

    def test_and_the_NUMBER_moved_with_the_NAME(self):
        """The half that makes this honest rather than decorative.

        A relabelled number is worse than the fallback it replaced: it would
        print the other field's distance under this field's name, which is
        confidently wrong rather than merely odd. He is ON the other field, so
        his own seat measures him at zero.
        """
        _d, nm, _rad = A.worked_from(self.away.name, self.scope,
                                     "Away 1", None)
        self.assertIsNotNone(nm, "the range was not re-measured")
        self.assertLess(nm, 1.0,
                        f"he is standing on {self.there.name} and his own "
                        f"seat makes him {nm} miles away")

    def test_the_pictures_own_answer_would_have_been_the_other_field(self):
        """Asserted so the test above cannot pass by the two agreeing. If the
        fallback and the seat ever name the same point, there is nothing here
        to catch and this says so."""
        self.assertNotEqual(self.fallback.published().get("name"),
                            self.there.name.upper(),
                            "the fallback datum already names his field, so "
                            "nothing above distinguishes the fix from the bug")


class TestItNeverGUESSES(unittest.TestCase):
    """When the seat or the position is missing, the picture's answer stands.

    The number WAS computed against that origin and must go on saying so.
    Relabelling it would be the confidently-wrong failure this whole line of
    work exists to prevent.
    """

    def setUp(self):
        project()
        self.pro = TH.the_arrival()
        self.fallback = A.field_origin("")

    def test_a_seat_nobody_recognises_leaves_the_picture_alone(self):
        scope = picture(self.fallback)
        d, nm, rad = A.worked_from("Nobody At All", scope, "X", None)
        self.assertEqual(d, A.datum_of(scope))
        self.assertIsNone(nm)
        self.assertIsNone(rad)

    def test_no_owner_at_all_leaves_the_picture_alone(self):
        scope = picture(self.fallback)
        self.assertEqual(A.worked_from("", scope, "X", None)[0],
                         A.datum_of(scope))

    def test_a_contact_with_no_position_is_not_re_measured(self):
        """A row we cannot locate must keep the number that was computed, not
        acquire a new one from nowhere."""
        if len(list(T.fields_now())) < 2:
            self.skipTest("one aerodrome")
        away = TH.station("tower", TH.other())
        if away is None:
            self.skipTest("no tower at the other field")
        scope = picture(self.fallback, [contact("Away 1", None, None)])
        d, _nm, _rad = A.worked_from(away.name, scope, "Away 1", None)
        self.assertEqual(d, A.datum_of(scope))

    def test_a_seat_at_the_SAME_field_changes_nothing(self):
        """No re-measurement when the two points are one. Doing the arithmetic
        anyway would round a number for no reason and make a diff look like a
        change."""
        here = TH.station("tower", TH.arrival())
        if here is None:
            self.skipTest("no tower at the arrival field")
        own = A.field_origin(TH.arrival().name)
        scope = picture(own, [contact("Home 1", 41.0, 41.0)])
        d, nm, rad = A.worked_from(here.name, scope, "Home 1", None)
        self.assertEqual(d, A.datum_of(scope))
        self.assertIsNone(nm)
        self.assertIsNone(rad)


class TestTheMetronomeTickIsTheCommonCase(unittest.TestCase):
    """Why this matters at all: most refreshes carry no transmission.

    The tick fetches with no `field=`, deliberately -- it is nobody's picture.
    That is fine now BECAUSE the datum is resolved per row afterwards, and
    would be wrong the moment somebody "fixed" the tick by passing a field,
    since one field is still one answer for a whole board.
    """

    def test_the_picture_the_BOARD_is_published_from_carries_no_field(self):
        """Precisely the metronome's fetch, not every fetch in the loop.

        `scheduler` holds two. The one feeding a hook CALLBACK passes a field
        and must -- that is one seat speaking, and #166 is the commit that gave
        it one. The one feeding `publish_state` must not, because a board is
        many rows and a field is one seat's answer.

        A first version asserted "no fetch in `scheduler` passes a field" and
        failed on the hook's, correctly. The claim is about which picture the
        BOARD is drawn from, so the test follows the variable rather than
        sweeping the function.
        """
        import ast
        import pathlib
        src = pathlib.Path(A.__file__).read_text()
        fn = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.FunctionDef) and n.name == "scheduler")
        pub = next(n for n in ast.walk(fn)
                   if isinstance(n, ast.Call)
                   and getattr(n.func, "id", "") == "publish_state")
        scope_arg = pub.args[2]
        self.assertIsInstance(scope_arg, ast.Name,
                              "the board's picture is no longer a named local, "
                              "so this test cannot follow it")
        fed_by = [n for n in ast.walk(fn)
                  if isinstance(n, ast.Assign)
                  and any(getattr(x, "id", "") == scope_arg.id
                          for x in n.targets)]
        self.assertTrue(fed_by, f"nothing assigns {scope_arg.id!r}")
        for a in fed_by:
            for c in ast.walk(a):
                if (isinstance(c, ast.Call)
                        and getattr(c.func, "id", "") == "fetch_radar"):
                    self.assertNotIn(
                        "field", {k.arg for k in c.keywords},
                        "the board's own picture is fetched for ONE seat, so "
                        "every row on it will be measured from that seat's "
                        "field -- the datum belongs per row, in worked_from")

    def test_and_publish_state_resolves_the_datum_per_row(self):
        import inspect
        self.assertIn("worked_from(", inspect.getsource(A.publish_state),
                      "the board is publishing the picture's datum again")


if __name__ == "__main__":
    unittest.main()
