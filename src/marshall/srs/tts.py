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


@dataclass
class Voice:
    """A TTS backend. Default is AWS Polly; swap for Piper later."""

    voice_id: str = "Joanna"
    region: str = "us-east-1"

    def pcm16k(self, text: str) -> np.ndarray:
        """Render `text` to mono 16-bit PCM at 16 kHz (int16 array)."""
        import boto3

        polly = boto3.client("polly", region_name=self.region)
        resp = polly.synthesize_speech(
            Text=text, OutputFormat="pcm",
            SampleRate=str(_POLLY_RATE), VoiceId=self.voice_id)
        return np.frombuffer(resp["AudioStream"].read(), dtype="<i2")

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
