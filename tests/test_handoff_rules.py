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
# QUALIFIED, because there are two Towers on the map. Unqualified these were
# Kobuleti's the moment the departure field got a Tower of its own, and every
# assertion below would have been about the wrong aerodrome while still
# passing for some of them. [#51]
TOWER = P.station_for("tower", field=R.ARRIVAL_FIELD)
APPROACH = P.station_for("approach", field=R.ARRIVAL_FIELD)


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
        """Each field staffs its own Tower now, and the answer must be HIS.

        Kobuleti's Ground used to wear the tower hat -- my judgement call when
        the ladder had no Kobuleti Tower in it, and the wrong one:

            "Ground should not clear for takeoff. That's tower."

        Who owns the runway is the one piece of separation on an aerodrome and
        is not an economy to make at a quiet field.
        """
        self.assertEqual(P.station_for("tower", field="Kobuleti").name,
                         "Kobuleti Tower")
        self.assertEqual(P.station_for("tower", field="Batumi").name,
                         "Batumi Tower")

    def test_ground_does_not_cover_the_tower_anywhere(self):
        """Structural, so the economy cannot creep back in at a new field."""
        for s in P.stations:
            if s.role == "ground":
                with self.subTest(station=s.name):
                    self.assertNotIn("tower", getattr(s, "also", ()),
                                     f"{s.name} can clear an aircraft for "
                                     f"take-off")

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
        self.assertEqual(self.nxt("Kobuleti Tower", H.State(False, 6.0, False)),
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

        THERE ARE NONE LEFT, and getting here is what the phase mechanism was
        for. Both former dead ends closed without a single new rule:

        `Kobuleti Clearance`  `clearance` (delivery) follows `taxi` (ground),
                              so reading the clearance back hands him on. It
                              had been listed as deliberately impossible --
                              "ready to push is not a fact the sim reports" --
                              which was true and beside the point: it is not a
                              fact the SIM reports, it is a fact the
                              CONVERSATION reports.

        `Batumi Ground`       `landed` (tower) follows `taxi` (ground), so
                              Tower hands him to Ground to taxi in. That was
                              F5 on the card, filed as a real gap, and it was
                              closed by writing the procedure down rather than
                              by adding a row for it.

        A preset nothing can hand you off is indistinguishable in the air from
        a controller who has forgotten you -- which is exactly what #51 felt
        like from the cockpit. This list staying empty is the check.

        A ROW IS NOT THE ONLY WAY OUT. The ground transitions are phase
        ownership rather than rules -- moving into a phase somebody else owns
        IS the handoff -- so a rung can be perfectly reachable with no row
        naming it. Checking only `RULES` reported Kobuleti Ground as a dead end
        while `taxi -> holding_short` was already handing him to Tower.
        """
        from marshall.atc import phases as PH
        expected_dead_ends: set[str] = set()

        def can_leave(s):
            covers = {s.role, *getattr(s, "also", ())}
            if [r for r in H.RULES if r.frm in covers]:
                return True
            # Or a no-geometry phase he owns leads to one somebody else owns.
            mine = [p for p in PH.PHASES.values()
                    if p.owner in covers and p.aims_at == "none"]
            return any(PH.owner_of(nxt) not in covers
                       for p in mine for nxt in p.follows
                       if PH.owner_of(nxt))

        for s in R.PRESET_LADDER:
            leaves = can_leave(s)
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


class TheGroundLadderCanActuallyLetGo(unittest.TestCase):
    """Every ground handoff failed at once, and one line of control flow did it.

    `next_controller` reads three kinds of evidence in order: the sim's events,
    the rule table, then the airspace volumes. The rule-table step is where the
    PHASE branch lives -- the one written specifically for the ground half of a
    sortie, whose own comment says:

        A parked aeroplane has no geometry to argue from, so without it
        Clearance, Ground and Tower can never let go of anybody.

    It sat behind `elif`, on the far side of `if down: nxt = None`. So the test
    written for aeroplanes that are parked ran only for aeroplanes that were
    flying, and the comment named exactly the aircraft that could never reach
    it.

    Live, 10 August, three failures from one sortie -- and in each the AGENT
    proposed the right handoff and the authorisation deleted it:

        Q3  a correct clearance read-back did not hand him to Ground
        Q6  reporting holding short did not hand him to Tower
        F5  landing did not hand him to Batumi Ground (#77)

            .. refused an unauthorised handoff: Sockeye, roger, holding short
               runway zero seven, contact Tower one three three decimal zero
            ATC: sockeye, Kobuleti Ground, go ahead.

    The phase table has described all three since it was written. Nothing could
    read it from the ground.
    """

    def setUp(self):
        from marshall.core import route as R
        self.R = R
        self.profile = R.BATUMI_ASR

    def station(self, name):
        return next(s for s in self.R.STATIONS if s.name == name)

    def due(self, me_name, phase):
        """What the ladder says, for a man on the ground in this phase."""
        from marshall.atc import handoff
        me = self.station(me_name)
        st = handoff.State(on_ground=True, range_nm=0.0, inbound=False,
                           phase=phase)
        return handoff.due(self.profile, me, st)

    def test_a_read_back_hands_clearance_to_ground(self):
        # `clearance_read_back(correct=True)` moves the phase to `taxi`, and
        # taxi is Ground's.
        v = self.due("Kobuleti Clearance", "taxi")
        self.assertIsNotNone(v, "Clearance can never let go of anybody")
        self.assertEqual(v.role, "ground")
        self.assertEqual(v.station.name, "Kobuleti Ground")

    def test_holding_short_hands_ground_to_tower(self):
        v = self.due("Kobuleti Ground", "holding_short")
        self.assertIsNotNone(v, "Ground can never let go of anybody")
        self.assertEqual(v.role, "tower")
        self.assertEqual(v.station.name, "Kobuleti Tower")

    def test_a_landed_aircraft_goes_to_the_ground_of_HIS_field(self):
        # #77. The arrival field's Ground, not the departure field's -- the
        # wrong answer here is a real controller forty miles away.
        v = self.due("Batumi Tower", "taxi")
        self.assertIsNotNone(v)
        self.assertEqual(v.station.name, "Batumi Ground")

    def test_tower_keeps_him_while_he_is_still_landed(self):
        # `landed` is Tower's own phase. He is not handed on until he is
        # taxiing, which is what reporting clear of the runway establishes.
        self.assertIsNone(self.due("Batumi Tower", "landed"))

    def test_a_seat_that_also_works_the_next_role_does_not_hand_over(self):
        # Batumi Ground carries also=("delivery", "clearance"); a pilot reading
        # back a clearance to him is not handed to himself.
        v = self.due("Batumi Ground", "taxi")
        self.assertIsNone(v, "he handed the aircraft to the man already holding it")

    def test_the_phase_branch_is_reachable_while_on_the_ground(self):
        # THE REGRESSION ITSELF. Everything above tests `handoff.due`, which was
        # right the whole time; this tests that `next_controller` asks it.
        import inspect
        from marshall.atc import agent_atc
        src = inspect.getsource(agent_atc.next_controller)
        i_down = src.index("nxt = None if down else handoff_on_the_event")
        i_due = src.index("_handoff.due(")
        self.assertLess(i_down, i_due)
        self.assertIn("if nxt is None and me is not None:", src,
                      "the phase branch must not be gated on being airborne")
