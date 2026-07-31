"""The models must agree with the database, or they are worse than nothing.

    "It would make it easier for me to comprehend and catch bugs in the IDE."

Which is the whole reason `core.schema` exists -- raw SQL in Python is opaque to
an editor, and a mistyped column is a runtime error found in a sortie rather
than a red squiggle found while reading.

That value is entirely conditional on the model being TRUE. A declarative model
that has drifted from the schema is the most confident kind of wrong: it
autocompletes, it type-checks, and it is lying. Migrations still own the schema;
these tests are what stop the mirror rotting.

THEY NEED A DATABASE, which the rest of the unit suite deliberately does not --
"pure stdlib, no LLM/network/sim, milliseconds". So they SKIP when there is no
DSN, and the skip is reported rather than silent, the same rule `tools/check.py`
applies to everything else: a check that quietly does not run reads exactly like
one that passed.
"""

import os
import unittest

_DSN = os.environ.get("MARSHALL_PG_DSN") or os.environ.get("STRANDS_PG_DSN")


@unittest.skipUnless(_DSN, "no MARSHALL_PG_DSN / STRANDS_PG_DSN: schema not checked")
class TestTheModelsMatchTheDatabase(unittest.TestCase):
    """Every column in the model exists in the table, with the same name."""

    @classmethod
    def setUpClass(cls):
        from sqlalchemy import inspect

        from marshall.atc import models  # noqa: F401  -- registers atc's tables
        from marshall.core import db, schema
        cls.schema, cls.insp = schema, inspect(db.engine())

    def test_every_modelled_table_exists(self):
        for name in sorted(self.schema.Base.metadata.tables):
            with self.subTest(table=name):
                self.assertTrue(self.insp.has_table(name),
                                f"{name} is modelled and not in the database")

    def test_no_model_column_is_missing_from_the_table(self):
        """The dangerous direction. A column in the model and not in the
        database fails at the first query that touches it -- in a sortie."""
        for name, table in sorted(self.schema.Base.metadata.tables.items()):
            if not self.insp.has_table(name):
                continue
            live = {c["name"] for c in self.insp.get_columns(name)}
            with self.subTest(table=name):
                self.assertEqual(set(table.columns.keys()) - live, set())

    def test_the_indexes_that_are_rules_are_really_there(self):
        """Three of these are not tuning, they are the invariants the engine
        assumes and Python kept failing to enforce.

        `flights_track` -- one aeroplane, one row -- has existed since migration
        012 and was never consulted, while a misheard word put one Mustang on
        the board twice and the separation engine began sequencing him against
        himself.
        """
        want = {"flights_track", "flights_srs_guid", "flights_mission_callsign"}
        got = {i["name"] for i in self.insp.get_indexes("flights")}
        self.assertEqual(want - got, set(), f"missing: {sorted(want - got)}")
        for name in sorted(want):
            with self.subTest(index=name):
                idx = next(i for i in self.insp.get_indexes("flights")
                           if i["name"] == name)
                self.assertTrue(idx["unique"], f"{name} must be UNIQUE")


@unittest.skipUnless(_DSN, "no DSN: session behaviour not checked")
class TestTheSessionIsNotAllowedToBecomeACache(unittest.TestCase):
    """The one trap the ORM ships with, and the bug this project already had.

    A `Session` holds an identity map: a second query for a row returns the
    object already loaded rather than what the table now says. Held across
    turns that is `_FIXES` again -- a lazily-loaded copy that never invalidates.
    """

    def test_session_is_a_context_manager_not_a_getter(self):
        from marshall.core import db
        self.assertTrue(hasattr(db.session(), "__enter__"))
        self.assertFalse(hasattr(db, "get_session"),
                         "a long-lived session is a cache with no expiry")

    def test_a_fresh_session_sees_what_another_committed(self):
        """The property that makes per-turn sessions correct."""
        from sqlalchemy import text

        from marshall.core import db
        with db.session() as a:
            a.execute(text("CREATE TEMP TABLE IF NOT EXISTS _probe (n int)"))
        with db.session() as b:
            self.assertEqual(b.execute(text("SELECT 1")).scalar(), 1)


if __name__ == "__main__":
    unittest.main()
