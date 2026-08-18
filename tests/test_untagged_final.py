"""An aeroplane radar can see, that nothing has tagged yet, on final.

    Codex audit, 10 August, finding 1.

THE FIX THAT WENT TO ONE CALL SITE. On 1 August `seen` was switched from asking
the scope by CALLSIGN to asking it by TRACK, because the picture labels a manned
contact by player name and `radar_fix` needs a bracketed tag -- so a pilot who
had not been tagged was reported NOT radar identified for a whole sortie:

    "im not sure batumi approach ever REALLY had me on the approach until the
     very end"

Its three siblings were left alone: the `fix` that seeds the engine, the airframe
lookup, and the ground check all went on asking by callsign. So for an identified
but untagged contact the bridge produced the one state worse than either half --

    seen = True        `may_be_sequenced` treats him as a radar arrival
    fix  = None        and the seed that says "he is already on final" never runs

-- and an aeroplane established on the approach is filed as a new arrival and
STACKED. That is precisely the condition the radar seed exists to prevent.

WHY NO EXISTING TEST CAUGHT IT. Every scope fixture in the suite carries a
tagged contact, because the tagged case is the one the prose parser needed.
Untagged-but-tracked is the state every pilot is in for the first few seconds of
every sortie, and nothing exercised it.
"""

import unittest

from marshall.atc import agent_atc as A
from marshall.atc import controller as atc
from marshall.atc import intents
from marshall.core import geo, route as R

# Batumi, as the rest of the suite writes it. `field_origin` cannot be used
# here: it reads PROJECTED, the fix table the SIM pushes at bridge start, which
# is empty offline -- so it returns None and every geometry below would be
# measured from nowhere.
BATUMI = (41.609594, 41.600234)
BULLSEYE = {"blue": {"lat": 42.186548, "lon": 41.678934}}
_BRIDGE = A.Bridge()


def _on_final(profile, nm: float, origin):
    """A contact established on the final approach course, `nm` miles out.

    Placed by projecting from the field along the RECIPROCAL of the final
    course -- i.e. out along the approach path -- and pointed inbound. Computed
    from the profile rather than written as literals so it cannot drift away
    from the approach it claims to be on.
    """
    back = (profile.final_crs_true + 180) % 360
    lat, lon = geo.project_true(origin, back, nm)
    return {
        "name": "Viper 1-4",             # the sim's own unit name -- the track
        "label": "362nd_Sockeye",        # what the picture prints
        "callsign": "",                  # NOTHING HAS TAGGED HIM. The whole point.
        "type": "F-16C_50",
        "lat": lat, "lon": lon,
        "alt_ft": int(nm * 300) + 500,   # a sane glide, roughly 3 degrees
        "heading": profile.final_crs_true,
        "speed_kt": 160.0,
        "manned": True,
    }


class _Spy(atc.Controller):
    """A Controller that records the two questions this bug turned off."""

    def __init__(self, profile):
        super().__init__(profile)
        self.radar_notes: list = []
        self.equipment_notes: list = []
        self.final_asked: list = []

    def note_radar_contact(self, cs, seen):
        self.radar_notes.append((cs, seen))
        return super().note_radar_contact(cs, seen)

    def note_equipment(self, cs, rx):
        self.equipment_notes.append((cs, rx))
        return super().note_equipment(cs, rx)

    def seen_on_final(self, cs, size: int = 1):
        self.final_asked.append(cs)
        return super().seen_on_final(cs, size)


class UntaggedButTracked(unittest.TestCase):

    def setUp(self):
        self.profile = R.BATUMI_ASR
        self.origin = BATUMI
        self.ctl = _Spy(self.profile)
        self.contact = _on_final(self.profile, 6.0, self.origin)
        self.scope = A.Scope("", contacts=[self.contact], origin=self.origin,
                             bullseye=BULLSEYE)
        self._real = A.bedrock_intent.classify if hasattr(A, "bedrock_intent") else None

    def _call(self, kind=intents.IntentKind.CHECK_IN, cs="Sockeye 1-1"):
        return A.separation_context(
            _BRIDGE, self.ctl, "Sockeye one one checking in", self.scope,
            # `known` is the callsign identity.py has bound to this RADIO, and
            # it arrives together with the track -- the engine hears from radios,
            # never from sentences. Without it the caller is unidentified and
            # nothing reaches the engine at all, which is correct and is a
            # different code path from the one under test.
            known="Sockeye 1-1", track=self.contact["name"],
            intent=intents.Intent(kind, cs))

    def test_the_premise_the_contact_really_is_untagged(self):
        """Asserted so this class cannot go vacuous the way others have."""
        self.assertEqual(self.contact["callsign"], "")
        self.assertIsNone(A.radar_fix(self.scope, "Sockeye 1-1", A.field_of(self.profile)),
                          "an untagged contact must be invisible to the "
                          "callsign lookup -- that is the premise of the bug")
        self.assertIsNotNone(
            A.radar_fix_by_track(self.scope, self.contact["name"], A.field_of(self.profile)),
            "but perfectly visible to the track lookup")

    def test_he_is_radar_identified(self):
        self._call()
        self.assertTrue(self.ctl.radar_notes, "radar contact was never noted")
        self.assertTrue(self.ctl.radar_notes[-1][1],
                        "an untagged contact radar can see is still identified")

    def test_the_final_approach_seed_actually_runs(self):
        """THE BUG. seen=True with fix=None meant this was never asked."""
        self._call()
        self.assertTrue(
            self.ctl.final_asked,
            "seen_on_final was never consulted, so an aeroplane established on "
            "the approach would be filed as a new arrival and stacked")

    def test_the_airframe_is_known(self):
        """Equipment fell over in the same case, and an unknown airframe falls
        back to 'assume modern' -- which offers a 1944 fighter a beacon hold."""
        self._call()
        self.assertTrue(self.ctl.equipment_notes,
                        "no equipment derived, so the type was never found")

    def test_a_tagged_contact_still_works(self):
        """The track path must not have cost us the callsign path."""
        tagged = dict(self.contact, callsign="Sockeye 1-1")
        scope = A.Scope("", contacts=[tagged], origin=self.origin,
                        bullseye=BULLSEYE)
        ctl = _Spy(self.profile)
        A.separation_context(_BRIDGE, ctl, "Sockeye one one checking in", scope,
                             known="Sockeye 1-1", track=tagged["name"],
                             intent=intents.Intent(intents.IntentKind.CHECK_IN,
                                                   "Sockeye 1-1"))
        self.assertTrue(ctl.radar_notes[-1][1])
        self.assertTrue(ctl.final_asked)

    def test_no_track_still_falls_back_to_the_callsign(self):
        """With no resolved track the callsign lookup is all there is, and it
        must still be reached -- the fix is track-FIRST, not track-only."""
        tagged = dict(self.contact, callsign="Sockeye 1-1")
        scope = A.Scope("", contacts=[tagged], origin=self.origin,
                        bullseye=BULLSEYE)
        ctl = _Spy(self.profile)
        A.separation_context(_BRIDGE, ctl, "Sockeye one one checking in", scope,
                             known="Sockeye 1-1", track="",
                             intent=intents.Intent(intents.IntentKind.CHECK_IN,
                                                   "Sockeye 1-1"))
        self.assertTrue(ctl.radar_notes[-1][1])

    def test_nothing_on_the_scope_is_not_radar_contact(self):
        """The other direction, so the fix cannot degenerate into always-true."""
        ctl = _Spy(self.profile)
        A.separation_context(_BRIDGE, ctl, "Sockeye one one checking in",
                             A.Scope("", contacts=[], origin=self.origin,
                                     bullseye=BULLSEYE),
                             known="Sockeye 1-1", track="Nobody 1-1",
                             intent=intents.Intent(intents.IntentKind.CHECK_IN,
                                                   "Sockeye 1-1"))
        self.assertTrue(ctl.radar_notes)
        self.assertFalse(ctl.radar_notes[-1][1])


if __name__ == "__main__":
    unittest.main()
