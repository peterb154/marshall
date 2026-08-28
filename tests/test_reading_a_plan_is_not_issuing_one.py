"""Every seat may READ a flight plan; only Delivery may issue one. [#199]

`flight_plan_help` rode inside `clearance_tools`, and that list is handed out
only when the seat has the CLEARANCE capability -- Clearance and Delivery and
nobody else. So the seats that actually work an aeroplane in the air could not
see where it was going.

    PILOT  Kobuleti Departure, request vectors to my next steerpoint
    ATC    negative on vectors, I don't have your steerpoints

Which was true: it had no such tool. Two fixes went into that tool the same
evening and neither could ever have reached the seat that was asked.

Issuing a clearance is a power. Knowing what an aeroplane is doing is not, for
the same reason `frequency` and `procedure` are universal: a pilot asks.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from marshall.atc import clearance as C  # noqa: E402
from marshall.atc.agent.capability import capabilities  # noqa: E402

WORKS_AEROPLANES = ("ground", "tower", "departure", "approach", "center")


def _names(tools) -> set:
    out = set()
    for t in tools:
        out.add(getattr(t, "__name__", ""))
    return out


class ReadingAPlanIsNotIssuingOne(unittest.TestCase):

    def test_every_seat_that_works_an_aeroplane_can_read_his_plan(self):
        for role in WORKS_AEROPLANES:
            with self.subTest(role=role):
                may = capabilities(role)
                self.assertIn("flightplan", may,
                              f"{role} works aeroplanes and cannot read a plan")

    def test_but_only_delivery_may_issue_a_clearance(self):
        for role in WORKS_AEROPLANES:
            with self.subTest(role=role):
                self.assertNotIn("clearance", capabilities(role),
                                 f"{role} must not be able to clear anybody")
        for role in ("clearance", "delivery"):
            self.assertIn("clearance", capabilities(role))

    def test_the_reading_set_carries_no_issuing_tool(self):
        got = _names(C.flightplan_tools("m", "s"))
        self.assertIn("flight_plan_help", got)
        self.assertNotIn("request_clearance", got,
                         "reading a plan must not smuggle in issuing one")
        self.assertNotIn("clearance_state", got)
