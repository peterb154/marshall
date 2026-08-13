"""The phase table is the one list of what can be happening to an aeroplane.

It exists because three components each held their own idea of that and
disagreed on the radio. A complete table with incomplete code behind it is the
honest position: naming every phase stops anything inventing a state nothing
else knows about, and `handler` says plainly which ones we can actually fly.
"""

import unittest

from marshall.atc import phases
from marshall.core import route as R


class TestTheTableIsCoherent(unittest.TestCase):
    def test_every_transition_points_at_a_real_phase(self):
        for p in phases.PHASES.values():
            for nxt in p.follows:
                self.assertIn(nxt, phases.PHASES, f"{p.name} -> {nxt}")

    def test_every_phase_declares_what_the_geometry_aims_at(self):
        for p in phases.PHASES.values():
            self.assertIn(p.aims_at, ("none", "point", "course", "orbit"), p.name)

    def test_a_phase_with_no_geometry_asks_for_none(self):
        for name in ("filed", "clearance", "taxi", "landed"):
            self.assertEqual(phases.get(name).aims_at, "none")

    def test_the_whole_sortie_is_reachable_from_an_entry_point(self):
        # Two ways in, both real: a plan is filed before the aeroplane exists,
        # or a pilot simply calls up and we know nothing. Nothing stranded from
        # either.
        seen, stack = set(), ["filed", "unknown"]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(phases.get(cur).follows)
        self.assertEqual(seen, set(phases.PHASES), f"unreachable: "
                         f"{set(phases.PHASES) - seen}")


class TestTransitions(unittest.TestCase):
    def test_a_holding_aircraft_may_be_cleared_for_the_approach(self):
        self.assertTrue(phases.may_follow("holding", "approach"))

    def test_an_enroute_aircraft_may_land(self):
        """It used to read `may_NOT_land`, and that was the table arguing with
        the sim. Wheels on the ground is an observation, and the phase he
        happened to be in when it happened cannot make it untrue. [#151]"""
        self.assertTrue(phases.may_follow("enroute", "landed"))

    def test_a_go_around_returns_to_the_pattern(self):
        self.assertTrue(phases.may_follow("approach", "missed"))
        self.assertTrue(phases.may_follow("missed", "holding"))

    def test_and_a_man_who_went_around_may_still_come_back_and_land(self):
        """The other half of the same rewrite. `missed -> landed` was refused,
        which is the commonest recovery there is: he goes around, he is brought
        back, he lands -- and if nothing re-derived him onto the approach first
        the touchdown was refused and his phase welded to `missed`."""
        self.assertTrue(phases.may_follow("missed", "landed"))

    def test_but_a_man_who_has_never_flown_has_not_landed(self):
        """What `follows` was written to protect, and it is untouched: a ground
        phase does not lead to `landed`, so a jet on the ramp before start-up is
        not welcomed home and sent to parking."""
        for phase in ("clearance", "taxi", "holding_short", "taxi_in"):
            with self.subTest(phase=phase):
                self.assertFalse(phases.may_follow(phase, "landed"))

    def test_an_unknown_phase_permits_nothing(self):
        self.assertFalse(phases.may_follow("loitering-about", "approach"))


class TestOwnershipDrivesHandoffs(unittest.TestCase):
    """A handoff should be a consequence of the phase changing, not a rule of
    its own -- which is what the range threshold that sends aircraft to Tower
    too early actually is."""

    def test_the_owner_changes_across_the_arrival(self):
        self.assertEqual(phases.owner_of("enroute"), "center")
        self.assertEqual(phases.owner_of("approach"), "approach")
        self.assertEqual(phases.owner_of("landed"), "tower")

    def test_tasking_belongs_to_the_overlord(self):
        self.assertEqual(phases.owner_of("tasked"), "overlord")
        self.assertEqual(phases.owner_of("on_station"), "overlord")


class TestDispatch(unittest.TestCase):
    def setUp(self):
        from marshall.atc import geometry
        self.pos = geometry.Position(8.0, 304.0, 2000, 124.0)

    def test_the_approach_is_flown_by_the_proven_geometry(self):
        from marshall.atc import asr
        g = phases.guide("approach", self.pos, R.BATUMI_ASR)
        self.assertIsNotNone(g)
        self.assertEqual(g, asr.guide(self.pos, R.BATUMI_ASR))

    def test_an_unimplemented_phase_is_silent_rather_than_improvising(self):
        for name in ("clearance", "departure", "tasked", "on_station"):
            self.assertIsNone(phases.guide(name, self.pos, R.BATUMI_ASR), name)

    def test_flown_lists_exactly_what_has_a_handler(self):
        """`arrival` joined on 9 August, and it is a correction rather than a
        feature: `asr.guide` has flown that phase since it was written -- the
        "vectoring, twenty three miles, turn right" calls are it, and they
        happen long before anybody is cleared. The table said the phase had no
        handler while the code flew it anyway."""
        self.assertEqual(set(phases.FLOWN), {"arrival", "approach", "missed"})
