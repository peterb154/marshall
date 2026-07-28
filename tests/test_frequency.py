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
                 / "director" / "prompts" / "rules.md").read_text(encoding="utf-8")
        self.assertIn("decimal", rules)
        self.assertRegex(rules, r"(?i)frequenc\w*\s+carries\s+its\s+decimal")


if __name__ == "__main__":
    unittest.main()
