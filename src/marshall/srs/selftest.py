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


def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.35"
    freq_hz = (float(sys.argv[2]) if len(sys.argv) > 2 else 124.0) * 1_000_000

    # External clients must authenticate via External AWACS Mode to be relayed.
    eam = "362"
    rx = SRSClient(host, name="Marshall-RX", eam_password=eam).connect([radio(freq_hz, AM)])
    tx = SRSClient(host, name="Marshall-TX", eam_password=eam).connect([radio(freq_hz, AM)])
    print(f"RX guid {rx.guid}, TX guid {tx.guid}, freq {freq_hz/1e6:.3f} MHz AM")

    result: dict[str, tuple[int, int]] = {}
    listener = threading.Thread(target=lambda: result.__setitem__("rx", rx.listen(9.0)))
    listener.start()
    time.sleep(1.0)  # let the listener settle and the server register both UDP sources

    frames = tts.Voice().frames("Self test, self test, one two three four five.")
    print(f"transmitting {len(frames)} frames ({len(frames)*tts.FRAME_MS/1000:.2f}s)...")
    tx.transmit(frames, freq_hz, AM)
    listener.join()

    packets, total = result.get("rx", (0, 0))
    print(f"RX received {packets} voice packets ({total} bytes)")
    ok = packets > 0
    print("RESULT:", "RELAY WORKS -- external clients are relayed, EAM not needed"
          if ok else "NO RELAY -- server drops external client audio; enable EXTERNAL_AWACS_MODE")
    tx.close(); rx.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
