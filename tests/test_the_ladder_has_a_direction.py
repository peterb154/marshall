"""An arrival climbs the ladder, and geography must not push him back down.

#138, from the sortie of 12 August. Two complaints, one cause:

    04:54:45   checked in with Batumi Approach at 27 nm inbound, handed BACK
               to Georgia Center
    05:03:42   Batumi Tower tried to hand him to Batumi Approach, four times,
               at four, two and one miles on final

        "he just tried to transfer me back to approach when I was within five
         miles on the final"
        "that was totally wrong that he wants me to go to approach"

There is no `tower -> approach` rule and never was. Both came from the PostGIS
airspace volumes -- the third and weakest kind of evidence `next_controller`
consults -- and the monotonic guard at the end of `leaving_my_airspace` could
stop neither: it forbids handing a man UP the ladder, so `tower -> approach`
counts as DOWN and is allowed. An aeroplane on final is inside Approach's
volume for as long as he is flying, because Tower's authority is the runway and
the circuit rather than a shape on a map.

The fix is the function's own name. It answers a question about a man who is
LEAVING; an aeroplane pointed at the field is not leaving.

The ranges, radials and headings below are off the flight recorder.
"""

from __future__ import annotations

import unittest

from marshall.atc import agent_atc as A
from marshall.atc import controller as atc
from marshall.atc import asr
from marshall.core import route as R

# WOULD FAIL IF REACHED. Every case here must be decided before any HTTP call,
# so the port is one nothing is listening on -- a test that passes because the
# director happened to be down would prove nothing at all.
NOWHERE = "http://127.0.0.1:1"


class AnInboundAircraftIsNotLeaving(unittest.TestCase):

    def setUp(self):
        self.p = R.BATUMI_ILS

    def at(self, nm, radial, heading, alt=3000):
        return asr.Position(range_nm=nm, radial_deg=radial, alt_ft=alt,
                            heading_deg=heading)

    def test_tower_does_not_give_a_man_on_final_back_to_approach(self):
        """05:03:42, 05:04:16, 05:04:20, 05:04:47 -- four times, inside 5 nm."""
        tower = R.station_for("tower", field="Batumi")
        for nm in (5.0, 4.0, 2.0, 1.0):
            with self.subTest(nm=nm):
                self.assertIsNone(
                    A.leaving_my_airspace(NOWHERE, "s", "Sockeye", tower,
                                          self.p, self.at(nm, 313, 133)))

    def test_approach_keeps_an_arrival_at_twenty_seven_miles(self):
        """04:54:45. He had checked in with Batumi Approach ninety seconds
        earlier and was handed back to Center."""
        approach = R.station_for("approach", field="Batumi")
        self.assertIsNone(
            A.leaving_my_airspace(NOWHERE, "s", "Sockeye", approach, self.p,
                                  self.at(27.0, 328, 213, alt=10000)))

    def test_the_recorded_geometry_reads_as_inbound(self):
        """The scope line at 04:51:57, verbatim:

            362nd_sockeye (F-16C_50, manned): 35.0 nm on the 328 radial,
            10,136 ft, heading 213, 562 knots

        Sitting on the 328 radial means the field is on 148. Heading 213 is
        sixty-five degrees off that -- inside the quadrant, so he is closing.
        """
        self.assertLess(abs(asr.angle_diff((328 + 180) % 360, 213)), 90)

    def test_an_outbound_departure_is_still_handed_over(self):
        """The case the airspace branch exists for, and it must survive.

        A jet leaving Kobuleti for Batumi turns for the destination and is never
        twenty-five miles outbound, so `departure -> center` cannot fire on this
        sortie and the volume is the only thing that catches him. Outbound, the
        question is a real one and the branch must reach the director -- which
        is not listening, so it returns None rather than a station, and that is
        the check: it got far enough to try.
        """
        dep = R.station_for("departure", field="Kobuleti")
        # ON the 040 radial and heading 040 is straight out from the field.
        # The first version of this fixture said heading 220, which is the
        # reciprocal -- an aeroplane flying home, asserted to be leaving.
        out = self.at(11.0, 40, 40)
        self.assertGreater(abs(asr.angle_diff((40 + 180) % 360, 40)), 90,
                           "the fixture must actually be outbound")
        self.assertIsNone(A.leaving_my_airspace(NOWHERE, "s", "Sockeye", dep,
                                                self.p, out))

    def test_a_fix_with_no_heading_is_not_guessed_at(self):
        """No trend, no opinion from this guard -- it falls through to the rest
        rather than inventing a direction."""
        pos = asr.Position(range_nm=20.0, radial_deg=90, alt_ft=5000,
                           heading_deg=None)
        self.assertIsNone(
            A.leaving_my_airspace(NOWHERE, "s", "Sockeye",
                                  R.station_for("approach", field="Batumi"),
                                  self.p, pos))


class AirborneIsNotAnEvent(unittest.TestCase):
    """The rung the first fix could not reach, because it is decided earlier.

    `next_controller` is a cascade -- the sim's events, then the ladder, then
    the volumes -- and #138 was fixed in the THIRD of those. The first one,
    `handoff_on_the_event`, answers "he is airborne and he is Tower's, so give
    him back to Approach" without ever looking at which way he is going, so it
    kept producing the exact transmission the fix was written to stop. On 12
    August the pilot got it four times inside five miles; a ghost flown inbound
    on 12 August got it twice, two hundred yards after being handed TO Tower:

        4.7 nm  Dagger one six, contact Batumi Tower one one eight decimal six.
        4.5 nm  Dagger one six, contact Batumi Approach one two four decimal
                four two five.

    `on_ground` is a STATE and the branch reads it as an EVENT: it is equally
    true of a jet that has just rotated and of one on a four-mile final. What
    distinguishes them is the trend, which is a fact we hold and were not using
    -- the third place the same rule had to be written, which is why it is now
    one function (`coming_towards_us`).
    """

    ON_FINAL = ("362nd_sockeye [Sockeye] (F-16C_50, manned): 4.5 nm on the 311 "
                "radial, 1,350 ft, heading 131, 300 knots")
    JUST_OFF = ("362nd_sockeye [Sockeye] (F-16C_50, manned): 2.0 nm on the 112 "
                "radial, 1,200 ft, heading 112, 220 knots")

    def setUp(self):
        self.p = R.BATUMI_ILS
        self.tower = R.station_for("tower", field="Batumi")

    def at(self, nm, radial, heading, alt=1350):
        return asr.Position(range_nm=nm, radial_deg=radial, alt_ft=alt,
                            heading_deg=heading)

    def test_tower_keeps_a_man_on_final(self):
        self.assertIsNone(
            A.handoff_on_the_event(self.ON_FINAL, "362nd_sockeye", self.tower,
                                   self.p, self.at(4.5, 311, 131)))

    def test_and_at_every_range_inside_the_circuit(self):
        """Four, two and one mile, which is where he got all four of them."""
        for nm in (4.0, 2.0, 1.0):
            with self.subTest(nm=nm):
                self.assertIsNone(
                    A.handoff_on_the_event(self.ON_FINAL, "362nd_sockeye",
                                           self.tower, self.p,
                                           self.at(nm, 311, 131)))

    def test_a_departure_with_radar_is_the_TABLE_S_and_not_this_branch_s(self):
        """INVERTED IN #200, and it completes this class's own thesis.

        It read "the case the branch exists for, and it must survive: he
        rotated, he is going away" -- and asserted the handoff at TWO MILES.
        That is the transmission a pilot complained about twice:

            "he sent me to departure before I even hit the end of the runway"

        Airborne is not an event, which is the name of this class. What follows
        from getting airborne is a matter of RANGE, and the range lives in the
        rule table -- `Rule("tower", "departure", "outbound_beyond",
        DEPARTURE_NM)` -- which said five miles all along and was never asked.

            "I don't see why the handoff to departure is any different on a go
             around. Still use the 5nm airspace rule right?"

        Right, and the go-around is a table row now too, at the same range and
        with a different destination.
        """
        got = A.handoff_on_the_event(self.JUST_OFF, "362nd_sockeye", self.tower,
                                     self.p, self.at(2.0, 112, 112))
        self.assertIsNone(got, "the event branch handed a departure away at "
                               "two miles, before the table could say five")

    def test_a_controller_with_no_radar_behaves_exactly_as_before(self):
        """No fix, no opinion about direction -- and the old answer stands. A
        guard that needs a picture must not disarm a controller who has none."""
        got = A.handoff_on_the_event(self.JUST_OFF, "362nd_sockeye", self.tower,
                                     self.p)
        self.assertIsNotNone(got)
        self.assertIn("approach", got.name.lower())

    def test_landing_still_ends_the_approach(self):
        """The other direction of the same branch, untouched: on the ground
        under a radar controller is Tower's, whichever way he was pointing."""
        down = ("362nd_sockeye [Sockeye] (F-16C_50, manned, on the ground): "
                "0.5 nm on the 112 radial, 40 ft, heading 131, 8 knots")
        got = A.handoff_on_the_event(
            down, "362nd_sockeye", R.station_for("approach", field="Batumi"),
            self.p, self.at(0.5, 112, 131, alt=40))
        self.assertIsNotNone(got)
        self.assertIn("tower", got.name.lower())


class OneDefinitionOfInbound(unittest.TestCase):
    """It was written out three times and enforced in two.

    Every one of these had its own copy of "within a quadrant of the reciprocal
    of the radial", and the copy that was missing is the one that outranks the
    other two. A rule stated three times is a rule that can be fixed twice.
    """

    def test_the_recorded_arrival_reads_as_coming_towards_us(self):
        self.assertTrue(A.coming_towards_us(
            asr.Position(range_nm=27.0, radial_deg=328, alt_ft=10000,
                         heading_deg=213)))

    def test_a_departure_does_not(self):
        self.assertFalse(A.coming_towards_us(
            asr.Position(range_nm=11.0, radial_deg=40, alt_ft=5000,
                         heading_deg=40)))

    def test_and_nothing_known_is_not_an_arrival_either(self):
        """"We cannot tell" and "he is going away" must not be one answer."""
        self.assertFalse(A.coming_towards_us(None))
        self.assertFalse(A.coming_towards_us(
            asr.Position(range_nm=20.0, radial_deg=90, alt_ft=5000,
                         heading_deg=None)))

    def test_the_ladder_reads_it_from_the_same_place(self):
        """`_handoff_state` and the event branch must agree by construction,
        which is what having one function buys."""
        pos = asr.Position(range_nm=4.5, radial_deg=311, alt_ft=1350,
                           heading_deg=131)
        st = A._handoff_state("", "362nd_nobody", pos)
        self.assertTrue(st.inbound)
        self.assertIs(st.inbound, A.coming_towards_us(pos))


class NobodyIssuesAClearanceThatIsNotHis(unittest.TestCase):
    """The other half of #138, and the aerodrome invariant from CLAUDE.md.

    The GROUND half has been enforced since the ground procedure was written --
    `request_takeoff` refuses and redirects. The TERMINAL half was written down
    only in the agent's brief, as English, so `request_approach` had no such
    line and Georgia Center cleared a man for the ILS twice while Batumi
    Approach cleared him not at all.

    REFUSE AND REDIRECT, not silence. A controller who simply does nothing is
    the failure this codebase keeps producing -- indistinguishable from one who
    agreed.
    """

    def setUp(self):
        self.p = R.BATUMI_ILS

    def working(self, role, field="Batumi"):
        ctl = atc.Controller(profile=self.p)
        ctl._me = R.station_for(role, field=field)
        return ctl

    def test_center_may_not_clear_an_approach(self):
        ctl = self.working("center", field="")
        ctl.request_approach("Sockeye")
        said = " ".join(t.text for t in ctl.out)
        self.assertIn("Approach's", said)
        self.assertNotIn("cleared", said.lower())

    def test_and_he_says_which_frequency(self):
        """Naming the position alone leaves a pilot hunting for a number."""
        ctl = self.working("center", field="")
        ctl.request_approach("Sockeye")
        self.assertIn("contact", " ".join(t.text for t in ctl.out))

    def test_approach_still_works_him(self):
        ctl = self.working("approach")
        ctl.request_approach("Sockeye")
        said = " ".join(t.text for t in ctl.out).lower()
        self.assertNotIn("approach's", said)

    def test_departure_may_too_because_it_is_the_same_man(self):
        """`Station.also` -- one radar room answering to two names. A field
        with a single controller must not refuse its own arrivals."""
        ctl = self.working("departure", field="Kobuleti")
        ctl.request_approach("Sockeye")
        self.assertNotIn("Approach's", " ".join(t.text for t in ctl.out))

    def test_an_engine_told_nothing_still_works(self):
        """`_owns` returns True when the bridge has not said who is speaking --
        every tool and rehearsal builds a Controller without a station, and the
        engine is blind by design rather than mute."""
        ctl = atc.Controller(profile=self.p)
        ctl.request_approach("Sockeye")
        self.assertNotIn("Approach's", " ".join(t.text for t in ctl.out))


if __name__ == "__main__":
    unittest.main()
