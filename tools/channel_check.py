"""Contest the frequency on purpose, and see whether the controller yields.

F2 and F3 on the card -- the mile calls pausing for a pilot and resuming, and
the metronome not filling the seconds while the model composes an answer -- were
marked as needing two humans because "synthetic pilots take turns too politely".

That was true of the earlier harness and not of scripts in general. A script can
contest a channel far more precisely than two people can: it transmits exactly
when a mile call is due, and again the instant the other man stops. Two humans
would struggle to hit those moments deliberately.

    uv run python tools/channel_check.py

It needs an aircraft the controller is actively talking down, so it puts one on
final and requests the approach for it. Then:

  F2  a long transmission across a mile boundary -- the call must be HELD and
      then made, never dropped. A deferred call that vanishes is worse than one
      that steps on you, because you never learn what you missed.

      The aircraft goes ON the final for this, not out at the intercept: the
      metronome only wants the channel when a mile boundary is crossed or a
      vector drifts, so out at fourteen miles a twenty-second transmission can
      pass with nothing wanting to speak -- which reads as a pass and tests
      nothing.
  F3  a second transmission the moment the first ends, inside the gap where the
      model is thinking -- the metronome must not fill it with somebody else's
      mile call.

Reads the bridge log for the verdict rather than the radio, because "was that
call held or lost?" is a question about what the CONTROLLER decided, and the log
says so in as many words.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

if "dcs" not in sys.modules:
    _pkg = types.ModuleType("dcs")
    _pkg.__path__ = [str(ROOT / "director" / "_grpc" / "dcs")]
    sys.modules["dcs"] = _pkg

LOG = os.environ.get("MARSHALL_BRIDGE_LOG", "/tmp/marshall-bridge-live.log")
HZ = float(os.environ.get("MARSHALL_FREQ", "124.0")) * 1e6

LONG = ("Batumi Approach, Hoover one one, this is a deliberately long "
        "transmission to hold the frequency while you are trying to make a "
        "mile call, reading back the heading and the altitude and confirming "
        "that I will report established on the final approach course, still "
        "talking, still talking")


def tail(path: str, since: int) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()[since:].splitlines()
    except OSError:
        return []


def size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def main() -> int:
    from marshall import config
    from marshall.radio import tts
    from marshall.radio.client import AM, SRSClient, radio
    from marshall.core import route as R

    p = R.BATUMI_ASR
    inbound = (p.final_crs + 180) % 360

    print("putting an aircraft on final so there is something to talk down\n")
    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "spawn.py"),
         "--name", "Hoover 1-1", "--type", "mustang", "--count", "1",
         "--alt", "2500", "--heading", str(int(p.final_crs)),
         "--at", "batumi", "--bearing", str(int(inbound)), "--range", "8",
         "--side", "blue"],
        capture_output=True, env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    time.sleep(12)

    voice = tts.Voice(voice_id="Joey")
    lead = SRSClient("192.168.0.35", name="Hoover",
                     eam_password=config.SRS_EAM_PASSWORD).connect([radio(HZ, AM)])
    wing = SRSClient("192.168.0.35", name="Shooter",
                     eam_password=config.SRS_EAM_PASSWORD).connect([radio(HZ, AM)])
    time.sleep(7)

    print("requesting the approach so the metronome starts working him")
    lead.transmit(voice.frames(
        "Batumi Approach, Hoover one one, request the radar approach runway "
        "one three"), HZ, AM)
    time.sleep(22)

    mark = size(LOG)
    print("\nF2: talking across a mile boundary")
    lead.transmit(voice.frames(LONG), HZ, AM)
    time.sleep(25)

    # SEQUENCED, not simultaneous. Transmitting from two clients at once puts
    # overlapping audio on the wire and Whisper returns one garbled utterance --
    # which tests the transcriber, not the controller. F3 is about the gap
    # AFTER a transmission ends, so the second one starts a beat later.
    print("F3: second transmission a beat after the first ends, inside the "
          "model's thinking time")
    wing.transmit(voice.frames(
        "Batumi Approach, Shooter one one, say the altimeter"), HZ, AM)
    time.sleep(1.2)
    lead.transmit(voice.frames("Hoover one one, say again the heading"), HZ, AM)
    time.sleep(30)

    lines = tail(LOG, mark)
    held = [l for l in lines if "holding the" in l or "holding a vector" in l]
    made = [l for l in lines if "ATC[asr]" in l or "ATC[vec]" in l]
    why_pilot = [l for l in held if "a pilot is transmitting" in l]
    why_answer = [l for l in held if "answering a pilot" in l]
    why_read = [l for l in held if "readback window" in l]

    print("\n--- what the controller decided ---")
    for l in held + made:
        print("  " + l.strip())

    print("\n--- verdict ---")
    ok = True
    if not held:
        print("  FAIL  nothing was ever held. Either the metronome had nothing "
              "to say, or it did not yield -- inconclusive, not a pass")
        ok = False
    else:
        print(f"  PASS  {len(held)} call(s) held: "
              f"{len(why_pilot)} for a pilot transmitting, "
              f"{len(why_answer)} while answering one, "
              f"{len(why_read)} in a readback window")
    if held and not made:
        print("  FAIL  held and never made -- a deferred call that vanishes is "
              "worse than one that steps on you")
        ok = False
    elif made:
        print(f"  PASS  {len(made)} call(s) made after yielding, so nothing "
              f"was dropped")

    for c in (lead, wing):
        try:
            c.close()
        except Exception:
            pass
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
