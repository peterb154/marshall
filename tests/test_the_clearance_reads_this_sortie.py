"""Clearance delivery reads THIS sortie's board, and could not before.

    "clearly he doesn't know how to find my flight plan"

Three requests in a row, answered "I have no flight on the board under that
callsign" -- while `Domino` sat on the board, resolvable by destination from the
plainest possible request:

    PILOT: Kobuleti Clearance, sockeye, IFR to Batumi with information delta.
    ATC:   Sockeye, I have no flight of that name on the board.

THE TOOL NEVER REACHED THE PLAN. `request_clearance` starts by finding the
AEROPLANE -- `_flight(callsign)` -- and answers `not_on_the_board` when it
cannot. `flights.find` filters on `mission`, `clearance_tools` took it as an
argument DEFAULTING to "default", and `app.py` called `clearance_tools()` with
none. The bridge writes every row under the instance key, so the lookup searched
an empty bucket and refused before it ever looked at what was filed.

It was correct until #119 gave rows a real instance key -- the shape this
project keeps finding: while every row was `mission='default'`, a hard-coded
"default" could not be wrong. And it was invisible because this is the one tool
factory whose argument has a default; every other takes the session and would
have raised a TypeError the first time it was called wrongly.

TWO BOARDS, AND THEY ARE NOT THE SAME ONE. `flight_plans` is what somebody
filed; `flights` is who is airborne. "No flight on the board" is a true sentence
about the second that says nothing about the first, and a pilot hears it as "your
flight plan is missing".
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestTheMissionReachesTheTools(unittest.TestCase):

    def setUp(self):
        self.app = (ROOT / "director" / "app.py").read_text()
        self.clr = (ROOT / "src" / "marshall" / "atc" / "clearance.py").read_text()

    def test_the_tools_are_bound_to_a_mission(self):
        # The bug in one line: `clearance_tools()` with no argument. It takes
        # the SEAT as well since #127 -- the station is what makes the origin a
        # fact rather than a guess.
        self.assertIn("clearance_tools(mission, station)", self.app)
        self.assertNotIn("clearance_tools()", self.app)

    def test_the_endpoint_reads_it_off_the_request(self):
        self.assertIn('body.get("mission")', self.app)

    def test_the_agent_cache_is_keyed_on_it(self):
        # A cached agent built under the previous sortie would go on reading the
        # previous sortie's flights -- the same leak the station and role were
        # added to this key to close.
        self.assertRegex(self.app, r"_key = \(session_id, station, role, also,"
                                   r"\s*mission\)")

    def test_the_bridge_sends_it(self):
        src = (ROOT / "src" / "marshall" / "atc" / "agent_atc.py").read_text()
        body = src[src.index("def ask_agent("):]
        body = body[:body.index("\ndef ")]
        self.assertIn('"mission": MISSION', body)

    def test_finding_a_flight_still_filters_on_the_mission(self):
        # If this ever stops being true the wiring above is pointless, and the
        # rows of one sortie become visible to the next.
        fl = (ROOT / "src" / "marshall" / "atc" / "board.py").read_text()
        self.assertIn("WHERE mission = %s", fl)


class TestTheTwoBoardsAreDifferentThings(unittest.TestCase):
    """`flight_plans` is what was filed. `flights` is who is flying."""

    def test_the_refusal_names_the_board_it_means(self):
        # "I have no flight on the board" is true of the FLIGHTS board and says
        # nothing about what is FILED -- and a pilot hears it as his flight plan
        # having gone missing, which is what happened.
        src = (ROOT / "src" / "marshall" / "atc" / "clearance.py").read_text()
        self.assertIn("def not_on_the_board", src)


if __name__ == "__main__":
    unittest.main()
