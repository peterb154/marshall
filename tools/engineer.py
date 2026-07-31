"""A radio that stays on the frequency, so engineering can answer instantly.

`say.py` opens an SRS client, waits two seconds, transmits and hangs up. That is
fine for a scripted test and useless for talking to a pilot: SRS has not
finished propagating a brand-new client to the other listeners before the audio
starts, so the transmission goes out to nobody. A pilot could hear the beacon
and the controller and not a word from me, which is exactly what a client that
never really joined looks like from the other end.

This one connects once and stays. Anything written to the spool file is spoken
on the next tick and the line is consumed, which makes "talk to the pilot" a
single append from anywhere -- no SRS knowledge, no connection dance, no
Whisper, no model.

    uv run --extra voice python tools/engineer.py --freq 124.0 &
    echo "Sakai, engineering, I have a fix ready" >> /tmp/marshall-say

Transmit only. It never listens, because the pilot's words already reach us
through the bridge's own transcription -- a second listener on the channel would
be a second thing to keep in step, and there is nothing it could learn that the
debug notes do not already carry.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

if "dcs" not in sys.modules:                     # see asr_autopilot.py
    _pkg = types.ModuleType("dcs")
    _pkg.__path__ = [str(ROOT / "director" / "_grpc" / "dcs")]
    sys.modules["dcs"] = _pkg

from marshall import config

SPOOL = Path("/tmp/marshall-say")
SRS_HOST = os.environ.get("SRS_HOST", "192.168.0.35")

# How long to let SRS settle before the first transmission. The whole reason
# this file exists: two seconds was not enough and the audio went nowhere.
SETTLE_SEC = 6.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--freq", type=float, default=124.0)
    ap.add_argument("--voice", default="Amy")
    ap.add_argument("--name", default="Engineering")
    ap.add_argument("--spool", default=str(SPOOL))
    args = ap.parse_args()

    from marshall.radio import tts
    from marshall.radio.client import AM, SRSClient, radio

    spool = Path(args.spool)
    spool.touch(exist_ok=True)
    hz = args.freq * 1_000_000
    voice = tts.Voice(voice_id=args.voice)
    client = SRSClient(SRS_HOST, name=args.name,
                       eam_password=config.SRS_EAM_PASSWORD).connect([radio(hz, AM)])
    print(f"{args.name} on {args.freq:.3f} in {args.voice}'s voice; "
          f"append lines to {spool}", flush=True)
    time.sleep(SETTLE_SEC)
    print("settled and ready", flush=True)

    try:
        while True:
            try:
                lines = [l for l in spool.read_text().splitlines() if l.strip()]
            except OSError:
                lines = []
            if lines:
                spool.write_text("")            # consume before speaking, so a
                                                # slow transmission cannot repeat
                for line in lines:
                    print(f"TX: {line}", flush=True)
                    try:
                        client.transmit(voice.frames(line), hz, AM)
                    except Exception as e:      # a radio is not worth crashing for
                        print(f"  !! transmit failed: {e}", flush=True)
                    time.sleep(0.4)
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            client.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
