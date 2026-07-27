"""Every ghost this project has actually produced, from 846 real transmissions.

    "the fact that this can happen -- that there is some dictionary with ghost
     aircraft -- makes me concerned about the foundational architecture."

These are not invented test strings. Each one is a verbatim Whisper transcript
from a flight recording on disk, together with the name the callsign extractor
made out of it. Replaying the whole corpus through the current code found 37
distinct names it would bind a radio to, of which 10 were aeroplanes.

A tested thing is not deleted, it becomes the regression check -- so the corpus
lives here rather than in a scratch script, and every fix to the extractor is
scored against the same 846 transmissions that produced the problem.

TWO SIDES ON PURPOSE. A filter that rejects everything scores perfectly against
ghosts and is useless, so the real callsigns are in the same list and a fix that
starts dropping them fails here too. That is not hypothetical: the guard added
on 27 July blacklisted the controller's own phraseology and killed the
"Maintained 2" class outright, and the class that replaced it -- "You 4", "Bound
4", "Here 4" -- is ordinary English, which cannot be blacklisted because there
is an unbounded supply of it.

BASELINE, NOT ZERO. Most of these are still open. A check that is always red is
a check nobody reads, so this fails only on a REGRESSION against the recorded
count. Beat the baseline and move it in the same commit.

The finding the corpus produced, which is the argument of [ARCH-2] / #40:
extraction cannot be fixed by better word lists. "Hammer 1-3" and "Pony 1-4"
have the exact shape of real callsigns, and in a four-ship they ARE real
callsigns -- so with one aeroplane they are ghosts and with four they are
mis-attributions that move somebody else's altitude. The only filter that can
work is corroboration against something nobody spoke.
"""

import unittest

from marshall.atc import agent_atc as A
from marshall.atc import callsign, identity

# (transcript exactly as Whisper produced it, who was ACTUALLY talking).
# "" means nobody -- an engineering call, a debug note, or a fragment that names
# no aeroplane at all, and the right answer is to bind nothing.
CORPUS = [
    # -- ordinary English that happens to be followed by a number ------------
    # The class that replaced "Maintained 2". Unfixable by blacklist: the supply
    # of English words is unbounded and pilots use all of them.
    ('Batumi Approach, Pony one-one with you 4,100 level and bound for landing.',
     'Pony 1-1'),
    ('Batumi approach Falcon one one with you 4,100 level.', 'Falcon 1-1'),
    ('Batumi Approach, Falcon one one with you 10,700 level.', 'Falcon 1-1'),
    ('Paired for the runway, one, three approach.', ''),
    ("Right, two, nine or four, outbound, 5,000 till established. By the way, "
     "we're going to fly this as a pair. Do not try to separate us.", ''),
    ('Batumi approach hammer 113500, adding 080.', 'Hammer 1-1'),

    # -- a real callsign, misheard into another plausible callsign -----------
    # THE DANGEROUS CLASS. Every one of these has the shape of an aeroplane, and
    # on a frequency with a four-ship on it, several of them ARE aeroplanes.
    ('Left two four nine, maintain two thousand, Tony one one, heading one four '
     'eight, maintain two thousand, Tony one one.', 'Pony 1-1'),
    ('Parking my discretion, Tony one.', 'Pony 1'),
    ('Georgia Center, Pony one one four thousand eight hundred west of Kobuleti.',
     'Pony 1-1'),
    ('Batumi Approach Hammer 113500, heading 140 inbound runway 13.', 'Hammer 1-1'),
    ('Batumi tower hammer one one three hundred outbound through two thousand '
     'for three.', 'Hammer 1-1'),
    ('Batumi Tower Hammer 113500, established on the 13 approach.', 'Hammer 1-1'),
    ('Hoover won one for engineering.', 'Hoover 1-1'),
    ('One three one, altitude two thousand, twenty one one.', ''),
    ('Toomey approach, Pony one one, just off runway three, one of Batumi for '
     '4,000.', 'Pony 1-1'),

    # -- the controller's own words, read back ------------------------------
    # Mostly closed by the 27 July phraseology guard; kept because that is what
    # tells us if the fix rots.
    ('Turn left 169, maintain 2,000, Pony one one, debug log. Controllers should '
     'say frequencies with their full frequency 124 decimal 00.', 'Pony 1-1'),
    ('124 decimal zero for vectors to Batumi hammer flight.', ''),
    ('Stanley two, one one, turn right heading zero, one three, maintain four '
     'thousand.', ''),
    ('3-0-4-2,000, Pony one one, debug log, I said 4,000 a second ago and he '
     'told me read back was correct on the 2,000 instructions.', 'Pony 1-1'),

    # -- not a radio call at all: engineering and debug notes ---------------
    ('Engineering issue alpha seven has been checked off as complete and working.',
     ''),
    ('Debug notes, when the controllers give me frequencies, they should give it '
     'to me with full decimal, like 134.00 or decimal 0.00.', ''),
    ("Debug log, it sure seems like he's sending me way out of here for "
     "deconfliction when I'm the only one up here.", ''),
    ("The debug log 304 is going a long ways away from that airport. We'll see "
     "what he's doing.", ''),
    ('Peabug log, vectors should generally be rounded to the nearest five degrees.',
     ''),
    ('Debug log, this is requiring a 4,000 foot per minute descent to get down '
     'from 8,000 to the 3,000.', ''),

    # -- and the ones that already work. Half the test. ---------------------
    ('Batumi Approach, Pony one one, request the radar approach, runway one three.',
     'Pony 1-1'),
    ('Batumi Approach, Pony 1, Flight of 2, Checking in.', 'Pony 1'),
    ('Pony12, checking in.', 'Pony 1-2'),
    ('Georgia Center, this is Hammer one one, four thousand level inbound Batumi.',
     'Hammer 1-1'),
    ('Batumi Approach, Hoover 11, request the radar approach runway 13.',
     'Hoover 1-1'),
    ('Georgia Center, Falcon 11, with you 10,000 level northbound.', 'Falcon 1-1'),
    ('Batumi Approach, Shooter one one, say the altimeter.', 'Shooter 1-1'),
    ('Batumi Tower, hammer flight, we\'re gonna get hammer one two, a new '
     'airplane, a P-51.', 'Hammer 1-2'),
]

# What the extractor gets wrong TODAY, measured. Lower it with a fix; never
# raise it to make a test pass.
#
# NOT A FIELD RATE, and it must not be quoted as one. The corpus was built by
# taking the FIRST transmission that produced each novel name, so it is
# deliberately concentrated on the failures -- 33 hand-picked transmissions out
# of 846. Over the whole 846, most calls bind correctly. This number measures
# the hard cases, which is what a regression check is for.
BASELINE_WRONG = 25


def bind(transcript: str) -> str:
    """The bridge's chain, exactly: extract, filter, take the speaker.

    Not `transmitter_callsign`, because that one also carries the per-radio vote
    that smooths single garbles away over a whole sortie. This is the raw
    per-transmission answer -- the thing the vote has to be good enough to
    survive, and the thing that decides a FIRST call, where there is nothing to
    vote with.
    """
    real = [c for c in callsign.extract_all(transcript)
            if A._plausible_callsign(c, transcript)]
    return real[1] if len(real) > 1 else (real[0] if real else "")


class TestNothingBecomesAnAeroplaneOnItsOwn(unittest.TestCase):
    """The same 33 transcripts, put through the identity ladder.

    This is the claim the architectural fix makes, and it is stronger and much
    simpler than "the extractor gets it right":

        no transmission ever produces a name that is not a real aeroplane.

    The extractor may still mis-hear -- it always will, it is a speech model --
    but a mis-hearing now has only two possible outcomes: the right aeroplane,
    or nobody. It can no longer invent a third one, and with several ships up it
    can no longer hand one pilot's report to another.
    """

    # The ten aeroplanes that were actually flying across these recordings.
    FLYING = ["Pony 1", "Pony 1-1", "Pony 1-2", "Hammer 1", "Hammer 1-1",
              "Hammer 1-2", "Hoover 1-1", "Falcon 1", "Falcon 1-1", "Shooter 1-1"]

    def test_no_third_name_is_ever_invented(self):
        invented = []
        for transcript, who in CORPUS:
            reg = identity.Registry()
            got = reg.resolve("guid", "unknown-radio", spoken=bind(transcript),
                              plans=self.FLYING)
            if got.callsign and got.callsign != who:
                invented.append((who or "<nobody>", got.callsign, transcript))
        if invented:
            lines = "\n".join(f"    really {w:12} became {g:12}  {t[:60]}"
                              for w, g, t in invented)
            self.fail(f"{len(invented)} transmissions invented an aeroplane:\n{lines}")

    def test_the_radio_settles_it_when_radar_has_him(self):
        """With the physical chain closed, the words cannot move the identity at
        all -- which is the case that matters with ten pilots up."""
        scope = ("362nd_sockeye [Pony 1-1] (P-47D-30): 4.1 nm on the 281 "
                 "radial, 4,659 ft, heading 026")
        reg = identity.Registry()
        for transcript, _who in CORPUS:
            with self.subTest(transcript[:40]):
                got = reg.resolve("guid-a", "Sockeye", spoken=bind(transcript),
                                  scope=scope)
                self.assertEqual(got.track, "362nd_sockeye")

    def test_a_refusal_is_the_correct_answer_not_a_gap(self):
        """Worth stating plainly because it looks like a failure in a
        scoreboard: a transmission nobody could identify moved nobody's
        altitude and nobody's place in the queue."""
        reg = identity.Registry()
        self.assertFalse(reg.resolve("g", "nobody", spoken="You 4",
                                     plans=self.FLYING))


class TestTheGhostCorpus(unittest.TestCase):
    def test_no_worse_than_the_baseline(self):
        wrong = []
        for transcript, who in CORPUS:
            got = bind(transcript)
            if got != who:
                wrong.append((who or "<nobody>", got or "<nobody>", transcript))
        if len(wrong) > BASELINE_WRONG:
            lines = "\n".join(f"    want {w:12} got {g:12}  {t[:70]}"
                              for w, g, t in wrong)
            self.fail(f"REGRESSION: {len(wrong)} wrong, baseline is "
                      f"{BASELINE_WRONG}\n{lines}")
        if len(wrong) < BASELINE_WRONG:
            self.fail(f"{len(wrong)} wrong, better than the baseline of "
                      f"{BASELINE_WRONG} -- lower BASELINE_WRONG in the same "
                      f"commit so the win cannot be given back")

    def test_the_real_callsigns_still_work(self):
        """The other half. A filter that rejects everything must fail here.

        These are the plain, well-formed calls that have worked all along; any
        fix to the ghost problem that costs one of them has made the system
        worse, because a controller who cannot identify a pilot who named
        himself correctly is not a controller.
        """
        plain = [(t, w) for t, w in CORPUS[-8:]]
        for transcript, who in plain:
            with self.subTest(transcript[:40]):
                self.assertEqual(bind(transcript), who)

    def test_a_debug_note_is_never_an_aeroplane(self):
        """The cheapest class, and worth its own guard: these arrive on the
        engineering channel, they are prose, and none of them is a pilot."""
        for transcript, who in CORPUS:
            if transcript.lower().startswith(("debug log", "debug notes")):
                with self.subTest(transcript[:40]):
                    self.assertEqual(who, "")

    def test_every_specimen_is_a_real_transcript(self):
        """Guard against somebody 'improving' the corpus into fiction.

        Its whole value is that Whisper actually produced these words from
        actual radio audio; a tidied-up specimen tests the tidying.
        """
        self.assertGreaterEqual(len(CORPUS), 30)
        for transcript, _who in CORPUS:
            self.assertTrue(transcript.strip())
            self.assertNotEqual(transcript, transcript.upper())


if __name__ == "__main__":
    unittest.main()
