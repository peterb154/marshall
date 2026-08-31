"""A route filed from a DKS kneeboard design instead of a data cartridge.

    "when using DKS, and a jet without a DTC (i.e. F4-C) it doesnt let us
     download the dtc file, so we need another way to import easily"

A cartridge is an F-16 thing. The Phantoms now on the Kobuleti ramp have no DTC
to export, so their pilots had no way to hand us a route at all.

THE FIXTURE IS A CAPTURED RESPONSE, not an invention: the real design behind
`/okb?design=613fe489-...`, fetched from the public API its own page calls, with
a real Phantom sortie in it. A hand-written fixture would have agreed with
whatever the parser happened to do.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from marshall.core import dtc, okb

DESIGN = json.loads(
    (pathlib.Path(__file__).parent / "fixtures"
     / "dks_design_georgiaphantoms.json").read_text())

PLACES = {"Batumi": (41.6103, 41.5997), "Kobuleti": (41.9297, 41.8656)}


class TheIdComesOutOfWhateverHePastes(unittest.TestCase):

    def test_the_whole_viewer_url(self):
        self.assertEqual(
            okb.design_id("https://www.digitalkneeboardsimulator.com/okb"
                          "?design=613fe489-4ecd-454e-8441-6bd72e67f4a5&pilot=1"),
            "613fe489-4ecd-454e-8441-6bd72e67f4a5")

    def test_the_bare_id(self):
        self.assertEqual(okb.design_id("613FE489-4ECD-454E-8441-6BD72E67F4A5"),
                         "613fe489-4ecd-454e-8441-6bd72e67f4a5")

    def test_anything_else_is_nothing(self):
        """Not a URL parser: `?design=` has already changed shape once, and a
        UUID in the text is the durable signal."""
        self.assertEqual(okb.design_id("here is my flight plan"), "")

    def test_fetching_without_one_says_so(self):
        with self.assertRaises(ValueError):
            okb.fetch("no id here", read=lambda i: "{}")


class TheRouteIsTheSameShapeACartridgeGives(unittest.TestCase):
    """Both importers normalise to `{seq, name, lat, lon, alt_ft}` so that
    everything downstream is shared. Two ways to build a plan is how two
    readers come to disagree about what a pilot filed."""

    def test_the_steerpoints_are_read_in_order_with_their_names(self):
        got = [(w["seq"], w["name"], w["alt_ft"]) for w in okb.waypoints(DESIGN)]
        self.assertEqual(got, [
            (1, "DEPARTURE", 5000), (2, "INGRESS", 15000), (3, "TARGET", 42),
            (4, "EGRESS", 10000), (5, "APPROACH", 5000), (6, "Batumi", 33)])

    def test_the_coordinates_are_decimal_degrees(self):
        """The cartridge carries degrees-and-decimal-minutes as strings that
        have to be parsed back; this does not, and the last point should land
        on Batumi."""
        last = okb.waypoints(DESIGN)[-1]
        self.assertAlmostEqual(last["lat"], 41.6094, places=3)
        self.assertAlmostEqual(last["lon"], 41.5999, places=3)

    def test_a_hole_in_the_numbering_ends_the_route(self):
        """The same gap rule the cartridge needs. DKS keeps targets and threats
        in their own arrays so this should not arise -- but a live cartridge had
        a published STAR sitting at 81..89, and "should" is what it looked like
        too."""
        d = json.loads(json.dumps(DESIGN))
        d["formData"]["waypoints"][3]["number"] = 81
        self.assertEqual([w["seq"] for w in okb.waypoints(d)], [1, 2, 3])

    def test_a_waypoint_with_no_position_is_skipped_not_fatal(self):
        d = json.loads(json.dumps(DESIGN))
        d["formData"]["waypoints"][2].pop("lat")
        self.assertEqual([w["seq"] for w in okb.waypoints(d)], [1, 2])


class ItKnowsWhereHeIsParked(unittest.TestCase):
    """WITHOUT THIS THE ROUTE NAMES ONE END. A design's waypoints begin after
    take-off, so the only aerodrome in the list is the recovery field."""

    def test_the_start_point_names_the_departure_field(self):
        self.assertEqual(okb.origin_from_start(DESIGN, PLACES), "Kobuleti")

    def test_nothing_within_range_is_nothing(self):
        self.assertEqual(
            okb.origin_from_start(DESIGN, {"Batumi": (41.6103, 41.5997)}), "")

    def test_and_the_filed_plan_has_both_ends_right(self):
        """The bug this pair exists for: filed without an origin the sortie
        came out Batumi to Batumi, because `dest` defaulted to `start` before
        the route's own aerodromes were consulted."""
        plan = dtc.plan_from_route(
            okb.waypoints(DESIGN), okb.comms_card(DESIGN), "GeorgiaPhantoms",
            origin=okb.origin_from_start(DESIGN, PLACES))
        self.assertEqual(plan["origin"], "Kobuleti")
        self.assertEqual(plan["destination"], "Batumi")
        self.assertEqual(plan["cruise_ft"], 15000)


class WhatTheDesignKnowsBesidesTheRoute(unittest.TestCase):

    def test_the_aeroplane_and_the_map(self):
        f = okb.facts(DESIGN)
        self.assertEqual(f["aircraft"], "F4E")
        self.assertEqual(f["theatre"], "Caucasus")

    def test_the_crew_and_their_callsigns(self):
        self.assertEqual(okb.facts(DESIGN)["crew"],
                         [{"callsign": "Hammer1-1", "pilot": "Sockeye"},
                          {"callsign": "Hammer1-2", "pilot": "Shooter"}])

    def test_the_home_plate_carries_his_frequencies(self):
        """A direct read on whether his kneeboard and our controllers agree.
        On this design they do not: his card says Batumi is 131.00, which is
        the sim's simplified number, against the published 118.600."""
        hp = okb.facts(DESIGN)["home_plate"]
        self.assertEqual(hp["field"], "Batumi")
        self.assertEqual(hp["runway"], "13")
        self.assertEqual(hp["radios"], "131.00/260.00")

    def test_an_empty_comms_card_is_an_answer(self):
        """Blank is usual, and callers fall back to the route rather than
        treating it as a failure."""
        self.assertEqual(okb.comms_card(DESIGN), [])


if __name__ == "__main__":
    unittest.main()
