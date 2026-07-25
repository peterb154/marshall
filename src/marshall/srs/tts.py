"""Text-to-speech -> Opus frames for the SRS transmit path.

AWS Polly renders 16 kHz PCM (its highest PCM rate). SRS relays a voice packet
whose audio payload is a run of fixed-duration Opus frames at SRS's own sample
rate, so we resample Polly's PCM to that rate and encode fixed frames.

Polly runs on the LXC (verified working) -- NOT on the DCS box via DCS-gRPC.
The provider is swappable: a Piper backend (offline) drops in behind the same
`Voice.frames()` seam without the SRS client caring.

    uv run --extra voice python -m marshall.srs.tts "Batumi Approach, radio check"
"""

from __future__ import annotations

from dataclasses import dataclass

import re

import numpy as np
import opuslib
import soxr

from marshall import config

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
# Plain respelling rather than SSML <phoneme> tags on purpose: it needs no
# change to how we call synthesize_speech, it cannot produce malformed markup
# mid-transmission, and anyone can add a line after hearing a word come out
# wrong. The cost is that the fix lives in the audio and not in the transcript,
# which is the right trade for a radio.
#
# "readback" is the one that started this: Polly reads it as the past tense --
# "RED-back" -- because that is the commoner English word. A controller says
# "REED-back".
SAY_AS = {
    "readback": "reed back",
    "readbacks": "reed backs",
    "Batumi": "Bah too mee",
    "Kobuleti": "Koh boo LEH tee",
    "Senaki": "Seh NAH kee",
    "Kutaisi": "Koo tah EE see",
    "Sukhumi": "Soo KHOO mee",
    "Vaziani": "Vah zee AH nee",
}
# Only words actually heard to come out wrong go in here. Guessing at
# pronunciations Polly already gets right is how you end up "fixing" roger into
# something worse.

_SAY_AS_RE = re.compile(
    r"\b(" + "|".join(sorted(SAY_AS, key=len, reverse=True)) + r")\b", re.I)


def pronounce(text: str) -> str:
    """Respell the handful of words Polly mangles, preserving capitalisation."""
    def sub(m):
        word = m.group(1)
        said = SAY_AS.get(word) or SAY_AS.get(word.lower()) or word
        if word[:1].isupper():
            return said[:1].upper() + said[1:]
        return said[:1].lower() + said[1:]
    return _SAY_AS_RE.sub(sub, text or "")


@dataclass
class Voice:
    """A TTS backend. Default is AWS Polly; swap for Piper later."""

    voice_id: str = "Joanna"
    region: str = "us-east-1"
    engine: str = ""            # "" = pick whatever this voice supports

    def pcm16k(self, text: str) -> np.ndarray:
        """Render `text` to mono 16-bit PCM at 16 kHz (int16 array).

        Polly's newer voices are neural-only and reject the standard engine with
        a ValidationException -- which, mid-rehearsal, kills the run at whichever
        pilot happened to draw that voice. Try standard, fall back to neural, and
        remember which worked so it costs one extra call per voice at most.
        """
        import boto3
        from botocore.exceptions import ClientError

        polly = boto3.client("polly", region_name=self.region)
        text = pronounce(text)
        engines = [self.engine] if self.engine else ["standard", "neural"]
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
            self.engine = engine
            return np.frombuffer(resp["AudioStream"].read(), dtype="<i2")
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
