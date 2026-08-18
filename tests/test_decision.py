"""Decisions rather than sentences, and why the difference is checkable.

    "I'm worried that the deterministic part is too rigid and will be difficult
     to maintain at scale."

The rigidity is not in the determinism -- it is in the PROSE. `controller.py`
carries 94 long f-strings and some 506 words of English, and adding a procedure
means writing more English inside Python.

It is also where the conflicts come from. Both halves compose sentences, so two
finished utterances have to be reconciled, and that reconciliation is the guards
-- 27 firings on the last sortie, each a referee catching a disagreement AFTER
both halves had spoken.

A DECISION IS VERIFIABLE AND A SENTENCE IS NOT, which is what this buys today:
three of seventeen issued altitudes never reached the air on the last sortie and
nothing noticed.
"""

import unittest

from marshall.atc import controller as atc
from marshall.atc import decision as D
from marshall.atc import intents as I
from marshall.core import route as R


class TestADecisionCarriesFactsNotWords(unittest.TestCase):

    def test_only_the_numbers_a_pilot_must_receive(self):
        d = D.Decision(kind="hold", to="Sockeye", altitude_ft=4000,
                       note="because somebody is ahead of you")
        self.assertEqual(d.facts(), {"altitude_ft": 4000})

    def test_prose_is_never_a_fact(self):
        """`note` is excluded on purpose -- a verifier that looked for a reason
        would fail on every rephrasing, which is the trap the fuzzy `voiced`
        check in /diag fell into."""
        d = D.Decision(kind="ack", to="Sockeye", note="anything at all")
        self.assertEqual(d.facts(), {})

    def test_the_kind_survives_a_change_of_phraseology(self):
        """Named for what the controller DID, not for the words. "cleared for
        the surveillance approach runway one three" is one era, one language
        and one field; "cleared_approach" is none of those."""
        for kind in ("hold", "cleared_approach", "taxi", "handoff", "refuse"):
            with self.subTest(kind=kind):
                self.assertIn(kind, D.KINDS)


class TestVerifyingWhatWasActuallySaid(unittest.TestCase):
    """The check a sentence cannot support."""

    def setUp(self):
        self.d = D.Decision(kind="cleared_approach", to="Sockeye",
                            altitude_ft=2000, runway="13")

    def test_a_reply_carrying_the_numbers_passes(self):
        said = ("Sockeye, cleared radar approach runway one three, "
                "maintain two thousand.")
        self.assertEqual(D.verify(self.d, said), [])

    def test_A_VAGUE_REPLY_IS_CAUGHT(self):
        """The failure that went unnoticed on a real sortie: the engine
        decided an altitude and a clearance, and the pilot heard neither."""
        lost = D.verify(self.d, "Sockeye, cleared for the approach.")
        self.assertIn("two thousand", lost)
        self.assertIn("one three", lost)

    def test_digits_count_as_the_fact_now_that_the_check_ENFORCES(self):
        """CHANGED DELIBERATELY, 10 August, when `verify` stopped being advisory.

        This used to assert that "cleared runway 13, maintain 2000" reported
        BOTH facts missing -- a reply written in digits was treated as a miss,
        which was a cheap nudge towards proper phraseology while the check only
        printed.

        It now REPAIRS the transmission (#79), and that changes the arithmetic.
        `for_voice` does not spell digits out, so "runway 13" reaches Polly and
        the pilot hears "thirteen" -- non-standard words, but unmistakably the
        right runway. Flagging it would append a second, complete take-off
        clearance to a transmission that already carried one.

        A duplicated clearance on a live frequency is worse than a controller
        saying "thirteen" instead of "one three". So the same fact in digits is
        a PASS, and the phraseology question belongs to `for_voice`, where every
        transmission passes, rather than to the verifier.
        """
        self.assertEqual(D.verify(self.d, "cleared runway 13, maintain 2000"), [])

    def test_punctuation_and_case_do_not_matter(self):
        said = "SOCKEYE — CLEARED, RUNWAY ONE THREE; MAINTAIN TWO THOUSAND."
        self.assertEqual(D.verify(self.d, said), [])

    def test_it_does_not_try_to_understand_the_reply(self):
        """A verifier that reasons is a second model with a second opinion,
        which is the problem rather than the fix. It checks for the words and
        nothing else."""
        self.assertEqual(D.verify(D.Decision(kind="ack", to="X"), ""), [])


class TestTheEngineEmitsThemWhereItMatters(unittest.TestCase):
    """The conflict-prone paths first: hold, clear, taxi, take-off, refusal."""

    def setUp(self):
        self.ctl = atc.Controller(R.BATUMI_ASR)
        self.ctl.t = 0.0
        # CLEARED, because these are about the RUNWAY on a taxi instruction
        # and #181 made a taxi instruction conditional on being cleared at all.
        # Without this they assert on a refusal, which carries no runway and
        # would read as the two seats disagreeing.
        self.ctl.get("Sockeye").clearance_agreed = True

    def decided(self):
        return [tx.decision for tx in self.ctl.take_out() if tx.decision]

    def test_a_taxi_clearance_carries_its_runway(self):
        self.ctl._me = R.KOB_GROUND
        I.dispatch(self.ctl, I.Intent(kind=I.IntentKind.REQUEST_TAXI,
                                      callsign="Sockeye"))
        got = self.decided()
        self.assertTrue(got)
        self.assertEqual(got[0].kind, "taxi")
        self.assertTrue(got[0].runway)

    def test_a_take_off_clearance_names_the_same_runway(self):
        """A taxi instruction and a take-off clearance that disagree is a jet
        lined up on the wrong strip -- and now that is checkable rather than
        a matter of reading two f-strings."""
        self.ctl._me = R.KOB_GROUND
        I.dispatch(self.ctl, I.Intent(kind=I.IntentKind.REQUEST_TAXI,
                                      callsign="Sockeye"))
        taxi = self.decided()[0]
        self.ctl._me = R.KOB_TOWER
        I.dispatch(self.ctl, I.Intent(kind=I.IntentKind.REQUEST_TAKEOFF,
                                      callsign="Sockeye"))
        dep = self.decided()[0]
        self.assertEqual(taxi.runway, dep.runway)

    def test_a_refusal_says_whose_it_is_and_on_what_frequency(self):
        self.ctl._me = R.KOB_GROUND
        I.dispatch(self.ctl, I.Intent(kind=I.IntentKind.REQUEST_TAKEOFF,
                                      callsign="Sockeye"))
        got = self.decided()[0]
        self.assertEqual(got.kind, "refuse")
        self.assertEqual(got.role, "tower")
        self.assertTrue(got.frequency_mhz)

    def test_an_unconverted_site_still_works(self):
        """The phrasebook is being moved out incrementally. A site that has
        not been converted carries no decision and behaves exactly as before,
        which is what makes this safe to do a few at a time."""
        self.ctl.say("Sockeye", "something not yet converted")
        self.assertEqual(self.decided(), [])


if __name__ == "__main__":
    unittest.main()
