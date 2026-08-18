"""Failures go to a logger; the sortie goes to the console. Two channels.

    "print() should be a smell shouldnt it?"

Yes, and one was added while fixing #185 by copying the neighbours instead of
thinking. Measured across `atc/` that day:

    agent_atc.py     print=97    logger? NO
    controller.py    print=8     logger? NO
    clearance.py     print=0     logger? yes
    board.py         print=0     logger? yes

Twenty-two exception paths reported through `print`. No level, no filtering, no
routing, interleaved with the sortie transcript, and gone the moment the
console scrolled. `agent_atc` had no logger at all, which is why `log` was
undefined the first time one was reached for -- ruff caught that, and it is the
only reason a twenty-third did not ship.

IT COST REAL EVIDENCE. On 18 August a pilot's flight row never reached
`flights`, and `flight_bind` reports its failure on one of these lines. The
diagnostic that would have named the cause went to a stdout that no longer
exists, so the question "did the bind fail or was it never called?" is now
unanswerable. A cache that agreed with nothing and an error channel that left
no trace produced a bug findable only by luck.

THE TRANSCRIPT IS NOT THE SMELL. The `ATC` and `PILOT` lines ARE the operator's
interface and belong on the console. What was wrong is that failures shared the
channel, so a diagnostic could not be raised in severity, silenced, or sent to
a file without taking the sortie with it. This file draws that line and nothing
wider: it polices `except` blocks, and leaves the sortie alone.  [#186]
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ATC = ROOT / "src" / "marshall" / "atc"


def _prints_in_except() -> list[str]:
    """Every `print` reached from an `except` handler, as file:line."""
    out = []
    for py in sorted(ATC.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:                              # pragma: no cover
            continue
        for handler in (n for n in ast.walk(tree)
                        if isinstance(n, ast.ExceptHandler)):
            for node in ast.walk(handler):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "print"):
                    out.append(f"{py.name}:{node.lineno}")
    return out


class AFailureIsLoggedAndNotPrinted(unittest.TestCase):

    def test_no_except_block_reports_through_print(self):
        got = _prints_in_except()
        self.assertEqual(
            got, [],
            f"{got} reports a failure with `print`. Use the module logger: a "
            f"printed error has no level, cannot be filtered or routed, and "
            f"is gone when the console scrolls — which is how the cause of "
            f"the 18 August missing flight row became unrecoverable.")

    def test_the_check_is_looking_at_something(self):
        """It passes by finding nothing, so it has to prove it can find. A
        parser that silently stopped walking would read as a clean sweep."""
        found = []
        for py in ATC.rglob("*.py"):
            tree = ast.parse(py.read_text(encoding="utf-8"))
            found += [n for n in ast.walk(tree)
                      if isinstance(n, ast.ExceptHandler)]
        self.assertGreater(len(found), 50,
                           "no except handlers parsed; the sweep is blind")


class TheModulesThatFailHaveSomewhereToSayIt(unittest.TestCase):
    """A logger is what makes the rule above followable. `agent_atc` had none,
    so the correct thing was not merely unusual there -- it was unavailable."""

    def test_every_atc_module_that_logs_has_a_logger(self):
        """FOUND BY AST, NOT BY SUBSTRING. The first version of this swept for
        `"log." in src` and failed on eight modules whose PROSE contains the
        word -- "a line for the log.", "reconstructing it from the log." That
        is this repository's oldest reading error, the same one that made a
        rule forbidding a phrase fail because it had to quote the phrase, and
        it is embarrassing to have written it again here. A call is a call;
        find it in the tree."""
        for py in sorted(ATC.rglob("*.py")):
            src = py.read_text(encoding="utf-8")
            calls = [
                n for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "log"]
            if not calls:
                continue
            with self.subTest(py.name):
                self.assertRegex(
                    src, r"(?m)^log = logging\.getLogger",
                    f"{py.name} calls `log.` and never defines one; the name "
                    f"resolves to nothing and the failure path raises inside "
                    f"the handler that was meant to contain it")


class ButTheSortieStillReachesTheConsole(unittest.TestCase):
    """The correction must not go so far that watching a sortie stops working.

    The operator reads the frequency live. Sweeping these into a logger would
    be a tidy that costs the thing the console is for.
    """

    def test_the_transcript_lines_are_still_printed(self):
        src = (ATC / "agent_atc.py").read_text(encoding="utf-8")
        for line in ('print(f"  ATC[', 'print(f"PILOT'):
            with self.subTest(line):
                self.assertIn(line, src)


if __name__ == "__main__":
    unittest.main()
