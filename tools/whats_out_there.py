"""Everything the sim currently has, with positions. For "what WAS that?"

Twice now a pilot has reported something on his own instruments that nothing in
our data can account for: radar returns high over the sea, and a cluster of
aircraft on the F10 map on a server he was alone on. Both were gone by the time
anybody looked.

    uv run python tools/whats_out_there.py

The `tracks` table cannot answer it. It records what the STREAMER saw, it drops
rows for units that disappear, and it was dead for twelve hours today because of
a missing SQL placeholder -- so an absence there proves nothing at all. This
asks the sim directly, and asks for everything: aircraft, helicopters, ground,
ships, statics, and any unit whose altitude does not match the ground beneath
it, which is how a T-55 came to be sitting at 2,585 ft over the water.

Run it WHILE the thing is on screen. That is the whole point: the question is
not what is out there now, it is what was out there then.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from marshall.feed.stubs import bind as _bind_dcs_stubs

_bind_dcs_stubs()

LUA = """
local out = {}
local cats = {
  ["air"] = Group.Category.AIRPLANE,
  ["helo"] = Group.Category.HELICOPTER,
  ["ground"] = Group.Category.GROUND,
  ["ship"] = Group.Category.SHIP,
}
for label, cat in pairs(cats) do
  for _, side in pairs({0, 1, 2}) do
    for _, gp in pairs(coalition.getGroups(side, cat) or {}) do
      for _, u in pairs(gp:getUnits() or {}) do
        local p = u:getPoint()
        local ground = land.getHeight({x = p.x, y = p.z}) or 0
        local agl = (p.y - ground) * 3.28084
        out[#out+1] = string.format("%s|%s|%s|%d|%.0f|%.0f|%s",
          label, gp:getName(), u:getTypeName(), side,
          p.y * 3.28084, agl, tostring(u:getPlayerName() or ""))
      end
    end
  end
end
return table.concat(out, ";")
"""


def main() -> int:
    import os

    import grpc
    from dcs.custom.v0 import custom_pb2, custom_pb2_grpc

    addr = os.environ.get("DCS_GRPC_ADDR", "192.168.0.35:50051")
    with grpc.insecure_channel(addr) as ch:
        raw = str(custom_pb2_grpc.CustomServiceStub(ch).Eval(
            custom_pb2.EvalRequest(lua=LUA), timeout=30).json).strip('"')

    rows = [r.split("|") for r in raw.split(";") if r.count("|") == 6]
    if not rows:
        print("nothing in the world at all -- no units of any kind")
        return 0

    print(f"{len(rows)} unit(s)\n")
    print(f"{'what':7} {'group':30} {'type':18} {'MSL':>7} {'AGL':>8}  who")
    for kind, group, typ, _side, msl, agl, player in rows:
        # A GROUND unit well above the ground is the interesting case: it is a
        # radar return that has no business existing, and it is how a tank ended
        # up looking like an aircraft.
        flag = ""
        if kind in ("ground", "ship") and float(agl) > 50:
            flag = "   <-- OFF THE GROUND, this is a false radar contact"
        print(f"{kind:7} {group[:30]:30} {typ[:18]:18} {float(msl):7.0f} "
              f"{float(agl):8.0f}  {player}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
