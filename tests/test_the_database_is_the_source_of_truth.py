"""The architecture rule that has drifted for a month, made mechanical.

    "there really shouldn't be much in memory data structures - we addressed
     this - database is fast and should be the single source of truth"

    "ive been begging you to stop using in memory data structures and instead
     use the database for a) persistence b) a single source of truth and using
     sqlalchemy for the data schema can keep us working with classes and
     objects rather than rando sql strings and bespoke schemas"

WHY THIS FILE EXISTS, AND IT IS A FINDING ABOUT THE PROJECT RATHER THAN ABOUT
THE BOARD. Look at which architectural rules held and which drifted:

    a rule with a CHECK      `test_the_atc_is_not_in_a_container` kept
                             `services/tools/` free of domain logic through a
                             directory rename, twelve module moves and a month.
                             `configuration_is_not_code`, `one_place_says_where`,
                             `a_beacon_is_not_an_airfield` -- all held
    a rule with only PROSE   "the database is the single source of truth" is in
                             CLAUDE.md, in STATE.md, in `hydrate`'s docstring
                             and in the owner's own words. It drifted into a
                             21-field in-memory dict, 7 fields of which never
                             reach the table, mutated from two threads with no
                             lock, beside a SQLAlchemy model that NOTHING
                             imports and that had gone five columns behind the
                             table it claims to describe

Same repository, same author, same agent. The difference is whether something
FAILS when the rule is broken. Prose is not a constraint; it is a wish.

#120 is the specific evidence. It is titled "The board is in memory; the
database is the source of truth" and was closed FIXED on 11 August by building
a WRITE-THROUGH CACHE -- which satisfies every word of the request and none of
its intent. #162 named that failure mode exactly, one issue over:

    "A criterion that a parallel implementation can satisfy does not retire
     the thing it was replacing."

A cache fed from the database satisfies "the database is the source of truth"
the way a parallel implementation satisfies an acceptance criterion. So this
file does not assert prose. It counts, and it fails when the count gets worse.

BASELINES, NOT ZEROES, and that is `asr_sweep`'s rule taken verbatim: *"a check
that is always red is a check nobody reads"* and a baseline is *"today's truth
written down so a regression is visible"*. Every number below is debt. Beat it
and move it in the same commit; never raise one to make a change pass.
"""

from __future__ import annotations

import ast
import dataclasses
import re
import unittest
from pathlib import Path

from marshall.atc import controller as C

ROOT = Path(__file__).resolve().parents[1]

# --- baseline 1: state that lives only in memory ------------------------------
#
# `Aircraft` is a write-through cache of `flights`, so every field on it must
# either reach the table or be declared as something a restart is ALLOWED to
# forget. A field in neither is state that silently dies -- which is how a
# reconnect mid-sortie loses a rung a pilot has climbed.
#
# EPHEMERAL IS A DECLARATION, NOT AN OMISSION. These are clocks and derived
# scratch that mean nothing outside one run; writing them down is what makes
# the ones below it debt rather than a design.
EPHEMERAL = {
    "callsign",        # the key itself
    "last_report_t",   # a clock, meaningless across a restart
    "map_t",           # ditto: computed station-passage time
}

# ...AND THE DEBT. Seven fields that are neither carried nor ephemeral. Each is
# a fact a restart forgets, and `owner` and `intent` are the two a pilot would
# notice: who is working him, and what he said he wants.
UNCARRIED_BASELINE = {"intent", "kit", "members", "owner", "ships"}

# --- baseline 2: the model that nothing uses ---------------------------------
#
# `atc/models.py` declares a SQLAlchemy `Flight` with `Mapped[]` columns. It is
# imported by exactly one file -- `tests/test_schema.py`, to register the table
# so another test passes. Every read and write of a flight goes round it in
# hand-written SQL, so nothing ever failed when a column arrived without a
# `Mapped[]` beside it -- and five had: `sortie_phase`, `on_visual`,
# `approaches_flown`, `atis_letter`, `flight_plan_label`, all from migration
# 026 onwards. They are declared now and the check below keeps them so.
#
# The COUNT is a floor rather than the assertion. The real check compares the
# model against the live table, which needs a database; this catches a column
# being deleted from the model on a machine that has not got one.
MODEL_COLUMNS_BASELINE = 33

# --- baseline 3: raw SQL outside the store modules ---------------------------
#
# "rando sql strings and bespoke schemas". A store module is allowed to speak
# SQL; that is what it is for. Domain modules are not, because a query in a
# domain module is a schema decision made where nobody will look for one.
STORES = {"board.py", "approaches.py", "tracks.py", "events.py",
          "store.py", "db.py", "schema.py", "models.py",
          # THE MISSION INSTANCE, and the reason it is a store rather than a
          # computation is the whole of #187: the key used to be DERIVED on
          # every process start from `wall_clock - timer.getTime()`, and model
          # time stops while the sim is paused, so it drifted. Rows written
          # under yesterday's key became unreachable and the table read as
          # empty. Something has to remember the answer, and remembering is
          # what a store is for.
          "missions.py"}
RAW_SQL_BASELINE = {"clearance.py": 4, "filing.py": 8, "frequencies.py": 1,
                    "identify.py": 7, "procedures.py": 1}


def _hydrated() -> set[str]:
    """Which `Aircraft` fields `hydrate` restores from the table."""
    src = (ROOT / "src" / "marshall" / "atc" / "controller.py").read_text()
    blk = src[src.index("def hydrate"):]
    end = blk.index("\n    def ", 10)
    return set(re.findall(r"ac\.(\w+)\s*=", blk[:end]))


def _raw_sql() -> dict[str, int]:
    """Statements written as string literals, by file.

    An AST walk and not a grep, because the paragraphs above have to QUOTE the
    thing they forbid -- the trap this repository has sprung four times.
    """
    out: dict[str, int] = {}
    for p in sorted((ROOT / "src").rglob("*.py")):
        try:
            tree = ast.parse(p.read_text())
        except SyntaxError:                         # pragma: no cover
            continue
        n = 0
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "execute"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                    and re.search(r"\b(select|insert|update|delete|create)\b",
                                  node.args[0].value, re.I)):
                n += 1
        if n and p.name not in STORES:
            out[p.name] = n
    return out


class NoFactLivesOnlyInMemory(unittest.TestCase):
    """Every `Aircraft` field reaches the table or is declared forgettable."""

    def test_no_new_field_escapes_the_table(self):
        fields = {f.name for f in dataclasses.fields(C.Aircraft)}
        loose = fields - _hydrated() - EPHEMERAL
        new = sorted(loose - UNCARRIED_BASELINE)
        self.assertEqual(
            new, [],
            f"new Aircraft field(s) {new} are neither written to `flights` nor "
            f"declared EPHEMERAL. A restart forgets them silently, which is "
            f"how a reconnect mid-sortie loses a rung the pilot has climbed. "
            f"Carry it in `hydrate` and the model, or add it to EPHEMERAL "
            f"with the reason.")

    def test_and_the_debt_has_not_grown(self):
        fields = {f.name for f in dataclasses.fields(C.Aircraft)}
        loose = fields - _hydrated() - EPHEMERAL
        self.assertLessEqual(
            len(loose), len(UNCARRIED_BASELINE),
            f"in-memory-only fields went from {len(UNCARRIED_BASELINE)} to "
            f"{len(loose)}: {sorted(loose)}")

    def test_the_baseline_is_honest(self):
        """It must name what is actually loose. A baseline listing something
        already fixed hides a regression behind a stale allowance."""
        fields = {f.name for f in dataclasses.fields(C.Aircraft)}
        loose = fields - _hydrated() - EPHEMERAL
        stale = sorted(UNCARRIED_BASELINE - loose)
        self.assertEqual(stale, [],
                         f"UNCARRIED_BASELINE names {stale}, which is carried "
                         f"now — shrink the baseline in the same commit")


class TheModelIsTheSchema(unittest.TestCase):
    """`Mapped[]` classes, not hand-written DDL and hand-written reads."""

    def test_the_flight_model_has_not_shrunk_further_behind(self):
        from marshall.atc import models
        n = len(models.Flight.__table__.columns)
        self.assertGreaterEqual(
            n, MODEL_COLUMNS_BASELINE,
            f"the Flight model lost columns ({n} < {MODEL_COLUMNS_BASELINE}); "
            f"it is already behind the live schema and going the wrong way")

    def test_the_model_declares_every_column_the_table_has(self):
        """THE CHECK THAT MAKES THE MODEL THE SCHEMA rather than a document.

        Five columns existed on `flights` and not here -- `sortie_phase`,
        `on_visual`, `approaches_flown`, `atis_letter`, `flight_plan_label` --
        added by migration 026 and absent from the model for eight days,
        because every read and write goes round it in hand-written SQL and
        nothing ever failed.

        `sortie_phase` is the one that cost the 18 August sortie: a pilot
        holding short derived as LANDED and Departure posted him back to Tower
        for thirteen miles, on a fact the model had never heard of.

        MY FIRST VERSION OF THIS TEST WAS WRONG and it is worth recording why.
        It demanded `cleared_approach` on `Flight`, and that is not a flights
        column at all -- the `flight_state` view joins it from
        `assigned_plans.approach`, because which approach you are cleared for
        is a fact about your CLEARANCE and not about your flight row, which is
        the whole of #162. A mechanical check encoding a wrong assumption is
        worse than prose, because it is obeyed.

        Needs the database, and SKIPS LOUDLY without one rather than passing:
        a check that cannot run reads exactly like one that was satisfied.
        """
        import os
        from marshall.atc import models
        try:
            from marshall.core.db import pool
            os.environ.setdefault(
                "MARSHALL_PG_DSN",
                "postgresql://strands:strands@127.0.0.1:5432/strands")
            with pool().connection() as c:
                rows = c.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'flights'").fetchall()
        except Exception as e:                      # pragma: no cover - no db
            self.skipTest(f"no database, so the model is unguarded: {e}")
        table = {r[0] for r in rows}
        model = {c.name for c in models.Flight.__table__.columns}
        self.assertEqual(
            sorted(table - model), [],
            "columns exist on `flights` that the model does not declare. Add "
            "them, or the next migration is invisible to every reader that "
            "uses the model. [#120]")
        self.assertEqual(
            sorted(model - table), [],
            "the model declares columns the table has not got — a migration "
            "was written and never run, or a column was dropped")


class SQLLivesInTheStores(unittest.TestCase):
    """A query in a domain module is a schema decision nobody will find."""

    def test_no_new_module_starts_writing_sql(self):
        got = _raw_sql()
        new = sorted(set(got) - set(RAW_SQL_BASELINE))
        self.assertEqual(
            new, [],
            f"{new} now writes SQL and is not a store module. Put the query "
            f"behind the model, or declare the module a store in STORES with "
            f"the reason.")

    def test_and_no_module_writes_more_of_it(self):
        got = _raw_sql()
        worse = {k: (RAW_SQL_BASELINE[k], v) for k, v in got.items()
                 if k in RAW_SQL_BASELINE and v > RAW_SQL_BASELINE[k]}
        self.assertEqual(worse, {},
                         f"raw SQL grew: {worse} (baseline, now)")

    def test_the_baseline_is_honest(self):
        got = _raw_sql()
        stale = {k: n for k, n in RAW_SQL_BASELINE.items()
                 if got.get(k, 0) < n}
        self.assertEqual(stale, {},
                         f"RAW_SQL_BASELINE overstates {stale} — shrink it in "
                         f"the same commit that removed the query")


class TheBoardIsMutatedFromTwoThreadsWithNoLock(unittest.TestCase):
    """The concurrency half, which nobody had looked at.

    `_run_srs` and `asr_monitor` both mutate the board, and the only lock in
    the file guards the RADIO. So a read-decide-write on the stack -- read the
    levels, pick a free one, assign it -- can interleave with the other
    thread. That is the "two aircraft on one level" hazard arriving by a route
    the separation tests cannot see, because they are single-threaded.

    A transaction is a better answer than a dict, and it is the same answer as
    everything else in this file.
    """

    MUTATORS = {"check_in", "request_approach", "request_visual",
                "request_breakup", "report_down", "report_landed",
                "report_missed", "report_beacon", "assign_approach",
                "note_vectored", "note_intent", "note_cleared_level",
                "clearance_read_back", "seed_from_radar", "release"}

    def _threads_that_mutate(self) -> dict[str, set[str]]:
        src = (ROOT / "src" / "marshall" / "atc" / "agent_atc.py").read_text()
        tree = ast.parse(src)
        out = {}
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            if fn.name not in ("asr_monitor", "scheduler", "_run_srs"):
                continue
            hits = {n.func.attr for n in ast.walk(fn)
                    if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr in self.MUTATORS
                    and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == "ctl"}
            if hits:
                out[fn.name] = hits
        return out

    def test_no_third_thread_starts_mutating_the_board(self):
        """Two is today's debt. Three would be a new race, and the point of a
        baseline is that the next one is caught the day it is written."""
        got = self._threads_that_mutate()
        self.assertLessEqual(
            len(got), 2,
            f"{len(got)} threads now mutate the board without a lock: "
            f"{ {k: sorted(v) for k, v in got.items()} }")

    def test_the_race_is_recorded_rather_than_forgotten(self):
        """Asserts the hazard EXISTS, so that fixing it fails this test and
        forces the record to be updated. A known race with no test is a race
        that gets rediscovered."""
        got = self._threads_that_mutate()
        self.assertIn("asr_monitor", got)
        self.assertIn("_run_srs", got)


if __name__ == "__main__":
    unittest.main()
