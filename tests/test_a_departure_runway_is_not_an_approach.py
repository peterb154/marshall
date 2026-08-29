"""A runway number on the ramp is his DEPARTURE runway. [#177]

The first transmission of a sortie, from a parked aeroplane:

    PILOT  Kobuleti Clearance, request clearance, VFR to Batumi,
           visual runway 07

`wants` carries "visual runway 07", and runway 07 resolves uniquely to the
Kobuleti ILS 07 across the whole map -- so the check-in hoist silently assigned
him an approach into the field he was about to leave. Every seat afterwards
worked him as an arrival into Kobuleti, and he found out forty minutes later
while inbound to Batumi, when he could not change it.

The hoist itself is right and is why a pilot who names his approach while
checking in is not asked to repeat himself. What was missing is that clearance,
taxi and holding short are the three rungs that exist only BEFORE an aeroplane
has flown, and a man standing on one of them is not choosing an approach.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from marshall.atc import controller as C  # noqa: E402


def _kind(p):
    return f"{getattr(p, 'kind', None)}-{getattr(p, 'runway', None)}" if p else None


class ADepartureRunwayIsNotAnApproach(unittest.TestCase):

    def setUp(self):
        self.c = C.Controller()
        self.c.check_in("Sockeye")
        self.ac = self.c.get("Sockeye")

    def _pro(self):
        return self.c._pro(self.c.get("Sockeye"))

    def test_every_ordinary_ground_call_would_have_matched(self):
        """The guard is not covering one unlucky phrasing. These are the
        ordinary words of a departure and every one of them resolves."""
        from marshall.core.approach import match_spoken
        for said in ("runway 7",
                     "holding short runway 7 ready for departure",
                     "taxi to runway zero seven",
                     "runway zero seven cleared for take-off"):
            with self.subTest(said=said):
                got, _ = match_spoken(said, C._published_now(), field="Kobuleti")
                self.assertIsNotNone(
                    got, "if this stops matching the guard is moot")

    def test_a_runway_named_on_the_ramp_assigns_nothing(self):
        for rung in ("clearance", "taxi", "holding_short"):
            with self.subTest(rung=rung):
                c = C.Controller()
                c.check_in("Sockeye")
                c.get("Sockeye").sortie_phase = rung
                c.note_wants_approach("Sockeye", "visual runway 07")
                self.assertIsNone(c._pro(c.get("Sockeye")),
                                  f"on {rung} he is departing, not arriving")

    def test_but_airborne_the_same_words_mean_what_they_say(self):
        self.ac.sortie_phase = "enroute"
        self.c.note_wants_approach("Sockeye", "ILS runway one three")
        self.assertEqual(_kind(self._pro()), "ils-13")

    def test_a_bare_runway_is_not_a_choice_in_the_air_either(self):
        """WHAT THE RUNG GUARD WOULD HAVE MISSED, and why it was a smell.

        Refusing the three pre-flight rungs fixed the sortie and left the same
        bug airborne, where a runway is just as often a fact and not a request.
        These are ordinary arrival transmissions, none of them choosing a
        procedure:"""
        self.ac.sortie_phase = "enroute"
        for said in ("runway one three in sight",
                     "field in sight, runway one three",
                     "negative, we were told runway one three"):
            with self.subTest(said=said):
                c = C.Controller()
                c.check_in("Sockeye")
                c.get("Sockeye").sortie_phase = "enroute"
                c.note_wants_approach("Sockeye", said)
                self.assertIsNone(c._pro(c.get("Sockeye")),
                                  "a runway he MENTIONS is not one he chose")

    def test_the_departing_runway_really_does_resolve(self):
        """The fix is load-bearing: unqualified, these words DO match a real
        procedure, which is why this was silent rather than an error."""
        from marshall.core.approach import match_spoken
        got, _ = match_spoken("visual runway 07", C._published_now(), field="")
        self.assertIsNotNone(got, "if this stops matching the guard is moot")
        self.assertEqual(_kind(got), "ils-07")


if __name__ == "__main__":
    unittest.main()
