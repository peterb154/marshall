"""A reply newer than the mark is not evidence that he answered ME. [#204]

`say_it` decided the controller had spoken by looking for any `atc/` record
written since the byte offset it took before transmitting. That is true of a
reply to somebody else: one that misses its own turn's deadline is written
after the NEXT turn's mark, so the next turn sees it at once, stops waiting,
and reports its predecessor's answer as its own. Every turn after that is one
behind, and nothing in the output says so.

`stack_rehearsal.py` ran that way for three flights and reported four
separation violations against an engine that had never been asked the
question. The tell was in the transcript all along -- the reply to "Pony one
two" addressed "Pony one one" -- and it reads as the controller misnaming
somebody, which is a real bug we have had, so it did not look like a harness
fault.

The bridge writes a `pilot` record when it hears the transmission, so that
record is the boundary.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))

# The harness lives in `tools/`, not the package, so the path has to be
# set up first. Suppressed here rather than for all of `tests/*`: the
# blanket ignore is what stopped anybody looking at the last one.
from ladder_rehearsal import mine_only  # noqa: E402


class ReplyBelongsToItsOwnTurn(unittest.TestCase):

    def test_a_late_reply_from_the_previous_turn_is_not_mine(self):
        """The exact shape that cost three flights."""
        ev = [
            {"kind": "atc/pilot", "text": "Sockeye, Batumi Approach, radar contact"},
            {"kind": "pilot", "transcript": "Pony one two, checking in, inbound"},
            {"kind": "atc/pilot", "text": "Bandit, Batumi Approach, radar contact"},
        ]
        mine = mine_only(ev)
        said = " ".join(e.get("text", "") for e in mine)
        self.assertNotIn("Sockeye", said,
                         "the previous turn's reply was attributed to this one")
        self.assertIn("Bandit", said, "this turn's own reply was dropped")

    def test_the_pilot_record_is_kept(self):
        """`arrived_intact` reads its transcript to judge whether I was heard."""
        ev = [{"kind": "pilot", "transcript": "checking in"},
              {"kind": "atc/pilot", "text": "go ahead"}]
        self.assertEqual(mine_only(ev)[0].get("kind"), "pilot")

    def test_nothing_heard_yet_is_nothing_not_whatever_is_lying_there(self):
        """No `pilot` record means the bridge has not heard us.

        Returning the stale reply here is what let a turn pass on somebody
        else's answer. The honest answer is empty, which `arrived_intact`
        reports as "nothing reached the bridge at all" -- a SKIP, not a pass.
        """
        ev = [{"kind": "atc/pilot", "text": "Sockeye, radar contact"},
              {"kind": "board", "board": []}]
        self.assertEqual(mine_only(ev), [])

    def test_an_ordinary_turn_is_unchanged(self):
        """The fix must not trim a turn that was already correct."""
        ev = [{"kind": "pilot", "transcript": "checking in"},
              {"kind": "board", "board": []},
              {"kind": "atc/pilot", "text": "go ahead"},
              {"kind": "atc/handoff", "text": "contact Tower"}]
        self.assertEqual(mine_only(ev), ev)


if __name__ == "__main__":
    unittest.main()
