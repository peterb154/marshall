"""A controller asked for position reports the aeroplane could not make.

    "The report beacon or report over holding fix has always been impossible in
     a ww2 aircraft. In modern we can instruct an aircraft to hold at a navaid
     or a fix on his flight plan. Telling a p51 to hold at the beacon or report
     established has always been impossible and a defect."

HALF THE ENGINE ALREADY KNEW, which is what made the other half easy to miss.
`_hold_phrase` has asked `equipment.can_hold_at` since #163 and falls through to
a racetrack -- a level, a turn direction, an outbound heading, a leg time and an
inbound heading -- for an aeroplane that cannot find the fix. That is the whole
of what a P-51 hold is, and it is right.

`_report_phrase` asked whether the PROCEDURE published a navaid and never
whether the AEROPLANE could detect one. So the instruction was gated on his
equipment and the report was not, on the two halves of one exchange.

WHY IT IS `can_hold_at` AND NOT `can_use`, because that distinction is a real
aeroplane rather than a nicety. An F-16 carries no ADF and cannot RECEIVE an
NDB -- but it has an inertial platform, so it knows where the point is and can
report over it. `can_use` would have sent a Viper looking out of the window for
the field. [#175]
"""

from __future__ import annotations

import dataclasses
import unittest

from marshall.atc import controller as atc
from marshall.atc import equipment
from tests import theatre as TH

# What each airframe can receive. `adf` is the WW2 homing receiver -- only the
# P-51D-30 has one in DCS and it works badly, which is why the era's recoveries
# are radar or visual.
NO_ADF = frozenset({"vhf"})            # every 1944 fighter but one
WITH_ADF = frozenset({"adf"})          # the P-51D-30
MODERN = frozenset({"ins", "tacan"})   # an F-16: no ADF, but it knows where it is


def procedural_with_a_beacon():
    """A published, non-vectored approach onto an NDB.

    Built rather than borrowed: this is the one shape where the question
    arises, and no map is required to publish one. See `tests/theatre.talkdown`
    on why an engine test declares what its rule is about.
    """
    base = TH.the_arrival()
    nav = dataclasses.replace(base.aerodrome, navaid_kind="ndb", freq_mhz=132.0)
    return dataclasses.replace(
        base, guidance="published", navaid=nav,
        atc=dataclasses.replace(base.atc, vectors=False))


def asked(kit, profile=None):
    c = atc.Controller(profile or procedural_with_a_beacon())
    c.bind("Pony 1", track="Pony 1")
    ac = c.get("Pony 1")
    ac.kit = kit
    return c._report_phrase(ac)


class TestHeIsNotAskedForAFixHeCannotFind(unittest.TestCase):

    def test_a_1944_fighter_with_no_receiver_is_asked_for_the_FIELD(self):
        """The one trigger every pilot can detect without anything published or
        anything fitted, which is the same argument the talkdown branch makes."""
        self.assertEqual(asked(NO_ADF), "report the field in sight")

    def test_the_one_aeroplane_that_CAN_home_is_asked_for_the_beacon(self):
        """The P-51D-30. The gate is equipment, not era -- so the era's one
        exception is treated as the exception it is."""
        self.assertIn("BATUMI", asked(WITH_ADF))

    def test_a_modern_aeroplane_with_no_ADF_is_asked_for_the_FIELD_too(self):
        """I asserted the opposite here an hour ago, on the reasoning that an
        F-16 knows where it is. It does -- and that is not the question.

            "F16 needs a navaid or a fix on his plan for a hold."

        He cannot tune an NDB and this fix is not on his filed plan, so he can
        no more report over it than the Mustang can. The era is not what
        decides; the equipment and the flight plan are, which is why the same
        aeroplane WOULD be asked for a fix he had filed."""
        self.assertEqual(asked(MODERN), "report the field in sight")

    def test_and_the_same_aeroplane_IS_asked_for_a_fix_he_filed(self):
        """`on_his_plan` carries it. No caller passes it yet -- that is the
        open half of #175 -- so this exercises the rule directly rather than
        pretending the wiring exists."""
        self.assertTrue(equipment.can_hold_at(MODERN, "ndb", on_his_plan=True))

    def test_an_aeroplane_nothing_is_known_about_is_asked_as_before(self):
        """`kit is None` means the scope has not said, which is not the same as
        "carries nothing" -- the same convention `_hold_phrase` uses. Treating
        silence as an empty aeroplane would downgrade every contact the feed
        has not classified yet."""
        self.assertIn("BATUMI", asked(None))


class TestTheTwoHalvesOfTheExchangeAgree(unittest.TestCase):
    """The instruction and the report ask the same question of the same kit.

    That is the whole defect in one line: they did not. Anything that asks a
    pilot to POSITION himself relative to a point and anything that asks him to
    REPORT it must agree about whether he can, or the controller contradicts
    himself inside one clearance.
    """

    def kit_cases(self):
        return (("no receiver", NO_ADF), ("homing", WITH_ADF),
                ("modern", MODERN))

    def test_whoever_may_be_held_at_a_fix_may_be_asked_to_report_it(self):
        pro = procedural_with_a_beacon()
        for name, kit in self.kit_cases():
            with self.subTest(name):
                can_hold = equipment.can_hold_at(kit, "ndb")
                names_it = "BATUMI" in asked(kit, pro)
                self.assertEqual(can_hold, names_it,
                                 f"{name}: may hold at the fix = {can_hold}, "
                                 f"but asked to report it = {names_it}")

    def test_and_the_hold_offered_to_a_1944_fighter_is_a_racetrack(self):
        """Not a fix. A level, a turn, an outbound heading and a clock, which
        is the whole of what he can fly -- and is already what the engine says.
        Asserted here so the fix side cannot regress unnoticed while this file
        watches the report side."""
        c = atc.Controller(procedural_with_a_beacon())
        c.bind("Pony 1", track="Pony 1")
        got = c._hold_phrase(c.get("Pony 1"), 5000, NO_ADF).lower()
        self.assertNotIn("as published", got)
        self.assertNotIn("batumi", got)
        for want in ("thousand", "outbound", "minute"):
            with self.subTest(want):
                self.assertIn(want, got)


class TestARadarControllerReadsItOutInstead(unittest.TestCase):
    """An ASR exists so he reads the range off a scope and TELLS him.

    Requesting a position the controller can already see is the procedure
    inverted; requesting one the pilot cannot determine is worse. On a talkdown
    the only thing asked of him is what he can see out of the window.
    """

    def test_a_talkdown_asks_only_for_the_field(self):
        # BUILT HERE rather than taken from a shared helper. That helper is
        # being renamed on another branch, and a test whose subject depends on
        # a name in flux is the coupling this whole session has been unpicking.
        base = TH.the_arrival()
        talkdown = dataclasses.replace(
            base, guidance="talkdown",
            atc=dataclasses.replace(base.atc, vectors=False))
        c = atc.Controller(talkdown)
        c.bind("Pony 1", track="Pony 1")
        ac = c.get("Pony 1")
        for name, kit in (("no receiver", NO_ADF), ("modern", MODERN)):
            ac.kit = kit
            with self.subTest(name):
                self.assertEqual(c._report_phrase(ac),
                                 "report the field in sight")


if __name__ == "__main__":
    unittest.main()
