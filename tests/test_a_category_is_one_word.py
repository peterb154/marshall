"""Every aeroplane was `is_aircraft: false`, and it cost one capital letter. [#156]

Measured live on a ghost `marshall-atc` was working: `category: "Airplane"`,
`is_aircraft: false`, `derived: ""`, `state: ""`. The untracked panel filters on
`is_aircraft` -- it exists to show A MANNED AEROPLANE RADAR CAN SEE THAT NOBODY
IS WORKING, which is [ID-5]'s invisible failure: a pilot who is talking, whose
identity never closed, so every call is answered and nothing is ever sequenced.
It could never show one.

WHERE THE FAULT ACTUALLY IS, because the issue names a different layer. It reads
`agent_atc._contact`'s

    "is_aircraft": not u.category,

as "the feed says `airplane`, which is truthy, so every aeroplane is false".
`_contact` never sees the feed's word. `identity.units_on` has already turned it
into `Unit.category`, which means *the category IF IT IS NOT AN AEROPLANE'S* --
six readers in `agent_atc` are written on that contract and `not u.category` is
correct under it. The comparison that produces it was the case-sensitive one:

    "" if c.get("category") in ("airplane", "helicopter") else ...

`tracks.category` has two writers. `feed.tracks._upsert` writes `airplane` out of
`_CATEGORY`; `tools/ghost_flight.py` painted the literal `Airplane`. One capital,
and a ghost stopped being an aeroplane in five places at once -- `is_aircraft`,
`derived`, `state`, the amber `level`, and `count_contacts`, which returned nought
so the separation engine never engaged for him at all.

So the vocabulary got one home (`feed/categories.py`), the five copies of it ask
that home, and the fixture writes the word the feed writes. Reproduced first,
against the two spellings the two writers actually put in the column: the real
feed's `airplane` was already correct, which is why this survived every sortie
and only ever bit a rehearsal.
"""

import re
import unittest
from pathlib import Path

from marshall.atc import identity, picture
from marshall.atc.agent_atc import Scope, _contact, count_contacts
from marshall.feed import categories as cat

ROOT = Path(__file__).resolve().parents[1]


def contact(category, **kw):
    """Exactly the dict `feed.tracks.contacts()` builds, with one word varied."""
    d = {"name": "Viper 1-1", "label": "362nd_sockeye", "type": "F-16C_50",
         "category": category, "manned": True, "player": "362nd_sockeye",
         "on_ground": False, "lat": 41.6, "lon": 41.6, "alt_ft": 8000.0,
         "heading": 130.0, "speed_kt": 300.0, "coalition": 2,
         "callsign": "", "formation": ""}
    d.update(kw)
    return d


def published(category, **kw):
    """One contact, all the way through to what the page is handed."""
    c = contact(category, **kw)
    sc = Scope("", contacts=[c], origin=(41.6, 41.6))
    return _contact(identity.units_on(sc)[0], sc, set())


class TestTheWordTheSimUses(unittest.TestCase):
    def test_the_sims_own_word_for_an_aeroplane_flies(self):
        # Acceptance 3: the word `_CATEGORY` maps GROUP_CATEGORY_AIRPLANE to.
        self.assertTrue(cat.is_aircraft(cat.AIRPLANE))
        self.assertTrue(cat.is_aircraft(cat.HELICOPTER))

    def test_the_capital_that_cost_the_issue(self):
        self.assertTrue(cat.is_aircraft("Airplane"))
        self.assertTrue(cat.is_aircraft("  AIRPLANE "))

    def test_armour_and_shipping_do_not_fly(self):
        self.assertFalse(cat.is_aircraft(cat.GROUND))
        self.assertFalse(cat.is_aircraft(cat.SHIP))
        self.assertFalse(cat.is_aircraft("Ground"))

    def test_a_word_nobody_knows_is_not_promoted_to_traffic(self):
        """Audit #45 is the expensive direction: four T-55s parked seventy
        miles away switched the separation engine on for a lone pilot. An
        unrecognised word is not made to fly."""
        self.assertFalse(cat.is_aircraft("structure"))

    def test_an_absent_category_is_read_generously_and_only_here(self):
        """`feed/dcs.py`, the older live scan, stamps `""` on everything because
        it asks an API that does not carry the group category. "I was not told"
        is not "it is a tank", and the mistake that way round DELETES a real
        aeroplane from the board."""
        self.assertTrue(cat.is_aircraft(""))
        self.assertTrue(cat.is_aircraft(None))


class TestWhatReachesThePage(unittest.TestCase):
    """Acceptance 1 and 2, through the real chain: the `contacts()` row shape,
    `units_on`, and `_contact`."""

    def test_an_aeroplane_is_an_aeroplane_however_it_was_spelled(self):
        for spelling in (cat.AIRPLANE, "Airplane", "AIRPLANE"):
            with self.subTest(spelling=spelling):
                self.assertTrue(published(spelling)["is_aircraft"])

    def test_and_carries_its_derived_callsign_and_its_state(self):
        got = published("Airplane")
        self.assertEqual(got["derived"], "Sockeye")
        self.assertTrue(got["state"])

    def test_a_manned_aeroplane_nobody_is_working_goes_amber(self):
        """The untracked panel's whole purpose. `level` was "" for a ghost."""
        self.assertEqual(published("Airplane")["level"], "warn")

    def test_armour_is_still_not_an_aircraft(self):
        for spelling in (cat.GROUND, "Ground", cat.SHIP):
            with self.subTest(spelling=spelling):
                got = published(spelling, type="T-55")
                self.assertFalse(got["is_aircraft"])
                self.assertEqual(got["derived"], "")
                self.assertEqual(got["level"], "")

    def test_the_separation_engine_still_counts_him(self):
        """`count_contacts` reads the same `Unit.category`. A ghost counted 0,
        so nothing was ever sequenced against him."""
        sc = Scope("", contacts=[contact("Airplane")], origin=(41.6, 41.6))
        self.assertEqual(count_contacts(sc), 1)

    def test_and_still_does_not_count_a_tank(self):
        sc = Scope("", contacts=[contact("Ground", type="T-55")],
                   origin=(41.6, 41.6))
        self.assertEqual(count_contacts(sc), 0)


class TestThePictureSaysWhatItIs(unittest.TestCase):
    """`picture` prints the category in the parenthetical for anything that is
    not an aeroplane, and printed ", Airplane" beside every ghost."""

    def test_an_aeroplane_gets_no_category_marker(self):
        self.assertNotIn("irplane", picture._marks(contact("Airplane")))

    def test_a_tank_still_says_so(self):
        self.assertIn("ground", picture._marks(contact("Ground", type="T-55")))


class TestOneVocabularyInTheTree(unittest.TestCase):
    """The five copies are what made this findable only by flying. A sixth
    written tomorrow would be case-sensitive again."""

    READERS = ("src/marshall/atc/identity.py", "src/marshall/atc/picture.py",
               "src/marshall/feed/tracks.py")

    def test_nobody_spells_the_vocabulary_out_again(self):
        pattern = re.compile(r'["\'](?:airplane|helicopter)["\']', re.I)
        for rel in self.READERS:
            with self.subTest(rel=rel):
                src = (ROOT / rel).read_text(encoding="utf-8")
                code = "\n".join(ln for ln in src.splitlines()
                                 if not ln.lstrip().startswith("#"))
                # The definitions in `categories.py` are the one place allowed.
                self.assertIsNone(pattern.search(code),
                                  f"{rel} names a category word directly; ask "
                                  f"marshall.feed.categories instead")

    def test_the_fixture_paints_the_word_the_feed_writes(self):
        """`ghost_flight.paint` is the other writer of `tracks.category`, and a
        rehearsal is only evidence while it paints what the sim would."""
        src = (ROOT / "tools" / "ghost_flight.py").read_text(encoding="utf-8")
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith("#"))
        self.assertNotIn("'Airplane'", code)
        self.assertNotIn('"Airplane"', code)
        self.assertIn("cat.AIRPLANE", code)

    def test_the_streamer_builds_its_map_from_the_same_words(self):
        """`_CATEGORY` is what puts the word in the column. Read as source --
        `feed/tracks.py` imports grpc and the suite has no simulator."""
        src = (ROOT / "src" / "marshall" / "feed" / "tracks.py").read_text(
            encoding="utf-8")
        for name in ("_cat.AIRPLANE", "_cat.HELICOPTER", "_cat.GROUND",
                     "_cat.SHIP"):
            self.assertIn(name, src)


if __name__ == "__main__":
    unittest.main()
