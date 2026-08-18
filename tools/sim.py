"""Ask the sim what state it is in, and put it in the right one.

    "Joining the server doesn't unpause it. We've experienced this before."

RIGHT, AND THE REPO KNEW AND COULD NOT ACT. `serverSettings.lua` sets
`pause_on_load = true`, so the sim boots PAUSED after every restart --
including the restart `deploy_mission.sh` performs on purpose. That script
ended by printing "now unpause" at a human and gave them nothing to run.
`SetPaused` has been in the vendored proto the whole time.

    uv run python tools/sim.py status
    uv run python tools/sim.py unpause
    uv run python tools/sim.py pause

`pause_without_clients` is false here, so the sim does NOT pause when the
server empties, and a client arriving does not clear a pause either. The only
thing that unpauses it is `SetPaused(false)` -- this.

WHY A PAUSED SERVER IS HARD TO RECOGNISE, and worth the paragraph because it
cost me a wrong diagnosis I wrote into a commit message: there are two Eval
services and only one of them stops.

    HookService.Eval     hook Lua -- DCS, net, Export        answers when paused
    CustomService.Eval   mission Lua -- coord, timer, world  HANGS when paused

So a paused server answers `GetMissionName`, answers `GetPaused`, reports
healthy in the log, and silently fails every question Marshall actually asks --
`theatre.verify` and the ATIS weather observation both run mission Lua. I read
those timeouts as the scripting environment not having come up after a restart.
It had come up. It was paused, and `status` below now says which.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


# WHERE THE SIM IS. This file used to resolve it privately -- env, else
# `services/.env` -- behind a comment naming exactly the failure that comment
# describes, while thirteen other callers defaulted to localhost or hardcoded a
# LAN address. It lives in `marshall.config` now, with the rest of the
# machine-specific facts, and this is a caller like any other.


def status() -> int:
    """Everything needed to tell a paused sim from an unreachable one."""
    from marshall.feed import dcs as D
    from marshall.feed.stubs import bind
    bind()
    import grpc
    from dcs.custom.v0 import custom_pb2, custom_pb2_grpc
    from dcs.hook.v0 import hook_pb2, hook_pb2_grpc

    print(f"sim at {D.DCS_GRPC_ADDR}")
    with grpc.insecure_channel(D.DCS_GRPC_ADDR) as ch:
        hook = hook_pb2_grpc.HookServiceStub(ch)
        try:
            name = hook.GetMissionName(hook_pb2.GetMissionNameRequest(), timeout=8).name
            paused = hook.GetPaused(hook_pb2.GetPausedRequest(), timeout=8).paused
        except grpc.RpcError as e:
            print(f"  UNREACHABLE: {e.code().name} -- is DCS up, and is the address right?")
            return 2
        print(f"  mission        {name}")
        print(f"  paused         {paused}")
        # THE ONE THAT MATTERS. Marshall's questions run in the mission Lua
        # state, so this line -- not the flag above -- is what says whether the
        # controller can see anything.
        try:
            got = custom_pb2_grpc.CustomServiceStub(ch).Eval(
                custom_pb2.EvalRequest(lua="return timer.getTime()"), timeout=10).json
            print(f"  mission Lua    answering (t={str(got).strip('\"')})")
        except grpc.RpcError:
            print("  mission Lua    NOT ANSWERING -- theatre.verify and the ATIS "
                  "weather will time out")
            if paused:
                print("                 because it is PAUSED. "
                      "`uv run python tools/sim.py unpause`")
            return 1
    return 0


def _set(paused: bool) -> int:
    from marshall.feed import dcs as D
    import grpc
    try:
        now = D.set_paused(paused)
    except grpc.RpcError as e:
        print(f"could not reach the sim: {e.code().name}")
        return 2
    if now != paused:
        print(f"asked for {'paused' if paused else 'running'}, "
              f"sim still reports {'PAUSED' if now else 'RUNNING'}")
        return 1
    print(f"sim is now {'PAUSED' if now else 'RUNNING'}")
    # UNPAUSING IS NOT DONE WHEN THE FLAG FLIPS. What a caller wants is the
    # mission scripting state answering, because that is what the controller,
    # the ATIS and `theatre.verify` all need. Report it rather than leave the
    # next person to discover it as a timeout.
    if not paused:
        print("  mission Lua    " + ("answering" if D.mission_lua_ready()
                                     else "NOT ANSWERING yet -- give it a moment"))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    what = (argv[0] if argv else "status").lower()
    if what == "status":
        return status()
    if what == "unpause":
        return _set(False)
    if what == "pause":
        return _set(True)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
