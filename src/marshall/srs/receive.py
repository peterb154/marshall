"""Listen on an SRS frequency and report received voice -- the ears, pre-Whisper.

Connects, tunes to a frequency, and for a window decodes every relayed voice
packet to PCM, saving a WAV and reporting energy so we can confirm we actually
heard a human. Whisper STT plugs in where this saves the WAV.

    uv run --extra voice python -m marshall.srs.receive [host] [freq_mhz] [seconds]
"""

from __future__ import annotations

import sys
import wave

import numpy as np

from marshall.srs import tts
from marshall.srs.client import AM, SRSClient, radio

OUT_WAV = "/tmp/claude-0/-opt-marshall/6446bc5e-63c5-45fd-86a2-b0ca1aae2bb0/scratchpad/heard.wav"


def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.35"
    freq_hz = (float(sys.argv[2]) if len(sys.argv) > 2 else 251.0) * 1_000_000
    secs = float(sys.argv[3]) if len(sys.argv) > 3 else 20.0

    c = SRSClient(host, name="Marshall-EARS", eam_password="362").connect([radio(freq_hz, AM)])
    print(f"listening on {freq_hz/1e6:.3f} MHz AM for {secs:.0f}s (guid {c.guid}) -- transmit now")
    packets, pcm = c.receive(secs)
    c.close()

    if packets and pcm.size:
        rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))
        dur = pcm.size / tts.SRS_SAMPLE_RATE
        with wave.open(OUT_WAV, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(tts.SRS_SAMPLE_RATE)
            w.writeframes(pcm.tobytes())
        print(f"HEARD: {packets} voice packets, {dur:.2f}s audio, RMS {rms:.0f}")
        print(f"  wrote {OUT_WAV}")
        return 0
    print("NOTHING RECEIVED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
