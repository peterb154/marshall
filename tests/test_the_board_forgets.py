"""A fact with no lifecycle is not state, it is sediment.

    "if the whole system requires claude code to keep the database clean, this
     isnt going to work."

Correct. Nothing ever deleted a flight row: `clear_mission` existed and was
called by exactly one thing, a human hitting `DELETE /flights`. Every row was
`mission = 'default'`, so yesterday's flights, today's and a test fixture's
occupied one bucket for ever; `player_leave_unit` freed the in-memory board and
not the row; and a mission load wiped nothing.

`tracks` has always done this correctly -- every radar sweep deletes whatever the
sim no longer has, nobody has ever cleaned it by hand, and it has never carried a
ghost. Same kind of fact, opposite treatment. See docs/STATE.md. [#119]
"""

from __future__ import annotations

import os
import unittest


class TheSortieIsIdentified(unittest.TestCase):
    """A row belongs to a LOADING of a mission, not to the string 'default'."""

    def test_the_flag_wins_so_tests_and_dry_runs_get_a_fixed_bucket(self):
        from marshall.atc import agent_atc as A
        was = os.environ.get("MARSHALL_MISSION")
        os.environ["MARSHALL_MISSION"] = "fixed"
        try:
            self.assertEqual(A.mission_instance(), "fixed")
        finally:
            if was is None:
                os.environ.pop("MARSHALL_MISSION", None)
            else:
                os.environ["MARSHALL_MISSION"] = was

    def test_an_unreachable_sim_degrades_rather_than_crashing(self):
        """The bridge is best-effort everywhere else and must be here too --
        but it says so, because sharing a bucket with previous sorties is
        exactly the failure this key exists to prevent."""
        from marshall.atc import agent_atc as A
        was = os.environ.get("MARSHALL_MISSION")
        os.environ.pop("MARSHALL_MISSION", None)
        addr = os.environ.get("DCS_GRPC_ADDR")
        os.environ["DCS_GRPC_ADDR"] = "127.0.0.1:1"      # nothing listens
        try:
            import importlib

            from marshall import config as C
            importlib.reload(C)
            self.assertEqual(A.mission_instance(default="fallback"), "fallback")
        finally:
            if addr:
                os.environ["DCS_GRPC_ADDR"] = addr
            if was is not None:
                os.environ["MARSHALL_MISSION"] = was
            import importlib

            from marshall import config as C
            importlib.reload(C)


class SrsNameIsABindingKey(unittest.TestCase):
    """The acute bug: a transmission carrying only an SRS name matched nothing
    and INSERTED, so a pilot got a fresh row every time he spoke. Three rows in
    thirty seconds, every `agree` writing into a row identifying nobody."""

    def _cols(self, fn_src: str) -> list[str]:
        import re
        m = re.search(r'for col(?:, val)? in \(([^)]*\))', fn_src, re.S)
        return re.findall(r'"(\w+)"', m.group(1)) if m else []

    def test_bind_matches_on_it(self):
        import inspect
        import sys
        sys.path.insert(0, "director")
        from tools import flights as F
        cols = self._cols(inspect.getsource(F._all_matching))
        self.assertIn("srs_name", cols)

    def test_and_it_is_the_WEAKEST_key(self):
        """A GUID or a track still wins. A name can be changed and two people
        can pick the same one -- it is last precisely because it is worst, and
        it is present because the alternative was minting a row."""
        import inspect
        import sys
        sys.path.insert(0, "director")
        from tools import flights as F
        cols = self._cols(inspect.getsource(F._all_matching))
        self.assertEqual(cols[-1], "srs_name")
        self.assertLess(cols.index("srs_guid"), cols.index("srs_name"))
        self.assertLess(cols.index("track_name"), cols.index("srs_name"))

    def test_find_agrees_with_bind(self):
        """Two orders of preference for one question is how the two come to
        disagree about who an aeroplane is."""
        import inspect
        import re
        import sys
        sys.path.insert(0, "director")
        from tools import flights as F
        # `find` pairs each column with its value, so take the column names.
        src = inspect.getsource(F.find)
        m = re.search(r"for col, val in \((.*?)\)\):", src, re.S)
        found = re.findall(r'\("(\w+)"', m.group(1)) if m else []
        self.assertEqual(found, self._cols(inspect.getsource(F._all_matching)))


class LeavingTheSlotEndsTheRow(unittest.TestCase):

    def test_the_release_path_forgets_the_row_too(self):
        """`Controller.release` has always explained why a leftover is dangerous
        and that reasoning was applied to the board and never to the table."""
        import inspect
        from marshall.atc import agent_atc as A
        self.assertIn("forget_flight", inspect.getsource(A.release_stale))

    def test_and_the_director_can_forget_one(self):
        import inspect
        import sys
        sys.path.insert(0, "director")
        from tools import flights as F
        src = inspect.getsource(F.forget)
        # ...with everything that hangs off it, or the orphans move down a level.
        self.assertIn("assigned_plans", src)
        self.assertIn("flight_member", src)


class SilenceExpiresIt(unittest.TestCase):
    """The belt to `player_leave_unit`'s braces: a client that vanishes without
    an event -- a crash, an alt-F4 -- leaves nothing to act on."""

    def test_it_asks_both_questions(self):
        import inspect
        import sys
        sys.path.insert(0, "director")
        from tools import flights as F
        src = inspect.getsource(F.expire)
        self.assertIn("updated_at", src, "the radio")
        self.assertIn("tracks", src, "and the scope")

    def test_and_something_actually_calls_it(self):
        """An endpoint nothing calls is the shape this project keeps finding.
        It rides the tick that already reconciles the in-memory board."""
        import inspect
        from marshall.atc import agent_atc as A
        src = inspect.getsource(A)
        i_rel = src.index("for gone in release_stale(")
        i_exp = src.index("_expired = expire_flights()")
        self.assertLess(abs(i_exp - i_rel), 2000,
                        "the two halves of one reconcile have drifted apart")


class IntentIsWrittenDown(unittest.TestCase):
    """He said "VFR to Batumi, visual 13" on his first call and at every
    handoff. `flights.intent` is read in four places and was written by none."""

    def test_the_classifier_can_carry_it(self):
        from marshall.atc import intents as I
        self.assertIn("wants", I.INTENT_SCHEMA["properties"])
        self.assertEqual(I.Intent(I.IntentKind.CHECK_IN, "Pony 1-1").wants, "")

    def test_any_transmission_may_carry_it(self):
        """Not an intent KIND of its own. A pilot states what he wants while
        checking in, while reporting a position, while asking for an approach."""
        from marshall.atc import controller as atc
        from marshall.atc import intents as I
        from marshall.core import route as R
        ctl = atc.Controller(R.BATUMI_ASR)
        ctl.check_in("Pony 1-1")
        I.dispatch(ctl, I.Intent(I.IntentKind.REPORT_BEACON, "Pony 1-1",
                                 wants="VFR to Batumi, visual 13"))
        self.assertEqual(ctl.get("Pony 1-1").wants, "VFR to Batumi, visual 13")

    def test_silence_never_erases_it(self):
        """He says it once. Every controller after that inherits it."""
        from marshall.atc import controller as atc
        from marshall.atc import intents as I
        from marshall.core import route as R
        ctl = atc.Controller(R.BATUMI_ASR)
        ctl.check_in("Pony 1-1")
        I.dispatch(ctl, I.Intent(I.IntentKind.CHECK_IN, "Pony 1-1",
                                 wants="ILS 21 left"))
        I.dispatch(ctl, I.Intent(I.IntentKind.REPORT_BEACON, "Pony 1-1"))
        self.assertEqual(ctl.get("Pony 1-1").wants, "ILS 21 left")

    def test_and_it_reaches_the_board(self):
        import inspect
        from marshall.atc import agent_atc as A
        src = inspect.getsource(A)
        self.assertIn('_agreed["intent"] = _ac.wants', src)


if __name__ == "__main__":
    unittest.main()
