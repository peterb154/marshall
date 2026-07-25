"""Live, agent-driven ATC session over SRS.

A persistent Marshall client monitors every flight-plan channel, transcribes
each over to a transcript file, and transmits whatever gets queued in a command
file. The agent (Claude) reads the transcript, decides, and writes 'freq|text'
commands -- a human-in-the-loop controller where the "human" is the model. Break
the 4th wall freely; it's a learning session, not a scripted state machine.

    uv run --extra voice python -m marshall.srs.atc_session <run_dir> [host] [minutes]

In <run_dir>:
    transcript.log   append-only: "MM:SS  chB 128.000 Batumi Approach | <text>"
    command.txt      append-only; the agent writes "128.000|Pony 1-1, descend 4000"
    stop             touch this file to end early
"""

from __future__ import annotations

import os
import sys
import threading
import time


from marshall.core import route as R
from marshall.srs import tts
from marshall.srs.client import AM, SRSClient, radio

# Flight-plan channels A/B/C, straight from the single source of truth.
CHANNELS = [(f.freq_mhz, chr(ord("A") + i), f.sector or f.name)
            for i, f in enumerate(R.FIXES)]


def chan_for(freq_hz: float | None) -> tuple[str, float, str]:
    if freq_hz is None:
        return "?", 0.0, ""
    mhz = freq_hz / 1e6
    for f, label, name in CHANNELS:
        if abs(f - mhz) < 0.01:
            return label, f, name
    return "?", mhz, ""


def main() -> int:
    run_dir = sys.argv[1]
    host = sys.argv[2] if len(sys.argv) > 2 else "192.168.0.35"
    minutes = float(sys.argv[3]) if len(sys.argv) > 3 else 30.0
    # Extra MHz freqs after minutes are added as ad-hoc channels (e.g. 105.0),
    # so Marshall can meet a pilot wherever they happen to be tuned.
    for i, mhz in enumerate(float(x) for x in sys.argv[4:]):
        CHANNELS.append((mhz, f"X{i+1}", "manual"))

    os.makedirs(run_dir, exist_ok=True)
    transcript = os.path.join(run_dir, "transcript.log")
    command = os.path.join(run_dir, "command.txt")
    stop = os.path.join(run_dir, "stop")
    open(transcript, "a").close()
    open(command, "a").close()

    radios = [radio(mhz * 1e6, AM) for mhz, _, _ in CHANNELS]
    c = SRSClient(host, name="Marshall", eam_password="362").connect(radios)
    print("Marshall up on " + ", ".join(f"{l} {m:.3f}" for m, l, _ in CHANNELS), flush=True)

    from marshall.srs import stt
    model = stt.load_model()
    print("whisper ready; listening", flush=True)

    t0 = time.monotonic()
    stamp = lambda: f"{int(time.monotonic()-t0)//60:02d}:{int(time.monotonic()-t0)%60:02d}"
    lock = threading.Lock()

    def listen() -> None:
        while not os.path.exists(stop):
            pcm, freq = c.recv_utterance(max_wait=5, silence=1.1)
            if pcm is None or not pcm.size:
                continue
            text = stt.transcribe(model, pcm)
            if not text:
                continue
            label, mhz, name = chan_for(freq)
            line = f"{stamp()}  ch{label} {mhz:.3f} {name} | {text}"
            with lock, open(transcript, "a") as fh:
                fh.write(line + "\n")
            print("RX " + line, flush=True)

    def commander() -> None:
        pos = 0
        while not os.path.exists(stop):
            with open(command) as fh:
                # Only newline-terminated lines are complete; the tail after the
                # last "\n" may be a partial write, so drop it.
                complete = fh.read().split("\n")[:-1]
            while pos < len(complete):
                ln, pos = complete[pos].strip(), pos + 1
                if not ln or "|" not in ln:
                    continue
                freqs, text = ln.split("|", 1)
                try:
                    fhz = float(freqs) * 1e6
                except ValueError:
                    continue
                print(f"TX {stamp()}  {freqs} | {text.strip()}", flush=True)
                c.transmit(tts.Voice().frames(text.strip()), fhz, AM)
            time.sleep(0.3)

    threading.Thread(target=listen, daemon=True).start()
    threading.Thread(target=commander, daemon=True).start()

    end = time.monotonic() + minutes * 60
    while time.monotonic() < end and not os.path.exists(stop):
        time.sleep(1)
    c.close()
    print("session ended", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
