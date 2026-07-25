"""A map of the route, drawn to scale, for the kneeboard.

The nav log says what to fly and the brief says why; neither shows the SHAPE.
And on this sortie the shape is the whole point -- the route goes out to sea and
round the top precisely because the direct line crosses three defended fields,
and a table of headings does not make that obvious the way a picture does.

Drawn from route.py, so it cannot show a route the flight is not flying. Plain
SVG inline in the page: no tiles, no external anything, which is a hard
requirement -- OpenKneeboard's Chromium fetches no sub-resources at all.

Deliberately not a chart. There is no terrain and no coastline, because getting
those slightly wrong is worse than leaving them out: a pilot who trusts a
hand-drawn coast will fly into it. What is here is what we know exactly --
where the route goes, where the guns are, and how far apart those two things
are.
"""

from __future__ import annotations

from marshall.core import route as R

P = R.BATUMI_ASR
M_PER_NM = 1852.0

W, H = 900, 1080          # kneeboard-ish portrait
PAD = 70


def _bounds():
    """Everything that must fit, plus the threat rings' radius."""
    xs = [f.x for f in R.SORTIE] + [d[1] for d in R.DEFENDED]
    zs = [f.z for f in R.SORTIE] + [d[2] for d in R.DEFENDED]
    pad = 8 * M_PER_NM
    return min(xs) - pad, max(xs) + pad, min(zs) - pad, max(zs) + pad


def build(profile=P) -> str:
    x0, x1, z0, z1 = _bounds()
    # x is NORTH and z is EAST, so the map's horizontal axis is z and its
    # vertical axis is x -- inverted, because north belongs at the top.
    span_x, span_z = x1 - x0, z1 - z0
    scale = min((W - 2 * PAD) / span_z, (H - 2 * PAD) / span_x)
    # Centre the drawing in whichever direction is not the limiting one.
    # Anchoring both axes to the corner instead left the whole route squashed
    # into the bottom of the page with half the sheet blank above it.
    off_z = (W - span_z * scale) / 2
    off_x = (H - span_x * scale) / 2

    def sx(z: float) -> float:
        return off_z + (z - z0) * scale

    def sy(x: float) -> float:
        return H - off_x - (x - x0) * scale

    legs = R.solve_route(legs=R.SORTIE_LEGS)

    # Threat rings first, so the route draws over them.
    rings = "".join(
        f'<circle cx="{sx(z):.1f}" cy="{sy(x):.1f}" r="{reach * M_PER_NM * scale:.1f}" '
        f'fill="#b03024" fill-opacity="0.13" stroke="#b03024" stroke-width="1.5" '
        f'stroke-dasharray="6 4"/>'
        f'<text x="{sx(z):.1f}" y="{sy(x) - reach * M_PER_NM * scale - 6:.1f}" '
        f'text-anchor="middle" font-size="13" fill="#8a2318">{name.upper()} AAA</text>'
        for name, x, z, reach in R.DEFENDED)

    # The route.
    path = " ".join(f"{'M' if i == 0 else 'L'} {sx(f.z):.1f} {sy(f.x):.1f}"
                    for i, f in enumerate(R.SORTIE))
    route = (f'<path d="{path}" fill="none" stroke="#1b3fa0" stroke-width="3" '
             f'stroke-linejoin="round"/>')

    # Waypoints, with the leg heading and distance written along the way out.
    marks = []
    for i, f in enumerate(R.SORTIE[:-1]):
        cx, cy = sx(f.z), sy(f.x)
        marks.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" fill="#fff" '
            f'stroke="#1b3fa0" stroke-width="2.5"/>'
            f'<text x="{cx + 9:.1f}" y="{cy - 8:.1f}" font-size="14" '
            f'font-weight="bold" fill="#1b3fa0">{i + 1}. {f.name}</text>')
    for leg in legs:
        mx = (sx(leg.frm.z) + sx(leg.to.z)) / 2
        my = (sy(leg.frm.x) + sy(leg.to.x)) / 2
        marks.append(
            f'<text x="{mx:.1f}" y="{my:.1f}" font-size="12" fill="#1b3fa0" '
            f'text-anchor="middle" paint-order="stroke" stroke="#e8dfc4" '
            f'stroke-width="4">{leg.heading_mag:03.0f}&#176; '
            f'{leg.distance_nm:.0f}nm</text>')

    # The target.
    t = R.TARGET_AREA
    marks.append(
        f'<circle cx="{sx(t.z):.1f}" cy="{sy(t.x):.1f}" '
        f'r="{5 * M_PER_NM * scale:.1f}" fill="#b03024" fill-opacity="0.18" '
        f'stroke="#b03024" stroke-width="2"/>')

    # A scale bar, because a map without one invites guessing at distances.
    bar_nm = 20
    bar = bar_nm * M_PER_NM * scale
    scale_bar = (
        f'<line x1="{PAD}" y1="{H - 28}" x2="{PAD + bar:.1f}" y2="{H - 28}" '
        f'stroke="#2b2620" stroke-width="3"/>'
        f'<text x="{PAD + bar / 2:.1f}" y="{H - 34}" text-anchor="middle" '
        f'font-size="12" fill="#2b2620">{bar_nm} nm</text>')

    total = sum(l.distance_nm for l in legs)
    mins = sum(l.minutes for l in legs)

    return f"""<title>Route Map</title>
<style>
  .rm {{ font: 13px/1.4 "Courier New", monospace; color: #2b2620;
         background: #e8dfc4; padding: 12px 14px; }}
  .rm h1 {{ font-size: 17px; margin: 0 0 2px; letter-spacing: 1.5px; }}
  .rm .sub {{ font-size: 12px; color: #5a5142; margin-bottom: 6px; }}
  .rm svg {{ display: block; background: #e8dfc4; }}
</style>
<div class="rm">
  <h1>OPERATION SAMOVAR &mdash; ROUTE</h1>
  <div class="sub">{total:.0f} nm, {int(mins)}:{round((mins % 1) * 60):02d}
    &middot; north up &middot; dashed rings are heavy flak, and are the guns'
    REACH, not their position</div>
  <svg width="{W}" height="{H}" viewBox="0 0 {W} {H}"
       xmlns="http://www.w3.org/2000/svg">
    {rings}
    {route}
    {''.join(marks)}
    {scale_bar}
  </svg>
</div>
"""


if __name__ == "__main__":
    from marshall import config
    config.ensure_dirs()
    out = config.KNEEBOARD_OUT / "routemap.html"
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out}")
