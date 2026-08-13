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
from tests import theatre as T

# QUALIFIED, because there are two Towers on the map. Unqualified these were
# Kobuleti's the moment the departure field got a Tower of its own, and every
# assertion below would have been about the wrong aerodrome while still
# passing for some of them. [#51]
#
# ...and RESOLVED WHEN ASKED, because they were module constants and that is a
# second copy of the same mistake one level up: `R.ARRIVAL_FIELD` is a Caucasus
# literal in `core/fields.py`, evaluated at import, so this file -- the guard
# for the rule table that decides who has an aeroplane next -- could not be
# collected on the second map at all.


def P():
    """The procedure this map's bridge is started on."""
    return T.the_arrival()


def TOWER():
    return T.station("tower")


def APPROACH():
    return T.station("approach")


def CENTER():
    return R.station_for("center")


def flying(nm, inbound=False):
    return H.State(on_ground=False, range_nm=nm, inbound=inbound)


class TestOutbound(unittest.TestCase):
    """Tower keeps him until he is clear of the circuit."""

    def test_beyond_five_miles_he_goes_to_the_radar_controller(self):
        v = H.due(P(), TOWER(), flying(6.0))
        self.assertIsNotNone(v)
        self.assertEqual(v.role, "departure")
        self.assertEqual(v.station,
                         R.station_for("departure", field=TOWER().field),
                         "handed to a radar controller at another aerodrome")

    def test_inside_five_miles_tower_still_has_him(self):
        self.assertIsNone(H.due(P(), TOWER(), flying(2.0)))

    def test_and_on_the_runway_nothing_is_due(self):
        """The moment after he rotates is not the moment to hand him over."""
        self.assertIsNone(H.due(P(), TOWER(), H.State(True, 0.2, False)))


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
        talkdown = T.letdown()
        self.assertEqual(talkdown.guidance, "talkdown")
        self.assertIsNone(H.due(talkdown, APPROACH(), flying(4.0, inbound=True)))

    def test_and_landing_hands_him_over_immediately(self):
        """The other half, and the reason suppressing the distance is safe: the
        `on_ground` rule still fires, so Tower gets him the moment he is down
        rather than never.

            "on touchdown, my status didnt change to on ground on the board --
             approach didnt hand me off to tower"
        """
        v = H.due(P(), APPROACH(), H.State(True, 0.3, False))
        self.assertIsNotNone(v)
        self.assertEqual(v.station, R.station_for("tower", field=APPROACH().field))

    def test_where_the_pilot_has_his_own_aid_five_miles_still_works(self):
        """An ILS or a visual is not a talkdown: the aeroplane is flying the
        approach, so once it is established there is nothing left for Approach
        to do and the distance rule is right. Constructed, because Batumi's ASR
        is the only approach in the tree today -- this is the row that must not
        break when Kobuleti's ILS lands."""
        import dataclasses
        ils = dataclasses.replace(P(), guidance="intercept")
        v = H.due(ils, APPROACH(), flying(4.0, inbound=True))
        self.assertIsNotNone(v)
        self.assertEqual(v.station, R.station_for("tower", field=APPROACH().field))

    def test_THE_SAME_RANGE_OUTBOUND_IS_NOT_AN_ARRIVAL(self):
        """The reason the conditions are named for the event and not the number.

        Five miles outbound climbing and five miles inbound descending are the
        same distance and opposite situations. A bare `at_5nm` rule hands a
        departing aircraft straight back to Tower, on his way out, which is the
        single most likely way to get this wrong.
        """
        self.assertIsNone(H.due(T.letdown(), APPROACH(),
                                flying(4.0, inbound=False)))

    def test_beyond_five_miles_approach_keeps_him(self):
        self.assertIsNone(H.due(P(), APPROACH(), flying(9.0, inbound=True)))

    def test_on_the_ground_under_a_radar_controller_is_corrected(self):
        """He has landed and nobody noticed, or he never left. Either way the
        radar controller is not the right man."""
        v = H.due(P(), APPROACH(), H.State(True, 0.3, False))
        self.assertEqual(v.station, R.station_for("tower", field=APPROACH().field))


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
        """AT EVERY FIELD. The field is not decoration on this call any more.

        This test used to read `station_for("departure")` with no field, and it
        passed for as long as Batumi was the only aerodrome in the world. Adding
        Kobuleti made the same call return KOBULETI Departure -- first in the
        list, a perfectly real Station, forty miles from the aircraft. Nothing
        raised. The expectation is qualified now because the question was always
        ambiguous and only ever had one possible answer by accident.
        """
        for f in T.fields():
            dep = R.station_for("departure", field=f.name)
            app = R.station_for("approach", field=f.name)
            if dep is None or app is None:
                continue
            with self.subTest(field=f.name):
                self.assertEqual(dep.field, f.name)
                self.assertEqual(app.field, f.name)

    @T.skip_unless("caucasus", why="Nellis staffs Approach 118.125 and Departure "
                                   "135.1 as two seats on two channels, which is "
                                   "what the real field does -- so 'they are "
                                   "synonyms' is this THEATRE's arrangement, not "
                                   "a rule. The invariant that survives both is "
                                   "asserted above: each resolves to a seat at "
                                   "the field that was asked about")
    def test_departure_and_approach_are_one_frequency(self):
        """The quote at the top of the class, kept exact where it is true."""
        for f in T.fields():
            dep = R.station_for("departure", field=f.name)
            app = R.station_for("approach", field=f.name)
            if dep is None or app is None:
                continue
            with self.subTest(field=f.name):
                self.assertEqual(dep.freq_mhz, app.freq_mhz)

    def test_the_same_role_at_the_other_field_is_a_different_man(self):
        """The bug this whole change exists to make impossible."""
        seen = {}
        for f in T.fields():
            dep = R.station_for("departure", field=f.name)
            if dep is None:
                continue
            with self.subTest(field=f.name):
                self.assertNotIn(dep.freq_mhz, seen,
                                 f"{f.name} and {seen.get(dep.freq_mhz)} are "
                                 f"handed the same departure frequency")
            seen[dep.freq_mhz] = f.name
        self.assertGreaterEqual(len(seen), 2,
                                "fewer than two fields work departures")

    def test_a_field_never_borrows_another_fields_controller(self):
        """Each field staffs its own Tower now, and the answer must be HIS.

        Kobuleti's Ground used to wear the tower hat -- my judgement call when
        the ladder had no Kobuleti Tower in it, and the wrong one:

            "Ground should not clear for takeoff. That's tower."

        Who owns the runway is the one piece of separation on an aerodrome and
        is not an economy to make at a quiet field.
        """
        for f in T.fields():
            tower = R.station_for("tower", field=f.name)
            with self.subTest(field=f.name):
                self.assertIsNotNone(tower, f"{f.name} staffs no Tower")
                self.assertEqual(tower.field, f.name,
                                 f"{f.name}'s runway is owned from {tower.field}")

    def test_ground_does_not_cover_the_tower_anywhere(self):
        """Structural, so the economy cannot creep back in at a new field."""
        for s in R.STATIONS:
            if s.role == "ground":
                with self.subTest(station=s.name):
                    self.assertNotIn("tower", getattr(s, "also", ()),
                                     f"{s.name} can clear an aircraft for "
                                     f"take-off")

    def test_a_region_controller_is_reachable_from_any_field(self):
        """Center owns airspace rather than an aerodrome, so he is fieldless and
        answers from either end of the route. That is the reason `station_for`
        falls out to the fieldless rather than restricting hard."""
        for f in T.fields():
            with self.subTest(field=f.name):
                self.assertEqual(R.station_for("center", field=f.name), CENTER())

    def test_a_rule_reaching_his_own_station_is_flagged_not_spoken(self):
        """Constructed rather than waited for: no rule produces this today,
        and one will the moment a role is split off a station that keeps it."""
        v = H.Verdict(station=APPROACH(), role="departure", same_station=True)
        self.assertTrue(v.same_station)
        self.assertTrue(v)

    def test_tower_to_departure_IS_a_real_handoff(self):
        """The frequency genuinely changes, so this one is spoken."""
        v = H.due(P(), TOWER(), flying(6.0))
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
                self.assertIsNotNone(R.station_for(r.to),
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
        self.assertIsNone(R.station_for("approach", field="Nowhere"))
        v = H.due(P(), TOWER(), flying(6.0))
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
                self.assertIs(R.station_for(s.role, field=s.field), s)
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
        return next(s for s in R.STATIONS if s.name == name)

    def nxt(self, who, st, profile=None):
        me = self.me(who) if isinstance(who, str) else who
        v = H.due(profile if profile is not None else P(), me, st)
        return None if (v is None or v.same_station) else v.station

    def test_a_departure_walks_the_whole_way_out(self):
        """From the DEPARTURE field's Tower, at whichever field that is. Each
        rung is asserted to be the seat at HIS field -- the wrong answer is a
        real controller at the other aerodrome, which is what this file exists
        for."""
        home = T.departure()
        tower = R.station_for("tower", field=home.name)
        self.assertEqual(self.nxt(tower, H.State(False, 6.0, False)),
                         R.station_for("departure", field=home.name))
        dep = R.station_for("departure", field=home.name)
        self.assertEqual(self.nxt(dep, H.State(False, 30.0, False)), CENTER())

    def test_an_arrival_walks_the_whole_way_in(self):
        home = T.arrival()
        app = R.station_for("approach", field=home.name)
        self.assertEqual(self.nxt(CENTER(), H.State(False, 23.0, True)), app,
                         "Center handed an arrival to another field's Approach")
        # ...held through the talkdown, then given up on landing. Asked with a
        # TALKDOWN, because that is the procedure the rule is about: on an ILS
        # the aeroplane flies it and five miles is the right trigger.
        self.assertIsNone(self.nxt(app, H.State(False, 4.0, True), T.letdown()))
        self.assertEqual(self.nxt(app, H.State(True, 0.3, False)),
                         R.station_for("tower", field=home.name))

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
        for f in T.fields():
            approach = R.station_for("approach", field=f.name)
            if approach is None:
                continue
            with self.subTest(field=f.name):
                self.assertIsNone(H.due(P(), approach,
                                        H.State(False, 25.0, True)),
                                  "an arrival was handed away from his own field")

    def test_but_an_outbound_one_is(self):
        """Asked of the DEPARTURE seat, which is the one the rule row names. At
        a field where one man wears both hats that is the same station; at
        Nellis, where Approach 118.125 and Departure 135.1 are two seats, it is
        not -- and asking Approach would be asking a controller who never had
        the departure."""
        for f in T.fields():
            dep = R.station_for("departure", field=f.name)
            if dep is None:
                continue
            v = H.due(P(), dep, H.State(False, 30.0, False))
            with self.subTest(field=f.name):
                self.assertIsNotNone(v, f"{dep.name} can never let go of a "
                                        f"departure")
                self.assertEqual(v.station, CENTER())

    def test_an_inbound_aircraft_on_tower_is_not_sent_to_departure(self):
        """The case that had been wrong all along and never asked."""
        self.assertIsNone(H.due(P(), TOWER(), flying(6.0, inbound=True)))

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
            if cond(near, 5.0, P(), None) == cond(away, 5.0, P(), None):
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
        self.profile = T.the_arrival()

    def station(self, name):
        return next(s for s in self.R.STATIONS if s.name == name)

    def due(self, who, phase):
        """What the ladder says, for a man on the ground in this phase."""
        from marshall.atc import handoff
        me = self.station(who) if isinstance(who, str) else who
        st = handoff.State(on_ground=True, range_nm=0.0, inbound=False,
                           phase=phase)
        return handoff.due(self.profile, me, st)

    def test_a_read_back_hands_clearance_to_ground(self):
        # `clearance_read_back(correct=True)` moves the phase to `taxi`, and
        # taxi is Ground's.
        # AT EVERY FIELD THAT STAFFS A CLEARANCE SEAT. The rung the pilot is
        # handed to must be at the field he is parked on, and a plausible wrong
        # answer is the other aerodrome's Ground on a real frequency.
        for f in T.fields():
            me = self.R.station_for("clearance", field=f.name)
            want = self.R.station_for("ground", field=f.name)
            if me is None or want is None or me is want:
                continue
            v = self.due(me, "taxi")
            with self.subTest(field=f.name):
                self.assertIsNotNone(v, "Clearance can never let go of anybody")
                self.assertEqual(v.role, "ground")
                self.assertEqual(v.station, want)

    def test_holding_short_hands_ground_to_tower(self):
        for f in T.fields():
            me = self.R.station_for("ground", field=f.name)
            want = self.R.station_for("tower", field=f.name)
            if me is None or want is None or me is want:
                continue
            v = self.due(me, "holding_short")
            with self.subTest(field=f.name):
                self.assertIsNotNone(v, "Ground can never let go of anybody")
                self.assertEqual(v.role, "tower")
                self.assertEqual(v.station, want)

    def test_a_landed_aircraft_goes_to_the_ground_of_HIS_field(self):
        # #77. The arrival field's Ground, not the departure field's -- the
        # wrong answer here is a real controller forty miles away.
        for f in T.fields():
            me = self.R.station_for("tower", field=f.name)
            want = self.R.station_for("ground", field=f.name)
            if me is None or want is None or me is want:
                continue
            v = self.due(me, "taxi")
            with self.subTest(field=f.name):
                self.assertIsNotNone(v)
                self.assertEqual(v.station, want)

    def test_tower_keeps_him_while_he_is_still_landed(self):
        # `landed` is Tower's own phase. He is not handed on until he is
        # taxiing, which is what reporting clear of the runway establishes.
        for f in T.fields():
            me = self.R.station_for("tower", field=f.name)
            if me is None:
                continue
            with self.subTest(field=f.name):
                self.assertIsNone(self.due(me, "landed"))

    def test_a_seat_that_also_works_the_next_role_does_not_hand_over(self):
        # A seat carrying also=("delivery", "clearance"): a pilot reading back a
        # clearance to him is not handed to himself.
        both = [s for s in self.R.STATIONS
                if s.role == "ground" and "clearance" in (getattr(s, "also", ()) or ())]
        if not both:
            raise unittest.SkipTest(
                f"{T.name()} has no Ground seat that also delivers clearances, "
                f"so nobody can be handed to himself here")
        for me in both:
            with self.subTest(who=me.name):
                self.assertIsNone(self.due(me, "taxi"),
                                  "he handed the aircraft to the man already "
                                  "holding it")

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


class TestAnAirborneAeroplaneIsNeverGrounds(unittest.TestCase):
    """The touch-and-go, and everything else shaped like it.

        "Yes, an airborne airplane is never ground's. Just have tower take him
         back if he's flying - even if he already said welcome go to ground"

    #77 made `report_down` name Ground in the roll-out transmission, which is
    right and is what a real tower does. It also made a touch-and-go worse: the
    radar poll runs every four seconds against a ten to twenty second roll, so
    it fires, he is told to call Ground and put on `taxi_in` -- and then he
    flies. Before these rows nothing could retrieve him. There was no row out of
    a ground seat at all, and `taxi_in` aims at nothing, so PHASE OWNERSHIP --
    which wins by design -- handed a flying aeroplane back to Ground on every
    poll.

    That is why the invariant is asserted twice below. A rule that a stronger
    branch outranks is not an invariant.
    """

    @property
    def GROUND(self):
        return T.station("ground")

    def test_tower_takes_him_back_when_he_is_flying(self):
        v = H.due(P(), self.GROUND, flying(1.5))
        self.assertIsNotNone(v, "nothing retrieved him")
        self.assertEqual(v.role, "tower")

    def test_even_after_the_goodbye_put_him_on_grounds_phase(self):
        """The phase branch owns him outright, so this is the assertion that
        matters -- the one that failed before the guard existed."""
        st = H.State(on_ground=False, range_nm=1.5, inbound=False,
                     phase="taxi_in")
        v = H.due(P(), self.GROUND, st)
        self.assertIsNotNone(v, "phase ownership kept a flying aeroplane")
        self.assertEqual(v.role, "tower")

    def test_but_a_parked_aeroplane_stays_with_ground(self):
        """The invariant is about FLYING, not about the phase. Ground keeps the
        aeroplane he is meant to have."""
        st = H.State(on_ground=True, range_nm=0.1, inbound=False,
                     phase="taxi_in")
        self.assertIsNone(H.due(P(), self.GROUND, st))

    def test_and_a_track_radar_has_LOST_is_left_where_he_is(self):
        """`not on_ground` is not `airborne`. A track that has gone quiet
        answers False to on_ground -- no unit, no position -- and reading that
        as flying would tear every parked aeroplane off Ground the moment the
        stream hiccuped. Same scar as the board entry for an aeroplane that had
        left the world."""
        st = H.State(on_ground=False, range_nm=None, inbound=False,
                     phase="taxi_in")
        self.assertIsNone(H.due(P(), self.GROUND, st))

    def test_the_ramp_seat_cannot_hold_him_either(self):
        """Airborne off a taxiway with no take-off clearance at all. Nobody
        would have written a special case for it; the invariant covers it."""
        cl = T.station("clearance")
        if cl is None:
            self.skipTest("no clearance seat at the arrival field")
        v = H.due(P(), cl, flying(1.0))
        self.assertIsNotNone(v)
        self.assertEqual(v.role, "tower")

    def test_the_case_the_guard_exists_for_he_has_not_switched_yet(self):
        """He is still on TOWER's frequency, has been told to call Ground, and
        gets airborne before he switches.

        This is the one phase ownership actually reaches: the phase names
        Ground, he is with Tower, so `want != role` and the branch fires --
        handing a flying aeroplane to Ground unprompted. The rule rows cannot
        help here, because the row is keyed on the seat he is WITH.
        """
        st = H.State(on_ground=False, range_nm=1.5, inbound=False,
                     phase="taxi_in")
        v = H.due(P(), TOWER(), st)
        self.assertNotEqual(getattr(v, "role", None), "ground",
                            "phase ownership gave Ground a flying aeroplane")

    def test_and_on_the_ground_that_same_handoff_is_correct(self):
        """The other side of it, so the guard cannot be 'never hand to Ground'.
        Down and rolling, still on Tower: Ground is exactly right."""
        st = H.State(on_ground=True, range_nm=0.2, inbound=False,
                     phase="taxi_in")
        v = H.due(P(), TOWER(), st)
        self.assertIsNotNone(v, "nobody sent him to Ground")
        self.assertEqual(v.role, "ground")
