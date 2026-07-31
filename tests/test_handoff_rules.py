"""Who has him next, decided from a table rather than a chain of ifs.

    "Don't hard code these rules too much yet, because we haven't added
     clearance delivery or ground yet. Those will be different controllers with
     different handoffs."

The old version was two branches for two roles. These tests are written against
the RULE TABLE so that adding Ground and Clearance Delivery is adding rows, and
so that the two things a distance rule gets wrong stay caught.
"""

import unittest

from marshall.atc import handoff as H
from marshall.core import route as R

P = R.BATUMI_ASR
TOWER = P.station_for("tower")
APPROACH = P.station_for("approach")


def flying(nm, inbound=False):
    return H.State(on_ground=False, range_nm=nm, inbound=inbound)


class TestOutbound(unittest.TestCase):
    """Tower keeps him until he is clear of the circuit."""

    def test_beyond_five_miles_he_goes_to_the_radar_controller(self):
        v = H.due(P, TOWER, flying(6.0))
        self.assertIsNotNone(v)
        self.assertEqual(v.station.name, "Batumi Approach")
        self.assertEqual(v.role, "departure")

    def test_inside_five_miles_tower_still_has_him(self):
        self.assertIsNone(H.due(P, TOWER, flying(2.0)))

    def test_and_on_the_runway_nothing_is_due(self):
        """The moment after he rotates is not the moment to hand him over."""
        self.assertIsNone(H.due(P, TOWER, H.State(True, 0.2, False)))


class TestInbound(unittest.TestCase):
    """Approach gives him back when the runway becomes the problem."""

    def test_within_five_miles_inbound_he_goes_to_tower(self):
        v = H.due(P, APPROACH, flying(4.0, inbound=True))
        self.assertIsNotNone(v)
        self.assertEqual(v.station.name, "Batumi Tower")

    def test_THE_SAME_RANGE_OUTBOUND_IS_NOT_AN_ARRIVAL(self):
        """The reason the conditions are named for the event and not the number.

        Five miles outbound climbing and five miles inbound descending are the
        same distance and opposite situations. A bare `at_5nm` rule hands a
        departing aircraft straight back to Tower, on his way out, which is the
        single most likely way to get this wrong.
        """
        self.assertIsNone(H.due(P, APPROACH, flying(4.0, inbound=False)))

    def test_beyond_five_miles_approach_keeps_him(self):
        self.assertIsNone(H.due(P, APPROACH, flying(9.0, inbound=True)))

    def test_on_the_ground_under_a_radar_controller_is_corrected(self):
        """He has landed and nobody noticed, or he never left. Either way the
        radar controller is not the right man."""
        v = H.due(P, APPROACH, H.State(True, 0.3, False))
        self.assertEqual(v.station.name, "Batumi Tower")


class TestApproachAndDepartureAreOneMan(unittest.TestCase):
    """A station is who has him; a role is what he is called.

        "Batumi Approach and Batumi Departure would always run on the same
         frequency (even at busy airports like Nellis) and they are synonyms
         for each other."

    So a handoff whose target resolves to the station he is ALREADY on is not a
    handoff. Nothing changes hands and nothing is transmitted -- telling a pilot
    to contact the person he is talking to is nonsense on the radio.
    """

    def test_departure_resolves_to_the_approach_station(self):
        self.assertEqual(P.station_for("departure").name, "Batumi Approach")
        self.assertEqual(P.station_for("departure").freq_mhz,
                         P.station_for("approach").freq_mhz)

    def test_a_rule_reaching_his_own_station_is_flagged_not_spoken(self):
        """Constructed rather than waited for: no rule produces this today,
        and one will the moment a role is split off a station that keeps it."""
        v = H.Verdict(station=APPROACH, role="departure", same_station=True)
        self.assertTrue(v.same_station)
        self.assertTrue(v)

    def test_tower_to_departure_IS_a_real_handoff(self):
        """The frequency genuinely changes, so this one is spoken."""
        v = H.due(P, TOWER, flying(6.0))
        self.assertFalse(v.same_station)


class TestTheTableIsTheInterface(unittest.TestCase):
    """Adding a controller must be adding rows."""

    def test_every_rule_names_a_condition_that_exists(self):
        for r in H.RULES:
            with self.subTest(rule=f"{r.frm}->{r.to}"):
                self.assertIn(r.when, H.CONDITIONS)

    def test_every_rule_names_a_role_the_field_can_resolve(self):
        for r in H.RULES:
            with self.subTest(rule=f"{r.frm}->{r.to}"):
                self.assertIsNotNone(P.station_for(r.to),
                                     f"no station covers {r.to!r}")

    def test_a_role_nobody_staffs_is_silently_skipped(self):
        """Clearance delivery does not exist at Batumi yet. A rule pointing at
        an unstaffed role must produce no handoff rather than an exception --
        otherwise adding a rule breaks every field that has not staffed it."""
        self.assertIsNone(P.station_for("clearance"))
        v = H.due(P, TOWER, flying(6.0))
        self.assertIsNotNone(v, "the staffed rules still work alongside it")


if __name__ == "__main__":
    unittest.main()
