"""A live SRS conversation: Marshall listens, transcribes, and answers.

One persistent client. It greets, then for each pilot 'over': decode the audio,
transcribe with Whisper, and read the words back via Polly. The deterministic
ATC brain (atc/controller.py + the intent seam) wires in where the readback is;
for now Marshall just proves it hears you and can answer on the same radio.

    uv run --extra voice python -m marshall.srs.converse [host] [freq_mhz] [exchanges]
"""

from __future__ import annotations

import sys
import time

import numpy as np

from marshall.srs import tts
from marshall.srs.client import AM, SRSClient, radio


def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.35"
    freq_hz = (float(sys.argv[2]) if len(sys.argv) > 2 else 251.0) * 1_000_000
    exchanges = int(sys.argv[3]) if len(sys.argv) > 3 else 5

    c = SRSClient(host, name="Marshall", eam_password="362").connect([radio(freq_hz, AM)])
    from faster_whisper import WhisperModel
    model = WhisperModel("base.en", device="cpu", compute_type="int8")

    def say(text: str) -> None:
        print(f"MARSHALL: {text}", flush=True)
        c.transmit(tts.Voice().frames(text), freq_hz, AM)

    time.sleep(3.0)  # let registration settle so the first over isn't dropped
    say(f"This is Marshall on {freq_hz/1e6:.3f}, radio check, go ahead.")

    for _ in range(exchanges):
        pcm, _freq = c.recv_utterance(max_wait=45)
        if pcm is None or not pcm.size:
            say("Marshall, nothing heard, standing by.")
            continue
        segs, _ = model.transcribe(pcm.astype(np.float32) / 32768.0, language="en")
        text = " ".join(s.text for s in segs).strip()
        print(f"PILOT   : {text}", flush=True)
        if not text:
            continue
        say(f"Marshall copies. {text}")

    say("Marshall out.")
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
