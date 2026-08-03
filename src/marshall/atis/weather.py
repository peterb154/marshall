"""What the sim says the weather is, per aerodrome.

    "The atis module should calculate Wx and active runway."

ONE PLACE ASKS THE SIM, and it asks per FIELD rather than once for the mission.
The difference is the whole reason `observation.py` exists: the mission has a
cloud base in metres above sea level and one QNH, and an aerodrome has a ceiling
in feet above its own ground and its own QFE. Kobuleti and Batumi read 1010.9
and 1011.8 hPa at the same instant because one is twenty-six feet higher.

THE WIND IS SAMPLED ABOVE THE FIELD, not at the surface. DCS's boundary layer
takes the wind to nearly nothing at ground level, so a surface sample reports
calm on a day with a usable breeze -- and the runway in use is decided off this
number, so "calm" would leave it on whatever end it started with.
"""

from __future__ import annotations

import math

# Ten metres is the meteorological standard height for a surface wind, and it is
# above the worst of the sim's ground friction without being a different wind.
WIND_SAMPLE_M = 10.0
MS_TO_KT = 1.94384
HPA_PER_PA = 0.01


def _lua(field_names: list[str]) -> str:
    names = ", ".join(f"'{n}'" for n in field_names)
    return f"""
local out = {{}}
local w = env.mission.weather
local base = (w.clouds and w.clouds.base) or 0
local dens = (w.clouds and w.clouds.density) or 0
local vis  = (w.visibility and w.visibility.distance) or 80000
for _, nm in ipairs({{{names}}}) do
  local ab = Airbase.getByName(nm)
  if ab then
    local p = ab:getPoint()
    local at = {{x = p.x, y = p.y + {WIND_SAMPLE_M}, z = p.z}}
    local v = atmosphere.getWind(at)
    local t, press = atmosphere.getTemperatureAndPressure(at)
    -- DCS's wind vector points where it BLOWS TO; met convention is where it
    -- comes FROM, which is what a pilot is given and what picks the runway.
    local to_deg = math.deg(math.atan2(v.z, v.x)) % 360
    out[#out+1] = string.format('%s|%.1f|%.2f|%.0f|%d|%.0f|%.1f|%.1f',
      nm, (to_deg + 180) % 360, math.sqrt(v.x*v.x + v.z*v.z),
      base, dens, vis, t - 273.15, press)
  end
end
return table.concat(out, ';')
"""


def observe_fields(fields, eval_lua) -> dict:
    """{field name: Observation} for every field given.

    `eval_lua` is injected rather than imported so this module does not depend
    on the gRPC stubs -- the same reason `atis` does not import the bridge. It
    takes one Lua string and returns the sim's answer.
    """
    from marshall.atis import observation as _o
    from marshall.core import route as _R

    raw = eval_lua(_lua([f.name for f in fields]))
    out = {}
    for chunk in str(raw).strip('"').split(";"):
        if not chunk.strip():
            continue
        name, wind_deg, wind_ms, base_m, dens, vis_m, temp_c, press_pa = chunk.split("|")
        field = _R.field_named(name)
        if field is None:
            continue
        qfe_hpa = float(press_pa) * HPA_PER_PA
        out[name] = _o.observe(
            field,
            wind_from_deg=float(wind_deg),
            wind_kt=float(wind_ms) * MS_TO_KT,
            cloud_base_m=float(base_m),
            cloud_density=int(dens),
            visibility_m=float(vis_m),
            temp_c=float(temp_c),
            # QNH is the field's pressure corrected to sea level. The sim gives
            # us the pressure where the aeroplane is, which IS the QFE.
            qnh_inhg=_o.hpa_to_inhg(qfe_hpa + field.elevation_ft * 0.03613),
            qfe_inhg=_o.hpa_to_inhg(qfe_hpa),
        )
    return out


def zulu(seconds: float) -> str:
    """Mission time as the four digits an ATIS says. Takes the clock rather
    than reading one, so a recording is reproducible."""
    total = int(seconds) % 86400
    return f"{total // 3600:02d}{(total % 3600) // 60:02d}"


def headwind_kt(field, obs) -> float:
    """How much of the wind is down the runway in use. Not broadcast -- it is
    what `runway_in_use` decided with, and having it here means the decision can
    be explained on `/diag` rather than only asserted."""
    off = math.radians(obs.wind_from_deg - field.runway_in_use(obs.wind_from_deg) * 10)
    return obs.wind_kt * math.cos(off)
