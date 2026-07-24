"""DCS-gRPC tools for the mission director — live world queries and control.

Live state (unit positions, spawning, mission control) comes from DCS-gRPC on the
sim server. Static map data (airports, navaids, beacons) belongs in PostGIS and is
served by separate tools; this module is the *live* half.

The gRPC stubs are generated from the DCS-gRPC protos and vendored under `_grpc/`
(added to sys.path in app.py). `DCS_GRPC_ADDR` defaults to the LAN sim server.
"""

from __future__ import annotations

import os

import grpc

try:
    from strands import tool
except ImportError:                     # allow import on a host without strands
    def tool(fn):
        return fn

from dcs.coalition.v0 import coalition_pb2, coalition_pb2_grpc
from dcs.common.v0 import common_pb2
from dcs.hook.v0 import hook_pb2, hook_pb2_grpc

DCS_GRPC_ADDR = os.environ.get("DCS_GRPC_ADDR", "192.168.0.35:50051")
_TIMEOUT = 8.0


def _channel() -> grpc.Channel:
    return grpc.insecure_channel(DCS_GRPC_ADDR)


@tool
def get_current_mission() -> str:
    """Return the name and .miz filename of the mission currently loaded on the
    DCS server. Use this to confirm which scenario is running."""
    with _channel() as ch:
        hook = hook_pb2_grpc.HookServiceStub(ch)
        name = hook.GetMissionName(hook_pb2.GetMissionNameRequest(), timeout=_TIMEOUT).name
        path = hook.GetMissionFilename(hook_pb2.GetMissionFilenameRequest(), timeout=_TIMEOUT).name
        return f"Current mission: {name}  (file: {path.replace(chr(92), '/').split('/')[-1]})"


@tool
def load_mission(file_name: str) -> str:
    """Hot-load a mission on the DCS server, live, with no server restart. Takes
    the FULL server-side path to the .miz. Players drop to the load screen and the
    new mission comes up."""
    with _channel() as ch:
        hook = hook_pb2_grpc.HookServiceStub(ch)
        hook.LoadMission(hook_pb2.LoadMissionRequest(file_name=file_name), timeout=_TIMEOUT)
        return f"Loading mission: {file_name}"


@tool
def get_player_units() -> str:
    """List the human-piloted aircraft currently on the server, with type,
    position (lat/lon), altitude, and heading. This is the god's-eye view of who
    is flying and where."""
    lines: list[str] = []
    with _channel() as ch:
        coal = coalition_pb2_grpc.CoalitionServiceStub(ch)
        for side in (common_pb2.COALITION_BLUE, common_pb2.COALITION_RED):
            try:
                resp = coal.GetPlayerUnits(
                    coalition_pb2.GetPlayerUnitsRequest(coalition=side), timeout=_TIMEOUT)
            except grpc.RpcError:
                continue
            for u in resp.units:
                who = u.player_name or u.callsign or u.name
                lines.append(
                    f"{who} ({u.type}) — {u.position.lat:.4f}, {u.position.lon:.4f}, "
                    f"{u.position.alt:.0f} m, heading {u.orientation.heading:.0f}")
    return "\n".join(lines) if lines else "No player-controlled units on the server right now."
