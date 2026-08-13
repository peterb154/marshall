"""Generate the Batumi approach plate.

Terrain figures come from the survey flown 2026-07-24 and live in route.py, so
the plate cannot claim a safe altitude the ground disagrees with.

    uv run python build_plate.py
"""

import math
from pathlib import Path

from marshall import config

from marshall.core import route as R

HERE = Path(__file__).parent

# Everything comes from the field's ApproachProfile -- the single source shared
# with ATC and the mission generator. The plate cannot disagree with the sim.
#
# The procedure (a no-DME beacon letdown to a coastal, sea-level field):
# hold over the field beacon with the racetrack out over the water; cleared, you
# descend to the platform on the reversal, then -- only while established on the
# beam -- down to MDA; station passage (the cone of silence overhead) is the
# missed approach point. No DME, no timing: the null over the beacon IS the fix,
# and because the field is at sea level with water underneath, the altimeter
# reads a true height so MDA can sit low, just under the briefed cloud base.
P = R.BATUMI_APPROACH

# THE BEACON, and this chart is the one page in the tree that genuinely means
# one: the letdown is flown ON it and station passage over it is the missed
# approach point. `beacon` is the profile's name for it since #163, where the
# other three procedures stopped claiming to have one.
BEACON = P.beacon
FINAL_CRS = P.final_crs
HOLD_TURNS = P.hold_turns
SPEED_KT = P.speed_kt          # nm/h, derived from the MPH the ASI reads
DESCENT_FPM = P.descent_fpm
STACK_FT = P.stack_ft
PLATFORM_FT = P.platform_ft
MDA_FT = P.mda_ft
CEILING_FT = P.ceiling_ft
MISSED_ALT_FT = P.missed_ft
MISSED_TURN = P.missed_turn
MISSED_HDG = P.missed_hdg
MISSED_STRAIGHT_FT = P.missed_straight_ft
# The inbound beam must be at least this long or you cannot be down by station
# passage -- it sizes the racetrack, and it lands near the real plate's D13.5.
INBOUND_NM = P.inbound_descent_nm

STYLE = """
  /* Portrait proportions with no JavaScript and nothing that can measure zero.
     An earlier version scaled a fixed 1024x1365 sheet with a transform; it kept
     computing scale(0) while OpenKneeboard resized the surface after load and
     the page vanished. A max-width is boring and cannot fail. */
  body { max-width: 1024px; margin: 0 auto; }

  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 10px; background: #d9cfb4; color: #241f18;
    font-family: "Courier New", monospace; font-size: 14px;
  }
  .sheet { border: 2px solid #241f18; padding: 10px; }
  h1 { margin: 0; font-size: 17px; letter-spacing: .16em; text-align: center;
       text-transform: uppercase; }
  .sub { text-align: center; font-size: 12px; letter-spacing: .1em;
         margin-bottom: 8px; }
  h2 { font-size: 11px; letter-spacing: .14em; text-transform: uppercase;
       margin: 10px 0 4px; border-bottom: 1px solid #241f18;
       padding-bottom: 2px; }
  table { width: 100%; border-collapse: collapse; }
  th, td { border: 1px solid #241f18; padding: 4px; text-align: center;
           font-variant-numeric: tabular-nums; }
  th { font-size: 10px; letter-spacing: .07em; text-transform: uppercase;
       background: #cabf9f; }
  td.l { text-align: left; }
  .warn { border: 3px solid #7a2318; color: #7a2318; padding: 8px;
          font-weight: bold; margin-top: 10px; font-size: 14px; }
  .steps { font-size: 13px; }
  .steps li { margin-bottom: 4px; }
  svg { display: block; margin: 6px auto; background: #cfc4a6;
        border: 1px solid #241f18; }
  text { font-family: "Courier New", monospace; fill: #241f18; }
"""


W, H = 470, 300
CX, CY = 300, 210            # Batumi beacon, on the coast, right-of-centre
SCALE = 9.0                  # px per nm


def off(bearing_deg: float, nm: float):
    """Displacement only, for building positions relative to another point."""
    a = math.radians(bearing_deg)
    return (math.sin(a) * nm * SCALE, -math.cos(a) * nm * SCALE)


def pt(bearing_deg: float, nm: float, ox: float = CX, oy: float = CY):
    """Bearing and distance from a point, to SVG coordinates.

    SVG's y axis grows DOWNWARD, so north is -y. Getting this wrong once put the
    holding fix south-east of the field and drew the approach coming in from the
    wrong side entirely -- exactly the sort of error that flies someone into a
    mountain. Everything geometric goes through here now.
    """
    a = math.radians(bearing_deg)
    return (ox + math.sin(a) * nm * SCALE,
            oy - math.cos(a) * nm * SCALE)


def _unit(bearing_deg: float):
    a = math.radians(bearing_deg)
    return (math.sin(a), -math.cos(a))       # SVG y is down, so north is -y


def _racetrack(fx: float, fy: float, inbound: float, turns: str,
               leg: float = 74, width: float = 40) -> str:
    """A holding racetrack whose INBOUND leg ends at (fx, fy) on `inbound`.

    Drawn from two straights and two 180 arcs so it reads as a real hold, not an
    ellipse. For right turns the pattern sits to the right of the inbound course;
    here that is the SW/seaward side, which is the whole point.
    """
    dx, dy = _unit(inbound)                   # inbound travel direction
    side = inbound + (90 if turns == "RIGHT" else -90)
    px, py = _unit(side)                      # toward the holding side
    r = width / 2
    A = (fx - dx * leg, fy - dy * leg)        # inbound-leg far (upwind) end
    B = (fx + px * width, fy + py * width)    # abeam the fix, outbound leg
    C = (B[0] - dx * leg, B[1] - dy * leg)    # outbound-leg far end
    sweep = 1 if turns == "RIGHT" else 0
    return (f'<path d="M {A[0]:.0f} {A[1]:.0f} L {fx:.0f} {fy:.0f} '
            f'A {r:.0f} {r:.0f} 0 0 {sweep} {B[0]:.0f} {B[1]:.0f} '
            f'L {C[0]:.0f} {C[1]:.0f} '
            f'A {r:.0f} {r:.0f} 0 0 {sweep} {A[0]:.0f} {A[1]:.0f} Z" '
            f'fill="none" stroke="#241f18" stroke-width="1.8"/>')


def plan_view() -> str:
    """Single-beacon letdown, north up, schematic.

    The beacon is at the field. You hold north-west of it over the water, inbound
    on the runway heading (130); the procedure turn and the missed both stay out
    to sea, because everything else is rising ground.
    """
    # Inbound leg begins out over the water on the 310 radial; the hold sits on
    # the seaward (SW) side of that course, so bias the label placement that way.
    app_x, app_y = pt(FINAL_CRS - 180, 15.0)
    hold = _racetrack(CX, CY, FINAL_CRS, HOLD_TURNS)
    ix, iy = _unit(FINAL_CRS)
    rx, ry = _unit(FINAL_CRS + 90)               # toward the holding side (SW)

    # Runway stub: from the beacon a short way on the landing heading, into land.
    rwx, rwy_ = CX + ix * 26, CY + iy * 26
    # Missed: from the beacon out to sea and back, returning below the stack.
    ma_out = pt(FINAL_CRS - 180 + 26, 13.0)
    ma_end = pt(FINAL_CRS - 180, 6.0)

    return f"""
<svg viewBox="0 0 {W} {H}" width="100%">
  <style>
    .m {{ font-family: "Courier New", monospace; fill: #241f18;
         paint-order: stroke; stroke: #e7ddc2; stroke-width: 3;
         stroke-linejoin: round; }}
  </style>
  <!-- Open sea fills the frame; land is a wedge along the south-east edge, the
       field on its coast. So the hold, the reversal and the missed all stay
       over water, and only the runway is over land. -->
  <rect x="0" y="0" width="{W}" height="{H}" fill="#cfc4a6"/>
  <path d="M {CX+ix*8:.0f} {CY+iy*8:.0f} L {W} 92 L {W} {H} L 250 {H} Z"
        fill="#b3a57f"/>
  <path d="M {W} 210 L {W} {H} L 330 {H} Q 440 250 {W} 190 Z" fill="#a2946b"/>
  <text class="m" x="14" y="28" font-size="14" letter-spacing="2">BLACK SEA</text>
  <text class="m" x="{W-92}" y="{H-16}" font-size="10">10,623 FT</text>
  <text class="m" x="{W-86}" y="120" font-size="10">7,306 FT</text>

  <!-- inbound / final approach course, from the sea to the beacon -->
  <line x1="{app_x:.0f}" y1="{app_y:.0f}" x2="{CX}" y2="{CY}"
        stroke="#241f18" stroke-width="2.6"/>
  <polygon points="{CX},{CY} {CX - ix*18 - iy*7:.0f},{CY - iy*18 + ix*7:.0f}
                   {CX - ix*18 + iy*7:.0f},{CY - iy*18 - ix*7:.0f}"
           fill="#241f18"/>
  <text class="m" x="{app_x-4:.0f}" y="{app_y-8:.0f}" font-size="12"
        font-weight="bold" text-anchor="middle">FINAL {FINAL_CRS:03d}&deg;</text>

  <!-- holding pattern (in lieu of procedure turn), over the water -->
  {hold}
  <text class="m" x="{CX + rx*58:.0f}" y="{CY + ry*58:.0f}" font-size="11"
        text-anchor="middle">HOLD</text>
  <text class="m" x="{CX + rx*58:.0f}" y="{CY + ry*58 + 14:.0f}" font-size="9"
        text-anchor="middle">{HOLD_TURNS} &middot; {PLATFORM_FT:,}</text>

  <!-- missed: straight ahead climbing, then LEFT back out to sea -->
  <path d="M {CX} {CY} Q {ma_out[0]:.0f} {ma_out[1]:.0f} {ma_end[0]:.0f} {ma_end[1]:.0f}"
        fill="none" stroke="#7a2318" stroke-width="2.2" stroke-dasharray="7 4"/>
  <polygon points="{ma_end[0]:.0f},{ma_end[1]:.0f} {ma_end[0]+14:.0f},{ma_end[1]+2:.0f}
                   {ma_end[0]+5:.0f},{ma_end[1]+13:.0f}" fill="#7a2318"/>
  <text class="m" x="{ma_out[0]:.0f}" y="{ma_out[1]-8:.0f}" font-size="10"
        fill="#7a2318" text-anchor="middle" letter-spacing="1">MISSED {MISSED_TURN} {MISSED_HDG:03d} &middot; {MISSED_ALT_FT:,}</text>

  <!-- runway stub, into the land -->
  <line x1="{CX}" y1="{CY}" x2="{rwx:.0f}" y2="{rwy_:.0f}"
        stroke="#241f18" stroke-width="4"/>

  <!-- the beacon, at the field; label above so it clears the busy SW side -->
  <circle cx="{CX}" cy="{CY}" r="6.5" fill="none" stroke="#241f18" stroke-width="2"/>
  <circle cx="{CX}" cy="{CY}" r="2.5" fill="#241f18"/>
  <text class="m" x="{CX+11}" y="{CY-8}" font-size="13"
        font-weight="bold">{BEACON.ident} {BEACON.freq_mhz:.3f}</text>
  <text class="m" x="{CX+11}" y="{CY+6}" font-size="9">RWY {P.runway} &middot; ELEV {P.field_elev_ft}</text>

  <text class="m" x="12" y="{H-14}" font-size="9">NORTH UP &middot; NOT TO SCALE</text>
</svg>"""


def build() -> str:
    stack = "".join(
        f"<tr><td>Pony {i+1}</td><td><b>{ft:,}</b></td>"
        f"<td class='l'>{'first to approach' if i == 0 else f'step down as {i} vacates'}</td></tr>"
        for i, ft in enumerate(STACK_FT))
    # The PUBLISHED sectors, which is what belongs on a chart the pilot reads.
    # The lower vectoring minima are the controller's and are not briefed.
    msa = "".join(f"<td>{int(lo):03d}&ndash;{int(hi):03d}<br><b>{v:,}</b></td>"
                  for lo, hi, v in R.BATUMI_FIELD.msa_sectors)

    return f"""<title>Batumi RWY {P.runway} - Beacon Approach</title>
<style>{STYLE}</style>
<div class="sheet">
  <h1>Batumi &mdash; Runway {P.runway}</h1>
  <div class="sub">Beacon Approach &middot; P-51D-30 &middot; No DME</div>

  {plan_view()}

  <h2>Minimum Safe Altitude &mdash; 25 NM</h2>
  <table><tr>{msa}</tr></table>

  <h2>Holding &amp; Letdown &mdash; over {BEACON.ident} {BEACON.freq_mhz:.3f} (the field)</h2>
  <table>
    <tr><th>Inbound</th><th>Turns</th><th>Platform</th><th>MDA</th></tr>
    <tr><td><b>{FINAL_CRS:03d}&deg;T</b></td><td>{HOLD_TURNS}</td>
        <td>{PLATFORM_FT:,} ft</td><td><b>{MDA_FT} ft</b></td></tr>
  </table>
  <table style="margin-top:6px">
    <tr><th>Aircraft</th><th>Altitude</th><th>Sequence</th></tr>
    {stack}
  </table>

  <h2>Approach</h2>
  <ol class="steps">
    <li>Hold over <b>{BEACON.ident}</b> as assigned. Cleared, descend on the
        reversal to <b>{PLATFORM_FT:,} ft</b>, out over the water.</li>
    <li>Established inbound <b>{FINAL_CRS:03d}&deg;T</b> &mdash; steady tone,
        on the beam &mdash; descend to <b>MDA {MDA_FT} ft</b> at no more than
        <b>{DESCENT_FPM} ft/min</b>. Descend <u>only</u> while the tone holds: a
        broken tone means you are not established. Do not descend to look.</li>
    <li>Hold MDA to the field. <b>Station passage</b> &mdash; the beacon goes
        silent overhead (cone of silence) &mdash; is the missed approach point.</li>
    <li>Runway {P.runway} in sight at station passage &mdash; land, field
        elevation {P.field_elev_ft} ft. Not in sight &mdash; go around.</li>
  </ol>

  <div class="warn">
    MISSED APPROACH &mdash; STRAIGHT AHEAD TO {MISSED_STRAIGHT_FT}',
    THEN <u>{MISSED_TURN}</u> {MISSED_HDG:03d}&deg;, CLIMB {MISSED_ALT_FT:,}'<br>
    Return to {BEACON.ident}, hold below the stack, await re-sequence.<br>
    Do not press on past the field: rising ground south-east.
  </div>

  <div style="font-size:11px;margin-top:8px">
    Terrain surveyed 2026-07-24: highest ground 10,623 ft, 23 NM south-east.
    The beacon is on the field; the hold, the reversal and the missed all stay
    north-west, over the water.
  </div>
</div>

"""


if __name__ == "__main__":
    config.ensure_dirs(); out = config.KNEEBOARD_OUT / "plate-batumi.html"
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out}")
    print(f"  hold over {BEACON.ident} {BEACON.freq_mhz:.3f}, inbound "
          f"{FINAL_CRS:03d}T {HOLD_TURNS} turns, stack {STACK_FT}")
    print(f"  MDA {MDA_FT}, missed climb {MISSED_ALT_FT:,} (below stack)")
