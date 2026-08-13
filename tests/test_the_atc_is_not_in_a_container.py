"""The ATC domain lives in the ATC package, and the old name does not resolve.

    #147 [ARCH-26], item 3 -- "`director/tools/` into `src/marshall/atc/`, the
    same move as `ebea93a`. This is where the value is."

`director/tools/` held twelve modules of ATC domain reasoning -- approaches,
clearance, flights, identify, plans, frequencies, capability, filing, hooks,
context, ops -- inside a deployable's directory, findable only by somebody who
already knew to look in a container. `ebea93a` moved the controller's WORDS out
for exactly this reason and stopped one layer short.

WHY THIS IS A GREP AND NOT A BEHAVIOUR TEST. Nothing about a working import
tells you where the code is: a redirect module, or a `sys.modules` rebind, or a
`getattr` fallback, all leave every caller green while the old spelling goes on
working. That is precisely how `ApproachProfile.beacon` survived its own
removal -- deleting it turned up four more readers reaching it through
`getattr(p, "beacon", None)`, a spelling the grep that found the first six had
walked straight past. A name that still resolves is a name nobody has to fix.

So the assertion is the absence of the old spelling, and the allowance below is
a NAMED list rather than a pattern. Adding a module to `director/tools/` means
adding a line here and arguing for it, which is the whole point.

    #162 is the other half of the argument: four acceptance criteria met while
    26 of 28 call sites kept the old path, because nothing was watching the
    call sites.
"""

from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

# What may still live in the deployable, and why. Both are properties of
# RUNNING AN AGENT BEHIND HTTP rather than of controlling aeroplanes, which is
# the line `marshall/atc/agent/__init__.py` already draws for the prompts:
# "the HTTP door -- endpoints, session locking, the tier swap -- stays in the
# deployable. Serving is not deciding."
SERVING = {
    # A table of non-blocking locks keyed on the agent's own identity, because
    # strands raises ConcurrencyException when a second call arrives mid-flight.
    "busy",
    # `escalate` -- one log line with a greppable marker, so the agent can raise
    # its hand to the operator. No aerodrome, no procedure.
    "ops",
    "__init__",
}

# `from tools.x import y`, `from tools import x`, `import tools.x` -- every
# spelling that makes the container's directory a package somebody imports.
IMPORTS = re.compile(r"^\s*(?:from\s+tools(?:\.\w+)?\s+import\s+(.+)"
                     r"|import\s+tools(?:\.(\w+))?)", re.M)


class TheDomainModulesAreInTheAtcPackage(unittest.TestCase):
    """Named, so that a module going missing is a failure and not a shrug."""

    MOVED = {
        # ATC domain reasoning and the state it works on. `atc/`.
        "approaches": "marshall.atc.approaches",
        "board": "marshall.atc.board",          # was tools/flights.py
        "clearance": "marshall.atc.clearance",
        "filing": "marshall.atc.filing",
        "frequencies": "marshall.atc.frequencies",
        "identify": "marshall.atc.identify",
        "plans": "marshall.atc.plans",
        # What shapes the model call. `atc/agent/`, beside the prompts.
        "capability": "marshall.atc.agent.capability",
        "context": "marshall.atc.agent.context",
        "hooks": "marshall.atc.agent.hooks",
    }

    def test_every_one_of_them_imports_under_its_new_name(self):
        import importlib
        for _, dotted in sorted(self.MOVED.items()):
            with self.subTest(dotted):
                self.assertTrue(importlib.import_module(dotted))

    def test_none_of_them_is_still_a_file_in_the_deployable(self):
        left = sorted(p.stem for p in (ROOT / "director" / "tools").glob("*.py"))
        self.assertEqual(left, sorted(SERVING), (
            "`director/tools/` may hold only what serves the agent over HTTP. "
            "Anything else is ATC domain reasoning in a container's directory, "
            "which is what #147 item 3 removed."))


class NobodySpellsItTheOldWay(unittest.TestCase):
    """A redirect left behind is worse than a broken import, because the broken
    import is the thing that was supposed to tell you the code had moved."""

    def _offenders(self, where: pathlib.Path, allow: set[str] = frozenset()) -> list[str]:
        bad = []
        allow = SERVING | set(allow)
        for path in sorted(where.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            for n, line in enumerate(path.read_text().splitlines(), 1):
                code = line.split("#", 1)[0]
                m = IMPORTS.search(code)
                if not m:
                    continue
                names = m.group(1) or m.group(2) or ""
                # `from tools import x as y, z` -- one module per comma, and
                # the module is the first word of each; the alias is not a name
                # anybody has to move.
                asked = {part.split()[0].split(".")[0]
                         for part in names.split(",") if part.split()}
                # A submodule import names it after the dot instead.
                dotted = re.search(r"from\s+tools\.(\w+)", code)
                if dotted:
                    asked = {dotted.group(1)}
                if asked - allow:
                    bad.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
        return bad

    def test_the_tests_import_the_new_names(self):
        bad = self._offenders(ROOT / "tests")
        self.assertEqual(bad, [], "\n".join(
            ["a test still imports ATC domain logic out of `director/tools/`; "
             "the modules are `marshall.atc.*` now:", *bad]))

    def test_the_deployable_imports_the_new_names(self):
        bad = self._offenders(ROOT / "director")
        self.assertEqual(bad, [], "\n".join(
            ["`director/` still imports ATC domain logic from its own `tools/`; "
             "the modules are `marshall.atc.*` now:", *bad]))

    def test_the_scripts_import_the_new_names(self):
        """THERE ARE TWO `tools/` DIRECTORIES and that is the trap. A script in
        the repo's own `tools/` saying `from tools import plans` reads as
        local, and resolved to the container's copy only because the line above
        it put `director/` on `sys.path` -- which is how `tools/plan_sweep.py`
        was importing ATC domain logic out of a deployable in a tier-1 check.
        A name that names a real file in `tools/` is fine and is left alone."""
        local = {p.stem for p in (ROOT / "tools").glob("*.py")}
        bad = (self._offenders(ROOT / "tools", local)
               + self._offenders(ROOT / "src", local))
        self.assertEqual(bad, [], "\n".join(
            ["a script imports ATC domain logic out of `director/tools/`; the "
             "modules are `marshall.atc.*` now:", *bad]))

    def test_no_test_puts_the_deployable_on_the_import_path_for_them(self):
        """`sys.path.insert(..., "director")` exists to import `tools.*`. Once
        the module is `marshall.*` the insert is a leftover that would let a
        redirect work again without anybody noticing."""
        bad = []
        for path in sorted((ROOT / "tests").glob("*.py")):
            text = path.read_text()
            if 'sys.path.insert' not in text or '"director"' not in text:
                continue
            # Still legitimate for whatever `SERVING` keeps there.
            if not re.search(r"from tools(?:\.\w+)? import|import tools", text):
                bad.append(str(path.relative_to(ROOT)))
        self.assertEqual(bad, [], "\n".join(
            ["these tests still put `director/` on sys.path and no longer "
             "import anything from it:", *bad]))


if __name__ == "__main__":
    unittest.main()
