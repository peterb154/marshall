"""Who has him next is answered three ways, and they must not contradict.

`next_controller` asks in order:

    1. the sim's EVENTS      `handoff_on_the_event` -- he got airborne, he
                             touched down
    2. the RULE TABLE        `handoff.due` -- ranges and directions, and the
                             ground phases by ownership
    3. the AIRSPACE VOLUMES  `leaving_my_airspace` -- PostGIS, when neither of
                             the above has an opinion

CLAUDE.md says this was three separate mechanisms until 1 August and they
disagreed, and that a pilot found it at 44 nm by declaring an emergency. They
are one function now. They are still three answers.

#189 gave the rule table the last word over the airspace: a rule that says NOT
YET is a decision, and `due` returning None for both "not yet" and "no opinion"
let geometry answer over the top of procedure.

THAT FIXED THE WRONG ONE FIRST. The events branch runs before both, and it
carried an assumption from the day it was written for go-arounds:

    "Getting airborne ends Tower's business."

which is true of an aeroplane that has just flown an approach, and false of one
that has just taken off, and false of one still rolling after landing. All
three are "airborne, with Tower", and only the PHASE tells them apart:

    departure   he has not flown an approach yet -- Tower keeps him to
                DEPARTURE_NM, which is what the card says and what a pilot
                expects. Twice observed handing over at rotation:
                "he sent me to departure before I even hit the end of the
                runway"
    landed /    he has finished one. Fifteen seconds after touchdown, still
    taxi_in     reading as airborne to radar, Tower offered him to Approach
    missed      he really is going around, and this branch is his

AND THE AIRSPACE MAY NOT TAKE A MAN OFF AN APPROACH. `under_our_vectors`
guarded that, and it is only true while a vector is in flight -- so an
aeroplane established and flying the ILS himself fell through and was offered
to Center mid-approach. Being CLEARED for an approach is the durable version of
the same fact.  [#200]
"""

from __future__ import annotations

import inspect
import unittest

from marshall.atc import agent_atc as A


class ADepartureIsNotAGoAround(unittest.TestCase):
    """Asserted on the source, because reaching the branch needs a live radar
    scope with a unit in it. What must be true is structural: the phase is
    consulted before Tower gives up a man who is airborne."""

    def setUp(self):
        self.src = inspect.getsource(A.handoff_on_the_event)

    def test_the_branch_knows_what_he_is_doing(self):
        self.assertIn("phase", inspect.signature(
            A.handoff_on_the_event).parameters,
            "the events branch cannot tell a departure from a go-around")

    def test_a_departure_is_left_with_tower(self):
        at = self.src.index('in_air is True and role == "tower"')
        self.assertIn("departure", self.src[at:],
                      "airborne with Tower hands a DEPARTURE away, at "
                      "rotation, before the rule table gets a word")

    def test_and_so_is_a_roll_out(self):
        at = self.src.index('in_air is True and role == "tower"')
        window = self.src[at:]
        for phase in ("landed", "taxi_in"):
            with self.subTest(phase):
                self.assertIn(phase, window)

    def test_the_caller_passes_it(self):
        src = inspect.getsource(A.next_controller)
        self.assertIn("phase=phase", src)


class TheAirspaceDoesNotTakeAManOffAnApproach(unittest.TestCase):

    def test_a_cleared_approach_stops_the_volume_deciding(self):
        src = inspect.getsource(A.leaving_my_airspace)
        at = src.index("under_our_vectors")
        window = src[at:]
        self.assertIn("profile is not None", window,
                      "only an in-flight vector stops the airspace handing "
                      "him away, so a man established on the ILS and flying "
                      "it himself is offered to Center")

    def test_and_it_is_HIS_procedure_not_the_bridge_s(self):
        """`profile` reaches `next_controller` as a PARAMETER, and the caller
        must fill it from the AIRCRAFT. The whole of #150 is that `ctl.profile`
        and `_pro(ac)` are different questions, and #162 removed the first."""
        src = inspect.getsource(A)
        sites = [i for i in range(len(src))
                 if src.startswith("next_controller(", i)
                 and not src.startswith("def next_controller(", max(0, i - 4))]
        self.assertTrue(sites, "nothing calls the cascade any more")
        for at in sites:
            with self.subTest(line=src[:at].count("\n") + 1):
                near = src[max(0, at - 500):at + 200]
                self.assertIn("_pro", near,
                              "the handoff cascade is handed a procedure that "
                              "did not come from the AIRCRAFT -- `ctl.profile` "
                              "and `_pro(ac)` are different questions (#150), "
                              "and #162 removed the first")


class TheOrderIsStillTheOrder(unittest.TestCase):
    """The three are asked in a fixed sequence and each may only speak when
    the one before it had no opinion. Three answers is fine; three answers
    that disagree is what #51 was."""

    def test_events_then_rules_then_airspace(self):
        src = inspect.getsource(A.next_controller)
        ev = src.index("handoff_on_the_event")
        rules = src.index("_handoff.due")
        air = src.index("leaving_my_airspace")
        self.assertLess(ev, rules)
        self.assertLess(rules, air)

    def test_and_a_rule_that_ruled_still_wins_over_the_airspace(self):
        """#189, kept: `due` returning a keep-Verdict must stop the volumes
        being asked at all."""
        src = inspect.getsource(A.next_controller)
        at = src.index("leaving_my_airspace")
        self.assertIn("not ruled", src[max(0, at - 400):at])


if __name__ == "__main__":
    unittest.main()
