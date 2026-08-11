"""Airspace is derived from the theatre, so a new aerodrome cannot arrive without it.

    "So how do we prevent missing airspace bug going forward. We're going to add
     dozens of airfields"

You cannot, by hand, and the reason is not effort. `sectors` held three rows
written into migration 005 -- batumi-approach, batumi-tower, georgia-center --
and 005's own comment named the day it would break: "the moment a second
aerodrome exists, and a second aerodrome is the next test." It arrived without
one, so a jet three miles off Kobuleti's runway at two thousand feet fell
through to the unbounded fallback and was offered Georgia Center in the circuit.

The row was not WRONG. It was ABSENT, and absence read as an answer -- which is
the failure mode a hand-maintained table has and a derived one cannot: `sectors`
was a second copy of a fact the theatre already holds, where the aerodromes are
and who works them, maintained independently of it. See docs/STATE.md.

So the check that matters is not "does Kobuleti have a sector" -- that pins one
fix and would have passed all week while the hole existed. It is **every field a
controller works has a volume, whatever the theatre**, and it is asked of every
theatre this project can load.
"""

import unittest

from marshall.core import airspace as A, nevada as N, route as R, theatre as T

# EVERY MAP THIS PROJECT CAN LOAD, not the one that happens to be current. The
# original hole was invisible because nobody asked the question of a theatre
# other than the one in front of them -- and Nevada had it too, unflown and
# unnoticed, right up until this file.
THEATRES = (
    ("caucasus", T.THEATRES["caucasus"](), R.BATUMI_ASR.stations),
    ("nevada", T.THEATRES["nevada"](), N.NEVADA_STATIONS),
)


def _sectors(th, stations):
    return A.sectors_for(th.fields, stations)


class TestNoFieldIsLeftWithoutSky(unittest.TestCase):
    """The general form. Asked of the theatre, not of a field somebody
    remembered to add."""

    def test_every_worked_field_gets_a_terminal_volume(self):
        for name, th, stations in THEATRES:
            with self.subTest(theatre=name):
                got = _sectors(th, stations)
                # Which fields have somebody working the terminal area. That is
                # the population; anything in it without a volume is the bug.
                worked = {s.field for s in stations
                          if s.role in A.TERMINAL_ROLES and s.field}
                have = {s["field"] for s in got if s["role"] == "approach"}
                self.assertEqual(worked, have,
                                 f"{worked - have} has a controller and no sky")

    def test_every_theatre_has_somewhere_to_fall_back_to(self):
        # With no unbounded sector, an aeroplane outside every terminal area
        # resolves to nobody and `due_handoff` skips NULLs -- so leaving the
        # area could never hand anyone over. Migration 008 was written for
        # exactly that, and a new theatre can reintroduce it by shipping no
        # Center.
        for name, th, stations in THEATRES:
            with self.subTest(theatre=name):
                got = _sectors(th, stations)
                self.assertTrue([s for s in got if s["radius_nm"] is None],
                                f"{name} has no unbounded sector")

    def test_a_field_answering_as_departure_still_gets_one(self):
        # Kobuleti's terminal controller is called DEPARTURE and Batumi's
        # APPROACH. A rule that knew only one of those words would give one of
        # the two fields nothing, which is exactly the shape of the original
        # bug wearing different clothes.
        got = _sectors(*THEATRES[0][1:])
        self.assertIn("kobuleti-approach", [s["name"] for s in got])

    def test_the_volume_is_named_for_its_role_not_its_station(self):
        # `leaving_my_airspace` reads the role off the END of the sector name,
        # so `kobuleti-departure` would have told it the volume belonged to a
        # "departure" -- not a rung of any ladder -- and silently switched
        # airspace off for that field.
        got = {s["name"]: s for s in _sectors(*THEATRES[0][1:])}
        self.assertEqual(got["kobuleti-approach"]["label"], "Kobuleti Departure")
        self.assertEqual(got["kobuleti-approach"]["name"].rsplit("-", 1)[-1],
                         "approach")

    def test_the_centre_is_unbounded_and_stays_that_way(self):
        # "everywhere not claimed by anyone else", which is what a Center is.
        # Drawing a polygon round the whole map to say so would be a lie in the
        # shape of precision -- migration 005's phrase, and still right.
        got = [s for s in _sectors(*THEATRES[0][1:]) if s["role"] == "center"]
        self.assertTrue(got)
        for s in got:
            self.assertIsNone(s["radius_nm"])
            self.assertEqual(s["field"], "")


class TestTheBoundaryGoesBetweenThem(unittest.TestCase):
    """Two aerodromes twenty-two miles apart do not both own twenty-five."""

    def test_neighbours_meet_in_the_middle(self):
        th = THEATRES[0][1]
        got = {s["name"]: s for s in _sectors(th, THEATRES[0][2])}
        bat, kob = got["batumi-approach"], got["kobuleti-approach"]
        gap = A._nm_between(
            next(f for f in th.fields if f.name == "Batumi"),
            next(f for f in th.fields if f.name == "Kobuleti"))
        # Half way, so neither swallows the other -- which is what happened on
        # the first attempt at this, when both were given the full terminal
        # range and an aeroplane on Kobuleti's ramp resolved to Batumi Approach.
        self.assertAlmostEqual(bat["radius_nm"], gap / 2.0, places=3)
        self.assertAlmostEqual(kob["radius_nm"], gap / 2.0, places=3)
        self.assertLessEqual(bat["radius_nm"] + kob["radius_nm"], gap + 1e-6)

    def test_a_lone_aerodrome_gets_the_full_terminal_area(self):
        # Nothing to share a boundary with, so the cap is the ladder's own
        # number and not an arbitrary one.
        class _F:
            name, lat, lon = "Alone", 41.0, 41.0

        class _S:
            name, role, field, freq_mhz = "Alone Approach", "approach", "Alone", 1.0
        got, = [s for s in A.sectors_for([_F()], [_S()])
                if s["role"] == "approach"]
        self.assertEqual(got["radius_nm"], A.TERMINAL_NM)

    def test_the_circuit_never_outgrows_the_terminal_area(self):
        # Two fields six miles apart would otherwise give each Tower a circuit
        # reaching over the other's runway.
        class _F:
            def __init__(self, n, lat):
                self.name, self.lat, self.lon = n, lat, 41.0

        class _S:
            def __init__(self, n, role, field):
                self.name, self.role, self.field, self.freq_mhz = n, role, field, 1.0
        fields = [_F("A", 41.0), _F("B", 41.1)]      # 6 nm apart
        st = [_S("A Approach", "approach", "A"), _S("A Tower", "tower", "A"),
              _S("B Approach", "approach", "B"), _S("B Tower", "tower", "B")]
        got = {s["name"]: s for s in A.sectors_for(fields, st)}
        self.assertLessEqual(got["a-tower"]["radius_nm"],
                             got["a-approach"]["radius_nm"])


class TestTheLadderAndTheVolumesAgree(unittest.TestCase):
    """Two statements of one boundary, which must be one number."""

    def test_center_hands_over_where_the_terminal_area_ends(self):
        # `handoff.CENTER_NM` is where Center gives an arrival up and takes a
        # departure back; `airspace.TERMINAL_NM` is the edge of Approach's
        # volume. A system holding them separately is one edit away from a
        # ladder that hands a man over at twenty-five miles into airspace that
        # stops at twenty.
        from marshall.atc import handoff as H
        self.assertEqual(H.CENTER_NM, A.TERMINAL_NM)


if __name__ == "__main__":
    unittest.main()
