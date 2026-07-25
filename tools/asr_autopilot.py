"""Fly an AI aircraft down the ASR, from the deterministic engine, in the sim.

The synthetic sweep flies 1,296 approaches in a fifth of a second, and it is
worth exactly as much as its model of an aeroplane: a point that turns at three
degrees a second and never overshoots. This flies the same engine against a real
airframe in DCS -- real inertia, real bank, real wind -- and it is the only way
to find out whether the geometry that converges on paper converges in the air.

The loop is the live one, minus the radio. Radar in (gRPC, the same scan the
bridge reads), `asr.guide` for the instruction, and the heading back out through
a user flag to `ai_control.lua`, which is where DCS keeps the tasking API. What
comes out of the engine here is byte for byte what the controller would say.

    uv run python tools/asr_autopilot.py --group Traffic --activate

Watch it from the sim: the aircraft should reposition to the entry gate if it
needs to, cut across at 45 degrees, blend onto the final approach course and
come down the descent profile to the missed approach point.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "director" / "_grpc"))
sys.path.insert(0, str(ROOT / "director"))

# `dcs` is claimed by two different things and only one of them can win by path
# order: pydcs, which the mission builder needs, and the generated DCS-gRPC
# stubs under director/_grpc. The stubs are a namespace package and pydcs is a
# regular one, and a regular package shuts the search down -- so on any
# interpreter that can see pydcs, every `dcs.trigger` import fails no matter
# where _grpc sits on the path. The director never hits this because its
# container has no pydcs. Binding the name to the stub tree up front, before
# anything imports either, is the whole fix; this process wants the stubs and
# has no use for pydcs.
if "dcs" not in sys.modules:
    import types
    _pkg = types.ModuleType("dcs")
    _pkg.__path__ = [str(ROOT / "director" / "_grpc" / "dcs")]
    sys.modules["dcs"] = _pkg

import grpc                                                    # noqa: E402

from marshall.atc import asr                                   # noqa: E402
from marshall.core import route as R                           # noqa: E402

ADDR = os.environ.get("DCS_GRPC_ADDR", "127.0.0.1:50051")
POLL_SEC = 4.0

# Only re-task on a real change. DCS AI re-flies its route from scratch on every
# setTask, so nudging it every four seconds by a degree produces an aeroplane
# that rolls continuously and never settles -- the sim's version of the dither
# the engine itself just stopped doing.
MIN_TURN_DEG = 5
MIN_ALT_FT = 300


def _grpc_bits():
    from dcs.coalition.v0 import coalition_pb2, coalition_pb2_grpc
    from dcs.common.v0 import common_pb2
    from dcs.group.v0 import group_pb2, group_pb2_grpc
    from dcs.trigger.v0 import trigger_pb2, trigger_pb2_grpc
    return (coalition_pb2, coalition_pb2_grpc, common_pb2,
            group_pb2, group_pb2_grpc, trigger_pb2, trigger_pb2_grpc)


def lead_of(ch, group_name: str):
    """The lead unit's position and heading, or None if it is not flying yet."""
    _, _, _, group_pb2, group_pb2_grpc, _, _ = _grpc_bits()
    stub = group_pb2_grpc.GroupServiceStub(ch)
    try:
        units = stub.GetUnits(group_pb2.GetUnitsRequest(
            group_name=group_name, active=True), timeout=5).units
    except grpc.RpcError:
        return None
    return units[0] if units else None


def position_of(unit, profile) -> asr.Position:
    """A gRPC unit -> the radar picture the engine works from."""
    from tools.dcs import _bearing_range          # the bridge's own conversion
    brg, rng = _bearing_range(unit.position.lat, unit.position.lon)
    return asr.Position(rng, brg,
                        int(unit.position.alt * 3.28084),
                        unit.orientation.heading)


def set_flag(ch, name: str, value: int) -> None:
    _, _, _, _, _, trigger_pb2, trigger_pb2_grpc = _grpc_bits()
    trigger_pb2_grpc.TriggerServiceStub(ch).SetUserFlag(
        trigger_pb2.SetUserFlagRequest(flag=name, value=value), timeout=5)


def activate(ch, group_name: str) -> None:
    _, _, _, group_pb2, group_pb2_grpc, _, _ = _grpc_bits()
    try:
        group_pb2_grpc.GroupServiceStub(ch).Activate(
            group_pb2.ActivateRequest(group_name=group_name), timeout=5)
        print(f"activated {group_name}")
    except grpc.RpcError as e:
        print(f"activate {group_name}: {e.details()}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--group", default="Traffic", help="AI group to vector")
    ap.add_argument("--activate", action="store_true",
                    help="call the group in first (it spawns late-activated)")
    ap.add_argument("--minutes", type=float, default=25.0)
    ap.add_argument("--callsign", default="Traffic one one",
                    help="what the controller calls the AI on the radio")
    ap.add_argument("--srs", metavar="HOST",
                    help="also TRANSMIT each call on the approach frequency, so "
                         "the run can be listened to as well as watched")
    args = ap.parse_args()

    profile = R.BATUMI_ASR
    grp_flag = 2 if args.group.lower().startswith("pony") else 1
    print(f"ASR autopilot -> {args.group} at {profile.beacon.name}, "
          f"runway {profile.runway}, course {profile.final_crs:03d}")
    print(f"  IF {profile.final_intercept_nm:.0f} nm at {profile.iaf_alt_ft} ft, "
          f"FAP {profile.fap_nm:.0f} nm, MDA {profile.mda_ft} ft")
    print(f"  gRPC {ADDR}\n")

    # Transmit-only: this opens a radio to talk on and never listens. The
    # bridge is already on these frequencies, and two clients that both hear
    # and answer on one channel spent an evening talking to each other.
    #
    # The client is registered for teardown before anything can fail, and the
    # signals are caught, because an abandoned run does not just waste a socket
    # -- it leaves a SECOND Batumi Approach on the frequency, transmitting its
    # own aircraft's vectors over the top of the live one. Three of them were
    # heard talking simultaneously before this was here.
    say = None
    srs = None
    if args.srs:
        import atexit
        import signal

        from marshall.atc import agent_atc
        from marshall.srs import tts
        from marshall.srs.client import AM, SRSClient, radio

        station = profile.station_for("approach") or profile.stations[0]
        hz = station.freq_mhz * 1_000_000
        srs = SRSClient(args.srs, name=f"{station.name} (ASR)").connect(
            [radio(hz, AM)])
        voice = tts.Voice(voice_id=station.voice)
        print(f"transmitting as {station.name} on {station.freq_mhz:.3f} "
              f"in {station.voice}'s voice\n")

        def hang_up(*_):
            try:
                srs.close()
            except Exception:
                pass

        atexit.register(hang_up)
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, lambda s, f: sys.exit(0))    # runs atexit

        # Talking must not stop him watching the scope. Rendering a call costs a
        # round trip to Polly and transmitting it takes as long as the words do,
        # and doing both inline stretched a four-second radar look to nearly ten
        # -- the aircraft moved eight hundred yards between looks while the
        # controller had his mouth open. A real controller does not stop seeing
        # when he keys the mic.
        #
        # One worker, one queue, and the queue is deliberately shallow: if calls
        # are arriving faster than they can be spoken, the newest is the only
        # one still true, and a backlog of stale range calls is worse than
        # silence. Dropped calls are counted rather than hidden, because a
        # talk-down that quietly stops talking looks identical to one that has
        # nothing to say.
        import queue
        import threading

        pending: "queue.Queue[str]" = queue.Queue(maxsize=1)
        dropped = 0

        def radio_worker():
            while True:
                text = pending.get()
                if text is None:
                    return
                try:
                    srs.transmit(voice.frames(text), hz, AM)
                except Exception as e:               # a radio is not the point
                    print(f"   (transmit failed: {e})")

        threading.Thread(target=radio_worker, daemon=True).start()

        def say(text: str) -> None:
            nonlocal dropped
            try:
                pending.put_nowait(text)
            except queue.Full:
                dropped += 1
                print(f"   (still talking — dropped a call, {dropped} so far)")

    last_hdg, last_alt = None, None
    last_said_nm = None
    deadline = time.time() + args.minutes * 60
    with grpc.insecure_channel(ADDR) as ch:
        if args.activate:
            activate(ch, args.group)
            time.sleep(3)
        set_flag(ch, "ai_grp", grp_flag)
        last_kts = 0

        while time.time() < deadline:
            unit = lead_of(ch, args.group)
            if unit is None:
                print("  ... no contact")
                time.sleep(POLL_SEC)
                continue

            pos = position_of(unit, profile)
            g = asr.guide(pos, profile)
            along = asr.along_track(pos, profile.final_crs)

            turned = last_hdg is None or abs(asr.angle_diff(g.heading, last_hdg)) >= MIN_TURN_DEG
            climbed = (last_alt is None or g.altitude_ft is None
                       or abs(g.altitude_ft - last_alt) >= MIN_ALT_FT)
            kts = int(g.speed_kt or profile.speed_kt)
            slowed = kts != last_kts
            if turned or climbed or slowed:
                hdg = g.heading if turned else last_hdg
                alt = g.altitude_ft if climbed else last_alt
                set_flag(ch, "ai_hdg", int(hdg))
                set_flag(ch, "ai_alt", int((alt or profile.platform_ft) / 100))
                set_flag(ch, "ai_kts", kts)
                set_flag(ch, "ai_vector", 1)
                last_hdg, last_alt, last_kts = hdg, alt, kts
                mark = "<<"
            else:
                mark = "  "

            print(f"{mark} {pos.range_nm:5.1f} nm / {pos.radial_deg:03.0f}  "
                  f"along {along:+6.1f}  off {g.xtk_nm:+5.2f}  "
                  f"{unit.position.alt * 3.28084:5.0f} ft hdg {pos.heading_deg:03.0f}"
                  f"   ->  {g.phase:6s} heading {g.heading:03d}"
                  f"{f', {g.altitude_ft} ft' if g.altitude_ft else ''}"
                  f"  {kts:3d} kt  [{g.deviation}]")

            # What a controller would actually say, and when he would say it: a
            # turn as it is given, and otherwise one call per mile on final. Not
            # every radar look -- a call every four seconds is not a talk-down,
            # it is a man shouting.
            if say:
                if g.phase == "map":
                    say(agent_atc.asr_call(args.callsign, g))
                elif g.established or turned:
                    mile = int(round(g.range_nm))
                    if turned or mile != last_said_nm:
                        say(agent_atc.asr_call(args.callsign, g))
                        last_said_nm = mile

            if g.phase == "map":
                print("\nmissed approach point — approach complete")
                return 0
            time.sleep(POLL_SEC)

    print("\ntime limit reached")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
