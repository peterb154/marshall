"""The engine's outbox, and why reading it is taking it.

A directive on a real sortie contained BOTH a hold and a clearance -- 7 turns
in 97:

    "Hammer one one, hold at BATUMI as published, maintain five thousand.
     | Hammer one one, cleared radar approach runway 13"

Those were never one decision. They were two turns' worth, because the drain
was conditional: it ran only when `intents.dispatch` returned True, so anything
queued on a turn it did not handle stayed in the list and reappeared beside the
next turn's words.

Contradictory instructions in one transmission, from the half of the system
that exists to be the reliable one.
"""

import unittest

from marshall.atc import controller as atc
from marshall.atc import intents as I
from marshall.core import route as R


class TestReadingTheOutboxTakesIt(unittest.TestCase):

    def setUp(self):
        self.ctl = atc.Controller(R.BATUMI_ASR)
        self.ctl.t = 0.0

    def test_take_out_returns_and_clears(self):
        self.ctl.say("Sockeye", "one")
        self.ctl.say("Sockeye", "two")
        got = self.ctl.take_out()
        self.assertEqual([t.text for t in got], ["one", "two"])
        self.assertEqual(self.ctl.out, [], "the outbox was read but not taken")

    def test_a_second_read_is_empty(self):
        self.ctl.say("Sockeye", "one")
        self.ctl.take_out()
        self.assertEqual(self.ctl.take_out(), [])

    def test_TAKING_IS_NOT_THE_CALLERS_DECISION(self):
        """The whole bug. Draining was a step a caller could skip, and on the
        turns it skipped, the words leaked into the next one.

        Asserted by exhaustion: no matter which way the outbox is read, it is
        empty afterwards. There is no accessor that hands the list over and
        leaves it in place.
        """
        self.ctl.say("Sockeye", "one")
        got = self.ctl.take_out()
        self.assertTrue(got)
        self.assertFalse(self.ctl.out)
        # And the list handed back is not the live one, so a caller mutating
        # what he was given cannot put words back on the air.
        got.append("smuggled")
        self.assertEqual(self.ctl.out, [])


class TestAnUnhandledTurnDoesNotLeak(unittest.TestCase):
    """The exact path that produced it."""

    def setUp(self):
        self.ctl = atc.Controller(R.BATUMI_ASR)
        self.ctl.t = 0.0

    def test_dispatch_returning_false_leaves_nothing_behind(self):
        self.ctl.say("Sockeye", "queued before an unhandled intent")
        handled = I.dispatch(self.ctl, I.Intent(kind=I.IntentKind.UNKNOWN,
                                                callsign="Sockeye"))
        self.assertFalse(handled)
        # The bridge drains regardless now -- see `separation_context`.
        self.ctl.take_out()
        self.assertEqual(self.ctl.out, [])

    def test_a_hold_and_a_clearance_cannot_share_a_directive(self):
        """Reconstructed: queue a hold, fail to drain the old way, then clear.

        With the conditional drain both reached one directive. Taking the
        outbox each turn is what makes that impossible rather than unlikely.
        """
        self.ctl.say("Hammer 1-1", "hold at BATUMI as published, maintain five thousand.")
        first = " | ".join(t.text for t in self.ctl.take_out())
        self.ctl.say("Hammer 1-1", "cleared radar approach runway 13.")
        second = " | ".join(t.text for t in self.ctl.take_out())
        for one in (first, second):
            with self.subTest(directive=one[:40]):
                self.assertFalse("hold at" in one and "cleared" in one,
                                 "a hold and a clearance in one transmission")


if __name__ == "__main__":
    unittest.main()
