"""Configuration comes from files, and the three scopes stay apart.

#137. The first slice of it: how the radio SAYS things and what it expects to
HEAR were both Python.

    "all of that should be configuration stored in the database, not code ...
     I feel like we are still under-leveraging the database as a source of
     truth"
    "I could be convinced that configuration can be structured files/objects
     that are loaded into memory rather than stored in the database - just not
     intermixed with code."

The bug this prevents is not "a constant in a file". It is THREE KINDS OF FACT
IN ONE DICT: `SAY_AS` held "niner" (aviation English, true everywhere),
"Kobuleti" (a name on one map) and "Sockeye" (one pilot's callsign on one
evening) as though they were the same kind of thing. So a new pilot was
mispronounced on the air until somebody edited Python and restarted the
bridge -- which is #97, and which makes "works with any pilot" impossible.
"""

from __future__ import annotations

import os
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from marshall.core import catalogue
from marshall.radio import stt, tts


class Sandbox(unittest.TestCase):
    """Each test gets its own config directory, so none of them reads the repo's."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        (self.dir / "theatres").mkdir()
        self._env = {k: os.environ.get(k)
                     for k in ("MARSHALL_CONFIG_DIR", "MARSHALL_THEATRE")}
        os.environ["MARSHALL_CONFIG_DIR"] = str(self.dir)
        os.environ["MARSHALL_THEATRE"] = "testmap"
        catalogue.reload()
        catalogue.known_callsigns.cache_clear()
        self.addCleanup(self._restore)

    def _restore(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        catalogue.reload()
        catalogue.known_callsigns.cache_clear()
        self._tmp.cleanup()


    def assertLogsToStdout(self, needle):
        """The loaders print rather than raise where they degrade, so the test
        has to read stdout to prove the operator was told."""
        import contextlib
        import io
        outer = self

        class Ctx:
            def __enter__(self):
                self.buf = io.StringIO()
                self.cm = contextlib.redirect_stdout(self.buf)
                self.cm.__enter__()
                return self

            def __exit__(self, *exc):
                self.cm.__exit__(*exc)
                outer.assertIn(needle, self.buf.getvalue())
                return False
        return Ctx()

    def write(self, rel, text):
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text), encoding="utf-8")
        catalogue.reload()
        catalogue.known_callsigns.cache_clear()


class TheThreeScopesStayApart(Sandbox):

    def setUp(self):
        super().setUp()
        self.write("speech.toml", """
            [terms]
            nine = "niner"
            [recogniser]
            phrases = ["say again"]
        """)
        self.write("theatres/testmap.toml", """
            [pronunciation]
            Kobuleti = "koh-boo-lay-tee"
            [recogniser]
            phrases = ["Kobuleti"]
        """)

    def test_universal_terms_apply_on_every_map(self):
        self.assertEqual(catalogue.speech()["nine"], "niner")

    def test_the_map_contributes_its_own_names(self):
        self.assertEqual(catalogue.speech()["Kobuleti"], "koh-boo-lay-tee")

    def test_another_map_does_not_get_this_one_s_names(self):
        """Priming or respelling with another map's names is worse than doing
        neither: it biases toward words that cannot occur."""
        self.write("theatres/othermap.toml", "[pronunciation]\n")
        os.environ["MARSHALL_THEATRE"] = "othermap"
        catalogue.reload()
        self.assertNotIn("Kobuleti", catalogue.speech())
        self.assertEqual(catalogue.speech()["nine"], "niner", "aviation is aviation")

    def test_a_callsign_is_the_sortie_s_and_is_passed_in(self):
        said = catalogue.speech({"Nomad": "no-mad"})
        self.assertEqual(said["Nomad"], "no-mad")
        self.assertNotIn("Nomad", catalogue.speech(),
                         "one pilot's name is not a fact about the map")

    def test_a_map_may_not_redefine_aviation_english(self):
        """Precedence is universal < theatre < sortie, so a pilot may fix how
        his own name is said; a map may not quietly turn 'niner' back into
        'nine' for everybody."""
        said = catalogue.speech({"nine": "NINE"})
        self.assertEqual(said["nine"], "NINE", "the sortie is the last word")


class WhatTheRadioSays(Sandbox):

    def test_pronounce_reads_the_files(self):
        self.write("speech.toml", '[terms]\nthree = "tree"\n')
        self.write("theatres/testmap.toml", '[pronunciation]\nBatumi = "bah-too-mee"\n')
        self.assertEqual(tts.pronounce("Runway three at Batumi", callsigns={}),
                         "Runway tree at Bah-too-mee")

    def test_a_new_pilot_needs_no_code_change(self):
        """#97 in one line. Adding a callsign used to mean editing Python."""
        self.write("speech.toml", "[terms]\n")
        self.write("theatres/testmap.toml", "[pronunciation]\n")
        self.assertEqual(tts.pronounce("Nomad two nine", {"Nomad": "no-mad"}),
                         "No-mad two nine")

    def test_capitalisation_is_preserved(self):
        self.write("speech.toml", '[terms]\nreadback = "reed back"\n')
        self.write("theatres/testmap.toml", "[pronunciation]\n")
        self.assertEqual(tts.pronounce("Readback correct", callsigns={}),
                         "Reed back correct")

    def test_no_config_is_an_accent_and_not_a_silence(self):
        """The one place a missing file is survivable, and it is a judgement:
        a controller with no table has an accent, a controller who cannot start
        is silence on every frequency."""
        self.assertEqual(tts.pronounce("Runway three", callsigns={}),
                         "Runway three")


class WhatTheRadioExpectsToHear(Sandbox):

    def test_the_default_prompt_names_no_sortie(self):
        """It used to be a 1944 Mustang sortie at Batumi, as the default
        argument of `transcribe` -- so every caller who passed no prompt primed
        for Mustangs while an F-16 flew."""
        self.write("speech.toml", '[recogniser]\nphrases = ["say again"]\n')
        self.write("theatres/testmap.toml",
                   '[recogniser]\nphrases = ["Kobuleti"]\n')
        got = stt.default_prompt()
        self.assertIn("say again", got)
        self.assertIn("Kobuleti", got)
        for gone in ("Mustang", "Pony", "Batumi", "Oscar Sierra"):
            self.assertNotIn(gone, got)

    def test_the_live_prompt_puts_the_man_on_the_radio_first(self):
        """A prompt is a budget -- Whisper weighs the start of it more."""
        self.write("speech.toml", '[recogniser]\nphrases = ["say again"]\n')
        self.write("theatres/testmap.toml", "[recogniser]\nphrases = []\n")
        got = stt.domain_prompt(callsigns=["Nomad two nine"], field="Kobuleti")
        self.assertLess(got.index("Nomad two nine"), got.index("say again"))

    def test_no_default_aerodrome(self):
        self.write("speech.toml", "[recogniser]\nphrases = []\n")
        self.write("theatres/testmap.toml", "[recogniser]\nphrases = []\n")
        self.assertNotIn("Batumi", stt.domain_prompt())

    def test_nothing_is_primed_twice(self):
        self.write("speech.toml", '[recogniser]\nphrases = ["Kobuleti"]\n')
        self.write("theatres/testmap.toml",
                   '[recogniser]\nphrases = ["kobuleti"]\n')
        self.assertEqual(catalogue.recogniser_phrases().count("Kobuleti"), 1)


class ABadFileIsLoudRatherThanEmpty(Sandbox):
    """A controller running on silently-empty configuration says numbers that
    are merely plausible, which is the shape of every foundational bug this
    month."""

    def test_a_missing_theatre_is_an_error_not_a_shrug(self):
        self.write("speech.toml", "[terms]\n")
        with self.assertRaises(FileNotFoundError):
            catalogue._theatre("nosuchmap")

    def test_malformed_toml_names_the_file(self):
        self.write("speech.toml", "[terms\nbroken = ")
        with self.assertRaises(ValueError) as e:
            catalogue._universal()
        self.assertIn("speech.toml", str(e.exception))

    def test_a_mistyped_SECTION_is_caught_and_named(self):
        """VALID TOML IS NOT VALID CONFIGURATION, and the gap between them was
        silent. Both of these parse clean:

            [recognizer]        the American spelling
            [pronounciation]    a misspelling nobody would see

        and the bridge came up with no pronunciation table and an unprimed
        recogniser, saying nothing about either.
        """
        self.write("speech.toml", '[terms]\nnine = "niner"\n'
                                  '[recognizer]\nphrases = ["say again"]\n')
        with self.assertRaises(ValueError) as e:
            catalogue._universal()
        self.assertIn("recognizer", str(e.exception))
        self.assertIn("speech.toml", str(e.exception))

    def test_a_mistyped_theatre_section_too(self):
        self.write("speech.toml", "[terms]\n")
        self.write("theatres/testmap.toml",
                   '[pronounciation]\nBatumi = "bah-too-mee"\n')
        with self.assertRaises(ValueError) as e:
            catalogue._theatre("testmap")
        self.assertIn("pronounciation", str(e.exception))

    def test_every_fault_is_reported_at_once(self):
        """One pass to fix a theatre, not one restart per typo."""
        self.write("speech.toml",
                   '[terms]\n[recognizer]\nphrases = []\n[extras]\nx = 1\n')
        with self.assertRaises(ValueError) as e:
            catalogue._universal()
        self.assertIn("recognizer", str(e.exception))
        self.assertIn("extras", str(e.exception))

    def test_the_words_themselves_stay_free_form(self):
        """The SECTIONS are schema; the WORDS are data. Adding a respelling
        must never require a code change -- that is the whole point."""
        self.write("speech.toml", '[terms]\nwilco = "will co"\n')
        self.write("theatres/testmap.toml", "[pronunciation]\n")
        self.assertEqual(catalogue.speech()["wilco"], "will co")

    def test_a_mistyped_callsigns_file_is_reported_not_swallowed(self):
        """Absent is fine; WRONG is not. A file somebody wrote and mistyped is
        a different thing from no file, and must not impersonate one."""
        self.write("callsigns.toml", '[pronounciation]\nNomad = "no-mad"\n')
        with self.assertLogsToStdout("callsigns.toml"):
            self.assertEqual(catalogue.known_callsigns(), {})


class TheRepoSOwnConfigurationLoads(unittest.TestCase):
    """Not a sandbox -- the shipped files, which nothing else would catch."""

    def setUp(self):
        catalogue.reload()
        self.addCleanup(catalogue.reload)

    def test_every_shipped_theatre_parses(self):
        for p in sorted((catalogue.root() / "theatres").glob("*.toml")):
            with self.subTest(theatre=p.stem):
                got = catalogue._read(p)
                self.assertIsInstance(got.get("pronunciation", {}), dict)

    def test_the_universal_table_is_aviation_and_not_a_map(self):
        """The regression that started this: no place name, no callsign."""
        terms = catalogue._read(catalogue.root() / "speech.toml")["terms"]
        for leaked in ("Batumi", "Kobuleti", "Sockeye", "Nellis", "Pony"):
            self.assertNotIn(leaked, terms)


if __name__ == "__main__":
    unittest.main()


class ThePublishedCatalogueIsCitable(unittest.TestCase):
    """The shipped Caucasus catalogue, and what may be in it.

    `theatre.fixes` used to be built by scraping every module-level `Fix` out
    of `route.py` -- a fact about which Python file a name sits in, not about
    whether anybody can look it up. So the 362nd's own turning points were
    published to every controller in every sortie as though they were navaids:

        "we deleted the domino flight plan that had feet wet… where on earth
         did that come from. It shouldn't be in the database from a flight plan
         as a private fix and it's definitely not a public fix."
    """

    def setUp(self):
        catalogue.reload()
        self.addCleanup(catalogue.reload)

    def test_the_sorties_own_turning_points_are_not_published(self):
        names = {f.name for f in catalogue.published_fixes("caucasus")}
        for mine in ("FEET WET", "INGRESS", "EGRESS", "TSUTSNVATI", "REHEARSAL"):
            self.assertNotIn(mine, names)

    def test_the_aerodromes_and_the_plate_fix_are(self):
        names = {f.name for f in catalogue.published_fixes("caucasus")}
        self.assertEqual(names, {"BATUMI", "KOBULETI", "KUTAISI", "INITIAL"})

    def test_every_published_fix_cites_a_source(self):
        """Reference data is seeded, never authored. A fix nobody can cite is
        one somebody invented."""
        for f in catalogue.published_fixes("caucasus"):
            with self.subTest(fix=f.name):
                self.assertTrue(f.source.strip(), f"{f.name} cites nothing")

    def test_a_fix_with_no_position_is_refused(self):
        """Required, not defaulted: a fix at 0,0 is in the Gulf of Guinea and
        every range from it is a real-looking number belonging nowhere."""
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            catalogue.PublishedFix(name="NOWHERE", x=1, z=2, source="test")


class GeometryWithoutARunningSim(unittest.TestCase):
    """What the stored projection buys, and it is the point of the exercise.

    Until now the only thing that could turn a fix into a position was
    `coord.LOtoLL` over gRPC at bridge start. So "does this terminal area
    contain its own approach" -- #139, the 11 nm circle around a procedure that
    starts at 22 -- could not be asked in a test, in a tool, or at all without
    the server up.
    """

    def setUp(self):
        catalogue.reload()
        self.addCleanup(catalogue.reload)

    def test_the_theatre_carries_positions_offline(self):
        from marshall.core import theatre as T
        for f in T.published_fixes():
            with self.subTest(fix=f.name):
                self.assertIsNotNone(f.lat)
                self.assertIsNotNone(f.lon)

    def test_the_distance_that_proves_139(self):
        """Batumi's ILS holds at KOBULETI. Its terminal area is published as
        min(25, nearest_field/2) -- and the two fields are 22 nm apart, so the
        area is ELEVEN miles and the procedure begins at twenty-two.

        Computed here from the files alone, which is the whole point: this
        assertion could not have been written last week.
        """
        from marshall.core import geo
        at = {f.name: f for f in catalogue.published_fixes("caucasus")}
        nm, _ = geo.range_bearing_true(
            (at["BATUMI"].lat, at["BATUMI"].lon),
            at["KOBULETI"].lat, at["KOBULETI"].lon)
        self.assertAlmostEqual(nm, 22.0, delta=1.5)
        from marshall.core import airspace
        self.assertLess(min(airspace.TERMINAL_NM, nm / 2.0), nm,
                        "the published area does not reach its own outer hold")


class TheTwoSourcesOfPositionAreMERGED(unittest.TestCase):
    """One table, two sources, and the second must not silently win.

    Caught on a running bridge and not by the suite: the published table came
    back holding FEET WET, INGRESS and EGRESS -- the sortie's own turning
    points -- and not one aerodrome. `push_fixes` collected the configured
    coordinates, then the sim branch did `out = {}` before adding its own.

    Exactly the replace-versus-merge that cost a whole catalogue in #129. Two
    sources for one table is the shape; it will happen again, so it gets a test
    rather than a comment.
    """

    def test_configured_fixes_survive_the_sim_branch(self):
        from unittest import mock

        from marshall.atc import agent_atc as A
        from marshall.core import route as R

        configured = R.Fix("BATUMI", "OS", -355811, 617386, 132.0,
                           lat=41.6096, lon=41.6002)
        sortie_only = R.Fix("FEET WET", "", -355811, 595162, None)

        class Theatre:
            fixes = (configured,)
            waypoints = ((1, sortie_only),)

        pushed = {}
        with mock.patch.object(A, "_theatre") as th, \
             mock.patch.object(A, "_put_json",
                               side_effect=lambda url, body: pushed.update(body)), \
             mock.patch.object(A, "_eval_fix_positions",
                               return_value={"FEET WET": [41.629, 41.336]}):
            th.current.return_value = Theatre()
            A.push_fixes("http://unused", profile=None)

        got = pushed.get("fixes") or {}
        self.assertIn("BATUMI", got, "the configured fix was wiped by the sim branch")
        self.assertIn("FEET WET", got, "the sim's answer was lost")
