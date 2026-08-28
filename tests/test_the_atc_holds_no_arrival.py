"""Nothing under `marshall/atc/` chooses an approach for the process. [#162]

`theatre.a_procedure_into` exists for TOOLS -- a rehearsal script standing in
for a pilot needs one procedure, because a pilot flies one. The radio must
never call it: a process cannot fly an approach, and the whole of #162 was
deleting the single `profile` that briefed the controller on one arrival and
was then handed to twenty-five functions as the answer for every aeroplane on
the frequency.

THIS TEST WAS CITED AND DID NOT EXIST. `a_procedure_into`'s own docstring says
"tests/test_the_atc_holds_no_arrival.py asserts that nothing under
marshall/atc/ reaches for it" -- and the file was never written, so the
invariant has been unguarded for as long as it has been documented. A pilot
asked why an ILS sortie kept mentioning ASR and the honest answer was that
nothing stops a default from coming back.

Asserted on the AST rather than by grep: a comment saying the words must not
fail the test that forbids them.
"""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ATC = ROOT / "src" / "marshall" / "atc"

# The rehearsal tools may. They are pilots, not controllers.
FORBIDDEN = {"a_procedure_into"}


class TheAtcHoldsNoArrival(unittest.TestCase):

    def test_no_module_under_atc_chooses_a_procedure_for_the_process(self):
        bad = []
        for f in sorted(ATC.rglob("*.py")):
            tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
            for node in ast.walk(tree):
                name = ""
                if isinstance(node, ast.Attribute):
                    name = node.attr
                elif isinstance(node, ast.Name):
                    name = node.id
                if name in FORBIDDEN:
                    bad.append(f"{f.relative_to(ROOT)}:{node.lineno} -> {name}")
        self.assertEqual(bad, [], "the radio must not choose an arrival: " + "; ".join(bad))

    def test_the_controller_carries_no_default_profile(self):
        """`Controller()` with no argument holds none, and `procedure_of`
        falls back to what the CALLER had -- never to a named approach."""
        import sys
        sys.path.insert(0, str(ROOT / "src"))
        from marshall.atc.controller import Controller, procedure_of
        self.assertIsNone(Controller().profile,
                          "a process-wide arrival is what #162 deleted")
        self.assertIsNone(procedure_of(None, None),
                          "no aeroplane and no caller profile is not an approach")


if __name__ == "__main__":
    unittest.main()
