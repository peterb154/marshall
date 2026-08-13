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
        untracked panel showed the type for every contact on the scope.

        The column became a CARD when the board went portrait, so this asks
        what it always meant to ask -- that the page renders the field -- rather
        than for one particular `<th>`.
        """
        row = publish("Pony 1-1", "362nd_sockeye")["board"][0]
        self.assertEqual(row["type"], "P-51D-30-NA")
        self.assertIn("val(r.type)", diag.page())

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

    def test_the_page_shows_exactly_the_live_rows(self):
        """Counted against the card, not against a list of names.

        This used to name Q1 and Q9b. Q9b was flown on 10 August and struck --
        which is the card working exactly as intended -- and the test failed for
        it. A check that breaks when a pilot retires a row teaches people to
        stop retiring rows.
        """
        import re
        from pathlib import Path as _P
        card = (_P(__file__).resolve().parent.parent
                / "docs" / "TEST_PLAN.md").read_text()
        rendered = {letter: len(rows) for letter, _t, rows in self.sections()}
        for letter, n in rendered.items():
            if letter == "E":          # a different animal; see `sections`
                continue
            start = card.index(f"## {letter} — ")
            end = card.index("\n## ", start + 4)
            live = len([l for l in card[start:end].splitlines()
                        if re.match(r"^\|\s*\**[A-Z]\d+[a-z]?\**\s*\|", l)])
            self.assertEqual(n, live,
                             f"section {letter}: {n} rendered, {live} live on "
                             f"the card")

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


# --- the revamp: what the page could not say, and now must ------------------
#
#     "I feel like the diag page might need revamping. I feel like it might
#      have been lying a little to console me. I want to make sure that it
#      represents what atc is seeing and thinking so that I can rationalize why
#      something is happening"
#
# Each class below is one way it consoled: a decision recorded and never shown,
# a value nothing decided printed as an answer, one clock standing in for two,
# and a panel that was published and never forwarded.


def _with_build(fn):
    """Run `fn(build_dir)` against a redirected build dir.

    BOTH HALVES ARE REDIRECTED, which they were not until this file asked. The
    snapshot path is resolved per call and the RECORDER path was a module
    constant, so a test that pointed the build dir at a tempdir still read the
    live `build/logs` -- passing for as long as nobody was flying and failing
    the moment somebody was. See `diag._logs`.
    """
    old = config.BUILD_DIR
    with tempfile.TemporaryDirectory() as d:
        config.BUILD_DIR = Path(d)
        try:
            return fn(Path(d))
        finally:
            config.BUILD_DIR = old


def _recorder(root: Path, session: str, rows: list[dict]) -> None:
    import time as _t
    (root / "logs").mkdir(parents=True, exist_ok=True)
    with open(root / "logs" / f"flight-{session}.jsonl", "w") as fh:
        for i, r in enumerate(rows):
            fh.write(json.dumps({"t": _t.time() - (len(rows) - i), **r}) + "\n")


def _snapshot(root: Path, **fields) -> None:
    import time as _t
    (root / "control").mkdir(parents=True, exist_ok=True)
    (root / "control" / "state.json").write_text(
        json.dumps({"at": _t.time(), "board": [], "legend": {}, **fields}))


class TestTheReasonNothingHappened(unittest.TestCase):
    """The single biggest gap, and it was never a missing measurement.

    `watching_him` was written to record deciding NOTHING -- its docstring names
    the sortie that cost, a pilot flying from four to thirty miles with no
    handoff and three minutes of silent log -- and it writes a sentence saying
    which controller kept him and why:

        handoff/none  Georgia Center keeps him -- departure, 35 nm, inbound

    The page read the recorder for the CONVERSATION and dropped every one of
    these. So the answer to "why is nothing happening" was in the file the
    diagnostics page already had open, and the diagnostics page did not print
    it.
    """

    def state(self, rows):
        return _with_build(lambda d: (_recorder(d, "s", rows),
                                      diag.state(session="s"))[1])

    def test_a_handoff_that_did_not_fire_reaches_the_page(self):
        got = self.state([{"kind": "handoff/none", "callsign": "Sockeye",
                           "text": "Batumi Approach keeps him -- approach, "
                                   "20 nm, inbound"}])
        self.assertEqual(len(got["quiet"]), 1)
        self.assertIn("keeps him", got["quiet"][0]["text"])

    def test_every_kind_of_no_is_carried(self):
        """A refusal, a dropped figure, its repair and a release are all the
        same question asked of different machinery."""
        rows = [{"kind": k, "callsign": "Sockeye", "text": k}
                for k in ("not_voiced", "repaired", "released", "dropped",
                          "ship-to-ship", "atc/challenge", "atc/misnamed",
                          "flight/refused")]
        self.assertEqual(len(self.state(rows)["quiet"]), len(rows))

    def test_the_newest_is_first_and_carries_its_age(self):
        """`watching_him` records only when the answer CHANGES, so the top line
        is the decision still standing."""
        q = self.state([{"kind": "handoff/none", "callsign": "A", "text": "old"},
                        {"kind": "handoff/none", "callsign": "A",
                         "text": "new"}])["quiet"]
        self.assertEqual(q[0]["text"], "new")
        self.assertLess(q[0]["ago"], q[1]["ago"])

    def test_it_is_grouped_by_the_callsign_the_recorder_wrote(self):
        """Both sides of that lookup are the same variable in the bridge --
        `record(callsign=cs)` and `ctl.board()`'s key -- so there is nothing to
        fold, and no fifth copy of the name squasher goes near it."""
        got = self.state([{"kind": "handoff/none", "callsign": "Sockeye",
                           "text": "kept"}])
        self.assertEqual(got["quiet_by"]["Sockeye"][0]["text"], "kept")

    def test_a_record_matching_nothing_is_still_shown(self):
        """THE MISS IS VISIBLE RATHER THAN SWALLOWED. A card with no reasons is
        never the only account of a decision: the flat panel still has the line
        with the name the recorder actually wrote, which is the difference
        between a lookup that fails honestly and `|| {}`."""
        got = self.state([{"kind": "handoff/none", "callsign": "dagger56",
                           "text": "kept"}])
        self.assertNotIn("Dagger 5-6", got["quiet_by"])
        self.assertEqual(got["quiet"][0]["callsign"], "dagger56")

    def test_the_page_renders_them_on_the_card_and_in_the_panel(self):
        page = diag.page()
        self.assertIn("quiet_by", page)
        self.assertIn("not done", page)


class TestTwoClocksNeverOne(unittest.TestCase):
    """The page had one age, measuring the RECORDER, labelled and banner-ed as
    though it measured the bridge:

        "Recorder last moved 2 h ago -- this is the LAST sortie, not live
         state. Is the bridge running?"

    It was. It had published its snapshot one second earlier. The two sources
    fail in opposite directions -- a quiet frequency ages the recorder while the
    board is live, a stopped bridge ages the snapshot while somebody is still
    talking -- and one number cannot say which happened.
    """

    def test_both_ages_are_published_separately(self):
        def go(d):
            _snapshot(d, board=[{"callsign": "A"}])
            _recorder(d, "s", [{"kind": "pilot", "callsign": "A",
                                "transcript": "hello"}])
            return diag.state(session="s")
        got = _with_build(go)
        self.assertIsNotNone(got["sources"]["bridge"]["age"])
        self.assertIsNotNone(got["sources"]["recorder"]["age"])

    def test_a_missing_snapshot_ages_to_nothing_not_to_zero(self):
        got = _with_build(lambda d: (_recorder(d, "s", [{"kind": "pilot"}]),
                                     diag.state(session="s"))[1])
        self.assertIsNone(got["bridge_age"])
        self.assertIsNotNone(got["recorder_age"])

    def test_the_page_shows_the_bridge_clock(self):
        self.assertIn("bridge_age", diag.page())

    def test_and_every_panel_says_which_source_it_came_from(self):
        page = diag.page()
        self.assertIn("function stamp(", page)
        for panel in ("s-board", "s-quiet", "s-last", "s-plans"):
            with self.subTest(panel=panel):
                self.assertIn(panel, page)

    def test_the_verdict_can_say_it_does_not_know(self):
        """"board and radar agree" was printed for a bridge that had published
        no board at all -- the same fault as the ghost count that could never go
        red, one panel over."""
        self.assertIn("no board published", diag.page())


class TestNothingIsAnsweredThatNobodyAsked(unittest.TestCase):
    """Three columns printed a value that no longer exists anywhere.

    `flight_plans.approach` and `flight_plans.active` were deleted by migration
    031 -- "a plan does not name an arrival ... `active` was how the bridge used
    to read its own procedure out of a plan row" -- and the panel went on
    printing a header for each. `x.active` was undefined on every row, so every
    plan rendered "no", which is an ANSWER; `x.approach` was undefined and
    rendered through `esc('&mdash;')`, so a reader saw the literal characters
    "&mdash;" where a blank belonged.
    """

    def test_the_page_does_not_read_deleted_columns(self):
        page = diag.page()
        for gone in ("x.active", "x.approach"):
            with self.subTest(field=gone):
                self.assertNotIn(gone, page)

    def test_an_em_dash_is_never_escaped(self):
        """`esc` doing exactly its job to a string that should never have been
        near it. The dash is a character now, in one place."""
        import re
        for call in re.findall(r"esc\(([^()]*)\)", diag.page()):
            with self.subTest(call=call):
                self.assertNotIn("&mdash;", call)

    def test_a_missing_number_is_blank_and_never_zero(self):
        """The console-lying failure in miniature: an altitude nobody published
        shown as `0` reads as an aeroplane on the deck."""
        page = diag.page()
        self.assertIn("const val = v =>", page)
        self.assertIn("(v === null || v === undefined)", page)
        self.assertNotIn("|| 0", page)


class TestThePanelThatCouldNotDrawARow(unittest.TestCase):
    """`releases` is published by the bridge -- it is the only record that a
    board entry ever existed, since a release destroys its own evidence -- and
    `state()` never forwarded it. So the panel written to make nine wrong
    releases visible could not render one, for the same reason `ghosts` could
    not: the page asked for a key nothing ever gave it."""

    def test_releases_reach_the_page(self):
        def go(d):
            _snapshot(d, releases=[{"callsign": "Dagger 1-6", "track": "t",
                                    "scope": ["362nd_dagger"]}])
            return diag.state(session="none")
        self.assertEqual(_with_build(go)["releases"][0]["callsign"], "Dagger 1-6")


class TestTheCardSaysWhatTheBoardKnew(unittest.TestCase):
    """Two more facts the bridge published and the table had no column for.

    `sortie_phase` is the rung of the ladder -- the ONE input `handoff.py`
    reads to decide who has him next -- and the board printed only the
    separation phase beside it. `plan` is the strip he was resolved from, joined
    on by the bridge because it needs the identity registry to do it.
    """

    def test_the_card_renders_the_ladder_phase_and_the_strip(self):
        page = diag.page()
        self.assertIn("r.sortie_phase", page)
        self.assertIn("r.plan", page)

    def test_and_the_engine_s_own_view_of_radar_identification(self):
        """Not the same question as the `confirmed` pill, and able to disagree
        with it: this one decides whether he may take a place in the stack."""
        self.assertIn("r.identified", diag.page())


class TestTwoColumnsAreNotTwoSpellingsOfOneFact(unittest.TestCase):
    """#171. One card, one instant, two rows, and both of them correct:

        separation   UNKNOWN
        ladder       enroute

        "in this case, wasnt the aircraft ENROUTE and with GA Center? Why would
         separation say UNKNOWN?"

    `phase` is his place in the ARRIVAL QUEUE, which only checking in with the
    arrival controller enters; `sortie_phase` is the rung of the whole sortie
    that decides who has him next. The page printed neither question -- and
    printed the queue's "nothing has ever put this man in it" in the same word
    it uses for a fact that never arrived, on the one screen whose job is
    telling those two apart.

    ASSERTED AS A DISTINCTION, not as the presence of a string. The failure was
    never a missing label; it was two labels a reader had no reason to tell
    apart, so a test that a label exists would have passed on the broken page.
    """

    def column(self):
        return publish("Pony 1-1", "362nd_sockeye")["legend"]["column"]

    def test_each_column_says_which_question_it_answers(self):
        col = self.column()
        for key in ("phase", "sortie_phase"):
            with self.subTest(key=key):
                self.assertTrue(col[key]["label"])
                self.assertTrue(col[key]["gloss"])

    def test_and_the_two_have_no_word_in_common(self):
        """Two labels sharing a word is how one fact printed twice reads, which
        is the thing being fixed rather than a milder form of it."""
        col = self.column()
        first, second = (set(col[k]["label"].lower().split())
                         for k in ("phase", "sortie_phase"))
        self.assertEqual(first & second, set())
        self.assertNotEqual(col["phase"]["gloss"],
                            col["sortie_phase"]["gloss"])

    def test_the_state_nothing_has_ever_entered_is_not_called_unknown(self):
        """A real engine answer -- nobody has ever put this man in the queue --
        printed in the page's own word for ignorance."""
        said = self.column()["phase"]["values"]["UNKNOWN"]
        self.assertTrue(said)
        self.assertNotIn("unknown", said.lower())

    def test_and_the_queue_says_what_its_own_ENROUTE_means(self):
        """The collision that produced the question: `enroute` is a word BOTH
        columns can print, and it answers a different question in each."""
        said = self.column()["phase"]["values"]["ENROUTE"]
        self.assertTrue(said)
        self.assertNotEqual(said.lower(), "enroute")

    def test_the_page_holds_none_of_those_words_itself(self):
        """Same rule as every other meaning here: it arrives in the legend,
        from the thing that defines it."""
        page = diag.page()
        self.assertIn("LEGEND.column", page)
        for own in ("'separation'", "'ladder'", "'arrival queue'",
                    "'never admitted'", "'UNKNOWN'"):
            with self.subTest(own=own):
                self.assertNotIn(own, page)

    def test_and_renders_the_label_gloss_and_reading_it_is_given(self):
        """Publishing a value is not showing it -- the lesson this file keeps
        relearning from a pilot on the radio."""
        page = diag.page()
        for call in ("kvq('phase'", "kvq('sortie_phase'",
                     "qval('phase', r.phase)"):
            with self.subTest(call=call):
                self.assertIn(call, page)

    def test_a_value_with_no_reading_still_renders_blank(self):
        """#155 criterion 2 stays green. This may EXPLAIN a fact; it must never
        supply one, so anything unglossed falls through to the blank."""
        self.assertIn("return said ? esc(said) : val(v);", diag.page())


class TestPortrait(unittest.TestCase):
    """It is read on a knee, in a cockpit, by somebody with two seconds.

        "Yes, take liberty to re-imagine and revamp it. Ideally with a kneeboard
         portrait layout."

    The board was thirteen columns inside `<div class="scroll">` -- a class the
    stylesheet never defined, so it did not scroll either -- and this file's own
    comments admit what that cost: `intent` "scrolled out of sight, which reads
    exactly like a column that was never added".
    """

    def test_the_board_is_not_a_wide_table_in_a_scroller(self):
        page = diag.page()
        self.assertNotIn('class="scroll"', page)
        self.assertIn("function card(", page)

    def test_the_page_itself_never_scrolls_sideways(self):
        self.assertIn("overflow-x:hidden", diag.page())

    def test_a_card_row_has_exactly_two_columns(self):
        """Same rule the last-turn row learned the hard way: grid's answer to an
        extra child is a new implicit column sized to min-content."""
        page = diag.page()
        self.assertIn(".kv{display:grid;grid-template-columns:6.4rem minmax(0,1fr)",
                      page)
