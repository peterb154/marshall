"""The automatic talk-down has to find somebody to talk to.

THE SORTIE THIS COMES FROM, 31 July. A pilot flew a surveillance approach and
the controller went silent on final. He noticed in the cockpit, on the
engineering channel, mid-approach:

    "I'm on the final. He's done a great job up to this point, but the diag
     says ASR he's on final... and the ASR part didn't take over."

The controller was behaving correctly. It had been handed:

    "he is on final, one zero miles. The talk-down is being transmitted
     automatically every mile -- do NOT repeat his range, heading or altitude."

So it stopped talking, as instructed, and the thing that was supposed to fill
that silence had an empty list.

WHY THE LIST WAS EMPTY, and it was a regression introduced hours before the
flight. `radar_fixes` matched a bracketed callsign in the RENDERED PROSE --
`362nd_sockeye [Sockeye] (F-16C_50)` -- so it could only find somebody the
picture had been drawn with bindings for. `fetch_radar` had just moved to
reading the tracks table and stopped passing them, every contact rendered
untagged, and the regex matched nothing:

    [RADAR: 362nd_sockeye (F-16C_50, manned): 10.9 nm on the 313 radial, ...]

No test caught it because no test drove the monitor thread, and the data path
was changed without exercising the thread that consumes it -- which is the 29
July audit's own central finding, committed by the person who quoted it.

THE FIX IS NOT THE BINDING. It is that the talk-down should never have been
reading identity out of a string it printed itself. The board already knows
`Sockeye -> 362nd_sockeye` on `radar` authority. These tests assert that it
works with NO tag in the prose at all, because that is the property that makes
the class of bug impossible rather than fixed.
"""

import unittest

from marshall.atc import agent_atc as A
from marshall.core import route as R

BATUMI = (41.609594, 41.600234)


def on_final(name="362nd_sockeye", nm_out=0.16):
    """A contact on the extended centreline, inbound, at circuit height.

    Placed by projecting from the field along the reciprocal of the final
    course, so it is genuinely on the approach rather than merely nearby.
    """
    from marshall.core import geo
    lat, lon = geo.project_true(BATUMI, (R.BATUMI_ASR.final_crs_true_measured
                                         + 180) % 360, nm_out * 60)
    return {"name": name, "label": name, "callsign": "", "type": "F-16C_50",
            "category": "airplane", "manned": True, "player": name,
            "on_ground": False, "lat": lat, "lon": lon, "alt_ft": 2000.0,
            "heading": R.BATUMI_ASR.final_crs_true_measured, "speed_kt": 250.0,
            "coalition": 3, "formation": ""}


def board_with(callsign="Sockeye", track="362nd_sockeye"):
    from marshall.atc.controller import Controller
    ctl = Controller(R.BATUMI_ASR)
    ctl.get(callsign)
    ctl.bind(callsign, track=track, owner="Batumi Approach")
    ctl.note_radar_contact(callsign, True)
    return ctl


class TestItFindsHimWithNoTagInThePicture(unittest.TestCase):
    """The exact condition of the failed sortie: correlated, and untagged."""

    def setUp(self):
        self.scope = A.Scope("", contacts=[on_final()], origin=BATUMI)
        self.ctl = board_with()

    def test_the_prose_really_has_no_tag(self):
        """The premise, asserted so this cannot go vacuous the way the old
        fixtures did -- they were written with the tag present, which is why a
        regression that removed it changed nothing they measured."""
        self.assertNotIn("[", str(self.scope))

    def test_and_he_is_found_anyway(self):
        got = A.radar_fixes(self.scope, R.BATUMI_ASR, self.ctl)
        self.assertEqual([cs for cs, _ in got], ["Sockeye"])

    def test_the_position_is_his_own(self):
        (_, pos), = A.radar_fixes(self.scope, R.BATUMI_ASR, self.ctl)
        self.assertLess(pos.range_nm, 12.0)
        self.assertIsNotNone(pos.alt_ft)

    def test_without_a_board_it_finds_nobody_rather_than_guessing(self):
        """The dry-run tools pass no board. An unidentified aircraft on final is
        not somebody we can talk to, and guessing produces a confident call to
        the wrong man."""
        self.assertEqual(A.radar_fixes(self.scope, R.BATUMI_ASR), [])


class TestItStillRefusesWhatItShould(unittest.TestCase):
    """Broadening where the identity comes from must not broaden WHO gets one."""

    def test_a_board_entry_with_no_track_is_not_talked_down(self):
        """Resolved from a filed strip, never seen on radar. He is real and
        unconfirmed, and reading ranges to a blip that might not be him is
        worse than saying nothing -- it sounds exactly as certain."""
        ctl = board_with()
        ctl.aircraft["Sockeye"].track = ""
        scope = A.Scope("", contacts=[on_final()], origin=BATUMI)
        self.assertEqual(A.radar_fixes(scope, R.BATUMI_ASR, ctl), [])

    def test_a_track_the_scope_cannot_see_is_not_talked_down(self):
        """On the board, bound, and radar has lost him. The row survives -- that
        is what `release_stale` is for -- but he is not being talked down to a
        position nobody can confirm."""
        ctl = board_with(track="362nd_somebody_else")
        scope = A.Scope("", contacts=[on_final()], origin=BATUMI)
        self.assertEqual(A.radar_fixes(scope, R.BATUMI_ASR, ctl), [])

    def test_an_empty_scope_finds_nobody(self):
        ctl = board_with()
        self.assertEqual(
            A.radar_fixes(A.Scope("", contacts=[], origin=BATUMI),
                          R.BATUMI_ASR, ctl), [])


if __name__ == "__main__":
    unittest.main()
