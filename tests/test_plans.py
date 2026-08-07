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
        # The AGENT wrote this, not the engine, so it says "five".
        # `tts.SAY_AS` turns it into "fife" on the way to the radio --
        # see that table on why the fix lives in the audio.
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


class TestNamingSomethingNobodyFiled(unittest.TestCase):
    """"Request clearance" and "request clearance to Vaziani" are different
    questions. The first names nothing and deserves the list; the second names
    somewhere nobody filed for, and answering it with a list of three plans that
    all go elsewhere answers a question he did not ask."""

    def test_a_destination_nobody_filed_for_matches_nothing(self):
        got = P.pick("Hoover one one, request clearance to Vaziani",
                     FILED, callsign="Hoover 1-1")
        self.assertTrue(got.get("none"))

    def test_a_task_nobody_filed_matches_nothing(self):
        got = P.pick("Hoover one one, clearance for the tanker track",
                     FILED, callsign="Hoover 1-1")
        self.assertTrue(got.get("none"))

    def test_naming_nothing_at_all_still_gets_the_list(self):
        got = P.pick("Hoover one one, request clearance", FILED,
                     callsign="Hoover 1-1")
        self.assertEqual(len(got.get("ambiguous") or []), len(FILED))

    def test_his_own_callsign_is_not_a_place(self):
        """Without taking his name out of what he said, "Hoover" is a word that
        matches no plan and every request reads as a request for somewhere
        nobody filed for."""
        got = P.pick("Hoover one one, request clearance for the ferry",
                     FILED, callsign="Hoover 1-1")
        self.assertEqual((got.get("plan") or {}).get("name"), "ferry")

    def test_an_unknown_caller_is_asked_rather_than_refused(self):
        """With no callsign there is no way to tell his name from a place, so
        the rule stands down. Asking is the safe way to be wrong."""
        got = P.pick("Hoover one one, request clearance to Vaziani", FILED)
        self.assertTrue(got.get("ambiguous"))
        self.assertFalse(got.get("none"))


class TestTheWordsOfTheQuestion(unittest.TestCase):
    """A plan's name is not a callsign, and the controller has to be given the
    word for it. Handed a bare label he reached for the only name-on-a-radio he
    knows and said "callsign Kettle", which tells a pilot there is an aeroplane
    out there called Kettle."""

    def test_the_label_is_offered_as_something_FILED(self):
        said = P.ask_which(FILED[:2])
        self.assertIn("filed as", said)
        self.assertNotIn("callsign", said.lower())

    def test_it_describes_them_before_it_names_them(self):
        """A pilot recognises what he is doing faster than a name he was given
        yesterday, so the task comes first in each option."""
        said = P.ask_which(FILED[:1])
        self.assertLess(said.index("CAS over Tsutsnvati"), said.index("filed as"))


class TestOpeningAPlanIsNotNamingOne(unittest.TestCase):
    """From the sortie of 28 July, where a pilot asked the ordinary question and
    was told nothing on file matched.

        21:28:48  "we'd like to open the flight plan for Pony Flight"
                  -> "Nothing is on file that matches."

    `open` was not in the noise list, so one surviving word made the request
    read as NAMING somewhere nobody had filed for -- which is the branch that
    exists to stop "request clearance to Vaziani" being answered with a menu.
    The no-name branch, which offers him what is on file, never ran.

    What he wants DONE with a plan is never WHICH plan.
    """

    def test_open_the_flight_plan_offers_what_is_on_file(self):
        got = P.pick("Pony one one, we'd like to open the flight plan",
                     FILED, callsign="Pony 1-1")
        self.assertFalse(got.get("none"),
                         "asking to open a plan is not asking for a plan "
                         "nobody filed")
        self.assertTrue(got.get("plan") or got.get("ambiguous"))

    def test_the_phrasings_that_all_mean_the_same_thing(self):
        for said in ("request clearance, ready to copy",
                     "we'd like to open our flight plan",
                     "like to pick up our IFR flight plan",
                     "requesting to activate the flight plan"):
            with self.subTest(said=said):
                got = P.pick(said, FILED, callsign="Pony 1-1")
                self.assertFalse(got.get("none"), said)

    def test_naming_a_plan_still_wins_over_the_verb(self):
        """Made noise-deaf, not deaf. "Pick up Samovar Three" still names one."""
        got = P.pick("like to pick up our IFR flight plan Samovar Three",
                     FILED, callsign="Falcon 1-1")
        self.assertEqual((got.get("plan") or {}).get("label"), "Samovar Three")

    def test_a_place_nobody_filed_for_is_still_refused(self):
        """The guard the noise list must not dissolve."""
        got = P.pick("we'd like to open the flight plan to Vaziani",
                     FILED, callsign="Pony 1-1")
        self.assertTrue(got.get("none"))


class TestAPlanOnFileBelongsToNobody(unittest.TestCase):
    """A plan becomes a pilot's at the moment a clearance is issued -- copied
    into `assigned_plans` against his flight_id -- and not one instant earlier.

    Two of the six templates on the live box carry a callsign, seeded back when
    a plan was written beside the aeroplane meant to fly it. `pick` acted on it:
    one plan bearing his callsign was handed over as "the one on file for you".

    That is a THIRD source of names, beside a pilot's own handle and a flight
    somebody created, and it is the same kind as the "Falcon" that cost a
    sortie: a word that exists because a builder typed it, attached to no person
    and no flight. It matches a live pilot by coincidence.
    """

    ONE_EACH = [
        {"name": "asr", "label": "Samovar", "destination": "Batumi",
         "callsign": "Pony 1-1", "task": "CAS over Tsutsnvati", "route": ""},
        {"name": "ndb", "label": "Kettle", "destination": "Batumi",
         "callsign": None, "task": "Night patrol, coast", "route": ""},
    ]

    def test_a_template_callsign_does_not_choose_for_him(self):
        """He named nothing, and exactly one plan carries his callsign. The old
        branch handed it over; the answer is the list."""
        got = P.pick("Pony one one, request clearance, ready to copy",
                     self.ONE_EACH, callsign="Pony 1-1")
        self.assertIsNone(got.get("plan"),
                          "a plan nobody was cleared for was assigned on the "
                          "strength of a name typed in the mission editor")
        self.assertEqual(len(got.get("ambiguous") or []), 2)

    def test_the_column_is_not_even_read(self):
        """Filtered at the query, so it cannot come back by accident."""
        from tools.clearance import _TEMPLATE_COLS
        self.assertNotIn("callsign", _TEMPLATE_COLS)

    def test_one_plan_on_file_is_still_the_only_one_on_file(self):
        """Dropping the pre-assignment must not cost the case that is genuinely
        unambiguous -- one plan, nothing to choose between."""
        got = P.pick("request clearance, ready to copy",
                     self.ONE_EACH[:1], callsign="Pony 1-1")
        self.assertEqual((got.get("plan") or {}).get("label"), "Samovar")
        self.assertEqual(got.get("why"), ["the only one on file"])

    def test_he_can_still_have_it_by_asking_for_it(self):
        """Anonymous, not unreachable. Naming the task or the label works as it
        always did -- what is gone is getting it without asking."""
        got = P.pick("request clearance for the CAS over Tsutsnvati",
                     self.ONE_EACH, callsign="Hoover 1-1")
        self.assertEqual((got.get("plan") or {}).get("label"), "Samovar")


class TestTheStationHeCallsIsNotSomethingHeAskedFor(unittest.TestCase):
    """Every transmission opens by naming a station, and that name is where the
    pilot IS -- not what he wants.

    Both halves of this were found on a board trimmed to a single plan, which is
    what a night's flying actually uses. On the five-plan test board neither
    shows: there is always another plan to be ambiguous with, so a standing
    bonus to the local one changes no outcome.
    """

    ONE = [{"name": "362nd-kobuleti-batumi", "label": "Domino", "callsign": None,
            "origin": "Kobuleti", "destination": "Batumi", "cruise_ft": 5000,
            "route": "KOBULETI, INITIAL, BATUMI",
            "task": "Transit and radar recovery"}]

    def got(self, said):
        r = P.pick(said, self.ONE, callsign="Viper 1-1")
        if r.get("plan"):
            return r["plan"]["label"]
        return "ASK" if r.get("ambiguous") else "NONE"

    def test_the_plainest_request_there_is_gets_the_only_plan(self):
        """"Kobuleti Clearance, Viper one one, request clearance" answered NONE.
        The station name survived into the "did he name something specific?"
        test, so the plainest request in aviation read as a pilot asking for a
        sortie nobody had filed."""
        for said in ("Kobuleti Clearance, Viper one one, request clearance",
                     "Kobuleti Clearance, Viper one one, ready to copy",
                     "Kobuleti Ground, Viper one one, request IFR clearance"):
            with self.subTest(said=said):
                self.assertEqual(self.got(said), "Domino")

    def test_somewhere_nobody_filed_for_is_still_refused(self):
        """And the other direction, which is the dangerous one. Addressing a
        controller gave his field's plans four points on every transmission, so
        the man who asked for VAZIANI -- with one plan on the board -- was read
        back a clearance to Batumi. A real aerodrome, a real clearance, and not
        the one he asked for."""
        for said in ("Kobuleti Clearance, Viper one one, request clearance to Vaziani",
                     "Kobuleti Clearance, Viper one one, clearance for the tanker track"):
            with self.subTest(said=said):
                self.assertEqual(self.got(said), "NONE")

    def test_the_address_still_breaks_a_tie_it_did_not_create(self):
        """It is context, not noise. Where his own words already point at more
        than one plan, where he is calling from is what tells them apart."""
        two = [*self.ONE,
               {"name": "362nd-batumi-run", "label": "Kettle",
                "callsign": None, "origin": "Batumi",
                "destination": "Batumi", "cruise_ft": 5000,
                "route": "BATUMI, INITIAL, BATUMI",
                "task": "Transit and radar recovery"}]
        r = P.pick("Kobuleti Clearance, Viper one one, request the transit",
                   two, callsign="Viper 1-1")
        self.assertEqual((r.get("plan") or {}).get("label"), "Domino")
        self.assertIn("origin (from who he called)", r.get("why") or [])


if __name__ == "__main__":
    unittest.main()
