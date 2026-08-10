"""The diagnostics page renders; it does not decide.

    "The page should be pretty stupid - it should be subscribing to upstream
     data -- the page should never natively know anything about player names,
     types of phases, static frequencies."

It used to decide three things it had no business deciding: it replayed the
flight roster from recorder events, it worked out for itself whether a board
entry was a ghost, and it re-parsed the radar prose a third time. All three are
a surface acting as an authority, and the ghost check was wrong in exactly the
way audit finding 1.1 was wrong -- comparing a spoken label against the name
radar prints, so a pilot labelled "Pony 1-1" whose scope line reads
"362nd_sockeye" matched nothing and was reported as a ghost while sitting in
front of the aerial.

The bridge knows all of it, because it is the thing that decided. It publishes
a snapshot and the page draws it. These tests followed the logic to where it
went: what `publish_state` puts in the snapshot, and that the page holds no
domain vocabulary of its own.
"""

import json
import tempfile
import unittest
from pathlib import Path

from marshall import config
from marshall.atc import agent_atc as A
from marshall.kneeboard import diag

# A real scope line, in the shape the director actually renders: the label is
# the PLAYER name, the bracketed tag is a callsign something has correlated,
# and neither is the spoken callsign the board is keyed on.
SCOPE = ("362nd_sockeye [Pony 1-1] (P-51D-30-NA, manned): 8.0 nm on the 281 "
         "radial, 4,659 ft, heading 026, 180 knots | "
         "362nd_Andre-1 (P-51D-30-NA, manned): 12.0 nm on the 300 radial, "
         "5,000 ft, heading 062, 200 knots")


def publish(callsign, track, scope=SCOPE, board=None):
    """Run the bridge's publisher against a temporary build dir."""

    class Ctl:
        def board(self):
            return board or [{"callsign": callsign, "phase": "CLEARED"}]

    bridge = A.Bridge()
    if callsign:
        bridge.identity.by_guid["g"] = A.identity.Identity(
            callsign=callsign, track=track, authority="radar", why="")
    old = config.BUILD_DIR
    with tempfile.TemporaryDirectory() as d:
        config.BUILD_DIR = Path(d)
        try:
            A.publish_state(bridge, Ctl(), scope, "s")
            return json.loads((Path(d) / "control" / "state.json").read_text())
        finally:
            config.BUILD_DIR = old


class TestWhatTheBridgeSaysAboutAnEntry(unittest.TestCase):
    """Three answers, not two. Ghost was always too blunt a word."""

    def test_a_track_on_the_scope_is_confirmed_by_radar(self):
        """The case the page got wrong. He is labelled "Pony 1-1" and radar
        prints "362nd_sockeye" -- no name matching can bridge those, and it
        does not have to, because the TRACK matches."""
        got = publish("Pony 1-1", "362nd_sockeye")
        self.assertEqual(got["board"][0]["confirmed"], "radar")

    def test_no_track_at_all_is_CLAIMED_not_a_ghost(self):
        """Rungs 2 and 3 of the ladder -- a filed strip, or the roster --
        resolve a callsign with no track. He is real and unconfirmed, and
        calling that a ghost would cry wolf on every guest."""
        got = publish("Pony 1-1", "")
        self.assertEqual(got["board"][0]["confirmed"], "claimed")

    def test_a_track_radar_cannot_see_is_UNSEEN(self):
        """The real ghost: something accounted for him once, nothing does now.
        This is the one worth a red row."""
        got = publish("Falcon 1-1", "362nd_falcon")
        self.assertEqual(got["board"][0]["confirmed"], "unseen")

    def test_the_board_carries_the_track_it_was_joined_on(self):
        """`controller.board()` cannot supply this -- the engine is blind and
        has never heard of a track -- so it is joined on at the one place that
        knows both."""
        self.assertEqual(publish("Pony 1-1", "362nd_sockeye")["board"][0]["track"],
                         "362nd_sockeye")


class TestTheMeaningTravelsWithTheValues(unittest.TestCase):
    """The page must not know that `radar` outranks `plan`, or which recorder
    kinds belong to which stage. It will be wrong the first time either changes
    and nobody thinks to look in the JavaScript."""

    def test_the_legend_is_published(self):
        legend = publish("Pony 1-1", "362nd_sockeye")["legend"]
        self.assertEqual(legend["confirmed"]["unseen"], "bad")
        self.assertEqual(legend["confirmed"]["radar"], "ok")
        self.assertEqual(legend["authority"]["radar"], "ok")
        self.assertEqual(legend["authority"][""], "bad")

    def test_every_recorder_kind_the_trail_shows_has_a_stage(self):
        legend = publish("Pony 1-1", "362nd_sockeye")["legend"]
        for kind in ("controller", "atc/pilot", "flight/joined", "dropped"):
            with self.subTest(kind=kind):
                self.assertIn("stage", legend["kind"][kind])

    def test_scope_markers_are_data_not_flags(self):
        """`manned` and `on the ground` arrive as tags the page prints
        verbatim, so a new marker needs no page change."""
        got = publish("Pony 1-1", "362nd_sockeye")
        tags = {t for u in got["scope"] for t in u["tags"]}
        self.assertIn("manned", tags)


class TestThePageHoldsNoDomainVocabulary(unittest.TestCase):
    """Guarded by reading the page, because this is the kind of thing that
    creeps back one convenient literal at a time."""

    def test_no_domain_words_in_the_javascript(self):
        page = diag.page()
        for word in ("'radar'", "'plan'", "'roster'", "manned",
                     "'final'", "'holding'", "124.0"):
            with self.subTest(word=word):
                self.assertNotIn(word, page)


class TestThePageDoesNotJoin(unittest.TestCase):
    """It renders rows. It does not relate one panel to another.

    `board()` opened by looking its own row up in the scope list --

        const u = d.scope.find(x => key(x.name) === key(r.track)) || {};

    -- which is the join from `HANDOFF-board.md`, in JavaScript, done with the
    page's own fourth copy of the name squasher. When it missed, `|| {}` turned
    a broken lookup into four empty columns, and an empty column on a
    diagnostics page reads as "the sim did not say", not as "this page cannot
    find him".

    A surface that joins is a surface that can disagree with the thing it is
    displaying, which defeats the entire purpose of having one.
    """

    def test_the_page_cannot_squash_a_name(self):
        """The specific tool of the specific crime. There are three copies of
        this in Python and there is no longer one in the browser."""
        self.assertNotIn("replace(/[^a-z0-9]/g", diag.page())

    def test_the_page_does_not_look_a_row_up_in_another_panel(self):
        page = diag.page()
        for probe in ("d.scope.find", "(d.scope || []).find", "scope.find("):
            with self.subTest(probe=probe):
                self.assertNotIn(probe, page)

    def test_the_board_row_arrives_with_its_own_position(self):
        """Which is what makes the join unnecessary rather than merely banned.
        The bridge always sent these; the page re-derived them anyway."""
        row = publish("Pony 1-1", "362nd_sockeye")["board"][0]
        for field in ("heading", "alt_ft", "speed_kt", "range_nm"):
            with self.subTest(field=field):
                self.assertIsNotNone(row[field])

    def test_the_board_says_what_he_is_flying(self):
        """It carried the type all along and the table had no column for it, so
        the board named a man and never said what he was in -- while the
        untracked panel showed the type for every contact on the scope."""
        row = publish("Pony 1-1", "362nd_sockeye")["board"][0]
        self.assertEqual(row["type"], "P-51D-30-NA")
        self.assertIn("<th>type</th>", diag.page())

    def test_and_its_own_owner_state_and_intent(self):
        """Three facts from three authorities, published separately so the page
        never has to decide which one 'doing' means."""
        row = publish("Pony 1-1", "362nd_sockeye")["board"][0]
        for field in ("owner", "state", "intent"):
            with self.subTest(field=field):
                self.assertIn(field, row)


class TestAnIndicatorThatCannotGoRed(unittest.TestCase):
    """The verdict banner asked for `d.ghosts`. Nothing ever published it.

    So `(d.ghosts || []).length` was 0 on every render the field ever had, and
    the page said "board and radar agree" for its whole life -- while capable of
    displaying a ghost row immediately underneath. This is the shape `check.py`
    is built around: a check that is always green reads exactly like one that
    passed.
    """

    def test_a_ghost_is_published_and_counted(self):
        got = publish("Pony 1-1", "not-on-this-scope")
        self.assertEqual(got["board"][0]["confirmed"], "unseen")
        self.assertEqual(got["ghosts"], ["Pony 1-1"])

    def test_and_a_healthy_board_reports_none(self):
        self.assertEqual(publish("Pony 1-1", "362nd_sockeye")["ghosts"], [])


class TestItSurvivesAnEmptySystem(unittest.TestCase):
    def test_no_snapshot_and_no_recorder_is_not_an_error(self):
        """A page that 500s when nothing is flying is a page nobody trusts when
        something is."""
        old = config.BUILD_DIR
        with tempfile.TemporaryDirectory() as d:
            config.BUILD_DIR = Path(d)
            try:
                st = diag.state(session="does-not-exist")
            finally:
                config.BUILD_DIR = old
        self.assertEqual(st["board"], [])
        self.assertEqual(st["ghosts"], [])
        self.assertEqual(st["flights"], [])


if __name__ == "__main__":
    unittest.main()


class TestWhichBrainSaidIt(unittest.TestCase):
    """The two-brain seam, made visible on the page.

    The deterministic half owns separation and geometry precisely so a model
    cannot invent them -- but the model is what SPEAKS, so the guarantee only
    holds if it voices the engine's instruction rather than rewording it. A
    controller who turns "turn left heading one six nine, maintain four
    thousand" into "come left a bit and hold your altitude" has quietly taken
    the decision back, and until now nothing anywhere reported it.
    """

    def test_origin_is_published_for_every_kind_the_trail_shows(self):
        """Three origins, not two: the loop's own GUARDS refuse and correct
        before either brain sees the call. "You are Sockeye, use that callsign"
        is a guard speaking, and reading it as the controller is how a
        mechanical correction gets mistaken for judgement."""
        got = publish("Pony 1-1", "362nd_sockeye")["legend"]["origin"]
        self.assertEqual(got["controller"], "engine")
        self.assertEqual(got["asr"], "engine")
        self.assertEqual(got["atc/pilot"], "agent")
        self.assertEqual(got["atc/misnamed"], "guard")

    def test_the_page_does_not_decide_which_brain_is_which(self):
        self.assertNotIn("'engine'", diag.page())
        self.assertNotIn("'deterministic'", diag.page())

    def _turn(self, engine, agent):
        return diag._voiced([{"kind": "controller", "text": engine},
                             {"kind": "atc/pilot", "text": agent}])

    def test_spoken_digits_count_as_voiced(self):
        """The agent says "one six niner"; the engine issued 169. Comparing
        them raw would report a paraphrase on every correct turn, and an alarm
        that is always on is one nobody reads."""
        self.assertTrue(self._turn("turn left heading 169, maintain 4000",
                                   "turn left heading one six niner, "
                                   "maintain four thousand")["ok"])

    def test_compound_altitudes_too(self):
        self.assertTrue(self._turn("descend and maintain 2500",
                                   "descend and maintain two thousand five "
                                   "hundred")["ok"])

    def test_a_paraphrase_is_caught(self):
        got = self._turn("turn left heading 169, maintain 4000",
                         "come left a little and hold your altitude")
        self.assertFalse(got["ok"])
        self.assertEqual(got["missing"], ["169", "4000"])

    def test_and_so_is_a_single_dropped_number(self):
        """The dangerous one. The heading is voiced and the ALTITUDE is not, so
        it sounds like a correct instruction and is half of one."""
        got = self._turn("turn left heading 169, maintain 4000",
                         "turn left heading one six nine")
        self.assertEqual(got["missing"], ["4000"])

    def test_a_turn_the_engine_said_nothing_about_is_not_judged(self):
        """No directive, no verdict. Most conversation is not an instruction."""
        self.assertEqual(diag._voiced([{"kind": "atc/pilot",
                                        "text": "Sockeye, go ahead."}]), {})


class TestTheOriginBadgeIsActuallyRendered(unittest.TestCase):
    """Publishing the legend is not the same as showing it.

    The origin legend shipped, the CSS for the badges shipped, and the line
    that RENDERS them did not -- a two-assertion edit whose second assertion
    failed, so the file was never written while an earlier edit in the same
    session landed fine. Everything looked right: the tests passed, the data
    was in `/diag.json`, and the page simply did not draw it. A pilot found it
    on the radio:

        "on the diag page under the last turn stage by stage, I don't see
         attribution and chain of thought"

    Testing that a value is PUBLISHED says nothing about whether it is USED, so
    this reads the page.
    """

    def test_the_page_reads_the_origin_legend(self):
        self.assertIn("LEGEND.origin", diag.page())

    def test_and_has_somewhere_to_put_it(self):
        for origin in ("org-engine", "org-agent", "org-guard"):
            with self.subTest(origin=origin):
                self.assertIn(origin, diag.page())

    def test_the_voiced_verdict_is_rendered_too(self):
        self.assertIn("PARAPHRASED", diag.page())
        self.assertIn("SILENT", diag.page())


class TestTheLastTurnRowIsLaidOutRight(unittest.TestCase):
    """A pilot sent a screenshot: the stage rows were a hundred-pixel ribbon of
    single words down the left of the page, under a badge stretched across the
    full width.

    `.trail li` is a two-column grid -- stage label, then value. The origin pill
    was emitted as a THIRD child, so it took the 1fr column for itself and the
    text landed in an implicit fourth column, which grid sizes to min-content.

    THE EXISTING TESTS ALL PASSED. They ask whether the pill is rendered, and it
    was; nothing asked WHERE. Only `decide` and `speak` carry an origin, so the
    two rows without one -- `heard` and `who` -- went on looking perfect, which
    is why a broken page still read as a working one at a glance.

    This parses the template the page actually ships rather than mirroring it,
    because a Python copy of the JS is two things that can disagree.
    """

    def row(self) -> str:
        """The trail row's markup, with every optional part present."""
        import re
        js = diag.page()
        start = js.index('out += `<li><span class="k">')
        end = js.index("'</span></li>';", start) + len("'</span></li>';")
        chunk = js[start:end]
        # Every literal segment, in order: the backtick templates and the one
        # quoted tail. Taking each conditional's truthy branch gives the row as
        # it renders when the turn has an origin AND a timing -- which is the
        # case that broke.
        parts = re.findall(r"`([^`]*)`|'([^']*)'", chunk)
        html = "".join(a or b for a, b in parts)
        return re.sub(r"\$\{[^}]*\}", "X", html)

    def test_the_stage_row_has_exactly_two_columns(self):
        from html.parser import HTMLParser

        class Kids(HTMLParser):
            depth = 0
            def __init__(self):
                super().__init__()
                self.top = []
            def handle_starttag(self, tag, attrs):
                if tag == "li":
                    self.depth = 1
                    return
                if self.depth == 1:
                    self.top.append(dict(attrs).get("class", ""))
                if self.depth:
                    self.depth += 1
            def handle_endtag(self, tag):
                if self.depth:
                    self.depth -= 1

        k = Kids()
        k.feed(self.row())
        self.assertEqual(len(k.top), 2,
                         f"a two-column grid row has {len(k.top)} children: "
                         f"{k.top} -- anything past the second lands in an "
                         f"implicit min-content column")

    def test_the_origin_pill_is_inside_the_value(self):
        """Not beside it. The `who` row above already does this correctly and
        is the pattern."""
        row = self.row()
        pill = row.index('class="pill org-')
        value = row.index('<span class="X">')
        self.assertLess(value, pill,
                        "the pill is emitted before the value span, which "
                        "makes it a sibling and steals the value's column")

    def test_the_value_column_cannot_be_widened_by_long_text(self):
        """minmax(0,1fr), not 1fr. A grid track defaults to a min-content floor,
        so one long unbroken transcript pushes the row wider than the page."""
        self.assertIn("minmax(0,1fr)", diag.page())

    def test_anything_extra_still_lands_in_the_value_column(self):
        """The durable half. Emitting the pill in the right place fixes today's
        row; this makes the NEXT child added to a stage row land in column two
        instead of inventing a column of its own."""
        self.assertIn(".trail li>*:not(.k){grid-column:2}", diag.page())


if __name__ == "__main__":
    unittest.main()


class TheFlightCardActuallyReachesTheCockpit(unittest.TestCase):
    """The card a pilot reads must be the card that was written.

        "Where will I find Q1-Q9 plus S10-S12 and H20-H21 -- they arent on the
         flighttest kneeboard"

    They were not. TWO faults, and between them the kneeboard was showing six
    pages of fifteen and 47 rows of 120.

    ONE: the row pattern matched only a bare `| H4 |`, so every section written
    since 2 August was invisible -- Q, R, S and T rendered ZERO rows between
    them. That is #60 exactly, in a second tool: that issue fixed the same
    blindness in `tools/issue_sync.py`, which REPORTS on the card, and nobody
    looked at the page a pilot actually reads.

    TWO: eleven sections had no GUID, and a section with no GUID is not
    published at all. The builder said so on every run -- "section Q has no
    GUID and will NOT appear" -- into a container start-up log nobody reads.
    A loud warning in a place nobody looks is a silent one.
    """

    def sections(self):
        from marshall.kneeboard import flighttest
        return flighttest.sections()

    def test_every_section_has_rows(self):
        for letter, title, rows in self.sections():
            self.assertTrue(rows, f"section {letter} ({title}) renders no rows")

    def test_the_bold_sections_are_there(self):
        # Q, R, S and T are written with bold IDs. The card opens by telling a
        # pilot to fly Q FIRST.
        got = {letter: [r["id"] for r in rows]
               for letter, _t, rows in self.sections()}
        for letter in ("Q", "R", "S", "T"):
            self.assertIn(letter, got)
            self.assertTrue(got[letter], f"section {letter} is empty")
        self.assertIn("Q1", got["Q"])
        self.assertIn("Q9b", got["Q"])

    def test_row_ids_carry_no_markup(self):
        # A pilot says "S10 failed", not "asterisk asterisk S 10".
        for letter, _t, rows in self.sections():
            for r in rows:
                self.assertNotIn("*", r["id"], f"{letter}: {r['id']!r}")
                self.assertNotIn("~", r["id"], f"{letter}: {r['id']!r}")

    def test_retired_rows_are_not_shown(self):
        # Striking a row through is what takes it off the cockpit list; the
        # script stays as the regression record. Section E is "known broken,
        # do not report these as new" and had swallowed twelve retired rows
        # because its slice ran to end of file.
        got = {letter: [r["id"] for r in rows]
               for letter, _t, rows in self.sections()}
        self.assertEqual(got.get("E"), ["E1", "E2"])

    def test_every_section_is_published(self):
        from marshall.kneeboard import flighttest
        letters = {letter for letter, _t, _r in self.sections()}
        missing = [x for x in letters if x not in flighttest.GUIDS]
        self.assertEqual(missing, [],
                         f"sections {missing} have no GUID and will not appear "
                         f"on the kneeboard at all")

    def test_every_section_has_a_tab_label(self):
        from marshall.kneeboard import flighttest
        letters = {letter for letter, _t, _r in self.sections()}
        missing = [x for x in letters if x not in flighttest.SHORT]
        self.assertEqual(missing, [], f"sections {missing} have no tab label")

    def test_no_two_sections_share_a_guid(self):
        # OpenKneeboard remembers the page a pilot was on; a reused identifier
        # drops him somewhere he did not choose.
        from marshall.kneeboard import flighttest
        vals = list(flighttest.GUIDS.values())
        self.assertEqual(len(vals), len(set(vals)))
