"""An aerodrome nobody surveyed was briefed Batumi's mountains. [#162]

    src/marshall/core/fields.py
        def msa_for(self, b):         return msa_for(b, self.msa_sectors or None)
        def mva_for(self, b, r=None): return mva_for(b, r, self.mva_cells or None)

`or None` looks like a guard and is the opposite of one. An empty grid becomes
`None`, `None` means "use the module tables", and the module tables are
BATUMI's: 7,000 and 13,600 feet of MSA surveyed against the Lesser Caucasus,
and a 48-cell MVA grid measured off the Georgian coast.

Measured on the tree before the fix, against Batumi's own numbers:

    Groom Lake (elev 4,494 ft), no msa_sectors, no mva_cells
      brg  70 / 12 nm -> MVA  6000   MSA 13600
      brg 270 / 10 nm -> MVA  1000   MSA  7000
      brg 120 / 25 nm -> MVA 12000   MSA 13600

    Batumi
      brg  70 / 12 nm -> MVA  6000   MSA 13600
      brg 270 / 10 nm -> MVA  1000   MSA  7000
      brg 120 / 25 nm -> MVA 12000   MSA 13600     identical, byte for byte

A controller vectoring west of that field assigns 1,000 ft -- three and a half
thousand feet below the ground -- silently, plausibly, and in a transmission a
pilot flies in cloud.

AND IT IS NOT LATENT. Neither Nevada field publishes an MSA, so BOTH of them
were briefed Georgia's: 7,000 ft on the northern sectors at Tonopah, whose ramp
is at 5,550 ft and whose own surveyed MVA reaches twelve thousand.

The correct code was twenty lines away the whole time and explains itself:
`ApproachProfile.min_safe_ft` walks surveyed MVA, then published MSA, then
platform, with a docstring reading "Defaulting to the module's tables instead
would hand a new field Batumi's mountains, and a field on flat ground would be
vectored eleven thousand feet up for terrain a hundred miles away." Exactly
right, and `Field_` did the thing it warns against.

An absent minimum altitude is a different FACT from a low one, and a caller
cannot tell them apart when the answer is a plausible integer belonging to
another continent. So it is None -- #109's rule, that a picture with no origin
renders nothing rather than a guess.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marshall.core import route as R
from marshall.core import theatre as TH
from marshall.core.airspace import MSA_SECTORS, MVA_CELLS
from marshall.core.fields import Field_

BEARINGS = (0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330)
RANGES = (None, 5.0, 10.0, 15.0, 25.0)

# 4,494 ft of ramp, no survey, and Batumi's western MVA is 1,000.
UNSURVEYED = Field_(name="Groom Lake", x=0.0, z=0.0, elevation_ft=4494,
                    runway=140, ends=(14, 32))

# Published sectors and no surveyed cells -- the middle rung of the ladder.
PUBLISHED_ONLY = Field_(name="Paper Field", x=0.0, z=0.0, elevation_ft=4494,
                        runway=140, ends=(14, 32),
                        msa_sectors=[(0.0, 180.0, 8300), (180.0, 0.0, 6200)])


class TestAnUnsurveyedFieldIsAnsweredWithNothing(unittest.TestCase):

    def test_no_published_msa_means_no_msa(self):
        for b in BEARINGS:
            with self.subTest(bearing=b):
                self.assertIsNone(UNSURVEYED.msa_for(b))

    def test_no_survey_and_nothing_published_means_no_mva(self):
        for b in BEARINGS:
            for r in RANGES:
                with self.subTest(bearing=b, range_nm=r):
                    self.assertIsNone(UNSURVEYED.mva_for(b, r))

    def test_and_specifically_not_the_other_continents_numbers(self):
        """The assertion the shape of this bug demands. `assertIsNone` above
        would also pass if the module tables were merely emptied; this says
        what the wrong answer WAS."""
        batumi = R.field_named("Batumi")
        self.assertTrue(batumi.msa_sectors and batumi.mva_cells,
                        "the fixture depends on Batumi being the surveyed one")
        for b in BEARINGS:
            with self.subTest(bearing=b):
                self.assertNotEqual(batumi.msa_for(b), UNSURVEYED.msa_for(b))
                self.assertNotEqual(batumi.mva_for(b, 10.0),
                                    UNSURVEYED.mva_for(b, 10.0))

    def test_a_minimum_is_never_below_the_ground_it_is_measured_over(self):
        """1,000 ft west of a field standing at 4,494 was the concrete harm."""
        for b in BEARINGS:
            for r in RANGES:
                got = UNSURVEYED.mva_for(b, r)
                with self.subTest(bearing=b, range_nm=r):
                    if got is not None:
                        self.assertGreater(got, UNSURVEYED.elevation_ft)


class TestTheLadderIsTheProfilesLadder(unittest.TestCase):
    """Surveyed MVA, then this field's own published MSA, then nothing --
    `ApproachProfile.min_safe_ft`'s ladder, on the object holding the tables."""

    def test_a_published_msa_answers_for_a_missing_survey(self):
        for b in BEARINGS:
            with self.subTest(bearing=b):
                self.assertEqual(PUBLISHED_ONLY.msa_for(b),
                                 PUBLISHED_ONLY.mva_for(b, 10.0))

    def test_and_it_is_his_own_and_not_the_modules(self):
        # Deliberately two figures no module table contains, so "it came from
        # this field" and "it happens to match" cannot be confused.
        self.assertEqual({6200, 8300},
                         {PUBLISHED_ONLY.mva_for(b, 10.0) for b in BEARINGS})
        self.assertFalse({6200, 8300} & {alt for *_, alt in MVA_CELLS})

    def test_a_survey_still_wins_over_the_published_figure(self):
        """The MVA is lower than the MSA by construction -- surveyed per cell
        rather than per sector -- so a field with both must not answer with the
        conservative one and lose the vectoring room it paid for."""
        for f in TH.fields_now():
            if not (f.mva_cells and f.msa_sectors):
                continue
            for b in BEARINGS:
                with self.subTest(field=f.name, bearing=b):
                    self.assertLessEqual(f.mva_for(b, 15.0), f.msa_for(b))


class TestEveryFieldOnThisMapAnswersFromItsOwnTables(unittest.TestCase):

    def test_a_field_with_no_sectors_publishes_no_msa(self):
        """Live on Nevada today: neither Nellis nor Tonopah publishes one, and
        both were reading Batumi's 7,000 and 13,600 out as their own."""
        for f in TH.fields_now():
            for b in BEARINGS:
                with self.subTest(field=f.name, bearing=b):
                    if f.msa_sectors:
                        self.assertIsNotNone(f.msa_for(b))
                    else:
                        self.assertIsNone(f.msa_for(b))

    def test_an_unsurveyed_field_never_borrows_the_module_grid(self):
        module_msa = {alt for _, _, alt in MSA_SECTORS}
        for f in TH.fields_now():
            if f.msa_sectors:
                continue
            for b in BEARINGS:
                with self.subTest(field=f.name, bearing=b):
                    self.assertNotIn(f.msa_for(b), module_msa)


if __name__ == "__main__":
    unittest.main()
