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


def _wp(seq, name, lat, lon, alt):
    return {"Sequence": seq, "Name": name, "Latitude": lat,
            "Longitude": lon, "Elevation": alt}


ROUTE = {
    "Aircraft": "F16C",
    "Waypoints": {"Waypoints": [
        _wp(1, "FOO", _pos("N", 41, "57.496"), _pos("E", 42, "01.395"), 5000),
        _wp(2, "BAR", _pos("N", 42, "03.307"), _pos("E", 41, "59.573"), 10000),
        _wp(3, "SPAM", _pos("N", 42, "00.229"), _pos("E", 41, "35.212"), 10000),
        _wp(4, "Batumi", _pos("N", 41, "36.566"), _pos("E", 41, "35.996"), 33),
    ]},
    "Misc": {"ILSFrequency": 109.1, "ILSCourse": 209, "TACANChannel": 16},
}


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
        self.assertEqual(sorted(dtc.named_steerpoints(wps)),
                         ["BAR", "FOO", "SPAM"])


if __name__ == "__main__":
    unittest.main()
