"""A sortie with no sim, no SRS, no Whisper, no Polly and no Bedrock.

The receive loop in `atc/agent_atc.py` is 1,167 lines, it touches every layer in
the system, and **no test executes a single line of it**. Every finding at the
top of the 29 July audit lives in there, which is not a coincidence: it is the
one place where nothing could be tested in isolation, so nothing was.

This is step 0 of the layering work. Before the loop is cut into stages it has
to be possible to say what it does TODAY -- otherwise the refactor is judged
against nobody's memory and every regression costs a sortie to find.

CHARACTERISATION, NOT SPECIFICATION. These tests assert what the code does right
now, including things that are arguably wrong. When the refactor changes one of
them on purpose, the diff on the expectation is the record of that decision --
which is the entire value. A characterisation test that was written to describe
the intended behaviour instead of the actual one proves nothing about a
refactor.

NOTHING IN PRODUCTION CHANGES TO SUPPORT THIS, which is the other rule. Every
seam here is a module attribute that already existed, patched from outside. If
the loop had to be edited to become testable, the tests would describe the
edited loop and the safety net would have a hole in it exactly where the work is
about to happen.

WHAT IS FAKED, and all of it is IO:

    marshall.srs.client.SRSClient   the radio -- scripted in, captured out
    marshall.srs.stt                Whisper. The script IS the transcript
    marshall.srs.tts.Voice          Polly. `frames(text)` returns the text, so
                                    an assertion can read what was said
    agent_atc.fetch_radar           the scope, per turn, from the script
    agent_atc.ask_agent             the director. The script says what it replies
    agent_atc.fetch_due             hooks -- empty unless a test wants one
    agent_atc.load_and_push_plate   the real profile from route.py, no network
    agent_atc.flight_bind           the director's flight rows
    agent_atc.filed_plans           the filed strips

The loop is `while True` with no broad except around its body, so `StopSortie`
raised from the fake radio when the script runs out propagates cleanly and ends
the run. That is deliberate on both sides: if somebody later wraps the body in
`except Exception`, this harness stops working and that is worth knowing.
"""

from __future__ import annotations

import pathlib
import threading


class StopSortie(Exception):
    """Raised by the fake radio when the script is exhausted. Ends the loop."""


class Pcm:
    """Whatever `recv_utterance` returns. The loop only ever asks for `.size`."""

    size = 1


class Transmission:
    """One thing the controller said, and where."""

    def __init__(self, text: str, hz: float, mod):
        self.text, self.hz, self.mod = text, hz, mod

    def __repr__(self) -> str:
        return f"<{self.hz / 1e6:.3f}: {self.text!r}>"


class FakeRadio:
    """The six members of SRSClient the receive loop actually uses.

    Scripted in: a list of (guid, srs_name, transcript). Captured out: every
    `transmit`, decoded back to text because the fake Voice hands frames through
    unchanged.
    """

    def __init__(self, script, guid="atc-guid"):
        self.script = list(script)
        self.guid = guid
        self.last_sender_guid = None
        self.sent: list[Transmission] = []
        self._names: dict[str, str] = {}
        self.udp = _Sock()
        self.roster: dict[str, str] = {}
        self.turns = 0

    # --- what the loop calls -------------------------------------------------
    def connect(self, radios):
        return self

    def recv_utterance(self, max_wait=None, silence=None):
        if not self.script:
            raise StopSortie(f"script exhausted after {self.turns} turns")
        guid, name, _text = self.script[0]
        self.last_sender_guid = guid
        self._names[guid] = name
        return Pcm(), None                      # heard_hz None => primary freq

    def name_for(self, guid):
        return self._names.get(guid, "")

    def transmit(self, frames, hz, mod):
        self.sent.append(Transmission(_text_of(frames), hz, mod))

    def someone_is_talking(self, *a, **k):
        return False

    # --- what the harness calls ---------------------------------------------
    def consume(self) -> str:
        """Pop the current line. Called by the fake stt once it has read it."""
        _guid, _name, text = self.script.pop(0)
        self.turns += 1
        return text

    def said(self) -> list[str]:
        return [t.text for t in self.sent]


class _Sock:
    """`client.udp` is only ever poked for timeouts and drains."""

    def settimeout(self, *_a):
        pass

    def recvfrom(self, *_a):
        raise OSError("empty")


def _text_of(frames):
    if isinstance(frames, str):
        return frames
    try:
        return "".join(frames)
    except TypeError:
        return repr(frames)


class FakeVoice:
    """Polly. `frames(text)` hands the text straight through so a test can read
    what was transmitted rather than a bag of Opus."""

    def __init__(self, *a, **k):
        pass

    def frames(self, text):
        return text


class Sortie:
    """Drive the real receive loop over fakes, and hand back what was said.

    Usage:

        s = Sortie(profile=R.BATUMI_ASR)
        s.say("pony-guid", "362nd_sockeye", "Batumi Approach, Pony 1-1, ten miles")
        s.radar("362nd_sockeye [Pony 1-1] (P-51D-30-NA, manned): 10.0 nm ...")
        s.replies("RADIO: Pony one one, Batumi Approach, radar contact")
        s.fly()
        assert "radar contact" in s.said()[0]
    """

    def __init__(self, profile=None, session="test", freq_mhz=124.0):
        from marshall.core import route as R
        self.profile = profile if profile is not None else R.BATUMI_ASR
        self.session, self.freq_mhz = session, freq_mhz
        self.script: list[tuple[str, str, str]] = []
        self._radar: list[str] = []
        self._replies: list[str] = []
        self._due: list[list] = []
        self.radio: FakeRadio | None = None
        self.messages: list[str] = []          # what the director was asked
        self.error: BaseException | None = None

    # --- scripting -----------------------------------------------------------
    def say(self, guid, srs_name, transcript):
        self.script.append((guid, srs_name, transcript))
        return self

    def radar(self, picture):
        self._radar.append(picture)
        return self

    def replies(self, text):
        self._replies.append(text)
        return self

    def hooks_due(self, due):
        self._due.append(due)
        return self

    # --- the run -------------------------------------------------------------
    def fly(self, timeout=20.0):
        import tempfile

        import marshall.atc.agent_atc as A
        from marshall import config
        from marshall.srs import client as srs_client
        from marshall.srs import stt, tts

        radio = FakeRadio(self.script)
        self.radio = radio
        saved = {}

        def patch(mod, name, value):
            saved.setdefault((mod, name), getattr(mod, name, None))
            setattr(mod, name, value)

        def fake_transcribe(_model, _pcm, prompt=None):
            return radio.consume()

        def fake_radar(_session_id="", *a, **k):
            # THE SCOPE PERSISTS. Radar does not go blank between reads, and the
            # loop reads it more than once per transmission -- the asr_monitor
            # thread has its own. A queue that drains to "no contacts" made the
            # second pilot in a two-ship unidentifiable, which is a bug in the
            # harness that looked exactly like a bug in the ladder.
            if self._radar:
                self._last_radar = self._radar.pop(0)
            return getattr(self, "_last_radar", "no contacts")

        def fake_ask(_session, message, tier="sonnet", url=None, *a, **k):
            self.messages.append(message)
            return self._replies.pop(0) if self._replies else "RADIO: (no call)"

        patch(srs_client, "SRSClient", lambda *a, **k: radio)
        patch(stt, "load_model", lambda *a, **k: object())
        patch(stt, "transcribe", fake_transcribe)
        patch(tts, "Voice", FakeVoice)
        patch(A, "fetch_radar", fake_radar)
        patch(A, "ask_agent", fake_ask)
        patch(A, "fetch_due", lambda *a, **k: self._due.pop(0) if self._due else [])
        patch(A, "load_and_push_plate", lambda *a, **k: self.profile)
        patch(A, "flight_bind", lambda *a, **k: {})
        patch(A, "filed_plans", lambda *a, **k: [])
        # Fresh per sortie, or one test's board leaks into the next. The
        # identity registry, the flight roster and the board clock now live on
        # a Bridge that `_run_srs` makes for itself, so they need no patching
        # at all -- which is the point of [LAYERS.md] step 2. What is left here
        # is the state still module-global, and this list shrinking is the
        # measure of that work.
        patch(A, "_last_heard", {})
        patch(A, "_heard_on", {})

        def run():
            try:
                A._run_srs("fake-host", self.freq_mhz, "Matthew", self.session)
            except StopSortie:
                pass                            # the script ran out; that is the end
            except BaseException as e:          # report it, never hang the suite
                self.error = e

        # A SORTIE MUST NOT WRITE WHERE THE REAL ONE DOES. The loop records to
        # build/logs and publishes to build/control, and both are read by the
        # live dashboard -- so running the unit suite used to overwrite the
        # bridge's published state and leave a `flight-test.jsonl` that /diag
        # then picked as the newest session. A pilot debugging a sortie was
        # shown output from `tools/check.py`.
        real_build = config.BUILD_DIR
        tmp = tempfile.TemporaryDirectory()
        config.BUILD_DIR = pathlib.Path(tmp.name)

        t = threading.Thread(target=run, daemon=True)
        t.start()
        t.join(timeout)
        config.BUILD_DIR = real_build
        tmp.cleanup()
        for (mod, name), old in saved.items():
            setattr(mod, name, old)
        if t.is_alive():
            raise AssertionError(
                f"the loop did not finish within {timeout}s -- it consumed "
                f"{radio.turns} of {len(self.script)} scripted transmissions")
        if self.error is not None:
            raise self.error
        return self

    # --- what happened -------------------------------------------------------
    def said(self) -> list[str]:
        return self.radio.said() if self.radio else []

    def said_on(self, mhz) -> list[str]:
        hz = mhz * 1_000_000
        return [t.text for t in (self.radio.sent if self.radio else [])
                if abs(t.hz - hz) < 1]

    def asked(self) -> list[str]:
        """Every message the director was handed. The prompt seam."""
        return self.messages

    def transmitted_anything(self) -> bool:
        return bool(self.said())
