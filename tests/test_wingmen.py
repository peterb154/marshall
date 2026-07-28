"""Two pilots in one flight are two aeroplanes.

    "This has been a total shitshow."

He was right, and it was one word. `radar_fix` and `aircraft_type_on_scope`
both matched on `.flight`, and FALCON 1-1 AND FALCON 1-2 ARE THE SAME FLIGHT --
so with two humans up, each one's lookup returned whichever of them appeared
first in the radar picture.

Every range, every off-course call, every altitude and every speed for one of
them was computed from the other's position. Live: one was told "one mile from
the runway, descend to minimums" at thirty six miles, while the other was told
he was thirty eight miles northwest and not on final -- as he touched down.

It reads as a controller who has lost his mind, and it could not happen with a
single pilot, which is why a fortnight of solo sorties never found it.
"""

import unittest

from marshall.atc import agent_atc as A
from marshall.core import route as R

# Lead far out and high, wingman on short final. Deliberately as different as
# two positions can be, so a mix-up cannot hide in a plausible number.
SCOPE = ("362nd_sockeye [Falcon 1-1] (F-16C_50, manned): 36.1 nm on the 300 "
         "radial, 12,000 ft, heading 170, 300 knots | "
         "362nd Andre [Falcon 1-2] (P-51D-30-NA, manned): 3.7 nm on the 130 "
         "radial, 900 ft, heading 130, 150 knots")


class TestEachPilotGetsHisOwnPosition(unittest.TestCase):
    def test_the_lead(self):
        self.assertAlmostEqual(
            A.radar_fix(SCOPE, "Falcon 1-1", R.BATUMI_ASR).range_nm, 36.1, 1)

    def test_the_wingman(self):
        self.assertAlmostEqual(
            A.radar_fix(SCOPE, "Falcon 1-2", R.BATUMI_ASR).range_nm, 3.7, 1)

    def test_they_are_not_the_same_aeroplane(self):
        a = A.radar_fix(SCOPE, "Falcon 1-1", R.BATUMI_ASR)
        b = A.radar_fix(SCOPE, "Falcon 1-2", R.BATUMI_ASR)
        self.assertNotEqual(a.range_nm, b.range_nm)


class TestEachPilotGetsHisOwnAeroplane(unittest.TestCase):
    """The same word gave them each other's AIRFRAME, which decides the speed
    assigned and what he can receive -- a wingman in a Mustang beside a lead in
    a Viper would have been told to fly three hundred knots."""

    def test_the_lead_is_the_jet(self):
        self.assertEqual(A.aircraft_type_on_scope(SCOPE, "Falcon 1-1"),
                         "F-16C_50")

    def test_the_wingman_is_the_warbird(self):
        self.assertEqual(A.aircraft_type_on_scope(SCOPE, "Falcon 1-2"),
                         "P-51D-30-NA")

    def test_the_speed_assigned_follows_the_right_airframe(self):
        from marshall.atc import equipment as E
        lead = E.min_speed_kt(A.aircraft_type_on_scope(SCOPE, "Falcon 1-1"))
        wing = E.min_speed_kt(A.aircraft_type_on_scope(SCOPE, "Falcon 1-2"))
        self.assertGreater(lead, wing)


class TestAFlightIsOnlyOneThingWhileItIsJoined(unittest.TestCase):
    """A formation is ONE contact and its members have no track of their own,
    so a member must be able to find the flight's. What must never happen is a
    member finding ANOTHER MEMBER's track.

    The discriminator is the tag: a joined formation is tagged with the FLIGHT
    designator ("Pony one flight"), and two independently tracked aeroplanes
    are tagged individually. If both are separately tagged they are two
    aeroplanes, whatever their callsigns have in common.
    """

    JOINED = ("E11 [Pony one flight] (P-51D): 12.0 nm on the 332 radial, "
              "6,004 ft, heading 151")

    def test_a_member_finds_his_joined_flight(self):
        got = A.radar_fix(self.JOINED, "Pony 1-3", R.BATUMI_ASR)
        self.assertIsNotNone(got)
        self.assertAlmostEqual(got.range_nm, 12.0, 1)

    def test_asking_for_a_flight_whose_members_fly_separately_is_refused(self):
        """"Falcon 1" names a formation that is not one. Both members have
        their own track, so the name refers to nobody in particular -- and
        answering it would pick one of two aeroplanes by accident, which is the
        failure this file exists for. Same reasoning as
        Controller.ambiguous_after_breakup."""
        self.assertIsNone(A.radar_fix(SCOPE, "Falcon 1", R.BATUMI_ASR))

    def test_asking_for_a_member_does_not_find_the_other(self):
        lone = ("362nd Andre [Falcon 1-2] (P-51D-30-NA, manned): 3.7 nm on the "
                "130 radial, 900 ft, heading 130, 150 knots")
        self.assertIsNone(A.radar_fix(lone, "Falcon 1-1", R.BATUMI_ASR))


if __name__ == "__main__":
    unittest.main()
