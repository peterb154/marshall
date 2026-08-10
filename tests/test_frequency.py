import unittest
from marshall.atc.controller import spell_freq

class TestAFrequencyAlwaysCarriesItsDecimal(unittest.TestCase):
    """"Make frequency instructions include decimal always."

    Asked twice -- first as a debug note in the middle of an approach, then
    plainly. The code deliberately dropped a trailing .0 on the reasoning that
    nobody says "one three two decimal zero". They do.

    A bare "one two four" has to be RECOGNISED as a frequency from context, and
    a pilot reaching for a radio while flying an approach in cloud should not
    have to do that work. It also means he reads it back the same shape every
    time, and a read-back that is always the same shape is one a controller can
    check at a glance.
    """

    def test_a_whole_number_still_gets_its_decimal(self):
        self.assertEqual(spell_freq(124.0), "one two four decimal zero")
        self.assertEqual(spell_freq(118.0), "one one eight decimal zero")

    def test_a_fraction_is_unchanged(self):
        self.assertEqual(spell_freq(128.5), "one two eight decimal five")

    def test_two_places_survive(self):
        self.assertEqual(spell_freq(124.25), "one two four decimal two five")

    def test_every_channel_on_the_card_has_one(self):
        """The four a pilot actually selects. None may come out bare."""
        for mhz in (139.0, 124.0, 118.0, 131.0):
            with self.subTest(mhz):
                self.assertIn("decimal", spell_freq(mhz))

    def test_the_agent_is_told_the_rule_too(self):
        """Half the frequencies a pilot hears are spoken by the model, not by
        spell_freq, so fixing the function alone fixes half the problem.

        Deliberately NOT a grep for bare frequencies across the source. The
        first version of this test was exactly that, and it flagged four lines
        of PROSE EXPLAINING THE RULE -- the docstring, the rule itself, a
        comment. A check that fires on its own documentation is the cry-wolf
        failure this project has already been bitten by twice today, and it
        gets switched off rather than fixed.
        """
        import pathlib

        rules = (pathlib.Path(__file__).resolve().parents[1]
                 / "src" / "marshall" / "atc" / "agent" / "prompts" / "rules.md").read_text(encoding="utf-8")
        self.assertIn("decimal", rules)
        self.assertRegex(rules, r"(?i)frequenc\w*\s+carries\s+its\s+decimal")


if __name__ == "__main__":
    unittest.main()


class TestNoWrittenCallsignReachesThePilot(unittest.TestCase):
    """"batumi tower thought I was falcon 121 again.. approach never did that"

    "Falcon 1-1" is how this system WRITES a callsign. Polly reads the hyphen
    and says "Falcon one TO one", which a pilot hears as a different aeroplane
    and reports as the controller not knowing who he is.

    One path did it -- the canned replies, a radio check and a closing
    acknowledgement -- and everything else happened to spell the callsign
    properly, which is luck rather than design. So it is caught in `for_voice`,
    where every transmission passes, as well as fixed at the source.

    It took most of an evening because that path TRANSMITTED WITHOUT RECORDING.
    The words the pilot heard were nowhere in the flight recorder, so the hunt
    went to the sim's own ATC and to Polly's voices -- anything except the line
    we had actually said. It records now.
    """

    def test_the_hyphen_never_reaches_the_air(self):
        from marshall.atc.agent_atc import for_voice
        self.assertEqual(for_voice("Falcon 1-1, roger, taxi to parking."),
                         "Falcon one one, roger, taxi to parking.")

    def test_a_wingman_too(self):
        from marshall.atc.agent_atc import for_voice
        self.assertIn("Pony one two", for_voice("Pony 1-2, turn left."))

    def test_an_already_spoken_callsign_is_untouched(self):
        from marshall.atc.agent_atc import for_voice
        self.assertEqual(for_voice("Hoover one one, cleared to land."),
                         "Hoover one one, cleared to land.")

    def test_the_canned_replies_spell_it_at_the_source(self):
        """The backstop must not be the only defence: a reply composed wrongly
        is still wrong in the log, which is what anybody debugging reads."""
        from marshall.atc.agent_atc import simple_response
        # A CLOSING ACKNOWLEDGEMENT, not a request. "taxi to parking" is now a
        # REQUEST and goes to the engine, where Ground answers it and Tower
        # refuses -- so it is no longer a canned reply at all (#77). The point
        # of this test is how a canned reply SPELLS a callsign, so it needs a
        # transcript that still gets one.
        said = simple_response("Batumi Tower, Falcon one one, down and stopped, "
                               "good day.")
        self.assertIsNotNone(said)
        self.assertNotIn("1-1", said)
        self.assertIn("Falcon one one", said)

    def test_a_runway_written_the_same_way_is_fixed_too(self):
        """Not a false positive -- the same defect wearing a different word.

        Polly reads EVERY digit-hyphen-digit as "to", so "Runway 1-3" comes out
        "runway one to three" exactly as the callsign did. The rule is about
        what the hyphen does to speech, not about callsigns specifically, so
        catching this as well is correct rather than incidental.
        """
        from marshall.atc.agent_atc import for_voice
        self.assertEqual(for_voice("Runway 1-3 is in use."),
                         "Runway one three is in use.")

    def test_ordinary_prose_is_left_alone(self):
        from marshall.atc.agent_atc import for_voice
        for text in ("Descend to two thousand.",
                     "Wind two seven zero at two zero.",
                     "Contact Tower one one eight decimal zero."):
            with self.subTest(text):
                self.assertEqual(for_voice(text), text)


class TestTheCannedRepliesKnowWhoIsTalking(unittest.TestCase):
    """A pilot's report: Batumi Ground "seems to be from a prior generation...
    not using callsigns, mispronouncing my callsign".

    It was from a prior generation. `simple_response` predates GUID identity and
    never learned about it -- it dug a callsign out of the WORDS with a regex,
    which is the mistake the rest of the system spent a fortnight removing. And
    closing calls are what land in this path, so Ground and Tower are where it
    showed.
    """

    def canned(self, said, known="Sockeye"):
        from marshall.atc.voice import simple_response
        return simple_response(said, known) or ""

    def test_a_readback_fragment_is_never_used_as_a_name(self):
        # Both are CLOSING acknowledgements. The taxi request that used to sit
        # here now goes to the engine instead of getting a canned reply (#77):
        # only Ground may clear a taxi, and a short-circuit that answers from
        # whatever seat is speaking cannot know which seat it is.
        for said in ("sockeye just off runway one three, down and stopped",
                     "sockeye is down and stopped, clear of the active"):
            with self.subTest(said=said):
                got = self.canned(said)
                self.assertTrue(got.startswith("Sockeye,"), got)
                self.assertNotIn("Runway", got)
                self.assertNotIn("The one", got)

    def test_the_radio_beats_the_transcript(self):
        """He calls himself something else entirely; the GUID says Sockeye."""
        got = self.canned("Falcon one one, clear of the runway")
        self.assertTrue(got.startswith("Sockeye,"), got)

    def test_with_no_identity_it_still_falls_back_to_the_words(self):
        """The regex earns its place only here -- an unidentified radio is the
        one case where what he said is all there is."""
        got = self.canned("Batumi Tower, Falcon one one, clear of the runway",
                          known="")
        self.assertTrue(got.startswith("Falcon one one,"), got)

    def test_and_never_a_hyphenated_callsign_over_the_air(self):
        """Polly reads "Falcon 1-1" as "Falcon one TO one"."""
        self.assertNotIn("-", self.canned("clear of the runway", "Falcon 1-1"))
