"""A runway is a resource with an owner, not a state to be inferred.

    "we need to have some form of ownership for each runway and only one
     aircraft or flight can use it at a time"

It was a SCAN -- "is anybody in a state that implies he is on the strip" -- and
both of 30 August's incursions were that inference being wrong. `departure` was
not in the list, so two aeroplanes were cleared to take off. Then `taxi_in` was,
and it lies: the rung moves when Tower hands a landed aeroplane to Ground while
he is still rolling.

A guess that has to enumerate every state meaning "on the runway" will keep
missing one. A holder cannot fail that way -- the engine records the decision it
made. This file tests the properties the scan could not have.
"""
from __future__ import annotations

import unittest

from marshall.atc import controller as atc
from tests import theatre as TH


def tower():
    c = atc.Controller(TH.the_arrival())
    c._me = TH.station("tower", TH.arrival())
    return c


def put(c, cs, phase, airborne=False, vacated=False):
    c.bind(cs, track=cs)
    ac = c.get(cs)
    ac.sortie_phase = phase
    ac.has_been_airborne = airborne
    ac.runway_vacated = vacated
    return ac


def said(c) -> str:
    return " ".join(x.text for x in c.out).lower()


class TheRunwayHasOneHolder(unittest.TestCase):

    def test_a_take_off_clearance_takes_it(self):
        c = tower()
        put(c, "First 1", "holding_short")
        c.request_takeoff("First 1")
        self.assertIn("cleared for take-off", said(c))
        self.assertEqual(c._on_the_runway(c.get("Second 2")), "First 1")

    def test_and_the_next_man_is_refused_by_name(self):
        c = tower()
        put(c, "First 1", "holding_short")
        put(c, "Second 2", "holding_short")
        c.request_takeoff("First 1")
        c.out.clear()
        c.request_takeoff("Second 2")
        self.assertIn("hold short", said(c))
        self.assertNotIn("cleared for take-off", said(c))

    def test_his_own_hold_does_not_block_him(self):
        """Otherwise the holder could never be answered again -- and a pilot who
        reads back and asks a question would be told to hold short of a runway
        he is already rolling down."""
        c = tower()
        put(c, "First 1", "holding_short")
        c.request_takeoff("First 1")
        self.assertIsNone(c._on_the_runway(c.get("First 1")))

    def test_getting_airborne_releases_it(self):
        c = tower()
        me = put(c, "First 1", "holding_short")
        c.request_takeoff("First 1")
        me.has_been_airborne = True
        self.assertIsNone(c._on_the_runway(c.get("Second 2")))

    def test_a_landing_clearance_commits_it_too(self):
        """Two cleared to land on one strip is the same accident as two cleared
        to leave it, and it does not become one only when the wheels touch."""
        c = tower()
        ac = put(c, "Arriving 1", "approach", airborne=True)
        ac.on_visual = True
        c.report_landed("Arriving 1")
        self.assertIn("cleared to land", said(c))
        self.assertEqual(c._on_the_runway(c.get("Behind 2")), "Arriving 1")

    def test_a_go_around_gives_it_back(self):
        """Without this an aeroplane climbing away holds the aerodrome for
        everybody behind him. Shooter went around at Batumi on 30 August."""
        c = tower()
        ac = put(c, "Arriving 1", "approach", airborne=True)
        ac.on_visual = True
        c.report_landed("Arriving 1")
        c.report_missed("Arriving 1")
        self.assertIsNone(c._on_the_runway(c.get("Behind 2")))

    def test_leaving_the_board_gives_it_back(self):
        """A deslotted pilot must not seize the strip for ever."""
        c = tower()
        put(c, "First 1", "holding_short")
        c.request_takeoff("First 1")
        c.release("First 1")
        self.assertIsNone(c._on_the_runway(c.get("Second 2")))

    def test_a_hold_does_not_outlive_the_timeout(self):
        """The backstop, and the letdown is the precedent. A pilot who lands and
        goes quiet would otherwise block every movement at the field."""
        c = tower()
        put(c, "Quiet 1", "landed")
        self.assertEqual(c._on_the_runway(c.get("Behind 2")), "Quiet 1")
        c.tick(atc.RUNWAY_HOLD_SEC + 1)
        self.assertIsNone(c._on_the_runway(c.get("Behind 2")))

    def test_the_other_field_is_untouched(self):
        """#170's scoping. A check that ignored the field would refuse every
        take-off on the map the moment anybody landed anywhere."""
        c = tower()
        away = put(c, "Elsewhere 1", "departure")
        away.profile = TH.two_approaches()[1]
        home = put(c, "Waiting 2", "holding_short")
        if c._key(away) == c._key(home):
            self.skipTest("this map publishes one aerodrome")
        self.assertIsNone(c._on_the_runway(home))


class ItAdoptsAnOccupantNobodyRecorded(unittest.TestCase):
    """The holder dict is in memory, like the letdown's; the facts it is built
    from are on the aircraft and durable. So a bridge that comes up mid-rollout,
    or an aeroplane that got onto the strip without our clearance, is still
    found."""

    def test_a_man_already_down_is_adopted(self):
        c = tower()
        put(c, "Landed 1", "landed")
        self.assertEqual(c._on_the_runway(c.get("Waiting 2")), "Landed 1")

    def test_and_one_already_rolling(self):
        c = tower()
        put(c, "Rolling 1", "departure")
        self.assertEqual(c._on_the_runway(c.get("Waiting 2")), "Rolling 1")

    def test_but_not_a_man_who_has_reported_clear(self):
        c = tower()
        put(c, "Parked 1", "taxi_in", vacated=True)
        self.assertIsNone(c._on_the_runway(c.get("Waiting 2")))

    def test_nor_one_holding_short_beside_him(self):
        """Two aeroplanes at the holding point are both OFF the runway. A check
        that counted them would deadlock the field."""
        c = tower()
        put(c, "Waiting 1", "holding_short")
        self.assertIsNone(c._on_the_runway(c.get("Waiting 2")))


if __name__ == "__main__":
    unittest.main()
