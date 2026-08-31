"""Every runway clearance asks who is on the runway. Structurally.

    "i feel like there should be a function to determine if anyone is on a
     runway. And tower should use that before he clears anyone to takeoff or
     land. Only one aircraft or flight allowed on the runway at a time"

There is one function -- `Controller.who_is_on_the_runway` -- and both sites
call it. This test is about the THIRD site, the one nobody has written yet: two
of the three incursions this month came from a runway clearance issued by a
path that never asked, and each was fixed by adding the question to one more
place. A rule enforced by remembering is a rule that lasts until somebody is in
a hurry.

WHAT IS DELIBERATELY NOT HERE. A visual approach clearance is not a landing
clearance -- it is gated on the LETDOWN, one aircraft on the approach, which is
the right separation for it. You may be cleared for the visual while somebody
is still rolling out; he will be gone by the time you arrive, and Tower's
landing clearance is a separate transmission that does ask.

NO LINE-UP-AND-WAIT. Real towers hold an aeroplane on the runway while another
lands, and this system does not: one aircraft or flight at a time, deliberately
simpler.
"""
from __future__ import annotations

import ast
import pathlib
import unittest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "marshall" / "atc"
GATE = "who_is_on_the_runway"

# The words that put an aeroplane ONTO a runway. A clearance that says one of
# these is a commitment of the strip.
CLEARANCES = ("cleared for take-off", "cleared to land")


def _spoken(fn: ast.FunctionDef) -> list[str]:
    """Every string this function could transmit, docstring excluded."""
    out = []
    body = fn.body[1:] if (fn.body and isinstance(fn.body[0], ast.Expr)
                           and isinstance(fn.body[0].value, ast.Constant)
                           and isinstance(fn.body[0].value.value, str)) else fn.body
    for node in body:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                out.append(sub.value)
    return out


def _calls(fn: ast.FunctionDef) -> set[str]:
    return {sub.func.attr for sub in ast.walk(fn)
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)}


class NothingClearsARunwayItHasNotLookedAt(unittest.TestCase):

    def _offenders(self):
        bad = []
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text())
            for fn in ast.walk(tree):
                if not isinstance(fn, ast.FunctionDef):
                    continue
                said = " ".join(_spoken(fn)).lower()
                if not any(c in said for c in CLEARANCES):
                    continue
                calls = _calls(fn)
                # IT HAS TO TRANSMIT ONE, not merely contain the words.
                # `phrasebook.render` turns a Decision the controller already
                # made -- and already gated -- into English, and
                # `assembly.compose_message` writes the words into the prompt
                # that TELLS the model what a landing clearance sounds like.
                # Neither issues anything, and flagging them would train the
                # next reader to add exceptions rather than to ask.
                if "say" not in calls:
                    continue
                if GATE not in calls:
                    bad.append(f"{path.name}:{fn.name}")
        return bad

    def test_every_runway_clearance_asks_first(self):
        self.assertEqual(
            self._offenders(), [],
            "these issue a take-off or landing clearance without asking "
            f"`{GATE}` who is on it. Two of this month's three incursions "
            "were exactly this -- a path that never asked.")

    def test_the_check_is_not_vacuous(self):
        """The guard above passes trivially if nothing matches. Both known
        sites must be found, or a renamed phrase has quietly disabled it."""
        found = []
        for path in sorted(SRC.rglob("*.py")):
            tree = ast.parse(path.read_text())
            for fn in ast.walk(tree):
                if isinstance(fn, ast.FunctionDef):
                    said = " ".join(_spoken(fn)).lower()
                    if (any(c in said for c in CLEARANCES)
                            and "say" in _calls(fn)):
                        found.append(fn.name)
        self.assertIn("request_takeoff", found)
        self.assertIn("report_landed", found)


if __name__ == "__main__":
    unittest.main()
