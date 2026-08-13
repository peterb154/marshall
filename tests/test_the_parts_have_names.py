"""The vocabulary exists, and the four documents that point at it still land.

    "i'm having a hard time validating the work you are doing and at what
     layer when it's all lumped into 'bridge' and 'director' -- which are
     legacy names."                                          -- #147 [ARCH-26]

`docs/STRUCTURE.md` → *What to call the parts* is the canonical table: each
part, what it does, and its `LAYERS.md` layer. `CLAUDE.md`, `START_HERE.md`,
`LAYERS.md`, `WIRING.md` and `README.md` all point at it rather than each
keeping a copy, because five copies of a vocabulary is four chances to
disagree about what a part is called.

WHAT THIS GUARDS is the failure `tools/docs_check.py` cannot see. It checks
that a relative link resolves to a FILE; nothing checks the `#anchor`. Rename
the heading and five documents go on linking to a section that is not there,
each landing at the top of a 600-line proposal, and the reader concludes the
vocabulary was never written down -- which is the exact complaint this issue
opened with.
"""

from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
STRUCTURE = ROOT / "docs" / "STRUCTURE.md"

# The agreed names. A part that is not in the table cannot be reviewed at a
# layer, which is the whole point of having one.
PARTS = ("marshall-radio", "marshall-atc", "marshall-feed", "marshall-kneeboard")

POINTERS = ("CLAUDE.md", "README.md", "docs/START_HERE.md", "docs/LAYERS.md",
            "docs/WIRING.md")


def _anchors(text: str) -> set[str]:
    """GitHub's slug: lowercase, punctuation dropped, spaces to hyphens."""
    out = set()
    for line in text.splitlines():
        if not line.startswith("#"):
            continue
        title = line.lstrip("#").strip()
        slug = re.sub(r"[^\w\s-]", "", title.lower()).replace(" ", "-")
        out.add(slug)
    return out


class TheTableIsThere(unittest.TestCase):

    def setUp(self):
        self.text = STRUCTURE.read_text(encoding="utf-8")

    def test_the_section_exists(self):
        self.assertIn("what-to-call-the-parts", _anchors(self.text))

    def test_every_part_is_named_in_it(self):
        section = self.text.split("## What to call the parts", 1)[-1]
        section = section.split("\n## ", 1)[0]
        for part in PARTS:
            with self.subTest(part):
                self.assertIn(part, section)

    def test_the_deprecated_words_are_marked_as_directory_names(self):
        section = self.text.split("## What to call the parts", 1)[-1]
        section = section.split("\n## ", 1)[0]
        self.assertIn("DIRECTORY names", section)
        self.assertIn("deprecated", section)

    def test_the_pin_is_stated_where_somebody_is_tempted(self):
        """The folder rename is the step after this one, and the volume is why
        it is dangerous. Saying so in the vocabulary section is not padding --
        it is where a reader arrives having just decided the names are wrong."""
        section = self.text.split("## What to call the parts", 1)[-1]
        section = section.split("\n## ", 1)[0]
        self.assertIn("marshall-director_pgdata", section)


class EveryPointerLands(unittest.TestCase):

    def test_the_anchor_resolves_from_every_document_that_links_it(self):
        have = _anchors(STRUCTURE.read_text(encoding="utf-8"))
        seen = []
        bad = []
        for rel in POINTERS:
            text = (ROOT / rel).read_text(encoding="utf-8")
            for anchor in re.findall(r"STRUCTURE\.md#([\w-]+)", text):
                seen.append(rel)
                if anchor not in have:
                    bad.append(f"{rel} links to STRUCTURE.md#{anchor}")
        self.assertEqual(bad, [], "\n".join(
            ["a link into the vocabulary lands nowhere; docs_check only "
             "verifies the FILE:", *bad]))
        self.assertTrue(seen, "nothing points at the vocabulary any more")


if __name__ == "__main__":
    unittest.main()
