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
        """He is on the taxiways and the strip is free. Blocking on him would
        stop every departure for as long as anybody was taxiing in.

        CHANGED ON PURPOSE, AND THE DIFF IS THE RECORD. This used to put him on
        the `taxi_in` RUNG and expect the runway free, which is the belief that
        caused the incursion of 30 August: the rung moves to `taxi_in` the
        moment Tower hands him to Ground, while the aeroplane is still rolling.
        Now he is vacated by the thing that actually means it -- HIS OWN
        REPORT, which is what `taxi_in()` is -- and the concern this test was
        written for still holds."""
        self.c.taxi_in("Parked 1")
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


class TestADepartingAeroplaneIsOnTheRunwayToo(unittest.TestCase):
    """THE COMMONEST WAY TO PUT TWO ON ONE STRIP, and it was invisible.

    The scan above looked only for `landed` -- a man who had come DOWN on it.
    Both of them LEAVING was not a state anybody asked about:

        15:58:06  Shooter, runway zero seven, cleared for take-off
        15:59:09  Sockeye, runway zero seven, cleared for take-off
        15:59:31  "Shooter is sitting on the runway right now, and Tower just
                   cleared me for takeoff"

    30 August, two singletons, and the ENGINE issued both.

    `departure` is the phase that STRADDLES (`phases.STRADDLES`): it runs from
    Tower's first word, through the roll, until Departure lets him go, "and
    most of that is spent stationary". So the phase alone cannot say whether he
    is still on the tarmac -- the fact that can is the one `phases` already
    names, positive radar evidence that he got airborne.
    """

    def test_a_departure_who_has_not_flown_holds_the_runway(self):
        c = field_controller()
        put(c, "Shooter", "departure")
        put(c, "Sockeye", "holding_short")
        c.out.clear()
        c.request_takeoff("Sockeye")
        self.assertIn("hold short", said(c))
        self.assertNotIn("cleared for take-off", said(c))

    def test_and_is_named_so_the_pilot_knows_what_is_out_there(self):
        c = field_controller()
        put(c, "Shooter", "departure")
        put(c, "Sockeye", "holding_short")
        c.out.clear()
        c.request_takeoff("Sockeye")
        self.assertIn("traffic on the runway", said(c))

    def test_but_once_he_is_airborne_the_runway_is_free(self):
        """Otherwise every field would seize after one departure: `departure`
        outlasts the roll by many miles."""
        c = field_controller()
        gone = put(c, "Shooter", "departure")
        gone.has_been_airborne = True
        put(c, "Sockeye", "holding_short")
        c.out.clear()
        c.request_takeoff("Sockeye")
        self.assertIn("cleared for take-off", said(c))


class TestNobodyIsClearedToLandOntoAnOccupiedRunway(unittest.TestCase):
    """`_on_the_runway` had ONE caller. Leaving a busy strip was refused;
    arriving onto the same one was never asked about.

        16:21:33  Sockeye, roger, cleared to land runway one three
        16:22:18  "Batumi Tower, I am still on the runway, shooter"
        16:22:34  "sockeye is down on the runway, and I almost ran into shooter"

    A LATE CLEARANCE, NOT A REFUSAL, which is the difference from take-off:
    "hold short" is something a stationary aeroplane can do and a man on final
    cannot. He is told what is on the runway and keeps coming.
    """

    def _on_final(self, c, cs="Sockeye"):
        ac = put(c, cs, "approach")
        ac.has_been_airborne = True
        ac.on_visual = True
        return ac

    def test_he_is_not_cleared_to_land_over_somebody(self):
        c = field_controller()
        put(c, "Shooter", "landed")
        self._on_final(c)
        c.out.clear()
        c.report_landed("Sockeye")
        self.assertNotIn("cleared to land", said(c))

    def test_he_is_told_to_continue_and_what_is_on_it(self):
        c = field_controller()
        put(c, "Shooter", "landed")
        self._on_final(c)
        c.out.clear()
        c.report_landed("Sockeye")
        self.assertIn("continue approach", said(c))
        self.assertIn("shooter", said(c))

    def test_the_man_on_the_runway_is_asked_to_report_clear(self):
        """WITHOUT THIS IT DEADLOCKS. His report is the only thing that frees
        the strip, and a pilot who has landed and gone quiet will never make it
        unprompted -- so the aeroplane on final is told to continue for ever.
        A real Tower asks, and nobody asked Shooter anything on 30 August."""
        c = field_controller()
        put(c, "Shooter", "landed")
        self._on_final(c)
        c.out.clear()
        c.report_landed("Sockeye")
        to_shooter = " ".join(x.text for x in c.out
                              if "shooter" in x.text.lower()).lower()
        self.assertIn("report clear of the runway", to_shooter)

    def test_and_that_report_frees_it(self):
        c = field_controller()
        put(c, "Shooter", "landed")
        self._on_final(c)
        c.taxi_in("Shooter")
        c.out.clear()
        c.report_landed("Sockeye")
        self.assertIn("cleared to land", said(c))

    def test_a_departing_aeroplane_blocks_a_landing_as_well(self):
        c = field_controller()
        put(c, "Shooter", "departure")
        self._on_final(c)
        c.out.clear()
        c.report_landed("Sockeye")
        self.assertNotIn("cleared to land", said(c))

    def test_a_clear_runway_still_clears_him(self):
        c = field_controller()
        self._on_final(c)
        c.out.clear()
        c.report_landed("Sockeye")
        self.assertIn("cleared to land", said(c))


if __name__ == "__main__":
    unittest.main()
