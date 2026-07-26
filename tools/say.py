"""Say one thing on the radio and hear what comes back. One exchange per run.

The synthetic pilot reads a script, and a script is a tape recorder: run against
a real aeroplane, one of them announced "established on the final approach
course" while the aircraft was five miles the wrong side of the field flying its
missed approach. The controller correctly said "negative, not established" --
and that is the problem. With a pilot who says untrue things, a right answer and
a wrong one sound identical, so the transcript proves nothing about the ATC.

This is the other way to test it: a human (or an agent) decides each line, having
seen what the controller just said and where the aeroplane actually is. It is
slower and it is the only way to probe the thing a script cannot -- what happens
when the pilot argues, asks for something odd, or is simply wrong.

    uv run --extra voice python tools/say.py "Batumi Approach, Pony one one, request the radar approach"
    uv run --extra voice python tools/say.py --freq 118.0 "Pony one one, runway in sight"
    uv run --extra voice python tools/say.py --look          # just read the scope

One exchange per process: connect, transmit, listen, transcribe, hang up. That
costs a few seconds of setup per line and keeps the SRS roster clean, which
matters more -- an abandoned client is a second controller on the frequency, and
three of them were once heard talking at once.
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
sys.path.insert(0, str(ROOT / "director" / "_grpc"))
sys.path.insert(0, str(ROOT / "director"))

if "dcs" not in sys.modules:                     # see asr_autopilot.py
    _pkg = types.ModuleType("dcs")
    _pkg.__path__ = [str(ROOT / "director" / "_grpc" / "dcs")]
    sys.modules["dcs"] = _pkg

from marshall import config                                     # noqa: E402
from marshall.core import route as R                            # noqa: E402

SRS_HOST = os.environ.get("SRS_HOST", "192.168.0.35")


def scope(group: str = "") -> str:
    """Where the aeroplane actually is, so a claim can be checked before it is
    made. A pilot who reports a position the radar contradicts is not testing
    the controller, he is testing whether it will believe nonsense."""
    import grpc
    from marshall.atc import asr
    sys.path.insert(0, str(ROOT / "tools"))
    from asr_autopilot import lead_of, position_of

    addr = os.environ.get("DCS_GRPC_ADDR", "127.0.0.1:50051")
    profile = R.BATUMI_ASR
    out = []
    with grpc.insecure_channel(addr) as ch:
        for name in ([group] if group else ["Pony 1", "Traffic"]):
            unit = lead_of(ch, name)
            if unit is None:
                continue
            pos = position_of(unit, profile)
            g = asr.guide(pos, profile)
            along = asr.along_track(pos, profile.final_crs)
            out.append(
                f"{name}: {pos.range_nm:.1f} nm on the {pos.radial_deg:03.0f} "
                f"radial, {pos.alt_ft:,} ft, heading {pos.heading_deg:03.0f} | "
                f"along {along:+.1f}, {g.xtk_nm:+.2f} off | engine says "
                f"{g.phase} {g.heading:03d} at {g.altitude_ft} ft"
                f"{', ' + g.deviation if g.deviation else ''}")
    return "\n".join(out) or "no contacts"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("text", nargs="*", help="what to say")
    ap.add_argument("--freq", type=float, default=124.0)
    ap.add_argument("--voice", default="Joey")
    ap.add_argument("--name", default="Sockeye", help="SRS roster name")
    ap.add_argument("--wait", type=float, default=25.0, help="seconds to listen")
    ap.add_argument("--no-listen", action="store_true",
                    help="transmit and hang up without waiting for a reply")
    ap.add_argument("--look", action="store_true",
                    help="print the radar picture and say nothing")
    ap.add_argument("--group", default="", help="which aircraft, for --look")
    args = ap.parse_args()

    if args.look or not args.text:
        print(scope(args.group))
        return 0

    from marshall.srs import stt, tts
    from marshall.srs.client import AM, SRSClient, radio

    line = " ".join(args.text)
    hz = args.freq * 1_000_000
    client = SRSClient(SRS_HOST, name=args.name,
                       eam_password=config.SRS_EAM_PASSWORD).connect([radio(hz, AM)])
    try:
        import time
        time.sleep(2)                                 # let registration settle
        print(f"PILOT: {line}", flush=True)
        client.transmit(tts.Voice(voice_id=args.voice).frames(line), hz, AM)
        if args.no_listen:
            # For talking TO the pilot rather than to the controller -- an
            # engineer on the frequency answering a debug note. Loading Whisper
            # to hear a reply nobody is going to give costs ten seconds and a
            # gigabyte for nothing.
            time.sleep(0.5)
            return 0
        pcm, _ = client.recv_utterance(max_wait=args.wait, silence=1.5)
        if pcm is None or not pcm.size:
            print("ATC:   <no reply>")
            return 1
        print(f"ATC:   {stt.transcribe(stt.load_model(), pcm)}")
    finally:
        try:
            client.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
