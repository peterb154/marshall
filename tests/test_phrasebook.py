"""Saying what changed, which needs memory the engine did not have.

    "The phrasing when calling a heading change was saying amend a lot. And
     unnecessary repeating altitude when it wasn't changing and it also was
     whipping the alts around, then finally sent to 2000 too early."

Four complaints, one cause and one consequence.

THE CAUSE: the engine composed each transmission from scratch with no idea what
it had already said. So every vector carried an altitude whether or not it had
moved, and every heading arrived labelled "amend" because the prompt says to
say that when changing something -- which, to a component with no memory, is
every time. Twenty-five of them in one sortie.

THE CONSEQUENCE: the descent planner recomputes against a descending aeroplane,
so its answer slides a few hundred feet every sweep. Every one of those numbers
is correct and none is worth a transmission -- and a continuous slide also
arrives at platform earlier than the stepped descent the profile intends, which
is the "2000 too early".
"""

import unittest

from marshall.atc import decision as D
from marshall.atc import phrasebook as P


def vec(hdg=None, alt=None, rng=None):
    return D.Decision(kind="vector", to="Sockeye", heading_deg=hdg,
                      altitude_ft=alt, range_nm=rng)


class TestOnlyWhatChanged(unittest.TestCase):

    def test_a_first_call_carries_everything(self):
        """He has just arrived and knows nothing."""
        said = P.render(vec(254, 6500), None)
        self.assertIn("two five four", said)
        self.assertIn("six thousand five hundred", said)

    def test_AN_UNCHANGED_ALTITUDE_IS_NOT_REPEATED(self):
        last = P.LastSaid(altitude_ft=5500, heading_deg=267)
        said = P.render(vec(305, 5500), last)
        self.assertIn("three zero five", said)
        self.assertNotIn("five thousand five hundred", said)

    def test_an_unchanged_heading_is_not_repeated(self):
        last = P.LastSaid(altitude_ft=5500, heading_deg=305)
        said = P.render(vec(305, 3000), last)
        self.assertNotIn("three zero five", said)
        self.assertIn("three thousand", said)

    def test_nothing_changed_means_nothing_said(self):
        """A renderer that always produces a sentence is what fills a
        frequency with restatements of things the pilot already did."""
        last = P.LastSaid(altitude_ft=3000, heading_deg=305)
        self.assertEqual(P.render(vec(305, 3000), last), "")

    def test_a_bare_range_is_not_a_transmission(self):
        """"fifteen miles from the field" with no instruction is a position
        report he can read off his own scope."""
        last = P.LastSaid(altitude_ft=3000, heading_deg=305)
        self.assertEqual(P.render(vec(305, 3000, rng=15), last), "")


class TestItDoesNotSayAmend(unittest.TestCase):
    """A routine vector is not an amendment. The word belongs to changing a
    clearance already given, and using it for every turn taught a pilot to
    ignore it -- 25 in one sortie."""

    def test_a_routine_turn_is_just_a_turn(self):
        self.assertNotIn("amend", P.render(vec(254, 6500), None))

    def test_but_a_real_amendment_can_still_say_so(self):
        said = P.render(vec(254, 6500), None, amended=True)
        self.assertTrue(said.startswith("amend"))


class TestTheDescentIsStepped(unittest.TestCase):
    """The planner slides; the pilot hears steps."""

    def test_a_few_hundred_feet_is_the_planner_not_an_instruction(self):
        last = P.LastSaid(altitude_ft=6500, heading_deg=254)
        self.assertNotIn("six thousand two hundred",
                         P.render(vec(254, 6200), last))

    def test_a_full_step_IS_said(self):
        last = P.LastSaid(altitude_ft=6500, heading_deg=254)
        self.assertIn("five thousand five hundred",
                      P.render(vec(254, 5500), last))

    def test_THE_MEMORY_HOLDS_WHAT_HE_WAS_TOLD_NOT_WHAT_WAS_COMPUTED(self):
        """The subtle one. If a suppressed slide still moved the memory, the
        next hundred-foot slide would look like a change from it and the
        whipping would come back one step slower."""
        last = P.LastSaid(altitude_ft=6500)
        for plan in (6400, 6300, 6200, 6100):
            d = vec(254, plan)
            last.update(d, P.changed(d, last))
        self.assertEqual(last.altitude_ft, 6500, "a suppressed slide moved it")

    def test_the_whole_sortie_reads_as_steps(self):
        """The sequence from the flight, through the phrasebook."""
        last, heard = P.LastSaid(), []
        for hdg, alt in [(254, 6500), (250, 6200), (267, 6000), (267, 5500),
                         (305, 5400), (305, 3000), (305, 2900)]:
            d = vec(hdg, alt)
            new = P.changed(d, last)
            said = P.render(d, last)
            last.update(d, new)
            if "altitude_ft" in new:
                heard.append(new["altitude_ft"])
            self.assertNotIn("amend", said)
        self.assertEqual(heard, [6500, 5500, 3000],
                         "the pilot heard the planner slide, not a descent")


class TestClimbIsNotDescend(unittest.TestCase):
    def test_a_higher_level_says_climb(self):
        last = P.LastSaid(altitude_ft=3000)
        self.assertIn("climb", P.render(vec(305, 5000), last))

    def test_a_lower_one_says_descend(self):
        last = P.LastSaid(altitude_ft=6000)
        self.assertIn("descend", P.render(vec(305, 3000), last))


if __name__ == "__main__":
    unittest.main()
