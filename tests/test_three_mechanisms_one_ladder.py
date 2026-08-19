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


class AirborneWithTowerIsTheTablesQuestion(unittest.TestCase):
    """The events branch does not decide it at all any more.

    The first fix taught the branch the phase, so it could tell a departure
    from a roll-out from a go-around. That was still three mechanisms
    answering one question:

        "I don't see why the handoff to departure is any different on a go
         around. Still use the 5nm airspace rule right?"

    It is not different. Both are an aeroplane climbing away from the runway,
    both at the same range; only the destination differs, and a table row says
    that in one line. So the branch answers only what the table CANNOT -- an
    airborne aeroplane with no radar picture at all, where there is no range to
    ask about and a blind controller would otherwise never let anybody go.
    """

    def setUp(self):
        self.src = inspect.getsource(A.handoff_on_the_event)

    def test_with_radar_the_branch_says_nothing(self):
        at = self.src.index('in_air is True and role == "tower"')
        self.assertIn("fix is None", self.src[at:],
                      "the events branch still decides an airborne handoff "
                      "when there is a picture to measure instead")

    def test_and_without_radar_it_still_answers(self):
        """A guard that needs a picture must not disarm a controller who has
        none -- `test_the_ladder_has_a_direction` has held that since #138."""
        self.assertIn("station_for(\"approach\"", self.src)

    def test_the_go_around_is_a_rule_and_not_a_special_case(self):
        from marshall.atc import handoff as H
        rows = [(r.frm, r.to, r.when) for r in H.RULES]
        self.assertIn(("tower", "approach", "going_around_beyond"), rows)

    def test_at_the_same_range_as_a_departure(self):
        from marshall.atc import handoff as H
        go = next(r for r in H.RULES if r.when == "going_around_beyond")
        dep = next(r for r in H.RULES
                   if r.frm == "tower" and r.to == "departure")
        self.assertEqual(go.nm, dep.nm)
        self.assertEqual(go.nm, H.DEPARTURE_NM)

    def test_and_it_is_asked_first_because_it_is_the_specific_one(self):
        from marshall.atc import handoff as H
        order = [r.when for r in H.RULES if r.frm == "tower"]
        self.assertLess(order.index("going_around_beyond"),
                        order.index("outbound_beyond"))


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
