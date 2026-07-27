"""What is on file tonight, as a kneeboard page.

Temporary, and honest about it: eventually a pilot is handed the plan he is
flying and does not shop from a list. Right now he is testing clearance
delivery, and he cannot ask for "Marlin" if he cannot remember what is on the
board — so the board goes in the cockpit.

Read LIVE from the director on every page turn rather than generated into the
chart build. The plans change by migration and by hand while this is being
worked on, and a page built at container start would show last night's board
with no way to tell — which is the exact failure the whole kneeboard server was
rebuilt to prevent.

**A page that cannot reach the director says so.** An empty list renders as a
perfectly good page that means "nothing is filed", and a pilot would believe it.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

# The kneeboard runs in its own container, where `localhost` is that container
# and not the host the director is published on -- so this is configurable and
# the compose file sets it. Defaulting to localhost keeps a bare `python -m
# marshall.kneeboard.serve` on the host working with no environment at all.
DIRECTOR = os.environ.get("MARSHALL_DIRECTOR_URL", "http://localhost:8000")


def filed(base: str = DIRECTOR) -> tuple[list[dict], str]:
    """(plans, error). The error is a sentence to print, not a code."""
    try:
        with urllib.request.urlopen(f"{base}/plans", timeout=4) as r:
            return json.load(r).get("plans") or [], ""
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        return [], f"could not reach the director at {base} — {e}"


CSS = """
  .fp { font: 15px/1.35 "Courier New", monospace; color: #1d1a14;
        background: #e8dfc4; padding: 14px 16px; }
  .fp h1 { font-size: 20px; margin: 0 0 2px; letter-spacing: 1.5px; }
  .fp .sub { font-size: 13px; color: #5a5142; margin-bottom: 10px; }
  .fp .plan { border-top: 1px solid #b9ad8c; padding: 8px 0; }
  .fp .hd { display: flex; align-items: baseline; gap: 10px; }
  .fp .label { font-size: 21px; font-weight: bold; letter-spacing: 1px; }
  .fp .alt { background: #1b3fa0; color: #fff; padding: 1px 6px;
             border-radius: 3px; font-size: 13px; font-weight: bold; }
  .fp .task { margin: 3px 0 0 4px; }
  .fp .route { margin: 3px 0 0 4px; font-size: 14px; color: #2f4a24;
               letter-spacing: 0.5px; }
  .fp .route:before { content: "▸ "; }
  .fp .warn { background: #f2e3c4; border-left: 4px solid #b03024;
              padding: 7px 10px; margin: 8px 0; }
  .fp .note { margin-top: 12px; font-size: 13px; color: #4a4335;
              border-left: 2px solid #b9ad8c; padding-left: 8px; }
  .fp .dup { color: #b03024; font-size: 12px; }
"""


def _esc(s: str) -> str:
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _feet(ft) -> str:
    return f"{int(ft):,} ft" if ft else "—"


def build() -> str:
    plans, err = filed()

    body = ['<div class="fp">',
            "<h1>FLIGHT PLANS ON FILE</h1>",
            '<div class="sub">ask Batumi Ground on 118 · say the name, or say '
            'what you are doing</div>']

    if err:
        body.append(f'<div class="warn"><b>NO BOARD.</b> {_esc(err)}<br>'
                    f'This page is not "nothing is filed" — it is "nobody '
                    f'answered". Do not fly the clearance tests until it '
                    f'reads.</div>')
    elif not plans:
        body.append('<div class="warn"><b>NOTHING FILED.</b> The director '
                    'answered and the board is empty.</div>')

    # Tasks that name more than one plan. Marked, because that is the case the
    # controller must answer with a QUESTION -- and a pilot who does not know
    # which two are alike cannot tell a correct question from a stalled one.
    firstword: dict[str, int] = {}
    for p in plans:
        key = (p.get("task") or "").split(",")[0].strip().lower()
        firstword[key] = firstword.get(key, 0) + 1

    for p in plans:
        key = (p.get("task") or "").split(",")[0].strip().lower()
        dup = ('<span class="dup">— shares this task; he should ASK which</span>'
               if firstword.get(key, 0) > 1 else "")
        body.append('<div class="plan">')
        body.append(f'<div class="hd"><span class="label">'
                    f'{_esc(p.get("label") or p.get("name"))}</span>'
                    f'<span class="alt">{_feet(p.get("cruise_ft"))}</span>'
                    f'{dup}</div>')
        body.append(f'<div class="task">{_esc(p.get("task"))}</div>')
        body.append(f'<div class="route">{_esc(p.get("route"))}</div>')
        body.append("</div>")

    body.append(
        '<div class="note">Everything returns to Batumi — Kobuleti and Kutaisi '
        'are turning points, not somewhere to land. So the DESTINATION cannot '
        'pick a plan here and asking "IFR to Batumi" should get you a question. '
        'Ask by what you are doing, or by the name.</div>')
    body.append("</div>")
    return f"<style>{CSS}</style>" + "\n".join(body)
