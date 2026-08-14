"""Clearance delivery decided it could not help without opening the file.

    "clearly he doesn't know how to find my flight plan"

    PILOT: Kobuleti Clearance, sockeye, IFR to Batumi with information delta.
    ATC:   Sockeye, I have no flight of that name on the board.
    PILOT: Call sign is Sakai requesting instruments to Batumi.
    ATC:   Sockeye, I have no flight on the board under either Sockeye or Sakai.
    PILOT: Kobuleti Clearance, sockeye, requesting Domino Flight plan.
    ATC:   Sockeye, negative, I have no flight on the board under that callsign.

`Domino` was on file the whole time and resolves from the plainest request
there is. `request_clearance` opened by finding the AEROPLANE and refused on
it, so the file was never opened -- three times, including the time the pilot
named the plan out loud.

THE PILOT WAS RIGHT ABOUT WHAT HE HEARD AND WRONG ABOUT THE CAUSE, which is
precisely the damage a refusal about the wrong noun does. He spent three
transmissions re-reading his flight plan, where nothing was wrong, because the
sentence he got was about a board he could not see.

#126 was closed once for the half that was a wiring bug -- `clearance_tools()`
searched the mission bucket `"default"` while the bridge wrote rows under the
sortie's key. That was real and is fixed. The symptom the issue is NAMED for
was not, and is what this file is about: the ORDER.

`resolve` is a pure lookup over `flight_plans` with no side effects and no
dependence on the board, so there was never a reason for it to run second.
"""

from __future__ import annotations

import unittest

from marshall.atc import board as B
from marshall.atc import clearance as C

# On file, and nothing else is. `pick` matches this on the destination alone
# and on "the only one on file" with no destination at all, which is what makes
# the transcript above so hard to read: every one of those three requests
# resolves.
DOMINO = {"name": "domino", "label": "Domino", "task": "IFR",
          "origin": "KOBULETI", "destination": "BATUMI",
          "legs": [{"fix": "KOBULETI", "alt_ft": 3000},
                   {"fix": "BATUMI", "alt_ft": 4000}]}


def tool_named(name: str, mission: str = "m1",
               station: str = "Kobuleti Clearance"):
    return next(x for x in C.clearance_tools(mission, station)
                if x.__name__ == name)


class _Stubbed(unittest.TestCase):
    """The file and the board, both replaced, because both are Postgres.

    `filed` is a module-level function `resolve` calls, and `board.find` is
    imported inside the tool -- so patching the modules reaches both without a
    database and without a director.
    """

    FILED: list = [DOMINO]
    BOARD: list = []          # nobody: the state the transcript was recorded in

    def setUp(self):
        self._filed, self._find, self._cs = C.filed, B.find, B.callsigns
        C.filed = lambda: list(self.FILED)
        B.find = lambda mission, callsign=None: next(
            (r for r in self.BOARD if r["callsign"] == callsign), None)
        B.callsigns = lambda mission: [r["callsign"] for r in self.BOARD]

    def tearDown(self):
        C.filed, B.find, B.callsigns = self._filed, self._find, self._cs


class TestTheFileIsOpenedBeforeTheRefusal(_Stubbed):

    def setUp(self):
        super().setUp()
        self.ask = tool_named("request_clearance")

    def said(self, words: str) -> str:
        return self.ask("Sockeye", words)

    def test_the_transcripts_first_request(self):
        """Verbatim. The plan is named in the answer, which is the fact that
        was missing from all three replies he actually got."""
        got = self.said("Kobuleti Clearance, sockeye, IFR to Batumi with "
                        "information delta")
        self.assertIn("Domino", got)

    def test_and_it_forbids_telling_him_the_plan_is_missing(self):
        """The sentence that sent him hunting. A refusal may be a refusal; it
        may not be a refusal about the wrong noun.

        ASSERTED AS A PROHIBITION PRESENT, not as words absent. The first
        version of this test swept for "not on file" and failed on the clause
        that FORBIDS saying it -- the text has to name the wrong sentence in
        order to rule it out, so a substring search cannot tell the rule from
        the violation. That is the same reading error as the bug itself: a
        string matched without regard to which noun it was about.
        """
        got = self.said("IFR to Batumi").lower()
        self.assertIn("the plan is on file", got)
        self.assertIn("do not say it is missing", got)

    def test_it_still_refuses_because_it_must(self):
        """A clearance is issued TO an aeroplane -- `assign` writes against a
        flight row -- and a sentence must not create one. So this is a refusal
        and the test says so, rather than quietly asserting a success that
        would mean the identity ladder had been talked past."""
        got = self.said("IFR to Batumi")
        self.assertNotIn("cleared to", got.lower())
        self.assertIn("NOT ON THE BOARD", got)

    def test_and_it_names_what_he_can_actually_fix(self):
        got = self.said("IFR to Batumi")
        self.assertIn("Sockeye", got)
        self.assertIn("callsign", got.lower())

    def test_the_third_request_named_the_plan_and_was_still_refused(self):
        """The one that makes the original transcript indefensible: he said the
        word `Domino` and was told there was no flight of that name."""
        got = self.said("Kobuleti Clearance, sockeye, requesting Domino "
                        "flight plan")
        self.assertIn("Domino", got)

    def test_it_says_who_IS_on_the_board(self):
        """The closed set, which the identity ladder gives us for free. A
        controller who can say who he has has told the pilot what to do next in
        one breath."""
        self.BOARD = [{"id": 7, "callsign": "Panther 2-6"}]
        self.assertIn("Panther 2-6", self.said("IFR to Batumi"))

    def test_an_empty_board_says_it_is_empty_rather_than_nothing(self):
        self.assertIn("empty", self.said("IFR to Batumi").lower())


class TestNothingOnFileIsStillItsOwnAnswer(_Stubbed):
    """The other branch, and the reason the order change is safe.

    "nothing is on file" and "you are not on the board" are two different
    facts, and the fix must not collapse them the other way -- a pilot who
    really has filed nothing must not be told his identity is wrong.
    """

    FILED: list = []

    def test_a_pilot_with_no_plan_is_told_about_the_plan(self):
        got = tool_named("request_clearance")("Sockeye", "IFR to Batumi")
        self.assertIn("on file", got.lower())
        self.assertNotIn("NOT ON THE BOARD", got)

    def test_even_when_he_is_not_on_the_board_either(self):
        """Both are wrong, and the FILE is the one he is asking about. This
        ordering is a judgement rather than a fact -- it is here so that
        changing it is deliberate."""
        got = tool_named("request_clearance")("Nobody", "IFR to Batumi")
        self.assertIn("on file", got.lower())


class TestAmbiguityStillWins(_Stubbed):
    """Two plans fit, and he is asked which -- before any board question.

    This is the branch that would silently regress if somebody restored the
    old order: asking a man to choose is useful whether or not he is on the
    board, and refusing him first throws the question away.
    """

    FILED: list = [DOMINO,
                   {"name": "ferry", "label": "Ferry", "task": "IFR",
                    "origin": "KOBULETI", "destination": "BATUMI",
                    "legs": [{"fix": "KOBULETI", "alt_ft": 3000},
                             {"fix": "BATUMI", "alt_ft": 9000}]}]

    def test_he_is_asked_which_one(self):
        got = tool_named("request_clearance")("Sockeye", "IFR to Batumi")
        self.assertIn("SAY THIS:", got)
        self.assertIn("Domino", got)
        self.assertIn("Ferry", got)


class TestTheOtherTwoToolsStillAskAboutTheAEROPLANE(_Stubbed):
    """Not every refusal is misordered, and this fix must not spread.

    `clearance_state` and the routing tool both need a flight row to look up
    what was ISSUED to it -- a fact about an aeroplane, not about the file. For
    those, "you are not on the board" is the correct and complete answer, and
    reordering them would be a change made by pattern-matching rather than by
    reading.
    """

    BOARD: list = []

    # NAMED EXACTLY, not guessed at. The first version listed `flight_intent`,
    # which does not exist -- and swallowed the StopIteration, so the loop ran
    # once and reported a pass for a class claiming to cover two tools. A test
    # that skips in silence is the thing this project keeps finding.
    OTHERS = ("clearance_state", "flight_plan_help")

    def test_the_named_tools_all_exist(self):
        have = {x.__name__ for x in C.clearance_tools("m1", "Kobuleti Clearance")}
        self.assertEqual(set(self.OTHERS) - have, set())

    def test_they_refuse_on_the_board(self):
        for name in self.OTHERS:
            with self.subTest(name):
                self.assertIn("NOT ON THE BOARD", tool_named(name)("Sockeye"))


if __name__ == "__main__":
    unittest.main()
