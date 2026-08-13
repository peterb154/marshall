"""A default argument is evaluated at import, and the map is chosen by
environment. [#162]

    src/marshall/atc/briefing.py:348   def plate(profile = R.BATUMI_ASR, ...)
    src/marshall/mission/build.py:74   radio_frequency = R.TOWER.freq_mhz

Both are evaluated when the module is imported -- a `def`'s defaults and a
class body run at import time -- and `route.__getattr__` resolves those names
against `MARSHALL_THEATRE`. So each is a fact captured before anybody has
chosen, and on the second map neither name exists:

    MARSHALL_THEATRE=nevada  import marshall.atc.briefing
      -> AttributeError: BATUMI_ASR names approach 'batumi-asr', which the
         configured theatre does not publish.

    MARSHALL_THEATRE=nevada  import marshall.mission.build
      -> AttributeError: TOWER names station 'Batumi Tower', which the
         configured theatre does not have.

`agent_atc.load_and_push_plate` opens `from marshall.atc import briefing`
UNGUARDED and `_run_srs` calls it unguarded, so the SRS bridge -- the live ATC
-- raised during start-up on Nevada. Not a wrong frequency: no controller at
all, for the whole map. And `mission/nevada.py` imports `channels_for`,
`set_channels` and `write_presets` from `mission/build.py`, so the Nevada
mission could not be built with the theatre correctly set either.

`core/route.py:126-138` already argues this exact point, about a different
function, in its own docstring: "a default argument is bound at import, which
on a theatre that is chosen by environment is a fact captured before anybody
has chosen." The lesson was written down and not applied one file over -- which
is why the last test here is a STRUCTURAL one rather than two more imports.
"""

from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marshall.atc import briefing
from marshall.core import route as R
from marshall.core import theatre as TH

SRC = Path(__file__).resolve().parents[1] / "src"

# WHICH `route` NAMES COME FROM THE MAP. Anything `route` defines itself is an
# ordinary module global and is the same on every theatre; everything else is
# served by `route.__getattr__` out of the configured map's tables, and is
# therefore a fact that does not exist until somebody has chosen one.
_REAL = set(vars(R))
_ALIASES = ("R", "route", "_R", "_route")


def _bound_at_import():
    """Every default argument and class attribute that reads a map-served name.

    Not a grep: `ast`, so a name in a docstring or a comment is not a hit and a
    multi-line signature is. The two shapes are the two that actually run at
    import -- a `def`'s defaults and a `class` body.
    """
    out = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args
                exprs = [d for d in (*args.defaults, *args.kw_defaults) if d]
            elif isinstance(node, ast.ClassDef):
                exprs = [n.value for n in node.body if isinstance(n, ast.Assign)]
            else:
                continue
            for expr in exprs:
                for sub in ast.walk(expr):
                    if (isinstance(sub, ast.Attribute)
                            and isinstance(sub.value, ast.Name)
                            and sub.value.id in _ALIASES
                            and sub.attr not in _REAL):
                        out.append(f"{path.relative_to(SRC.parent)}:{sub.lineno} "
                                   f"{node.name} <- {sub.value.id}.{sub.attr}")
    return sorted(set(out))


def _imports(module: str, theatre: str) -> subprocess.CompletedProcess:
    """In a SUBPROCESS, because a theatre is chosen once per process and the
    caches behind it are keyed on the map. Importing under a different map is
    not something a running process can be asked to do."""
    # THIS tree, not whatever is installed. Without it the child imports the
    # editable install, which is the same source only by coincidence -- and a
    # check that silently tests a different copy of the code is worse than no
    # check, because it passes.
    env = {**os.environ, "MARSHALL_THEATRE": theatre,
           "PYTHONPATH": os.pathsep.join(
               [str(SRC), *filter(None, [os.environ.get("PYTHONPATH", "")])])}
    return subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        env=env, capture_output=True, text=True, timeout=120)


class TestTheBridgeStartsOnEitherMap(unittest.TestCase):
    """The three modules that could not be imported on the second map."""

    MODULES = ("marshall.atc.briefing",
               "marshall.mission.build",
               "marshall.mission.nevada")

    def test_they_import_under_both_theatres(self):
        for theatre in ("caucasus", "nevada"):
            for module in self.MODULES:
                with self.subTest(theatre=theatre, module=module):
                    got = _imports(module, theatre)
                    self.assertEqual(0, got.returncode,
                                     got.stderr.strip()[-400:])

    def test_and_the_bridges_own_start_up_import_is_one_of_them(self):
        """`load_and_push_plate` reaches `briefing` with no try/except round
        it, which is why an import error there is a dead radio rather than a
        missing page."""
        from marshall.atc import agent_atc
        src = inspect.getsource(agent_atc.load_and_push_plate)
        self.assertIn("from marshall.atc import briefing", src)


class TestThePlateAsksWhichProcedure(unittest.TestCase):

    def test_it_has_no_default_procedure(self):
        """There is no such thing as the theatre's approach. Which one is
        being flown is a fact about a CLEARANCE -- `flights.cleared_approach`
        is the column that holds it -- so a caller without one is not asking
        for Batumi's surveillance approach, he is asking a question with no
        answer."""
        got = inspect.signature(briefing.plate).parameters["profile"]
        self.assertIs(inspect.Parameter.empty, got.default)
        with self.assertRaises(TypeError):
            briefing.plate()

    def test_and_it_renders_for_every_procedure_this_map_publishes(self):
        for key, p in sorted(TH.approaches_now().items()):
            with self.subTest(procedure=key):
                txt = briefing.plate(p)
                self.assertIn("This mission's plate", txt)
                self.assertIn(p.aerodrome.name, txt)


class TestNothingElseBindsTheMapAtImport(unittest.TestCase):
    """The structural half, because the lesson had already been written down
    once and not applied. Two identical faults in two files is a shape, and a
    shape wants a check rather than two more test cases."""

    def test_no_default_argument_or_class_body_reads_a_map_served_name(self):
        self.assertEqual([], _bound_at_import(),
                         "a fact captured before anybody has chosen a map")

    def test_the_check_can_actually_see_one(self):
        """A guard nobody has watched fail is a guard nobody should trust."""
        offender = ast.parse("def f(p=R.BATUMI_ASR): pass")
        node = offender.body[0]
        hit = node.args.defaults[0]
        self.assertIsInstance(hit, ast.Attribute)
        self.assertNotIn(hit.attr, _REAL,
                         "BATUMI_ASR must be map-served for this to bite")

    def test_and_it_does_not_flag_an_ordinary_module_constant(self):
        """`R.FLIGHT_CALLSIGN` is `route`'s own global and reads the same on
        every map, so binding it at import is a different argument (#2's, about
        one flight per process) and not this one."""
        self.assertIn("FLIGHT_CALLSIGN", _REAL)
        self.assertIn("FLIGHT_SIZE", _REAL)


if __name__ == "__main__":
    unittest.main()
