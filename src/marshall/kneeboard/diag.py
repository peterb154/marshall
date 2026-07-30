"""Live diagnostics: what the two brains believe, right now, on a kneeboard.

    "I'll bet if I could see state machine info I'd know why / when things are
     going wrong."

Every sortie this month has been debugged the same way: fly, land, read a
transcript, guess. The state that would have answered the question existed at
the time and was gone by the time anybody looked. This puts it on a page in the
cockpit while the aeroplane is still flying.

NOTHING NEW IS INSTRUMENTED, and that is the point. The bridge already appends a
JSON line per transmission to `build/logs/flight-<session>.jsonl` -- identity
with its authority, the deterministic engine's whole board, the computed
directive, the roster verdicts, and the scope as it stood. This reads that file
and the director's `/radar`, and renders. So it cannot perturb the thing it is
measuring: a diagnostic that can break a sortie is one nobody dares run during
one.

FOUR PANELS, chosen from what actually cost time:

  WHO      per radio: the SRS name, what Whisper made of the callsign, who the
           ladder concluded, and on what AUTHORITY. Anything not `radar` is a
           finding rather than a curiosity -- see atc/identity.py.
  BOARD    what the deterministic engine believes is flying, beside what radar
           shows, WITH THE DIVERGENCE MARKED. The engine is blind by design; it
           knows only what pilots reported. Every ghost -- an aeroplane holding
           a level in the stack that nobody was flying -- is these two lists
           disagreeing, and there has never been a way to see it happen.
  LAST     one transmission end to end: heard, which gate it passed, who it was
           attributed to, what the engine computed, and what was said. The
           two-brain seam in five lines.
  FLIGHTS  the roster and the approach phase per aircraft: the state machines.

THE DIVERGENCE COMPARISON IS THE DELICATE PART. The board is keyed on callsigns,
handles and flight names; the scope prints unit names and labels. Comparing them
directly is the exact bug the 29 July audit found in `release_stale` -- a set of
printed radar names tested against board keys, so the test could never match and
the entry was immortal. `_on_scope` below does the conversion properly, and it
is the one piece of logic here worth a test.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from marshall import config

LOGS = config.BUILD_DIR / "logs"
# Same variable the PLANS page already reads, for the same reason: inside the
# container `localhost` is the container, and the director is published on the
# host. See kneeboard/plans.py and the extra_hosts note in the compose file.
DIRECTOR = os.environ.get("MARSHALL_DIRECTOR_URL", "http://localhost:8000")
RADAR_URL = f"{DIRECTOR}/radar"

# How much of the recorder to read. A sortie is a few hundred lines; this is
# generous and still one cheap read.
TAIL_BYTES = 512_000


def newest_session() -> str:
    files = sorted(LOGS.glob("flight-*.jsonl"), key=lambda p: p.stat().st_mtime)
    return files[-1].stem[len("flight-"):] if files else ""


def _events(session: str) -> list[dict]:
    path = LOGS / f"flight-{session}.jsonl"
    if not path.is_file():
        return []
    size = path.stat().st_size
    with open(path, "rb") as fh:
        if size > TAIL_BYTES:
            fh.seek(size - TAIL_BYTES)
            fh.readline()                     # discard the partial first line
        raw = fh.read().decode("utf-8", errors="replace")
    out = []
    for line in raw.splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue                          # a half-written tail line
    return out


def radar(url: str = RADAR_URL, timeout: float = 2.5) -> str:
    """The live scope. Best effort: the page is still useful without it."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode()).get("picture", "")
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return ""


def _key(s: str) -> str:
    return "".join(c for c in (s or "").lower() if c.isalnum())


def _on_scope(callsign: str, units, labels: set[str]) -> bool:
    """Is this BOARD entry something radar can actually see?

    THE CONVERSION IS THE WHOLE FUNCTION. A board key is a spoken callsign, a
    handle or a flight name; a scope line prints a unit name and, once something
    has correlated it, a bracketed label. `release_stale` compared the two
    directly and the test could never match -- so the entry it existed to remove
    was immortal, which is finding 1.1 of the 29 July audit.

    Four ways an entry is accounted for, any one of which is enough: the label
    radar is printing, the unit name, the HANDLE of the unit name (`362nd_sockeye`
    is `sockeye`), or the callsign already bound to the line.
    """
    from marshall.atc import identity
    k = _key(callsign)
    if not k:
        return False
    if k in labels:
        return True
    for u in units:
        if k in (_key(u.name), _key(identity.handle(u.name)), _key(u.callsign)):
            return True
    return False


def _flights_from(events: list[dict]) -> list[dict]:
    """Replay the roster verdicts into the roster they describe."""
    flights: dict[str, dict] = {}
    for e in events:
        kind, name, who = e.get("kind", ""), e.get("callsign", ""), e.get("who", "")
        if kind == "flight/created":
            flights[name] = {"name": name, "lead": who, "members": [],
                             "since": e.get("t", 0)}
        elif kind == "flight/joined" and name in flights:
            m = flights[name]["members"]
            if who and who not in m and who != flights[name]["lead"]:
                m.append(who)
            flights[name]["miles"] = e.get("miles")
        elif kind in ("flight/left", "flight/dissolved"):
            f = flights.get(name)
            if not f:
                continue
            if kind == "flight/dissolved" or f["lead"] == who:
                flights.pop(name, None)
            elif who in f["members"]:
                f["members"].remove(who)
    return sorted(flights.values(), key=lambda f: f["name"])


# The transmission-level events that belong to the call before them, in the
# order a reader wants them: what it was, then what each brain did about it.
_TRAIL = ("dropped", "ship-to-ship", "atc/challenge", "flight/created",
          "flight/joined", "flight/refused", "flight/left", "flight/dissolved",
          "controller", "asr", "atc/pilot", "atc/simple", "atc/vector",
          "atc/range", "atc/landed", "board")


def state(session: str = "", scope: str | None = None) -> dict:
    """Everything the page draws, as one JSON-able dict."""
    from marshall.atc import identity

    session = session or newest_session()
    events = _events(session) if session else []
    scope = radar() if scope is None else scope
    units = identity.units_on(scope)
    labels = {_key(u.callsign) for u in units if u.callsign}
    now = time.time()

    # WHO -- the latest resolution per radio, newest first.
    radios: dict[str, dict] = {}
    for e in events:
        if e.get("kind") != "pilot":
            continue
        radios[e.get("srs_name") or "?"] = {
            "radio": e.get("srs_name") or "?",
            "heard": e.get("claimed") or "",
            "is": e.get("callsign") or "",
            "authority": e.get("authority") or "",
            "track": e.get("track") or "",
            "why": e.get("why") or "",
            "ago": round(now - e.get("t", now), 1),
        }

    # BOARD -- the engine's own account, already structured. Newest wins.
    board = []
    for e in events:
        if e.get("kind") == "board" and isinstance(e.get("board"), list):
            board = e["board"]
    for row in board:
        row["on_scope"] = _on_scope(row.get("callsign", ""), units, labels)

    # LAST -- one transmission, from the words to what was said.
    last: dict = {}
    idx = max((i for i, e in enumerate(events) if e.get("kind") == "pilot"),
              default=-1)
    if idx >= 0:
        p = events[idx]
        last = {
            "heard": p.get("transcript") or "",
            "who": p.get("callsign") or "",
            "authority": p.get("authority") or "",
            "track": p.get("track") or "",
            "why": p.get("why") or "",
            "freq": p.get("freq_mhz"),
            "ago": round(now - p.get("t", now), 1),
            "trail": [],
        }
        for e in events[idx + 1:]:
            if e.get("kind") == "pilot":
                break
            if e.get("kind") in _TRAIL and e.get("kind") != "board":
                last["trail"].append({
                    "kind": e.get("kind"),
                    "text": (e.get("text") or "")[:400],
                    "seconds": e.get("seconds"),
                    "tier": e.get("tier"),
                    "gate": e.get("gate"),
                })

    return {
        "session": session,
        "at": now,
        "recorder_age": round(now - max((e.get("t", 0) for e in events),
                                        default=now), 1) if events else None,
        "radar_ok": bool(scope),
        "radios": sorted(radios.values(), key=lambda r: r["ago"]),
        "board": board,
        "scope": [{"name": u.name, "callsign": u.callsign, "type": u.type,
                   "manned": u.manned, "on_ground": u.on_ground} for u in units],
        "ghosts": [r["callsign"] for r in board if not r["on_scope"]],
        "flights": _flights_from(events),
        "last": last,
    }


def page() -> str:
    """The diagnostics kneeboard. Self-contained; polls /diag.json."""
    return _PAGE


# --- the page ---------------------------------------------------------------
#
# A cockpit instrument, not a log viewer. Dark because it is read over a
# night approach, monospace because every column is data, and colour used for
# exactly one thing: something disagreeing with something else. If the page is
# all one colour, the two brains agree.
_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Marshall diagnostics</title>
<style>
  :root{
    --bg:#0A0C0E; --panel:#111518; --rule:#1F262C; --dim:#6C767E;
    --ink:#D8DEE2; --ok:#5FA88C; --warn:#E0A040; --bad:#D4604F; --accent:#7FB3D5;
    --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--mono);
    font-size:15px;line-height:1.45;-webkit-font-smoothing:antialiased}
  header{display:flex;gap:1.2rem;align-items:baseline;flex-wrap:wrap;
    padding:.6rem 1rem;border-bottom:1px solid var(--rule);background:var(--panel)}
  header b{letter-spacing:.14em;font-size:.8rem;color:var(--dim);font-weight:600}
  header .stat{font-size:.78rem;color:var(--dim)}
  header .stat i{font-style:normal;color:var(--ink)}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--rule)}
  section{background:var(--bg);padding:.75rem 1rem 1rem;min-width:0}
  h2{font-size:.7rem;letter-spacing:.16em;text-transform:uppercase;color:var(--dim);
    margin:0 0 .6rem;font-weight:600}
  table{border-collapse:collapse;width:100%;font-size:.83rem;
    font-variant-numeric:tabular-nums}
  th{text-align:left;color:var(--dim);font-weight:400;font-size:.68rem;
    letter-spacing:.1em;text-transform:uppercase;padding:0 .6rem .3rem 0;
    border-bottom:1px solid var(--rule)}
  td{padding:.28rem .6rem .28rem 0;border-bottom:1px solid #14191D;
    vertical-align:top;word-break:break-word}
  tr:last-child td{border-bottom:0}
  .ok{color:var(--ok)} .warn{color:var(--warn)} .bad{color:var(--bad)}
  .dim{color:var(--dim)} .acc{color:var(--accent)}
  .ghost td{background:rgba(212,96,79,.10)}
  .pill{display:inline-block;padding:0 .4em;border:1px solid currentColor;
    border-radius:2px;font-size:.7rem;letter-spacing:.05em}
  .trail{margin:0;padding:0;list-style:none;font-size:.83rem}
  .trail li{padding:.2rem 0;border-bottom:1px solid #14191D;display:grid;
    grid-template-columns:5.5rem 1fr;gap:.7rem}
  .trail li:last-child{border-bottom:0}
  .trail .k{color:var(--dim);font-size:.7rem;letter-spacing:.09em;
    text-transform:uppercase;padding-top:.15rem}
  .heard{color:var(--accent)}
  #stale{background:var(--warn);color:#0A0C0E;padding:.45rem 1rem;
    font-size:.8rem;letter-spacing:.04em}
  #control{display:flex;align-items:center;gap:.55rem;flex-wrap:wrap;
    padding:.5rem 1rem;border-bottom:1px solid var(--rule);background:var(--panel)}
  #control .lbl{font-size:.66rem;letter-spacing:.16em;color:var(--dim)}
  #control .sep{width:1px;height:1.1rem;background:var(--rule);margin:0 .35rem}
  #control button{font-family:var(--mono);font-size:.72rem;letter-spacing:.06em;
    background:transparent;color:var(--ink);border:1px solid var(--rule);
    border-radius:2px;padding:.2rem .6rem;cursor:pointer}
  #control button:hover:not(:disabled){border-color:var(--accent);color:var(--accent)}
  #control button:disabled{opacity:.35;cursor:not-allowed}
  #control button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  #cmsg{font-size:.72rem;color:var(--dim)}
  .empty{color:var(--dim);font-size:.8rem;padding:.4rem 0}
  @media (max-width:900px){.grid{grid-template-columns:1fr}}
</style></head><body>
<div id="stale" style="display:none"></div>
<header>
  <b>MARSHALL DIAG</b>
  <span class="stat">session <i id="sess">-</i></span>
  <span class="stat">recorder <i id="age">-</i></span>
  <span class="stat">radar <i id="radar">-</i></span>
  <span class="stat" id="verdict"></span>
</header>
<div id="control">
  <span class="lbl">BRIDGE</span>
  <span id="bstate" class="pill">-</span>
  <button data-do="start">start</button>
  <button data-do="restart">restart</button>
  <button data-do="stop">stop</button>
  <span class="sep"></span>
  <span class="lbl">MISSION</span>
  <button data-do="mission">reload current</button>
  <span id="cmsg"></span>
</div>
<div class="grid">
  <section><h2>Board vs scope &mdash; ghosts</h2><div id="board"></div></section>
  <section><h2>The last turn, stage by stage</h2><div id="last"></div></section>
  <section><h2>On the frequency</h2><div id="who"></div></section>
  <section><h2>Phase</h2><div id="flights"></div></section>
</div>
<script>
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/[&<>]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const AUTH = { radar: 'ok', plan: 'warn', roster: 'warn', '': 'bad' };

function who(rs) {
  if (!rs.length) return '<p class="empty">no transmissions recorded yet</p>';
  return '<table><tr><th>radio</th><th>heard</th><th>is</th><th>auth</th>'
    + '<th>track</th><th>ago</th></tr>' + rs.map(r => {
      const cls = AUTH[r.authority] !== undefined ? AUTH[r.authority] : 'warn';
      return `<tr><td>${esc(r.radio)}</td>`
        + `<td class="dim">${esc(r.heard) || '&mdash;'}</td>`
        + `<td class="acc">${esc(r.is) || '&mdash;'}</td>`
        + `<td class="${cls}"><span class="pill">${esc(r.authority) || 'none'}</span></td>`
        + `<td class="dim">${esc(r.track) || '&mdash;'}</td>`
        + `<td class="dim">${r.ago}s</td></tr>`
        + (r.authority !== 'radar' && r.why
            ? `<tr><td></td><td colspan="5" class="dim">${esc(r.why)}</td></tr>` : '');
    }).join('') + '</table>';
}

function board(d) {
  const b = d.board || [], s = d.scope || [];
  if (!b.length && !s.length) return '<p class="empty">board empty, radar shows nothing</p>';
  const rows = Math.max(b.length, s.length);
  let out = '<table><tr><th>engine believes</th><th>phase</th><th>radar shows</th></tr>';
  for (let i = 0; i < rows; i++) {
    const e = b[i], u = s[i];
    const ghost = e && !e.on_scope;
    out += `<tr class="${ghost ? 'ghost' : ''}">`
      + `<td class="${ghost ? 'bad' : ''}">${e ? esc(e.callsign) : ''}`
      + `${ghost ? ' <span class="pill">not on radar</span>' : ''}</td>`
      + `<td class="dim">${e ? esc(e.phase) + (e.assigned_ft ? ' ' + e.assigned_ft + 'ft' : '')
          + (e.in_letdown ? ' <span class="pill warn">letdown</span>' : '') : ''}</td>`
      + `<td class="dim">${u ? esc(u.callsign || u.name)
          + (u.manned ? ' <span class="pill ok">manned</span>' : '')
          + (u.on_ground ? ' <span class="pill">ground</span>' : '') : ''}</td></tr>`;
  }
  return out + '</table>';
}

function last(l) {
  if (!l || !l.heard) return '<p class="empty">nothing heard yet</p>';
  const auth = AUTH[l.authority] !== undefined ? AUTH[l.authority] : 'warn';
  let out = '<ul class="trail">'
    + `<li><span class="k">heard</span><span class="heard">${esc(l.heard)}</span></li>`
    + `<li><span class="k">who</span><span>${esc(l.who) || '<i class="dim">unidentified</i>'}`
    + ` <span class="pill ${auth}">${esc(l.authority) || 'none'}</span>`
    + `<span class="dim"> ${esc(l.track)}</span></span></li>`;
  // THE PIPELINE, not the gates. Four of the five gates were deleted on 30
  // July -- ATC answers everything now -- so "which gate ate it" is no longer
  // the question. The question is which STAGE last touched the turn:
  // hear, attribute, membership, decide, settle, compose, speak.
  const STAGE = {
    'dropped':        ['admit',    'bad'],
    'ship-to-ship':   ['admit',    'bad'],
    'atc/challenge':  ['admit',    'warn'],
    'flight/created': ['membership','ok'],
    'flight/joined':  ['membership','ok'],
    'flight/refused': ['membership','warn'],
    'flight/left':    ['membership','ok'],
    'flight/dissolved':['membership','warn'],
    'controller':     ['decide',   'ok'],
    'asr':            ['decide',   'ok'],
    'atc/pilot':      ['speak',    ''],
    'atc/simple':     ['speak',    ''],
    'atc/vector':     ['speak',    ''],
    'atc/range':      ['speak',    ''],
    'atc/landed':     ['speak',    ''],
  };
  (l.trail || []).forEach(t => {
    const [stage, cls] = STAGE[t.kind] || [t.kind.replace('atc/', ''), ''];
    out += `<li><span class="k">${esc(stage)}</span>`
      + `<span class="${cls}">${esc(t.gate || t.text)}`
      + (t.seconds ? `<span class="dim"> ${t.seconds}s ${esc(t.tier || '')}</span>` : '')
      + '</span></li>';
  });
  return out + `</ul><p class="empty">${l.ago}s ago on ${l.freq || '?'}</p>`;
}

function flights(d) {
  const f = d.flights || [], b = d.board || [];
  let out = '';
  out += f.length
    ? '<table><tr><th>flight</th><th>lead</th><th>members</th></tr>'
      + f.map(x => `<tr><td class="acc">${esc(x.name)}</td><td>${esc(x.lead)}</td>`
        + `<td class="dim">${x.members.length ? esc(x.members.join(', ')) : '&mdash;'}`
        + `${x.miles != null ? ' <span class="dim">' + x.miles + 'nm</span>' : ''}</td></tr>`
        ).join('') + '</table>'
    : '<p class="empty">no flights formed</p>';
  out += '<h2 style="margin-top:1rem">Phase</h2>';
  out += b.length
    ? '<table><tr><th>callsign</th><th>phase</th><th>assigned</th><th>id</th></tr>'
      + b.map(r => `<tr><td>${esc(r.callsign)}</td><td class="dim">${esc(r.phase)}</td>`
        + `<td class="dim">${r.assigned_ft ? r.assigned_ft + ' ft' : '&mdash;'}</td>`
        + `<td class="${r.identified ? 'ok' : 'dim'}">${r.identified ? 'radar' : '&mdash;'}</td></tr>`
        ).join('') + '</table>'
    : '<p class="empty">nobody on the board</p>';
  return out;
}

async function tick() {
  try {
    const d = await (await fetch('/diag.json', {cache: 'no-store'})).json();
    $('sess').textContent = d.session || 'none';
    $('age').textContent = d.recorder_age == null ? 'no file' : d.recorder_age + 's';
    $('age').className = (d.recorder_age != null && d.recorder_age > 120) ? 'warn' : '';
    $('radar').textContent = d.radar_ok ? 'up' : 'no contacts';
    $('radar').className = d.radar_ok ? 'ok' : 'warn';
    // HISTORY MUST NOT READ AS STATE. With the bridge stopped the recorder
    // stops moving and the last board sits there looking live -- which would
    // have the page confidently reporting ghosts from a sortie that ended
    // hours ago. Say so, loudly, above everything else.
    const st = $('stale'), age = d.recorder_age;
    if (age == null) {
      st.style.display = 'block';
      st.textContent = 'No flight recorder yet \u2014 the bridge has not run for this mission.';
    } else if (age > 120) {
      st.style.display = 'block';
      const mins = Math.round(age / 60);
      st.textContent = 'Recorder last moved ' + (mins > 90
        ? Math.round(mins / 60) + ' h' : mins + ' min')
        + ' ago \u2014 this is the LAST sortie, not live state. Is the bridge running?';
    } else {
      st.style.display = 'none';
    }
    const g = (d.ghosts || []).length;
    $('verdict').innerHTML = g
      ? `<span class="bad">${g} on the board that radar cannot see</span>`
      : '<span class="ok">board and radar agree</span>';
    $('who').innerHTML = who(d.radios || []);
    $('board').innerHTML = board(d);
    $('last').innerHTML = last(d.last);
    $('flights').innerHTML = flights(d);
  } catch (e) {
    $('verdict').innerHTML = '<span class="bad">diag unreachable</span>';
  }
}
// --- control ---------------------------------------------------------------
// The token is not in the page. It is asked for once and kept in this tab, so
// the page can be left open on a kneeboard without carrying the ability to
// stop the bridge into a screenshot.
let TOKEN = sessionStorage.getItem('marshall-token') || '';

async function control(what) {
  if (!TOKEN) {
    TOKEN = prompt('Control token (MARSHALL_CONTROL_TOKEN in .env):') || '';
    if (!TOKEN) return;
    sessionStorage.setItem('marshall-token', TOKEN);
  }
  const url = what === 'mission'
    ? '/control/mission/restart?token=' + encodeURIComponent(TOKEN)
    : '/control/bridge/' + what + '?token=' + encodeURIComponent(TOKEN);
  $('cmsg').textContent = what + '...';
  $('cmsg').className = '';
  try {
    const r = await fetch(url, {method: 'POST', cache: 'no-store'});
    const d = await r.json();
    if (r.status === 403) { sessionStorage.removeItem('marshall-token'); TOKEN = ''; }
    $('cmsg').textContent = d.ok
      ? (d.mission ? 'reloading ' + d.mission : (d.note || 'asked'))
      : (d.error || d.detail || 'refused');
    $('cmsg').className = d.ok ? 'ok' : 'bad';
  } catch (e) {
    $('cmsg').textContent = 'no answer from the server';
    $('cmsg').className = 'bad';
  }
}

document.querySelectorAll('#control button').forEach(b =>
  b.addEventListener('click', () => control(b.dataset.do)));

async function bridgeTick() {
  try {
    const d = await (await fetch('/control/bridge', {cache: 'no-store'})).json();
    const el = $('bstate');
    el.textContent = d.supervisor === 'up' ? d.bridge : ('supervisor ' + d.supervisor);
    el.className = 'pill ' + (d.supervisor !== 'up' ? 'bad'
      : d.bridge === 'running' ? 'ok' : 'warn');
    // A button that cannot possibly work should not look like one: with no
    // supervisor the command is written to a spool nobody reads.
    const dead = d.supervisor !== 'up';
    document.querySelectorAll('#control button').forEach(b => {
      b.disabled = dead && b.dataset.do !== 'mission';
    });
    if (dead && d.why) { $('cmsg').textContent = d.why; $('cmsg').className = 'dim'; }
  } catch (e) { /* the page is still useful without it */ }
}

tick();
bridgeTick();
setInterval(tick, 2000);
setInterval(bridgeTick, 2000);
</script></body></html>
"""
