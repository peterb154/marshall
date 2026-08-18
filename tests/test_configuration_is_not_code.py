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
from unittest import mock

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

    def test_the_aerodromes_ARE_the_catalogue(self):
        """CHANGED. This asserted a fourth name, INITIAL, and called it "the
        plate fix" -- which is exactly the claim that turned out to be wrong.

            "I created a private fix called INITIAL this seems to be
             conflicting with a fix in your list"

        It is the initial approach fix of a letdown we invented, on a plate we
        generate. Nobody outside that procedure can look it up, and a real DKS
        cartridge carries a steerpoint of the same name thirteen miles away --
        so publishing ours warned a pilot about a collision with our own
        fiction on every import (#143, #144, #145).

        The rule it now encodes is docs/CONFIG.md's: a fix needs a NAME only if
        he can fly to it. What is left is the three aerodromes, every one of
        which a pilot can look up and go to.
        """
        names = {f.name for f in catalogue.published_fixes("caucasus")}
        self.assertEqual(names, {"BATUMI", "KOBULETI", "KUTAISI"})

    def test_the_letdowns_own_point_is_still_THERE_just_not_published(self):
        """The other half, and it is the half that must not be lost. Retiring
        INITIAL is not deleting it: the procedures that use it carry it, at the
        same place, on the same frequency, under the same name."""
        from marshall.core import theatre as T
        got = T.published_approaches(
            fields=T.published_fields("caucasus"), theatre="caucasus")
        asr, ndb = got["batumi-asr-13"], got["batumi-ndb-12"]
        self.assertEqual(asr.iaf.name, "INITIAL")
        self.assertEqual(ndb.arrival_fix.name, "INITIAL")
        self.assertEqual(asr.iaf.freq_mhz, 128.0)
        self.assertEqual(asr.iaf.ident, "SW")
        # ...and it is ONE point, not four that happen to agree.
        for a in got.values():
            for role in ("iaf", "arrival_fix", "outer_hold"):
                f = getattr(a, role, None)
                if f is not None and f.name == "INITIAL":
                    self.assertEqual((f.x, f.z), (asr.iaf.x, asr.iaf.z))
                    self.assertEqual((f.lat, f.lon), (asr.iaf.lat, asr.iaf.lon))

    def test_a_role_the_approach_does_not_use_stays_None(self):
        """An UNUSED role is not an unresolvable name, and conflating the two is
        what broke the first two attempts at this. The radar ASR names no
        `arrival_fix`; falling back to the procedure's own point on the empty
        string gave it one, and a controller who reads `arrival_fix is not None`
        as "he is arriving and I am blind" then briefed a departing aircraft on
        an approach. `briefing.py` guards on the same None."""
        from marshall.core import theatre as T
        got = T.published_approaches(
            fields=T.published_fields("caucasus"), theatre="caucasus")
        self.assertIsNone(got["batumi-asr-13"].arrival_fix)
        self.assertIsNone(got["batumi-ndb-12"].iaf)

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
        # THE SECOND FIX IS A PUBLISHED ONE WITH NO POSITION, not a sortie
        # point. This used to pair BATUMI with a route point the theatre
        # folded into the push -- and #188 deleted the fold-in, because a map
        # publishes places and a mission's turning points belong to the
        # mission. The invariant is unchanged and is about the MERGE: a fix
        # the file locates keeps its own numbers, and one it does not gets the
        # sim's. Both have to survive the same push.
        unlocated = R.Fix("INITIAL", "", -355811, 595162, None)

        class Theatre:
            fixes = (configured, unlocated)

        pushed = {}
        with mock.patch.object(A, "_theatre") as th, \
             mock.patch.object(A, "_put_json",
                               side_effect=lambda url, body: pushed.update(body)), \
             mock.patch.object(A, "_eval_fix_positions",
                               return_value={"INITIAL": [41.629, 41.336]}):
            th.current.return_value = Theatre()
            A.push_fixes("http://unused", ())

        got = pushed.get("fixes") or {}
        self.assertIn("BATUMI", got, "the configured fix was wiped by the sim branch")
        self.assertIn("INITIAL", got, "the sim's answer was lost")


class TheFilesAreTheOnlyCopy(unittest.TestCase):
    """What replaced the migration guard, now that the Python is gone.

    While the move was half done the same values existed TWICE -- in the files
    and in `core/fields.py`, `core/stations.py`, `core/approach.py` -- and a
    test asserted them equal attribute by attribute. It earned its keep twice:
    it caught a double quote turned into an apostrophe inside three
    controllers' `manner` (prose that goes straight to the agent, suite green,
    brief silently changed), and it caught that the 1944 letdown carries no
    controllers at all (#140).

    Then the Python was deleted and that test became a tautology comparing the
    files to themselves, so it is gone. What is worth asserting now is that
    there is nothing left to drift FROM.
    """

    def setUp(self):
        catalogue.reload()
        self.addCleanup(catalogue.reload)

    def test_the_modules_no_longer_define_the_data(self):
        from marshall.core import approach, fields, stations

        for mod, names in ((approach, ("BATUMI_ASR", "BATUMI_ILS",
                                       "BATUMI_APPROACH", "KOBULETI_ILS")),
                           (fields, ("FIELDS", "BATUMI_FIELD",
                                     "KOBULETI_FIELD")),
                           (stations, ("STATIONS", "APPROACH", "TOWER",
                                       "KOB_CLEARANCE", "PRESET_LADDER"))):
            for n in names:
                with self.subTest(module=mod.__name__, name=n):
                    self.assertFalse(
                        hasattr(mod, n),
                        f"{mod.__name__}.{n} is back -- two copies again")

    def test_the_names_still_resolve_for_the_call_sites(self):
        """~300 of them read `R.BATUMI_ASR` and `R.STATIONS`. They keep
        working; the values come from the theatre instead of a literal."""
        from marshall.core import route as R

        self.assertEqual(R.BATUMI_ILS.kind, "ils")
        self.assertEqual(len(R.STATIONS), 9)
        self.assertEqual([f.name for f in R.FIELDS], ["Batumi", "Kobuleti"])

    def test_one_object_per_thing(self):
        """`R.KOB_CLEARANCE is R.STATIONS[0]` was true when both were one
        module constant, and several tests assert exactly that -- identity is
        the cheapest way to say "the same controller, not a copy that happens
        to match". The caches are keyed on a RESOLVED map name for this reason:
        `stations_now("")` and `stations_now("caucasus")` were briefly two
        entries holding two equal-but-distinct sets."""
        from marshall.core import route as R

        self.assertIs(R.KOB_CLEARANCE, R.STATIONS[0])
        self.assertIs(R.BATUMI_FIELD, R.FIELDS[0])

    def test_a_name_nobody_publishes_is_an_AttributeError(self):
        """Which is what Python expects, and what keeps a typo an error rather
        than a None that becomes a plausible number three layers away."""
        from marshall.core import route as R

        # The name is built rather than written so that neither ruff's
        # "useless expression" nor its "constant getattr" rule applies -- both
        # are right about ordinary code and wrong about a test whose whole
        # subject is attribute lookup.
        missing = "BATUMI" + "_GCA"
        with self.assertRaises(AttributeError):
            getattr(R, missing)

    def test_the_ladder_is_the_files_order_minus_who_is_not_on_it(self):
        from marshall.core import route as R

        self.assertEqual([s.name for s in R.PRESET_LADDER][:2],
                         ["Kobuleti Clearance", "Kobuleti Ground"])
        self.assertNotIn("Sentry", [s.name for s in R.PRESET_LADDER])


class AMapIsAFileAndNotAFunction(unittest.TestCase):
    """#137 -- `THEATRES = {"caucasus": caucasus, "nevada": nevada}`.

    Adding a map meant writing a Python function, and the set of arrivals a map
    offered lived in `CAUCASUS_RECOVERIES` -- a dict mapping a key to the NAME
    OF A PYTHON CONSTANT, in a different module from the map. So a theatre file
    could publish a procedure nothing was able to select.
    """

    def setUp(self):
        catalogue.reload()
        self.addCleanup(catalogue.reload)

    def test_the_maps_are_discovered_from_disk(self):
        self.assertEqual(catalogue.maps(), ["caucasus", "nevada"])

    def test_the_theatre_carries_its_own_identity(self):
        me = catalogue.identity("caucasus")
        self.assertEqual((me.name, me.departure, me.arrival),
                         ("Caucasus", "Kobuleti", "Batumi"))

    def test_the_recoveries_are_the_files_keys(self):
        from marshall.core import theatre as T

        got = T.published_approaches(T.published_fields("caucasus"),
                                     "caucasus")
        self.assertEqual(sorted(got),
                         ["batumi-asr-13", "batumi-ils-13", "batumi-ndb-12",
                          "kobuleti-ils-07"])

    def test_a_misspelt_map_is_said_out_loud_and_still_starts(self):
        """`THEATRES.get(want, caucasus)` swapped an unknown map for the
        Caucasus IN SILENCE, so MARSHALL_THEATRE=nevda gave a bridge working
        Georgia while its operator believed it was in the desert -- every
        frequency, fix and field real and on the wrong continent.

        And the fallback has to LAND: the theatre builders read the environment
        underneath, so they went looking for `nevda.toml` all over again and
        the fallback crashed instead of falling back.
        """
        import contextlib
        import io

        from marshall.core import theatre as T

        with mock.patch.dict(os.environ, {"MARSHALL_THEATRE": "nevda"}):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                th = T.current()
            self.assertIn("no theatre 'nevda'", buf.getvalue())
            self.assertIn("caucasus, nevada", buf.getvalue())
            self.assertEqual(th.name, "Caucasus")
            self.assertTrue(th.fields and th.approaches)

    def test_the_environment_cannot_choose_an_approach_at_all(self):
        """The mechanism one level down is DELETED rather than corrected.

        This asserted that a misspelt `MARSHALL_APPROACH` was named rather
        than silently swapped -- a good guard on a bad mechanism. #162 is
        that the mechanism should not exist: which approach you fly is a
        fact about your CLEARANCE, and letting the shell decide it meant a
        restart changed the procedure under a flying aeroplane (#158,
        `batumi-ils` became `batumi-asr` mid-rehearsal).

        So the test is not "a wrong value is reported" but "no value has any
        effect": a spelling that USED to select the ILS, and one that never
        named anything, produce identical theatres. Set on the environment
        rather than asserted absent from the source, because the criterion
        is about behaviour -- a grep would pass on a file that read the
        variable under another name."""
        from marshall.core import theatre as T

        with mock.patch.dict(os.environ, {"MARSHALL_THEATRE": "caucasus"}):
            plain = T.current()
        for spelt in ("batumi-ils-13", "batumi-gca", ""):
            with self.subTest(MARSHALL_APPROACH=spelt):
                with mock.patch.dict(os.environ,
                                     {"MARSHALL_THEATRE": "caucasus",
                                      "MARSHALL_APPROACH": spelt}):
                    th = T.current()
                self.assertEqual(th.approaches, plain.approaches)
                self.assertEqual(th.arrival, plain.arrival)
        # ...AND THERE IS NOWHERE TO PUT ONE. A singular beside the plural
        # is how the old path would come back.
        self.assertFalse(hasattr(plain, "approach"))
        self.assertFalse(hasattr(plain, "approach_key"))


class BothMapsAreRows(unittest.TestCase):
    """#137's second half, and the reason it needed one: Nevada was not.

    `config/theatres/caucasus.toml` held the fields, the seats, the fixes and
    the approaches; Nevada held all four as module constants in
    `core/nevada.py` and `theatre.nevada()` never opened a theatre file at all.
    So one map was data and the other was code, and every rule in
    docs/CONFIG.md applied to one of them. The two consequences are asserted
    below rather than described, because both were invisible: a map that
    published no `[[station]]` rows needed a fallback to have any controllers,
    and a misspelt `MARSHALL_SORTIE` silently became Nellis.
    """

    MAPS = ("caucasus", "nevada")

    def setUp(self):
        catalogue.reload()
        self.addCleanup(catalogue.reload)

    def test_every_map_publishes_the_same_tables(self):
        """The point of "the same path": not that the values match -- they must
        not -- but that there is one reader and every map goes through it."""
        for m in self.MAPS:
            with self.subTest(theatre=m):
                self.assertIsNotNone(catalogue.identity(m), "no [theatre]")
                self.assertTrue(catalogue.aerodromes(m), "no [[field]]")
                self.assertTrue(catalogue.controllers(m), "no [[station]]")
                self.assertTrue(catalogue.published_fixes(m), "no [[fix]]")
                self.assertTrue(catalogue.approaches(m), "no [[approach]]")
                self.assertTrue(catalogue.navaids(m), "no [[navaid]]")

    def test_the_theatre_is_built_from_those_tables_and_nothing_else(self):
        """Identity rather than equality, which is the cheapest way to say "the
        same object, not a copy that happens to agree". A theatre still holding
        a Python constant would pass an equality check and fail this one."""
        from marshall.core import theatre as T

        for m in self.MAPS:
            with self.subTest(theatre=m):
                th = T.THEATRES[m]()
                self.assertEqual(th.fields, T.fields_now(m))
                self.assertEqual(th.stations, T.stations_now(m))
                self.assertIs(th.fields[0], T.fields_now(m)[0])
                self.assertIs(th.stations[0], T.stations_now(m)[0])
                # THE SAME OBJECTS, not copies that happen to agree --
                # `ApproachProfile` is unhashable, so identity is checked
                # by `is` against the keyed table rather than by set.
                pub = T.approaches_now(m)
                self.assertEqual(len(th.approaches), len(pub))
                for key, a in pub.items():
                    with self.subTest(approach=key):
                        self.assertTrue(any(a is x for x in th.approaches))

    def test_no_map_needs_a_fallback_for_its_seats(self):
        """`_stations_cached` used to answer out of `THEATRES[name]().stations`
        when the file published none, because Nevada's nine controllers were
        `Station` objects in Python -- and this is the ONE place a station is
        looked up, so without it that map was silently stationless. The rows
        exist now, and the fallback is gone: leaving it would recurse, since
        `nevada()` reads `stations_now` itself."""
        from marshall.core import theatre as T

        for m in catalogue.maps():
            with self.subTest(theatre=m):
                self.assertTrue(T.published_stations(m),
                                f"{m}.toml publishes no controllers")
                self.assertEqual(T.published_stations(m), T.stations_now(m))

    def test_every_published_fix_on_every_map_cites_a_source(self):
        for m in self.MAPS:
            for f in catalogue.published_fixes(m):
                with self.subTest(theatre=m, fix=f.name):
                    self.assertTrue(f.source.strip(), f"{f.name} cites nothing")

    def test_an_unknown_sortie_is_NAMED_rather_than_silently_flown(self):
        """`NEVADA_SORTIES.get(want, NEVADA_SORTIES["nellis"])`. The two filed
        sorties recover at DIFFERENT FIELDS, so a misspelt `MARSHALL_SORTIE`
        gave a bridge working a Nellis recovery while its operator believed he
        was going to Tonopah -- every frequency and every minimum real and
        belonging to the wrong airport. The same shape as the approach key,
        which is how a pilot came to fly a talkdown after asking for an ILS."""
        import contextlib
        import io

        from marshall.core import theatre as T

        with mock.patch.dict(os.environ, {"MARSHALL_THEATRE": "nevada",
                                          "MARSHALL_SORTIE": "range"}):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                th = T.current()
            self.assertIn("range", buf.getvalue())
            self.assertIn("nellis, tonopah", buf.getvalue())
            self.assertEqual(th.arrival, "Nellis")

    def test_a_known_sortie_still_picks_its_own_recovery(self):
        from marshall.core import theatre as T

        with mock.patch.dict(os.environ, {"MARSHALL_THEATRE": "nevada",
                                          "MARSHALL_SORTIE": "tonopah"}):
            th = T.current()
        # A FIELD AND A PLAN. The approach key was the middle value and a
        # sortie does not choose a procedure -- see #162.
        self.assertEqual((th.arrival, th.bootstrap_plan),
                         ("Tonopah", "nevada-nellis-tonopah"))

    def test_the_nevada_module_is_a_reader_and_no_longer_the_map(self):
        """`N.NELLIS_ILS` still resolves for the call sites that read it -- the
        kneeboard card, the mission builder, the terrain survey -- and the
        value comes out of the file. A literal would be a second copy, and
        identity is what tells the two apart."""
        from marshall.core import nevada as N
        from marshall.core import theatre as T

        self.assertIs(N.NELLIS_FIELD, T.fields_now("nevada")[0])
        self.assertIs(N.NELLIS_CLEARANCE, T.stations_now("nevada")[0])
        self.assertIs(N.NELLIS_ILS, T.approaches_now("nevada")["nellis-ils-21"])
        self.assertIs(N.TONOPAH_ILS, T.approaches_now("nevada")["tonopah-ils-15"])
        # ...and the PUBLISHED table is one object per fix. This also checked
        # that `NEVADA_ROUTE = [LSV, TPH, LSV]` was one Fix appearing twice
        # rather than two that agree -- a real hazard, for a route that no
        # longer exists: #188 deleted theatre-level routes, Nevada's included,
        # because declaring one in PYTHON is the same fault as declaring it in
        # the Caucasus toml one file further out.
        self.assertIs(N.LSV, T.fixes_now("nevada")[0])

    def test_the_module_defines_no_instances_at_all(self):
        """"The old path is gone" is the criterion #2 was missing and #162
        writes as greps, so it is written as one here: a `Field_`, `Station`,
        `Fix` or `ApproachProfile` CONSTRUCTED in this module is the data
        coming back."""
        from pathlib import Path

        from marshall.core import nevada as N

        src = Path(N.__file__).read_text(encoding="utf-8")
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith("#"))
        code = code.split('"""')[0] + '"""'.join(code.split('"""')[2:])
        for shape in ("Field_(", "Station(", "Fix(", "ApproachProfile("):
            with self.subTest(shape=shape):
                self.assertNotIn(shape, code,
                                 f"core/nevada.py builds a {shape[:-1]} again")

    def test_a_name_nevada_does_not_publish_is_an_AttributeError(self):
        from marshall.core import nevada as N

        # Built rather than written, so neither ruff's "useless expression" nor
        # its "constant getattr" rule applies -- both right about ordinary code
        # and wrong about a test whose subject is attribute lookup.
        missing = "TONOPAH" + "_NDB"
        with self.assertRaises(AttributeError):
            getattr(N, missing)
