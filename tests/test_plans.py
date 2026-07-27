"""Resolving a spoken clearance request to a filed plan, and reading it back.

The civil key -- callsign plus destination -- separates nothing here, because a
sortie leaves Batumi, does something and comes back to Batumi. What separates
plans is what a pilot would say anyway: what he is doing and where.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "director"))

from tools import plans as P

FILED = [
    {"name": "asr", "label": "Samovar One", "destination": "Batumi",
     "callsign": "Pony 1-1", "cruise_ft": 9000,
     "route": "BATUMI, FEET WET, INGRESS, TSUTSNVATI, EGRESS, BATUMI",
     "task": "CAS over Tsutsnvati"},
    {"name": "ndb", "label": "Samovar Two", "destination": "Batumi",
     "callsign": "Pony 1-1", "cruise_ft": 5000,
     "route": "BATUMI, FEET WET, BATUMI", "task": "Night patrol, coast"},
    {"name": "ferry", "label": "Samovar Three", "destination": "Batumi",
     "callsign": None, "cruise_ft": 7000,
     "route": "BATUMI, FEET WET, KUTAISI, BATUMI",
     "task": "Ferry spares to Kutaisi"},
]


class TestFindingThePlanHeMeans(unittest.TestCase):
    def picked(self, said, callsign="Hoover 1-1"):
        r = P.pick(said, FILED, callsign=callsign)
        return r.get("plan", {}).get("label"), r

    def test_by_what_he_is_doing_and_where(self):
        for said in ("request clearance, CAS over Tsutsnvati",
                     "request my clearance for the CAS",
                     "ready to copy, the Tsutsnvati one"):
            with self.subTest(said=said):
                self.assertEqual(self.picked(said)[0], "Samovar One")

    def test_by_the_label_when_he_names_it(self):
        self.assertEqual(self.picked("request clearance on Samovar Three")[0],
                         "Samovar Three")

    def test_any_pilot_may_take_any_plan(self):
        """Templates are filed against nobody. Samovar One says 'Pony 1-1' and
        Hoover must still be able to fly it."""
        self.assertEqual(self.picked("clearance for the CAS", "Hoover 1-1")[0],
                         "Samovar One")

    def test_the_civil_phrasing_cannot_separate_them(self):
        """Everything returns to Batumi, so destination is nearly free -- and it
        must not outweigh a task word."""
        _, r = self.picked("request clearance, IFR to Batumi, ready to copy")
        self.assertIn("ambiguous", r)
        self.assertEqual(len(r["ambiguous"]), 3)

    def test_ambiguity_asks_rather_than_guessing(self):
        _, r = self.picked("request clearance")
        self.assertIn("ambiguous", r)
        said = P.ask_which(r["ambiguous"])
        self.assertIn("CAS over Tsutsnvati", said)
        self.assertIn("Say which", said)

    def test_it_says_why_it_matched(self):
        """So the controller can say 'the CAS to Tsutsnvati' rather than read
        out a database key."""
        _, r = self.picked("clearance for the ferry to Kutaisi")
        self.assertTrue(any("ferry" in w for w in r["why"]))

    def test_one_plan_on_file_needs_no_qualifier(self):
        r = P.pick("request clearance, ready to copy", [FILED[0]])
        self.assertEqual(r["plan"]["label"], "Samovar One")

    def test_nothing_on_file(self):
        self.assertIn("none", P.pick("request clearance", []))


class TestTheClearanceItself(unittest.TestCase):
    def craft(self, **kw):
        return P.clearance(FILED[0], flight_id=41, departure_freq=124.0,
                           initial_ft=5000, **kw)

    def test_craft_order(self):
        said = self.craft()
        for a, b in (("cleared to", "as filed"), ("as filed", "maintain"),
                     ("maintain", "departure frequency"),
                     ("departure frequency", "squawk")):
            self.assertLess(said.index(a), said.index(b), f"{a} before {b}")

    def test_as_filed_only_when_it_is(self):
        """A pilot who hears 'as filed' and got something else is the failure
        that phrase exists to prevent."""
        self.assertIn("as filed", self.craft())
        amended = self.craft(amended_route="BATUMI, FEET WET, BATUMI")
        self.assertNotIn("as filed", amended)
        self.assertIn("routing amended", amended)

    def test_an_amendment_reads_the_route_out(self):
        said = self.craft(amended_route="BATUMI, FEET WET, EGRESS, BATUMI")
        self.assertIn("Egress", said)

    def test_numbers_are_spoken(self):
        said = self.craft()
        self.assertIn("five thousand", said)
        self.assertIn("one two four decimal zero", said)
        self.assertNotIn("124.0", said)


class TestSquawksAreDecorationButNotNonsense(unittest.TestCase):
    """DCS models no transponder, so the code is invented -- but a controller
    never assigns 7700, and a squawk with an 8 in it is not a squawk."""

    def test_never_a_reserved_code(self):
        for i in range(4096):
            self.assertNotIn(P.squawk_for(i), P.RESERVED_SQUAWKS)

    def test_always_octal(self):
        for i in range(0, 4096, 7):
            self.assertRegex(P.squawk_for(i), r"^[0-7]{4}$")

    def test_stable_for_a_flight(self):
        """Asking twice must not change it, or a pilot reading back what he
        wrote down is wrong through no fault of his own."""
        self.assertEqual(P.squawk_for(41), P.squawk_for(41))

    def test_it_does_not_look_generated(self):
        """Straight modulo gave flight 1 the code 0001 and flight 2 the code
        0002 -- legal, deterministic, and obviously a computer."""
        first = [P.squawk_for(i) for i in (1, 2, 3)]
        self.assertNotEqual(first, ["0001", "0002", "0003"])


class TestTheRouteOnTheGround(unittest.TestCase):
    """Coordinates are not stored on the plan. They live in the fix table, which
    the sim projects from route.py -- one source of truth, so a plan and a chart
    cannot disagree about where INGRESS is."""

    FIXES = {"batumi": (41.6103, 41.5997), "feet wet": (41.6292, 41.3364),
             "ingress": (42.4872, 41.4502), "tsutsnvati": (42.2886, 42.8613)}

    def test_names_become_places(self):
        got, missing = P.route_fixes(
            {"route": "BATUMI, FEET WET, INGRESS"}, self.FIXES)
        self.assertEqual([f["name"] for f in got],
                         ["BATUMI", "FEET WET", "INGRESS"])
        self.assertEqual(missing, [])
        self.assertAlmostEqual(got[2]["lat"], 42.4872, places=3)

    def test_an_unfindable_fix_is_reported_not_dropped(self):
        """A route with a fix nobody can find strands a pilot halfway. The
        controller should refuse it at clearance delivery, not discover it on
        the third leg."""
        got, missing = P.route_fixes(
            {"route": "BATUMI, NOWHERE, INGRESS"}, self.FIXES)
        self.assertEqual(missing, ["NOWHERE"])
        self.assertEqual(len(got), 2)


class TestHowMuchHelpHeNeeds(unittest.TestCase):
    """An F-16 with an inertial platform does not want ranges read to him; a
    Mustang on a compass and a watch cannot manage without them."""

    def test_the_mustang_with_the_homer(self):
        self.assertEqual(P.nav_of("P-51D-30-NA"), "adf")

    def test_everything_else_in_the_hangar_is_dead_reckoning(self):
        for t in ("P-47D-30", "SpitfireLFMkIX", "F4U-1D"):
            with self.subTest(t=t):
                self.assertEqual(P.nav_of(t), "dr")

    def test_anything_modern_is_assumed_to_know_where_it_is(self):
        self.assertEqual(P.nav_of("F-16C_50"), "ins")

    def test_an_unknown_type_gets_the_cautious_answer(self):
        """Unknown here means unknown in a 1944 hangar, so assume he needs
        help -- the failure of guessing wrong that way is chatter, and the
        other way is a pilot left alone who cannot navigate."""
        self.assertEqual(P.nav_of(None), "dr")

    def test_each_level_says_what_to_do_about_it(self):
        for nav in ("ins", "adf", "dr"):
            with self.subTest(nav=nav):
                self.assertTrue(P.help_level(nav).strip())
