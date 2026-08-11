"""Refusing a plan that cannot be flown, which is the whole of the filer.

    "A plan can be filed without touching the database by hand."  -- [UI-1] #22

The form is twenty lines of HTML and anybody can write one. What makes filing
safe is that a plan naming a place nobody holds is refused at the moment
somebody types it and not on the radio at two hundred knots.

EVERY REFUSAL BELOW IS A MISTAKE SOMEBODY ACTUALLY MADE, most of them in the
week the filer was written:

    a fix that does not exist        the typo this module exists to catch
    a label already on the board     #56's board had one of these for weeks
    "Samovar One" / "Samovar Two"    migration 012, and the wrong sortie cleared
    a task repeating its endpoints   #57 -- confident answer to an ambiguous ask
    deleting the ACTIVE plan         #61 -- the bridge reads its approach there

`check` takes the board as arguments, so this suite needs no Postgres, no
container and no director. That is the point of the split -- see its docstring.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "director"))

from tools import filing as F

FIXES = {"batumi", "kobuleti", "initial", "feet wet", "ingress", "tsutsnvati",
         "egress", "kutaisi"}
APPROACHES = {"batumi-asr", "batumi-ndb"}
TAKEN = {"domino": "362nd-kobuleti-batumi", "marlin": "362nd-coast-patrol"}

# THE ROUTE IS THE ENROUTE PORTION. It used to read "BATUMI, FEET WET, BATUMI"
# -- the aerodrome written in twice beside the origin and destination columns
# that already hold it. See #127 and `filing.check`.
GOOD = {"name": "362nd-night-run", "label": "Kestrel", "origin": "Batumi",
        "destination": "Batumi", "route": "FEET WET",
        "cruise_ft": 3000, "task": "Night patrol of the coastline",
        "approach": "batumi-asr"}


def check(**over):
    plan = dict(GOOD)
    plan.update(over)
    return F.check(plan, fixes=FIXES, approaches=APPROACHES, taken=TAKEN,
                   updating=over.pop("updating", ""))


class TestWhatIsRefused(unittest.TestCase):

    def test_a_plan_that_is_fine_is_not_argued_with(self):
        bad, warn = check()
        self.assertEqual(bad, [])
        self.assertEqual(warn, [])

    def test_a_fix_nobody_holds(self):
        """The typo that motivated the whole module. INTIAL for INITIAL is one
        transposed letter and it reads perfectly well on screen."""
        bad, _ = check(route="INTIAL")
        self.assertTrue(bad)
        self.assertIn("INTIAL", bad[0])

    def test_it_names_WHICH_fix(self):
        """Not "invalid route". A six-fix route with one typo must say which of
        the six, or the person filing it reads all six again and picks wrong."""
        bad, _ = check(route="FEET WET, NOWHERE, EGRESS")
        self.assertEqual(len(bad), 1)
        self.assertIn("NOWHERE", bad[0])
        self.assertNotIn("EGRESS", bad[0])

    def test_a_route_is_case_and_space_insensitive(self):
        """The fix table is lowercase; routes are written in caps. Neither is
        wrong and the filer must not care."""
        bad, _ = check(route="  ingress ,Feet Wet,  EGRESS ")
        self.assertEqual(bad, [])

    def test_one_fix_is_a_perfectly_good_route(self):
        """CHANGED 11 August: it used to demand at least two.

        That rule only ever passed BECAUSE the endpoints were padding the list,
        and a genuine direct flight -- zero enroute fixes, which is most of what
        gets flown here -- could not be filed without writing them in twice.
        What the module actually cares about is unchanged: every fix NAMED is
        one the sim holds. See #127.
        """
        bad, _ = check(route="FEET WET")
        self.assertEqual(bad, [])

    def test_an_empty_route_is_direct(self):
        bad, _ = check(route="")
        self.assertEqual(bad, [])

    def test_repeating_an_aerodrome_is_warned_about_not_refused(self):
        # Every row filed before #127 does this, so it cannot be a refusal --
        # but it is the difference between "via" and "direct" and a controller
        # reads it out.
        bad, warn = check(route="BATUMI, FEET WET, BATUMI")
        self.assertEqual(bad, [])
        self.assertTrue(any("ENROUTE portion" in w for w in warn), warn)

    def test_a_label_already_on_the_board(self):
        bad, _ = check(label="Domino")
        self.assertTrue(any("already on the board" in b for b in bad))
        self.assertTrue(any("362nd-kobuleti-batumi" in b for b in bad))

    def test_a_label_with_a_spoken_number_in_it(self):
        """Migration 012's lesson, enforced instead of written down. A
        transcriber that turns "one" into "won" picks the wrong sortie."""
        for label in ("Samovar One", "Alpha 2", "Kettle Two"):
            with self.subTest(label=label):
                bad, _ = check(label=label)
                self.assertTrue(any("ONE word" in b for b in bad),
                                f"{label!r} was accepted")

    def test_editing_a_plan_does_not_collide_with_itself(self):
        """Re-filing Domino to fix its task must not be refused for having
        Domino's label."""
        bad, _ = F.check(dict(GOOD, name="362nd-kobuleti-batumi",
                              label="Domino"),
                         fixes=FIXES, approaches=APPROACHES, taken=TAKEN)
        self.assertEqual(bad, [])

    def test_an_approach_that_does_not_exist(self):
        bad, _ = check(approach="batumi-ils")
        self.assertTrue(any("no approach" in b for b in bad))

    def test_no_approach_at_all_is_allowed(self):
        """A plan may recover visually, or somewhere with no published
        procedure. Empty is a real answer."""
        bad, _ = check(approach="")
        self.assertEqual(bad, [])

    def test_the_things_a_controller_reads_back_are_required(self):
        for missing in ("origin", "destination", "task"):
            with self.subTest(missing=missing):
                bad, _ = check(**{missing: ""})
                self.assertTrue(any(missing in b for b in bad))

    def test_an_altitude_that_is_not_a_number(self):
        for alt in ("lots", "", None, 0, -500):
            with self.subTest(alt=alt):
                bad, _ = check(cruise_ft=alt)
                self.assertTrue(any("altitude" in b for b in bad))


class TestWhatIsOnlyWarnedAbout(unittest.TestCase):
    """Judgement, and the caller is told rather than overruled. A refusal has to
    be provable; these are hazards somebody may have a reason to accept."""

    def test_a_label_that_sounds_like_another(self):
        bad, warn = check(label="Dominion")
        self.assertEqual(bad, [], "a near-miss is a warning, not a refusal")
        self.assertTrue(any("sounds like" in w for w in warn))

    def test_a_label_that_merely_shares_a_letter_is_not_flagged(self):
        """The warning has to be worth reading. If every label trips it, it is
        noise and the next real one is ignored."""
        _, warn = check(label="Kestrel")
        self.assertEqual(warn, [])

    def test_a_task_that_repeats_its_own_destination(self):
        """#57. The endpoints have their own columns and are scored from them;
        repeating one gives this plan triple credit for the same word and turns
        an ambiguous request into a confident wrong answer."""
        _, warn = check(task="transit from Kobuleti to Batumi",
                        origin="Kobuleti", destination="Batumi")
        self.assertTrue(any("repeats the origin" in w for w in warn))
        self.assertTrue(any("repeats the destination" in w for w in warn))

    def test_a_task_naming_a_place_that_is_not_an_endpoint_is_fine(self):
        """Anvil's job IS going to Kobuleti and its destination is Batumi. That
        is a task doing exactly what a task is for."""
        _, warn = check(task="Escort a transport as far as Kobuleti",
                        origin="Batumi", destination="Batumi")
        self.assertEqual(warn, [])

    def test_an_altitude_that_is_not_a_round_hundred(self):
        _, warn = check(cruise_ft=5250)
        self.assertTrue(any("round hundred" in w for w in warn))


class TestTheRouteIsNormalisedOnTheWayIn(unittest.TestCase):

    def test_spacing_is_made_uniform(self):
        self.assertEqual(F.route_fixes("  A ,B,  C  "), ["A", "B", "C"])

    def test_a_trailing_comma_is_not_a_fix(self):
        """Typing a route and pausing leaves one. It is not a place called ""."""
        self.assertEqual(F.route_fixes("BATUMI, INITIAL,"), ["BATUMI", "INITIAL"])


if __name__ == "__main__":
    unittest.main()
