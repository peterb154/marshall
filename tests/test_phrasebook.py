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


class TestTheHeadingQuantumAndItsDeadband(unittest.TestCase):
    """Two numbers that are one decision.

        "Most times, especially en route, heading should be rounded to nearest
         5 degrees."

    Rounding alone made things WORSE, measurably: the sweep went from 0
    dithering to 7 and from 581 turns to 1614, nearly three times the direction
    changes. The cause was resonance -- the turn deadband was also five
    degrees, so every single rounding step landed exactly on the threshold and
    flipped the commanded turn.

    Widening the deadband to eight gave 576 turns and 0 dithering, better than
    the baseline it started from. This test is what stops the two drifting back
    together.
    """

    def test_THE_DEADBAND_IS_WIDER_THAN_THE_QUANTUM(self):
        from marshall.atc import geometry as G
        self.assertGreater(G.TURN_DEADBAND_DEG, G.HEADING_STEP_DEG,
                           "a single rounding step now lands on the threshold "
                           "-- expect the sweep to triple its turn count")

    def test_one_step_does_not_call_a_turn(self):
        """The property that matters, stated without the numbers."""
        from marshall.atc import geometry as G
        self.assertEqual(G.turn_direction(90, 90 + G.HEADING_STEP_DEG), "")

    def test_two_steps_does(self):
        from marshall.atc import geometry as G
        self.assertEqual(G.turn_direction(90, 90 + 2 * G.HEADING_STEP_DEG),
                         "right")

    def test_headings_come_out_in_fives(self):
        from marshall.atc import asr
        for raw in (251.2, 253.9, 267.0, 88.4):
            with self.subTest(raw=raw):
                self.assertEqual(asr._round_deg(raw, asr.HEADING_STEP_DEG) % 5, 0)

    def test_north_is_three_sixty_not_zero(self):
        from marshall.atc import asr
        self.assertEqual(asr._round_deg(359.6, 5), 360)


class DigitsNeverReachPolly(unittest.TestCase):
    """"runway 13" must not come out of the radio as "thirteen".

        "im not sure i understand why we are using thirteen vs one three?"

    Nor was there a good reason. `verify` was relaxed to ACCEPT digits so that
    enforcing #79 could not append a duplicate clearance to a transmission that
    already carried one -- a real hazard, and the wrong place to solve it.

    The evidence settled it: across 886 recorded agent transmissions, nine
    contained a digit and all nine were the "station calling ... say your
    callsign" template quoting the pilot back. The agent has never written a
    clearance number in digits. So this is a GUARANTEE rather than a repair --
    `for_voice` is the last thing between the agent and the air, and after this
    no aviation quantity can reach Polly as a numeral.

    NOT A BLANKET DIGIT-SPELLER, because the quantities disagree: a runway is
    spelled digit by digit and an ALTITUDE is not. "two zero zero zero feet" is
    nobody's phraseology.
    """

    def spell(self, s):
        from marshall.atc.voice import spell_numbers
        return spell_numbers(s)

    def test_runway(self):
        self.assertEqual(self.spell("runway 13, cleared for take-off"),
                         "runway one three, cleared for take-off")

    def test_runway_with_a_side(self):
        self.assertEqual(self.spell("runway 07L"), "runway zero seven left")

    def test_heading_keeps_its_leading_zero(self):
        self.assertEqual(self.spell("turn left heading 090"),
                         "turn left heading zero nine zero")

    def test_an_altitude_is_not_spelled_digit_by_digit(self):
        # The whole reason this is per-quantity rather than global.
        self.assertEqual(self.spell("descend to 2,000 feet"),
                         "descend to two thousand feet")
        self.assertEqual(self.spell("maintain 5000 ft"),
                         "maintain five thousand ft")

    def test_frequency(self):
        self.assertEqual(self.spell("contact Kobuleti Tower 133.0"),
                         "contact Kobuleti Tower one three three decimal zero")

    def test_speed_and_squawk(self):
        self.assertEqual(self.spell("250 knots"), "two five zero knots")
        self.assertEqual(self.spell("squawk 4271"), "squawk four two seven one")

    def test_wind(self):
        self.assertEqual(self.spell("wind 090 at 6"), "wind zero nine zero at six")

    def test_a_bare_number_is_left_alone(self):
        # "Flight of 2" and "in 5 minutes" are not aviation quantities with a
        # spoken convention, and a speller that guessed would be worse than one
        # that declines.
        self.assertEqual(self.spell("Flight of 2, in 5 minutes"),
                         "Flight of 2, in 5 minutes")

    def test_already_spoken_text_is_untouched(self):
        said = "runway one three, cleared for take-off"
        self.assertEqual(self.spell(said), said)

    def test_it_is_on_the_transmit_path(self):
        # It must run inside `for_voice`, which every transmission passes --
        # not at one call site that happens to remember.
        import inspect
        from marshall.atc import voice
        self.assertIn("spell_numbers(text)", inspect.getsource(voice.for_voice))
