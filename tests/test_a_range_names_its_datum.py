"""A range must say what it is measured from — on the air and on the board.

    "I don't really care which airfield is the reference for center's bra,
     should probably be the flight plans destination airfield, but that doesn't
     matter as much as we show / say from where. Else that bra is senseless."

WHY THIS FILE EXISTS. `field_origin` has answered "where does this controller
measure from" since the first sortie, and the answer went nowhere except into
the arithmetic. Given a field it resolves that aerodrome; given NO field --
which is every Center, whose airspace is the whole theatre -- it fell through
to THE LOADED APPROACH's beacon. So every range a Center has ever spoken was
measured from Batumi, nothing chose that, and no screen or transmission
anywhere said so.

That was the property worth fixing first, ahead of choosing a better field: an
unstated reference produces a real range to a real airport and sounds exactly
like a right answer, which is how #160 survived from the first sortie. A STATED
wrong reference is something a pilot catches in the air.

BOTH HALVES ARE NOW CLOSED, and the second one is #162. The datum SAYS what it
is (that was this file's original subject) and it no longer MOVES: the
fallback is the sortie's arrival aerodrome, a fact about the map, rather than
whichever procedure the process was started on. The two rows in `BEFORE` that
changed are exactly the two that used to depend on the loaded approach, and
they are called out where they sit -- a Center measured from Kobuleti because
somebody had started the radio on the Kobuleti ILS, and the same Center on the
same map measured from Batumi otherwise. Forty miles, no other difference.

WHAT IS STILL DELIBERATELY NOT TESTED HERE: that the datum is the BEST one.
`WHY_DESTINATION` -- the field HIS plan ends at -- is what a controller
working an aeroplane should eventually get, and choosing it moves a number
that `CENTER_NM` is computed against. That is its own commit and its own
ghost flight.

Every OTHER number in this file is asserted UNCHANGED against co-ordinates
captured before the change.
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

import tests.theatre as _T


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
        d = A.field_origin("Kobuleti")
        self.assertEqual(d.name, "KOBULETI")
        self.assertEqual(d.why, A.WHY_FIELD)

    def test_a_controller_with_no_field_falls_to_the_arrival_aerodrome(self):
        """A Center has no aerodrome of its own, so it measures from where
        the traffic is GOING -- and says so. It used to land on the arrival
        the process was started with, which is a different sentence with the
        same answer on this map and a different one on the next."""
        d = A.field_origin("")
        self.assertEqual(d.name, _th.current().arrival.upper())
        self.assertEqual(d.why, A.WHY_ARRIVAL)

    def test_and_the_same_center_no_longer_moves_forty_miles(self):
        """CLOSED, and this is the assertion that says so. Starting the
        radio on the Kobuleti ILS used to move every number Center spoke
        forty miles, with no other change -- the whole of #160, invisible
        from any screen and any transmission.

        There is nothing left to start it ON. The function takes a place, so
        the only way to get two answers is to ask about two places, and
        asking twice about none gives one answer by construction."""
        answers = {(A.field_origin("").name, A.field_origin("").why)
                   for _ in range(3)}
        self.assertEqual(len(answers), 1, "the datum moved under a Center")
        (name, why), = answers
        self.assertEqual(why, A.WHY_ARRIVAL)
        self.assertEqual(name, _th.current().arrival.upper())

    def test_the_five_reasons_are_distinguishable(self):
        """The `why` is the audit trail, not decoration. Two of them reading
        the same string would make the board's account of itself useless."""
        whys = (A.WHY_DESTINATION, A.WHY_FIELD, A.WHY_ARRIVAL,
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
        self.assertEqual(A.field_origin("").spoken, "from Batumi")


# EVERY ORIGIN THIS THEATRE CAN PRODUCE, CAPTURED BEFORE THE CHANGE and pinned
# as literals rather than as a comparison between two functions -- a check that
# asks the code what it does today can only ever agree with itself.
#
# Read off the running system at 8587385 across all four published procedures
# and every field a caller passes, including the two that resolve nothing.
BATUMI_POINT = (41.609594, 41.600234)          # the beacon, projected by the sim
KOBULETI_POINT = (41.929922, 41.863275)
# KEYED ON THE FIELD ALONE, because that is now the only input. It was keyed
# `(procedure, field)` and half the point of the table was that the first
# element changed the answer. It cannot: `field_origin` takes a place. [#162]
BEFORE = {
    "Batumi": BATUMI_POINT,
    "batumi": BATUMI_POINT,
    "Kobuleti": KOBULETI_POINT,
    "KOBULETI": KOBULETI_POINT,
    # NO FIELD -- every Center. It read BATUMI under three procedures and
    # KOBULETI under the fourth, which is the whole of #160, and it is now
    # the arrival aerodrome under all of them.
    "": BATUMI_POINT,
    # AN AERODROME WITH NO PROJECTED FIX. Falls past the field branch to the
    # same fallback. Read KOBULETI on a Kobuleti-ILS process and BATUMI on
    # any other; there is one answer now.
    "Senaki": BATUMI_POINT,
}


class TheNumberDidNotMove(_Projected):
    """The reference was ADDED. Nothing was corrected, and this is what says so.

    `field_origin` is what every range in the system is computed against -- the
    picture, the board, the mile calls, and `CENTER_NM`, which decides when a
    pilot changes frequency. A changed answer here is a changed answer on the
    radio, so it is pinned to captured co-ordinates rather than asserted to be
    self-consistent.
    """

    def test_every_field_resolves_exactly_as_before(self):
        for field, want in BEFORE.items():
            with self.subTest(field=field):
                self.assertEqual(A.field_origin(field).point, want)

    def test_an_unresolvable_field_still_falls_through(self):
        """Senaki has no projected fix, so the field branch misses and the
        fallback runs -- and names the arrival aerodrome when it does."""
        got = A.field_origin("Senaki")
        self.assertEqual(got.point, A.field_origin("").point)
        self.assertEqual(got.why, A.WHY_ARRIVAL)

    def test_with_nothing_projected_there_is_no_origin_and_no_datum(self):
        """The empty-table case, which used to be spelt as a profile naming
        no fixes. There is no profile to name anything now, so the only way
        to have no datum is to have projected no places -- which is a bridge
        that started with no sim and no theatre file, and it must render
        blank rather than guess."""
        was = dict(A.PROJECTED)
        A.PROJECTED.clear()
        try:
            got = A.field_origin("")
            self.assertIsNone(got.point)
            self.assertFalse(got)
        finally:
            A.PROJECTED.update(was)


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
        d = A.field_origin("")
        return A.Scope("", contacts=[_inbound(profile, nm, d.point)],
                       origin=d.point, datum=d if named else None)

    def test_the_radar_block_states_what_it_was_measured_from(self):
        said = assembly.radar_datum(self.scope(R.BATUMI_ASR))
        self.assertIn("MEASURED FROM", said)
        self.assertIn("from Batumi", said)
        self.assertIn(A.WHY_ARRIVAL, said)

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
        said = A.asr_context(_T.flying(R.BATUMI_ASR, "Sockeye"), sc, "Sockeye", track="Viper 1-4")
        self.assertIn("miles from Batumi", said)

    def test_and_says_only_the_range_when_the_origin_has_no_name(self):
        sc = self.scope(R.BATUMI_ASR, named=False)
        said = A.asr_context(_T.flying(R.BATUMI_ASR, "Sockeye"), sc, "Sockeye", track="Viper 1-4")
        self.assertIn("miles", said)
        self.assertNotIn("from Batumi", said)

    def test_a_handoff_says_where_the_boundary_range_was_measured_from(self):
        class Nxt:
            name, freq_mhz = "Georgia Center", 139.0
        fix = asr.Position(12.0, 100.0, 5000)
        d = A.field_origin("")
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
        d = A.field_origin("")
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
                                        "why": A.WHY_ARRIVAL})

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


class TheBoardMeasuresFromWhoeverIsWorkingHim(_Projected):
    """#169. A datum is one per `Scope`, and a board is not.

    `field_origin` takes the SPEAKING controller's field, and only the
    transmission path ever passed one. The metronome tick -- which is what most
    refreshes are -- fetches its picture with no field at all and publishes
    that one fallback for every row on the page.

    IT IS NOT A DISPLAY NICETY, and the issue's own "harmless today" was too
    kind. It is true only of a Center, who has no field and would have used the
    fallback anyway. With two aerodromes up, the four Kobuleti seats work
    aeroplanes twenty miles from the point this page quoted them against:

        Quiver 7-1, five miles west of Kobuleti, worked by Kobuleti Tower
            before   20.4 nm on 019, from BATUMI, the loaded approach
            after     5.0 nm on 270, from KOBULETI, his field

    Every number in the first line is real and belongs to another airport,
    which is the same shape as `station_for`, `channels_for` and `field_origin`
    before each of them took a field.

    WHAT IS DELIBERATELY NOT FIXED HERE: which field a FIELDLESS seat chooses.
    A Center still falls back to the loaded approach and still says so in
    words, because pointing him at his man's destination moves `CENTER_NM` and
    therefore moves a handoff -- that is #160 and a ghost flight's worth of
    verification. This is the plumbing that makes #160 visible instead of
    silent: a per-row reference, resolved from whoever is working the row.
    """

    def publish(self, board, place=(("Kobuleti", 270.0, 5.0),
                                    ("Batumi", 90.0, 20.0))):
        """A METRONOME TICK: the picture fetched with NO FIELD AT ALL.

        That is what `scheduler()` publishes, so it is what the board is
        rendered from whenever nobody has just spoken.
        """
        tick = A.field_origin("")
        contacts = []
        for row, (fld, brg, nm) in zip(board, place):
            lat, lon = geo.project_true(
                A.field_origin(fld).point, brg, nm)
            contacts.append({"name": row["track"], "label": row["track"],
                             "callsign": "", "type": "F-16C_50",
                             "lat": lat, "lon": lon, "alt_ft": 3000,
                             "heading": 90, "speed_kt": 250.0,
                             "manned": True, "coalition": 3})
        sc = A.Scope("", contacts=contacts, origin=tick.point, datum=tick)

        class Ctl:
            profile = R.BATUMI_ILS

            def board(self):
                return board

        bridge = A.Bridge()
        was = config.BUILD_DIR
        with tempfile.TemporaryDirectory() as tmp:
            config.BUILD_DIR = Path(tmp)
            try:
                A.publish_state(bridge, Ctl(), sc, "s")
                got = json.loads(
                    (Path(tmp) / "control" / "state.json").read_text())
            finally:
                config.BUILD_DIR = was
        return {r["callsign"]: r for r in got["board"]}

    def two_seats(self, **over):
        return self.publish([
            {**{"callsign": "Quiver 7-1", "track": "Quiver 7-1",
                "phase": "UNKNOWN", "owner": "Kobuleti Tower"}, **over},
            {"callsign": "Hoover 1-1", "track": "Hoover 1-1",
             "phase": "UNKNOWN", "owner": "Georgia Center"}])

    def test_a_row_worked_by_the_other_aerodrome_is_quoted_from_it(self):
        """The seat that has him is Kobuleti Tower, and nobody spoke on this
        tick -- so the reference is his, not the picture's."""
        row = self.two_seats()["Quiver 7-1"]
        self.assertEqual(row["datum"], {"name": "KOBULETI",
                                        "why": A.WHY_FIELD})

    def test_and_the_number_MOVES_WITH_THE_NAME(self):
        """The half that makes it honest rather than decorative.

        `Datum.point` is the lat/lon the arithmetic actually used, "so the name
        can never drift from the number: they are one object". A row quoted
        against another point must be RE-MEASURED there -- a relabelled number
        is confidently wrong, which is worse than the fallback it replaces.
        """
        row = self.two_seats()["Quiver 7-1"]
        self.assertAlmostEqual(row["range_nm"], 5.0, places=1)
        self.assertAlmostEqual(row["radial"], 270, delta=1)
        # And emphatically not the answer the tick's own picture holds.
        self.assertNotAlmostEqual(row["range_nm"], 20.4, places=1)

    def test_two_rows_on_one_board_can_name_different_references(self):
        """THE REASON A FIELD CANNOT SIMPLY BE PASSED INTO THE TICK. One
        picture is one origin, and the board shows aeroplanes worked by seats
        at different aerodromes -- so handing the fetch a field would only pick
        a different single wrong answer."""
        got = self.two_seats()
        self.assertNotEqual(got["Quiver 7-1"]["datum"]["name"],
                            got["Hoover 1-1"]["datum"]["name"])

    def test_a_fieldless_seat_still_falls_back_and_still_says_so(self):
        """#160, untouched and still visible. A Center has no aerodrome, so he
        lands on whichever arrival this radio was started with -- and the board
        goes on printing the bug's own name until #160 points him at the field
        his man is flying to."""
        row = self.two_seats()["Hoover 1-1"]
        self.assertEqual(row["datum"], {"name": "BATUMI",
                                        "why": A.WHY_ARRIVAL})
        self.assertAlmostEqual(row["range_nm"], 20.0, places=1)

    def test_a_seat_nothing_can_resolve_keeps_the_pictures_own_answer(self):
        """Never a guess. With no owner there is nobody whose reference this
        could be, and the number WAS computed against the picture's origin --
        so that is what it must go on saying."""
        row = self.two_seats(owner="")["Quiver 7-1"]
        self.assertEqual(row["datum"], {"name": "BATUMI",
                                        "why": A.WHY_ARRIVAL})
        self.assertAlmostEqual(row["range_nm"], 20.4, places=1)

    def test_and_a_row_with_no_position_to_re_measure_is_not_RELABELLED(self):
        """The failure this must never produce: a name that does not describe
        the number beside it. If the contact cannot be found there is nothing
        to re-measure, so the picture's reference stands."""
        row = self.publish([{"callsign": "Quiver 7-1", "track": "not-on-radar",
                             "phase": "UNKNOWN", "owner": "Kobuleti Tower"}],
                           place=[])["Quiver 7-1"]
        self.assertIsNone(row["range_nm"])
        self.assertEqual(row["datum"], {"name": "BATUMI",
                                        "why": A.WHY_ARRIVAL})


if __name__ == "__main__":
    unittest.main()
