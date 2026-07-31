"""Fly the whole flight sequence with synthetic pilots, over the real radio.

    "I might be able to get Andre to join again tomorrow but we need a battery
     of tests and ai simulations to ensure it works."

[ARCH-4] / #42. The unit tests prove the rules; this proves the PATH -- real
SRS, real Polly, real Whisper, real Bedrock, the live bridge, and aeroplanes
that are genuinely where they say they are.

HOW A SYNTHETIC PILOT BECOMES A REAL ONE. The identity chain matches the SRS
client name against the name radar prints, and both ends are ours to choose: an
SRS client called "Andre" and a spawned unit called "362nd_Andre" resolve
exactly as a human does, because the matcher only ever sees the radar label and
cannot tell the difference. Spawning them a few hundred yards apart makes the
one-mile join rule real rather than mocked.

WHAT THIS CANNOT PROVE, and it must not be read as proving it:

  * that a HUMAN VOICE saying "request creation of Apex flight" survives
    Whisper. This is our Polly against our Whisper, which only shows the two
    agree with each other.
  * anything gated on MANNED. An AI unit reports no player name, so it shows
    as AI, and the elimination rung and the ground-state marker are untouched.

So it gets the logic proven and the phrasing unproven, which is exactly the
split worth knowing before a guest arrives.

    uv run --extra voice python tools/flight_rehearsal.py --srs <host> \\
        --freq 124.0 --session <bridge session>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from marshall import config

# (handle, Polly voice, bearing from Batumi, range, altitude).
#
# Sockeye and Andre are a few hundred yards apart -- inside the one-mile join
# rule. Shooter is ten miles away on purpose: he is the refusal, and a rule
# nobody ever sees refuse is a rule nobody knows works.
FLEET = [
    ("Sockeye", "Joey",    300.0, 14.00, 5000),
    ("Andre",   "Justin",  300.0, 14.15, 5000),
    ("Shooter", "Stephen", 300.0, 24.00, 6000),
]

# The sequence, in the order a flight actually lives it.
# (who speaks, what he says, what should happen)
SCRIPT = [
    ("Sockeye", "Batumi Approach, Sockeye, request creation of Apex flight.",
     "Apex is created with Sockeye as its lead"),
    ("Andre", "Batumi Approach, Andre, joining Apex.",
     "Andre joins -- he is a few hundred yards off Sockeye's wing"),
    ("Shooter", "Batumi Approach, Shooter, joining Apex.",
     "REFUSED: he is ten miles out, and must be inside one to join"),
    ("Andre", "Batumi Approach, Andre, joining Bolt.",
     "REFUSED: there is no Bolt flight, and he is told so rather than ignored"),
    ("Sockeye", "Batumi Approach, Apex flight, one four miles northwest, "
                "four thousand, request the radar approach.",
     "the flight asks as one aeroplane"),
    ("Andre", "Batumi Approach, Andre, separating from Apex flight.",
     "he breaks HIMSELF out and becomes an individual again"),
    ("Andre", "Batumi Approach, Andre, joining Apex.",
     "and rejoins -- which is joining, not a concept of its own"),
]


def spawn(handle: str, bearing: float, rng: float, alt_ft: int) -> bool:
    """Put an aeroplane in the sim whose name carries the handle.

    THE FAILURE IS REPORTED, and it used to be swallowed. `capture_output` with
    `check=False` meant a spawn that never happened looked exactly like one that
    did, so the first run of this harness reported that the flight logic had
    failed when what had actually happened was that `spawn.py` could not reach
    the sim -- it defaults to localhost and the sim is on another host, so every
    aeroplane silently did not exist and the bridge saw "no contacts" for the
    whole script. A rehearsal that cannot tell "the rule is broken" from "there
    was nothing to test" is worse than no rehearsal, because it produces a bug
    report against innocent code.
    """
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "spawn.py"),
         "--name", f"362nd_{handle}", "--type", "mustang", "--at", "BATUMI",
         "--bearing", str(bearing), "--range", str(rng),
         "--alt", str(alt_ft), "--heading", "120"],
        check=False, capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 or "FAILED" in out:
        print(f"  !! could not spawn 362nd_{handle}: "
              f"{out.strip().splitlines()[-1] if out.strip() else r.returncode}")
        return False
    return True


def despawn(handle: str) -> None:
    import os

    from marshall.feed.stubs import bind as _bind_dcs_stubs
    _bind_dcs_stubs()
    import grpc
    from dcs.custom.v0 import custom_pb2, custom_pb2_grpc

    addr = os.environ.get("DCS_GRPC_ADDR", "192.168.0.35:50051")
    lua = (f"local g=Group.getByName('362nd_{handle}') "
           f"if g then g:destroy() return 'ok' end return 'gone'")
    with grpc.insecure_channel(addr) as ch:
        custom_pb2_grpc.CustomServiceStub(ch).Eval(
            custom_pb2.EvalRequest(lua=lua), timeout=20)


def verdicts(session: str, since: float) -> list[dict]:
    """What the bridge decided, from the flight recorder."""
    path = config.BUILD_DIR / "logs" / f"flight-{session}.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("t", 0) >= since and str(e.get("kind", "")).startswith("flight/"):
            out.append(e)
    return out


def run(host: str, freq_mhz: float, session: str, keep: bool = False) -> int:
    from marshall.radio import stt, tts
    from marshall.radio.client import AM, SRSClient, radio

    print("spawning the fleet -- each unit named so its handle matches a radio")
    made = 0
    for handle, _v, brg, rng, alt in FLEET:
        if spawn(handle, brg, rng, alt):
            made += 1
            print(f"  362nd_{handle} at {rng} nm on the {brg:.0f}")
    if made < len(FLEET):
        print(f"\nABORTED: {made} of {len(FLEET)} aeroplanes exist. Every case "
              f"here is about WHERE aircraft are, so a short fleet cannot fail "
              f"honestly -- it can only produce a refusal that looks like the "
              f"rule working.\nCheck DCS_GRPC_ADDR (spawn.py defaults to "
              f"localhost; the sim is usually on another host).")
        return 2
    time.sleep(12)                       # let the track streamer see them

    freq_hz = freq_mhz * 1_000_000
    model = stt.load_model()
    radios, voices = {}, {}
    for handle, voice_id, *_ in FLEET:
        voices[handle] = tts.Voice(voice_id=voice_id)
        radios[handle] = SRSClient(host, name=handle,
                                   eam_password=config.SRS_EAM_PASSWORD).connect(
            [radio(freq_hz, AM)])
        print(f"  radio '{handle}' up ({voice_id})")
        time.sleep(1.0)

    started = time.time()
    print()
    for who, line, expect in SCRIPT:
        client = radios[who]
        client.udp.settimeout(0.0)
        try:
            while True:
                client.udp.recvfrom(4096)
        except OSError:
            pass
        print(f"{who}(tx): {line}")
        print(f"   expect: {expect}")
        client.transmit(voices[who].frames(line), freq_hz, AM)
        pcm, _f = client.recv_utterance(max_wait=30.0, silence=1.6)
        heard = stt.transcribe(model, pcm) if (pcm is not None and pcm.size) else "<no reply>"
        print(f"      ATC: {heard}\n")
        time.sleep(2.5)

    print("--- what the bridge actually did ---")
    got = verdicts(session, started)
    if not got:
        print("  NOTHING RECORDED. The bridge never reached the flight logic, "
              "which is a failure of the run rather than a pass.")
    for e in got:
        extra = f" ({e['miles']} nm)" if e.get("miles") else ""
        print(f"  {e['kind']:18} {e.get('callsign',''):8} "
              f"{e.get('who',''):9}{extra}  {(e.get('text') or '')[:60]}")

    if not keep:
        print("\nremoving the fleet")
        for handle, *_ in FLEET:
            despawn(handle)
    return 0 if got else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--srs", required=True)
    ap.add_argument("--freq", type=float, default=124.0)
    ap.add_argument("--session", required=True,
                    help="the bridge session id, so the run can be scored")
    ap.add_argument("--keep", action="store_true",
                    help="leave the aeroplanes in the sim afterwards")
    args = ap.parse_args()
    return run(args.srs, args.freq, args.session, args.keep)


if __name__ == "__main__":
    raise SystemExit(main())
