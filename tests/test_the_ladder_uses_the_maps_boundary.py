"""The ladder hands over at the edge the MAP drew, not at a constant.

`handoff.CENTER_NM` imports `airspace.TERMINAL_NM` and argues for it:

    "AND IT IS THE SAME NUMBER AS THE EDGE OF APPROACH'S VOLUME, so it is
     imported rather than restated ... holding them separately is one edit away
     from a ladder that hands a man over at twenty-five miles into airspace
     that stops at twenty."

The comment was right and the code stopped satisfying it, because a constant
imported from a module is not the function that module uses. The ladder had 25;
the map drew 11.3.

THIS WAS TRIED ON 13 AUGUST AND REVERTED, and the revert was correct. Reading
the map was right and the map was wrong: terminal areas were eleven-mile
circles around approaches that begin at twenty-two, so `center -> approach`
reading the derived reach would have held an arrival on Center until eleven
miles -- inside the final, later than the rule #51 was filed to fix, for a man
flying the approach exactly as published. Nine tests said so.

#139 fixed the map. An area is derived from the procedures it serves now, so
the same change is the correct one:

    Batumi     27.5 nm     its ILS holds at KOBULETI, 22.5 nm out
    Kobuleti   28.8 nm     its ILS holds at INITIAL,  23.8 nm out

Which is what this file asserts: the boundary the ladder uses and the boundary
the map draws are one number, and it is big enough that an arrival is with
Approach BEFORE his procedure starts. [#130]
"""

from __future__ import annotations

import unittest

from marshall.atc import handoff as H
from marshall.core import airspace as A
from marshall.core import geo
from marshall.core import theatre as T
from tests import theatre as TH


def two_fields():
    got = list(T.fields_now())
    if len(got) < 2:
        raise unittest.SkipTest(f"{TH.name()} works one aerodrome")
    return got


class TestTheTwoBoundariesAreOneNumber(unittest.TestCase):

    def test_the_ladder_asks_the_map(self):
        for f in two_fields():
            with self.subTest(f.name):
                want = A.terminal_reach_nm(
                    f, [o for o in T.fields_now() if o is not f])
                self.assertAlmostEqual(H.reach_of(f.name), want, places=6)

    def test_a_field_nobody_publishes_answers_None(self):
        """The caller keeps its constant. A boundary that collapsed to zero
        because a lookup missed would hand every aeroplane over the instant it
        left the ground."""
        self.assertIsNone(H.reach_of("Nowhere At All"))
        self.assertIsNone(H.reach_of(""))

    def test_only_the_terminal_rows_are_scaled(self):
        """A circuit distance is a circuit distance -- five miles is five miles
        at every aerodrome on every map. Marking a circuit row `terminal_edge`
        would hand a man to Departure twenty-eight miles out."""
        scaled = {(r.frm, r.to) for r in H.RULES if r.terminal_edge}
        self.assertEqual(scaled, {("center", "approach"),
                                  ("departure", "center")})


class TestAnArrivalIsWithApproachBeforeHisProcedureStarts(unittest.TestCase):
    """The whole point, and the thing the 13 August attempt got wrong.

    Center must give him up further out than the approach begins. If the
    boundary is inside the procedure, the man is still talking to a Center at
    the moment he should be established -- which is #51 with the numbers
    changed.
    """

    def setUp(self):
        self.fields = two_fields()
        self.me = TH.center()

    def verdict(self, profile, nm, inbound=True):
        return H.due(profile, self.me,
                     H.State(on_ground=False, range_nm=nm, inbound=inbound,
                             phase="arrival"))

    def test_the_boundary_is_outside_every_approach_it_works(self):
        for key, p in T.approaches_now().items():
            fld = next((x for x in self.fields if x.name.lower()
                        == getattr(p.aerodrome, "name", "").lower()), None)
            fix = getattr(p, "outer_hold", None) or getattr(p, "iaf", None)
            if fld is None or fix is None or getattr(fix, "lat", None) is None:
                continue
            nm, _ = geo.range_bearing_true((fld.lat, fld.lon), fix.lat, fix.lon)
            with self.subTest(key):
                self.assertGreater(
                    H.reach_of(fld.name), nm,
                    f"{key} begins at {nm:.1f} nm and Center keeps him to "
                    f"{H.reach_of(fld.name):.1f} -- he is on the wrong "
                    f"frequency when the procedure starts")

    def test_he_is_handed_over_inside_the_boundary(self):
        pro = TH.the_ils(TH.arrival())
        reach = H.reach_of(TH.arrival().name)
        got = self.verdict(pro, reach - 1.0)
        self.assertIsNotNone(got, "Center still has him inside the area")
        self.assertEqual(got.role, "approach")

    def test_and_kept_outside_it(self):
        pro = TH.the_ils(TH.arrival())
        reach = H.reach_of(TH.arrival().name)
        self.assertFalse(self.verdict(pro, reach + 5.0),
                          "Center gave him up before the area starts")

    def test_the_old_constant_alone_would_now_be_wrong(self):
        """25 is not 27.5, and the difference is the point. If this ever passes
        by accident -- because the derived reach happens to equal the constant
        -- the test above is doing no work and this one says so."""
        reach = H.reach_of(TH.arrival().name)
        if abs(reach - H.CENTER_NM) < 0.5:
            self.skipTest("this map's derived reach equals the constant, so "
                          "nothing here separates them")
        self.assertGreater(reach, H.CENTER_NM)


class TestADepartureIsKeptToTheEdgeOfHisOwnArea(unittest.TestCase):
    """The mirror, and the row #130 was actually filed about.

        "Also kob departure didn't hand me off to center again"
    """

    def setUp(self):
        self.me = TH.station("departure", TH.departure())

    def verdict(self, nm):
        return H.due(TH.the_arrival(), self.me,
                     H.State(on_ground=False, range_nm=nm, inbound=False,
                             phase="departure"))

    def test_kept_inside_his_area(self):
        reach = H.reach_of(TH.departure().name)
        self.assertFalse(self.verdict(reach - 2.0))

    def test_given_to_center_beyond_it(self):
        reach = H.reach_of(TH.departure().name)
        got = self.verdict(reach + 3.0)
        self.assertIsNotNone(got, "nothing hands a departure to Center")
        self.assertEqual(got.role, "center")

    def test_a_SHORT_HOP_LEGITIMATELY_HAS_NO_ENROUTE_LEG(self):
        """The half of #130 that is not a bug, written down so nobody fixes it.

        Kobuleti and Batumi are 22.6 nm apart and a pilot turns for his
        destination long before he is 28.8 miles outbound -- so `outbound_beyond`
        never fires and Center never gets him. That is what happens between two
        fields this close, and the comms card promising an enroute leg is the
        thing that is wrong, not the ladder.
        """
        turned = H.State(on_ground=False, range_nm=11.0, inbound=True,
                         phase="departure")
        self.assertFalse(
            H.due(TH.the_arrival(), self.me, turned),
            "a departure that has turned for his destination was sent to "
            "Center, which is a rung nobody flies on a hop this short")


if __name__ == "__main__":
    unittest.main()
