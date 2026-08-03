"""The broadcast loop, driven without a sim, a radio or an hour of waiting.

Everything the loop needs from the world is a parameter -- the transmitter, the
Lua evaluator, the clock -- which is the same rule that keeps `atis` a sibling
of `atc` rather than something underneath it. It is also what makes this file
possible: the tests below run an hour of ATIS in a few milliseconds.
"""

import threading
import unittest

from marshall.atis import broadcast as B
from marshall.atis import serve as S
from marshall.core import route as R


class FakeVoice:
    def __init__(self):
        self.rendered = []

    def frames(self, text):
        self.rendered.append(text)
        return [f"<{len(text)} bytes>"]


class Rig:
    """One field, a fake radio, and a clock you turn by hand."""

    def __init__(self, fields=None, wind=90):
        self.fields = fields or [R.KOBULETI_FIELD]
        self.sent = []
        self.now = 0.0
        self.wind = wind
        self.voice = FakeVoice()
        self.published = []
        self.logs = []
        self.flying = True

    def eval_lua(self, _lua):
        return ";".join(
            f"{f.name}|{self.wind:.1f}|2.57|300|0|80000|20.0|101090"
            for f in self.fields)

    def transmit(self, frames, mhz):
        self.sent.append((round(self.now, 1), mhz, frames))

    def run(self, ticks, poll=10.0, repeat=30.0, at=None, empty=False):
        """ONE serve() call, advanced `ticks` times.

        `at` is {tick: fn(rig)} -- the weather changing, the sim dying -- so a
        whole sortie happens inside a single loop. Calling serve() twice would
        rebuild its state each time, which is not a restart, it is amnesia.
        """
        stop = threading.Event()
        n = {"i": 0}

        def sleep(_s):
            self.now += poll
            n["i"] += 1
            if at and n["i"] in at:
                at[n["i"]](self)
            if n["i"] >= ticks:
                stop.set()

        import unittest.mock as mock
        with mock.patch.object(S.store, "publish",
                               side_effect=lambda o, l, t: self.published.append(l)):
            # Indirection on purpose: `at` hooks swap these mid-run, and a
            # bound method captured at call time would keep the old one.
            who = None
            if empty == "dynamic":
                who = lambda: self.flying            # noqa: E731
            elif empty:
                who = lambda: False                  # noqa: E731
            S.serve(self.fields,
                    lambda fr, mhz: self.transmit(fr, mhz),
                    self.voice,
                    lambda lua: self.eval_lua(lua),
                    clock=lambda: self.now, stop=stop, sleep=sleep,
                    repeat_sec=repeat, poll_sec=poll,
                    anybody_flying=who, log=self.logs.append)


class TestItGoesOnTheAir(unittest.TestCase):

    def test_it_records_once_and_plays_repeatedly(self):
        """The whole point: one recording, looped. If it re-rendered per
        transmission it would be a network call on a loop that cannot fail."""
        rig = Rig()
        rig.run(ticks=12)                      # 120 s at 10 s polls
        self.assertEqual(len(rig.voice.rendered), 1, "re-rendered the same words")
        self.assertGreaterEqual(len(rig.sent), 3, "did not repeat")

    def test_it_plays_on_the_fields_own_frequency(self):
        rig = Rig()
        rig.run(ticks=4)
        self.assertTrue(rig.sent)
        self.assertEqual({mhz for _, mhz, _ in rig.sent},
                         {R.KOBULETI_FIELD.atis_mhz})

    def test_two_fields_get_two_broadcasts_on_two_frequencies(self):
        rig = Rig(fields=[R.KOBULETI_FIELD, R.BATUMI_FIELD])
        rig.run(ticks=4)
        self.assertEqual({mhz for _, mhz, _ in rig.sent},
                         {R.KOBULETI_FIELD.atis_mhz, R.BATUMI_FIELD.atis_mhz})
        self.assertEqual(len(rig.voice.rendered), 2, "one recording per field")

    def test_the_first_letter_is_alpha(self):
        rig = Rig()
        rig.run(ticks=2)
        self.assertIn("information Alpha", rig.voice.rendered[0])

    def test_a_field_that_does_not_broadcast_is_skipped(self):
        import dataclasses
        quiet = dataclasses.replace(R.KOBULETI_FIELD, atis_mhz=0.0)
        rig = Rig(fields=[quiet])
        rig.run(ticks=3)
        self.assertEqual(rig.sent, [])
        self.assertIn("nothing to do", " ".join(rig.logs))


class TestTheLetterWalksOn(unittest.TestCase):

    def test_a_wind_shift_that_changes_the_runway_re_records(self):
        def swing(rig):
            rig.wind = 270                      # the other end of the runway
        rig = Rig(wind=90)
        rig.run(ticks=8, at={4: swing})
        self.assertGreater(len(rig.voice.rendered), 1, "never re-recorded")
        self.assertIn("Alpha", rig.voice.rendered[0])
        self.assertIn("Bravo", rig.voice.rendered[-1])
        # The runway swings with the wind, and the TRANSCRIPT is plain English
        # -- "two five", not "two fife". The ICAO words are applied at the
        # radio, so this is the right layer to see "five" on.
        self.assertIn("zero seven", rig.voice.rendered[0])
        self.assertIn("two five", rig.voice.rendered[-1])

    def test_steady_weather_inside_the_hour_keeps_the_letter(self):
        rig = Rig()
        rig.run(ticks=20)                       # 200 s, weather unchanged
        self.assertEqual(len(rig.voice.rendered), 1)

    def test_the_rotation_decision_is_testable_on_its_own(self):
        """`rerecord` is split out so the policy needs no radio."""
        was = S.Airwave(letter="", recorded_at=0.0)
        letter, changed = S.rerecord(R.KOBULETI_FIELD, None, was, 0.0)
        self.assertEqual((letter, changed), (B.LETTERS[0], True))

    def test_an_hour_advances_it_even_with_identical_weather(self):
        """DCS weather does not move, so this is the only thing that ever
        advances the letter -- and a letter that never changes carries no
        information at all."""
        was = S.Airwave(letter="Alpha", recorded_at=0.0)

        class Obs:
            def same_as(self, other):
                return True
        letter, changed = S.rerecord(R.KOBULETI_FIELD, Obs(), was,
                                     B.ROTATE_AFTER_SEC + 1, previous_obs=Obs())
        self.assertTrue(changed)
        self.assertEqual(letter, "Bravo")


class TestItStaysOnTheAirWhenThingsBreak(unittest.TestCase):
    """A broadcast is the one thing that should keep going."""

    def test_a_failed_weather_read_keeps_the_last_recording_playing(self):
        """What a real ATIS does between observations, and the case that
        matters: the sim is gone and a pilot is still tuned in."""
        def die(rig):
            rig.eval_lua = lambda _l: (_ for _ in ()).throw(RuntimeError("sim gone"))
        rig = Rig()
        rig.run(ticks=12, at={3: die})
        after = [t for t, _m, _f in rig.sent if t > 30]
        self.assertTrue(after, "it went silent when the sim did")
        self.assertIn("still playing the last recording", " ".join(rig.logs))

    def test_a_failed_transmit_does_not_stop_the_loop(self):
        rig = Rig()
        rig.transmit = lambda f, m: (_ for _ in ()).throw(OSError("radio down"))
        rig.run(ticks=4)
        self.assertIn("transmit failed", " ".join(rig.logs))

    def test_A_FAILED_PUBLISH_IS_LOUD(self):
        """Not cosmetic. Every controller reads the runway in use from that
        row, so a failed publish means the broadcast and the taxi clearance can
        name different runways."""
        import unittest.mock as mock
        rig = Rig()
        stop = threading.Event()
        n = {"i": 0}

        def sleep(_s):
            rig.now += 10
            n["i"] += 1
            if n["i"] >= 2:
                stop.set()
        with mock.patch.object(S.store, "publish",
                               side_effect=RuntimeError("no db")):
            S.serve(rig.fields, rig.transmit, rig.voice, rig.eval_lua,
                    clock=lambda: rig.now, stop=stop, sleep=sleep,
                    log=rig.logs.append)
        joined = " ".join(rig.logs)
        self.assertIn("PUBLISH FAILED", joined)
        self.assertIn("different runway", joined)


if __name__ == "__main__":
    unittest.main()


class TestItStandsDownOnAnEmptyServer(unittest.TestCase):
    """A broadcast to nobody costs money and means nothing.

    The letter rotates hourly whether or not anyone is connected, so a server
    left up for a week spends it re-recording for an empty sky -- about $0.37
    at two fields and $24 a month at thirty.

    It is also more correct: a pilot who joins should hear a letter that means
    "this is what I recorded", not one that has been walking the alphabet since
    Tuesday.
    """

    def test_an_empty_server_gets_no_transmissions(self):
        rig = Rig()
        rig.run(ticks=6, empty=True)
        self.assertEqual(rig.sent, [])
        self.assertEqual(rig.voice.rendered, [], "rendered for nobody")
        self.assertIn("nobody on the server", " ".join(rig.logs))

    def test_it_comes_back_when_somebody_joins(self):
        rig = Rig()
        rig.flying = False

        def arrive(r):
            r.flying = True
        rig.run(ticks=10, at={3: arrive}, empty="dynamic")
        self.assertTrue(rig.sent, "never came back on the air")
        self.assertIn("somebody joined", " ".join(rig.logs))

    def test_it_says_so_once_rather_than_every_poll(self):
        rig = Rig()
        rig.run(ticks=8, empty=True)
        said = [ln for ln in rig.logs if "nobody on the server" in ln]
        self.assertEqual(len(said), 1, "logged the same thing every tick")
