"""The pilot's kneeboard exists, and every page on it renders.

There was no test for this. Not a weak one -- none, for the whole of
`kneeboard/`, which is every page a pilot reads: the brief, the route map, the
comms card, the nav log, the plans board, the plate, the E6B.

So this was true on `main`, on both maps, for an unknown length of time:

    >>> site.build()
    AttributeError: 'ApproachProfile' object has no attribute 'profile'

`comms.build` takes `(card, profile)` and every other page takes `(profile)`.
The call passed the procedure positionally, it landed in the CARD slot, and
`card.profile` raised. OpenKneeboard renders that as **"No Pages"** -- so the
pilot had no brief, no frequencies, no plate and no flight plan, from one
argument in the wrong position, and the suite was entirely green.

WHAT MAKES THIS THE RIGHT TEST rather than a regression test for that bug: it
does not check the argument, it checks that the page comes out. A test written
against the mistake would pass while some other page broke the same way.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from marshall.core import route as R

# One page per tab a pilot can turn to. Named here rather than discovered, so
# DELETING a page is a decision somebody makes on purpose and not something a
# refactor does quietly.
PAGES = ("brief", "routemap", "comms", "navlog", "plans", "e6b")


class TestEveryPageRenders(unittest.TestCase):

    def test_the_site_builds_at_all(self):
        """The one that was failing, and the cheapest thing that would have
        caught it."""
        from marshall.kneeboard import site
        out = site.build()
        self.assertTrue(out, "the kneeboard is empty")
        self.assertGreater(len(out), 10_000,
                           "a kneeboard that short is a stack trace")

    def test_each_page_on_its_own(self):
        """So a failure names the page rather than the whole site."""
        import importlib
        for page in PAGES:
            with self.subTest(page):
                mod = importlib.import_module(f"marshall.kneeboard.{page}")
                build = getattr(mod, "build", None)
                self.assertIsNotNone(build, f"{page} has no build()")
                out = build()
                self.assertTrue(out and str(out).strip(), f"{page} is blank")

    def test_the_plate_renders_for_the_procedure_that_has_one(self):
        from marshall.kneeboard import asr_plate
        self.assertIn("BATUMI", asr_plate.build())


class TestAFrequencyIsSpokenInFull(unittest.TestCase):
    """A clearance names a channel a pilot can actually tune.

    `director/tools/plans.py` rendered the departure frequency with
    `f"{freq:.1f}"`, so the IFR clearance -- the FIRST exchange of the sortie,
    the one he writes on his knee -- said:

        124.425  ->  "one two four decimal four"      Approach is on .425
        118.125  ->  "one one eight decimal one"      Tower is on .125
        132.55   ->  "one three two decimal six"      not even the same number

    `core.say.spell_freq` is the one renderer for this and `frequencies.py`, one
    module over in the same package, already called it. Two spellings of one
    number is how they come to disagree.
    """

    def test_spell_freq_keeps_every_digit(self):
        from marshall.core.say import spell_freq
        self.assertIn("four two five", spell_freq(124.425))
        self.assertIn("one two five", spell_freq(118.125))
        self.assertIn("five five", spell_freq(132.55))

    def test_no_frequency_is_rendered_to_one_decimal(self):
        """A grep, because the defect is a FORMAT and the wrong answer is a
        plausible frequency. Nothing downstream can tell 124.4 from 124.425."""
        root = Path(__file__).resolve().parent.parent
        bad = []
        for path in list((root / "src").rglob("*.py")) + \
                list((root / "director" / "tools").rglob("*.py")):
            # `core/say.py` DEFINES both renderers and quotes the defect in
            # prose as the example. Stripping `#` does not strip a docstring,
            # and the module that fixes a thing is allowed to name it.
            if path.name == "say.py":
                continue
            for i, line in enumerate(path.read_text().splitlines(), 1):
                code = line.split("#", 1)[0]
                if re.search(r"(freq|mhz|hz)\w*[^\n]{0,20}:\.1f", code, re.I):
                    bad.append(f"{path.relative_to(root)}:{i}")
        self.assertEqual(bad, [],
                         "a frequency rendered to one decimal place. Use "
                         "core.say.spell_freq -- .425 and .125 are real "
                         "channels and rounding them loses a real station.")


class TestThePagesAskTheAerodromeTheyMean(unittest.TestCase):
    """Each page is drawn for ONE procedure at ONE field, and says which."""

    def test_the_comms_card_names_a_field(self):
        from marshall.kneeboard import comms
        out = comms.build(profile=R.BATUMI_ILS)
        self.assertTrue(out.strip())
        self.assertIn("Batumi", out)


if __name__ == "__main__":
    unittest.main()
