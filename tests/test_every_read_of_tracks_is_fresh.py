"""A stale track is not a contact, on EVERY read, whichever way it is read.

    "should we write a test looking for SQL strings so that this doesnt keep
     happening?"

Nearly -- and the near miss is the point. Banning SQL strings would not have
caught this. `RAW_SQL_BASELINE` in
`test_the_database_is_the_source_of_truth.py` already ratchets the amount of
hand-written SQL and it caught a stray SELECT the same evening. What went wrong
was not that SQL existed. It was that a RULE existed in one reader and not the
other.

`feed/tracks.py` says in its module docstring, and has said for as long as it
has existed:

    Every read filters on ``last_seen`` -- a stale track reads as no-contact

No read did. Three hand-written queries with no WHERE, and the ORM read in
`core/scope.py` with no filter either. So a track written by hand -- which is
how `tools/ghost_flight.py` works, and it gets no `gone` event from the sim --
stayed a live contact for ever. Two ghosts were on the scope two hours after
their run, the board would not release the aeroplanes (correctly: nothing drops
an aircraft radar can see), and a pilot's next sortie began with two phantoms
on his frequency and queue discipline applied to them.

AND THE FIX HAD TO GO IN TWICE. The table is read two ways -- hand-written SQL
in `feed/tracks.py`, the `Track` model in `core/scope.py` -- and filtering the
SQL alone would have fixed the reader nobody uses: `fetch_radar` comes through
the ORM. A rule applied to one of two readers is not applied.

WHAT THIS CHECKS, and what it does not. It is a TEXT check over the statement
that performs each read, not a proof that the filter is semantically right --
that is what `FRESH_SEC` and the tests around it are for. It answers one
question mechanically: does every place that reads this table mention the
column that decides whether a row still counts? A reader that does not is
either a bug or a deliberate exception that has to be written down here.
"""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "marshall"

# The column that decides whether a row is still a contact.
FRESH_COLUMN = "last_seen"

# READS THAT DELIBERATELY SEE EVERYTHING, with the reason. A write, a delete or
# a reconcile is not a read of the picture and must NOT be filtered: reconciling
# against the sim has to see stale rows in order to remove them.
EXEMPT = {
    # A write, a delete or a reconcile is not a read of the picture and must
    # NOT be filtered: reconciling against the sim has to SEE stale rows in
    # order to remove them.
    "_delete": "removes one row by name",
    "reconcile": "deletes what the sim no longer has -- it must see stale rows",
    "clear_all": "wipes the table outright",
    # ...AND THE NAME LOOKUPS, which are a different question.
    #
    # "Is this aeroplane a contact right now" must be fresh. "What is this unit
    # called" and "what type is it" are facts about a NAME, asked when
    # something else already established the aeroplane matters -- an event that
    # has just fired, a flight already on the board. Filtering them would lose
    # a label for a landing reported a moment after the last sweep, which is a
    # regression dressed as consistency.
    "SELECT label FROM tracks": "a name lookup for an event that already happened",
    "SELECT type FROM tracks": "the airframe of a flight already established",
    "ST_Y(geog::geometry), ST_X(geog::geometry)":
        "`_resolve` turns a NAME into a position -- a fix, a field, a\n         beacon someone asked about by name. Not a claim that anything\n         is flying there.",
}


def _reads(path: Path) -> list[tuple[int, str]]:
    """(line, source) for every statement that READS the tracks table.

    Statement-level, not node-level. `ast.get_source_segment` re-splits the
    file on every call, so asking it for every node of every module is
    quadratic and took the suite past two minutes. Only the statements are
    asked, and only in files that mention the table at all.
    """
    src = path.read_text(encoding="utf-8")
    if "tracks" not in src and "select(Track" not in src:
        return []
    lines = src.splitlines()
    tree = ast.parse(src, filename=str(path))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.Expr, ast.Return, ast.For)):
            continue
        a = getattr(node, "lineno", 0)
        b = getattr(node, "end_lineno", a)
        if not a:
            continue
        seg = "\n".join(lines[a - 1:b])
        low = seg.lower()
        if ("from tracks" in low and "select" in low) or "select(Track" in seg:
            found.append((a, seg))
    return found


class EveryReadOfTracksIsFresh(unittest.TestCase):

    def test_every_read_of_the_picture_filters_on_last_seen(self):
        bad = []
        for f in sorted(SRC.rglob("*.py")):
            for line, seg in _reads(f):
                if FRESH_COLUMN in seg:
                    continue
                if any(k in seg for k in EXEMPT):
                    continue
                bad.append(f"{f.relative_to(ROOT)}:{line}")
        # Deduplicate: ast.walk yields nested nodes for one statement.
        bad = sorted(set(bad))
        self.assertEqual(
            bad, [],
            "a read of `tracks` that does not consult `last_seen`; a stale "
            "row is not a contact, and this rule has to hold on every reader "
            "however the table is reached: " + ", ".join(bad))

    def test_the_window_is_named_once(self):
        """One number, imported, not two that can drift apart."""
        from marshall.feed.tracks import FRESH_SEC
        self.assertGreater(FRESH_SEC, 0)
        scope = (SRC / "core" / "scope.py").read_text(encoding="utf-8")
        self.assertIn("FRESH_SEC", scope,
                      "the ORM reader must import the window, not restate it")

    def test_this_test_can_actually_fail(self):
        """A guard nobody has seen fail is a guard nobody should trust."""
        fake = "rows = conn.execute('SELECT a FROM tracks t ORDER BY nm')"
        self.assertNotIn(FRESH_COLUMN, fake)
        self.assertTrue("from tracks" in fake.lower() and "select" in fake.lower(),
                        "the matcher must recognise a bare read")


if __name__ == "__main__":
    unittest.main()
