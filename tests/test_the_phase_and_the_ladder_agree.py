"""The controller a phase names and the controller the ladder gives him.

#168's third criterion, and the one that generalises. `enroute` was declared,
owned by Center, named as a legal successor by four other phases -- and nothing
could put an aeroplane in it. It survived #63, which fixed every other phase,
for a reason worth keeping in front of us:

    "handoffs key on the controller's ROLE, not on the phase. So the ladder ran
     correctly -- Center took him at twenty-five miles and gave him up again --
     while the phase beside it was wrong. Nothing downstream of the phase was
     broken, so nothing complained."

TWO MECHANISMS, ONE QUESTION. `phases.owner_of` says who works a man in this
phase; `handoff.due` decides who he is given to. They are consulted by different
code at different moments and nothing has ever asserted they agree, so either
can drift and the symptom is a board that disagrees with the radio -- which is
exactly what a pilot reports as "he's behind" or "the strip is wrong".

`tests/test_every_phase_can_be_entered.py` is the sibling: it asks whether every
phase can be REACHED. This asks whether, once reached, the phase and the ladder
name the same controller. [#168]
"""

from __future__ import annotations

import unittest

from marshall.atc import handoff as H
from marshall.atc import phases as P
from marshall.core import theatre as T
from tests import theatre as TH

# Phases nobody is HANDED to, and each is a deliberate absence rather than a
# gap. `unknown` and `filed` have no owner at all -- "heard on the radio and
# nothing more", "a plan exists and there is no aeroplane yet" -- so there is
# nobody for the ladder to name.
NO_OWNER = ("unknown", "filed")


def seats() -> set[str]:
    """Every role the loaded map staffs, including the hats a seat also wears.

    `Station.also` is not decoration: one controller answers as Departure and
    as Approach, and a role lookup that ignored it would call half the ladder
    unstaffed on a field that works perfectly.
    """
    got = set()
    for s in T.stations_now():
        got.add(s.role)
        got |= set(s.also or ())
    return got


class TestEveryPhaseOwnerIsSomebodyTheMapStaffs(unittest.TestCase):
    """A phase whose owner nobody staffs cannot hand over, silently.

    `due`'s phase-ownership branch resolves the owner through `station_for` and
    does nothing when it comes back None -- correctly, because inventing a
    controller is worse. But the aeroplane then stays with whoever has him
    while the board says he belongs to somebody else, and no error is raised
    anywhere.
    """

    def test_each_owner_resolves_to_a_seat(self):
        have = seats()
        for name in P.PHASES:
            owner = P.owner_of(name)
            if not owner:
                with self.subTest(name):
                    self.assertIn(name, NO_OWNER,
                                  f"{name} has no owner and is not one of the "
                                  f"phases documented as ownerless")
                continue
            with self.subTest(name):
                self.assertIn(owner, have,
                              f"phase {name!r} is owned by {owner!r}, which "
                              f"{TH.name()} staffs nobody for -- the "
                              f"phase-ownership handoff will do nothing and "
                              f"say nothing")

    def test_and_the_ownerless_ones_are_named_rather_than_counted(self):
        """So that a phase which quietly loses its owner has to be added here
        on purpose rather than joining a silent tally."""
        got = {n for n in P.PHASES if not P.owner_of(n)}
        self.assertEqual(got, set(NO_OWNER))


class TestEveryRoleTheLadderNamesIsAPhasesOwner(unittest.TestCase):
    """The mirror, and the half that catches the ladder drifting.

    If a rule hands a man to a role no phase accounts for, the frequency moves
    and the phase does not -- which is #168's shape exactly: the ladder running
    correctly beside a phase that is wrong.
    """

    def test_no_rule_hands_him_to_a_role_no_phase_owns(self):
        owners = {P.owner_of(n) for n in P.PHASES} - {""}
        for rule in H.RULES:
            with self.subTest(f"{rule.frm}->{rule.to}"):
                self.assertIn(rule.to, owners,
                              f"the ladder hands a man to {rule.to!r} and no "
                              f"phase is owned by it, so his strip cannot "
                              f"follow him")

    def test_and_every_rule_STARTS_from_a_seat_the_map_staffs(self):
        """`frm` is checked against the SEATS, not against the phase owners,
        and the difference is a real one this test found.

        `Rule("clearance", "tower", "airborne")` starts from `clearance`, and
        no phase is owned by that word: `phases.clearance.owner` is
        **"delivery"**. Two spellings of one seat, reconciled by `Station.also`
        carrying both -- so every lookup works and nothing was ever wrong.

        It is not harmless, and the sibling test below is the proof. The
        airborne guard in `due` asked `owner_of(phase) in _GROUND_SEATS`
        against a hand-written `("ground", "clearance")`, and "delivery" is in
        neither -- so an aeroplane at eight thousand feet in the clearance
        phase was handed to Ground. The vocabulary being split is what let a
        list drift under a comment promising it could not.
        """
        have = seats()
        for rule in H.RULES:
            with self.subTest(f"{rule.frm}->{rule.to}"):
                self.assertIn(rule.frm, have,
                              f"the ladder starts a rule from {rule.frm!r}, "
                              f"which {TH.name()} staffs nobody for")

    def test_the_two_spellings_of_the_delivery_seat_are_both_known(self):
        """Pinned rather than tidied, because tidying it is a rename across
        the phase table, the rule table and every theatre file -- and the
        thing that actually bit was a guard that knew one spelling. If a third
        appears, this fails."""
        have = seats()
        for word in ("clearance", "delivery"):
            with self.subTest(word):
                self.assertIn(word, have)
        self.assertEqual(P.owner_of("clearance"), "delivery")


class TestThePhaseOwnedTransitionsGiveHimToHisOwner(unittest.TestCase):
    """The direct claim: for a phase with no geometry, `due` names its owner.

    A phase that "aims at nothing" is owned outright -- moving into it IS the
    handoff, which is what `handoff.py` says about the ground rungs. So the two
    mechanisms are not merely consistent in the abstract; one is computed from
    the other, and this asserts it end to end rather than by reading.
    """

    def setUp(self):
        self.pro = TH.the_arrival()
        # From Approach, who owns none of the ground phases -- so every verdict
        # below is a real transition rather than "he is already with me".
        self.me = TH.station("approach", TH.arrival())

    def test_each_grounded_phase_hands_him_to_its_owner(self):
        for name, p in P.PHASES.items():
            if getattr(p, "aims_at", "") != "none":
                continue          # the airborne phases are the rules' business
            owner = P.owner_of(name)
            if not owner:
                continue
            st = H.State(on_ground=True, range_nm=0.2, inbound=False,
                         phase=name)
            got = H.due(self.pro, self.me, st)
            with self.subTest(name):
                self.assertIsNotNone(
                    got, f"nothing hands a man in {name!r} to {owner!r}")
                self.assertEqual(
                    got.role, owner,
                    f"phase {name!r} is owned by {owner!r} and the ladder "
                    f"gives him to {got.role!r}")

    def test_an_AIRBORNE_aeroplane_is_never_given_to_a_ground_seat(self):
        """The guard that has to be stated in both places or it is not an
        invariant. `taxi_in` aims at nothing, so phase-ownership alone would
        hand a flying aircraft to Ground on every poll."""
        for name in ("taxi", "taxi_in", "clearance"):
            st = H.State(on_ground=False, range_nm=8.0, inbound=False,
                         phase=name)
            got = H.due(self.pro, self.me, st)
            with self.subTest(name):
                self.assertNotIn(getattr(got, "role", ""),
                                 ("ground", "clearance", "delivery"),
                                 f"an airborne aeroplane in {name!r} was given "
                                 f"to a ground seat")


class TestTheTaskHalfIsStillMissingAndSaysSo(unittest.TestCase):
    """#168's second criterion, unmet, asserted rather than forgotten.

    `tasked` and `on_station` are owned by an overlord and nothing tasks
    anybody. They are reachable in principle -- `enroute` is a phase now -- and
    have no trigger, which is a different thing from being unreachable and is
    worth keeping visible.
    """

    def test_the_overlord_owns_them_and_the_map_staffs_one(self):
        for name in ("tasked", "on_station"):
            with self.subTest(name):
                self.assertEqual(P.owner_of(name), "overlord")
        self.assertIn("overlord", seats(),
                      "nothing on this map answers as an overlord, so those "
                      "two phases are owned by nobody at all")

    def test_but_no_rule_reaches_him(self):
        """If this ever fails somebody built the trigger. Delete this class and
        the note in #168 with it."""
        self.assertNotIn("overlord", {r.to for r in H.RULES})


if __name__ == "__main__":
    unittest.main()
