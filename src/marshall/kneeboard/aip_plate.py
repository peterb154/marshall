"""The real published approach plate for whatever field we're flying, scanned.

Every other page in `kneeboard/` is *generated* from `route.py`, so the chart
cannot disagree with the sim. This one is the opposite, deliberately: it is the
authority the generated pages are supposed to agree WITH. Carrying both on the
kneeboard makes a disagreement visible in the air rather than discovered
afterwards -- the IF distance, the FAP, the missed approach, the descent table.
Several of those were invented differently by this project before anyone looked
at the real document.

It is `profile.plate_png` that decides which chart appears, so this page follows
the profile to a new field with no code change. A profile with no scan on file
still flies; it just has no scan on the kneeboard, and this page says so rather
than rendering a broken image.

Inlined as a data URI: OpenKneeboard's embedded Chromium never issues requests
for sub-resources -- not iframes, and not images either (docs/GOTCHAS.md).
Whatever the page needs has to already be in the page.
"""

from __future__ import annotations

import base64
from pathlib import Path

from marshall.core import route as R

PLATES = Path(__file__).parent / "plates"

P = R.BATUMI_ASR


def plate_path(profile: R.ApproachProfile = P) -> Path | None:
    """The scan for this profile, if we hold one."""
    name = getattr(profile, "plate_png", "")
    if not name:
        return None
    path = PLATES / name
    return path if path.exists() else None


def has_plate(profile: R.ApproachProfile = P) -> bool:
    return plate_path(profile) is not None


def build(profile: R.ApproachProfile = P) -> str:
    path = plate_path(profile)
    field = profile.beacon.name
    chart = getattr(profile, "chart_name", "") or "published chart"

    if path is None:
        return f"""
<style>
  .aip {{ font: 13px/1.6 "Courier New", monospace; color: #3a3427; padding: 24px; }}
</style>
<div class="aip">
  <b>{field}</b> — no published plate on file.<br>
  The approach is flown from the profile in <code>route.py</code>; drop a scan
  into <code>kneeboard/plates/</code> and name it in the profile's
  <code>plate_png</code> to have it appear here.
</div>
"""

    img = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"""
<style>
  .aip {{ margin: 0; background: #fff; }}
  .aip img {{ display: block; width: 100%; max-width: 100%; height: auto; }}
  .aip .src {{ font: 11px/1.4 "Courier New", monospace; color: #5a5142;
               background: #d9cfb4; padding: 4px 8px; }}
</style>
<div class="aip">
  <div class="src">{field.upper()} &middot; {chart} &mdash; the published chart.
     Our approach is anchored to it.</div>
  <img src="data:image/png;base64,{img}" alt="{field} published approach plate">
</div>
"""


if __name__ == "__main__":
    from marshall import config
    config.ensure_dirs()
    out = config.KNEEBOARD_OUT / "plate-aip.html"
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size:,} B)")
