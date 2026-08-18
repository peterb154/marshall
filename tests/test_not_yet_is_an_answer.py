"""A rule that says "not yet" has spoken, and nothing else gets a vote.

    "tower, switch me over to departure pretty quick, should be at five miles
     I think, just hit it off the end of the runway"

The table says five miles:

    Rule("tower", "departure", "outbound_beyond", DEPARTURE_NM)   # 5.0

and it works — below five it declines, above five it fires. What it could not
do is SAY SO. `due` returned `None` both when a rule had governed the
transition and decided he stays, and when no rule applied at all, and
`next_controller` reads the second as permission to ask the PostGIS airspace
volumes instead:

    v = _handoff.due(...)                     -> None (a rule said not yet)
    nxt = ... else v.station                  -> None
    if nxt is None and not down: nxt = leaving_my_airspace(...)   -> Departure

So geometry answered over the top of procedure, at about a mile, and neither
knew the other had spoken. The 5 nm in the table was correct, tested, and
unreachable in practice.

THIS IS #181 ONE MODULE OVER AND ONE DAY LATER. There, `clearance_agreed is
False` — "he was issued one and has not read it back" — was collapsed into
`None` — "nobody has cleared him at all" — and taxi was granted to a man who
had never been cleared. Same shape: a deterministic engine that cannot
distinguish a DECISION from an ABSENCE OF OPINION cannot hold a line, because
every refusal reads as an invitation to whoever asks next.

    a rule fired          -> Verdict with a station. Hand him over.
    a rule governs, not yet -> Verdict with keep=True. Nobody else decides.
    no rule at all        -> None. The airspace may answer.

`same_station=True` on the keep verdict is deliberate: to every caller that
already means "no frequency change, no transmission", which is exactly what
not-yet amounts to, so nothing else had to learn about the flag. [#189]
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from marshall.atc import handoff as H
from marshall.core import route as R

import tests.theatre as T

ROOT = Path(__file__).resolve().parents[1]


def _tower():
    return R.station_for("tower", field=T.other().name)


class BelowTheThresholdIsADecision(unittest.TestCase):

    def setUp(self):
        self.me = _tower()
        if self.me is None:
            self.skipTest("this map staffs no tower at the departure field")
        self.pro = T.the_arrival()

    def _due(self, nm: float):
        return H.due(self.pro, self.me,
                     H.State(False, nm, False, phase="departure"))

    def test_a_rule_that_declines_still_answers(self):
        """The flown case: airborne, outbound, inside five miles."""
        for nm in (0.5, 1.0, 3.0, 4.9):
            with self.subTest(nm=nm):
                v = self._due(nm)
                self.assertIsNotNone(
                    v, f"at {nm} nm a rule governs this and said not yet, and "
                       f"`due` reported nothing — which the caller reads as "
                       f"permission for the airspace to decide")
                self.assertTrue(v.keep)
                self.assertIsNone(v.station)

    def test_and_it_is_still_falsy_so_nobody_is_handed_anywhere(self):
        """The keep verdict must not read as a handoff to anything that
        already unwraps a Verdict."""
        v = self._due(1.0)
        self.assertFalse(v)
        self.assertTrue(v.same_station)

    def test_beyond_it_the_rule_fires_as_before(self):
        v = self._due(5.1)
        self.assertTrue(v)
        self.assertFalse(v.keep)
        self.assertEqual(getattr(v.station, "role", ""), "departure")

    def test_the_threshold_is_where_the_table_says(self):
        """Guards the number itself. A silently moved DEPARTURE_NM is a pilot
        handed over somewhere other than the card says."""
        self.assertEqual(H.DEPARTURE_NM, 5.0)


class ButNoRuleAtALLIsStillSilence(unittest.TestCase):
    """The distinction has to cut both ways, or it is just a rename.

    The airspace volumes exist because the table cannot describe every
    transition — a region has a shape and a rule has a number. Turning every
    "no" into a keep would silence the branch that #51 was fixed by, where a
    pilot held at 44 nm with no mechanism able to move him.
    """

    def test_a_seat_no_rule_mentions_gets_None(self):
        me = R.station_for("clearance", field=T.other().name)
        if me is None:
            self.skipTest("no clearance seat on this map")
        governed = {r.frm for r in H.RULES} | {
            x for r in H.RULES for x in ()}
        if me.role in governed:
            self.skipTest(f"{me.role} is governed by a rule after all")
        self.assertIsNone(
            H.due(T.the_arrival(), me, H.State(False, 40.0, True)),
            "a seat no rule mentions must leave the airspace free to answer")


class TheCallerHonoursIt(unittest.TestCase):
    """The half that actually fixes the sortie.

    Asserted on the source rather than by driving a live turn: reaching
    `leaving_my_airspace` needs a running store, a radar picture and a bound
    track, and what must be true is structural — the airspace branch is gated
    on the table not having ruled.
    """

    def _next_controller_src(self) -> str:
        src = (ROOT / "src" / "marshall" / "atc" / "agent_atc.py").read_text()
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "next_controller")
        return ast.get_source_segment(src, fn) or ""

    def test_the_airspace_is_not_asked_when_a_rule_has_ruled(self):
        src = self._next_controller_src()
        self.assertIn("ruled", src,
                      "`next_controller` does not track whether the rule "
                      "table already decided")
        at = src.index("leaving_my_airspace")
        guard = src[max(0, at - 400):at]
        self.assertIn("not ruled", guard,
                      "the airspace volumes are consulted without asking "
                      "whether a rule already said not yet — which is the "
                      "whole of #189")

    def test_the_flag_is_set_from_the_verdict(self):
        src = self._next_controller_src()
        self.assertIn('getattr(v, "keep", False)', src)


if __name__ == "__main__":
    unittest.main()
