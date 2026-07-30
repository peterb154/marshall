"""The picture is drawn for ONE controller, and drawing it did not change it.

    "why is that using batumi and not bull?"

Because the wrong layer was drawing it. Rendering needs an origin, and an origin
belongs to the CONTROLLER, not the world -- so the director, which held the only
origin that existed, quietly made every consumer on the map read ranges from
Batumi's aerodrome reference and sorted their traffic by distance from it.

The renderer moved to the controller side. [#47] acceptance 5 says that must not
change what the agent reads, and this file is the proof.

TWO KINDS OF EXPECTATION HERE, and the difference is worth stating rather than
leaving somebody to assume:

  * GOLDEN, CAPTURED. `LIVE_*` is a real response from the running director on
    30 July -- one F-16 on the ramp at Batumi -- pasted verbatim. Rendering its
    contacts with the DIRECTOR'S origin must reproduce its prose byte for byte.
    That is the port being faithful, and nothing about it is derived from the
    code being tested.
  * DERIVED. The formation and ground cases are built from the format strings in
    `tools/tracks.py:_render` and `_other_ship`, because that renderer cannot be
    imported here (it pulls in `strands` and a database pool) and inventing a
    second live capture would have meant writing fake tracks into the board a
    pilot was flying on. They pin the SHAPE; the captured case pins the format.
"""

import unittest

from marshall.atc import picture

# The director's own reference, `tools/dcs.py:BATUMI_LAT, BATUMI_LON` -- the
# aerodrome point. Used ONLY to prove the port is faithful.
DIRECTOR_ORIGIN = (41.6103, 41.5997)
# route.py's BATUMI beacon, projected through the sim's converter. What a
# controller at Batumi actually measures from. A different point, and the
# difference is the finding.
OUR_BEACON = (41.609594, 41.600234)

# ---------------------------------------------------------------- captured
LIVE_CONTACT = {
    "name": "Viper 1-4", "label": "362nd_sockeye", "type": "F-16C_50",
    "category": "airplane", "manned": True, "player": "362nd_sockeye",
    "on_ground": False,
    "lat": 41.60646227764352, "lon": 41.608273992258795,
    "alt_ft": 39.011457144699094, "heading": 215.2639044900947,
    "speed_kt": 3.6589229157614784e-06, "coalition": 3,
    "callsign": "", "formation": "",
}
LIVE_PROSE = ("362nd_sockeye (F-16C_50, manned): 0.4 nm on the 121 radial, "
              "39 ft, heading 215, 0 knots")


class TestThePortIsFaithful(unittest.TestCase):
    """[#47] acceptance 5. The agent has read this format for weeks and its
    prompt is written around it, so moving the renderer must be invisible."""

    def test_the_same_origin_gives_byte_identical_prose(self):
        self.assertEqual(picture.picture([LIVE_CONTACT], DIRECTOR_ORIGIN),
                         LIVE_PROSE)

    def test_a_speed_of_almost_zero_still_prints_zero_knots(self):
        """The captured contact reports 3.66e-06 knots -- truthy, so the
        director printed ", 0 knots" rather than omitting it. A `> 0` test here
        would have silently dropped the field on every parked aeroplane, and
        the golden is the only reason anybody would notice."""
        self.assertIn("0 knots", picture.picture([LIVE_CONTACT], OUR_BEACON))

    def test_an_empty_scope_says_so(self):
        self.assertEqual(picture.picture([], OUR_BEACON), "no contacts")

    def test_no_origin_draws_nothing_rather_than_guessing(self):
        """A controller with no projected field must not quote ranges from
        somebody else's beacon, which is the bug this whole change is about."""
        self.assertEqual(picture.picture([LIVE_CONTACT], None), "no contacts")


class TestTheOriginIsTheOnlyThingThatMoves(unittest.TestCase):
    def test_our_beacon_reads_differently_from_the_directors_point(self):
        """Three degrees at half a mile is nothing. The same disagreement at
        forty miles is not, and through prose nobody could ever have seen it."""
        theirs = picture.picture([LIVE_CONTACT], DIRECTOR_ORIGIN)
        ours = picture.picture([LIVE_CONTACT], OUR_BEACON)
        self.assertIn("121 radial", theirs)
        self.assertIn("118 radial", ours)

    def test_a_second_field_renders_the_same_contact_its_own_way(self):
        """Senaki is not a second world. Same contacts, different origin."""
        senaki = picture.picture([LIVE_CONTACT], (42.0500, 42.0500))
        self.assertNotIn("0.4 nm", senaki)
        self.assertIn("362nd_sockeye", senaki)

    def test_nearest_first_is_from_OUR_field(self):
        """The ordering was an ORDER BY in the director measured from its
        constant, so a controller elsewhere got his traffic in somebody else's
        order before he had read a line of it."""
        near = dict(LIVE_CONTACT, name="near", label="near",
                    lat=41.62, lon=41.60)
        far = dict(LIVE_CONTACT, name="far", label="far",
                   lat=42.20, lon=41.60)
        got = picture.picture([far, near], OUR_BEACON)
        self.assertLess(got.index("near"), got.index("far"))
        # ...and from a field up the coast the order reverses.
        got2 = picture.picture([far, near], (42.30, 41.60))
        self.assertLess(got2.index("far"), got2.index("near"))


def ship(name, lat, lon, **kw):
    return {"name": name, "label": kw.get("label", name),
            "callsign": kw.get("callsign", ""),
            "type": kw.get("type", "P-51D-30-NA"),
            "category": kw.get("category", "airplane"),
            "manned": kw.get("manned", True), "on_ground": kw.get("on_ground", False),
            "lat": lat, "lon": lon, "alt_ft": kw.get("alt_ft", 6004),
            "heading": kw.get("heading", 151), "speed_kt": kw.get("speed_kt", 0),
            "coalition": 2, "formation": kw.get("formation", "")}


class TestFormationsDrawAsOneContact(unittest.TestCase):
    """Shape derived from `_render`/`_other_ship`. The collapse is a
    PRESENTATION -- four ships in trail ARE one contact to a human -- and it is
    applied here, where presentation belongs, over data that never collapsed."""

    LEAD = ship("Pony-1", 41.70, 41.60, label="Pony-1", callsign="Pony 1")
    WING = ship("Pony-2", 41.705, 41.605, label="Pony-2", formation="Pony-1")

    def setUp(self):
        self.LEAD = dict(self.LEAD, formation="Pony-1")

    def test_one_line_for_the_formation(self):
        got = picture.render([self.LEAD, self.WING], OUR_BEACON)
        self.assertEqual(len(got), 1)
        self.assertIn("IN FORMATION with", got[0])
        self.assertIn("2 ships", got[0])

    def test_the_lead_is_the_one_the_streamer_named(self):
        """Not whoever happens to be nearest us. Two controllers must agree on
        who lead is, and only the world can say."""
        got = picture.render([self.WING, self.LEAD], OUR_BEACON)[0]
        self.assertTrue(got.startswith("Pony-1"), got)

    def test_the_wingman_keeps_his_airframe_and_his_offset(self):
        got = picture.render([self.LEAD, self.WING], OUR_BEACON)[0]
        self.assertIn("Pony-2 (P-51D-30-NA, manned,", got)
        self.assertRegex(got, r"Pony-2 \(P-51D-30-NA, manned, 0\.\d nm\)")

    def test_the_bracketed_tag_is_printed_when_something_correlated_one(self):
        got = picture.render([self.LEAD, self.WING], OUR_BEACON)[0]
        self.assertTrue(got.startswith("Pony-1 [Pony 1] ("), got)

    def test_two_singles_that_are_not_a_formation_get_two_lines(self):
        a = ship("A", 41.70, 41.60)
        b = ship("B", 41.705, 41.605)
        self.assertEqual(len(picture.render([a, b], OUR_BEACON)), 2)


class TestTheMarkersSurvive(unittest.TestCase):
    """Every one of these is read by something downstream, and each was added
    after a specific failure -- see the comments in `_marks`."""

    def test_ground_units_say_so_on_the_lead_and_the_wingmen(self):
        lead = ship("Armour-1", 41.9, 41.9, type="T-55", category="ground",
                    manned=False, formation="Armour-1")
        wing = ship("Armour-2", 41.901, 41.9, type="T-55", category="ground",
                    manned=False, formation="Armour-1")
        got = picture.render([lead, wing], OUR_BEACON)[0]
        self.assertIn("(T-55, ground)", got)
        self.assertIn("Armour-2 (T-55, ground,", got)

    def test_on_the_ground_comes_from_the_sim_not_from_altitude(self):
        got = picture.render([ship("X", 41.7, 41.6, on_ground=True)],
                             OUR_BEACON)[0]
        self.assertIn(", manned, on the ground)", got)

    def test_an_ai_is_not_marked_manned(self):
        got = picture.render([ship("AI", 41.7, 41.6, manned=False)],
                             OUR_BEACON)[0]
        self.assertNotIn("manned", got)


if __name__ == "__main__":
    unittest.main()
