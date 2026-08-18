"""The pages that are still served, render. And a frequency keeps its digits.

There was no test for any of this. Not a weak one -- none -- and that is how
`site.build()` came to raise on both maps for an unknown length of time:

    >>> site.build()
    AttributeError: 'ApproachProfile' object has no attribute 'profile'

`comms.build` took `(card, profile)` and every other page took `(profile)`, so
the procedure was passed positionally into the CARD slot. OpenKneeboard renders
that as "No Pages" -- the pilot had nothing at all -- and the suite was green.

WHAT IS LEFT TO TEST, after the charts were removed:

    /flighttest   the test card and the issue numbers
    /diag         what the two brains believe, now
    /docs         the documents
    /file         the planner

The brief, route map, comms card, nav log, plans board, approach plate and E6B
are gone: a pilot gets his steerpoints, his frequencies and his plate from the
DTC in the aeroplane, and a second copy on a web page was one more thing that
could disagree with the jet.

WHAT MAKES THIS THE RIGHT TEST rather than a regression test for that bug: it
does not check the argument, it checks that the page comes out. A test written
against the mistake would pass while another page broke the same way.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


class TestTheServedPagesRender(unittest.TestCase):

    def test_the_flight_test_card_builds(self):
        """The one a pilot actually flies with, and the reason `site.build`
        survived the charts: it was always parameterised by its page list."""
        from marshall.kneeboard import flighttest, site
        out = site.build(flighttest.pages())
        self.assertTrue(out, "the flight test card is empty")
        self.assertGreater(len(out), 5_000,
                           "a card that short is a stack trace")

    def test_the_diagnostics_page_builds(self):
        from marshall.kneeboard import diag
        self.assertTrue(diag.page().strip(), "the diag board is blank")

    def test_the_documents_index_builds(self):
        from marshall.kneeboard import docs
        self.assertTrue(docs.index().strip(), "the documents index is blank")

    def test_every_slug_the_index_offers_actually_renders(self):
        """The index and the renderer must agree. A slug listed but unservable
        is a link a pilot taps to a stack trace -- the same shape as the tab
        that started this file, one layer down."""
        from marshall.kneeboard import docs
        slugs = re.findall(r'href="/docs/([a-z0-9-]+)"', docs.index())
        self.assertTrue(slugs, "the index offers no documents at all")
        for slug in slugs:
            with self.subTest(slug=slug):
                self.assertTrue(docs.render(slug).strip(), f"{slug} is blank")

    def test_the_planner_builds(self):
        from marshall.kneeboard import filing
        build = getattr(filing, "page", None) or getattr(filing, "build", None)
        self.assertIsNotNone(build, "filing has no entry point")
        self.assertTrue(str(build()).strip(), "the planner is blank")

    def test_the_renderer_refuses_to_guess(self):
        """`build()` used to default to the chart document. There is no default
        now -- a caller says what it wants rendered or gets a TypeError, which
        is the honest failure for a page list that does not exist."""
        from marshall.kneeboard import site
        with self.assertRaises(TypeError):
            site.build()


class TestAFrequencyKeepsItsDigits(unittest.TestCase):
    """A clearance names a channel a pilot can actually tune.

    `director/tools/plans.py` rendered the departure frequency with
    `f"{freq:.1f}"`, so the IFR clearance -- the FIRST exchange of the sortie,
    the one he writes on his knee -- said:

        124.425  ->  "one two four decimal four"      Approach is on .425
        118.125  ->  "one one eight decimal one"      Tower is on .125
        132.55   ->  "one three two decimal six"      not even the same number

    Eight more places did the same in writing, and the worst was not a page:
    `assembly.py` composes what the AGENT is told about itself -- "YOU ARE:
    Batumi Approach on 124.4". That is #23's shape with the right field and the
    wrong number.

    There was a renderer for a SPOKEN frequency and none for a WRITTEN one,
    which is why nine sites each independently invented the same rounding.
    """

    def test_spoken_keeps_every_digit(self):
        from marshall.core.say import spell_freq
        self.assertIn("four two five", spell_freq(124.425))
        self.assertIn("one two five", spell_freq(118.125))
        self.assertIn("five five", spell_freq(132.55))

    def test_written_keeps_every_digit_and_always_has_one(self):
        from marshall.core.say import freq_text
        self.assertEqual(freq_text(124.425), "124.425")
        self.assertEqual(freq_text(118.125), "118.125")
        self.assertEqual(freq_text(132.55), "132.55")
        self.assertEqual(freq_text(133.0), "133.0", "a bare 133 is not a freq")

    def test_no_frequency_is_rendered_to_one_decimal(self):
        """A grep, because the defect is a FORMAT and the wrong answer is a
        plausible frequency. Nothing downstream can tell 124.4 from 124.425."""
        root = Path(__file__).resolve().parent.parent
        bad = []
        for path in list((root / "src").rglob("*.py")) + \
                list((root / "services" / "tools").rglob("*.py")):
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
                         "core.say.freq_text in writing or spell_freq on the "
                         "air -- .425 and .125 are real channels and rounding "
                         "them loses a real station.")


if __name__ == "__main__":
    unittest.main()
