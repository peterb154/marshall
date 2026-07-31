"""One aeroplane, four names, one place that reconciles them.

`_key` was written THREE times -- `atc/identity.py`, `atc/agent_atc.py`,
`kneeboard/diag.py` -- plus a fourth in the diagnostics page's JavaScript. Each
looked correct in isolation, which is what makes this class of bug survive
review, and two of the three were not the same function:

    identity._key   re.sub(r"[^a-z0-9]", "", s.lower())
    diag._key       "".join(c for c in s.lower() if c.isalnum())

`isalnum()` is Unicode-aware and the character class is not. They agree on every
ASCII name anybody had tested with and disagree on everything else.

Nobody wrote that bug. It grew in the gap between two copies of one idea, which
is why the fix is not a better `_key` -- it is one `_key`.
"""

import unittest

from marshall.atc import agent_atc as A
from marshall.atc import identity
from marshall.core import names as N
from marshall.kneeboard import diag


class TestACyrillicPilotIsIdentifiable(unittest.TestCase):
    """The live bug, and the reason it mattered rather than merely differed.

    The ASCII-only squash reduced "Соколов" to the EMPTY STRING. That is not a
    worse answer than "соколов" -- it is a disqualifying one:
    `unit_for_radio` refuses any key under three characters, so the physical
    chain (radio -> sim unit -> track) could never close for him. He fell
    through to identification by ELIMINATION, which works with one aeroplane up
    and fails the moment a second joins.

    DCS is played in Russian, German and French. This is not an exotic input.
    """

    def test_cyrillic_survives_the_squash(self):
        self.assertEqual(N.squash("Соколов"), "соколов")

    def test_and_is_therefore_evidence(self):
        self.assertTrue(N.is_evidence("Соколов"),
                        "an empty key is below the three-character floor")

    def test_the_old_behaviour_is_what_we_are_asserting_against(self):
        """Written out so the regression is unmistakable if anyone reverts it."""
        import re
        was = re.sub(r"[^a-z0-9]", "", "Соколов".lower())
        self.assertEqual(was, "", "the old squash returned nothing at all")
        self.assertNotEqual(N.squash("Соколов"), was)


class TestAccentsFoldRatherThanVanish(unittest.TestCase):
    """"Jörg" and "Jorg" are one man.

    SRS takes its client name from the DCS export on one path and from a typed
    setting on another, so the same pilot can arrive spelled both ways in one
    sortie. Dropping the accented letter gave "jrg"; keeping it unfolded gave
    "jörg"; neither matches "jorg", so both were wrong in different directions.
    """

    def test_the_accented_and_plain_spellings_are_the_same_man(self):
        self.assertTrue(N.same("Jörg", "Jorg"))
        self.assertEqual(N.squash("Ångström"), "angstrom")

    def test_but_different_people_are_still_different(self):
        self.assertFalse(N.same("Jorg", "Georg"))


class TestThereIsOnlyOneOfThem(unittest.TestCase):
    """The point of the module. Guarded by identity, not by inspection.

    A fourth copy is easy to write and impossible to notice; this fails the
    moment one of the three stops being the shared function.
    """

    def test_every_caller_uses_the_same_object(self):
        self.assertIs(identity._key, N.squash)
        self.assertIs(A._key_name, N.squash)
        self.assertIs(diag._key, N.squash)

    def test_and_the_handle_rule_is_shared_too(self):
        self.assertIs(identity.handle, N.handle)

    def test_they_agree_on_everything_including_the_hard_cases(self):
        for name in ("362nd_Sockeye", "Sockeye", "Jörg", "Соколов",
                     "Ångström", "Müller-1", "Hoover 1-1-1", ""):
            with self.subTest(name=name):
                self.assertEqual(identity._key(name), A._key_name(name))
                self.assertEqual(identity._key(name), diag._key(name))


class TestTheHandleRuleIsUnchanged(unittest.TestCase):
    """Moving a function must not quietly re-decide what it does."""

    def test_the_squadron_tag_and_the_slot_number_both_go(self):
        self.assertEqual(N.handle("362nd_Sockeye"), "Sockeye")
        self.assertEqual(N.handle("Hoover 1-1-1"), "Hoover")
        self.assertEqual(N.handle("362nd Andre-1"), "Andre")

    def test_a_name_that_is_all_digits_falls_back_to_itself(self):
        """"Viper2" is still somebody."""
        self.assertEqual(N.handle("Viper2"), "Viper2")


if __name__ == "__main__":
    unittest.main()
