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
1944 scenario -- the real Batumi homer is `LU` on 0.430 and sits 0.72 nm away,
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

import pathlib
import re
import unittest

from marshall.core import route as R

# Every procedure the theatre publishes, by the name the façade exports.
PROCEDURES = ("BATUMI_ASR", "BATUMI_ILS", "BATUMI_APPROACH", "KOBULETI_ILS")

# The one that is genuinely flown ON a beacon: the pilot tunes it, the ARA-8
# points the nose at it, and station passage over it IS the missed approach
# point. It is the reason the concept exists at all.
THE_LETDOWN = "BATUMI_APPROACH"

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"


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
                self.assertIsNone(getattr(p, "homer", None))

    def test_nor_does_the_surveillance_approach(self):
        """An ASR is a man reading a radar and talking. There is nothing in the
        aeroplane to tune."""
        self.assertIsNone(getattr(R.BATUMI_ASR, "homer", None))

    def test_but_the_letdown_does_and_keeps_it(self):
        p = getattr(R, THE_LETDOWN)
        h = getattr(p, "homer", None)
        self.assertIsNotNone(h, "the one procedure that IS a beacon lost it")
        self.assertTrue(getattr(h, "freq_mhz", 0), "a homer he cannot tune")

    def test_exactly_one_procedure_on_this_map_has_a_beacon(self):
        got = [n for n, p in profiles() if getattr(p, "homer", None) is not None]
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


class TestTheTransitionalShimDoesNotSpread(unittest.TestCase):
    """`ApproachProfile.beacon` survives as a property, and must not grow.

    It returns the homer where there is one and the aerodrome otherwise --
    which is precisely the merged answer that was wrong. It exists only because
    the change could not edit `agent_atc.py`, which another agent held at the
    time, and `controller.py`'s letdown phrases.

    This is the criterion #162 found missing on #2: four acceptance criteria
    were met while the old path stayed in 26 of 28 call sites, because none of
    them asked what still READ the thing being replaced. So this one is a grep.
    """

    ALLOWED = {"atc/agent_atc.py", "atc/controller.py"}

    def test_only_the_known_readers_remain(self):
        found = set()
        for path in SRC.rglob("*.py"):
            for line in path.read_text().splitlines():
                code = line.split("#", 1)[0]
                if re.search(r"\.beacon\b", code) and "def beacon" not in code:
                    rel = path.relative_to(SRC / "marshall").as_posix()
                    # `a.beacon` on the catalogue row is a STRING KEY naming a
                    # published fix, not the profile property. Different thing,
                    # and it is how the file says which navaid to resolve.
                    if rel.startswith("core/"):
                        continue
                    found.add(rel)
        new = found - self.ALLOWED
        self.assertEqual(new, set(),
                         f"new readers of the transitional shim: {sorted(new)}. "
                         "Use `aerodrome` for the datum or `homer` for the "
                         "navaid; do not add a caller to the merged answer.")


if __name__ == "__main__":
    unittest.main()
