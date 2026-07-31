"""Aeroplanes in formation must still be aeroplanes.

Found by the flight rehearsal, and it is the defect that makes the whole flight
model unreachable. The radar picture collapses a formation onto one line for the
controller -- a real controller reads four ships in close trail as ONE thing --
and the collapse silently dropped everything except the lead's name:

    362nd_Sockeye-1 (P-51D-30-NA) IN FORMATION with 362nd_Andre-1 — 2 ships,
    lead 13.5 nm on the 307 radial, 5,952 ft, heading 062, 281 knots

The lead did not parse, because every scope regex wanted a colon after the type
and a formation line has none. The wingman did not parse, because he is named
only inside the prose. So BOTH aeroplanes vanished from `units_on`, neither
resolved to a track, `_who` came back empty, and the bridge's entire flight
block -- create, join, break out -- is gated on `_who`.

Which is exactly backwards. Forming up is what a pilot does immediately before
asking to join a flight, so the act of forming up made him unidentifiable. In
the rehearsal Sockeye and Andre were spawned a few hundred yards apart to
exercise the one-mile join rule and thereby made themselves invisible, while
Shooter -- ten miles away, alone, and meant to be the REFUSAL -- was the only
one the ladder could see. The one negative case passed and every positive case
died, which is why the run looked like a parser bug in `parse_create`.

THE OFFSET IS NOT DECORATION. `FORM_NM` is 2.0 and `JOIN_NM` is 1.0, so "radar
shows them as a formation" is NOT evidence they are within a mile. Treating it
as evidence would double the join radius by accident. The picture prints each
wingman's distance off the lead and the rule keeps measuring.
"""

import ast
import math
import unittest
from pathlib import Path

from marshall.atc import agent_atc as A
from marshall.atc import identity

ROOT = Path(__file__).resolve().parent.parent

# The old picture, exactly as recorded on the night. Kept verbatim because the
# bridge and the director are separate deployables: one can be restarted without
# the other, so a picture with no offsets is a real thing to be handed and must
# degrade to "I cannot confirm" rather than to a wrong number.
OLD = ("362nd_Sockeye-1 (P-51D-30-NA) IN FORMATION with 362nd_Andre-1 — 2 ships, "
       "lead 13.5 nm on the 307 radial, 5,952 ft, heading 062, 281 knots | "
       "362nd_Shooter-1 (P-51D-30-NA): 23.3 nm on the 304 radial, 5,999 ft, "
       "heading 075, 306 knots")

NEW = ("362nd_Sockeye-1 [Apex] (P-51D-30-NA, manned) IN FORMATION with "
       "362nd_Andre-1 (P-51D-30-NA, manned, 0.3 nm) — 2 ships, "
       "lead 13.5 nm on the 307 radial, 5,952 ft, heading 062, 281 knots | "
       "362nd_Shooter-1 (P-51D-30-NA, manned): 23.3 nm on the 304 radial, "
       "5,999 ft, heading 075, 306 knots")


class TestEverybodyInAFormationIsOnTheScope(unittest.TestCase):
    def names(self, scope):
        return [u.name for u in identity.units_on(scope)]

    def test_the_lead_parses_without_a_colon(self):
        self.assertIn("362nd_Sockeye-1", self.names(OLD))

    def test_the_wingman_is_an_aeroplane_too(self):
        self.assertIn("362nd_Andre-1", self.names(OLD))

    def test_every_radio_reaches_its_own_aeroplane(self):
        """The failure in one line: this is what `_who` needs, and it returned
        nothing for the two men who had formed up."""
        for scope in (OLD, NEW):
            units = identity.units_on(scope)
            for who, expect in (("Sockeye", "362nd_Sockeye-1"),
                                ("Andre", "362nd_Andre-1"),
                                ("Shooter", "362nd_Shooter-1")):
                with self.subTest(scope=scope[:20], who=who):
                    got = identity.unit_for_radio(who, units)
                    self.assertIsNotNone(got, f"{who} could not be identified")
                    self.assertEqual(got.name, expect)

    def test_a_wingman_keeps_his_airframe_and_his_manned_flag(self):
        """Both decide real things -- the speed he is assigned, what he can
        receive, and whether elimination can find a guest."""
        u = next(u for u in identity.units_on(NEW) if u.name == "362nd_Andre-1")
        self.assertEqual(u.type, "P-51D-30-NA")
        self.assertTrue(u.manned)

    def test_a_lone_contact_is_untouched(self):
        u = next(u for u in identity.units_on(NEW) if u.name == "362nd_Shooter-1")
        self.assertEqual(u.type, "P-51D-30-NA")
        self.assertTrue(u.manned)


class TestTheLeadKeepsHisOwnPosition(unittest.TestCase):
    """The offset is printed BEFORE the lead's range, so every regex that takes
    the first "N nm" after the name would read 0.3 nm as the lead's distance
    from the field and put a flight three hundred yards off the runway."""

    def test_the_lead_is_where_he_actually_is(self):
        fix = A.radar_fix_by_track(NEW, "362nd_Sockeye-1")
        self.assertIsNotNone(fix)
        self.assertAlmostEqual(fix.range_nm, 13.5, places=1)
        self.assertAlmostEqual(fix.radial_deg, 307.0, places=0)

    def test_the_tagged_lookup_agrees_with_the_track_lookup(self):
        by_tag = A.radar_fix(NEW, "Apex")
        self.assertIsNotNone(by_tag)
        self.assertAlmostEqual(by_tag.range_nm, 13.5, places=1)

    def test_flattening_leaves_an_ordinary_contact_line(self):
        flat = identity.flatten_formation(NEW)
        self.assertNotIn("IN FORMATION", flat)
        self.assertIn("362nd_Sockeye-1 [Apex] (P-51D-30-NA, manned): 13.5 nm", flat)


class TestHowFarOffTheLeadHeIs(unittest.TestCase):
    def test_the_printed_offset_is_the_gap(self):
        self.assertAlmostEqual(
            A.miles_between(NEW, "362nd_Andre-1", "362nd_Sockeye-1"), 0.3, places=2)

    def test_it_reads_the_same_both_ways_round(self):
        self.assertEqual(A.miles_between(NEW, "362nd_Andre-1", "362nd_Sockeye-1"),
                         A.miles_between(NEW, "362nd_Sockeye-1", "362nd_Andre-1"))

    def test_an_unprinted_offset_is_unknown_and_not_zero(self):
        """The under-estimate is the dangerous direction: it joins a man to a
        formation radar cannot confirm he is in. `join` turns None into
        "radar does not show you both", which is the truth."""
        self.assertIsNone(A.miles_between(OLD, "362nd_Andre-1", "362nd_Sockeye-1"))

    def test_a_wingman_against_an_outsider_is_still_measurable(self):
        """Shooter is ten miles away and must still be refused by NUMBER, not
        by "I cannot see you" -- his refusal is the case the rehearsal exists
        to prove."""
        gap = A.miles_between(NEW, "362nd_Andre-1", "362nd_Shooter-1")
        self.assertIsNotNone(gap)
        self.assertGreater(gap, 1.0)

    def test_two_wingmen_are_bounded_rather_than_guessed(self):
        three = ("A-1 (P-51D-30-NA, manned) IN FORMATION with "
                 "B-1 (P-51D-30-NA, 0.3 nm), C-1 (P-51D-30-NA, 1.4 nm) — 3 ships, "
                 "lead 13.5 nm on the 307 radial, 5,952 ft, heading 062, 281 knots")
        self.assertEqual([u.name for u in identity.units_on(three)],
                         ["A-1", "B-1", "C-1"])
        # Opposite sides of the lead is the worst case, and over-estimating
        # costs a false refusal where under-estimating costs separation.
        self.assertAlmostEqual(A.miles_between(three, "B-1", "C-1"), 1.7, places=2)


class TestTheRendererAndTheParserAgree(unittest.TestCase):
    """The line is WRITTEN in the director and READ in the bridge, two
    deployables that do not import each other. A test that hand-writes the line
    proves only that the parser can read the test's idea of it, so this lifts
    the renderer's own function out of the source and round-trips through it.
    """

    def _other_ship(self):
        src = (ROOT / "src" / "marshall" / "feed" / "tracks.py").read_text()
        tree = ast.parse(src)
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "_other_ship")
        ns: dict = {}
        exec(compile(ast.Module([fn], []), "tracks.py", "exec"), ns)
        return ns["_other_ship"]

    def row(self, label, name, typ, nm, radial, manned):
        # label, name, typ, alt, hdg, speed, nm, radial, manned
        return [label, name, typ, 5952, 62, 281, nm, radial, manned]

    def test_a_rendered_wingman_parses_back_to_himself(self):
        other = self._other_ship()
        lead = self.row("362nd_Sockeye-1", "362nd_Sockeye-1", "P-51D-30-NA",
                        13.5, 307, True)
        wing = self.row("362nd_Andre-1", "362nd_Andre-1", "P-51D-30-NA",
                        13.7, 307.5, True)
        naming = {"362nd_Sockeye-1": "362nd_Sockeye-1",
                  "362nd_Andre-1": "362nd_Andre-1"}
        text = other(wing, lead, naming, set())

        line = (f"362nd_Sockeye-1 (P-51D-30-NA, manned) IN FORMATION with {text}"
                f" — 2 ships, lead 13.5 nm on the 307 radial, 5,952 ft, "
                f"heading 062, 281 knots")
        units = {u.name: u for u in identity.units_on(line)}
        self.assertIn("362nd_Andre-1", units, f"could not read back: {text!r}")
        self.assertEqual(units["362nd_Andre-1"].type, "P-51D-30-NA")
        self.assertTrue(units["362nd_Andre-1"].manned)

        # And the distance the renderer computed is the distance the bridge reads.
        def xy(nm, radial):
            r = math.radians(radial)
            return nm * math.sin(r), nm * math.cos(r)
        ax, ay = xy(13.5, 307)
        bx, by = xy(13.7, 307.5)
        self.assertAlmostEqual(
            A.miles_between(line, "362nd_Andre-1", "362nd_Sockeye-1"),
            round(math.hypot(ax - bx, ay - by), 1), places=2)

    def test_a_wingman_on_the_ground_says_so(self):
        other = self._other_ship()
        lead = self.row("L-1", "L-1", "P-51D-30-NA", 0.1, 90, True)
        wing = self.row("W-1", "W-1", "P-51D-30-NA", 0.2, 90, True)
        text = other(wing, lead, {"L-1": "L-1", "W-1": "W-1"}, {"W-1"})
        line = (f"L-1 (P-51D-30-NA, manned, on the ground) IN FORMATION with "
                f"{text} — 2 ships, lead 0.1 nm on the 090 radial, 20 ft, "
                f"heading 130")
        u = next(u for u in identity.units_on(line) if u.name == "W-1")
        self.assertTrue(u.on_ground)
        self.assertTrue(u.manned)


if __name__ == "__main__":
    unittest.main()
