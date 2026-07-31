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
a late-activated group is in the world the only way out is to remove it.

Which means `--up` cannot simply re-activate what `--down` removed -- the group
is GONE until the next mission load, and the first version of this tool
cheerfully reported "no such group" and left you with an empty sky. So `--up`
SPAWNS when the mission's own groups are not there, using the same mechanism as
tools/spawn.py. A test instrument that only works once is not one.

A clean board is the default a guest should meet, so `--down` is the state to
leave things in unless somebody is deliberately testing separation.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from marshall.feed.stubs import bind as _bind_dcs_stubs

_bind_dcs_stubs()

# The groups build.py adds under --formation and --traffic. Named rather than
# discovered: "activate everything late-activated" would also wake whatever a
# future mission parks for its own reasons.
GROUPS = ("Pony 1", "Traffic")

# What to conjure when the mission's own groups have already been used up. Two
# aeroplanes, because every bug worth catching this week needed TWO -- the
# clusterer, the colliding labels, the ghost that holds somebody.
SPAWN = [("mustang", 300.0, 14.0, 5000),
         ("jug",     320.0, 18.0, 6000)]
SPAWN_NAMES = tuple(f"Traffic {i + 1}" for i in range(len(SPAWN)))


def _spawn(typ: str, bearing: float, range_nm: float, alt_ft: int,
           name: str) -> None:
    """Place one aeroplane, via the same path tools/spawn.py uses."""
    import subprocess
    subprocess.run(
        [sys.executable, str(Path(__file__).parent / "spawn.py"),
         "--name", name, "--type", typ, "--at", "BATUMI",
         "--bearing", str(bearing), "--range", str(range_nm),
         "--alt", str(alt_ft), "--heading", "120"],
        check=False, capture_output=True)


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

    spawned: list[str] = []
    addr = os.environ.get("DCS_GRPC_ADDR", "192.168.0.35:50051")
    with grpc.insecure_channel(addr) as ch:
        stub = custom_pb2_grpc.CustomServiceStub(ch)
        # DOWN must be able to remove everything UP can create, including the
        # groups this tool spawned itself. Otherwise it is a tool that makes
        # traffic it cannot clear, and "clean board" stops being achievable --
        # which is the state a guest is supposed to meet.
        targets = GROUPS if args.up else GROUPS + SPAWN_NAMES
        for name in targets if (args.up or args.down) else ():
            verb = "activate" if args.up else "destroy"
            lua = (f"local g=Group.getByName('{name}') "
                   f"if g then g:{verb}() return 'ok' end return 'no such group'")
            got = _eval(stub, custom_pb2, lua)
            if args.down and got != "ok":
                continue          # already gone is the desired state, not news
            print(f"{verb} {name!r}: {got}")
            if args.up and got != "ok":
                spawned.append(name)
        if spawned:
            # The mission's groups are gone for this load. Conjure equivalents
            # rather than reporting an empty sky and stopping -- what the caller
            # wants is TRAFFIC, not those particular aeroplanes.
            print(f"  ({', '.join(spawned)} not in this mission load -- spawning "
                  f"replacements)")
            for i, (typ, brg, rng, alt) in enumerate(SPAWN):
                _spawn(typ, brg, rng, alt, f"Traffic {i + 1}")
            time.sleep(6)
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
