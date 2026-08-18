"""The other direction, which nothing ever asked.

`decision.verify` asks which of the engine's facts did not survive being spoken
-- the DROP -- and it has caught real transmissions since #102. Nothing asked
the opposite: what did the controller say that nothing issued?

18 August. The engine issued no clearance for the entire sortie, because #180
had stalled the rung before it. The controller said:

    15:13:52  Sockeye, Kobuleti Clearance, cleared to Batumi, as filed,
              maintain five thousand, expect one zero thousand, departure
              frequency one two three decimal three, squawk ...
    15:14:33  Sockeye, readback correct, contact Kobuleti Ground ...

`assigned_plans` held no row for him and `flights` held no row at all. Ground
taxied him, Tower launched him, and he flew to another aerodrome on a clearance
that existed only in the air -- and every rung below believed it, because
nothing anywhere asked whether it was real. That is why it took a day of
reading transcripts to find, and why it is the last of the seven.

IT RECORDS, IT DOES NOT EDIT, and the distinction is the whole design. Cutting
the clause would be a regex guard on a model's words, which is #179 and which
this project has agreed is a bandaid over a prompt fault. The prompt fault is
fixed in the same commit -- the rules now say *a refusal is not a clearance; if
the tool did not hand you the words, you have none* -- and this exists so the
next occurrence is loud on the first transmission.

ANSWERED FROM THE DATABASE, not from what the turn is carrying, because what
the turn believes is precisely the thing in question. Which also means it must
be silent when it cannot ask: a missing flight row or an unreachable store is
an unanswerable question, not evidence of a lie, and a check that cries wolf
when Postgres hiccups is a check somebody switches off.  [#185]
"""

from __future__ import annotations

import unittest

from marshall.atc import board as F
from marshall.atc import clearance as C


class _Stubbed(unittest.TestCase):
    """A board and a clearance table, without a database.

    Stubbed at the two module functions the check actually calls, so the
    phrase-matching and the state logic are exercised for real.
    """

    FLIGHT: dict | None = {"id": 7, "callsign": "Sockeye"}
    ASSIGNED: dict | None = None

    def setUp(self):
        self._find, self._assigned = F.find, C.assigned
        F.find = lambda mission, callsign=None: (
            self.FLIGHT if self.FLIGHT
            and callsign and callsign.lower() == self.FLIGHT["callsign"].lower()
            else None)
        C.assigned = lambda flight_id: self.ASSIGNED

    def tearDown(self):
        F.find, C.assigned = self._find, self._assigned

    def claims(self, said: str) -> list[str]:
        return C.unbacked_claims("m", "Sockeye", said)


class AClearanceNobodyIssuedIsNoticed(_Stubbed):
    ASSIGNED = None

    def test_the_transmission_that_was_actually_made(self):
        got = self.claims(
            "Sockeye, Kobuleti Clearance, cleared to Batumi, as filed, "
            "maintain five thousand, expect one zero thousand, departure "
            "frequency one two three decimal three, squawk four six two one.")
        self.assertTrue(got)
        self.assertIn("CLEARED TO", got[0])

    def test_and_the_readback_that_followed_it(self):
        got = self.claims("Sockeye, readback correct, contact Kobuleti "
                          "Ground one two one decimal eight.")
        self.assertTrue(got)
        self.assertIn("READBACK CORRECT", got[0])

    def test_both_in_one_transmission_are_both_named(self):
        self.assertEqual(
            len(self.claims("cleared to Batumi, readback correct")), 2)


class AnOrdinaryTransmissionIsNotFlagged(_Stubbed):
    """The noise question. A check that fires on innocent phrasing is one
    somebody turns off, and then the real one is not caught either."""

    ASSIGNED = None

    def test_the_rest_of_the_sortie_is_quiet(self):
        for said in (
            "Sockeye, Kobuleti Ground, taxi to runway zero seven, hold short.",
            "Sockeye, Kobuleti Tower, runway zero seven, cleared for take-off, "
            "wind zero nine zero at five.",
            "Sockeye, Kobuleti Departure, radar contact.",
            "Sockeye, advise you have information Whiskey. Say your request.",
            "Sockeye, say again your callsign.",
            "Sockeye, no plan called Marlin is filed. On file: Domino.",
        ):
            with self.subTest(said[:44]):
                self.assertEqual(self.claims(said), [])


class ARealClearanceIsNotFlagged(_Stubbed):
    """The other half, and the one that decides whether this can stay on.

    If a genuinely issued clearance trips it, the log fills with false alarms
    on every normal sortie.
    """

    ASSIGNED = {"label": "Domino", "acked_at": None}

    def test_an_issued_clearance_may_be_read_out(self):
        self.assertEqual(
            self.claims("Sockeye, cleared to Batumi, as filed, "
                        "maintain five thousand."), [])

    def test_but_readback_correct_still_needs_the_acknowledgement(self):
        """ISSUED is not ACKNOWLEDGED -- the three states of #105, and the
        reason `clearance_state` exists. Saying his read-back was correct
        before it has been judged is the 11 August incident."""
        got = self.claims("Sockeye, readback correct.")
        self.assertTrue(got)
        self.assertIn("READBACK CORRECT", got[0])


class AndOnceHeHasReadItBackNothingIsFlagged(_Stubbed):
    ASSIGNED = {"label": "Domino", "acked_at": "2026-08-18T15:14:33"}

    def test_the_whole_exchange_is_clean(self):
        for said in ("Sockeye, cleared to Batumi, as filed.",
                     "Sockeye, readback correct, contact Ground one two one "
                     "decimal eight."):
            with self.subTest(said[:40]):
                self.assertEqual(self.claims(said), [])


class AnUnanswerableQuestionIsNotAnAccusation(_Stubbed):
    """Silence when it cannot ask, which is what keeps it trustworthy."""

    FLIGHT = None
    ASSIGNED = None

    def test_no_flight_row_reports_nothing(self):
        """He may be a VFR join, an air start, or simply not on the frag. Not
        knowing is not the same as catching him."""
        self.assertEqual(self.claims("Sockeye, cleared to Batumi"), [])

    def test_a_broken_store_reports_nothing(self):
        def _boom(*a, **k):
            raise RuntimeError("no Postgres DSN")
        F.find = _boom
        self.assertEqual(self.claims("Sockeye, cleared to Batumi"), [])


class ItRecordsRatherThanEdits(unittest.TestCase):
    """#179's rule, applied to the fix for #185 itself.

    The temptation here is enormous and it is the wrong instinct: the engine
    KNOWS the clearance is fictional, so why transmit it? Because deleting a
    clause mid-sentence is what produced "Sockeye, Kobuleti Tower, go ahead" --
    a filter cut the handoff out of "that's correct, contact Departure" and
    took the answer with it. The cause is in the prompt and belongs there.
    """

    def test_the_checker_returns_findings_and_never_a_reply(self):
        import inspect
        src = inspect.getsource(C.unbacked_claims)
        self.assertNotIn("replace(", src)
        self.assertNotIn("re.sub", src)

    def test_and_the_caller_only_records_it(self):
        import inspect
        from marshall.atc import agent_atc as A
        src = inspect.getsource(A)
        at = src.index("unbacked_claims")
        window = src[at:at + 700]
        self.assertIn('kind="unbacked"', window)
        self.assertNotIn("reply =", window,
                         "the claim check edits the transmission; it may only "
                         "record it — see #179")


if __name__ == "__main__":
    unittest.main()
