"""A range must say what it is measured from — on the air and on the board.

    "I don't really care which airfield is the reference for center's bra,
     should probably be the flight plans destination airfield, but that doesn't
     matter as much as we show / say from where. Else that bra is senseless."

WHY THIS FILE EXISTS. `field_origin` has answered "where does this controller
measure from" since the first sortie, and the answer went nowhere except into
the arithmetic. Given a field it resolves that aerodrome; given NO field --
which is every Center, whose airspace is the whole theatre -- it falls through
to the loaded approach's beacon. So every range a Center has ever spoken was
measured from Batumi, nothing chose that, and no screen or transmission
anywhere said so.

That is the property worth fixing first, ahead of choosing a better field: an
unstated reference produces a real range to a real airport and sounds exactly
like a right answer, which is how #160 survived from the first sortie. A STATED
wrong reference is something a pilot catches in the air.

WHAT IS DELIBERATELY NOT TESTED HERE: that the datum is the RIGHT one. It is
not, yet -- a Center still measures from whichever arrival the bridge was
started on -- and the board is expected to print exactly that, in words, as
"BATUMI, the loaded approach". The bug printing its own name is the point.

Every NUMBER in this file is asserted UNCHANGED, against co-ordinates captured
before the change. `field_origin` picks exactly the point it always picked; what
is new is that it says which point that is and why.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from marshall import config
from marshall.atc import agent_atc as A
from marshall.atc import assembly, asr, decision, phrasebook
from marshall.core import geo, route as R, theatre as _th
from marshall.kneeboard import diag


def _fill_projected() -> dict:
    """The fix table the SIM pushes at bridge start, filled offline.

    `PROJECTED` is empty without a sim, and an empty table makes `field_origin`
    resolve nothing at all -- which would make every assertion below pass for
    the wrong reason. The published catalogue carries the sim's own
    projection (see `push_fixes`), so the same numbers are available here.
    """
    was = dict(A.PROJECTED)
    for f in _th.current().fixes:
        if getattr(f, "lat", None) is not None:
            A.PROJECTED.setdefault(f.name.upper(), (f.lat, f.lon))
    for fld in _th.current().fields:
        if getattr(fld, "lat", None) is not None:
            A.PROJECTED.setdefault(fld.name.upper(), (fld.lat, fld.lon))
    return was


class _Projected(unittest.TestCase):
    """Every test here needs the fix table and none of them may leak it."""

    def setUp(self):
        self._was = _fill_projected()

    def tearDown(self):
        A.PROJECTED.clear()
        A.PROJECTED.update(self._was)


# ------------------------------------------------------------------ the datum

class TheReferenceIsNamedAndJustified(_Projected):

    def test_a_field_controller_measures_from_his_own_field(self):
        d = A.field_origin(R.BATUMI_ASR, "Kobuleti")
        self.assertEqual(d.name, "KOBULETI")
        self.assertEqual(d.why, A.WHY_FIELD)

    def test_a_controller_with_no_field_falls_to_the_loaded_approach(self):
        """THE BUG, STATED. A Center has no aerodrome, so it lands on the
        arrival the bridge happened to be started with -- and now says so."""
        d = A.field_origin(R.BATUMI_ASR, "")
        self.assertEqual(d.name, "BATUMI")
        self.assertEqual(d.why, A.WHY_APPROACH)

    def test_and_the_same_center_moves_forty_miles_on_another_arrival(self):
        """Still true, still open, and now VISIBLE. Start the bridge on the
        Kobuleti ILS and every number Center speaks is measured somewhere
        else -- which was the whole of #160 and could not be seen from any
        screen or any transmission."""
        here = A.field_origin(R.BATUMI_ILS, "")
        there = A.field_origin(R.KOBULETI_ILS, "")
        self.assertNotEqual(here.name, there.name)
        self.assertEqual((here.why, there.why),
                         (A.WHY_APPROACH, A.WHY_APPROACH))

    def test_the_five_reasons_are_distinguishable(self):
        """The `why` is the audit trail, not decoration. Two of them reading
        the same string would make the board's account of itself useless."""
        whys = (A.WHY_DESTINATION, A.WHY_FIELD, A.WHY_APPROACH,
                A.WHY_BULLSEYE, A.WHY_NONE)
        self.assertEqual(len(set(whys)), len(whys))

    def test_an_unnamed_origin_is_falsy_and_says_nothing(self):
        """#109: an origin-less picture is not a picture. A NAMELESS one is
        the same failure -- a plausible number attributed to nobody."""
        d = A.Datum(point=(41.6, 41.6))
        self.assertFalse(d)
        self.assertEqual(d.spoken, "")
        self.assertEqual(d.published(), {})

    def test_it_is_spoken_as_a_man_says_his_own_field(self):
        self.assertEqual(A.field_origin(R.BATUMI_ASR, "").spoken, "from Batumi")


# EVERY ORIGIN THIS THEATRE CAN PRODUCE, CAPTURED BEFORE THE CHANGE and pinned
# as literals rather than as a comparison between two functions -- a check that
# asks the code what it does today can only ever agree with itself.
#
# Read off the running system at 8587385 across all four published procedures
# and every field a caller passes, including the two that resolve nothing.
BATUMI_POINT = (41.609594, 41.600234)          # the beacon, projected by the sim
KOBULETI_POINT = (41.929922, 41.863275)
BEFORE = {
    ("BATUMI_ASR", ""): BATUMI_POINT,
    ("BATUMI_ASR", "Batumi"): BATUMI_POINT,
    ("BATUMI_ASR", "batumi"): BATUMI_POINT,
    ("BATUMI_ASR", "Kobuleti"): KOBULETI_POINT,
    ("BATUMI_ASR", "KOBULETI"): KOBULETI_POINT,
    ("BATUMI_ASR", "Senaki"): BATUMI_POINT,
    ("BATUMI_ILS", ""): BATUMI_POINT,
    ("BATUMI_ILS", "Kobuleti"): KOBULETI_POINT,
    ("BATUMI_ILS", "Senaki"): BATUMI_POINT,
    ("BATUMI_APPROACH", ""): BATUMI_POINT,
    ("BATUMI_APPROACH", "Kobuleti"): KOBULETI_POINT,
    ("BATUMI_APPROACH", "Senaki"): BATUMI_POINT,
    # THE ONE THAT IS THE BUG. Same Center, same theatre, forty miles of
    # difference, and nothing but which arrival the bridge was started with.
    ("KOBULETI_ILS", ""): KOBULETI_POINT,
    ("KOBULETI_ILS", "Batumi"): BATUMI_POINT,
    ("KOBULETI_ILS", "batumi"): BATUMI_POINT,
    ("KOBULETI_ILS", "Kobuleti"): KOBULETI_POINT,
    ("KOBULETI_ILS", "Senaki"): KOBULETI_POINT,
}


class TheNumberDidNotMove(_Projected):
    """The reference was ADDED. Nothing was corrected, and this is what says so.

    `field_origin` is what every range in the system is computed against -- the
    picture, the board, the mile calls, and `CENTER_NM`, which decides when a
    pilot changes frequency. A changed answer here is a changed answer on the
    radio, so it is pinned to captured co-ordinates rather than asserted to be
    self-consistent.
    """

    def test_every_procedure_and_field_resolves_exactly_as_before(self):
        for (name, field), want in BEFORE.items():
            with self.subTest(procedure=name, field=field):
                self.assertEqual(
                    A.field_origin(getattr(R, name), field).point, want)

    def test_an_unresolvable_field_still_falls_through_to_the_approach(self):
        """Senaki has no projected fix, so the field branch misses and the old
        fallback runs -- and calls itself the loaded approach when it does."""
        got = A.field_origin(R.BATUMI_ASR, "Senaki")
        self.assertEqual(got.point, A.field_origin(R.BATUMI_ASR, "").point)
        self.assertEqual(got.why, A.WHY_APPROACH)

    def test_a_profile_that_names_nothing_gives_no_origin_and_no_datum(self):
        class Nothing:
            beacon = arrival_fix = outer_hold = None
        got = A.field_origin(Nothing(), "")
        self.assertIsNone(got.point)
        self.assertFalse(got)


# -------------------------------------------------------------------- say it

def _inbound(profile, nm: float, origin):
    """A contact `nm` miles out on the final approach course, pointing in."""
    back = (profile.final_crs_true + 180) % 360
    lat, lon = geo.project_true(origin, back, nm)
    return {"name": "Viper 1-4", "label": "362nd_Sockeye", "callsign": "",
            "type": "F-16C_50", "lat": lat, "lon": lon,
            "alt_ft": int(nm * 300) + 500, "heading": profile.final_crs_true,
            "speed_kt": 160.0, "manned": True,
            # DCS: 3 is blue. `_from_bullseye` refers a contact to its OWN
            # coalition's bullseye and answers nothing without one.
            "coalition": 3}


class ARangeOnTheAirNamesItsDatum(_Projected):
    """The half that was captured nowhere, and the more serious one.

    A controller who says "twenty three miles" and nothing else has said a
    number a pilot can neither use nor check -- and unlike the board, there is
    nothing to go back and look at.
    """

    def scope(self, profile, nm=12.0, named=True):
        d = A.field_origin(profile, "")
        return A.Scope("", contacts=[_inbound(profile, nm, d.point)],
                       origin=d.point, datum=d if named else None)

    def test_the_radar_block_states_what_it_was_measured_from(self):
        said = assembly.radar_datum(self.scope(R.BATUMI_ASR))
        self.assertIn("MEASURED FROM", said)
        self.assertIn("from Batumi", said)
        self.assertIn(A.WHY_APPROACH, said)

    def test_and_an_unnamed_origin_states_nothing_rather_than_guessing(self):
        """A guessed reference is worse than none: it is a real distance to a
        real airport, and it reads exactly like a right answer."""
        self.assertEqual(
            assembly.radar_datum(self.scope(R.BATUMI_ASR, named=False)), "")
        self.assertEqual(assembly.radar_datum(A.Scope("")), "")

    def test_the_guidance_directive_carries_the_datum_with_the_number(self):
        """It rides WITH the figure rather than being re-derived by the model.
        `guide()`'s range is the Position's range, and the Position was
        computed against the Scope's origin -- so this is the one place that
        knows both."""
        sc = self.scope(R.BATUMI_ASR)
        said = A.asr_context(R.BATUMI_ASR, sc, "Sockeye", track="Viper 1-4")
        self.assertIn("miles from Batumi", said)

    def test_and_says_only_the_range_when_the_origin_has_no_name(self):
        sc = self.scope(R.BATUMI_ASR, named=False)
        said = A.asr_context(R.BATUMI_ASR, sc, "Sockeye", track="Viper 1-4")
        self.assertIn("miles", said)
        self.assertNotIn("from Batumi", said)

    def test_a_handoff_says_where_the_boundary_range_was_measured_from(self):
        class Nxt:
            name, freq_mhz = "Georgia Center", 139.0
        fix = asr.Position(12.0, 100.0, 5000)
        d = A.field_origin(R.BATUMI_ASR, "")
        self.assertIn("12 miles from Batumi",
                      assembly.handoff_phrase(Nxt(), fix, d))

    def test_and_falls_back_to_the_words_it_always_used(self):
        """"out" is what this sentence has said since it was written. An
        absent datum must not silently change a transmission."""
        class Nxt:
            name, freq_mhz = "Georgia Center", 139.0
        fix = asr.Position(12.0, 100.0, 5000)
        self.assertIn("12 miles out", assembly.handoff_phrase(Nxt(), fix, None))


class ThePhrasebookWillNotSayAnUnattributedRange(unittest.TestCase):
    """"From the field" named a datum only while there was one field.

    With two aerodromes it names neither, and a Center -- which has no field
    at all -- was quoting Batumi. So the reference comes off the decision, and
    a range that cannot say where it is from is not said. The pilot loses
    nothing: this clause has never carried an instruction.
    """

    def vector(self, **over):
        return decision.Decision(kind="vector", to="Sockeye", heading_deg=130,
                                 range_nm=15.0, **over)

    def test_the_range_names_the_point_it_came_from(self):
        said = phrasebook.render(self.vector(datum="BATUMI"))
        self.assertIn("15 miles from Batumi", said)

    def test_and_a_datum_less_range_is_not_spoken_at_all(self):
        said = phrasebook.render(self.vector())
        self.assertIn("heading", said)
        self.assertNotIn("miles", said)
        self.assertNotIn("the field", said)

    def test_the_instruction_it_was_attached_to_is_untouched(self):
        """The range was always a rider on a turn. Dropping it may not drop
        the turn, which is the part a pilot flies."""
        self.assertEqual(phrasebook.render(self.vector()),
                         phrasebook.render(decision.Decision(
                             kind="vector", to="Sockeye", heading_deg=130)))


# ------------------------------------------------------------------- show it

class TheBoardPrintsWhereItMeasuredFrom(_Projected):
    """#155: a value with no source is not wrong, it is unfalsifiable.

        position   23.4 nm / 033   from BATUMI - the loaded approach
    """

    def publish(self, datum_named=True):
        d = A.field_origin(R.BATUMI_ASR, "")
        # TWO CONTACTS: one the board is working, one nobody is. They are the
        # two references this page has to keep apart.
        loose = dict(_inbound(R.BATUMI_ASR, 30.0, d.point),
                     name="Ural", label="Ural", coalition=3)
        sc = A.Scope("", contacts=[_inbound(R.BATUMI_ASR, 12.0, d.point),
                                   loose],
                     origin=d.point, datum=d if datum_named else None,
                     bullseye={"blue": {"lat": 42.186548, "lon": 41.678934}})

        class Ctl:
            def board(self):
                return [{"callsign": "Sockeye", "phase": "CLEARED",
                         "track": "Viper 1-4"}]

        bridge = A.Bridge()
        old = config.BUILD_DIR
        with tempfile.TemporaryDirectory() as tmp:
            config.BUILD_DIR = Path(tmp)
            try:
                A.publish_state(bridge, Ctl(), sc, "s")
                return json.loads(
                    (Path(tmp) / "control" / "state.json").read_text())
            finally:
                config.BUILD_DIR = old

    def test_the_board_row_carries_the_reference_beside_the_range(self):
        row = self.publish()["board"][0]
        self.assertIsNotNone(row["range_nm"])
        self.assertEqual(row["datum"], {"name": "BATUMI",
                                        "why": A.WHY_APPROACH})

    def test_the_untracked_contact_is_quoted_off_the_bullseye_and_says_so(self):
        """The one reference on the page that was already half honest: it
        named WHOSE bullseye and never said that a bullseye is what these two
        numbers are off."""
        loose = [u for u in self.publish()["scope"] if not u["controlled"]]
        self.assertTrue(loose)
        self.assertEqual(loose[0]["bulls"]["name"], "BULLSEYE")
        self.assertEqual(loose[0]["bulls"]["why"], A.WHY_BULLSEYE)

    def test_a_nameless_origin_publishes_no_datum_key_value(self):
        """A blank fact renders blank -- never `0`, never a plausible
        substitute -- and the only reliable way to say blank to a renderer is
        to send it nothing."""
        row = self.publish(datum_named=False)["board"][0]
        self.assertIsNone(row["datum"])


class ThePageActuallyDrawsIt(unittest.TestCase):
    """Publishing a value is not the same as showing it -- see
    `TestTheOriginBadgeIsActuallyRendered`, which is the same lesson learned
    from a pilot on the radio."""

    def test_the_position_row_renders_the_published_datum(self):
        self.assertIn("datum(r.datum)", diag.page())

    def test_the_bullseye_row_does_too(self):
        self.assertIn("datum(b)", diag.page())

    def test_the_page_prints_the_reason_and_does_not_choose_one(self):
        page = diag.page()
        self.assertIn("d.why", page)
        # QUOTED, the way the page's other vocabulary check reads it: the
        # comments explain the feature and the CODE must contain no reference
        # of its own. A page that knows one field's name can print it when the
        # bridge sent another.
        for guess in ("'BATUMI'", "'KOBULETI'", "'the loaded approach'",
                      "'BULLSEYE'", '"BULLSEYE"'):
            with self.subTest(guess=guess):
                self.assertNotIn(guess, page)


if __name__ == "__main__":
    unittest.main()
