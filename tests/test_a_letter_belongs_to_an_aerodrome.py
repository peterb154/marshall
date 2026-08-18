"""Three lookups fell back to the literal "Batumi", and one of them went
silent. [#162 #137]

    src/marshall/atc/controller.py   _atis_phrase, _wind_phrase, _runway_in_use
        fld = _R.field_named(getattr(me, "field", "") or _R.ARRIVAL_FIELD)

`me.field` is the speaking controller's own aerodrome and is the right answer.
Reaching PAST it to a module constant is what makes the line map-specific:
`ARRIVAL_FIELD` is the string "Batumi", so on Nevada `field_named` returns None
and every one of the three falls through to its own last resort.

`_atis_phrase`'s last resort was the empty string, and `request_clearance`
returned early on a missing letter, so:

    MARSHALL_THEATRE=nevada, a controller with no seat named
      before   (silence)
      after    Sockeye one one, Say your request.

Silence, to a pilot who has just asked for his IFR clearance, from the first
controller of the sortie. That is harder to diagnose from the cockpit than a
wrong number, because it reads as a broken radio.

The Caucasus half is the more interesting one, because it was RIGHT BY
ACCIDENT: there is an aerodrome called Batumi on that map, so the fallback
resolved and the letter went out. One map succeeded and the other was mute, off
the same line -- which is the whole shape of the 13 August inventory.

WHAT REPLACES IT IS NOT A DIFFERENT DEFAULT. An unnamed seat is not an
aerodrome to guess at (#109), so no letter is advised and no runway is named.
But "nothing" is the FACT, never the transmission: "say your request" carries no
weather, no runway and no field, so it needs no aerodrome to be true, and the
man on the radio is still answered.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marshall.atc import controller as C
from marshall.atis import store
from marshall.core import route as R
from marshall.core import theatre as TH
import tests.theatre as _theatre_help

# NAMED, not taken off a process global. `TH.current().approach_key` is
# gone (#162) and a test that wants one procedure has to say which.
A_PROCEDURE = _theatre_help.the_arrival()


def _clearance(seat, on_air=True, letter="Alpha"):
    c = C.Controller(A_PROCEDURE)
    if seat is not None:
        c._me = seat
    with mock.patch.object(store, "current",
                           return_value=mock.Mock(on_the_air=on_air,
                                                  letter=letter)):
        c.request_clearance("Sockeye 1-1")
    return c.take_out()


def _delivery_seats():
    """Every seat on this map that would confirm a letter at all."""
    out = []
    for f in TH.fields_now():
        s = (R.station_for("clearance", field=f.name)
             or R.station_for("approach", field=f.name))
        if s is not None and s.field == f.name:
            out.append(s)
    return out


class TestNobodyAsksForAClearanceAndHearsNothing(unittest.TestCase):

    def test_a_seat_that_names_no_field_still_answers_him(self):
        """The measured failure, and the reason it is worth a test rather than
        a reading: an empty string here becomes silence two functions away."""
        out = _clearance(None)
        self.assertTrue(out, "he asked for a clearance and got nothing")
        self.assertIn("Say your request", " ".join(t.text for t in out))

    def test_but_it_invents_no_letter_for_him(self):
        """Which is the other half. Reading Batumi's information Alpha to a
        pilot at Nellis is the same fault wearing a success."""
        said = " ".join(t.text for t in _clearance(None)).lower()
        self.assertNotIn("information", said)
        self.assertEqual([], [t.decision for t in _clearance(None) if t.decision])

    def test_a_seated_controller_still_advises_the_letter(self):
        """The half that must not be lost. Every field's own delivery seat."""
        for seat in _delivery_seats():
            with self.subTest(seat=seat.name):
                out = _clearance(seat)
                self.assertIn("information Alpha",
                              " ".join(t.text for t in out))
                self.assertEqual(["advise_atis"],
                                 [t.decision.kind for t in out if t.decision])

    def test_and_a_field_with_no_broadcast_is_answered_without_one(self):
        """Not asked is not unanswered. `_atis_phrase` has said "Say your
        request" for this case all along; `request_clearance` swallowed it."""
        for seat in _delivery_seats():
            with self.subTest(seat=seat.name):
                out = _clearance(seat, on_air=False, letter="")
                self.assertTrue(out)
                said = " ".join(t.text for t in out)
                self.assertIn("Say your request", said)
                self.assertNotIn("information", said.lower())


class TestTheRunwayAndTheWindNameTheirField(unittest.TestCase):
    """The two siblings of the same line, in the same method-body shape."""

    def _ctl(self, seat):
        c = C.Controller(A_PROCEDURE)
        if seat is not None:
            c._me = seat
        return c

    def test_a_ground_seat_names_its_own_runway(self):
        for f in TH.fields_now():
            seat = R.station_for("ground", field=f.name) \
                or R.station_for("tower", field=f.name)
            if seat is None or seat.field != f.name:
                continue
            with self.subTest(field=f.name):
                got = self._ctl(seat)._runway_in_use()
                self.assertNotIn("in use", got)
                from marshall.core.say import spell_rwy
                self.assertEqual(spell_rwy(f"{f.runway_in_use():02d}"), got,
                                 "the seat's own field decides the end")

    def test_with_no_seat_the_field_is_not_consulted_at_all(self):
        """It used to be read off whatever field the theatre file calls the
        arrival -- on Nevada an aerodrome on the other map, on the Caucasus a
        real runway belonging to nobody in particular. With nobody named it
        falls to the documented last resort instead: the runway HIS approach
        lands on, which is a real answer for the man being spoken to.

        THE RECIPROCAL, deliberately. Asking with the procedure's own runway
        would pass either way on the Caucasus, where the arrival field's
        into-wind end happens to be the same 13 the approach lands on -- which
        is the accident this whole file is about."""
        import dataclasses

        from marshall.core.say import spell_rwy
        recip = str((int(A_PROCEDURE.runway) + 18 - 1) % 36 + 1).zfill(2)
        other = dataclasses.replace(A_PROCEDURE, runway=recip)
        self.assertNotEqual(A_PROCEDURE.runway, other.runway)
        c = C.Controller(other)
        self.assertEqual(spell_rwy(other.runway), c._runway_in_use(),
                         "his own procedure's runway, not an aerodrome's")

    def test_and_with_no_approach_either_nothing_is_named(self):
        """"In use" commits to nothing, which is what a controller says when
        the runway is not his to name."""
        self.assertEqual("in use", C.Controller()._runway_in_use())

    def test_the_wind_is_still_said_to_a_seatless_controller(self):
        """A wind is not an aerodrome's the way a letter is -- the declared
        one is the map's -- so this answers rather than falling silent."""
        self.assertIn("wind", self._ctl(None)._wind_phrase())


class TestTheLiteralIsNotConsultedByTheEngineAtAll(unittest.TestCase):
    """The structural half. Three copies of one line is a shape, and a shape
    that has already been fixed twice wants a check rather than a third fix."""

    def test_no_arrival_or_departure_literal_survives_in_atc(self):
        """`ast`, not a grep: the two names appear all over the comments in
        these files explaining why they are gone, and a check that cannot tell
        prose from code would have to be weakened until it caught nothing."""
        import ast
        src = Path(__file__).resolve().parents[1] / "src" / "marshall" / "atc"
        bad = []
        for path in sorted(src.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in ast.walk(tree):
                name = (node.attr if isinstance(node, ast.Attribute)
                        else node.id if isinstance(node, ast.Name) else "")
                if name in ("ARRIVAL_FIELD", "DEPARTURE_FIELD"):
                    bad.append(f"{path.name}:{node.lineno} {name}")
        self.assertEqual([], bad,
                         "a controller's field is his seat's, never a map's "
                         "literal")


if __name__ == "__main__":
    unittest.main()
