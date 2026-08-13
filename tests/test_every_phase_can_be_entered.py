"""A phase nothing can put an aeroplane in is a phase that does not exist.

`enroute` was declared, owned by Center, and named as a legal successor by four
other phases -- and `_wanted` never returned it. Swept from `departure` the
reachable set was `{arrival, departure}`, so an aeroplane crossed the theatre
with the board saying `departure` the entire way.

It took the task half with it. `tasked` and `on_station` follow ONLY from
`enroute`, so a strike, a CAS check-in and a tanker join were unreachable by
construction, however they read on the page.

WHY IT SURVIVED #63, which fixed every other phase: handoffs key on the
controller's ROLE, not on the phase. So the ladder ran correctly -- Center took
him at twenty-five miles and gave him up again -- while the phase beside it was
wrong. Nothing downstream of the phase was broken, so nothing complained. That
is also the shape of the general test below: a value that is only ever READ by
something that does not depend on it is a value nobody checks.

THE GENERAL FORM is the point of this file. A test that `enroute` is now
reachable would pass for ever while the next phase added went the same way. So
the sweep asks the question of EVERY phase in the table, and a new one that
nothing can enter fails here on the day it is added. [#168]
"""

from __future__ import annotations

import unittest

from marshall.atc import phases as P

# Everything `derive` can be handed. Small on purpose -- these are the facts a
# radar poll and the separation engine actually produce, not a fuzz space.
GROUND = (True, False, None)
SEPARATION = ("", "holding", "cleared", "missed", "landed")
WORKED_BY = ("", "clearance", "ground", "tower", "departure", "center",
             "approach", "overlord")

# Phases no FACT can produce, because what enters them is a THING SAID. They are
# named here rather than skipped silently, so the list is a claim somebody can
# argue with -- and so a phase that quietly stops being derivable has to be
# added here on purpose.
#
#   taxi / holding_short   the ground rungs. "Clearance, taxi and holding short
#                          are the same range, the same direction and the same
#                          zero knots" -- radar cannot tell them apart and must
#                          not pretend to. `_wanted` says exactly this.
#   taxi_in                entered by `report_down` off the radar poll, and by a
#                          taxi request. Not by `derive`.
#   tasked / on_station    an overlord TASKS him; there is no geometry for it.
#                          Reachable in principle now that `enroute` is, and
#                          still without a trigger -- see the test below.
#   rtb                     a stated INTENTION -- "RTB Kobuleti". Deriving it
#                          from a turn towards home would be guessing at intent,
#                          which is the thing this deriver refuses to do.
#                          `controller.py` sets it when he says so.
#   unknown                "Heard on the radio and nothing more. Ask his
#                          intentions; never assume them" -- its own note. Set
#                          where a man is audible and unadmitted.
#   filed                  "A plan exists and there is no aeroplane yet. Nobody
#                          works him." `derive` runs for an aeroplane on radar,
#                          so it can never produce a phase whose definition is
#                          that there is no aeroplane. In `NOT_YET` with "" and
#                          `unknown`.
SAID_NOT_SEEN = {"taxi", "holding_short", "taxi_in", "tasked", "on_station",
                 "rtb", "unknown", "filed"}


def reachable() -> set[str]:
    """Every phase something can put an aeroplane INTO, over every input.

    ONLY TRANSITIONS COUNT. `derive` returns `current` unchanged when no fact
    argues otherwise, so counting that would make every declared phase
    "reachable" from itself and this whole file vacuous -- it would have passed
    on `enroute` the day before the fix, which is the exact thing it exists to
    catch. A phase is entered when the deriver moves an aeroplane into it from
    somewhere else.
    """
    out = set()
    for current in ["", *P.PHASES]:
        for on_ground in GROUND:
            for sep in SEPARATION:
                for was in (True, False):
                    for who in WORKED_BY:
                        got = P.derive(current, on_ground=on_ground,
                                       separation=sep, was_airborne=was,
                                       worked_by=who)
                        if got and got != current:
                            out.add(got)
    return out


class TestNoPhaseIsUnreachable(unittest.TestCase):

    def test_every_declared_phase_can_be_entered(self):
        got = reachable() | SAID_NOT_SEEN
        missing = set(P.PHASES) - got
        self.assertEqual(missing, set(),
                         f"declared and unreachable: {sorted(missing)}. Either "
                         "something must derive it, or it is entered by a "
                         "transition and belongs in SAID_NOT_SEEN with the "
                         "reason.")

    def test_enroute_in_particular(self):
        """The one that was missing, asserted directly as well as by the sweep,
        so a failure names it rather than a set difference."""
        self.assertIn("enroute", reachable())

    def test_and_it_is_being_worked_by_center_that_does_it(self):
        """Being handed to Center is what "he is enroute" MEANS -- the same
        argument the arrival rule makes about Approach one line above."""
        got = P.derive("departure", on_ground=False, was_airborne=True,
                       worked_by="center")
        self.assertEqual(got, "enroute")

    def test_a_man_coming_home_is_not_sent_back_out(self):
        """Center owns `rtb` too, so the rule has to exclude it or a recovery
        is re-derived into the outbound leg every poll."""
        got = P.derive("rtb", on_ground=False, was_airborne=True,
                       worked_by="center")
        self.assertEqual(got, "rtb")

    def test_the_arrival_rule_still_wins_from_enroute(self):
        """Unchanged, and the reason the two rules are ordered this way."""
        got = P.derive("enroute", on_ground=False, was_airborne=True,
                       worked_by="approach")
        self.assertEqual(got, "arrival")


class TestTheTaskHalfIsReachableInPrincipleAndHasNoTrigger(unittest.TestCase):
    """Honest about what is still missing, rather than implying a fix.

    `tasked` and `on_station` follow from `enroute` and nothing else, so making
    `enroute` reachable is the PREREQUISITE for them and not the whole of it.
    An overlord has to task him, and there is no seat doing that today.
    """

    def test_they_follow_from_enroute_and_from_nothing_else(self):
        for name in ("tasked", "on_station"):
            with self.subTest(name):
                froms = {n for n, p in P.PHASES.items()
                         if name in (p.follows or ())}
                self.assertTrue(froms, f"{name} follows nothing at all")
                self.assertLessEqual(froms, {"enroute", "tasked", "on_station",
                                             "rtb"},
                                     f"{name} is entered from {sorted(froms)}")

    def test_and_nothing_derives_them_yet(self):
        """If this ever fails, somebody built the trigger -- delete this test
        and take them out of SAID_NOT_SEEN."""
        self.assertFalse({"tasked", "on_station"} & reachable())


if __name__ == "__main__":
    unittest.main()
