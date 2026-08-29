"""A pilot says "one three". He never says "13". [#177]

`match_spoken` narrowed on the runway with `\\b(\\d{1,2})\\b` -- a search for
DIGITS in a transcript of speech. So "the ILS one three", which is how every
runway is said on every frequency, parsed as naming no runway at all. With
nothing to narrow on, it matched every ILS published and came back ambiguous:

    match_spoken('ILS runway one three', field='')  ->  None, 2 candidates

Masked at a field with one ILS, which is why it survived. The question only has
to be asked where two exist, or where no field narrows it -- and a controller
who cannot resolve the approach assigns none, which is how an ILS arrival ends
up not being a vectored aircraft at all.

THE PAIR IS THE RUNWAY. "one three" is 13, not 1 and 3, because a runway is
spoken digit by digit and the run of digits together names it.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from marshall.core.approach import match_spoken  # noqa: E402


def _kind(p):
    return f"{getattr(p, 'kind', None)}-{getattr(p, 'runway', None)}" if p else None


class ARunwayIsSpokenNotTyped(unittest.TestCase):

    def setUp(self):
        from marshall.atc.controller import _published_now
        self.pub = _published_now()
        if len(self.pub) < 2:
            self.skipTest("this map publishes fewer than two approaches")

    def test_spelled_digits_name_a_runway(self):
        got = match_spoken("ILS runway one three", self.pub, field="")[0]
        self.assertEqual(_kind(got), "ils-13")

    def test_and_so_do_typed_ones(self):
        """The written form must not regress while fixing the spoken one."""
        got = match_spoken("ILS runway 13", self.pub, field="")[0]
        self.assertEqual(_kind(got), "ils-13")

    def test_the_pair_is_the_runway_not_two_digits(self):
        """"one three" is 13. Folded as 1 and 3 it matches nothing."""
        got = match_spoken("the ILS one three", self.pub, field="")[0]
        self.assertEqual(_kind(got), "ils-13")

    def test_a_kind_spoken_with_a_runway_still_narrows(self):
        got = match_spoken("radar approach one three", self.pub, field="")[0]
        self.assertEqual(_kind(got), "asr-13")

    def test_an_ambiguous_request_still_asks(self):
        """Widening what is understood must not start guessing. "the ILS" at a
        map with two is exactly the case that must come back as a question."""
        got, cands = match_spoken("the ILS", self.pub, field="")
        self.assertIsNone(got)
        self.assertGreater(len(cands), 1)


if __name__ == "__main__":
    unittest.main()
