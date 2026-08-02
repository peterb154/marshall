"""Rendered speech is cached, and the cache key is the interesting part.

    "Maybe we build a cache layer into the bridge. Then we get it for
     everything. So 'Roger' and 'readback correct' etc etc get the benefit too."

MEASURED RATHER THAN ASSUMED: 372 recorded transmissions, 322 unique, so 13%
hit. Modest, and the phrases it hits are the right ones -- "readback correct"
twelve times, "roger" twelve -- which are short, frequent, and exactly where
half a second of Polly is most audible.

ATIS is what makes it structural. A looped broadcast is the same recording by
definition, so it renders once per information letter rather than once every
thirty seconds.

The tests below are about the KEY, because the key is where this went wrong
twice and both failures were silent: a cache that never hits looks exactly like
a cache that is not there, except on the bill.
"""

import unittest

import numpy as np

from marshall.radio import tts


class TestTheKeyIsStable(unittest.TestCase):
    """Both bugs were the same shape: lookup and store disagreed."""

    def setUp(self):
        tts._MEM.clear()
        self.pcm = np.zeros(16, dtype="<i2")

    def test_the_same_words_in_the_same_voice_are_the_same_recording(self):
        tts.remember_pcm("Matthew", "", "Sockeye, roger.", self.pcm)
        self.assertIsNotNone(tts.cached_pcm("Matthew", "", "Sockeye, roger."))

    def test_a_different_voice_is_a_different_recording(self):
        tts.remember_pcm("Matthew", "", "roger", self.pcm)
        self.assertIsNone(tts.cached_pcm("Joanna", "", "roger"))

    def test_different_words_are_different_recordings(self):
        tts.remember_pcm("Matthew", "", "roger", self.pcm)
        self.assertIsNone(tts.cached_pcm("Matthew", "", "wilco"))

    def test_THE_RESOLVED_ENGINE_IS_NOT_PART_OF_THE_KEY(self):
        """The bug, twice over.

        `Voice.engine` is a dataclass field AND a memo -- it starts empty and
        gets overwritten with whichever engine Polly accepted. Keying on it
        meant a fresh Voice looked up "auto" against a stored "standard", and
        the SAME Voice looked up "auto" on its first call and "standard" on its
        second. Two entries, no hits, and the disk layer never used at all.

        A field that changes meaning under you cannot be part of a cache key,
        so the resolved engine lives in `_resolved` and the field stays the
        request.
        """
        v = tts.Voice(voice_id="Matthew")
        self.assertEqual(v.engine, "")
        v._resolved = "standard"          # as a render would leave it
        self.assertEqual(v.engine, "", "the request was overwritten by the memo")

    def test_an_explicit_engine_still_separates(self):
        """Asking for neural and asking for standard are different requests and
        must not share audio -- that part of the key is real."""
        tts.remember_pcm("Matthew", "neural", "roger", self.pcm)
        self.assertIsNone(tts.cached_pcm("Matthew", "standard", "roger"))


class TestItSurvivesTheThingsItHasTo(unittest.TestCase):

    def setUp(self):
        tts._MEM.clear()

    def test_it_survives_a_restart(self):
        """On disk as well as in memory, because the bridge restarts and the
        weather does not. Without this a restart mid-sortie re-renders every
        stock phrase at the worst possible moment."""
        pcm = np.arange(32, dtype="<i2")
        tts.remember_pcm("Matthew", "", "disk test phrase", pcm)
        tts._MEM.clear()                          # the restart
        got = tts.cached_pcm("Matthew", "", "disk test phrase")
        self.assertIsNotNone(got, "the disk layer did not answer")
        np.testing.assert_array_equal(got, pcm)

    def test_the_audio_comes_back_unchanged(self):
        pcm = np.array([-32768, -1, 0, 1, 32767], dtype="<i2")
        tts.remember_pcm("Matthew", "", "roundtrip", pcm)
        tts._MEM.clear()
        np.testing.assert_array_equal(
            tts.cached_pcm("Matthew", "", "roundtrip"), pcm)

    def test_memory_is_bounded(self):
        """A long session must not grow without limit. Disk is allowed to."""
        for i in range(tts._MEM_MAX + 20):
            tts.remember_pcm("Matthew", "", f"phrase {i}", np.zeros(4, dtype="<i2"))
        self.assertLessEqual(len(tts._MEM), tts._MEM_MAX)

    def test_a_cache_that_cannot_write_is_not_fatal(self):
        """It must never cost a transmission. A pilot on final does not care
        whether we saved a file."""
        import unittest.mock as mock
        with mock.patch("pathlib.Path.mkdir", side_effect=OSError("full")):
            tts.remember_pcm("Matthew", "", "unwritable", np.zeros(4, dtype="<i2"))
        self.assertIsNotNone(tts.cached_pcm("Matthew", "", "unwritable"),
                             "memory should still have it")

    def test_a_miss_reads_as_a_miss_rather_than_an_error(self):
        self.assertIsNone(tts.cached_pcm("Nobody", "", "never rendered"))


class TestPronunciationHappensBeforeTheKey(unittest.TestCase):
    """Two spellings that pronounce identically ARE the same recording."""

    def test_the_key_is_the_audio_that_will_be_produced(self):
        a, b = tts.pronounce("Vaziani"), tts.pronounce("vaziani")
        self.assertNotEqual(a, "Vaziani", "nothing was respelled; pick another word")
        self.assertEqual(a.lower(), b.lower())


if __name__ == "__main__":
    unittest.main()
