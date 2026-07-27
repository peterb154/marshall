"""Ask for a visual approach, and check he gives you one without an argument.

C1, C2 and C3 on the card -- #10.

    C1  asking for a visual gets one, first time. The controller used to refuse
        outright ("I have no visual approach published here") and had to be
        talked into it, which is backwards: the surveillance approach is the
        hard weather case and a visual is what everybody flies on a clear day.
    C2  once cleared visual, the MILE CALLS STOP. Reading ranges to a man
        looking at the runway is chatter over somebody busy, and it is the whole
        difference between a visual approach and a talkdown he did not ask for.
    C3  "field in sight" is a REPORT, not a request. It earns a landing
        clearance and the wind. The two are one word apart and mean opposite
        things, and getting them backwards either denies an approach or clears
        somebody who is still in cloud.

    uv run python tools/visual_check.py

Listens on the radio for C1 and C3, because what matters there is the words a
pilot actually hears. C2 is read from the bridge log instead: "did a mile call
go out for this aircraft?" is a question about what the controller decided, and
absence on the radio could equally mean the metronome had nothing to say.
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


def main() -> int:
    from marshall import config
    from marshall.srs import stt, tts
    from marshall.srs.client import AM, SRSClient, radio
    from marshall.core import route as R

    p = R.BATUMI_ASR
    inbound = (p.final_crs + 180) % 360

    subprocess.run(
        [sys.executable, str(ROOT / "tools" / "spawn.py"),
         "--name", "Hoover 1-1", "--type", "mustang", "--count", "1",
         "--alt", "2500", "--heading", str(int(p.final_crs)),
         "--at", "batumi", "--bearing", str(int(inbound)), "--range", "10",
         "--side", "blue"],
        capture_output=True, env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    time.sleep(12)

    model = stt.load_model()
    voice = tts.Voice(voice_id="Joey")
    c = SRSClient("192.168.0.35", name="Hoover",
                  eam_password=config.SRS_EAM_PASSWORD).connect([radio(HZ, AM)])
    time.sleep(7)

    def say(line: str, wait: float = 32) -> str:
        c.transmit(voice.frames(line), HZ, AM)
        pcm, _ = c.recv_utterance(max_wait=wait, silence=1.6)
        return (stt.transcribe(model, pcm)
                if pcm is not None and pcm.size else "")

    ok = True
    print("C1: asking for a visual")
    say("Batumi Approach, Hoover one one, checking in, one zero miles northwest")
    heard = say("Hoover one one, request the visual approach runway one three")
    low = heard.lower()
    granted = "cleared visual" in low or "visual approach" in low
    refused = any(w in low for w in ("unable", "negative", "not published",
                                     "no visual"))
    good = granted and not refused
    ok = ok and good
    print(f"  {'PASS' if good else 'FAIL'}  granted without an argument")
    print(f"        <- {heard.strip() or '<silence>'}")

    mark = os.path.getsize(LOG) if os.path.exists(LOG) else 0
    print("\nC2: mile calls must stop on a visual")
    time.sleep(30)
    with open(LOG, encoding="utf-8", errors="replace") as fh:
        after = fh.read()[mark:]
    miles = [l for l in after.splitlines() if "ATC[asr]" in l]
    good = not miles
    ok = ok and good
    print(f"  {'PASS' if good else 'FAIL'}  {len(miles)} mile call(s) after the "
          f"visual clearance")
    for l in miles[:3]:
        print(f"        {l.strip()}")

    print("\nC3: 'field in sight' is a report, not a request")
    heard = say("Hoover one one, field in sight")
    low = heard.lower()
    cleared = "cleared to land" in low
    asked_back = "report the field" in low
    good = cleared and not asked_back
    ok = ok and good
    print(f"  {'PASS' if good else 'FAIL'}  answered with a landing clearance")
    if asked_back:
        print("        asked him to report the field he had just reported")
    print(f"        <- {heard.strip() or '<silence>'}")

    try:
        c.close()
    except Exception:
        pass
    print("\nall cases behaved" if ok else "\nSOME CASES FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
