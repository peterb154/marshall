"""The controller decides which plan; the engine only checks it is real.

    15:13:08  PILOT  Roger Sock, I would like Batumi Test, IFR to Batumi.
    15:13:20  ATC    two plans fit that -- say which: transit and recovery
                     filed as Batumi Test, or transit and recovery filed as
                     Domino.

He named it. `plans.score` gave 100 points for naming a plan outright and could
not fire, because the test was `label in said` and a label is TYPED
(`BatumiTest`) while a request is SPOKEN ("Batumi Test"). Only `destination`
scored, which both plans shared, so they tied and the controller was handed a
question to ask whose answer was already in the transmission.

THE FIRST FIX WAS TO MATCH LETTERS INSTEAD OF CHARACTERS, and it worked, and it
was wrong:

    "lets not implement stopgaps"

It would have left the design in place -- five hand-weighted point values, a
noise list, an address parser and a stop-word set, all reimplementing
comprehension in front of a model that comprehends. The scorer was a worse
language model sitting in front of a good one. The controller calls the tool
having read the pilot's words, with every filed label in his prompt and the
conversation behind him; he passed the raw transcript IN and a matcher with
none of that context decided.

SO THE JUDGMENT MOVED AND THE ASSIGNMENT DID NOT. `request_clearance` now takes
a LABEL the controller has chosen. What is left in `plans` is `named` -- an
exact lookup -- because which plan an aeroplane is issued decides what it is
cleared for, and that must be settled by a key rather than a judgment. Same
line #177 drew for approaches: the language half chooses the words, the engine
records the fact.

WHAT THIS FILE CAN AND CANNOT HOLD. It holds the engine's half: a real label
resolves however it is spelled, an unfiled one is refused, and the refusal says
what IS on the board. It CANNOT hold "he named it, so do not ask him" -- that
is now a judgment, and it is scored by the flight test card (G3-G7) and by a
pilot, not here. Pretending otherwise would put the scorer back one assertion
at a time.  [#183, #182]
"""

from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

from marshall.atc import plans

ROOT = Path(__file__).resolve().parents[1]


def _plan(label: str) -> dict:
    """Two plans differing ONLY by name, which is the flown case."""
    return {"label": label, "origin": "KOBULETI", "destination": "BATUMI",
            "task": "transit and recovery", "route": ""}


BOARD = [_plan("BatumiTest"), _plan("Domino")]


class ANamedPlanIsFoundHoweverItIsSpelled(unittest.TestCase):
    """A label is typed once and said many times, and the two never agree.

    This is normalisation of a known identifier, not matching -- there is no
    scoring and no second-best. It exists because the controller reads the
    label back out of his own transmission and may space it as a human would.
    """

    def test_the_spellings_that_all_mean_one_plan(self):
        for said in ("BatumiTest", "Batumi Test", "batumi test",
                     "batumi-test", "BATUMI  TEST", "  BatumiTest  "):
            with self.subTest(said):
                got = plans.named(said, BOARD)
                self.assertIsNotNone(got, f"{said!r} did not find the plan")
                self.assertEqual(got["label"], "BatumiTest")

    def test_the_other_one_too(self):
        self.assertEqual(plans.named("Domino", BOARD)["label"], "Domino")

    def test_a_label_nobody_filed_is_not_found(self):
        self.assertIsNone(plans.named("Marlin", BOARD))

    def test_an_empty_label_finds_nothing(self):
        """`"" in anything` is True, which is how a lookup like this usually
        goes wrong."""
        for empty in ("", "   ", None, "---"):
            with self.subTest(repr(empty)):
                self.assertIsNone(plans.named(empty, BOARD))

    def test_it_does_not_match_on_a_substring(self):
        """`named` is exact after normalising. A plan called Domino must not
        answer to "Dom", and "BatumiTest" must not be found by "Batumi" --
        which the destination is, and which a pilot says constantly."""
        for near in ("Dom", "Batumi", "Test", "BatumiTestFlight"):
            with self.subTest(near):
                self.assertIsNone(plans.named(near, BOARD))


class AnUnfiledNameIsRefusedWithTheBoard(unittest.TestCase):
    """A refusal that only says "no" makes a pilot guess, and he will guess at
    what he already said.

    #126, one noun over: he was told his FLIGHT was missing when his PLAN was
    on file the whole time, and went hunting where nothing was wrong.
    """

    def test_it_names_what_is_filed(self):
        said = plans.whats_filed(BOARD)
        self.assertIn("BatumiTest", said)
        self.assertIn("Domino", said)

    def test_one_plan_reads_as_one_plan(self):
        self.assertIn("only plan", plans.whats_filed([_plan("Domino")]))

    def test_an_empty_board_says_so_rather_than_listing_nothing(self):
        self.assertIn("Nothing is on file", plans.whats_filed([]))


class TheScorerIsGoneAndStaysGone(unittest.TestCase):
    """The guard on the design, not on a case.

    Every one of these came back the moment somebody wanted a slightly better
    match, and each is individually reasonable. Together they are a language
    model made of regexes. If plan resolution needs improving, it is the
    controller's prompt that needs it.
    """

    RETIRED = ("score", "pick", "ask_which", "_squash", "_spoken",
               "_addressed_field", "_words")

    def test_none_of_it_is_back(self):
        for gone in self.RETIRED:
            with self.subTest(gone):
                self.assertFalse(
                    hasattr(plans, gone),
                    f"plans.{gone} is back. Resolution is the controller's "
                    f"judgment (#183); this module validates a label and "
                    f"issues a clearance.")

    def test_the_tool_takes_a_label_and_not_a_transcript(self):
        """THE CONTRACT, asserted where it is declared.

        `said: str = ""` is what made the engine responsible for
        comprehension. A default would also let the controller call it having
        chosen nothing, which is the failure this whole change exists to stop
        -- so the parameter is named `plan` and it is required.
        """
        src = (ROOT / "src" / "marshall" / "atc" / "clearance.py").read_text()
        fn = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "request_clearance")
        args = [a.arg for a in fn.args.args]
        self.assertEqual(args, ["callsign", "plan"])
        self.assertEqual(fn.args.defaults, [],
                         "`plan` has a default, so the controller can ask for "
                         "a clearance without having decided on one")

    def test_the_tool_tells_the_controller_to_ask_when_he_cannot_tell(self):
        """#165's rule did not move -- only who applies it. It has to be IN
        the tool description, because that is the only place the controller
        reads about this tool."""
        from marshall.atc import clearance
        doc = inspect.getsource(clearance)
        start = doc.index("def request_clearance")
        body = doc[start:start + 2000].lower()
        self.assertIn("if you cannot tell, ask him", body)
        self.assertIn("do not call this with a guess", body)


if __name__ == "__main__":
    unittest.main()
