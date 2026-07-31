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

    def test_on_a_TALKDOWN_the_trigger_is_landing_and_not_a_distance(self):
        """He is NOT handed over at five miles here, and that is the procedure.

            "Real practice keeps him: the final controller obtains the landing
             clearance from Tower and relays it, and the pilot never changes
             frequency inside the final."

        On a surveillance approach the controller IS the approach aid -- he
        reads the range every mile and corrects the heading. Handing him to
        Tower at five miles abandons the pilot at the moment the procedure
        starts, and it did, live, at ten miles in cloud.

        This expectation MOVED when the rule came out of the bridge and into
        the table. It used to pass because the table did not know what an ASR
        was; the bridge's receive path knew, and suppressed the handoff with an
        `if` that the proactive monitor never saw. So the answer depended on
        whether the pilot happened to key the mic. [#51]
        """
        self.assertEqual(P.guidance, "talkdown")
        self.assertIsNone(H.due(P, APPROACH, flying(4.0, inbound=True)))

    def test_and_landing_hands_him_over_immediately(self):
        """The other half, and the reason suppressing the distance is safe: the
        `on_ground` rule still fires, so Tower gets him the moment he is down
        rather than never.

            "on touchdown, my status didnt change to on ground on the board --
             approach didnt hand me off to tower"
        """
        v = H.due(P, APPROACH, H.State(True, 0.3, False))
        self.assertIsNotNone(v)
        self.assertEqual(v.station.name, "Batumi Tower")

    def test_where_the_pilot_has_his_own_aid_five_miles_still_works(self):
        """An ILS or a visual is not a talkdown: the aeroplane is flying the
        approach, so once it is established there is nothing left for Approach
        to do and the distance rule is right. Constructed, because Batumi's ASR
        is the only approach in the tree today -- this is the row that must not
        break when Kobuleti's ILS lands."""
        import dataclasses
        ils = dataclasses.replace(P, guidance="intercept")
        v = H.due(ils, APPROACH, flying(4.0, inbound=True))
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


class TestTheLadderRunsEndToEnd(unittest.TestCase):
    """One table, and every rung reachable from the one before it.

    Both gaps found here were the same shape and neither was found by flying:
    a role that nothing could ever hand to. Center could not be left (#51), and
    then -- once the ladder could be READ in one place -- it turned out nothing
    reached Center either.
    """

    def me(self, name):
        return next(s for s in P.stations if s.name == name)

    def nxt(self, name, st):
        v = H.due(P, self.me(name), st)
        return None if (v is None or v.same_station) else v.station.name

    def test_a_departure_walks_the_whole_way_out(self):
        self.assertEqual(self.nxt("Kobuleti Ground", H.State(False, 6.0, False)),
                         "Kobuleti Departure")
        self.assertEqual(self.nxt("Kobuleti Departure", H.State(False, 30.0, False)),
                         "Georgia Center")

    def test_an_arrival_walks_the_whole_way_in(self):
        self.assertEqual(self.nxt("Georgia Center", H.State(False, 23.0, True)),
                         "Batumi Approach")
        # ...held through the talkdown, then given up on landing.
        self.assertIsNone(self.nxt("Batumi Approach", H.State(False, 4.0, True)))
        self.assertEqual(self.nxt("Batumi Approach", H.State(True, 0.3, False)),
                         "Batumi Tower")

    def test_center_is_reachable_and_leaveable(self):
        """#51 was half of this. A rung you cannot leave strands a pilot; a
        rung nothing reaches is a preset that is never used."""
        reaches = [r for r in H.RULES if r.to == "center"]
        leaves = [r for r in H.RULES if r.frm == "center"]
        self.assertTrue(reaches, "nothing ever hands anybody TO Center")
        self.assertTrue(leaves, "nothing ever hands anybody OFF Center")

    def test_every_rung_of_the_preset_ladder_can_be_left(self):
        """Except the last one on each leg, which is where you stop.

        TWO RUNGS ARE DEAD ENDS TODAY and the pilot has to switch himself.
        Named here rather than silently tolerated, because a preset nothing can
        hand you off is indistinguishable in the air from a controller who has
        forgotten you -- which is exactly what #51 felt like from the cockpit.

        `Kobuleti Clearance`  the absence is deliberate and documented in
                              RULES: "he has his clearance and is ready to
                              push" is not a fact the sim reports, and a
                              condition invented before anything can satisfy it
                              is a rule that can only ever be wrong.

        `Batumi Ground`       not deliberate. `phases` gives "landed" to Tower,
                              which was right while Tower wore the ground hat
                              too; splitting Ground off left a real controller
                              on a real preset that no rule reaches. [F5]

        This list shrinking is the measure of the ladder being finished.
        """
        expected_dead_ends = {"Kobuleti Clearance", "Batumi Ground"}
        for s in R.PRESET_LADDER:
            covers = {s.role, *getattr(s, "also", ())}
            leaves = [r for r in H.RULES if r.frm in covers]
            with self.subTest(station=s.name):
                if s.name in expected_dead_ends:
                    self.assertFalse(leaves, f"{s.name} is no longer a dead end "
                                             f"-- update the exception list")
                else:
                    self.assertTrue(leaves, f"nothing can hand anybody off "
                                            f"{s.name}")


class TestRangeWithoutDirectionIsAmbiguous(unittest.TestCase):
    """The module says so at the top, and one of its conditions did not obey it.

    `airborne_beyond` tested the range and ignored the trend. It survived
    because its only rule was tower -> departure, where an arrival is rarely
    still on Tower at six miles. Adding departure -> center made it reachable
    at once: an aeroplane 25 nm out INBOUND, worked by Approach -- who also
    wears the departure hat -- matched "airborne beyond 25" and was sent to
    Center, away from the field he was arriving at.
    """

    def test_an_inbound_aircraft_is_never_sent_out_to_center(self):
        approach = P.station_for("approach", field="Batumi")
        self.assertIsNone(H.due(P, approach, H.State(False, 25.0, True)),
                          "an arrival was handed away from his own field")

    def test_but_an_outbound_one_is(self):
        approach = P.station_for("approach", field="Batumi")
        v = H.due(P, approach, H.State(False, 30.0, False))
        self.assertIsNotNone(v)
        self.assertEqual(v.station.name, "Georgia Center")

    def test_an_inbound_aircraft_on_tower_is_not_sent_to_departure(self):
        """The case that had been wrong all along and never asked."""
        self.assertIsNone(H.due(P, TOWER, flying(6.0, inbound=True)))

    def test_every_distance_rule_reads_the_trend(self):
        """Structural, so a new rule cannot reintroduce this. A condition that
        takes a distance must consult `inbound` -- otherwise it answers the
        same for an arrival and a departure."""
        blind = []
        # Each probed INSIDE its own band, or the distance test decides the
        # answer and the direction is never reached -- which is how the first
        # version of this test passed a condition that ignores the trend.
        for name, nm in (("outbound_beyond", 10.0), ("inbound_within", 3.0)):
            cond = H.CONDITIONS[name]
            near = H.State(on_ground=False, range_nm=nm, inbound=True)
            away = H.State(on_ground=False, range_nm=nm, inbound=False)
            if cond(near, 5.0, P, None) == cond(away, 5.0, P, None):
                blind.append(name)
        self.assertEqual(blind, [], f"{blind} cannot tell an arrival from a "
                                    f"departure at the same range")
