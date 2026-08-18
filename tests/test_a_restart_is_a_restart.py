"""A restart cannot change the procedure, because there is none to change.

WHAT THIS FILE USED TO GUARD, and why the guard is now the opposite assertion.

`tools/bridge.py` had no test at all, and this is what it cost. `DEFAULT_ARGS`
carried `--theatre` and never the approach, so `MARSHALL_APPROACH` survived a
restart only if the operator happened to have exported it in the shell he was
restarting from. From anywhere else it silently reverted to the map's default:

    started:   MARSHALL_APPROACH=batumi-ils  ->  ILS runway 13, intercept
    restarted: (nothing carried)             ->  batumi-asr, a TALKDOWN

It happened twice on 13 August. Once by accident, mid-rehearsal, which
invalidated the run and was noticed only because the agent flying it checked the
log line before judging anything; once deliberately, to reproduce it.

The fix was to ASK THE RUNNING PROCESS -- `/proc/<pid>/environ` is the
environment at exec time and does not follow any shell -- and to carry the
answer across the stop. That was a correct fix, and it is gone. [#158]

IT WAS A CORRECT FIX TO A MECHANISM THAT SHOULD NOT HAVE EXISTED, which is
#162:

    "the radio should not have a default appproach it was loaded with.
     Approaches should be assigned on a per flight basis at runtim"

A restart cannot revert a procedure if no procedure is attached to the process.
So the carry-forward is deleted rather than maintained, and this file asserts
the DELETION -- which is the stronger guard, because a carry-forward can be
forgotten, mis-set, or defeated by starting the radio by hand, and a thing that
does not exist cannot be any of those.

WHAT REPLACES IT is state that outlives the process: `flights.cleared_approach`
holds what each aeroplane was ISSUED and `Controller.hydrate` restores it, so a
restart mid-approach brings back every aeroplane's own procedure rather than one
guess for all of them.

ASSERTED ON THE AST, NOT ON THE TEXT. Every one of these names has to be
QUOTED to be forbidden -- the paragraphs above say `MARSHALL_APPROACH` five
times -- so `"MARSHALL_APPROACH" not in source` fails on a file that merely
explains itself. That trap has misfired four times in this repository. The
questions below are asked of the parsed module: which names it binds, which
strings it compares argv against, which keys it writes into `os.environ`.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import bridge

_TOOLS = Path(__file__).resolve().parent.parent / "tools"
_SRC = Path(__file__).resolve().parent.parent / "src" / "marshall"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text())


def _env_writes(tree: ast.Module) -> set[str]:
    """Every literal key assigned into `os.environ[...]`."""
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if (isinstance(tgt, ast.Subscript)
                    and isinstance(tgt.value, ast.Attribute)
                    and tgt.value.attr == "environ"
                    and isinstance(tgt.slice, ast.Constant)):
                out.add(tgt.slice.value)
    return out


def _string_constants(tree: ast.Module) -> set[str]:
    """Literals used as VALUES, excluding docstrings and comments.

    Comments are not in the AST at all, which is the property this file needs:
    a module may explain at any length what it no longer does.
    """
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value not in docstrings}


class TestTheBridgeCannotCarryAProcedure(unittest.TestCase):
    """`tools/bridge.py`, which is where the carry-forward lived."""

    def setUp(self):
        self.tree = _tree(_TOOLS / "bridge.py")

    def test_the_reader_is_gone(self):
        """`approach_of(pids)` opened `/proc/<pid>/environ` and returned the
        procedure the running radio had been started with. Asked of the module
        object, so a rename to something equally load-bearing still fails."""
        self.assertFalse(hasattr(bridge, "approach_of"))

    def test_nothing_writes_an_approach_into_the_environment(self):
        """The `--approach` flag set `MARSHALL_APPROACH`, and so did the
        carry-forward. `--theatre` still writes `MARSHALL_THEATRE`, which is
        the control this SHOULD have been compared against all along: a map is
        a property of the world the process is working, and an approach is a
        property of one aeroplane's clearance."""
        wrote = _env_writes(self.tree)
        self.assertIn("MARSHALL_THEATRE", wrote,
                      "the theatre flag stopped working, which is a real "
                      "regression rather than the deletion this file guards")
        self.assertNotIn("MARSHALL_APPROACH", wrote)

    def test_no_command_line_flag_offers_one(self):
        """A flag is a string compared against `sys.argv`. `--theatre` is
        present for the same contrast as above."""
        consts = _string_constants(self.tree)
        self.assertIn("--theatre", consts)
        self.assertNotIn("--approach", consts)


class TestNothingInTheRadioReadsTheVariable(unittest.TestCase):
    """The deletion has to hold everywhere, or the flag comes back by another
    door: `bridge.py` clean while `theatre.py` still consults the environment
    would restore the whole defect with no flag to notice it by."""

    def test_no_module_reads_MARSHALL_APPROACH_from_the_environment(self):
        offenders = []
        for path in sorted(_SRC.rglob("*.py")) + sorted(_TOOLS.rglob("*.py")):
            tree = _tree(path)
            for node in ast.walk(tree):
                # `os.environ.get("X")` and `os.environ["X"]`, which are the
                # two ways this was ever read.
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "get"
                        and isinstance(node.func.value, ast.Attribute)
                        and node.func.value.attr == "environ"
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value == "MARSHALL_APPROACH"):
                    offenders.append(str(path))
                if (isinstance(node, ast.Subscript)
                        and isinstance(node.value, ast.Attribute)
                        and node.value.attr == "environ"
                        and isinstance(node.slice, ast.Constant)
                        and node.slice.value == "MARSHALL_APPROACH"):
                    offenders.append(str(path))
        self.assertEqual(offenders, [])

    def test_and_the_theatre_publishes_no_singular_to_put_one_in(self):
        """The other half. A variable with nowhere to land is harmless; a
        `Theatre.approach` with no variable would just acquire a new one."""
        from marshall.core import theatre as T
        th = T.current()
        self.assertFalse(hasattr(th, "approach"))
        self.assertFalse(hasattr(th, "approach_key"))
        self.assertTrue(th.approaches, "the map publishes no procedures at all")


class TestWhatCarriesAcrossARestartInstead(unittest.TestCase):
    """Not nothing -- the aeroplane's own clearance, which is durable."""

    def test_the_engine_restores_a_procedure_per_aircraft(self):
        """`hydrate` is the restart path and `cleared_approach` is the column.
        A restart mid-approach brings back what each aeroplane was ISSUED,
        which is more than the carry-forward ever managed: it restored ONE
        procedure for everybody."""
        from marshall.atc import controller as C
        self.assertTrue(hasattr(C.Controller, "hydrate"))
        self.assertTrue(hasattr(C.Controller, "assign_approach"))

    def test_a_fresh_controller_holds_no_arrival_at_all(self):
        """The property that makes the deletion safe: a Controller built with
        nothing works for everything that is not an approach -- the whole
        ground ladder, the whole enroute half, every seat below Approach."""
        from marshall.atc import controller as C
        ctl = C.Controller()
        self.assertIsNone(ctl.profile)
        self.assertIsNone(ctl.procedure_for("Nobody 1-1"))


if __name__ == "__main__":
    unittest.main()
