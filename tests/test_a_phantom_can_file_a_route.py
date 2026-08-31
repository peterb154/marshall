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
            okb.waypoints(DESIGN), [], "GeorgiaPhantoms",
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

    def test_the_comms_card_resolves_its_agency_references(self):
        """THE FREQUENCIES ARE NOT IN THE DESIGN. Each channel carries an
        agency id and the card is resolved from the squadron library. I
        recorded that this could not be done, on the strength of a guessed URL
        returning 405 -- which is METHOD NOT ALLOWED and was the endpoint
        saying the path was right and the verb was wrong.

        The resolver is stubbed: a test that reached the network would be
        testing somebody else's uptime."""
        library = [{"id": "a1", "name": "Kobuleti CLNC", "frequency": "251.100"},
                   {"id": "a2", "name": "Batumi TWR", "frequency": "260.000"}]
        d = json.loads(json.dumps(DESIGN))
        d["formData"]["co-1-agency1-id"] = "a1"
        d["formData"]["co-2-agency1-id"] = "a2"
        got = okb.comms_card(d, resolve=lambda ids, sq: library)
        self.assertEqual(got[0], {"channel": "1", "agency": "Kobuleti CLNC",
                                  "freq_mhz": "251.100"})
        self.assertEqual(got[1]["freq_mhz"], "260.000")

    def test_a_card_that_cannot_be_read_is_not_a_card_that_is_empty(self):
        """A resolver that fails leaves the channels with whatever the design
        spells out -- usually nothing -- and must not raise. The caller falls
        back to the route, which is where both ends come from anyway."""
        def _boom(ids, sq):
            raise OSError("no network")
        self.assertEqual(okb.comms_card(DESIGN, resolve=_boom), [])


class HisOwnNamesForIt(unittest.TestCase):
    """A design is already called something and already says what the sortie is
    for. Making a pilot retype either asks him for a fact the file in front of
    him already holds."""

    def test_the_design_name_becomes_the_label(self):
        self.assertEqual(okb.label_from(DESIGN), "GeorgiaPhantoms")

    def test_but_only_when_it_can_be_SAID(self):
        """`filing._LABEL_OK` allows letters, apostrophes and hyphens and
        nothing else, for the reason migration 012 records: "Samovar One" and
        "Samovar Two" are the Alpha One / Alpha Two shape, and a transcriber
        that hears "won" picks the wrong sortie."""
        # "GO" is legal -- two letters, and the rule allows it. The rejects
        # are a SPACE, a DIGIT, one character, and nothing at all.
        for name in ("Op Deep Strike", "Phantoms 2", "G", ""):
            with self.subTest(name=name):
                d = json.loads(json.dumps(DESIGN))
                d["name"] = name
                self.assertEqual(okb.label_from(d), "")

    def test_the_task_is_composed_from_his_aimpoints_and_racks(self):
        """A cartridge has prose to quote; a design has none, so this is built
        from fields he filled in. `plans.py` scores a spoken request against
        `task`, so it has to tell two similar sorties apart -- his nouns do
        that and an invented adjective would not."""
        self.assertEqual(okb.task_from(DESIGN), "TGT01 Airfiled -- Mk-82")

    def test_a_weapon_is_counted_once_however_many_pylons_carry_it(self):
        """The racks repeat the same store per station -- Mk-82x6, Mk-82x3 --
        and what tells sorties apart is WHICH weapon, not how many pylons."""
        self.assertEqual(okb.task_from(DESIGN).count("Mk-82"), 1)

    def test_nothing_to_say_is_said_as_nothing(self):
        """Never a word every plan shares: that distinguishes nothing, and
        `dtc.task_from` refuses the same temptation for the same reason."""
        d = json.loads(json.dumps(DESIGN))
        d["formData"]["dmpis"] = []
        for i in range(1, 12):
            d["formData"].pop(f"lo-{i}-type", None)
        self.assertEqual(okb.task_from(d), "")


class HisRadioCardAgainstOurs(unittest.TestCase):
    """A frequency he cannot reach us on fails silently and in the air: he
    calls, nobody answers, and neither end knows which of them has the wrong
    number. The import is the one moment both cards are to hand."""

    class _Seat:
        def __init__(self, name, field, role, freqs, also=()):
            self.name, self.field, self.role = name, field, role
            self.freqs, self.also, self.freq_mhz = freqs, also, freqs[0]

    SEATS = [_Seat("Kobuleti Clearance", "Kobuleti", "clearance", (125.1, 251.1)),
             _Seat("Kobuleti Tower", "Kobuleti", "tower", (133.0, 262.0)),
             _Seat("Batumi Tower", "Batumi", "tower", (118.6, 260.0))]
    ATIS = {"Batumi": 280.0, "Kobuleti": 279.0}

    def _check(self, card):
        return okb.check_card(card, self.SEATS, self.ATIS)

    def test_a_matching_card_says_nothing(self):
        self.assertEqual(self._check(
            [{"channel": "4", "agency": "Kobuleti TWR", "freq_mhz": "262.000"},
             {"channel": "1", "agency": "Kobuleti ATIS", "freq_mhz": "279.000"}]),
            [])

    def test_an_abbreviation_is_not_a_disagreement(self):
        """His card says CLNC and our seat is Clearance. Insisting on one
        spelling would report every channel and teach him to ignore it."""
        self.assertEqual(self._check(
            [{"channel": "2", "agency": "Kobuleti CLNC", "freq_mhz": "251.100"}]),
            [])

    def test_a_wrong_frequency_is_named_with_both_numbers(self):
        got = self._check(
            [{"channel": "8", "agency": "Batumi TWR", "freq_mhz": "131.000"}])
        self.assertEqual(len(got), 1)
        self.assertIn("131.000", got[0])
        self.assertIn("118.600", got[0])

    def test_a_wrong_atis_too(self):
        got = self._check(
            [{"channel": "9", "agency": "Batumi ATIS", "freq_mhz": "281.000"}])
        self.assertEqual(len(got), 1)
        self.assertIn("280.000", got[0])

    def test_a_facility_this_map_does_not_have_is_left_alone(self):
        """Squadrons carry agencies for every theatre they fly. A Nevada seat on
        a Caucasus card is his library being bigger than this sortie."""
        self.assertEqual(self._check(
            [{"channel": "6", "agency": "Nellis GND", "freq_mhz": "275.800"}]),
            [])

    def test_and_so_is_anything_it_cannot_parse(self):
        """A check that cries wolf is a check somebody turns off."""
        self.assertEqual(self._check(
            [{"channel": "7", "agency": "", "freq_mhz": "251.100"},
             {"channel": "8", "agency": "Batumi TWR", "freq_mhz": "see plate"}]),
            [])


if __name__ == "__main__":
    unittest.main()
