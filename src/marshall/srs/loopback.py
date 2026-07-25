"""End-to-end self-validation of the voice loop, no human needed.

One Marshall client speaks (Polly TTS), another listens and transcribes
(Whisper) -- exercising TTS -> SRS transmit -> server relay -> SRS receive ->
STT all the way round, and checking the words survive the trip.

    uv run --extra voice --with faster-whisper python -m marshall.srs.loopback [host] [freq_mhz]
"""

from __future__ import annotations

import sys
import threading
import time

import numpy as np

from marshall.srs import tts
from marshall.srs.client import AM, SRSClient, radio
from marshall import config

PHRASES = [
    "Marshall, Pony one one, ten miles south, request the approach.",
    "Batumi Approach, Pony one one, leaving five thousand for the hold.",
    "Pony one one, established on the beam, commencing the letdown.",
]


def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else config.SRS_HOST
    freq_hz = (float(sys.argv[2]) if len(sys.argv) > 2 else 251.0) * 1_000_000

    ears = SRSClient(host, name="Marshall-Ears", eam_password=config.SRS_EAM_PASSWORD).connect([radio(freq_hz, AM)])
    mouth = SRSClient(host, name="Marshall-Mouth", eam_password=config.SRS_EAM_PASSWORD).connect([radio(freq_hz, AM)])
    time.sleep(2.5)  # let both radios register server-side

    from faster_whisper import WhisperModel
    model = WhisperModel("base.en", device="cpu", compute_type="int8")
    print(f"loopback on {freq_hz/1e6:.3f} MHz -- speak/listen x{len(PHRASES)}\n")

    heard_ok = 0
    for phrase in PHRASES:
        box: dict = {}
        t = threading.Thread(target=lambda: box.__setitem__("pcm", ears.recv_utterance(max_wait=15)))
        t.start()
        time.sleep(0.5)
        mouth.transmit(tts.Voice().frames(phrase), freq_hz, AM)
        t.join()

        pcm = box.get("pcm")
        if pcm is None or not pcm.size:
            print(f"SAID : {phrase}\nHEARD: <nothing>\n")
            continue
        segs, _ = model.transcribe(pcm.astype(np.float32) / 32768.0, language="en")
        text = " ".join(s.text for s in segs).strip()
        print(f"SAID : {phrase}\nHEARD: {text}\n")
        if text:
            heard_ok += 1

    print(f"{heard_ok}/{len(PHRASES)} transmissions heard and transcribed")
    ears.close()
    mouth.close()
    return 0 if heard_ok == len(PHRASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
