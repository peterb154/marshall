"""A name in `[project.scripts]` is a promise, and it must be keepable.

    #147 [ARCH-26], item 1 -- "`console_scripts` in `pyproject.toml` for what
    already exists. Costs nothing, changes no directory, and makes the four
    names real for the first time."

`docs/STRUCTURE.md` argues that "bridge" and "director" are the names of two
DIRECTORIES that grew into processes, and that the parts should be named for
what they do: `marshall-radio` (L0), `marshall-atc` (L4-L5), `marshall-feed`
(L1), `marshall-kneeboard` (L7). Until one of them was a real command the
argument had no referent -- `pyproject.toml` said "no console scripts yet" and
the only way to start anything was a `__main__` block, which nothing can
import, name, or call.

WHAT THIS GUARDS is the failure that makes an entrypoint table worse than no
table: a line naming a module path or a function that is not there. `pip
install` does not check it, the shim it writes fails at RUN time, and the first
person to find out is whoever typed the command expecting a server.

The absences are deliberate and are not this test's business -- `marshall-radio`
and `marshall-atc` wait on `_run_srs` coming out of `agent_atc.py` (#55), and
`marshall-feed` is not a process at all today. An aspirational entrypoint is a
promise nobody kept.
"""

from __future__ import annotations

import importlib
import pathlib
import tomllib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class EveryConsoleScriptResolves(unittest.TestCase):

    def setUp(self):
        with (ROOT / "pyproject.toml").open("rb") as fh:
            self.scripts = tomllib.load(fh).get("project", {}).get("scripts", {})

    def test_there_is_at_least_one(self):
        """The whole point of item 1. If this table empties, the four names
        have gone back to being directory names."""
        self.assertTrue(self.scripts, "`[project.scripts]` is empty")

    def test_each_target_is_a_module_and_a_callable_in_it(self):
        for name, target in sorted(self.scripts.items()):
            with self.subTest(name):
                self.assertRegex(target, r"^[\w.]+:[\w.]+$",
                                 "a console script is `module:callable`")
                mod, _, func = target.partition(":")
                obj = importlib.import_module(mod)
                for part in func.split("."):
                    obj = getattr(obj, part, None)
                    self.assertIsNotNone(
                        obj, f"{name} points at {target}, which does not exist")
                self.assertTrue(callable(obj), f"{name} -> {target} is not callable")

    def test_the_names_are_marshall_ones(self):
        for name in self.scripts:
            with self.subTest(name):
                self.assertTrue(name.startswith("marshall-"), (
                    "the parts are named for what they do, prefixed with the "
                    "product: marshall-radio, marshall-atc, marshall-feed, "
                    "marshall-kneeboard"))


class TheKneeboardStillRunsAsAModule(unittest.TestCase):
    """`python -m marshall.kneeboard.serve 8362` is in the module docstring, in
    `docs/`, and in a deploy file. Extracting `main()` must not have taken it
    away -- an entrypoint is an ADDITION, not a migration."""

    def test_the_module_still_has_a_main_block_that_calls_main(self):
        src = (ROOT / "src" / "marshall" / "kneeboard" / "serve.py").read_text()
        self.assertIn('if __name__ == "__main__":', src)
        tail = src[src.index('if __name__ == "__main__":'):]
        self.assertRegex(tail, r"\bmain\(\)")

    def test_the_port_still_comes_off_the_command_line(self):
        """It was `sys.argv[1]`, and a console script is handed the same argv.
        `marshall-kneeboard 8362` must mean what the module form meant."""
        import inspect

        from marshall.kneeboard import serve
        body = inspect.getsource(serve.main)
        self.assertIn("sys.argv[1:]", body)
        self.assertIn("KNEEBOARD_PORT", body)


if __name__ == "__main__":
    unittest.main()
