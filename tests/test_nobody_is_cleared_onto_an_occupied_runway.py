"""Two aeroplanes on one strip, and nothing was watching for it.

    "lack of separation for anything but an approach IS one of the issues I
     smelled"

`request_takeoff` asked exactly ONE question before clearing a man onto the
runway -- `self._owns("tower")`, which is #65's answer to "whose clearance is
this" -- and never asked whether anybody was already on it. So a man who had
just landed and not yet vacated did not stop a take-off clearance being issued
over him.

THE INVARIANT SAYS AN LLM NEVER INVENTS SEPARATION BETWEEN AIRCRAFT. It does
not say somebody else does it instead, and outside the arrival stack nobody
did: an aeroplane enters that stack only through `check_in` or
`seed_from_radar`, so a departure and an arrival at one field were sequenced
against each other by nothing, and neither were two departures.

WHY IT LOOKED UNBUILDABLE, and the reason is recorded in `report_down`'s own
docstring: an aerodrome row carries a position and a landing heading, and no
runway length and no thresholds -- so there is no polygon to test a point
against, and "is he on the runway" reads like a geometry question this system
cannot answer.

It is not a geometry question. `phases.py` already defines the state:

    landed    "Down and still on the runway, which is Tower's."
    taxi_in   "Off the runway, to a stand."

A phase is an observable that needs no survey, and the ladder already moves an
aeroplane between those two on facts the sim reports. The answer is a scan of
the board. [#170]
"""

from __future__ import annotations

import unittest

from marshall.atc import controller as atc
from tests import theatre as TH


def field_controller():
    """Tower at the arrival field, with two aeroplanes on his board."""
    c = atc.Controller(TH.the_arrival())
    c._me = TH.station("tower", TH.arrival())
    return c


def put(c, cs: str, phase: str):
    c.bind(cs, track=cs)
    c.get(cs).sortie_phase = phase
    return c.get(cs)


def said(c) -> str:
    return " ".join(x.text for x in c.out).lower()


class TestATakeOffIsRefusedWhileSomebodyIsOnTheRunway(unittest.TestCase):

    def setUp(self):
        self.c = field_controller()

    def test_the_clearance_is_not_issued(self):
        put(self.c, "Landed 1", "landed")
        put(self.c, "Waiting 2", "holding_short")
        self.c.out.clear()
        self.c.request_takeoff("Waiting 2")
        self.assertNotIn("cleared for take-off", said(self.c))

    def test_and_he_is_told_why(self):
        """A refusal a pilot cannot act on is a refusal he argues with."""
        put(self.c, "Landed 1", "landed")
        put(self.c, "Waiting 2", "holding_short")
        self.c.out.clear()
        self.c.request_takeoff("Waiting 2")
        self.assertIn("hold short", said(self.c))
        self.assertIn("traffic on the runway", said(self.c))

    def test_he_does_not_become_a_departure(self):
        """The phase must not move either. A man told to hold is on the
        holding point, and a ladder that advanced him would hand him to
        Departure while he is stopped on the tarmac."""
        put(self.c, "Landed 1", "landed")
        ac = put(self.c, "Waiting 2", "holding_short")
        self.c.request_takeoff("Waiting 2")
        self.assertEqual(ac.sortie_phase, "holding_short")

    def test_and_it_is_a_decision_the_engine_owns(self):
        """Not a sentence the agent composed. `decision.verify` can check a
        refusal reached the air only if the engine decided one."""
        put(self.c, "Landed 1", "landed")
        put(self.c, "Waiting 2", "holding_short")
        self.c.out.clear()
        self.c.request_takeoff("Waiting 2")
        # `Tx.decision`, not `.decided` -- `say(decided=...)` is the argument's
        # name and `decision` is the field it lands in. Reading the wrong one
        # returned "" for everything and the assertion would have passed for a
        # transmission that decided nothing at all.
        kinds = [getattr(getattr(x, "decision", None), "kind", "")
                 for x in self.c.out]
        self.assertIn("hold_short", kinds)


class TestAndClearedWhenTheRunwayIsFree(unittest.TestCase):
    """The other half, and the one that stops this being a brake."""

    def setUp(self):
        self.c = field_controller()

    def test_an_empty_runway_clears_him(self):
        put(self.c, "Waiting 2", "holding_short")
        self.c.out.clear()
        self.c.request_takeoff("Waiting 2")
        self.assertIn("cleared for take-off", said(self.c))

    def test_a_man_who_has_VACATED_does_not_block_him(self):
        """`taxi_in` is "off the runway, to a stand" -- he is on the taxiways
        and the strip is free. Blocking on him would stop every departure for
        as long as anybody was taxiing in."""
        put(self.c, "Parked 1", "taxi_in")
        put(self.c, "Waiting 2", "holding_short")
        self.c.out.clear()
        self.c.request_takeoff("Waiting 2")
        self.assertIn("cleared for take-off", said(self.c))

    def test_nor_does_a_man_holding_short_beside_him(self):
        """Two aeroplanes at the holding point are both OFF the runway. A
        check that counted them would deadlock the field: neither can be
        cleared while the other waits."""
        put(self.c, "First 1", "holding_short")
        put(self.c, "Second 2", "holding_short")
        self.c.out.clear()
        self.c.request_takeoff("Second 2")
        self.assertIn("cleared for take-off", said(self.c))


class TestTheRunwayBelongsToItsOwnAerodrome(unittest.TestCase):
    """A man on the runway at one field says nothing about the other.

    This is the failure shape this project keeps finding, applied in advance:
    a check that ignored the field would refuse every take-off on the map the
    moment anybody landed anywhere.
    """

    def test_a_landing_at_the_other_field_does_not_hold_him(self):
        c = atc.Controller(TH.the_arrival())
        c._me = TH.station("tower", TH.arrival())
        home = put(c, "Waiting 2", "holding_short")
        away = put(c, "Landed 1", "landed")
        # the other aeroplane is worked on the OTHER field's procedure
        away.profile = TH.two_approaches()[1]
        if c._key(away) == c._key(home):
            self.skipTest("this map publishes one aerodrome to depart from")
        c.out.clear()
        c.request_takeoff("Waiting 2")
        self.assertIn("cleared for take-off", said(c))


if __name__ == "__main__":
    unittest.main()
