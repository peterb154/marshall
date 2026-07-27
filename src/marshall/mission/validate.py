"""Pre-flight check on the built .miz.

Every assertion here corresponds to something that actually broke and cost a
flight. DCS reports a malformed mission as a bare load failure with nothing
useful in the log, so it is far cheaper to check here.

    uv run python validate.py
"""

import re
import sys
import zipfile

from marshall.core import route as R
from marshall import config

MIZ = config.MISSION_OUT / "362nd-Blind-Flying.miz"

problems: list[str] = []
notes: list[str] = []


def check(ok: bool, msg: str) -> None:
    (notes if ok else problems).append(("PASS  " if ok else "FAIL  ") + msg)


zf = zipfile.ZipFile(MIZ)
names = set(zf.namelist())
mission = zf.read("mission").decode("utf-8", "ignore")
resource = zf.read("l10n/DEFAULT/mapResource").decode("utf-8", "ignore")

for required in ("mission", "options", "warehouses", "theatre",
                 "l10n/DEFAULT/dictionary", "l10n/DEFAULT/mapResource"):
    check(required in names, f"miz contains {required}")
check(bool(re.search(r'\["theatre"\]\s*=\s*"Caucasus"', mission)),
      "theatre is Caucasus")

# --- the script -------------------------------------------------------------
trig = mission[mission.find('["trig"]'):]
check("a_radio_transmission" not in trig,
      "no mission-editor radio transmissions (that path is silently broken)")
check("a_do_script(getValueDictByKey" not in trig,
      "no DoScript-from-dictionary (getValueDictByKey returns the key, not the text)")
check("a_do_script_file" in trig, "script loaded from a resource file")

lua_members = [n for n in names if n.endswith(".lua") and "Avionics" not in n]
check(len(lua_members) == 1, f"exactly one mission script ({len(lua_members)})")
if lua_members:
    body = zf.read(lua_members[0]).decode("utf-8", "ignore")
    check('"l10n/DEFAULT/" .. b.file' in body,
          "beacon filenames carry the l10n/DEFAULT/ prefix -- THE fix")
    try:
        from luaparser import ast
        ast.parse(body)
        check(True, "mission script parses as Lua")
    except ImportError:
        notes.append("SKIP  lua syntax check (luaparser missing)")
    except Exception as exc:
        check(False, f"script is not valid Lua: {str(exc).splitlines()[0][:80]}")

    for fix in R.FIXES:
        check(f'ident="{fix.ident}"' in body, f"{fix.name}: beacon defined")
        check(f'freq={fix.freq_mhz:.3f}' in body,
              f"{fix.name}: {fix.freq_mhz:.3f} MHz matches route.py")
        wav = f"l10n/DEFAULT/bcn_{fix.ident.lower()}.wav"
        check(wav in names, f"{fix.name}: {wav.split('/')[-1]} packed")

# --- radios -----------------------------------------------------------------
for freq in re.findall(r'\["frequency"\]=(\d+),\s*\n\s*\["modulation"\]', mission):
    check(100 <= int(freq) <= 156,
          f"group radio {freq} MHz inside the SCR-522 band (pydcs defaults to 251)")

presets = [n for n in names if n.endswith("VHF_RADIO/SETTINGS.lua")]
check(len(presets) >= 1, f"SCR-522 presets written for {len(presets)} slot(s)")
wanted = {int(f.freq_mhz * 1_000_000) for f in R.FIXES}
for p in presets:
    have = {int(v) for v in re.findall(r"\[\d\]=(\d+)", zf.read(p).decode())}
    missing = wanted - have
    check(not missing,
          f"slot {p.split('/')[2]}: every route beacon tunable"
          + (f" (missing {missing})" if missing else ""))

# --- the aeroplane ----------------------------------------------------------
# Speed appears in three places and pydcs gets two of them wrong: route
# waypoints default to 25 m/s and each unit's spawn speed to 27 m/s (61 mph),
# which stalls the Mustang on spawn. Wind also uses a "speed" key, so exclude it
# rather than flagging a correctly-set 20 mph breeze.
wind_speeds = {float(s) for s in re.findall(
    r'\["(?:atGround|at2000|at8000)"\]=\s*\{[^}]*?\["speed"\]=([\d.]+)',
    mission, re.S)}
all_speeds = {float(s) for s in re.findall(r'\["speed"\]=([\d.]+)', mission)}
slow = {s for s in (all_speeds - wind_speeds) if s < 60}
check(not slow,
      "no waypoint or unit spawn speed below 60 m/s"
      + (f" -- found {sorted(slow)}, the Mustang stalls" if slow else ""))
check(len(all_speeds - wind_speeds) == 1,
      f"every waypoint and unit shares one cruise speed "
      f"({sorted(all_speeds - wind_speeds)})")
check(mission.count('"Client"') == 4, f"4 client slots "
      f"(found {mission.count(chr(34) + 'Client' + chr(34))})")
check("P-51D-30-NA" in mission, "aircraft is the -30 (only ARA-8 airframe)")

for line in notes:
    print(line)
if problems:
    print()
    for line in problems:
        print(line)
    print(f"\n{len(problems)} problem(s) -- do not load this mission")
    sys.exit(1)
print(f"\nall {len(notes)} checks passed")
