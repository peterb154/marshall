"""Static guards on the director's track cache, from bugs that actually bit.

The director is a separate deployable with its own dependencies -- PostGIS, the
gRPC stubs, strands -- so importing it here is not on. But the two things that
have gone wrong in this file are both visible in the SOURCE, and a check that
runs in the ordinary suite is worth far more than one that needs a database:

  A PLACEHOLDER COUNT. `INSERT INTO tracks` once had eight %s and nine
  parameters. psycopg raises, the streamer thread dies, and NOTHING ELSE
  CHANGES -- the reads still work, they just return an empty picture. Radar
  read "no contacts" to everybody for twelve hours and the first anyone knew
  was a pilot asking why the controller could not see him.

  A ROW SHAPE. `_clusters` is called from two places with rows built by two
  different queries, and `near()` unpacked a fixed six fields. The row has
  grown twice since -- groundspeed for the descent planner, then the player's
  name for identity -- and each time it became a ValueError that fires ONLY
  when two contacts are compared. One aeroplane never reaches it. Every test
  with a single ship passes. The failure was waiting for the first night a
  second pilot was invited.

Both are cheap to state and neither can be caught by testing with one aircraft,
which is the condition this project has been in for a fortnight.
"""

import ast
import re
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "director" / "tools" / "tracks.py"


class TestTheInsertMatchesItsParameters(unittest.TestCase):
    def test_every_placeholder_has_a_value(self):
        tree = ast.parse(SRC.read_text(encoding="utf-8"))
        checked = 0
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "execute" and len(node.args) == 2):
                continue
            sql = node.args[0]
            if not (isinstance(sql, ast.Constant) and isinstance(sql.value, str)):
                continue
            params = node.args[1]
            if not isinstance(params, ast.Tuple):
                continue
            checked += 1
            self.assertEqual(
                sql.value.count("%s"), len(params.elts),
                f"line {node.lineno}: {sql.value.count('%s')} placeholders, "
                f"{len(params.elts)} parameters. This exact mismatch killed the "
                f"track streamer for twelve hours and radar read 'no contacts' "
                f"to everyone.")
        self.assertGreater(checked, 0, "found no parameterised queries to check")


class TestBothQueriesFeedTheSameClusterer(unittest.TestCase):
    """`_clusters` takes rows from two queries. They have to be the same shape.

    Not a style point. `near()` reads altitude, heading, range and radial by
    position, so a query that omits a column silently shifts every field after
    it -- and the symptom is not an error, it is two aeroplanes a mile apart
    being called a formation, or not.
    """

    def _columns(self, sql: str) -> list[str]:
        # The LAST SELECT before "FROM tracks" -- the CTE has its own SELECT and
        # taking the first one parses the wrong query entirely.
        end = sql.index("FROM tracks")
        body = sql[sql.rindex("SELECT", 0, end) + len("SELECT"):end]
        # Split on commas that are not inside a function call.
        out, depth, cur = [], 0, ""
        for ch in body:
            depth += ch == "("
            depth -= ch == ")"
            if ch == "," and depth == 0:
                out.append(cur.strip())
                cur = ""
            else:
                cur += ch
        out.append(cur.strip())
        # Aliases are cosmetic -- "… / 1852.0 AS nm" and "… / 1852.0" are the
        # same column, and only ORDER BY cares about the name. What must match
        # is the EXPRESSION and its position.
        return [re.sub(r"\s+AS\s+\w+\s*$", "", re.sub(r"\s+", " ", c), flags=re.I)
                for c in out if c.strip()]

    def test_the_leading_columns_agree(self):
        text = SRC.read_text(encoding="utf-8")
        queries = [m for m in re.findall(r'"""(\s*WITH bcn AS.*?)"""', text, re.S)]
        self.assertGreaterEqual(len(queries), 2,
                                "expected the picture and formation queries")
        shapes = [self._columns(q) for q in queries]
        first = shapes[0]
        for other in shapes[1:]:
            n = min(len(first), len(other))
            self.assertEqual(
                first[:n], other[:n],
                "the two queries that feed _clusters disagree on column order; "
                "near() reads by position and will compare the wrong fields")


class TestTheClustererDoesNotDemandAFixedWidth(unittest.TestCase):
    def test_near_reads_by_index_not_by_unpacking(self):
        """The row has grown twice and will grow again.

        Tuple unpacking pins the width, and the resulting ValueError only
        appears with two contacts on the scope -- so it survives every
        single-ship test and waits for a busy night.
        """
        text = SRC.read_text(encoding="utf-8")
        body = text[text.index("def near("):]
        body = body[:body.index("\n    groups")]
        offenders = [ln.strip() for ln in body.splitlines()
                     if re.match(r"\s*(_|\w+)(\s*,\s*(_|\w+))+\s*=\s*[ab]\s*$", ln)]
        self.assertEqual(offenders, [],
                         "near() unpacks a fixed-width row: " + "; ".join(offenders))


if __name__ == "__main__":
    unittest.main()
