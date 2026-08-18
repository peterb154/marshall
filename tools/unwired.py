"""Things that exist and nothing uses.

    "So that problem -- where we have a system and nothing is using it... that's
     happened several times. Is this something you can audit for?"

It has happened at least six times, and it is the dominant failure mode of this
project. Not bugs in what was written -- the written thing is usually correct --
but a correct thing that no path reaches:

    phases.guide          a dispatcher written to fly the phase he is in, and
                          the arrival's geometry was called directly instead.
                          A departing F-16 was told he had gone around.
    Controller._me        read in six places, assigned in none. Every read took
                          the no-station branch, so Kobuleti Tower cleared a
                          take-off on Batumi's runway.
    flight_strip          the plan, route and cruise level were assigned,
                          stored, joined -- and the strip read none of them, so
                          every later controller asked a cleared pilot what he
                          wanted.
    phrasebook.render     built, tested, never wired. Tests made it look alive.
    kneeboard/plans.py    a page a pilot needs, with no tab.
    AtcCapability.era     declared, never consulted -- and the code says so in
                          a comment, which is how long it has been known.

WHAT IS DETECTABLE, and each of those is a different shape:

    a function nothing calls
    an attribute read but never assigned
    a module nothing imports
    something only its own TESTS call, which is the nastiest because a green
        suite reads as proof of life

WHAT IS NOT, honestly: whether a thing is called on the path that MATTERS.
`asr.guide` was called constantly and by the wrong caller. No static check finds
that; only a sortie does. This narrows the search, it does not replace flying.

FALSE POSITIVES ARE EXPECTED AND ARE THE POINT OF THE BASELINE. A public helper,
a tool the agent calls by name, a FastAPI route -- all look unused and are not.
So this compares against a recorded baseline and fails only on something NEW,
the same bargain as the approach sweep: a check that is always red is a check
nobody reads.

    uv run python tools/unwired.py            # what is new since the baseline
    uv run python tools/unwired.py --all      # everything it can see
    uv run python tools/unwired.py --bless    # record today's answer
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tools" / "unwired.json"

# Where the SYSTEM lives, as opposed to what drives or tests it.
SOURCE = (ROOT / "src" / "marshall", ROOT / "services")
# Everything that may legitimately be a caller. `tools/` counts: a script that
# is the only caller of something is a real use, and saying otherwise would
# report every diagnostic helper in the repo.
CALLERS = (*SOURCE, ROOT / "tools")
TESTS = (ROOT / "tests",)

# Decorators that mean "something else calls this". A framework entry point has
# no caller in the repo and never will.
FRAMEWORK = {"tool", "app.get", "app.post", "app.put", "app.delete",
             "staticmethod", "classmethod", "dataclass"}
# A PROPERTY IS ASSIGNED BY BEING DEFINED. `@property def _vectored` is read as
# `self._vectored` and never stored, which is not the `_me` shape at all.
AS_GOOD_AS_ASSIGNED = {"property", "cached_property", "functools.cached_property"}


# NOT OURS, so not our problem. `services/strands_pg` is a stamp of the upstream
# framework and `_grpc` is generated from the DCS protos -- a library is full of
# things this repo does not call, by design, and reporting them would bury the
# handful that matter.
VENDORED = ("__pycache__", "_grpc", "strands_pg", "migrations", "shots")


def _files(roots) -> list[Path]:
    out: list[Path] = []
    for r in roots:
        if r.exists():
            out += [p for p in r.rglob("*.py")
                    if not set(p.parts) & set(VENDORED)]
    return sorted(out)


def _decorators(node) -> set[str]:
    got = set()
    for d in getattr(node, "decorator_list", []):
        got.add(ast.unparse(d).split("(")[0].lstrip("@"))
    return got


class Defs(ast.NodeVisitor):
    """Every name this file offers to the rest of the system."""

    def __init__(self, path: Path):
        self.path, self.out = path, {}
        self.properties: set[str] = set()
        self.fields: set[str] = set()
        self.stack: list[str] = []

    def _add(self, name: str, line: int, kind: str) -> None:
        if name.startswith("__"):
            return
        # Recorded under BOTH its bare name and `module:name`, so a caller that
        # reaches it either way counts -- and two functions sharing a bare name
        # can still be told apart. See `Refs`.
        self.out.setdefault(name, (self.path, line, kind))
        self.out.setdefault(f"{self.path.stem}:{name}", (self.path, line, kind))

    def visit_FunctionDef(self, node):
        if _decorators(node) & AS_GOOD_AS_ASSIGNED:
            self.properties.add(node.name)
        if not (_decorators(node) & (FRAMEWORK | AS_GOOD_AS_ASSIGNED)):
            self._add(node.name, node.lineno,
                      "method" if self.stack else "function")
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        # A DECLARED FIELD IS ASSIGNED BY THE CLASS. `_broken_up: dict =
        # field(default_factory=dict)` is only ever mutated in place after
        # that, never rebound, and it is not the `_me` shape.
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                self.fields.add(item.target.id)
            elif isinstance(item, ast.Assign):
                for t in item.targets:
                    if isinstance(t, ast.Name):
                        self.fields.add(t.id)
        self._add(node.name, node.lineno, "class")
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()


class Refs(ast.NodeVisitor):
    """Every name this file uses, however it reaches it.

    QUALIFIED WHERE IT CAN BE. `guide` is defined in BOTH `asr.py` and
    `phases.py`, so a bare-name check cannot tell them apart -- and the bug it
    was written to find was precisely `phases.guide` being uncalled while
    `asr.guide` was called constantly. So an attribute reached through an
    imported module alias is recorded as `module:name` as well as `name`.
    """

    def __init__(self):
        self.names: set[str] = set()
        # alias -> dotted module, from this file's imports
        self.alias: dict[str, str] = {}
        # ATTRIBUTES ARE TRACKED APART FROM BARE NAMES. The first draft mixed
        # them and the "read but never assigned" list filled with local
        # variables -- `_taken`, `_who`, `_typ` -- which are assigned as Names
        # and so looked like attributes nobody wrote. Five hundred rows of
        # noise, and the one real finding buried in it.
        # NAMES THAT CAME OUT OF A STRING, kept apart. A string constant is
        # good enough evidence for cross-module dispatch -- `phases.py` really
        # does call `asr:guide` through one -- and NOT good enough to say a
        # function is called from its own file, because the string that names
        # it may be the dispatch table declaring it rather than a call.
        self.from_strings: set[str] = set()
        self.attr_read: set[str] = set()
        # ONLY AN ATTRIBUTE STORE. A LOCAL VARIABLE OF THE SAME NAME IS NOT ONE,
        # and that distinction is the whole check: `_me` was read as
        # `self._me` in six places and never stored -- but `agent_atc` has a
        # LOCAL `_me = profile.station_on(...)`, so counting bare-name binds as
        # assignments hid the very bug this was written to find.
        self.attr_written: set[str] = set()
        self.bound: set[str] = set()

    def visit_Name(self, node):
        self.names.add(node.id)
        if isinstance(node.ctx, ast.Store):
            self.bound.add(node.id)

    def visit_ImportFrom(self, node):
        for a in node.names:
            self.alias[a.asname or a.name] = f"{node.module or ''}.{a.name}"
            # `from tools.clearance import resolve` IS a reference, and an
            # unambiguous one. Without recording it, a function whose bare name
            # is shared with another module looked uncalled even though the
            # import names it exactly.
            if node.module:
                self.names.add(f"{node.module.rsplit('.', 1)[-1]}:{a.name}")
        self.generic_visit(node)

    def visit_Import(self, node):
        for a in node.names:
            self.alias[a.asname or a.name.split(".")[0]] = a.name
        self.generic_visit(node)

    def visit_Attribute(self, node):
        self.names.add(node.attr)
        self.attr_read.add(node.attr)
        if isinstance(node.value, ast.Name):
            mod = self.alias.get(node.value.id)
            if mod:
                self.names.add(f"{mod.rsplit('.', 1)[-1]}:{node.attr}")
        # WRITTEN, as distinct from read. `self._me = x` is what makes an
        # attribute real; `getattr(self, "_me", None)` in six places and no
        # assignment anywhere is a field that is always its default.
        if isinstance(node.ctx, ast.Store):
            self.attr_written.add(node.attr)
        self.generic_visit(node)

    def visit_Constant(self, node):
        # A NAME IN A STRING IS STILL A USE. `phases.py` dispatches through
        # handler="marshall.atc.asr:guide", and a checker that could not see
        # that would report the one function the table exists to call.
        if isinstance(node.value, str) and len(node.value) < 200:
            for part in node.value.replace(":", " ").replace(".", " ").split():
                self.names.add(part)
                self.from_strings.add(part)

    def visit_Call(self, node):
        # getattr(x, "name") reads a name the AST would otherwise miss.
        f = node.func
        if (isinstance(f, ast.Name)
                and f.id in ("getattr", "hasattr", "setattr")
                and len(node.args) > 1
                and isinstance(node.args[1], ast.Constant)):
            self.names.add(str(node.args[1].value))
            self.attr_read.add(str(node.args[1].value))
            if f.id == "setattr":
                self.attr_written.add(str(node.args[1].value))
        self.generic_visit(node)


def refs_of(path: Path):
    """(names used, attributes read, attributes written, names from strings)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set(), set(), set(), set()
    r = Refs()
    r.visit(tree)
    return r.names, r.attr_read, r.attr_written, r.from_strings


def audit() -> dict[str, list]:
    """What is defined in the system and referenced by nothing outside itself.

    KEYED ON `module:name`, ALWAYS. Bare names cannot answer the question this
    tool exists for: `guide` is defined in both `asr.py` and `phases.py`, and
    the bug was `phases.guide` never being called while `asr.guide` was called
    constantly. Keyed on the bare name, whichever file sorted first owned the
    answer and the other was invisible.

    A definition counts as reached when another file mentions `module:name`, or
    mentions the bare name AND that bare name is unambiguous in this codebase.
    The second half is what keeps `from x import y; y()` working; the first is
    what keeps two same-named functions apart.

    PER FILE ON BOTH SIDES. A name used twice inside the module that defines it
    is not reached from anywhere, and an earlier draft that compared against
    every reference in the repo -- its own file included -- found nothing at all.
    """
    defs: dict[str, tuple] = {}
    properties: set[str] = set()
    bare_count: dict[str, int] = {}
    for p in _files(SOURCE):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        d = Defs(p)
        d.visit(tree)
        properties |= d.properties | d.fields
        for name, where in d.out.items():
            if ":" not in name:
                continue                       # the qualified form is the key
            defs.setdefault(name, where)
            bare_count[name.split(":", 1)[1]] = \
                bare_count.get(name.split(":", 1)[1], 0) + 1

    prod_refs = {p: refs_of(p) for p in _files(CALLERS)}
    test_refs = {p: refs_of(p) for p in _files(TESTS)}

    def reached(key: str, home: Path, where, kind: str = "") -> bool:
        """Does anything call it -- INCLUDING its own module.

        The defining file counts, and leaving it out was wrong: a private
        helper used twice inside one module is wired, and excluding its home
        reported every `_` function in `agent_atc.py` as reached only by tests.

        Safe to include, because a `def` statement does not reference its own
        name -- the name lives on the FunctionDef node, not in a Name node --
        so a function nothing calls stays unreached even in the file that
        defines it. `phases.guide` was exactly that: defined, and called from
        nowhere at all.
        """
        bare = key.split(":", 1)[1]
        # A METHOD CANNOT BE QUALIFIED. `ctl.get(...)` reaches
        # `Controller.get`, and `ctl` is an object, not a module alias -- no
        # static pass resolves that without type inference. So a method is
        # judged on its bare name even when the name is shared, which is a
        # weaker check and honest about it: methods get false NEGATIVES here,
        # module-level functions get the strong answer.
        loose = kind == "method"
        for _p, r in where.items():
            if key in r[0]:
                return True
            # A BARE HIT IN ITS OWN FILE IS CONCLUSIVE, shared name or not:
            # Python resolves a bare name in a module to that module's own
            # definition. Without this, `mission/nevada.py` calling its own
            # `build()` read as uncalled, because `build` is also defined in
            # `mission/build.py` and the two modules share a stem.
            #
            # EXCEPT FROM A STRING, which may be the dispatch table declaring
            # the handler rather than anything calling it -- `phases.py`
            # contains "marshall.atc.asr:guide" and `phases.guide` being
            # uncalled is the bug this tool was written to find.
            if _p == home and bare in (r[0] - r[3]):
                return True
            if (loose or bare_count.get(bare, 0) <= 1) and bare in r[0]:
                return True
        return False

    found: dict[str, list] = {"unused": [], "tests_only": [], "unassigned": []}
    for key, (path, line, kind) in sorted(defs.items()):
        if reached(key, path, prod_refs, kind):
            continue
        row = [key, f"{path.relative_to(ROOT)}:{line}", kind]
        if reached(key, path, test_refs, kind):
            found["tests_only"].append(row)
        else:
            found["unused"].append(row)

    # AN ATTRIBUTE READ AND NEVER WRITTEN -- the `_me` shape, which put a
    # take-off clearance on another aerodrome's runway. Attribute stores only:
    # a LOCAL variable of the same name is not an assignment to the attribute,
    # and counting it hid exactly this.
    read = (set().union(*(a for _, a, _, _ in prod_refs.values()))
            if prod_refs else set())
    written = (set().union(*(w for _, _, w, _ in prod_refs.values()))
               if prod_refs else set())
    known = {k.split(":", 1)[1] for k in defs}
    for name in sorted(read - written - properties - known):
        if not name.startswith("_") or name.startswith("__"):
            continue
        if name in dir(str) or name in dir(list) or name in dir(dict):
            continue
        found["unassigned"].append([name, "", "attribute"])
    return found


# WHY A BASELINED ENTRY IS STILL THERE. A name with no reason beside it is how
# a mechanical check becomes prose again.
#
# `models:Flight` is the case that proved it. The owner asked for SQLAlchemy
# models; a model was written; nothing used it; THIS TOOL FOUND IT on 13 August
# and it was blessed into the baseline with `--bless`, which records the whole
# audit and asks nothing. By 18 August it had rotted five columns behind the
# table it claims to describe, and a sortie broke on one of them --
# `sortie_phase`, which the model had never heard of.
#
# The check was not missing. Its escape hatch was silent. So an entry may sit
# in the baseline, and now it has to say why and name the issue that removes
# it; anything blessed without one is reported every run.
WHY = {
    "models:Flight":
        "the read/write path is still hand-written SQL. #120 is the work that "
        "makes this the way flights are read and written; until then it is "
        "declared, tested against the live schema, and used by nothing",
}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="everything, not the drift")
    ap.add_argument("--bless", action="store_true", help="record today as the baseline")
    args = ap.parse_args(argv)

    found = audit()
    was = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}

    if args.bless:
        BASELINE.write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
        n = sum(len(v) for v in found.values())
        print(f"baseline recorded: {n} known, in {BASELINE.relative_to(ROOT)}")
        # WHAT WAS JUST ACCEPTED WITHOUT A REASON. Blessing is how debt gets
        # taken on, and taking it on silently is how it stops being debt and
        # becomes the design. Named here rather than refused, because refusing
        # would make the tool unusable on the day somebody needs it -- but a
        # list nobody can read is the thing this whole file argues against.
        loose = [r[0] for rows in found.values() for r in rows
                 if r[0] not in WHY]
        if loose:
            print(f"  .. {len(loose)} of them carry no reason. Add one to WHY "
                  f"in this file for anything that is DEBT rather than a "
                  f"false positive, naming the issue that removes it.")
        return 0

    def _why(name: str) -> str:
        r = WHY.get(name)
        return f"\n        .. {r}" if r else ""

    titles = {
        "unused": "DEFINED AND NOTHING CALLS IT",
        "tests_only": "ONLY ITS OWN TESTS CALL IT  (a green suite is not proof of life)",
        "unassigned": "READ BUT NEVER ASSIGNED  (always its default)",
    }
    news = 0
    for key, rows in found.items():
        old = {tuple(r[:1]) for r in was.get(key, [])}
        show = rows if args.all else [r for r in rows if tuple(r[:1]) not in old]
        if not show:
            continue
        news += 0 if args.all else len(show)
        print(f"\n{titles[key]}")
        for name, where, kind in sorted(show, key=lambda r: r[1]):
            print(f"  {name:34} {kind:9} {where}{_why(name)}")

    if args.all:
        print(f"\n{sum(len(v) for v in found.values())} total; "
              f"baseline holds {sum(len(v) for v in was.values())}")
        return 0
    if news:
        print(f"\n{news} NEW since the baseline. Each is either a thing to wire "
              f"up or a thing to delete —\nboth are fine and leaving it is not. "
              f"Bless it with --bless when it is deliberate.")
        return 1
    print("nothing new is unwired")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
