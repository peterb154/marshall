""""Nothing has told us" was written down three times and read as "he is flying".

#149, found by the audit for #146's siblings. The database has THREE answers to
"is he in the air" -- the sim says up, the sim says down, and the sweep has not
reached him -- and every boundary between `tracks` and the thing that moves an
aeroplane collapsed them into two. Four separate places said so in a comment
while discarding it in the expression underneath:

    feed/tracks.py     "NULL here means the sweep has not run yet, and that is
                        not the same as 'airborne'"
    core/scope.py      "NULL means nobody has asked yet, which is a third
                        answer -- and reading it as 'airborne' is what told a
                        parked Mustang it was flying"
    atc/identity.py    "False means either 'airborne' or 'nothing has told us',
                        and the caller keeps its own fallback"
    feed/dcs.py        "does NOT know the sim's ground/landed events"

No caller kept a fallback, because there was nothing left to keep one on.
`on_ground` alone maps NULL and TRUE onto the same False, so by the time a
`Unit` reached anybody `not on_ground` was the only test available -- and it
answers True for an aeroplane nobody has looked at.

WHO ACTED ON IT. `handoff_on_the_event` is the FIRST rung of `next_controller`'s
cascade, so it answers before anything that knows about arrivals is consulted:

    if not unit.on_ground and role == "tower":
        return profile.station_for("approach", field=fld)

Its own docstring closed with "Silent unless the sim has actually said so ...
this must not fire on the second". It fired on the second. The only guard was
`unit is None` -- not on the picture at all -- which was sufficient while the
flag came from land/takeoff events and stopped being sufficient the day it moved
to a swept column that starts NULL.

The window is one sweep, and it is widest exactly where it is worst: a fresh
mission, a restart, an aeroplane spawning on a ramp while a controller is being
asked who has him. #114 is the same column read wrongly in the other direction
and cost a whole map's ground ladder.

`handoff._airborne` was fixed for this shape on 13 August and its docstring is
the rule: "he is flying, POSITIVELY -- not merely 'not known to be down'".
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from marshall.atc import agent_atc as A
from marshall.atc import identity
from marshall.core import route as R

ROOT = Path(__file__).resolve().parent.parent

# The tower he would be handed away from, and the field he is sitting on.
FIELD = "Batumi"


def contact(**kw) -> dict:
    """One row of the structured picture, as `core/scope.contacts` builds it."""
    c = {"name": "362nd_sockeye", "label": "362nd_sockeye", "callsign": "",
         "type": "F-16C_50", "category": "airplane", "manned": True,
         "player": "362nd_sockeye", "lat": None, "lon": None, "alt_ft": None,
         "heading": None, "speed_kt": None, "coalition": 2, "formation": ""}
    c.update(kw)
    return c


# The three answers the column can hold, spelled as a contact dict carries them.
FLYING = contact(in_air=True, on_ground=False)
DOWN = contact(in_air=False, on_ground=True)
NOT_KNOWN = contact(in_air=None, on_ground=False)


def scope(*contacts) -> A.Scope:
    return A.Scope("", contacts=list(contacts))


class TheThirdAnswerSurvivesTheJourney(unittest.TestCase):
    """Acceptance 1: distinguishable at every layer between `tracks` and
    `handoff_on_the_event`.

    The old shape passed a test like this trivially and wrongly -- both of the
    two states it had were reachable, so nothing looked broken. The question is
    whether the THIRD one arrives, which is why every case here is a triple.
    """

    def unit(self, c: dict):
        got = identity.units_on(scope(c))
        self.assertEqual(len(got), 1)
        return got[0]

    def test_the_scope_reader_carries_all_three(self):
        for c, want in ((FLYING, True), (DOWN, False), (NOT_KNOWN, None)):
            with self.subTest(in_air=c["in_air"]):
                self.assertIs(self.unit(c).in_air, want)

    def test_and_on_ground_still_means_exactly_what_it_meant(self):
        """It is the convenience, not the answer, and it must not have moved --
        every existing caller reads it and it has always meant THE SIM SAYS HE
        IS DOWN."""
        self.assertIs(self.unit(FLYING).on_ground, False)
        self.assertIs(self.unit(DOWN).on_ground, True)
        self.assertIs(self.unit(NOT_KNOWN).on_ground, False)

    def test_a_contact_that_says_nothing_says_nothing(self):
        """A dict with no `in_air` key has not told us either. Deriving it from
        `not on_ground` here would rebuild the collapse one line further down
        the pipe, where it would be harder to find."""
        bare = contact()
        bare.pop("in_air", None)
        self.assertIsNone(self.unit(bare).in_air)

    def test_the_deleted_producer_stayed_deleted(self):
        """`feed/tracks.contacts` must go on delegating, not build its own.

        It is the reader that was deleted; if it grows a dict again the table
        has two producers and this whole family of bug is back.
        """
        src = (ROOT / "src" / "marshall" / "feed" / "tracks.py").read_text()
        tree = ast.parse(src)
        node = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "contacts")
        keys = {k.value for d in ast.walk(node)
                if isinstance(d, ast.Dict) for k in d.keys
                if isinstance(k, ast.Constant)}
        self.assertNotIn("on_ground", keys,
                         "it is a delegate; building the picture here is the "
                         "duplication that was removed")
        body = ast.get_source_segment(src, node) or ""
        self.assertIn("scope", body,
                      "it must reach core.scope for the picture")

    def test_every_producer_of_a_picture_emits_it(self):
        """Acceptance 4, and the reason it is a source check: these three build
        the dict in three files and only one of them can be run without a
        database or a sim. A producer that quietly stops emitting `in_air`
        hands every consumer a `None` that means "not known" and is really
        "nobody wrote it down"."""
        # TWO PRODUCERS NOW, NOT THREE. `feed/tracks.contacts` built the dict
        # from hand-written PostGIS that returned exactly what
        # `core/scope.contacts` returns through the `Track` model -- proven
        # identical on the same row -- so the table had two readers and a rule
        # applied to one was not applied to the other. That is how a track
        # nobody had seen for two hours stayed a live contact. It delegates
        # now, so it is no longer a place `in_air` can be dropped; the
        # invariant is enforced where the dict is actually built.
        want = {"marshall/core/scope.py": "contacts",
                "marshall/feed/dcs.py": "contacts_live"}
        for rel, fn in want.items():
            with self.subTest(producer=f"{rel}:{fn}"):
                tree = ast.parse((ROOT / "src" / rel).read_text())
                node = next(n for n in ast.walk(tree)
                            if isinstance(n, ast.FunctionDef) and n.name == fn)
                keys = {k.value for d in ast.walk(node)
                        if isinstance(d, ast.Dict) for k in d.keys
                        if isinstance(k, ast.Constant)}
                self.assertIn("on_ground", keys)     # the dict we mean
                self.assertIn("in_air", keys,
                              "a picture that carries `on_ground` and not "
                              "`in_air` has three answers and two states")


class NobodyIsHandedOverOnAnAbsence(unittest.TestCase):
    """Acceptance 2. Tower does not offer Approach to an aeroplane nothing has
    reported a ground state for.

    The wrong answer is always plausible, which is why this was invisible: a
    real controller, on a real frequency, for a man who may well be sitting on
    a ramp with the canopy open.
    """

    def setUp(self):
        self.tower = R.station_for("tower", field=FIELD)
        self.approach = R.station_for("approach", field=FIELD)

    def next_for(self, c: dict, me):
        return A.handoff_on_the_event(scope(c), "362nd_sockeye", me,
                                      R.BATUMI_ILS)

    def test_an_unreported_aeroplane_is_not_taken_off_tower(self):
        self.assertIsNone(self.next_for(NOT_KNOWN, self.tower))

    def test_but_one_the_sim_says_is_flying_still_is(self):
        """The case the branch exists FOR, and it must survive: he rotated,
        Tower owns the runway rather than the departure."""
        got = self.next_for(FLYING, self.tower)
        self.assertIsNotNone(got)
        self.assertIn("approach", got.name.lower())

    def test_and_landing_still_ends_the_approach(self):
        """The other direction is untouched -- it was already positive
        evidence, because `on_ground` True can only come from the sim saying
        so."""
        got = self.next_for(DOWN, self.approach)
        self.assertIsNotNone(got)
        self.assertIn("tower", got.name.lower())

    def test_the_prose_fallback_behaves_as_it_always_did(self):
        """A picture with no contacts in it is parsed out of English, and the
        English has two states by construction: "on the ground" is printed or
        it is not. Turning every regex-parsed aircraft into an unknown would
        disarm this branch for the one case that is already degraded."""
        flying = ("362nd_sockeye [Sockeye] (F-16C_50, manned): 2.0 nm on the "
                  "112 radial, 1,200 ft, heading 112, 220 knots")
        got = A.handoff_on_the_event(flying, "362nd_sockeye", self.tower,
                                     R.BATUMI_ILS)
        self.assertIsNotNone(got)
        self.assertIn("approach", got.name.lower())


class TheBoardDoesNotSayAirborneOnAnAbsence(unittest.TestCase):
    """Acceptance 3, and the same fault one function along.

    `sim_state` already refused to answer for an aeroplane radar had stopped
    seeing -- `TestAVanishedAeroplaneIsNotFlying`, and the comment for it is
    still there. It answered "airborne" for one radar had never reported,
    which is the identical absence from the other end of the sortie.
    """

    def test_a_unit_nothing_has_reported_has_no_state(self):
        self.assertEqual(A.sim_state(scope(NOT_KNOWN), "362nd_sockeye"), "")

    def test_the_sim_saying_so_is_enough(self):
        self.assertEqual(A.sim_state(scope(FLYING), "362nd_sockeye"),
                         "airborne")

    def test_and_so_is_radar_seeing_him_up_and_moving(self):
        """The geometry fallback is a real observation and must keep answering:
        `is_on_the_ground` saying False about an aircraft it can SEE is the
        altitude-and-speed test speaking, not an absence. This is the path
        every existing caller takes."""
        up = contact(in_air=None, on_ground=False, lat=41.75, lon=41.45,
                     alt_ft=4000.0, speed_kt=250.0, heading=90.0)
        sc = A.Scope("", contacts=[up], origin=(41.609594, 41.600234))
        fix = A.radar_fix_by_track(sc, "362nd_sockeye")
        self.assertIsNotNone(fix)
        self.assertEqual(A.sim_state(sc, "362nd_sockeye", fix), "airborne")

    def test_down_still_reports_the_ground(self):
        self.assertEqual(A.sim_state(scope(DOWN), "362nd_sockeye"),
                         "on the ground")

    def test_off_the_scope_altogether_is_still_silent(self):
        """The guard that was already there. Both absences answer the same way
        and they always should have."""
        self.assertEqual(A.sim_state(scope(), "362nd_sockeye"), "")


class TheStripSaysWhichOfTheThreeItIs(unittest.TestCase):
    """The last layer, and the page was ready for it two weeks early.

    `/diag` renders `on_ground` as three states -- "airborne", "on the ground",
    or an em dash -- with its own comment saying "we do not know" must not
    render as "parked". It was never handed the middle one: the row published
    None only when the track was MISSING, and False for a unit on the scope
    whose ground state nothing knew.
    """

    def row(self, c: dict | None):
        units = {A._key_name(c["name"]): identity.units_on(scope(c))[0]} \
            if c else {}
        return A._plan_row({"label": "PONY11"}, "Pony 1-1", {},
                           {"Pony 1-1": "362nd_sockeye"}, units)

    def test_an_aeroplane_nothing_has_reported_renders_as_the_dash(self):
        self.assertIsNone(self.row(NOT_KNOWN)["on_ground"])

    def test_flying_and_down_are_unchanged(self):
        self.assertIs(self.row(FLYING)["on_ground"], False)
        self.assertIs(self.row(DOWN)["on_ground"], True)

    def test_and_a_track_radar_cannot_see_is_still_none(self):
        self.assertIsNone(self.row(None)["on_ground"])


if __name__ == "__main__":
    unittest.main()
