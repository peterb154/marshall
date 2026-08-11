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
        self.sent_all = []
        self.now = 0.0
        self.wind = wind
        self.voice = FakeVoice()
        self.published = []
        self.logs = []
        self.flying = True
        self.reads = []

    def rendered_reads(self):
        """How many times the sim was asked for the weather."""
        return self.reads

    def observation(self):
        """One field's weather, as `observe_fields` would return it."""
        from marshall.atis import weather
        return weather.observe_fields(self.fields, self.eval_lua)[self.fields[0].name]

    def eval_lua(self, _lua):
        self.reads.append(round(self.now, 1))
        return ";".join(
            f"{f.name}|{self.wind:.1f}|2.57|300|0|80000|20.0|101090"
            for f in self.fields)

    def transmit(self, frames, *mhz):
        """ONE PACKET, EVERY FREQUENCY. `serve` multicasts a field's ATIS on
        its VHF and its UHF together -- the SRS voice packet carries a
        frequency list, so the weather reaches the box a pilot is working
        without a second transmission. The rig records the first frequency as
        the field's identity and keeps the whole list beside it."""
        self.sent.append((round(self.now, 1), mhz[0], frames))
        self.sent_all.append((round(self.now, 1), tuple(mhz), frames))

    def run(self, ticks, poll=10.0, repeat=30.0, at=None, empty=False):
        """ONE serve() call, advanced `ticks` times.

        `at` is {tick: fn(rig)} -- the weather changing, the sim dying -- so a
        whole sortie happens inside a single loop. Calling serve() twice would
        rebuild its state each time, which is not a restart, it is amnesia.
        """
        stop = threading.Event()
        n = {"i": 0}

        def sleep(secs):
            # HONOUR THE ARGUMENT. This added a fixed `poll` however long serve
            # asked to wait, so the loop's own granularity was invisible to
            # every test here -- including the one that matters, how long the
            # radio is actually quiet between playbacks.
            #
            # A TICK IS A POLL PERIOD, NOT AN ITERATION. `serve` sleeps in one
            # second steps now so it can honour a five second gap, so counting
            # iterations would have shrunk every test here from forty seconds of
            # sortie to four. `ticks` still means what it always meant -- how
            # many poll periods pass -- and the hooks in `at` still fire on the
            # boundary they always did.
            self.now += secs if secs else poll
            while n["i"] < int(self.now // poll):
                n["i"] += 1
                if at and n["i"] in at:
                    at[n["i"]](self)
            if self.now >= ticks * poll:
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
                    lambda fr, *mhz: self.transmit(fr, *mhz),
                    self.voice,
                    lambda lua: self.eval_lua(lua),
                    clock=lambda: self.now, stop=stop, sleep=sleep,
                    mission_clock=lambda: 48061.0,
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

    def test_the_first_letter_is_the_one_the_field_is_already_on(self):
        """CHANGED 11 August: it used to assert Alpha.

        Alpha says the aerodrome switched its transmitter on the moment the
        mission loaded. A real one has been broadcasting all day, so the first
        letter is derived from the field and the mission's hour -- see
        `broadcast.first_letter`. Not random: a bridge restart must not change
        the letter a pilot already copied.
        """
        from marshall.atis import broadcast
        rig = Rig()
        rig.run(ticks=2)
        want = broadcast.first_letter(R.KOBULETI_FIELD.name, 48061.0)
        self.assertIn(f"information {want}", rig.voice.rendered[0])

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
        # The LETTER WALKS ON, whatever it started at -- which is the point of
        # this test and was never really about Alpha and Bravo.
        from marshall.atis import broadcast
        first = broadcast.first_letter(R.KOBULETI_FIELD.name, 48061.0)
        self.assertIn(first, rig.voice.rendered[0])
        self.assertIn(broadcast.next_letter(first), rig.voice.rendered[-1])
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


class TheWeatherGoesOutOnBothBoxes(unittest.TestCase):
    """One transmission, VHF and UHF together.

        "put atis on uhf frequencies also ... and multicast those atis
         messages on UHF & VHF"

    A modern jet carries two radios and a pilot is usually working the
    controllers on one of them. Making him retune the box he is TALKING on to
    hear the weather is exactly the friction an ATIS exists to remove.

    It costs one packet, not two: the SRS voice packet has always carried a
    variable-length frequency list -- the same mechanism that lets one
    controller be audible to an SCR-522 and a modern radio at once. Two
    transmissions would cost a second render, a second slot on the air, and a
    chance for the two to drift apart mid-letter.
    """

    def test_both_frequencies_in_one_call(self):
        rig = Rig()
        rig.run(ticks=4)
        self.assertTrue(rig.sent_all, "nothing went out at all")
        _t, freqs, _frames = rig.sent_all[0]
        self.assertEqual(freqs, (R.KOBULETI_FIELD.atis_mhz,
                                 R.KOBULETI_FIELD.atis_uhf_mhz))

    def test_it_is_one_transmission_not_two(self):
        rig = Rig()
        rig.run(ticks=4)
        # One entry per broadcast, carrying both frequencies -- not two entries.
        self.assertEqual(len(rig.sent_all), len(rig.sent))
        for _t, freqs, _f in rig.sent_all:
            self.assertEqual(len(freqs), 2)

    def test_a_field_with_no_uhf_keeps_its_vhf(self):
        # One is not neither. A field that broadcasts on VHF alone must not go
        # silent because it has no UHF assigned.
        import dataclasses
        vhf_only = dataclasses.replace(R.KOBULETI_FIELD, atis_uhf_mhz=0.0)
        rig = Rig(fields=[vhf_only])
        rig.run(ticks=4)
        self.assertTrue(rig.sent_all)
        _t, freqs, _f = rig.sent_all[0]
        self.assertEqual(freqs, (R.KOBULETI_FIELD.atis_mhz,))

    def test_the_two_fields_do_not_share_a_uhf_frequency(self):
        # The whole point of a per-field ATIS is that they are different
        # broadcasts. Sharing a frequency would put Batumi's weather on
        # Kobuleti's button.
        uhf = [f.atis_uhf_mhz for f in R.FIELDS if f.atis_uhf_mhz]
        self.assertEqual(len(uhf), len(set(uhf)))

    def test_no_atis_frequency_collides_with_a_controller(self):
        theirs = {round(s.freq_mhz, 3) for s in R.STATIONS}
        for f in R.FIELDS:
            for mhz in (f.atis_mhz, f.atis_uhf_mhz):
                if mhz:
                    self.assertNotIn(round(mhz, 3), theirs,
                                     f"{f.name} ATIS sits on a controller's "
                                     f"frequency")


class TheRadioIsNotQuietForLong(unittest.TestCase):
    """How long a pilot waits between hearing the loop.

        "the gap between atis loop re-playing is too long.. must be at least
         20 secs. Should be 5 sec or so"

    It was, and the arithmetic is worth keeping because it was backwards.
    `last_played` was stamped BEFORE a transmit that BLOCKS for the length of
    the audio -- it paces Opus frames at 40 ms -- and the interval was measured
    between STARTS. So the silence a listener actually heard was

        repeat - duration, rounded up to the ten-second poll

    which means a LONGER recording gave a SHORTER silence, and a fifteen-second
    one gave twenty seconds of nothing on a thirty-second repeat.

    Measured from the END it is simply the gap, whatever the recording's length,
    and that is the only version a listener can perceive.
    """

    def gaps(self, rig):
        """Silence between one playback ending and the next beginning."""
        out = []
        for (t0, _f, _fr), (t1, _f2, _fr2) in zip(rig.sent, rig.sent[1:]):
            out.append(round(t1 - t0, 1))
        return out

    def test_the_gap_is_about_five_seconds(self):
        rig = Rig()
        rig.run(ticks=6, repeat=S.GAP_SEC)
        self.assertGreaterEqual(len(rig.sent), 3, "it barely played at all")
        for g in self.gaps(rig):
            self.assertLessEqual(g, S.GAP_SEC + S.TICK_SEC,
                                 f"the radio was quiet for {g}s")

    def test_the_default_gap_is_short(self):
        self.assertLessEqual(S.GAP_SEC, 10.0)
        # And the loop can actually honour it: a tick longer than the gap makes
        # a five second silence into a ten second one.
        self.assertLess(S.TICK_SEC, S.GAP_SEC)

    def test_the_weather_is_not_re_read_every_tick(self):
        # The tick is short so the gap can be short. Re-reading the sim at that
        # rate would be twelve times the work for a number that changes hourly.
        rig = Rig()
        rig.run(ticks=6)
        self.assertLessEqual(len(rig.rendered_reads()), 8,
                             "the weather is being read on the loop's clock")


class TheBroadcastKnowsWhatTimeItIs(unittest.TestCase):
    """A real ATIS opens with the hour it was recorded.

        "ATIS always says 0,0,0,0,0 julium, and is always on alpha"

    Which is "time zero zero zero zero Zulu" through Whisper, and a fair
    transcription. The bridge passed `mission_clock=None` -- the one caller of a
    parameter written for exactly this -- so every recording was stamped
    midnight.

    The sim's own clock is the right source, not this machine's: a mission set
    at dawn on a server running at teatime is the case that makes the difference
    visible, and `timer.getAbsTime` answers in the mission's day.
    """

    def test_a_clock_reaches_the_words(self):
        rig = Rig()
        rig.run(ticks=4)
        said = rig.voice.rendered
        self.assertTrue(said, "nothing was recorded")
        self.assertNotIn("Time zero zero zero zero Zulu", said[0],
                         "the recording is stamped midnight")
        self.assertIn("Time one three two one Zulu", said[0])

    def test_zero_still_produces_a_broadcast(self):
        # A sim that will not answer costs the timestamp, never the broadcast.
        from marshall.atis import weather
        self.assertEqual(weather.zulu(0), "0000")

    def test_the_bridge_passes_one(self):
        import inspect
        from marshall.atc import agent_atc
        src = inspect.getsource(agent_atc)
        self.assertIn("mission_clock=_mission_zulu_seconds", src)
        self.assertIn("timer.getAbsTime", src)


class TheLetterSurvivesARestart(unittest.TestCase):
    """It was only ever Alpha, and rotation was not the reason.

        "its only ever been alpha and the mission has run for MANY hours. so
         rotation isnt working."

    Rotation worked. An HOUR OF AGE never accumulated, because the bridge kept
    being restarted and every restart built a fresh `Airwave` -- no letter, no
    recorded-at -- so the loop took the first letter again and reset its own
    clock.

    The durable half was in Postgres the whole time. The `atis` table has
    carried `letter` and `recorded_at` since the ATIS was built -- controllers
    read them so a taxi clearance and the broadcast cannot name different
    runways -- and the writer never read them back. The same shape as every
    other unwired system here, in the one place where the state is explicitly
    persisted.
    """

    def test_a_letter_with_no_audio_is_re_recorded_not_rotated(self):
        # The restart case: the letter came off the table, the frames did not,
        # because Polly renders those and nothing stores them. A pilot who
        # copied it two minutes ago has not been overtaken by an hour.
        was = S.Airwave(letter="Foxtrot", frames=[], recorded_at=0.0)
        obs = Rig().observation()
        letter, changed = S.rerecord(None, obs, was, now_sec=10.0,
                                     previous_obs=obs)
        self.assertEqual(letter, "Foxtrot")
        self.assertTrue(changed, "it would have gone silent after a restart")

    def test_an_hour_still_rotates(self):
        was = S.Airwave(letter="Foxtrot", frames=["x"], recorded_at=0.0)
        obs = Rig().observation()
        letter, changed = S.rerecord(None, obs, was,
                                     now_sec=S.broadcast.ROTATE_AFTER_SEC + 1,
                                     previous_obs=obs)
        self.assertEqual(letter, "Golf")
        self.assertTrue(changed)

    def test_a_fresh_letter_does_not_rotate_early(self):
        was = S.Airwave(letter="Foxtrot", frames=["x"], recorded_at=0.0)
        obs = Rig().observation()
        letter, changed = S.rerecord(None, obs, was, now_sec=60.0,
                                     previous_obs=obs)
        self.assertEqual(letter, "Foxtrot")
        self.assertFalse(changed)

    def test_the_loop_reads_the_table_on_the_way_in(self):
        import inspect
        self.assertIn("store.current(f)", inspect.getsource(S.serve))
        self.assertIn("was.recorded_at = clock() -", inspect.getsource(S.serve))

    def test_the_store_reports_how_old_the_letter_is(self):
        from marshall.atis import store
        self.assertIn("age_sec", store.Current.__dataclass_fields__)
