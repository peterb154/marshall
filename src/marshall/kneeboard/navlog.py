"""Generate the kneeboard pages from route.py.

Everything the pilot reads is derived from the same data the mission is built
from, so a chart cannot disagree with the sim.

    uv run python build_kneeboard.py

Writes navlog.html next to this file. Add it in OpenKneeboard as a Web
Dashboard tab.
"""

from pathlib import Path

from marshall import config

from marshall.core import route as R

HERE = Path(__file__).parent

# Buff paper and dark ink: this is a document, not an instrument. It also keeps
# the page from blinding you in a night cockpit the way pure white would.
STYLE = """
  /* Portrait proportions with no JavaScript and nothing that can measure zero.
     An earlier version scaled a fixed 1024x1365 sheet with a transform; it kept
     computing scale(0) while OpenKneeboard resized the surface after load and
     the page vanished. A max-width is boring and cannot fail. */
  body { max-width: 1024px; margin: 0 auto; }

  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 12px;
    background: #d9cfb4; color: #241f18;
    font-family: "Courier New", "DejaVu Sans Mono", monospace;
    font-size: 15px;
  }
  .sheet { border: 2px solid #241f18; padding: 10px; }
  h1 {
    margin: 0 0 2px; font-size: 17px; letter-spacing: .18em;
    text-transform: uppercase; text-align: center;
  }
  .sub {
    text-align: center; font-size: 12px; letter-spacing: .12em;
    margin-bottom: 10px; text-transform: uppercase;
  }
  .band {
    display: flex; justify-content: space-between; flex-wrap: wrap;
    gap: 6px 18px; border-top: 1px solid #241f18;
    border-bottom: 1px solid #241f18; padding: 6px 0; margin-bottom: 10px;
    font-size: 14px;
  }
  .band b { letter-spacing: .06em; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 12px; }
  th, td {
    border: 1px solid #241f18; padding: 5px 4px; text-align: center;
    font-variant-numeric: tabular-nums;
  }
  th {
    font-size: 11px; letter-spacing: .08em; text-transform: uppercase;
    background: #cabf9f;
  }
  td.fix { text-align: left; font-weight: bold; letter-spacing: .05em; }
  /* Columns the pilot fills in with a pencil in the aeroplane. */
  td.blank { background: #cfc4a6; }
  .tot td { font-weight: bold; background: #cabf9f; }
  h2 {
    font-size: 12px; letter-spacing: .14em; text-transform: uppercase;
    margin: 0 0 5px; border-bottom: 1px solid #241f18; padding-bottom: 3px;
  }
  .warn {
    border: 2px solid #7a2318; color: #7a2318; padding: 7px;
    font-weight: bold; font-size: 14px; margin-top: 10px;
  }
  .note { font-size: 12px; margin-top: 6px; }
"""


def morse(ident: str) -> str:
    table = {
        "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.",
        "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-",
        "L": ".-..", "M": "--", "N": "-.", "O": "---", "P": ".--.",
        "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-",
        "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--", "Z": "--..",
    }
    return " ".join(table[c] for c in ident.upper())


def build() -> str:
    # The SORTIE, not the letdown. This page used to show the three beacon legs
    # of the approach, which stopped being a flight plan the moment the approach
    # went to radar -- it was a nav log for a journey nobody makes. What a pilot
    # actually needs is the trip: out to the work, and home.
    legs = R.solve_route(legs=R.SORTIE_LEGS)
    total_nm = sum(l.distance_nm for l in legs)
    total_min = sum(l.minutes for l in legs)

    rows = []
    elapsed = 0.0
    # The first line is the departure point itself: no leg flown to reach it.
    start = R.SORTIE[0]
    rows.append(
        f'<tr><td class="fix">{start.name}</td>'
        f'<td>{start.ident or "&mdash;"}</td>'
        f'<td>{f"{start.freq_mhz:.3f}" if start.freq_mhz else "&mdash;"}</td>'
        f'<td>&mdash;</td><td>&mdash;</td><td>&mdash;</td><td>&mdash;</td>'
        f'<td>&mdash;</td><td>&mdash;</td><td class="blank"></td></tr>')

    for leg in legs:
        elapsed += leg.minutes
        eta = f"{int(elapsed)}:{round((elapsed % 1) * 60):02d}"
        rows.append(
            f'<tr><td class="fix">{leg.to.name}</td>'
            f'<td>{leg.to.ident or "&mdash;"}</td>'
            f'<td>{f"{leg.to.freq_mhz:.3f}" if leg.to.freq_mhz else "&mdash;"}</td>'
            f'<td>{leg.course_true:03.0f}</td>'
            f'<td>{leg.wca:+.0f}</td>'
            f'<td><b>{leg.heading_mag:03.0f}</b></td>'
            f'<td>{leg.distance_nm:.1f}</td>'
            f'<td>{leg.groundspeed_mph:.0f}</td>'
            f'<td>{leg.time_str}</td>'
            f'<td class="blank"></td></tr>')

    rows.append(
        f'<tr class="tot"><td class="fix">TOTAL</td><td></td><td></td>'
        f'<td></td><td></td><td></td><td>{total_nm:.1f}</td><td></td>'
        f'<td>{int(total_min)}:{round((total_min % 1) * 60):02d}</td>'
        f'<td class="blank"></td></tr>')

    # The channel card lists CONTROLLERS, not beacons. Under a radar approach
    # the pilot navigates by nothing, so a preset is only ever somebody to talk
    # to -- and unlike a beacon, a controller needs no receiver in the aeroplane,
    # which is why any airframe can fly the approach.
    channels = "".join(
        f'<tr><td>{"ABCD"[i]}</td><td>{s.freq_mhz:.3f}</td>'
        f'<td class="fix">{s.name}</td>'
        f'<td style="text-align:left">{s.role.title()}</td></tr>'
        for i, s in enumerate(R.STATIONS))

    # The PUBLISHED sectors, which is what belongs on a chart the pilot reads.
    # The lower vectoring minima are the controller's and are not briefed.
    msa = "".join(f"<td>{int(lo):03d}&ndash;{int(hi):03d}<br><b>{v:,}</b></td>"
                  for lo, hi, v in R.BATUMI_FIELD.msa_sectors)

    return f"""<title>362nd Nav Log</title>
<style>{STYLE}</style>
<div class="sheet">
  <h1>Pilot's Flight Plan and Log</h1>
  <div class="sub">362nd Fighter Squadron &nbsp;&middot;&nbsp; P-51D-30 &nbsp;&middot;&nbsp; Instrument</div>

  <div class="band">
    <span><b>WIND</b> {R.WIND_FROM_DEG:03.0f}/{R.WIND_MPH:.0f}</span>
    <span><b>TAS</b> {R.CRUISE_TAS_MPH:.0f} MPH</span>
    <span><b>ALT</b> {R.CRUISE_ALT_FT:,} FT</span>
    <span><b>VAR</b> {R.MAGVAR:.0f}&deg;E</span>
    <span><b>PILOT</b> _________</span>
    <span><b>TIME OFF</b> _______</span>
  </div>

  <table>
    <tr>
      <th>Checkpoint</th><th>Ident</th><th>Freq</th>
      <th>Crs&deg;T</th><th>WCA</th><th>Hdg&deg;M</th>
      <th>Dist</th><th>GS</th><th>Time</th><th>ATA</th>
    </tr>
    {"".join(rows)}
  </table>

  <h2>Controllers &mdash; SCR-522 Channels</h2>
  <table>
    <tr><th>Ch</th><th>Freq</th><th>Station</th><th>Sector</th></tr>
    {channels}
  </table>

  <h2>Batumi &mdash; Minimum Safe Altitude, 25 NM</h2>
  <table><tr>{msa}</tr></table>
  <div class="note">
    Highest terrain 10,623 ft at 23 NM southeast. The approach, the hold and the
    missed all remain northwest of the field, over water.
  </div>

  <div class="warn">
    MISSED APPROACH: CLIMBING LEFT TURN TO SEAWARD.<br>
    A right turn from runway heading enters rising ground.
  </div>
</div>

"""


if __name__ == "__main__":
    config.ensure_dirs(); out = config.KNEEBOARD_OUT / "navlog.html"
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out}")
    for leg in R.solve_route():
        print(f"  {leg.frm.ident} -> {leg.to.ident}  "
              f"hdg {leg.heading_mag:03.0f}M  {leg.distance_nm:.1f} nm  "
              f"{leg.time_str}")
