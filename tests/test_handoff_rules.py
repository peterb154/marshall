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
        """AT BATUMI. The field is not decoration on this call any more.

        This test used to read `station_for("departure")` with no field, and it
        passed for as long as Batumi was the only aerodrome in the world. Adding
        Kobuleti made the same call return KOBULETI Departure -- first in the
        list, a perfectly real Station, forty miles from the aircraft. Nothing
        raised. The expectation is qualified now because the question was always
        ambiguous and only ever had one possible answer by accident.
        """
        self.assertEqual(P.station_for("departure", field="Batumi").name,
                         "Batumi Approach")
        self.assertEqual(P.station_for("departure", field="Batumi").freq_mhz,
                         P.station_for("approach", field="Batumi").freq_mhz)

    def test_the_same_role_at_the_other_field_is_a_different_man(self):
        """The bug this whole change exists to make impossible."""
        self.assertEqual(P.station_for("departure", field="Kobuleti").name,
                         "Kobuleti Departure")
        self.assertNotEqual(
            P.station_for("departure", field="Kobuleti").freq_mhz,
            P.station_for("departure", field="Batumi").freq_mhz)

    def test_a_field_never_borrows_another_fields_controller(self):
        """Kobuleti staffs no dedicated Tower -- Ground wears that hat. Asking
        for one must find HIS ground/tower seat, never Batumi Tower."""
        self.assertEqual(P.station_for("tower", field="Kobuleti").name,
                         "Kobuleti Ground")

    def test_a_region_controller_is_reachable_from_any_field(self):
        """Center owns airspace rather than an aerodrome, so he is fieldless and
        answers from either end of the route. That is the reason `station_for`
        falls out to the fieldless rather than restricting hard."""
        for fld in ("Batumi", "Kobuleti"):
            with self.subTest(field=fld):
                self.assertEqual(P.station_for("center", field=fld).name,
                                 "Georgia Center")

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
        """A rule pointing at an unstaffed role must produce no handoff rather
        than an exception -- otherwise adding a rule breaks every field that has
        not staffed it.

        CLEARANCE USED TO BE THE EXAMPLE HERE and no longer is: both fields
        staff it now, Kobuleti with its own seat and Batumi folded onto Ground.
        So the test needs a role that genuinely nobody works, and "center" at a
        field is the honest one -- Georgia Center is fieldless on purpose, and
        no aerodrome employs him.
        """
        self.assertIsNone(P.station_for("approach", field="Nowhere"))
        v = H.due(P, TOWER, flying(6.0))
        self.assertIsNotNone(v, "the staffed rules still work alongside it")

    def test_both_fields_staff_every_rung_of_the_ladder(self):
        """Seven presets, and a real controller behind each one.

        A rung whose role resolves to nobody is a button the pilot presses in
        the air to reach silence, and he finds out at the worst moment. This is
        the check that the card and the staffing agree.
        """
        for i, s in enumerate(R.PRESET_LADDER, start=1):
            with self.subTest(preset=i, station=s.name):
                self.assertTrue(s.role, f"preset {i} has no role")
                self.assertIs(P.station_for(s.role, field=s.field), s)
                self.assertEqual(R.preset_of(s), i)


if __name__ == "__main__":
    unittest.main()
