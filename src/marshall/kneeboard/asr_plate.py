"""The surveillance-radar approach plate.

Deliberately not a rework of `plate.py`. That chart draws a beacon letdown --
racetrack, procedure turn, station passage -- and an ASR has none of those
things. On a radar approach the pilot is not navigating at all: the controller
vectors him onto the final approach course and talks him down. So the chart's
job changes completely. It stops being a map to fly and becomes a card of the
few numbers he must be able to check the controller against:

    who he is talking to, on what frequency
    the final approach course
    the altitude he descends to, and the one he must not go below
    what the controller's calls will sound like, so an unfamiliar one is obvious

Everything is read from the ApproachProfile the ATC and the mission generator
share, so the card cannot brief a number the controller will not say.
"""

from __future__ import annotations

from marshall import config
from marshall.core import route as R

P = R.BATUMI_ASR


def _row(label: str, value: str, note: str = "") -> str:
    return (f'<tr><th>{label}</th><td class="v">{value}</td>'
            f'<td class="n">{note}</td></tr>')


def build(profile: R.ApproachProfile = P) -> str:
    inbound = profile.final_crs
    outbound = (inbound + 180) % 360
    field = profile.beacon           # the radar reference point IS the field
    stations = profile.stations or []

    freqs = "".join(
        f'<tr><th>{s.name}</th><td class="v">{s.freq_mhz:.3f}</td>'
        f'<td class="n">{R.preset_label(i + 1)}</td></tr>'
        for i, s in enumerate(stations))

    calls = "".join(
        f"<li>{c}</li>" for c in [
            "&ldquo;radar contact, <b>NN</b> miles northwest of the field&rdquo;",
            "&ldquo;turn left heading <b>NNN</b>, vectors to the final "
            "approach course&rdquo;",
            f"&ldquo;{profile.final_intercept_nm:.0f} miles from the field, turn "
            f"right heading <b>{inbound:03d}</b>, descend to <b>"
            f"{profile.mda_ft}</b>&rdquo;",
            "&ldquo;<b>N</b> miles from the runway &mdash; on course&rdquo; "
            "<i>(each mile)</i>",
            "&ldquo;drifting right of course, turn left heading "
            "<b>NNN</b>&rdquo;",
            "&ldquo;over the missed approach point &mdash; if the runway is not "
            "in sight, execute missed approach&rdquo;",
        ])

    return f"""
<style>
  .wrap {{ font: 15px/1.45 "Courier New", monospace; color: #241f18;
           background: #d9cfb4; padding: 18px 20px; }}
  h1 {{ font-size: 21px; margin: 0 0 2px; letter-spacing: 1px; }}
  h2 {{ font-size: 14px; margin: 18px 0 6px; letter-spacing: 2px;
        border-bottom: 2px solid #241f18; padding-bottom: 3px; }}
  .sub {{ font-size: 13px; margin: 0 0 4px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 4px; }}
  th {{ text-align: left; font-weight: normal; padding: 3px 6px 3px 0;
        white-space: nowrap; }}
  td.v {{ font-weight: bold; font-size: 17px; text-align: right;
          padding: 3px 10px; white-space: nowrap; }}
  td.n {{ font-size: 12px; color: #5a5142; width: 45%; }}
  tr + tr th, tr + tr td {{ border-top: 1px dotted #a89c7d; }}
  .warn {{ border: 2px solid #7a2318; color: #7a2318; padding: 8px 10px;
           margin-top: 10px; font-size: 13px; }}
  ol {{ margin: 4px 0 0 18px; padding: 0; font-size: 13px; }}
  ol li {{ margin-bottom: 3px; }}
  b {{ background: #cabf9f; padding: 0 2px; }}
  .mins {{ display: flex; gap: 10px; margin-top: 6px; }}
  .mins div {{ flex: 1; border: 2px solid #241f18; padding: 6px 8px;
               text-align: center; }}
  .mins .big {{ font-size: 24px; font-weight: bold; display: block; }}
  .mins .cap {{ font-size: 11px; letter-spacing: 1px; }}
</style>

<div class="wrap">
  <h1>{field.name} &mdash; SURVEILLANCE RADAR APPROACH</h1>
  <p class="sub">Runway {profile.runway} &middot; field elevation
     {profile.field_elev_ft} ft &middot; ATC vectors, pilot flies headings</p>

  <h2>RADIO</h2>
  <table>{freqs}</table>

  <h2>APPROACH</h2>
  <table>
    {_row("Final approach course", f"{inbound:03d}&deg;", "magnetic, inbound")}
    {_row("Outbound / downwind", f"{outbound:03d}&deg;", "reciprocal")}
    {_row("Vectoring altitude", f"{profile.platform_ft:,} ft",
          "until established on final")}
    {_row("Turn-on range", f"{profile.final_intercept_nm:.0f} nm",
          "rolled out on the course by here")}
    {_row("Missed approach point", f"{profile.map_nm:.1f} nm",
          "from the field")}
    {_row("Missed approach", f"{profile.missed_ft:,} ft",
          f"climbing {profile.missed_turn.lower()} turn, re-sequence")}
  </table>

  <div class="mins">
    <div><span class="cap">MDA</span><span class="big">{profile.mda_ft}</span>
         ft &middot; {profile.mda_ft - profile.field_elev_ft} HAT</div>
    <div><span class="cap">CEILING</span>
         <span class="big">{profile.ceiling_ft}</span> ft briefed</div>
    <div><span class="cap">WIND</span>
         <span class="big">{int(R.WIND_FROM_DEG):03d}</span>
         at {int(R.WIND_MPH)} mph</div>
  </div>

  <h2>WHAT YOU WILL HEAR</h2>
  <ol>{calls}</ol>

  <div class="warn">
    <b>FLY THE HEADINGS.</b> The controller is navigating, not you. Do not
    home a beacon and do not correct his headings for wind &mdash; he is
    watching your ground track and the drift is already in the number he gives
    you. If you crab off his heading he will correct a drift you created.
    <br><br>
    Do not descend below <b>{profile.mda_ft} ft</b> without the runway in
    sight. Range calls are to the field, and there is no glidepath on this
    approach &mdash; your descent is your own.
  </div>
</div>
"""


if __name__ == "__main__":
    config.ensure_dirs()
    out = config.KNEEBOARD_OUT / "plate-asr.html"
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out}")
