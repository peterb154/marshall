"""Self-test the SRS transmit path with no human in the cockpit.

Connects two clients to the SRS server on the same frequency -- one transmits a
short utterance, the other listens -- and reports whether the server relayed the
voice. This isolates "does our client work" from "was someone tuned in".

    uv run --extra voice python -m marshall.srs.selftest [host] [freq_mhz]
"""

from __future__ import annotations

import sys
import threading
import time

from marshall.srs import tts
from marshall.srs.client import AM, SRSClient, radio
from marshall import config


def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else config.SRS_HOST
    freq_hz = (float(sys.argv[2]) if len(sys.argv) > 2 else 124.0) * 1_000_000

    # External clients must authenticate via External AWACS Mode to be relayed.
    eam = config.SRS_EAM_PASSWORD
    rx = SRSClient(host, name="Marshall-RX", eam_password=eam).connect([radio(freq_hz, AM)])
    tx = SRSClient(host, name="Marshall-TX", eam_password=eam).connect([radio(freq_hz, AM)])
    print(f"RX guid {rx.guid}, TX guid {tx.guid}, freq {freq_hz/1e6:.3f} MHz AM")

    import numpy as np
    result: dict = {}
    listener = threading.Thread(target=lambda: result.__setitem__("rx", rx.receive(9.0)))
    listener.start()
    time.sleep(2.5)  # let the listener settle and the server register both UDP sources

    frames = tts.Voice().frames("Self test, self test, one two three four five.")
    print(f"transmitting {len(frames)} frames ({len(frames)*tts.FRAME_MS/1000:.2f}s)...")
    tx.transmit(frames, freq_hz, AM)
    listener.join()

    packets, pcm = result.get("rx", (0, np.zeros(0, dtype="<i2")))
    dur = pcm.size / tts.SRS_SAMPLE_RATE
    rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2))) if pcm.size else 0.0
    print(f"RX received {packets} packets -> decoded {dur:.2f}s PCM, RMS {rms:.0f}")
    ok = packets > 0 and rms > 50
    print("RESULT:", "TWO-WAY SRS WORKS -- transmit and receive+decode confirmed"
          if ok else "NO RELAY / silent decode")
    tx.close(); rx.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
