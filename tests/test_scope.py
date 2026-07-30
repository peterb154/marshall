"""The geometry reads structure, not prose. [#47]

    "you have range 0.4nm.. from what? I assume Batumi. But why? When we have
     50 controllers on the system - Batumi is just one fix"

Two defects, one root. The director held every track in PostGIS with real
coordinates, rendered them to one English string measured from a MODULE
CONSTANT, and the bridge parsed that string back with six regexes to recover
numbers that had been floats one process away.

  * the origin was Batumi's aerodrome reference, so every consumer on the map
    read ranges from one field -- and the rows even came back sorted by distance
    from it, so a controller elsewhere got his traffic in somebody else's order;
  * the collapse was lossy. A formation prints as ONE line, so a wingman had no
    position at all, and `flatten_formation` -- added to fix an earlier symptom
    -- deletes the wingmen before the position regexes ever see them.

A `Scope` is the prose (still the agent's input, untouched) plus the contacts it
was drawn from, plus THIS controller's origin. These tests are written against
that contract rather than against the parsers, and they are deliberately the
cases the prose could not express.
"""

import unittest

from marshall.atc import agent_atc as A
from marshall.atc import identity

# Batumi's beacon, as route.py's BATUMI projected through the sim's own
# converter -- not the director's aerodrome constant, which is a different point.
BATUMI = (41.609594, 41.600234)
# The blue bullseye the sim reports on this map, about forty miles north.
BULLSEYE = {"blue": {"lat": 42.186548, "lon": 41.678934}}


def contact(name, lat, lon, **kw):
    return {"name": name, "label": kw.get("label", name),
            "callsign": kw.get("callsign", ""), "type": kw.get("type", "P-51D"),
            "category": kw.get("category", "airplane"),
            "manned": kw.get("manned", True), "player": kw.get("player", ""),
            "on_ground": kw.get("on_ground", False),
            "lat": lat, "lon": lon,
            "alt_ft": kw.get("alt_ft", 4000), "heading": kw.get("heading", 90),
            "speed_kt": kw.get("speed_kt", 200), "coalition": 2,
            "formation": kw.get("formation", "")}


# A two-ship in formation. THIS IS THE CASE THAT MATTERS: in prose it is one
# line, the wingman has no position, and every parser in the system either
# misses him or is fed a flattened string with him deleted.
LEAD = contact("Pony-1", 41.70, 41.60, callsign="Pony 1-1", formation="Pony-1")
WING = contact("Pony-2", 41.705, 41.605, formation="Pony-1")
ALONE = contact("Hawk-1", 41.50, 41.70, callsign="Hawk 1-1")

SCOPE = A.Scope("prose the agent reads, not parsed here",
                contacts=[LEAD, WING, ALONE], origin=BATUMI, bullseye=BULLSEYE)


class TestTheScopeIsStillTheProse(unittest.TestCase):
    """A str subclass, so forty call sites that thread `scope: str` keep
    working while the geometry migrates one function at a time."""

    def test_it_is_the_picture(self):
        self.assertIsInstance(SCOPE, str)
        self.assertEqual(str(SCOPE), "prose the agent reads, not parsed here")

    def test_an_empty_scope_is_falsy_like_the_string_it_replaces(self):
        """Every `if scope:` in the bridge depends on this."""
        self.assertFalse(A.Scope(""))
        self.assertFalse(A.Scope("", contacts=[]))

    def test_it_carries_what_the_prose_was_drawn_from(self):
        self.assertEqual(len(SCOPE.contacts), 3)
        self.assertEqual(SCOPE.origin, BATUMI)


class TestTheOriginIsTheConsumersChoice(unittest.TestCase):
    """The whole point. One position, three references, none of them stored."""

    def test_range_is_measured_from_this_controllers_field(self):
        fix = A.radar_fix_by_track(SCOPE, "Hawk-1")
        self.assertIsNotNone(fix)
        # ~13 nm south-east of the beacon. The number is not the point; that it
        # came from OUR origin rather than a constant in another process is.
        self.assertGreater(fix.range_nm, 5)
        self.assertLess(fix.range_nm, 20)

    def test_the_same_contact_reads_differently_from_bullseye(self):
        """And that is correct, not a discrepancy. Bullseye is a RENDERING --
        the right one for anything shared between controllers, the wrong one for
        a talkdown, which needs range from the runway."""
        b = SCOPE.bullseye["blue"]
        from_field = A._range_radial(BATUMI, ALONE["lat"], ALONE["lon"])[0]
        from_bulls = A._range_radial((b["lat"], b["lon"]),
                                     ALONE["lat"], ALONE["lon"])[0]
        self.assertNotAlmostEqual(from_field, from_bulls, places=0)
        self.assertGreater(from_bulls, from_field)

    def test_a_second_field_gets_its_own_ranges(self):
        """Senaki is not a second world -- it is a second origin over the same
        contacts. This is what could not be expressed at all before."""
        senaki = (42.0500, 42.0500)
        here = A.Scope(str(SCOPE), contacts=SCOPE.contacts, origin=BATUMI)
        there = A.Scope(str(SCOPE), contacts=SCOPE.contacts, origin=senaki)
        a = A.radar_fix_by_track(here, "Hawk-1")
        b = A.radar_fix_by_track(there, "Hawk-1")
        self.assertNotAlmostEqual(a.range_nm, b.range_nm, places=0)

    def test_with_no_origin_it_does_not_guess(self):
        """A controller with no projected field falls through to the prose
        rather than quoting a range from somebody else's beacon."""
        s = A.Scope("", contacts=SCOPE.contacts, origin=None)
        self.assertIsNone(A.radar_fix_by_track(s, "Hawk-1"))


class TestEveryAeroplaneHasAPosition(unittest.TestCase):
    """[#47] acceptance 3, and the wingman gap from the 29 July audit."""

    def test_a_wingman_is_a_unit_in_his_own_right(self):
        names = {u.name for u in identity.units_on(SCOPE)}
        self.assertIn("Pony-2", names)
        self.assertIn("Pony-1", names)

    def test_a_wingman_has_a_position(self):
        """In prose he has none: a formation is ONE line, and
        `flatten_formation` deletes him before the position regexes run."""
        self.assertIsNotNone(A.radar_fix_by_track(SCOPE, "Pony-2"))

    def test_the_gap_inside_a_formation_is_measurable(self):
        """The join rule measures a real gap against a one-mile radius, so an
        upper bound was not good enough. Needs no origin -- it is a fact about
        the two aeroplanes."""
        gap = A.miles_between(SCOPE, "Pony-1", "Pony-2")
        self.assertIsNotNone(gap)
        self.assertLess(gap, 1.0)

    def test_being_in_a_formation_is_a_field_not_a_deletion(self):
        lead = SCOPE.of("Pony-1")
        wing = SCOPE.of("Pony-2")
        self.assertEqual(lead["formation"], "Pony-1")
        self.assertEqual(wing["formation"], "Pony-1")
        self.assertEqual(SCOPE.of("Hawk-1")["formation"], "")


class TestTheTagIsStillOnlyCorroboration(unittest.TestCase):
    """Reading structure must not quietly promote the bracketed callsign into
    an authority -- see identity.py. It is looked up, never believed."""

    def test_a_callsign_finds_its_track(self):
        self.assertEqual(A._track_tagged(SCOPE, "Hawk 1-1"), "Hawk-1")

    def test_a_member_finds_the_flight_tag_but_never_another_member(self):
        """"Pony 1-3" legitimately finds the formation's tag; it must never
        find a different member's own track."""
        self.assertEqual(A._track_tagged(SCOPE, "Pony 1-3"), "Pony-1")

    def test_an_untagged_contact_is_not_found_by_name(self):
        self.assertEqual(A._track_tagged(SCOPE, "Pony 1-2"), "Pony-1")


class TestGroundUnitsSurviveTheTrip(unittest.TestCase):
    """The category is carried, so `count_contacts` can still tell a tank from
    a fighter without the marker being re-parsed out of a parenthetical."""

    TANKS = A.Scope("", origin=BATUMI, contacts=[
        ALONE,
        contact("Armour-1", 41.9, 41.9, type="T-55", category="ground",
                manned=False),
        contact("Armour-2", 41.9, 41.901, type="T-55", category="ground",
                manned=False, formation="Armour-1")])

    def test_armour_is_not_traffic(self):
        self.assertEqual(A.count_contacts(self.TANKS), 1)

    def test_the_category_reaches_the_unit(self):
        cats = {u.name: u.category for u in identity.units_on(self.TANKS)}
        self.assertEqual(cats["Armour-1"], "ground")
        self.assertEqual(cats["Armour-2"], "ground")
        self.assertEqual(cats["Hawk-1"], "")


class TestTheProseStillWorks(unittest.TestCase):
    """Nothing is deleted yet. An older director, or a radar hiccup, and every
    consumer falls back to the parser it has always used."""

    PROSE = ("362nd_sockeye [Pony 1-1] (P-51D-30-NA, manned): 8.0 nm on the 281 "
             "radial, 4,000 ft, heading 100, 180 knots")

    def test_a_plain_string_still_parses(self):
        us = identity.units_on(self.PROSE)
        self.assertEqual(len(us), 1)
        self.assertEqual(us[0].name, "362nd_sockeye")

    def test_geometry_still_works_on_a_plain_string(self):
        fix = A.radar_fix_by_track(self.PROSE, "362nd_sockeye")
        self.assertAlmostEqual(fix.range_nm, 8.0, places=1)


if __name__ == "__main__":
    unittest.main()
