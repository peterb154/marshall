"""Sent away and given an order by the man who sent him.

    ATC: "Bandit, contact Los Angeles Center, one three three decimal four.
          Good day. Hold at present position, maintain one zero thousand..."

Seen on the first Nevada stack run. Each half is defensible on its own -- the
arrivals were outside Approach's twenty-five miles so Center did own them, and an
aircraft third in the queue does get a level -- and both reached the radio.

`reconcile` exists precisely to stop that, and it was arbitrating THREE
authorities out of four. A handoff was decided by `next_controller` two hundred
lines further down and merged into the reply afterwards, so a turn that produced
both produced both.

A HANDOFF IS THE STRONGEST ANSWER to "who owns this aeroplane": somebody else
does. A REFUSAL survives it, because a refusal is not an instruction -- "take-off
is Tower's, contact Kobuleti Tower one three three decimal zero" IS the handoff,
with its reason attached, and dropping it would leave a pilot sent away with no
idea why. [#115]
"""

from __future__ import annotations

import unittest

from marshall.atc import agent_atc as A
from marshall.atc import decision as D


class _Station:
    def __init__(self, name="Los Angeles Center"):
        self.name = name


class AHandoffSilencesTheInstruction(unittest.TestCase):

    def test_a_hold_does_not_go_out_with_a_handoff(self):
        hold = D.Decision(kind="hold", to="Bandit", altitude_ft=10000)
        directive, _s, _v, dropped, kept = A.reconcile(
            "Bandit, hold at present position, maintain one zero thousand.",
            "", "", None, [hold], handoff=_Station())
        self.assertEqual(directive, "")
        self.assertNotIn(hold, kept, "the decision survives and #79 repairs it "
                                     "straight back on to the air")
        self.assertIn("handed to Los Angeles Center", dropped)

    def test_the_vector_goes_too(self):
        """A heading is an instruction like any other."""
        _d, _s, vectoring, _w, _k = A.reconcile(
            "", "", "turn left heading zero eight zero", None,
            [D.Decision(kind="vector", to="Bandit", heading_deg=80)],
            handoff=_Station())
        self.assertEqual(vectoring, "")

    def test_but_a_refusal_survives_because_it_IS_the_handoff(self):
        """Q5 on the card: Ground refuses the runway and names Tower. The
        refusal and the handoff are one act, and suppressing the words would
        send a pilot away with no reason given."""
        refuse = D.Decision(kind="refuse", to="Sockeye", role="tower",
                            station="Kobuleti Tower", frequency_mhz=133.0)
        directive, _s, _v, _w, kept = A.reconcile(
            "Sockeye, take-off is Tower's, contact Kobuleti Tower one three "
            "three decimal zero.", "", "", None, [refuse],
            handoff=_Station("Kobuleti Tower"))
        self.assertIn(refuse, kept)
        self.assertIn("Tower", directive)

    def test_the_stack_still_goes(self):
        """It is about the OTHER aircraft, and they have not been handed
        anywhere."""
        _d, stack, _v, _w, _k = A.reconcile(
            "Bandit, hold at present position.", "Sockeye cleared, Hoover 11000",
            "", None, [D.Decision(kind="hold", to="Bandit", altitude_ft=10000)],
            handoff=_Station())
        self.assertIn("Hoover", stack)

    def test_no_handoff_changes_nothing(self):
        hold = D.Decision(kind="hold", to="Bandit", altitude_ft=10000)
        directive, _s, _v, dropped, kept = A.reconcile(
            "Bandit, hold at present position.", "", "", None, [hold])
        self.assertIn("hold", directive)
        self.assertEqual(dropped, "")
        self.assertIn(hold, kept)


class ItIsDecidedBeforeTheInstructionsAreSettled(unittest.TestCase):
    """Source order, because the fault WAS the order. `next_controller` ran
    after `settle`, so no arbitration could have included it."""

    def test_the_handoff_is_computed_above_settle(self):
        import inspect
        src = inspect.getsource(A)
        i_nxt = src.index("nxt = next_controller(")
        i_settle = src.index("directive, stack, vectoring, _g, dropped = settle(")
        self.assertLess(i_nxt, i_settle,
                        "the handoff is decided after the instructions again")

    def test_and_it_is_passed_in(self):
        import inspect
        src = inspect.getsource(A.settle)
        self.assertIn("handoff=handoff", src)


if __name__ == "__main__":
    unittest.main()
