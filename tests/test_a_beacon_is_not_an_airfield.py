"""An approach always has a field. It sometimes has a beacon. [#163]

    "A beacon is not an airfield. They are separate things and you have built
     them as though they are. ... I think all approaches have an airfield. Not
     all approaches have a beacon. A beacon may be used for things other than
     an approach"

`ApproachProfile.beacon` used to be one slot doing three jobs: the navaid a
pilot tunes and holds on, the geometric datum every range and plate is measured
from, and the origin `field_origin` fell back to. Only the first is a beacon's.

What it actually held was the AERODROME REFERENCE POINT wearing an ident and a
frequency that `tools/import_beacons.py` says outright were invented for the
1944 scenario -- the real Batumi beacon is `LU` on 0.430 and sits 0.72 nm away,
in the same theatre file, imported from the sim's own tables.

THREE ISSUES WERE THIS ONE DEFECT, which is why it was worth splitting rather
than renaming:

    #160  a Center measured from "the beacon", because the beacon was secretly
          the field -- so every range it spoke came from whichever arrival the
          radio happened to be loaded with
    #141  Nevada's TONOPAH fix was called wrong for sitting 34 km from Tonopah
          airfield. It is an ENROUTE VORTAC that carries the town's name, and
          was on top of TPH all along. Closed on that evidence
    #163  this

The tests below are the ones the original change did not live to write.
"""

from __future__ import annotations

import unittest

from marshall.core import route as R

# Every procedure the theatre publishes, by the name the façade exports.
PROCEDURES = ("BATUMI_ASR", "BATUMI_ILS", "BATUMI_APPROACH", "KOBULETI_ILS")

# The one that is genuinely flown ON a beacon: the pilot tunes it, the ARA-8
# points the nose at it, and station passage over it IS the missed approach
# point. It is the reason the concept exists at all.
THE_LETDOWN = "BATUMI_APPROACH"

def profiles():
    for name in PROCEDURES:
        p = getattr(R, name, None)
        if p is not None:
            yield name, p


class TestEveryApproachHasAField(unittest.TestCase):
    """The half that is always true, and was the optional one."""

    def test_all_of_them(self):
        for name, p in profiles():
            with self.subTest(name):
                self.assertIsNotNone(getattr(p, "aerodrome", None),
                                     "an approach with no aerodrome")
                self.assertTrue(getattr(p.aerodrome, "name", ""),
                                "an aerodrome with no name")

    def test_and_it_is_the_field_the_procedure_arrives_at(self):
        want = {"BATUMI_ASR": "BATUMI", "BATUMI_ILS": "BATUMI",
                "BATUMI_APPROACH": "BATUMI", "KOBULETI_ILS": "KOBULETI"}
        for name, p in profiles():
            with self.subTest(name):
                self.assertEqual(p.aerodrome.name, want[name])

    def test_the_letdown_arrives_SOMEWHERE(self):
        """It used to carry `field = ""` -- which was how the file said "no
        surveyed minima", and also said this approach happens at no aerodrome
        at all. Two questions through one key. The field was never in doubt."""
        p = getattr(R, THE_LETDOWN)
        self.assertEqual(p.aerodrome.name, "BATUMI")


class TestMostApproachesHaveNoBeacon(unittest.TestCase):
    """The half that was assumed always true, and is usually false."""

    def test_neither_ILS_has_one(self):
        """A localiser and a glideslope. Nobody homes on the airfield."""
        for name in ("BATUMI_ILS", "KOBULETI_ILS"):
            p = getattr(R, name, None)
            if p is None:
                continue
            with self.subTest(name):
                self.assertIsNone(getattr(p, "navaid", None))

    def test_nor_does_the_surveillance_approach(self):
        """An ASR is a man reading a radar and talking. There is nothing in the
        aeroplane to tune."""
        self.assertIsNone(getattr(R.BATUMI_ASR, "navaid", None))

    def test_but_the_letdown_does_and_keeps_it(self):
        p = getattr(R, THE_LETDOWN)
        h = getattr(p, "navaid", None)
        self.assertIsNotNone(h, "the one procedure that IS a beacon lost it")
        self.assertTrue(getattr(h, "freq_mhz", 0), "a beacon he cannot tune")

    def test_exactly_one_procedure_on_this_map_has_a_beacon(self):
        got = [n for n, p in profiles() if getattr(p, "navaid", None) is not None]
        self.assertEqual(got, [THE_LETDOWN])


class TestTheDatumIsTheField(unittest.TestCase):
    """Where "how far out" is measured from."""

    def test_the_IAF_distance_is_from_the_aerodrome(self):
        """It read the beacon, which was the field wearing an invented ident --
        so it happened to be right here and was zero on Nevada, where the fix
        of the same name is a VORTAC 34 km away."""
        from marshall.atc import asr
        for name, p in profiles():
            if getattr(p, "arrival_fix", None) is None:
                continue
            with self.subTest(name):
                self.assertGreater(asr.iaf_nm(p), 0.0,
                                   "the IAF is zero miles from itself")

    def test_the_asr_plate_draws_from_the_aerodrome(self):
        """Its own comment said "the radar reference point IS the field" while
        the code read the beacon -- a comment correcting its own line."""
        from marshall.kneeboard import asr_plate
        self.assertIn("BATUMI", asr_plate.build())


class TestTheMergedAnswerIsGone(unittest.TestCase):
    """`beacon` means a beacon now, and nothing else.

        "Homer is a new term. Why is beacon such an issue?"

    It was not the word. It was that one slot held two things, so `beacon`
    returned an AIRFIELD on three of this map's four procedures. The split gave
    the datum its own name (`aerodrome`); the navaid briefly got the period word
    `homer`, which was the wrong instinct -- the 1944 vocabulary describing the
    very thing that had over-fitted the system to 1944. It is `beacon` again,
    because the theatre file and the catalogue model always called it that:

        [[approach]] key = "batumi-ndb"   beacon = "BATUMI"      <- the only one
        Approach.beacon: str = ""         <- optional, and always was in DATA

    One word across data, model and runtime, meaning exactly what it says.

    WHAT THIS CLASS GUARDS is the property the merge destroyed: asking a
    procedure with no beacon for its beacon must FAIL, loudly, rather than
    hand back a plausible airfield. That is the difference between a bug
    somebody finds in an hour and one that survives from the first sortie to
    the hundredth, which is what #160, #141 and #163 all were.
    """

    def test_asking_an_ILS_for_a_navaid_raises(self):
        """It used to answer "BATUMI" -- a real fix, at a real place, with a
        real frequency, belonging to a procedure that has no beacon at all."""
        for name in ("BATUMI_ILS", "KOBULETI_ILS", "BATUMI_ASR"):
            p = getattr(R, name, None)
            if p is None:
                continue
            with self.subTest(name), self.assertRaises(AttributeError):
                _ = p.navaid.name

    def test_and_the_letdown_still_answers(self):
        self.assertEqual(getattr(R, THE_LETDOWN).navaid.name, "BATUMI")

    def test_the_datum_never_raises_because_every_approach_has_one(self):
        for name, p in profiles():
            with self.subTest(name):
                self.assertTrue(p.aerodrome.name)

    def test_they_are_two_slots_and_not_an_alias(self):
        """On the letdown both resolve to the same published point, which is a
        fact about Batumi in 1944 -- not evidence that one field would do. The
        real beacon LU is 0.72 nm from the aerodrome; the fiction sits on it."""
        import dataclasses
        p = getattr(R, THE_LETDOWN)
        names = {f.name for f in dataclasses.fields(type(p))}
        self.assertIn("aerodrome", names)
        self.assertIn("navaid", names)
        for name in ("BATUMI_ILS", "KOBULETI_ILS", "BATUMI_ASR"):
            q = getattr(R, name, None)
            if q is None:
                continue
            with self.subTest(name):
                self.assertIsNone(q.navaid)
                self.assertIsNotNone(q.aerodrome)


if __name__ == "__main__":
    unittest.main()
