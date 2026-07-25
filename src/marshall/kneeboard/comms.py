"""The comms ladder: which button, who is on it, and when you use it.

A pilot in a period cockpit has four buttons and no way to dial a frequency, so
the card is not a convenience -- it is the entire radio. Getting it wrong is not
a missed call, it is inaudibility: he transmits into an empty channel and hears
nothing back, and from the cockpit that is indistinguishable from an ATC that is
not answering. It has happened here, twice.

So this page is generated from the same `route.py` stations the mission writes
into the aeroplane and the bridge listens on. Three things that must agree, one
source. And it is ordered by the SORTIE rather than by frequency, because that
is the order the buttons get pressed: ground, departure, enroute, and back.
"""

from __future__ import annotations

from marshall.atc import phases
from marshall.core import route as R

P = R.BATUMI_ASR

# The sortie, in order, and which phase sends you to each button. Only phases
# that actually change the frequency appear -- a ladder listing every state
# would be a table of the phase machine and not a radio card.
LADDER = [
    ("Start-up, taxi", ("clearance", "taxi")),
    ("Take-off, departure", ("departure",)),
    ("Enroute, transit", ("enroute", "rtb")),
    ("Tasking, on station", ("tasked", "on_station")),
    ("Recovery, approach", ("arrival", "holding", "approach", "missed")),
    ("Landing, taxi in", ("landed",)),
]

STYLE = """
  .comms { font: 15px/1.5 "Courier New", monospace; color: #2b2620;
           background: #d9cfb4; padding: 18px 20px; }
  .comms h1 { font-size: 20px; margin: 0 0 2px; letter-spacing: 1px; }
  .comms .sub { font-size: 12px; color: #5a5142; margin-bottom: 14px; }
  .comms table { border-collapse: collapse; width: 100%; margin-bottom: 16px; }
  .comms th, .comms td { border: 1px solid #8a8069; padding: 5px 7px;
                         text-align: left; }
  .comms th { background: #c6bb9c; font-size: 12px; letter-spacing: .5px; }
  .comms .ch { font-size: 22px; font-weight: bold; text-align: center;
               width: 42px; }
  .comms .fq { font-size: 17px; font-weight: bold; white-space: nowrap; }
  .comms .who { font-weight: bold; }
  .comms .note { font-size: 12px; color: #5a5142; }
  .comms h2 { font-size: 14px; margin: 16px 0 6px; letter-spacing: 1px;
              border-bottom: 1px solid #8a8069; padding-bottom: 3px; }
  .comms .facts td { font-size: 13px; }
  .comms .warn { background: #c9b98f; }
"""


def build(profile=P) -> str:
    stations = list(getattr(profile, "stations", None) or R.STATIONS)
    letters = "ABCD"

    rows = []
    for i, s in enumerate(stations[:4]):
        # What this seat covers, said in the pilot's language rather than the
        # phase table's. He does not care that "arrival" and "holding" are
        # different states; he cares which button to press.
        covers = [s.role] + list(getattr(s, "also", ()))
        when = [label for label, ph in LADDER
                if any(phases.owner_of(p) in covers for p in ph)]
        rows.append(
            f"<tr><td class='ch'>{letters[i]}</td>"
            f"<td class='fq'>{s.freq_mhz:.3f}</td>"
            f"<td class='who'>{s.name}</td>"
            f"<td class='note'>{'; '.join(when) or '&mdash;'}</td></tr>")

    inbound = profile.final_crs
    rwy = profile.runway or "in use"
    qfe = R.altimeter_spoken(R.qfe_inhg(profile.field_elev_ft))
    return f"""<title>Comms &amp; Batumi {rwy}</title>
<style>{STYLE}</style>
<div class="comms">
  <h1>COMMS LADDER</h1>
  <div class="sub">Four presets, in the order you press them. This card, the
    aeroplane's radio and the controller all come from one source &mdash; if
    they ever disagree, believe nothing and say so.</div>

  <table>
    <tr><th>CH</th><th>FREQ</th><th>STATION</th><th>WHEN</th></tr>
    {''.join(rows)}
  </table>

  <h2>BATUMI &mdash; RUNWAY {rwy} &mdash; RADAR APPROACH</h2>
  <table class="facts">
    <tr><td>Final approach course</td><td><b>{inbound:03d}&deg;</b> magnetic</td></tr>
    <tr><td>Initial approach fix</td>
        <td><b>{profile.final_intercept_nm:.0f} nm</b> at
            <b>{profile.iaf_alt_ft:,} ft</b> &mdash; established by here</td></tr>
    <tr><td>Final approach point</td>
        <td><b>{profile.fap_nm:.0f} nm</b> &mdash; begin descent</td></tr>
    <tr><td>Minimums (MDA)</td>
        <td><b>{profile.mda_ft:,} ft</b>
            ({profile.mda_ft - profile.field_elev_ft:,} above the field)</td></tr>
    <tr><td>Missed approach point</td><td><b>{profile.map_nm:.1f} nm</b></td></tr>
    <tr class="warn"><td>Missed approach</td>
        <td>straight ahead; at <b>{profile.missed_straight_ft:,}</b> turn
            <b>{profile.missed_turn}</b> heading
            <b>{profile.missed_hdg:03d}</b>, climb
            <b>{profile.missed_climb_ft:,}</b></td></tr>
    <tr><td>Approach speed</td>
        <td><b>{profile.final_speed_mph}</b> mph from the fix
            (pattern {profile.speed_mph})</td></tr>
    <tr><td>Altimeter</td>
        <td><b>{qfe}</b> ({profile.altimeter_datum})</td></tr>
    <tr><td>Wind</td>
        <td>{int(R.WIND_FROM_DEG):03d} at {int(R.WIND_MPH)} mph</td></tr>
    <tr><td>Holding</td>
        <td><b>{profile.stack_ft[0]:,} ft</b> and up, in clear air &mdash;
            {profile.hold_outbound_hdg:03d} outbound,
            {(profile.hold_outbound_hdg + 180) % 360 or 360:03d} inbound</td></tr>
  </table>

  <div class="sub">The controller navigates: you fly the headings he gives you
    and he absorbs the wind. There is no glidepath &mdash; his altitudes are
    advisory and the descent rate is yours.</div>
</div>
"""


if __name__ == "__main__":
    from marshall import config
    config.ensure_dirs()
    out = config.KNEEBOARD_OUT / "comms.html"
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out}")
