"""A tab is a flight, and every live row is on one.

    "yea, actually, i think you are right, the flighttest cards are all wrong.
     Maybe each tab should be a flight with things we should test top to
     bottom."

The card grew by THEME -- H is "the approach", G is "clearance delivery" --
and `flighttest.py` built one cockpit tab per section. That is the right axis
for WRITING tests and the wrong one for FLYING them: a pilot does not fly
section H, he flies from the ramp to the parking spot and passes through six
sections on the way, flipping tabs the whole time.

WHAT THIS GUARDS, and both halves have already gone wrong once:

    a flight names a row      it must exist in the library. A range that
    that does not exist       expands short renders a flight one row lighter,
                              and a missing row looks exactly like one the
                              pilot has not scrolled to
    a live row is in no       nobody will ever fly it. #176 and #177 sat
    flight at all             labelled `needs-flight-test` with no card row at
                              all, invisible to the check that exists to catch
                              exactly that, because `file_issues.py` reads the
                              FIRST `^labels:` line and a heading one silently
                              overrode the trailing one

The second is the one worth having. The card can be perfectly well-formed and
still fail to reach a pilot, which is the failure mode this whole document has
-- 148 live rows and the two that mattered this week were on none of them.

RANGES ARE OVER CARD ORDER, NOT ARITHMETIC. Section H runs H18, H19, H11, H13,
H10, H9, H4 ... in the order somebody found the faults, so expanding `H4..H28`
by counting would invent rows that do not exist and skip ones that do.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from marshall.kneeboard import flighttest as ft

CARD = Path(__file__).resolve().parents[1] / "docs" / "TEST_PLAN.md"


def _live_ids() -> list[str]:
    """Every row a pilot is still expected to fly, straight off the card."""
    out = []
    for _letter, _title, rows in ft.sections():
        out += [r["id"] for r in rows if r["id"]]
    return out


class EveryFlightNamesRowsThatExist(unittest.TestCase):

    def setUp(self):
        self.flights = ft.flights()
        self.live = set(_live_ids())

    def test_there_are_flights_at_all(self):
        self.assertTrue(self.flights, "the card declares no flights")

    def test_no_flight_names_a_row_the_card_has_not_got(self):
        known = self.live | {r["id"] for _l, _t, rows in ft.sections()
                             for r in rows if r["id"]}
        for name, _blurb, ids in self.flights:
            for rid in ids:
                with self.subTest(flight=name, row=rid):
                    self.assertIn(rid, known,
                                  f"{name} names {rid}, which is not on the card")

    def test_a_range_expands_over_card_order_not_arithmetic(self):
        """`H4..H28` must not become H4, H5, H6 ... H28. The numbers in a
        section are not contiguous and never have been."""
        text = CARD.read_text(encoding="utf-8")
        m = re.search(r"^## Flights$(.*?)(?=\n## )", text, re.M | re.S)
        self.assertIsNotNone(m, "no Flights section")
        ranges = re.findall(r"\b([A-Z]+\d+[a-z]?)\.\.([A-Z]+\d+[a-z]?)\b",
                            m.group(1))
        self.assertTrue(ranges, "no ranges to check")
        for lo, hi in ranges:
            with self.subTest(rng=f"{lo}..{hi}"):
                self.assertIn(lo, self.live, f"{lo} is not a live row")
                self.assertIn(hi, self.live, f"{hi} is not a live row")

    def test_no_flight_is_empty(self):
        for name, _blurb, ids in self.flights:
            with self.subTest(flight=name):
                self.assertTrue(ids, f"{name} has no rows")


class EveryLiveRowIsOnSomeFlight(unittest.TestCase):
    """The guard that would have caught #176 and #177 having no row.

    A row in the library and on no flight is a row nobody will ever fly. That
    is not a tidiness complaint: the card can be perfectly well-formed, pass
    every other check, and still never reach a pilot.
    """

    def test_nothing_live_is_unreachable(self):
        flown = {rid for _n, _b, ids in ft.flights() for rid in ids}
        orphans = sorted(set(_live_ids()) - flown)
        self.assertEqual(
            orphans, [],
            f"live rows on no flight, so nobody will fly them: {orphans}")

    def test_and_this_week_s_work_is_actually_on_one(self):
        """Named explicitly rather than left to the sweep above, because these
        two are the reason the sortie is being flown at all."""
        flown = {rid for _n, _b, ids in ft.flights() for rid in ids}
        for rid in ("V12", "V13", "V15"):
            with self.subTest(rid):
                self.assertIn(rid, flown)


class TheCockpitRendersOneTabPerFlight(unittest.TestCase):

    def test_the_tabs_are_flights_and_not_sections(self):
        labels = [label for _guid, label, _slug, _b in ft.pages()]
        self.assertIn("2 VFR", labels)
        # The old shape was one tab per LETTER: "H APPROACH", "G CLNC".
        for gone in ("H APPROACH", "G CLNC", "V DATUM"):
            with self.subTest(gone):
                self.assertNotIn(gone, labels)

    def test_every_tab_has_a_hand_written_label(self):
        """The strip is narrow and a truncated heading is not a name. A tab
        with no label is a page nobody opens."""
        for _guid, label, _slug, _b in ft.pages():
            with self.subTest(label):
                self.assertTrue(label.strip())
                self.assertNotEqual(label.strip(), "?")

    def test_flight_guids_are_stable_and_do_not_collide_with_sections(self):
        """OpenKneeboard remembers which page a pilot was on, so an identifier
        may never be reissued to a different document. Flights are namespaced
        on `flight:` precisely so one can never take a retired section's."""
        guids = [g for g, _l, _s, _b in ft.pages()]
        self.assertEqual(len(guids), len(set(guids)), "two tabs share a GUID")
        section_guids = {ft.guid_for(x) for x in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
        section_guids |= set(ft.GUIDS.values())
        for name, _b, _i in ft.flights():
            with self.subTest(name):
                self.assertNotIn(ft.guid_for(f"flight:{name}"), section_guids)

    def test_a_flight_page_renders_its_rows(self):
        html = ft.build_flight("FLIGHT 2 — the VFR arrival")
        self.assertIn("V12", html)
        self.assertIn("rows", html)

    def test_the_parked_flight_says_not_to_fly_it(self):
        html = ft.build_flight("PARKED — do not fly")
        self.assertIn("Do not fly", html)


if __name__ == "__main__":
    unittest.main()
