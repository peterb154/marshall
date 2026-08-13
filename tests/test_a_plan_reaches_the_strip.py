"""A filed plan travels five hops to the strip, and every hop must carry it.

This is the defect that opened the 13 August session -- the pilot asked why
`/diag` said nothing was on the strip while the controller was plainly working
a man on the Domino plan. The answer was that the strip has been blank for
EVERY aeroplane that has ever been on that board.

    list_flight_plans   SELECT name, callsign     <- no label, no legs
    GET /flightplans    {"name", "callsign"}
    filed_plans         names = {p["callsign"]}   <- always the empty set
    Identity.plan       matched against that set  <- so never assigned
    plan_of             keyed on p["label"]       <- payload never had one
    _plan_row           joined on p["callsign"]   <- the same dead column

`callsign` is what #142 retired: a plan is a label, legs and a task, and which
aeroplane flies it is a fact about a CLEARANCE. Six readers went on asking.

WHY ONE FIX LOOKED LIKE THE FIX. `816c97e` corrected `plan_of` and was reported
as done -- by me. Every other link fails to an empty string or an empty set,
never an error, so the corrected join ran happily against a dictionary that was
empty two hops upstream. Four links failing the same way is the thing to catch,
and a test of any single link passes while the chain is broken.

SO THIS TESTS THE CHAIN. Each hop below is asserted to carry the label forward,
and the last one asserts what a pilot actually sees.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from marshall import config
from marshall.atc import agent_atc as A
from marshall.atc import filing, identity

# A row as the table actually holds it after migration 031: a label, legs with
# a position and an altitude each, a task. No callsign, no route column, no
# destination column, no cruise_ft -- every one of those was a second answer to
# a question `legs` already answers.
ROW = {"name": "domino", "label": "Domino", "task": "IFR",
       "legs": [{"fix": "KOBULETI", "alt_ft": 3000},
                {"fix": "GUDAUTA", "alt_ft": 10000},
                {"fix": "BATUMI", "alt_ft": 4000}]}


class TestHopOneTheRowBecomesAPlan(unittest.TestCase):
    """`derived` is the one author of the facts that stopped being columns."""

    def setUp(self):
        self.plan = filing.derived(dict(ROW))

    def test_the_label_survives(self):
        self.assertEqual(self.plan["label"], "Domino")

    def test_and_the_destination_is_the_last_leg(self):
        """Nothing else makes it special -- it is the last steerpoint, and it
        is computed rather than stored because a controller SAYS it."""
        self.assertEqual(self.plan["destination"], "BATUMI")

    def test_the_dead_column_is_not_reintroduced(self):
        self.assertNotIn("callsign", self.plan)


class TestHopTwoThePayloadReachesTheRadio(unittest.TestCase):
    """`filed_plans` collects what a pilot will SAY."""

    def setUp(self):
        # PAST THE CACHE, not at zero: `filed_plans` returns the cached
        # names when `now - at < FILED_TTL_SEC`, so a fetch at t=1 never
        # happens. The test was asserting the cache, not the code.
        A._filed["at"] = 0.0
        A._filed["names"] = []
        A._filed["rows"] = []
        self.payload = {"flight_plans": [filing.derived(dict(ROW))]}
        self._real = A._get_json
        A._get_json = lambda url, timeout=0: self.payload

    def tearDown(self):
        A._get_json = self._real
        A._filed["at"] = 0.0

    def test_the_labels_come_back(self):
        self.assertEqual(A.filed_plans("http://x/flightplans", now=A.FILED_TTL_SEC + 10.0),
                         ["Domino"])

    def test_and_the_whole_row_is_cached_for_the_board(self):
        """`filed_plan_rows` is deliberately a reader of the cache this fills,
        so a board and a controller cannot poll on two timers and disagree."""
        A.filed_plans("http://x/flightplans", now=A.FILED_TTL_SEC + 10.0)
        rows = A.filed_plan_rows()
        self.assertEqual([r["label"] for r in rows], ["Domino"])
        self.assertEqual(rows[0]["destination"], "BATUMI")


class TestHopThreeTheLabelBindsWhenRADARKNOWSHIM(unittest.TestCase):
    """`Identity.plan` is matched against the labels -- but only on the RADAR
    rung, and that is deliberate rather than an oversight.

    Three branches build an Identity and exactly one sets `plan`. The comment
    beside the roster branch says why:

        "A STRIP STILL IS one -- a procedural controller works strips -- but it
         has to be tied to him by ASSIGNMENT, at clearance delivery, rather than
         by a name he happened to say. Until that link exists he is audible and
         not admitted."

    So saying a plan's name does not admit you and does not attach you to it.
    Being seen on radar does. That is the same door #133 and FEET WET were
    about: a SENTENCE must not create a fact.

    Which makes the label the right key twice over -- it is what he says, and
    it is only believed once something that is not a microphone agrees.
    """

    def unit(self):
        return {"name": "362nd_Sockeye", "label": "362nd_Sockeye",
                "callsign": "", "type": "F-16C_50", "category": "airplane",
                "manned": True, "player": "362nd_Sockeye", "on_ground": True,
                "lat": 41.6, "lon": 41.6, "alt_ft": 40.0,
                "heading": 215.0, "speed_kt": 0.0, "coalition": 3,
                "formation": ""}

    def test_radar_has_him_and_he_names_a_plan(self):
        reg = identity.Registry()
        got = reg.resolve("guid-1", srs_name="362nd_Sockeye",
                          spoken="Kobuleti Clearance, Sockeye, request IFR "
                                 "clearance to Batumi, Domino please",
                          scope=A.Scope("", contacts=[self.unit()]),
                          plans=["Domino"])
        self.assertEqual(got.authority, "radar")
        self.assertEqual(got.plan, "Domino")

    def test_but_an_empty_list_binds_nothing(self):
        """The state the system was ACTUALLY in: `filed_plans` returned [], so
        this matched nothing however clearly he spoke. Same inputs as above."""
        reg = identity.Registry()
        got = reg.resolve("guid-2", srs_name="362nd_Sockeye",
                          spoken="request IFR clearance to Batumi, Domino please",
                          scope=A.Scope("", contacts=[self.unit()]),
                          plans=[])
        self.assertEqual(got.plan, "")

    def test_and_saying_it_alone_does_not_admit_him(self):
        """No radar, no roster: he is audible and not admitted, and he carries
        no plan. A sentence must not create a fact."""
        reg = identity.Registry()
        got = reg.resolve("guid-3", srs_name="stranger",
                          spoken="request IFR clearance to Batumi, Domino please",
                          plans=["Domino"])
        self.assertEqual(got.plan, "")
        self.assertEqual(got.authority, "")


class TestHopFourTheStripSaysIt(unittest.TestCase):
    """What a pilot sees, which is the only reason any of the above matters."""

    def board(self):
        bridge = A.Bridge()
        bridge.identity.by_guid["g"] = identity.Identity(
            callsign="Sockeye", track="362nd_Sockeye", authority="radar",
            why="", plan="Domino", who="Sockeye")

        class Ctl:
            def board(self):
                return [{"callsign": "Sockeye", "phase": "cleared"}]

        scope = A.Scope("", contacts=[], origin=None, bullseye={})
        old = config.BUILD_DIR
        with tempfile.TemporaryDirectory() as d:
            config.BUILD_DIR = Path(d)
            try:
                A.publish_state(bridge, Ctl(), scope, "s",
                                plans=[filing.derived(dict(ROW))])
                return json.loads(
                    (Path(d) / "control" / "state.json").read_text())
            finally:
                config.BUILD_DIR = old

    def test_the_row_carries_his_plan(self):
        row = next(r for r in self.board()["board"]
                   if r["callsign"] == "Sockeye")
        self.assertIsNotNone(row.get("plan"), "the strip is empty")
        self.assertEqual(row["plan"]["label"], "Domino")

    def test_and_where_it_goes(self):
        """`Domino -> BATUMI`. Unreachable before #167 even on a match, because
        the payload carried no legs for `destination` to be derived from."""
        row = next(r for r in self.board()["board"]
                   if r["callsign"] == "Sockeye")
        self.assertEqual(row["plan"].get("destination"), "BATUMI")

    def test_the_plans_panel_attributes_it_to_him(self):
        """The sibling join, 108 lines below the one that was fixed. Fixing one
        left the panel saying nobody was flying a plan while the strip beside
        it said somebody was."""
        got = self.board()["plans"]
        self.assertTrue(got, "no plans panel at all")
        mine = next(p for p in got if p.get("label") == "Domino")
        self.assertEqual(mine.get("attributed_to"), "Sockeye")


if __name__ == "__main__":
    unittest.main()
