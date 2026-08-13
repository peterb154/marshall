"""E6B wind face, drawn as the real instrument.

The picture carries the feel; the digits carry the workload. It is rendered as
an actual rotating azimuth disc over a wind grid, because that is the object a
1944 pilot held -- but you set it with buttons rather than by dragging, and the
answer is also printed in figures.

Reading a hairline off a scale with a VR cursor at 200 mph is not a thing anyone
should have to do.

    uv run python build_e6b.py
"""

import math
from pathlib import Path

from marshall import config

from marshall.core import route as R

HERE = Path(__file__).parent
CX, CY, RADIUS = 250, 250, 205


def azimuth_disc() -> str:
    """Transparent compass rose: ticks every 5 deg, numbers every 30."""
    parts = [f'<circle cx="{CX}" cy="{CY}" r="{RADIUS}" fill="#efe7d2" '
             f'stroke="#241f18" stroke-width="2"/>']
    for deg in range(0, 360, 5):
        a = math.radians(deg - 90)
        major = deg % 30 == 0
        r0 = RADIUS - (16 if major else 8)
        parts.append(
            f'<line x1="{CX + math.cos(a) * r0:.1f}" y1="{CY + math.sin(a) * r0:.1f}" '
            f'x2="{CX + math.cos(a) * RADIUS:.1f}" y2="{CY + math.sin(a) * RADIUS:.1f}" '
            f'stroke="#241f18" stroke-width="{1.6 if major else 0.7}"/>')
        if major:
            rt = RADIUS - 30
            parts.append(
                f'<text x="{CX + math.cos(a) * rt:.1f}" y="{CY + math.sin(a) * rt + 5:.1f}" '
                f'font-size="17" text-anchor="middle" '
                f'transform="rotate({deg} {CX + math.cos(a) * rt:.1f} '
                f'{CY + math.sin(a) * rt:.1f})">{deg // 10 or 36}</text>')
    return "".join(parts)


def wind_grid() -> str:
    """Concentric speed arcs and radial drift lines, as on the slide."""
    parts = []
    for speed in range(20, 121, 20):
        r = speed * 1.55
        parts.append(f'<circle cx="{CX}" cy="{CY}" r="{r:.0f}" fill="none" '
                     f'stroke="#8c8069" stroke-width="0.6"/>')
        parts.append(f'<text x="{CX + 4}" y="{CY - r + 13:.0f}" font-size="10" '
                     f'fill="#6e6353">{speed}</text>')
    for drift in range(-40, 41, 10):
        a = math.radians(drift - 90)
        parts.append(
            f'<line x1="{CX}" y1="{CY}" '
            f'x2="{CX + math.cos(a) * RADIUS * 0.92:.1f}" '
            f'y2="{CY + math.sin(a) * RADIUS * 0.92:.1f}" '
            f'stroke="#8c8069" stroke-width="{1.1 if drift == 0 else 0.5}"/>')
        if drift:
            rr = RADIUS * 0.96
            parts.append(
                f'<text x="{CX + math.cos(a) * rr:.1f}" y="{CY + math.sin(a) * rr:.1f}" '
                f'font-size="10" fill="#6e6353" text-anchor="middle">{abs(drift)}</text>')
    return "".join(parts)


def build() -> str:
    return f"""<title>362nd E6B</title>
<style>
  * {{ box-sizing: border-box; }}
  /* Portrait proportions with no JavaScript and nothing that can measure zero.
     An earlier version scaled a fixed 1024x1365 sheet with a transform; it kept
     computing scale(0) while OpenKneeboard resized the surface after load and
     the page vanished. A max-width is boring and cannot fail. */
  body {{ max-width: 1024px; margin: 0 auto; }}

  body {{ margin: 0; padding: 8px; background: #d9cfb4; color: #241f18;
         font-family: "Courier New", monospace; font-size: 14px; }}
  .wrap {{ border: 2px solid #241f18; padding: 8px; }}
  h1 {{ margin: 0 0 6px; font-size: 15px; letter-spacing: .16em;
       text-align: center; text-transform: uppercase; }}
  .face {{ position: relative; }}
  .readout {{ display: grid; grid-template-columns: 1fr 1fr 1fr;
             gap: 6px; margin: 8px 0; text-align: center; }}
  .readout div {{ border: 1px solid #241f18; padding: 5px 2px;
                 background: #cabf9f; }}
  .readout b {{ display: block; font-size: 27px; font-variant-numeric: tabular-nums; }}
  .readout span {{ font-size: 10px; letter-spacing: .1em; text-transform: uppercase; }}
  .ctl {{ display: grid; grid-template-columns: 78px 1fr; gap: 5px;
         align-items: center; margin-bottom: 5px; }}
  .ctl label {{ font-size: 12px; text-transform: uppercase; letter-spacing: .06em; }}
  .btns {{ display: flex; gap: 4px; align-items: center; }}
  button {{ background: #cabf9f; border: 1px solid #241f18; border-radius: 3px;
           font-family: inherit; font-size: 15px; font-weight: bold;
           min-width: 42px; min-height: 38px; cursor: pointer; }}
  button:active {{ background: #241f18; color: #d9cfb4; }}
  .cur {{ min-width: 56px; text-align: center; font-size: 19px; font-weight: bold;
         font-variant-numeric: tabular-nums; }}
  .warn {{ color: #7a2318; font-weight: bold; font-size: 12px; min-height: 16px; }}
</style>

<div class="wrap">
  <h1>Wind Face &mdash; Dead Reckoning Computer</h1>

  <div class="readout">
    <div><b id="o-hdg">&mdash;</b><span>Heading &deg;M</span></div>
    <div><b id="o-gs">&mdash;</b><span>Ground Speed</span></div>
    <div><b id="o-wca">&mdash;</b><span>Drift</span></div>
  </div>
  <div class="warn" id="o-warn"></div>

  <svg viewBox="0 0 500 500" width="100%" class="face">
    {wind_grid()}
    <!-- azimuth disc rotates with the course, as the real one does -->
    <g id="disc" transform="rotate(0 {CX} {CY})" opacity="0.55">
      {azimuth_disc()}
    </g>
    <!-- wind dot: bearing = direction wind blows FROM, radius = speed -->
    <circle id="winddot" cx="{CX}" cy="{CY - 60}" r="6" fill="#7a2318"/>
    <line id="windline" x1="{CX}" y1="{CY}" x2="{CX}" y2="{CY - 60}"
          stroke="#7a2318" stroke-width="1.6"/>
    <!-- true index -->
    <polygon points="{CX},{CY - RADIUS - 12} {CX - 9},{CY - RADIUS + 4} {CX + 9},{CY - RADIUS + 4}"
             fill="#241f18"/>
    <circle cx="{CX}" cy="{CY}" r="3.5" fill="#241f18"/>
  </svg>

  <div class="ctl"><label>Course</label><div class="btns">
    <button data-f="crs" data-d="-10">&minus;10</button>
    <button data-f="crs" data-d="-1">&minus;1</button>
    <span class="cur" id="v-crs"></span>
    <button data-f="crs" data-d="1">+1</button>
    <button data-f="crs" data-d="10">+10</button></div></div>

  <div class="ctl"><label>TAS</label><div class="btns">
    <button data-f="tas" data-d="-10">&minus;10</button>
    <button data-f="tas" data-d="-5">&minus;5</button>
    <span class="cur" id="v-tas"></span>
    <button data-f="tas" data-d="5">+5</button>
    <button data-f="tas" data-d="10">+10</button></div></div>

  <div class="ctl"><label>Wind from</label><div class="btns">
    <button data-f="wdir" data-d="-10">&minus;10</button>
    <button data-f="wdir" data-d="-5">&minus;5</button>
    <span class="cur" id="v-wdir"></span>
    <button data-f="wdir" data-d="5">+5</button>
    <button data-f="wdir" data-d="10">+10</button></div></div>

  <div class="ctl"><label>Wind mph</label><div class="btns">
    <button data-f="wspd" data-d="-5">&minus;5</button>
    <button data-f="wspd" data-d="-1">&minus;1</button>
    <span class="cur" id="v-wspd"></span>
    <button data-f="wspd" data-d="1">+1</button>
    <button data-f="wspd" data-d="5">+5</button></div></div>
</div>

<script>
  const VAR = {R.MAGVAR};
  const S = {{ crs: 130, tas: {R.CRUISE_TAS_MPH:.0f},
              wdir: {R.WIND_FROM_DEG:.0f}, wspd: {R.WIND_MPH:.0f} }};
  const LIM = {{ crs: null, tas: [60, 400], wdir: null, wspd: [0, 99] }};
  const wrap = d => ((d % 360) + 360) % 360;

  function render() {{
    for (const k in S) {{
      const el = document.getElementById("v-" + k);
      el.textContent = (k === "crs" || k === "wdir")
        ? String(S[k]).padStart(3, "0") : S[k];
    }}

    // Rotate the disc so the course sits under the true index, exactly as you
    // would turn the real azimuth ring.
    document.getElementById("disc")
      .setAttribute("transform", `rotate(${{-S.crs}} {CX} {CY})`);

    // Wind dot: plotted from the centre toward where the wind comes from,
    // relative to the course now under the index.
    const rel = (S.wdir - S.crs) * Math.PI / 180;
    const r = Math.min(S.wspd * 1.55, {RADIUS - 12});
    const wx = {CX} + Math.sin(rel) * r, wy = {CY} - Math.cos(rel) * r;
    document.getElementById("winddot").setAttribute("cx", wx.toFixed(1));
    document.getElementById("winddot").setAttribute("cy", wy.toFixed(1));
    document.getElementById("windline").setAttribute("x2", wx.toFixed(1));
    document.getElementById("windline").setAttribute("y2", wy.toFixed(1));

    const xw = S.wspd * Math.sin(rel), hw = S.wspd * Math.cos(rel);
    const ratio = xw / S.tas;
    const warn = document.getElementById("o-warn");
    const put = (id, txt) => document.getElementById(id).textContent = txt;

    if (Math.abs(ratio) >= 1) {{
      put("o-hdg", "—"); put("o-gs", "—"); put("o-wca", "—");
      warn.textContent = "Wind exceeds airspeed across track — course cannot be held.";
      return;
    }}
    const wca = Math.asin(ratio) * 180 / Math.PI;
    const gs = S.tas * Math.cos(wca * Math.PI / 180) - hw;
    put("o-hdg", String(Math.round(wrap(S.crs + wca - VAR))).padStart(3, "0"));
    put("o-gs", gs > 0 ? Math.round(gs) : "—");
    put("o-wca", (wca >= 0 ? "R" : "L") + Math.abs(wca).toFixed(0) + "\\u00b0");
    warn.textContent = gs > 0 ? "" : "Groundspeed zero — you would go backwards.";
  }}

  document.addEventListener("click", e => {{
    const b = e.target.closest("button");
    if (!b) return;
    const f = b.dataset.f, d = Number(b.dataset.d), lim = LIM[f];
    S[f] = lim ? Math.min(lim[1], Math.max(lim[0], S[f] + d)) : wrap(S[f] + d);
    render();
  }});
  render();
</script>

"""


if __name__ == "__main__":
    config.ensure_dirs(); out = config.KNEEBOARD_OUT / "e6b.html"
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out}  (heading output is MAGNETIC, var {R.MAGVAR:.0f}E applied)")
