"""A read-back correction named its items in prose, so nothing checked them.

Found by `tools/ghost_flight.py --sortie` on 13 August, in the first run where
one aeroplane climbed the whole ladder under one callsign. The engine decided
this:

    CONTROLLER: Marlin three one, negative — say again one zero thousand,
                one two three decimal three.

and this reached the air:

    ATC[pilot/sonnet]: Marlin three one, negative — say again the altitude,
                       one zero thousand.

ONE OF TWO ITEMS WAS DROPPED AND NOTHING NOTICED, which is remarkable in a
system that verifies every other number it decides. The reason is exact:
`clearance_read_back` emitted `Decision(kind="say_again", note=what)`, and
`Decision.facts()` excludes `note` deliberately -- prose is not a fact. So the
one transmission whose entire purpose is to name numbers was the one
transmission with no numbers in it.

THE CONSEQUENCE IS WORSE THAN A DROPPED WORD. The frequency he never read back
is now a thing he has not been ASKED for, so no answer of his can end the
exchange however carefully he replies -- and the correction repeats for ever.
That is #134's unwinnable loop arriving through a door #134's fix did not
close.

The repair is that `decision.unspoken` returns the FIELDS rather than only how
they sounded, so a correction can be rebuilt as a decision carrying numbers,
and the ordinary verify-and-repair path does the rest. [#157]
"""

from __future__ import annotations

import unittest

from marshall.atc import controller as atc
from marshall.atc import decision as D
from marshall.atc import phrasebook
from tests import theatre as TH

# The pair from the sortie. Ten thousand and one two three decimal three.
ALT_FT = 10000
FREQ_MHZ = 123.3


def a_correction() -> D.Decision:
    """What the engine decided that day, built the way the engine builds it."""
    c = atc.Controller(TH.the_arrival())
    c._me = TH.station("clearance", TH.departure())
    c.bind("Marlin 3-1", track="Marlin 3-1")
    c.out.clear()
    c.clearance_read_back(
        "Marlin 3-1", correct=False,
        missed=("one zero thousand", "one two three decimal three"),
        facts={"altitude_ft": ALT_FT, "frequency_mhz": FREQ_MHZ})
    return next(d for d in (getattr(x, "decision", None) for x in c.out)
                if d is not None and d.kind == "say_again")


class TestTheCorrectionCarriesItsNumbers(unittest.TestCase):

    def setUp(self):
        self.d = a_correction()

    def test_the_altitude_is_a_field_not_a_phrase(self):
        self.assertEqual(self.d.altitude_ft, ALT_FT)

    def test_and_so_is_the_frequency(self):
        self.assertEqual(self.d.frequency_mhz, FREQ_MHZ)

    def test_so_facts_can_see_them(self):
        """`facts()` is what `/diag` shows and what `verify` is built around.
        Before this it returned {} for every correction ever made."""
        got = self.d.facts()
        self.assertEqual(got.get("altitude_ft"), ALT_FT)
        self.assertEqual(got.get("frequency_mhz"), FREQ_MHZ)

    def test_the_prose_is_still_there_for_a_human(self):
        """`note` was not the mistake -- being the ONLY thing was. It is what a
        log line reads and what the agent is handed to phrase."""
        self.assertIn("one two three decimal three", self.d.note)


class TestTheThirteenAugustTransmissionGoesRed(unittest.TestCase):
    """The regression the acceptance criteria ask for, driven verbatim.

    Two missing items in, one voiced, and the check must go red naming the
    other. Before the fix `verify` returned [] here -- there was nothing on the
    decision to check -- so this exact pair passed.
    """

    SPOKEN = ("Marlin three one, negative — say again the altitude, "
              "one zero thousand.")

    def setUp(self):
        self.d = a_correction()

    def test_the_dropped_frequency_is_caught(self):
        missed = D.verify(self.d, self.SPOKEN)
        self.assertTrue(missed, "the 13 August transmission still passes")
        self.assertIn("one two three decimal three", " ".join(missed))

    def test_and_it_names_the_FIELD_not_only_the_sound(self):
        lost = D.unspoken(self.d, self.SPOKEN)
        self.assertEqual([f.field for f in lost], ["frequency_mhz"])

    def test_the_altitude_he_DID_say_is_not_reported_missing(self):
        """A correction that demanded back what was already said would restate
        it on the air -- the frequency-filling this whole mechanism exists to
        avoid, arriving as its own fix."""
        self.assertNotIn("altitude_ft",
                         [f.field for f in D.unspoken(self.d, self.SPOKEN)])

    def test_a_transmission_carrying_both_passes(self):
        whole = ("Marlin three one, negative — say again one zero thousand, "
                 "one two three decimal three.")
        self.assertEqual(D.verify(self.d, whole), [])

    def test_the_OLD_shape_is_why_this_was_invisible(self):
        """The bug, kept as an executable statement of itself.

        A correction carrying only prose verifies CLEAN against a transmission
        that dropped half of it -- not "fails quietly", but reports success.
        That is why nothing ever noticed: the check ran, on every turn, and had
        nothing to look for.

        If this ever stops holding, `note` has started being treated as a fact
        somewhere, and the test above is passing for a reason that is not the
        fix.
        """
        old = D.Decision(kind="say_again", to="Marlin 3-1", note=self.d.note)
        self.assertEqual(old.facts(), {})
        self.assertEqual(D.verify(old, self.SPOKEN), [])


class TestAndItIsPutBack(unittest.TestCase):
    """Catching it is half. `repair` is why the pilot ever hears it."""

    def setUp(self):
        self.d = a_correction()

    def test_there_is_a_rendering_for_a_correction(self):
        """`repair` returns "" for a kind the phrasebook cannot render, and
        that silent no-op is correct -- inventing words is worse. But it meant
        `say_again` was recorded as unvoiced and never repaired."""
        self.assertTrue(D.repair(self.d), "no rendering for say_again")

    def test_the_repair_contains_what_went_missing(self):
        add = D.repair(self.d, said=TestTheThirteenAugustTransmissionGoesRed.SPOKEN)
        self.assertIn("one two three decimal three", add)

    def test_and_a_correction_that_was_fully_voiced_repairs_nothing(self):
        whole = ("Marlin three one, negative — say again one zero thousand, "
                 "one two three decimal three.")
        self.assertEqual(D.repair(self.d, said=whole), "")

    def test_an_old_correction_with_only_prose_still_renders_it(self):
        """Compatibility, stated rather than assumed: a decision carrying no
        typed facts falls back to the note. Anything else would turn a
        harmless old shape into silence on the radio."""
        old = D.Decision(kind="say_again", to="Marlin 3-1",
                         note="one zero thousand")
        self.assertEqual(phrasebook.render(old), "one zero thousand")


class TestTheEngineStillDecidesTheSentence(unittest.TestCase):
    """The two-brain rule, which this must not quietly cross.

    The engine names what he missed; the agent phrases it. Adding numbers to
    the decision must not turn the correction into a template the agent is
    bypassed for -- `repair` APPENDS to the agent's reply and is only reached
    when a fact went missing.
    """

    def test_the_transmission_is_still_composed_by_the_engine(self):
        c = atc.Controller(TH.the_arrival())
        c._me = TH.station("clearance", TH.departure())
        c.bind("Marlin 3-1", track="Marlin 3-1")
        c.out.clear()
        c.clearance_read_back("Marlin 3-1", correct=False,
                              missed=("one zero thousand",),
                              facts={"altitude_ft": ALT_FT})
        said = " ".join(x.text for x in c.out).lower()
        self.assertIn("negative", said)
        self.assertIn("say again", said)
        self.assertIn("one zero thousand", said)

    def test_a_correct_read_back_decides_nothing_to_say_again(self):
        c = atc.Controller(TH.the_arrival())
        c._me = TH.station("clearance", TH.departure())
        c.bind("Marlin 3-1", track="Marlin 3-1")
        c.out.clear()
        c.clearance_read_back("Marlin 3-1", correct=True)
        kinds = [getattr(getattr(x, "decision", None), "kind", "") for x in c.out]
        self.assertNotIn("say_again", kinds)

    def test_no_facts_still_produces_the_correction(self):
        """A caller that has the spoken forms and not the fields -- which is
        every caller that predates this -- must still get a transmission."""
        c = atc.Controller(TH.the_arrival())
        c._me = TH.station("clearance", TH.departure())
        c.bind("Marlin 3-1", track="Marlin 3-1")
        c.out.clear()
        c.clearance_read_back("Marlin 3-1", correct=False,
                              missed=("one zero thousand",))
        self.assertIn("one zero thousand",
                      " ".join(x.text for x in c.out).lower())


if __name__ == "__main__":
    unittest.main()
