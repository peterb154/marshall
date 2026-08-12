"""Text-to-speech -> Opus frames for the SRS transmit path.

AWS Polly renders 16 kHz PCM (its highest PCM rate). SRS relays a voice packet
whose audio payload is a run of fixed-duration Opus frames at SRS's own sample
rate, so we resample Polly's PCM to that rate and encode fixed frames.

Polly runs on the LXC (verified working) -- NOT on the DCS box via DCS-gRPC.
The provider is swappable: a Piper backend (offline) drops in behind the same
`Voice.frames()` seam without the SRS client caring.

    uv run --extra voice python -m marshall.radio.tts "Batumi Approach, radio check"
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
import hashlib

from marshall import config

import re

import numpy as np
import opuslib
import soxr


# SRS voice: Opus, mono, 40 ms frames at 16 kHz ("wideband"). Confirmed against
# SkyEye's simpleradio client -- both ends must agree on the rate or the audio
# plays at the wrong pitch. Polly's PCM is already 16 kHz, so no resampling.
SRS_SAMPLE_RATE = 16000
SRS_CHANNELS = 1
FRAME_MS = 40
SAMPLES_PER_FRAME = SRS_SAMPLE_RATE * FRAME_MS // 1000  # 640

_POLLY_RATE = 16000  # Polly PCM tops out here -- and matches SRS, so no resample


# Words Polly gets wrong, respelled the way it should say them.
#
# THE TABLE IS NOT HERE ANY MORE. It lives in `config/speech.toml` and
# `config/theatres/<map>.toml`, read through `core.catalogue` -- because it was
# three different kinds of fact in one Python dict:
#
#     "niner"      aviation English, true on every map in every era
#     "Kobuleti"   a name on THIS map
#     "Sockeye"    one pilot's callsign, on one evening
#
# So a new pilot with a new callsign was mispronounced on the air until
# somebody edited this file and restarted the bridge, which is #97 -- and
# "should work with any pilot" was impossible while a callsign had to be
# compiled in. See docs/CONFIG.md and #137.
#
# The respelling convention that took two attempts to get right is documented
# in the TOML beside the entries it applies to, which is where somebody adding
# a word will actually read it.


def say_as(callsigns: dict | None = None) -> dict:
    """The respellings in force: universal, then this map, then this sortie.

    Falls back to `catalogue.known_callsigns()` when the caller passes nothing,
    so a bridge that has not been told who is flying still says the names it
    knows. That fallback is the stopgap described in config/callsigns.toml and
    goes when a pilot record exists.
    """
    from marshall.core import catalogue
    return catalogue.speech(
        catalogue.known_callsigns() if callsigns is None else callsigns)


@lru_cache(maxsize=8)
def _matcher(words: tuple) -> re.Pattern:
    """One regex per distinct table, cached.

    Built at import from a module constant before the table could change.
    Now the sortie's callsigns are part of it, so it is derived from whatever
    is in force -- longest first, so "Pony one one" wins over "Pony one".
    """
    return re.compile(r"\b(" + "|".join(
        re.escape(w) for w in sorted(words, key=len, reverse=True)) + r")\b",
        re.I)


def pronounce(text: str, callsigns: dict | None = None) -> str:
    """Respell the words Polly mangles, preserving capitalisation.

    `callsigns` is this sortie's own respellings -- his name, said his way. It
    is passed in rather than looked up because this module has no business
    knowing who is flying; the bridge hands it whatever the board holds.
    """
    table = say_as(callsigns)
    if not table:
        return text or ""
    # CASE-INSENSITIVELY, because the regex already matches that way and the
    # lookup did not. Every place name is stored capitalised, so "batumi" out
    # of a transcript matched the pattern, missed the table, and went to Polly
    # unrespelled -- the exact mangling this exists to prevent, for anybody who
    # did not capitalise.
    folded = {k.lower(): v for k, v in table.items()}

    def sub(m):
        word = m.group(1)
        said = folded.get(word.lower()) or word
        if word[:1].isupper():
            return said[:1].upper() + said[1:]
        return said[:1].lower() + said[1:]
    return _matcher(tuple(sorted(table))).sub(sub, text or "")


# ---------------------------------------------------------------------------
# RENDERED SPEECH IS CACHED, and it is cached HERE rather than in the ATIS
# module that wanted it:
#
#     "Maybe we build a cache layer into the bridge. Then we get it for
#      everything. So 'Roger' and 'readback correct' etc etc get the benefit
#      too."
#
# Which is the right level. The same words in the same voice are byte-for-byte
# the same audio, so a second render is a network round trip to be told
# something we already know.
#
# WHAT IT ACTUALLY BUYS, measured on 372 recorded transmissions rather than
# guessed: 322 were unique, so 13% hit. That is modest and the phrases it hits
# are the right ones -- "readback correct" twelve times, "roger" twelve --
# which are short, frequent, and exactly where a half-second of Polly is most
# audible. A controller who says "roger" instantly sounds like a controller;
# one who pauses first sounds like a machine.
#
# ATIS is the case that makes it structural rather than a nicety. A looped
# broadcast is the SAME recording every time by definition, so it renders once
# per information letter instead of once every thirty seconds -- which is also
# what a real ATIS is, and the reason it has a letter at all.
#
# ON DISK AS WELL AS IN MEMORY, because the bridge restarts and the weather
# does not. A restart mid-sortie re-renders every stock phrase otherwise, at
# the worst possible moment.
_MEM: OrderedDict[str, np.ndarray] = OrderedDict()
_MEM_MAX = 256          # phrases; a 20-second ATIS is 640 KB, most are far less


def _key(voice_id: str, engine: str, text: str) -> str:
    return hashlib.sha256(
        "\u0000".join((voice_id, engine or "auto", text)).encode()).hexdigest()[:32]


def cached_pcm(voice_id: str, engine: str, text: str) -> np.ndarray | None:
    """Speech we have already paid for, from memory or from disk."""
    k = _key(voice_id, engine, text)
    got = _MEM.get(k)
    if got is not None:
        _MEM.move_to_end(k)
        return got
    path = config.TTS_CACHE / f"{k}.pcm"
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    pcm = np.frombuffer(raw, dtype="<i2")
    _MEM[k] = pcm
    _trim()
    return pcm


def remember_pcm(voice_id: str, engine: str, text: str, pcm) -> None:
    """Keep it, in memory and on disk. Never fatal -- a cache that cannot write
    must not cost a transmission."""
    k = _key(voice_id, engine, text)
    _MEM[k] = pcm
    _MEM.move_to_end(k)
    _trim()
    try:
        config.TTS_CACHE.mkdir(parents=True, exist_ok=True)
        tmp = config.TTS_CACHE / f".{k}.tmp"
        tmp.write_bytes(pcm.tobytes())
        tmp.replace(config.TTS_CACHE / f"{k}.pcm")
    except OSError:
        return
    # Every so often rather than every write -- pruning stats the whole
    # directory, and doing that on the transmit path would trade a network
    # round trip for a filesystem one.
    _STATS["writes"] = _STATS.get("writes", 0) + 1
    if _STATS["writes"] % 64 == 0:
        prune()


def _trim() -> None:
    while len(_MEM) > _MEM_MAX:
        _MEM.popitem(last=False)


# NO TTL, AND ON PURPOSE. The key is a hash of (voice, engine, pronounced
# text), so the audio is a pure function of its own key and cannot go stale --
# and if the pronunciation table changes, the pronounced text changes, so the
# key changes, so it re-renders and the old entry is simply an orphan. An
# expiry would only force us to pay again for identical audio.
#
# WHAT DOES NEED A BOUND IS SIZE. Memory is capped by count; disk was capped by
# nothing at all. A typical phrase is about 64 KB of PCM and a full ATIS around
# 700 KB, so a few sorties is tens of megabytes and nothing ever removed any of
# it. Least-recently-USED rather than oldest-written, because the stock phrases
# are old and are exactly the ones worth keeping.
_DISK_MAX_BYTES = 256 * 1024 * 1024


def prune(budget: int = _DISK_MAX_BYTES) -> int:
    """Keep the disk cache under `budget`. Returns bytes removed.

    Never fatal: a cache that cannot tidy itself is still a working cache.
    """
    try:
        files = [(f.stat().st_atime, f.stat().st_size, f)
                 for f in config.TTS_CACHE.glob("*.pcm")]
    except OSError:
        return 0
    total = sum(sz for _, sz, _ in files)
    if total <= budget:
        return 0
    freed = 0
    for _atime, size, f in sorted(files):        # least recently used first
        if total - freed <= budget:
            break
        try:
            f.unlink()
            freed += size
        except OSError:
            pass
    return freed


def cache_stats() -> dict:
    """For `/diag`, because a cache nobody can see is a cache nobody trusts."""
    try:
        on_disk = len(list(config.TTS_CACHE.glob("*.pcm")))
    except OSError:
        on_disk = 0
    try:
        bytes_ = sum(f.stat().st_size for f in config.TTS_CACHE.glob("*.pcm"))
    except OSError:
        bytes_ = 0
    return {"in_memory": len(_MEM), "on_disk": on_disk, "disk_bytes": bytes_,
            "hits": _STATS["hits"], "misses": _STATS["misses"]}


_STATS = {"hits": 0, "misses": 0}


@dataclass
class Voice:
    """A TTS backend. Default is AWS Polly; swap for Piper later."""

    voice_id: str = "Joanna"
    region: str = "us-east-1"
    engine: str = ""            # "" = pick whatever this voice supports
    # Which engine actually answered. A MEMO, kept apart from `engine` so the
    # request stays the request -- see `pcm16k` on why a mutating field cannot
    # be part of a cache key.
    _resolved: str = ""

    def pcm16k(self, text: str) -> np.ndarray:
        """Render `text` to mono 16-bit PCM at 16 kHz (int16 array).

        Polly's newer voices are neural-only and reject the standard engine with
        a ValidationException -- which, mid-rehearsal, kills the run at whichever
        pilot happened to draw that voice. Try standard, fall back to neural, and
        remember which worked so it costs one extra call per voice at most.
        """
        import boto3
        from botocore.exceptions import ClientError

        text = pronounce(text)
        # ALREADY PAID FOR? Checked after `pronounce` so the key is the audio
        # that will actually be produced -- respelling happens first, and two
        # spellings that pronounce identically really are the same recording.
        #
        # KEYED ON WHAT THE CALLER ASKED FOR, never on what answered.
        #
        # `engine` is a dataclass field AND a memo: it starts empty and is
        # overwritten with whichever engine Polly accepted, so its meaning
        # changes under you. Keying the cache on it missed twice for two
        # different reasons -- a fresh Voice looked up "auto" against a stored
        # "standard", and the same Voice looked up "auto" on the first call and
        # "standard" on the second. Two entries, no hits, and the disk layer --
        # the half that survives a restart -- never used at all.
        #
        # So the resolved engine lives in `_resolved` and the field stays the
        # request. Measured after: 0.1 ms on a hit against 211 ms.
        want = self.engine
        got = cached_pcm(self.voice_id, want, text)
        if got is not None:
            _STATS["hits"] += 1
            return got
        _STATS["misses"] += 1

        polly = boto3.client("polly", region_name=self.region)
        engines = [self.engine] if self.engine else (
            [self._resolved] if self._resolved else ["standard", "neural"])
        last: Exception | None = None
        for engine in engines:
            try:
                resp = polly.synthesize_speech(
                    Text=text, OutputFormat="pcm",
                    SampleRate=str(_POLLY_RATE), VoiceId=self.voice_id,
                    Engine=engine)
            except ClientError as e:
                last = e
                continue
            self._resolved = engine
            pcm = np.frombuffer(resp["AudioStream"].read(), dtype="<i2")
            remember_pcm(self.voice_id, want, text, pcm)
            return pcm
        raise last

    def frames(self, text: str) -> list[bytes]:
        """Render `text` and return a list of Opus frames ready for SRS."""
        return pcm_to_opus(self.pcm16k(text))


def pcm_to_opus(pcm16k: np.ndarray) -> list[bytes]:
    """Resample 16 kHz PCM to the SRS rate and encode fixed Opus frames.

    The trailing partial frame is zero-padded so the whole utterance is sent;
    SRS treats the run of frames as one transmission.
    """
    if SRS_SAMPLE_RATE != _POLLY_RATE:
        resampled = soxr.resample(pcm16k.astype(np.float32), _POLLY_RATE, SRS_SAMPLE_RATE)
        pcm = np.clip(np.round(resampled), -32768, 32767).astype("<i2")
    else:
        pcm = pcm16k

    enc = opuslib.Encoder(SRS_SAMPLE_RATE, SRS_CHANNELS, opuslib.APPLICATION_VOIP)
    frames: list[bytes] = []
    n = SAMPLES_PER_FRAME
    full = len(pcm) // n
    for i in range(full):
        chunk = pcm[i * n:(i + 1) * n]
        frames.append(enc.encode(chunk.tobytes(), n))
    rem = len(pcm) - full * n
    if rem:
        last = np.zeros(n, dtype="<i2")
        last[:rem] = pcm[full * n:]
        frames.append(enc.encode(last.tobytes(), n))
    return frames


if __name__ == "__main__":
    import sys

    text = " ".join(sys.argv[1:]) or "Batumi Approach, radio check, how do you read?"
    fr = Voice().frames(text)
    total = sum(len(f) for f in fr)
    print(f'"{text}"')
    print(f"  {len(fr)} Opus frames ({FRAME_MS} ms @ {SRS_SAMPLE_RATE} Hz), "
          f"{len(fr) * FRAME_MS / 1000:.2f}s, {total} bytes")
