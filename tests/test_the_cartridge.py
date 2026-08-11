"""The DKS data cartridge: what a pilot filed, read back as data.

    "why wouldnt we file the flight plan to match the DTC data exactly?"

Marshall's filed plan said KOBULETI, INITIAL, BATUMI at five thousand while the
cartridge in the jet said a box out east and north at ten. Clearance would have
read back a route he was not flying at an altitude he was not holding, and every
controller after it would have inherited the wrong expectation.

THE DISTINCTION THIS FILE EXISTS TO PIN is SHARED versus PUBLISHED, which took
two mistakes to find. DIOMI is published -- on every pilot's plate, for ever, and
fileable as a route. FOO is not published and is still perfectly shared: he typed
it, it is on his HSI, and the cartridge carried it here. What may never happen is
filing a name only one party can resolve, because that reads as agreement.
"""

import base64
import gzip
import json
import struct
import unittest

from marshall.core import dtc


def _cartridge(payload: dict) -> str:
    body = json.dumps(payload).encode()
    return base64.b64encode(struct.pack("<I", len(body))
                            + gzip.compress(body)).decode()


# DKS ends its minutes with a typographic apostrophe rather than a prime. It is
# DATA, not prose, so it is constructed here instead of typed -- which keeps the
# fixtures honest and keeps ruff's ambiguous-character rule meaning something.
MARK = "\u2019"
DEG = "\u00b0"


def _pos(hemi: str, deg: int, minutes: str) -> str:
    return f"{hemi} {deg:02d}{DEG}{minutes}{MARK}"


def _wp(seq, name, lat=None, lon=None, alt=5000):
    """One waypoint. The position defaults because most tests are about which
    waypoints are the ROUTE, not about where they are."""
    return {"Sequence": seq, "Name": name,
            "Latitude": lat or _pos("N", 41, "57.496"),
            "Longitude": lon or _pos("E", 42, "01.395"), "Elevation": alt}


def _preset(n, name, mhz="120.00"):
    return {"Number": n, "Name": name, "Frequency": mhz}


# THE LADDER IS THE FIXTURE NOW, because it is where both ends come from. A
# comms ladder opens at the departure field's Clearance or Ground -- you cannot
# taxi anywhere else -- and closes at the arrival field's Tower or Ground.
LADDER = {"Radio2": {"Presets": [
    _preset(1, "Kobuleti Clearance"), _preset(2, "Kobuleti Ground"),
    _preset(3, "Kobuleti Tower"), _preset(4, "Kobuleti Departure"),
    _preset(5, "Georgia Center"), _preset(6, "Batumi Approach"),
    _preset(7, "Batumi Tower"), _preset(8, "Batumi Ground"),
]}}

ROUTE = {
    "Aircraft": "F16C",
    "Radios": LADDER,
    "Waypoints": {"Waypoints": [
        _wp(1, "FOO", _pos("N", 41, "57.496"), _pos("E", 42, "01.395"), 5000),
        _wp(2, "BAR", _pos("N", 42, "03.307"), _pos("E", 41, "59.573"), 10000),
        _wp(3, "SPAM", _pos("N", 42, "00.229"), _pos("E", 41, "35.212"), 10000),
        _wp(4, "Batumi", _pos("N", 41, "36.566"), _pos("E", 41, "35.996"), 33),
    ]},
    "Misc": {"ILSFrequency": 109.1, "ILSCourse": 209, "TACANChannel": 16},
}


class TestTheRouteStopsAtTheGap(unittest.TestCase):
    """Targeting points and box corners live past a break and are not the route."""

    def test_a_published_star_in_the_high_block_is_not_the_route(self):
        # A LIVE ONE PROVED IT BETTER THAN TARGETING DATA WOULD HAVE. Steerpoints
        # 81-89 of a Nellis cartridge were ARCOE, RONKY, WISTO, OLNIE, KRYSS,
        # SHEET, ROTSE, JELIR, CADOS, descending fifteen thousand to nothing --
        # a published STAR, every fix real, and still not this flight's route.
        # Filed, a controller would expect him to fly an arrival he had loaded.
        wps = [_wp(i, n) for i, n in enumerate(["FOO", "BAR", "SPAM"], 1)]
        wps += [_wp(81, "ARCOE"), _wp(82, "RONKY"), _wp(89, "CADOS")]
        d = dtc.decode(_cartridge({**ROUTE, "Waypoints": {"Waypoints": wps}}))
        self.assertEqual([w["name"] for w in dtc.waypoints(d)],
                         ["FOO", "BAR", "SPAM"])
        self.assertEqual(len(dtc.waypoints(d, route_only=False)), 6)


class TestReadingOne(unittest.TestCase):

    def test_it_decodes(self):
        self.assertEqual(dtc.decode(_cartridge(ROUTE))["Aircraft"], "F16C")

    def test_a_truncated_one_says_so(self):
        # A cartridge that has been through a chat window loses its tail more
        # often than not, and "invalid" sends somebody hunting the wrong thing.
        # One arrived whose base64 was perfect and whose gzip was nine bytes
        # short of its own declared length.
        good = base64.b64decode(_cartridge(ROUTE))
        with self.assertRaises((OSError, EOFError, ValueError)):
            dtc.decode(base64.b64encode(good[:-12]).decode())

    def test_minutes_are_minutes_not_seconds(self):
        # 57.496 MINUTES is .958 of a degree. Read as seconds it is .016, which
        # puts the waypoint fifty miles away and still looks like a position.
        self.assertAlmostEqual(dtc.latlon(_pos("N", 41, "57.496")),
                               41.958267, places=5)

    def test_west_and_south_are_negative(self):
        self.assertAlmostEqual(dtc.latlon(_pos("W", 117, "30.000")), -117.5)
        self.assertAlmostEqual(dtc.latlon(_pos("S", 12, "30.000")), -12.5)

    def test_waypoints_come_back_in_order(self):
        wps = dtc.waypoints(dtc.decode(_cartridge(ROUTE)))
        self.assertEqual([w["name"] for w in wps],
                         ["FOO", "BAR", "SPAM", "Batumi"])


class TestWhatMayBeFiled(unittest.TestCase):

    def setUp(self):
        self.d = dtc.decode(_cartridge(ROUTE))

    def test_the_cruise_is_the_highest_leg(self):
        # `flight_plans` holds one altitude, the cartridge holds one per
        # waypoint. The number that matters is the one a controller must not be
        # surprised by -- filing the first leg's 5,000 while he climbs to 10,000
        # is the disagreement this whole thing exists to end.
        self.assertEqual(dtc.plan_from(self.d, "x", label="D")["cruise_ft"],
                         10000)

    def test_the_aerodrome_is_the_destination(self):
        self.assertEqual(dtc.plan_from(self.d, "x", label="D")["destination"],
                         "Batumi")

    def test_by_default_his_own_names_are_not_filed(self):
        # THE CIVIL RULE. "in civil avation, we dont make up our own random
        # fixes in a flight plan though." A filed route is a shared PUBLISHED
        # reference and his cartridge is published to nobody.
        route = dtc.plan_from(self.d, "x", label="D")["route"]
        for n in ("FOO", "BAR", "SPAM"):
            self.assertNotIn(n, route)

    def test_asked_for_they_are(self):
        # ...and he may choose to SHARE them, which is a different question from
        # whether they are published.
        self.assertEqual(dtc.plan_from(self.d, "x", label="D",
                                       steerpoints=True)["route"],
                         "KOBULETI, FOO, BAR, SPAM, BATUMI")

    def test_both_ends_come_from_the_comms_ladder(self):
        # "is the origin (Nellis) not in the DTC anywhere?" -- it is, and this
        # is where. No geometry, no theatre: the ladder names them in order.
        self.assertEqual(dtc.ladder(self.d), ["Kobuleti", "Batumi"])

    def test_a_centre_is_not_an_aerodrome(self):
        # Georgia Center wears a seat word and works a piece of sky. Left in, it
        # lands in the middle of a route.
        self.assertNotIn("Georgia", dtc.ladder(self.d))

    def test_a_there_and_back_has_one_field_at_both_ends(self):
        # A ladder that never leaves Nellis is exactly what a range sortie is.
        d = dtc.decode(_cartridge({**ROUTE, "Radios": {"R": {"Presets": [
            _preset(1, "Nellis CLNC"), _preset(2, "Nellis GND"),
            _preset(3, "NELLIS CONTROL"), _preset(4, "Nellis APP")]}}}))
        p = dtc.plan_from(d, "x", label="D")
        self.assertEqual((p["origin"], p["destination"]), ("Nellis", "Nellis"))

    def test_an_unnamed_steerpoint_is_never_filed(self):
        # "STPT" is not a name he chose, it is the absence of one. Filing it
        # would be back to inventing, which is what STPT1/2/3 was.
        bare = json.loads(json.dumps(ROUTE))
        for w in bare["Waypoints"]["Waypoints"][:3]:
            w["Name"] = "STPT"
        got = dtc.plan_from(dtc.decode(_cartridge(bare)), "x", label="D",
                            steerpoints=True)
        self.assertEqual(got["route"], "KOBULETI, BATUMI")

    def test_aerodromes_are_never_pushed_as_steerpoints(self):
        # Batumi is published, with a surveyed position and a beacon. A
        # cartridge's rounded one must not quietly replace it.
        wps = dtc.waypoints(self.d)
        self.assertEqual(
            sorted(dtc.named_steerpoints(wps, ("Kobuleti", "Batumi"))),
            ["BAR", "FOO", "SPAM"])


if __name__ == "__main__":
    unittest.main()
