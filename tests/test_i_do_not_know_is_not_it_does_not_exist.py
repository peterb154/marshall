"""Three places where the language brain stated an absence as a fact. [#153]

    "I do not know" and "it does not exist" are two different sentences and only
    one of them is usually true.

Each site had a comment nearby stating the rule it broke, which is what makes
this a shape rather than three bugs. `atc/frequencies.py` is the fixed one to
copy -- *"an empty answer is a real answer here. It means no published list knows
this seat, and the tool must say so rather than read him somebody else's map."*

    1  A MERGE TREATS False AND 0 AS "NOT KNOWN".  `board._merge`
       `False in (None, "", 0)` is True in Python. Reproduced: a survivor holding
       `on_visual=False`, `approaches_flown=0`, `missed_count=0`,
       `assigned_ft=0`, `sequence_no=0` was overwritten from the losing row with
       `[True, 3, 8000, 4, 2]`. `on_visual` means "he is flying it himself, the
       talk-down must stop", so the merge stopped a talk-down for a man who never
       said he had anything in sight.

    2  A FAILED RADAR READ IS RETURNED AS AN EMPTY SKY.  `director/app.py`
       `except Exception: got = []`, two lines under its own comment saying
       `contacts` returns None rather than [] precisely so a cold cache can be
       told from an empty sky. Silent, as well: a double radar failure and a
       quiet night produced the same payload.

    3  NAVIGATION CAPABILITY FROM AN ABSENT AIRFRAME.  `plans.nav_of`
       `if not aircraft_type: return "dr"`. Reproduced: `nav_of(None)` -> "dr" ->
       "Dead reckoning only -- a compass, a watch and a map... he cannot tell you
       where he is more precisely than a landmark." That line goes into the
       controller's prompt through `clearance.flight_plan_help`, so the agent
       VOICES it -- a pilot in an F-16 whose track had not been correlated yet
       got a controller talking him down like a Mustang. There was no output
       meaning "we do not know".
"""

import ast
import unittest
import unittest.mock as mock
from pathlib import Path

from marshall.atc import board as B, plans as P

ROOT = Path(__file__).resolve().parents[1]


class TestAMergeKeepsAnAnswerOfNo(unittest.TestCase):
    """Site 1. Acceptance 1: `on_visual=False` survives a merge."""

    # The four falsy-but-meaningful columns, and the one that reaches a pilot.
    KEEP = {"id": 1, "callsign": "Pony 1-1", "on_visual": False,
            "approaches_flown": 0, "missed_count": 0, "assigned_ft": 0,
            "sequence_no": 0, "intent": "", "destination": None}
    LOSE = {"id": 2, "callsign": "Pony 1-1", "on_visual": True,
            "approaches_flown": 3, "missed_count": 2, "assigned_ft": 8000,
            "sequence_no": 4, "intent": "land", "destination": "Batumi"}

    def merge(self, keep=None, lose=None):
        """Run the real `_merge` and hand back what it wrote, column -> value."""
        sql = []

        class Conn:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def execute(s, q, params=None):
                sql.append((q, params))
                return s

        class Pool:
            def connection(s): return Conn()

        with mock.patch.object(B, "get_pool", Pool), \
             mock.patch.object(B, "get", lambda i: None):
            B._merge([dict(keep or self.KEEP), dict(lose or self.LOSE)])
        for q, params in sql:
            if q.startswith("UPDATE"):
                cols = [c.split("=")[0].strip()
                        for c in q.split("SET")[1].split(", updated_at")[0].split(",")]
                return dict(zip(cols, params))
        return {}

    def test_he_is_not_on_a_visual_and_stays_not_on_a_visual(self):
        """The one that reaches a pilot: a deliberate False being read as unset
        turned the talk-down off for somebody who never called the field."""
        self.assertNotIn("on_visual", self.merge())

    def test_nor_do_the_counts_and_the_altitude_move(self):
        wrote = self.merge()
        for col in ("approaches_flown", "missed_count", "assigned_ft",
                    "sequence_no"):
            with self.subTest(col=col):
                self.assertNotIn(col, wrote)

    def test_what_the_survivor_was_never_told_it_still_takes(self):
        """The merge must go on doing its job. An empty string and a NULL are
        genuinely unset, and the losing row's answer is better than nothing."""
        wrote = self.merge()
        self.assertEqual(wrote.get("intent"), "land")
        self.assertEqual(wrote.get("destination"), "Batumi")

    def test_and_a_no_can_still_be_filled_in_from_a_row_that_has_one(self):
        """The other direction: an unset survivor takes a False. `False` is an
        answer whichever row is holding it."""
        keep = dict(self.KEEP, on_visual=None)
        wrote = self.merge(keep=keep, lose=dict(self.LOSE, on_visual=False))
        self.assertIs(wrote.get("on_visual"), False)

    def test_the_predicate_says_what_it_means(self):
        self.assertTrue(B._unset(None))
        self.assertTrue(B._unset(""))
        self.assertFalse(B._unset(False))
        self.assertFalse(B._unset(0))
        self.assertFalse(B._unset(0.0))


class TestAFailedRadarReadIsReportedAsFailed(unittest.TestCase):
    """Site 2. Acceptance 2.

    Read as SOURCE. `director/app.py` is a separate deployable -- strands,
    fastapi, the gRPC stubs -- and the suite cannot import it; that is the same
    reasoning `tests/test_director_sql.py` is built on, and the fault is visible
    in the source either way.
    """

    SRC = ROOT / "director" / "app.py"

    def endpoint(self):
        src = self.SRC.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.FunctionDef) and node.name == "radar_endpoint":
                return node, src
        self.fail("director/app.py has no radar_endpoint")

    def test_no_handler_answers_a_failure_with_an_empty_sky(self):
        node, _ = self.endpoint()
        for h in (n for n in ast.walk(node) if isinstance(n, ast.ExceptHandler)):
            for a in (n for n in ast.walk(h) if isinstance(n, ast.Assign)):
                for v in (a.value.elts if isinstance(a.value, ast.Tuple)
                          else [a.value]):
                    self.assertFalse(
                        isinstance(v, ast.List) and not v.elts,
                        "a radar read that failed is being answered with [], "
                        "which says radar looked and nothing is flying")

    def test_the_failure_is_not_swallowed_in_silence(self):
        node, src = self.endpoint()
        body = "\n".join(src.splitlines()[node.lineno - 1:node.end_lineno])
        self.assertIn("log.warning", body,
                      "a double radar failure left no record at all")

    def test_the_payload_says_which_of_the_three_it_is(self):
        node, src = self.endpoint()
        body = "\n".join(src.splitlines()[node.lineno - 1:node.end_lineno])
        self.assertIn('"radar_read"', body)
        for word in ('"cache"', '"live"', '"failed"'):
            with self.subTest(word=word):
                self.assertIn(word, body)


class TestAnUnknownAirframeIsNotAMustang(unittest.TestCase):
    """Site 3. Acceptance 3.

    `clearance.aircraft_type` returns None both when the pilot has not been
    correlated to a track yet and when the row is missing. Neither is a
    statement about what he is flying.
    """

    def test_nobody_has_said_what_he_is_flying(self):
        self.assertEqual(P.nav_of(None), "")
        self.assertEqual(P.nav_of(""), "")
        self.assertEqual(P.nav_of("   "), "")

    def test_and_the_controller_is_told_that_rather_than_a_capability(self):
        line = P.help_level(P.nav_of(None))
        self.assertTrue(line.strip())
        low = line.lower()
        self.assertIn("unknown", low)
        self.assertIn("ask him", low)

    def test_he_is_not_described_as_a_man_with_a_compass_and_a_watch(self):
        """The exact sentence the agent used to voice, for a pilot in an F-16
        whose track had not been correlated yet."""
        line = P.help_level(P.nav_of(None)).lower()
        self.assertNotIn("dead reckoning", line)
        self.assertNotIn("compass", line)

    def test_an_unlisted_TYPE_is_a_different_question_and_keeps_its_answer(self):
        """We know the airframe; it is not in the table. That default is
        generous on purpose and does not move."""
        self.assertEqual(P.nav_of("F-16C_50"), "ins")
        self.assertEqual(P.nav_of("Su-27"), "ins")

    def test_the_hangar_is_unchanged(self):
        self.assertEqual(P.nav_of("P-51D-30-NA"), "adf")
        self.assertEqual(P.nav_of("P-47D-30"), "dr")

    def test_every_level_including_the_unknown_one_says_what_to_do(self):
        for nav in ("ins", "adf", "dr", ""):
            with self.subTest(nav=nav):
                self.assertTrue(P.help_level(nav).strip())


if __name__ == "__main__":
    unittest.main()
