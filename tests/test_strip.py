"""What the next controller inherits.

    "is the flight plan assignment working? I ask clearance for off to batumi
     but I don't think anything is happening with that"

It was working, completely. A pilot asks Clearance for "Domino", the plan is
matched from his own words, COPIED into `assigned_plans` against his flight,
denormalised onto `flights`, joined into `flight_state`, and stamped when he
reads it back. Every field populated and correct.

And `flight_strip` -- the ONE thing that tells the next controller what he has
inherited -- read none of them. Not the plan, not the route, not the cruise
altitude, not whether it had been acknowledged. So Departure, Center and Approach
each met a man with a filed route and a cleared level and asked him what he
wanted, which is what a pilot reported:

    "I had an IFR flight plan open and now they're asking for my intent."

The same shape as everything else this week: the data exists, is correct, and
nothing reads it.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marshall.atc.assembly import flight_strip

CLEARED = {
    "callsign": "sockeye", "claimed_size": 1, "destination": "Batumi",
    "origin": "Kobuleti", "procedure": "batumi-asr-13", "runway": "13",
    "cleared": "cleared approach", "assigned_ft": 2000,
    "flight_plan": "362nd-kobuleti-batumi", "flight_plan_label": "Domino",
    "route": "KOBULETI, INITIAL, BATUMI", "cruise_ft": 5000,
    "clearance_ack": "2026-08-09 20:48:52",
}


class TestTheStripCarriesTheClearance(unittest.TestCase):

    def test_it_names_the_plan_the_pilot_asked_for(self):
        """The LABEL, not the key. "362nd-kobuleti-batumi" is a database row
        read aloud; "Domino" is the word he said."""
        said = flight_strip(CLEARED)
        self.assertIn("Domino", said)
        self.assertNotIn("362nd-", said)

    def test_it_carries_the_route_and_not_an_invented_level(self):
        said = flight_strip(CLEARED)
        # `>` AND NOT `-` SINCE #191. The separator changed with the labels:
        # a route is ORDERED and a hyphenated list is not obviously so, and
        # the fields are named now because "on BatumiTest, via FOO-BAR" told
        # a controller neither what the name was nor what the points were.
        self.assertIn("KOBULETI > INITIAL > BATUMI", said)
        self.assertIn("ROUTE:", said)
        # NO LEVEL FROM THE PLAN. This asserted "5,000 ft" off `cruise_ft` --
        # `max(alt_ft)` synthesised and then stored under a name no plan has.
        # #192 dropped the column from both tables; a flight plan has a level
        # per LEG and no cruise. What the next controller needs is the level
        # the aeroplane is HELD to, which is `MAINTAINING:` off `assigned_ft`.
        self.assertNotIn("CRUISE", said.upper())
        self.assertNotIn("cruise", said)

    def test_the_route_does_not_read_as_more_fields(self):
        """The strip is already a comma list. A route inside it with its own
        commas reads as four more entries."""
        self.assertNotIn("ROUTE: KOBULETI, INITIAL", flight_strip(CLEARED))

    def test_an_unacknowledged_clearance_says_so(self):
        """A read-back is what makes a clearance agreed, and `clearance_ack`
        exists to record the difference. A controller who assumes agreement has
        an aeroplane flying a route nobody confirmed."""
        self.assertIn("read back", flight_strip(CLEARED))
        self.assertIn("NOT read back",
                      flight_strip({**CLEARED, "clearance_ack": None}))

    def test_a_flight_with_no_plan_reads_as_it_always_did(self):
        said = flight_strip({"callsign": "Pony 1-1", "destination": "Batumi",
                             "procedure": "batumi-asr-13", "runway": "13"})
        self.assertIn("inbound Batumi", said)
        self.assertNotIn("as filed", said)

    def test_a_row_without_claimed_size_does_not_crash(self):
        """`f.get("claimed_size", 1) and f["claimed_size"]` -- the default made
        the guard truthy and the subscript then raised. The strip is composed on
        every transmission, so this took the whole turn down for any row that
        had not been given a size."""
        self.assertTrue(flight_strip({"callsign": "Sockeye"}))

    def test_nothing_at_all_is_still_nothing(self):
        self.assertEqual(flight_strip({}), "")


if __name__ == "__main__":
    unittest.main()
