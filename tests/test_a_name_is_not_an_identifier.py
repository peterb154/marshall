"""A callsign matches its row whatever the case; a GUID does not. [#210]

`board.find` compared every column with `=`. The identity ladder binds a row
as `sockeye`; the agent asks for `Sockeye`, because that is how a controller
says a name. So every clearance tool -- all of which go through one flight
lookup -- answered as though the aeroplane did not exist, and printed the row
it had just failed to match in the sentence denying it:

    "Sockeye IS NOT ON THE BOARD ... On the board: sockeye."

A pilot then spent twenty minutes on the ramp: Clearance could not clear him
and told him he already was, Ground read the record and refused taxi.

The distinction, which is the fix: `srs_guid` and `track_name` are the sim's
own strings and must match EXACTLY -- binding the wrong aeroplane on a loose
comparison is a separation fault. `callsign` and `srs_name` are names.
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

SRC = (ROOT / "src" / "marshall" / "atc" / "board.py").read_text(encoding="utf-8")


class ANameIsNotAnIdentifier(unittest.TestCase):

    def _where_clause(self) -> str:
        """The line `find` builds its comparison from."""
        m = re.search(r"where = \((.*?)\)\n", SRC, re.S)
        self.assertIsNotNone(m, "find no longer builds a `where` expression")
        return m.group(1)

    def test_names_are_matched_without_regard_to_case(self):
        w = self._where_clause()
        self.assertIn("lower(", w,
                      "a name written 'sockeye' must match a name said 'Sockeye'")

    def test_the_sims_own_identifiers_stay_exact(self):
        """Loose matching on a GUID binds the wrong aeroplane, which is a
        separation fault and worse than the bug being fixed."""
        m = re.search(r"_EXACT = \((.*?)\)", SRC, re.S)
        self.assertIsNotNone(m, "the exact-match set is gone")
        exact = m.group(1)
        self.assertIn("srs_guid", exact)
        self.assertIn("track_name", exact)

    def test_the_exact_set_is_named_not_inverted(self):
        """Stated positively, for the reason `AIRBORNE_ONLY` is: a column
        nobody classifies must fail SAFE. A new identifier left out of an
        exclusion list would silently start matching loosely."""
        self.assertNotIn("_LOOSE = (", SRC,
                         "list what must be exact, not what may be loose")


if __name__ == "__main__":
    unittest.main()
