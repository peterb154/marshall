"""Put AI aircraft on the scope, or take them off. For testing with company.

Every serious bug this project has found in the last day needed TWO aircraft to
show itself, and every sortie for a fortnight has flown with one:

  * the clusterer unpacked a fixed-width row, which only raises when two
    contacts are compared -- one aeroplane never reaches that line
  * two AI groups both labelled themselves "Enfield11", so the scope showed one
    name at four miles and the same name at fifteen
  * a ghost holds nobody when there is nobody to hold

So the ability to conjure traffic on demand is a test instrument, not a
convenience. The mission ships the groups late-activated: they exist, they are
not flying, and they cost nothing until asked for.

    uv run python tools/ai_traffic.py            # what is out there
    uv run python tools/ai_traffic.py --up       # activate the test groups
    uv run python tools/ai_traffic.py --down     # remove them, clean board

`--down` DESTROYS rather than deactivates, because DCS has no un-activate: once
a late-activated group is in the world the only way out is to remove it. They
come back with the next mission load, which is what `deploy_mission.sh` does.

A clean board is the default a guest should meet, so `--down` is the state to
leave things in unless somebody is deliberately testing separation.
"""

from __future__ import annotations

import argparse
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
_STUBS = ROOT / "director" / "_grpc"
sys.path.insert(0, str(_STUBS))
if "dcs" not in sys.modules or not hasattr(sys.modules.get("dcs"), "__path__"):
    _pkg = types.ModuleType("dcs")
    _pkg.__path__ = [str(_STUBS / "dcs")]
    sys.modules["dcs"] = _pkg

# The groups build.py adds under --formation and --traffic. Named rather than
# discovered: "activate everything late-activated" would also wake whatever a
# future mission parks for its own reasons.
GROUPS = ("Pony 1", "Traffic")

LIST = """
local out={}
for _,s in pairs({0,1,2}) do
 for _,g in pairs(coalition.getGroups(s, Group.Category.AIRPLANE) or {}) do
  for _,u in pairs(g:getUnits() or {}) do
   local p=u:getPoint()
   out[#out+1]=string.format("%s|%s|%.0f|%s|%s", g:getName(), u:getName(),
     p.y*3.28084, tostring(u:isActive()), tostring(u:getPlayerName() or ""))
  end
 end
end
return table.concat(out,";")
"""


def _eval(stub, pb, lua: str, timeout: float = 20.0) -> str:
    return str(stub.Eval(pb.EvalRequest(lua=lua), timeout=timeout).json).strip('"')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--up", action="store_true", help="activate the test groups")
    g.add_argument("--down", action="store_true", help="remove them (destroys)")
    args = ap.parse_args()

    import grpc
    from dcs.custom.v0 import custom_pb2, custom_pb2_grpc

    addr = os.environ.get("DCS_GRPC_ADDR", "192.168.0.35:50051")
    with grpc.insecure_channel(addr) as ch:
        stub = custom_pb2_grpc.CustomServiceStub(ch)
        for name in GROUPS if (args.up or args.down) else ():
            verb = "activate" if args.up else "destroy"
            lua = (f"local g=Group.getByName('{name}') "
                   f"if g then g:{verb}() return 'ok' end return 'no such group'")
            print(f"{verb} {name!r}: {_eval(stub, custom_pb2, lua)}")
        raw = _eval(stub, custom_pb2, LIST)

    rows = [r.split("|") for r in raw.split(";") if r.count("|") == 4]
    if not rows:
        print("\nno aircraft in the world at all")
        return 0
    print(f"\n{'group':14} {'unit':20} {'alt':>7}  {'flying':6} who")
    for grp, unit, alt, active, player in rows:
        # Late-activated groups are LISTED but not flying. Reading the list as
        # "what is on the scope" is how a dormant four-ship looked like traffic.
        flying = "yes" if active == "true" else "no"
        print(f"{grp[:14]:14} {unit[:20]:20} {float(alt):7.0f}  {flying:6} "
              f"{player or '(AI)'}")
    live = sum(1 for r in rows if r[3] == "true")
    print(f"\n{live} actually flying, {len(rows) - live} dormant")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
