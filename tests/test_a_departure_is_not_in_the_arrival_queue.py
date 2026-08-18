"""Nobody is in the letdown before he has taken off.

    "sitting on the ground here, getting ready to taxi, I look at the board,
     the arrival cue says, check in with the arrival cue"

    "the board says, arrival queue is checked in with the arrival controller.
     His place in the let down and nothing else. My issue with this is that I
     obviously have not checked in with the arrival controller yet. What is
     this status actually?"

He was right, and the board was faithfully reporting what the engine held.
`phase` was `ENROUTE` on every board snapshot of the sortie -- all eighteen of
them, from his first word on a cold ramp to thirteen miles out:

    15:12:51   phase ENROUTE   sortie_phase clearance      (cold, on the ramp)
    15:16:34   phase ENROUTE   sortie_phase taxi
    15:20:01   phase ENROUTE   sortie_phase holding_short
    15:20:14   phase ENROUTE   sortie_phase departure

It never changed, because there was nothing left for it to change to.

ONE LINE IN `check_in`, guarded against the wrong end of the sortie. It refused
to demote a CLEARED or a LANDED aeroplane -- both learned from #51, where a
check-in on a new frequency knocked a man out of the letdown he was already in
-- and said nothing about a man who has not started his engine. The FIRST
transmission of any sortie is a check-in, so every aeroplane joined the arrival
queue before it moved.

`UNKNOWN` MEANS "NEVER ADMITTED" and no departure could ever be shown it. #171
published exactly those words in the legend so the page could tell a real
answer from a missing one, and this line overwrote the answer on his first
word.

WHAT THIS IS NOT. It is not a separation bug, and saying so precisely matters
more than the fix. Every reader of the field pairs `UNKNOWN` with `ENROUTE` --
stack admission in `report_beacon` and `_try_clear`, the channel choice in
`_channel` -- so nobody was sequenced differently and no aeroplane took a slot
it should not have. What was wrong is that the board asserted a fact about a
man that was not true of him, on the one screen whose whole job is telling
those two apart.

THE EVIDENCE IS #178's LATCH. `has_been_airborne` is set only on positive
radar, which is #164's scar -- `not on_ground` is not `airborne` -- and it
survives a restart in `flights`. An aeroplane radar has not yet placed stays
UNKNOWN, which is honest and, since the two read identically, costs nothing.
[#184]
"""

from __future__ import annotations

import unittest

from marshall.atc import controller as atc

import tests.theatre as T


class AManOnTheRampIsNotInTheArrivalQueue(unittest.TestCase):

    def setUp(self):
        self.ctl = atc.Controller(T.the_arrival())
        self.ctl._me = T.station("clearance", field="Kobuleti")

    def test_his_first_word_does_not_admit_him(self):
        """The transmission that opened the sortie: "Kobuleti Clearance,
        sockeye, with whiskey"."""
        self.ctl.check_in("Sockeye")
        self.assertIs(self.ctl.get("Sockeye").phase, atc.Phase.UNKNOWN)

    def test_nor_do_the_next_six(self):
        """A pilot checks in on every frequency change and the ladder gives him
        six or seven. One of them being enough is what made this permanent."""
        for _ in range(7):
            self.ctl.check_in("Sockeye")
        self.assertIs(self.ctl.get("Sockeye").phase, atc.Phase.UNKNOWN)

    def test_the_whole_ground_ladder_leaves_him_out_of_it(self):
        """Every rung the pilot actually passed through, in order."""
        ac = self.ctl.get("Sockeye")
        for rung in ("clearance", "taxi", "holding_short", "departure"):
            with self.subTest(rung):
                ac.sortie_phase = rung
                self.ctl.check_in("Sockeye")
                self.assertIs(ac.phase, atc.Phase.UNKNOWN,
                              f"in the arrival queue while {rung}")


class ButAnAeroplaneThatHasFlownIsAdmitted(unittest.TestCase):
    """The other side of the line. `check_in` exists to do this."""

    def setUp(self):
        self.ctl = atc.Controller(T.the_arrival())

    def test_once_he_has_flown_a_check_in_admits_him(self):
        ac = self.ctl.get("Sockeye")
        ac.has_been_airborne = True
        self.ctl.check_in("Sockeye")
        self.assertIs(ac.phase, atc.Phase.ENROUTE)

    def test_and_the_latch_survives_the_ground(self):
        """He lands, taxis in, and says something. He HAS flown, so the
        question of admitting him is decided by the phase guards below and not
        by the latch -- which is why the latch is one-way."""
        ac = self.ctl.get("Sockeye")
        ac.has_been_airborne = True
        ac.phase = atc.Phase.LANDED
        self.ctl.check_in("Sockeye")
        self.assertIs(ac.phase, atc.Phase.LANDED)

    def test_a_cleared_aeroplane_is_still_not_demoted(self):
        """#51: a check-in on a new frequency knocked a man out of the letdown
        he was already in, and he held at 44 nm and declared an emergency. The
        new guard must not be read as replacing that one."""
        ac = self.ctl.get("Sockeye")
        ac.has_been_airborne = True
        ac.phase = atc.Phase.CLEARED
        self.ctl.check_in("Sockeye")
        self.assertIs(ac.phase, atc.Phase.CLEARED)


class AndItChangesNobodysSequence(unittest.TestCase):
    """The claim that this is a truth bug and not a separation one, asserted
    rather than asserted-in-a-comment.

    If some reader treated the two differently, this change would silently move
    an aeroplane in the queue -- which is the one thing an LLM may never do and
    the one thing a display fix must not do either.
    """

    def test_every_reader_pairs_unknown_with_enroute(self):
        import inspect
        import re
        src = inspect.getsource(atc)
        # every line that tests the field against ENROUTE
        for line in src.splitlines():
            if "Phase.ENROUTE" not in line or "=" in line.split("Phase")[0][-2:]:
                continue
            if re.search(r"\bin\b.*Phase\.ENROUTE", line) or "Phase.ENROUTE)" in line:
                with self.subTest(line.strip()[:70]):
                    self.assertIn(
                        "Phase.UNKNOWN", line,
                        "a reader treats ENROUTE differently from UNKNOWN, so "
                        "#184 is no longer only about what the board says")


if __name__ == "__main__":
    unittest.main()
