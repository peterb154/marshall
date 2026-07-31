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
from marshall.core import names as _names

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


# The third copy. Unicode-aware where the other two were not, which is how the
# disagreement was found. See `core.names`.
_key = _names.squash


PUBLISHED = config.BUILD_DIR / "control" / "state.json"

# How stale the bridge's snapshot may be before the page stops believing it.
# It publishes on every transmission, so on a quiet frequency this will be
# minutes old and that is not an error -- it is reported, not hidden.
def published(max_age: float = 3600.0) -> dict:
    """What the BRIDGE says it believes. The page renders this; it derives
    nothing from it.

    THE DASHBOARD USED TO WORK ALL THIS OUT ITSELF -- replaying the roster from
    recorder events, deciding ghost status by matching a spoken label against a
    printed radar name, and re-parsing the scope prose a third time. All three
    were a surface acting as an authority it is not, and the ghost check was
    wrong in precisely the way audit finding 1.1 was wrong.

    The bridge knows, because it is the thing that decided. See
    `agent_atc.publish_state`.
    """
    # THE PATH IS RESOLVED PER CALL, not at import. `PUBLISHED` is a module
    # constant computed from `config.BUILD_DIR`, so a test that redirects the
    # build dir to a tempdir was still reading the LIVE snapshot -- and passed
    # only for as long as nothing happened to be on the real board. It started
    # failing the moment a pilot checked in, which is a test that was never
    # testing what it said.
    path = config.BUILD_DIR / "control" / "state.json"
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    age = time.time() - float(raw.get("at") or 0)
    raw["age"] = round(age, 1)
    return raw


# The transmission-level events that belong to the call before them, in the
# order a reader wants them: what it was, then what each brain did about it.
_TRAIL = ("dropped", "ship-to-ship", "atc/challenge", "flight/created",
          "flight/joined", "flight/refused", "flight/left", "flight/dissolved",
          "controller", "asr", "atc/pilot", "atc/simple", "atc/vector",
          "atc/range", "atc/landed", "board")


def state(session: str = "", scope: str | None = None) -> dict:
    """Everything the page draws. Read, not derived.

    The recorder still supplies the CONVERSATION -- what was heard and what was
    said, which is a history and belongs in a log. Everything about what the
    system currently BELIEVES comes from the bridge's own snapshot.
    """
    session = session or newest_session()
    events = _events(session) if session else []
    now = time.time()
    live = published()

    # WHO IS TALKING, from the registry that resolved them -- not from the
    # recorder, and not by matching names here.
    radios = []
    for r in live.get("radios", []):
        radios.append({"radio": r.get("guid", ""), "is": r.get("callsign", ""),
                       "authority": r.get("authority", ""),
                       "track": r.get("track", ""), "why": r.get("why", ""),
                       "heard": "", "ago": live.get("age")})
    # The words each radio last used, which only the recorder has.
    for e in events:
        if e.get("kind") != "pilot":
            continue
        for r in radios:
            if r["is"] and r["is"] == e.get("callsign"):
                r["heard"] = e.get("claimed") or ""
                r["ago"] = round(now - e.get("t", now), 1)

    last = _last_turn(events, now)
    board = live.get("board", [])
    return {
        "session": session,
        "at": now,
        "recorder_age": round(now - max((e.get("t", 0) for e in events),
                                        default=now), 1) if events else None,
        "bridge_age": live.get("age"),
        "radar_ok": bool(live.get("scope")),
        "radios": radios,
        "board": board,
        "scope": live.get("scope", []),
        # Three answers, and the bridge decided all three. UNSEEN is the only
        # one that means what "ghost" used to.
        "ghosts": [r["callsign"] for r in board if r.get("confirmed") == "unseen"],
        "unconfirmed": [r["callsign"] for r in board
                        if r.get("confirmed") == "claimed"],
        "flights": live.get("flights", []),
        # EVERY STRIP ON FILE, AND WHO IS FLYING IT. Published since 30 July and
        # dropped here, which is the shape of most of this file's history: the
        # bridge decided something and the page did not carry it.
        "plans": live.get("plans", []),
        # What the controller was handed, block by block. Behaviour
        # follows from this and nothing else.
        "handed": live.get("handed", []),
        "unidentified": live.get("unidentified", []),
        # The MEANING of the values, from the thing that defines them.
        "legend": live.get("legend", {}),
        "last": last,
    }


def _last_turn(events: list, now: float) -> dict:
    """One transmission, from the words to what was said. The recorder owns
    this -- it is a history, not a belief."""
    idx = max((i for i, e in enumerate(events) if e.get("kind") == "pilot"),
              default=-1)
    if idx < 0:
        return {}
    p = events[idx]
    last = {"heard": p.get("transcript") or "", "who": p.get("callsign") or "",
            "authority": p.get("authority") or "", "track": p.get("track") or "",
            "why": p.get("why") or "", "freq": p.get("freq_mhz"),
            "ago": round(now - p.get("t", now), 1), "trail": []}
    for e in events[idx + 1:]:
        if e.get("kind") == "pilot":
            break
        if e.get("kind") in _TRAIL and e.get("kind") != "board":
            last["trail"].append({"kind": e.get("kind"),
                                  "text": (e.get("text") or "")[:400],
                                  "seconds": e.get("seconds"),
                                  "tier": e.get("tier"), "gate": e.get("gate")})
    last["voiced"] = _voiced(last["trail"])
    return last


# Numbers a controller issues: headings, altitudes, ranges.
# The figures a clearance is made of, taken only where an instruction word
# puts them. Anything else in a directive is context.
_INSTRUCTION = __import__("re").compile(
    r"(?:heading|maintain|climb|descend|descend and maintain|at)\s+"
    r"(\d[\d,]*\d|\d)", __import__("re").I)


def _figures(text: str) -> str:
    """Spoken numbers as numerals, so the two sides can be compared at all.

    THE AGENT SPEAKS DIGITS AS WORDS -- "turn left heading one six nine" -- and
    the engine issues them as figures. Comparing the two directly would report a
    paraphrase on every correctly voiced turn, which is worse than no check:
    an alarm that is always on is one nobody reads.

    `callsign._digits` already does this, including the homophones a live
    rehearsal taught it ("niner", "won", "fore", "ate"). Reusing it rather than
    writing a fifth version of the same idea -- which is the whole argument of
    docs/SCHEMA.md, applied to a diagnostics page.
    """
    import re as _re

    from marshall.atc.callsign import _digits
    got = _digits(text or "").replace(",", "")
    # MAGNITUDES, which `_digits` does not do because a callsign has none. An
    # altitude is spoken "four thousand" and issued as 4000, so without this the
    # check would report a paraphrase on every correct altitude -- and the one
    # number most worth watching is the one it would be wrong about.
    #
    # The inverse of `route._spoken_alt`, and deliberately only the two forms a
    # controller actually uses. "Two thousand five hundred" is one altitude, so
    # the hundreds are folded into the thousands when they follow.
    def _mag(m):
        n = int(m.group(1)) * (1000 if m.group(2).lower() == "thousand" else 100)
        rest = m.group(3)
        if rest:
            n += int(rest) * 100
        return f" {n} "
    got = _re.sub(r"\b(\d+)\s*(thousand|hundred)(?:\s+(\d+)\s*hundred)?\b",
                  _mag, got, flags=_re.I)
    return got.replace(" ", "")


def _voiced(trail: list[dict]) -> dict:
    """Did the agent SAY the engine's numbers, or paraphrase them?

    THE TWO-BRAIN SEAM, MADE VISIBLE. The deterministic half owns separation and
    geometry precisely so a model cannot invent them -- but the model is what
    speaks, so the guarantee only holds if it VOICES the engine's instruction
    rather than rewording it. A controller who paraphrases "turn left heading
    one six nine, maintain four thousand" into "come left a bit and stay where
    you are" has quietly taken the decision back, and nothing anywhere reports
    it.

    So: every number the engine produced this turn, and whether it appears in
    what was actually transmitted. Reported, never enforced -- a missing number
    is sometimes correct (the engine repeats itself; the agent is told not to
    repeat a range on final) and this is a diagnostic, not a gate. The page
    shows what was dropped and a human decides whether it mattered.
    """
    said = _figures(" ".join(t.get("text") or "" for t in trail
                                 if t.get("kind", "").startswith("atc/")))
    # ONLY THE NUMBERS THAT ARE INSTRUCTIONS. A directive carries three kinds
    # of figure and they are not equal:
    #
    #   heading / altitude   an INSTRUCTION. Separation depends on it, the
    #                        pilot reads it back, and a controller who drops it
    #                        has changed the clearance.
    #   range                CONTEXT. "vectoring, fifteen miles" tells him how
    #                        it is going; no rule says it must be repeated, and
    #                        on final the agent is expressly told NOT to.
    #
    # Judging all three flagged 23 of 47 turns from a real sortie, almost all
    # for an unspoken range. A check that fires on half the turns is one nobody
    # reads, which is worse than not having it -- so this asks only about the
    # figures a clearance is made of.
    want: list[str] = []
    for t in trail:
        if t.get("kind") in ("controller", "asr"):
            want += _INSTRUCTION.findall(t.get("text") or "")
    if not want:
        return {}
    missing = [n for n in want if n.replace(",", "") not in said]
    # THREE VERDICTS, NOT TWO, and the third is the one that cost a sortie.
    #
    #   voiced       the agent said every figure the engine issued
    #   paraphrased  it spoke, and dropped one -- it sounds like a clearance
    #                and is half of one
    #   SILENT       the engine issued an instruction and NOTHING went out
    #
    # Scoring a real sortie, all seventeen failures were the third: the engine
    # had a heading and an altitude for him and the frequency stayed empty. That
    # is the broken talk-down, visible in the data the whole time and reported
    # nowhere -- the pilot found it by noticing the silence himself.
    verdict = ("voiced" if not missing
               else "paraphrased" if said else "silent")
    return {"wanted": want, "missing": missing, "ok": not missing,
            "spoke": bool(said), "verdict": verdict}


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
  /* SINGLE COLUMN on the kneeboard. A grid assumes a monitor; this is read in
     the air. Wide enough to keep the board's twelve columns legible without
     the page itself scrolling sideways -- the tables scroll, the page does
     not. */
  .stack{display:flex;flex-direction:column;gap:1px;background:var(--rule)}
  .stack > section{width:100%}
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
  /* NUMBERS DO NOT WRAP. `word-break:break-word` is right for a callsign or a
     transcript and wrong for a figure: in a narrow column it broke "2,000" and
     "1 1 5" across lines, so the board printed its digits vertically and was,
     in a pilot's words while flying it, "really hard to read".
     A measurement is one token. Let the column scroll instead -- the table is
     already inside `.scroll`, which is the right place to give way. */
  td.n{white-space:nowrap;word-break:normal;text-align:right;
    font-variant-numeric:tabular-nums}
  tr:last-child td{border-bottom:0}
  .org-engine{background:#12303a;color:#7FB3D5;border-color:#1d4a5a}
  .org-agent{background:#2a2438;color:#b39ddb;border-color:#3d3352}
  .org-guard{background:#3a2a12;color:#E0A040;border-color:#5a4020}
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
  section.wide{border-top:1px solid var(--rule)}
  h2 .hint{text-transform:none;letter-spacing:0;font-weight:400;color:var(--dim)}
  h4{font-size:.66rem;letter-spacing:.14em;text-transform:uppercase;
    color:var(--dim);margin:.9rem 0 .3rem;font-weight:600}
  h4:first-child{margin-top:0}
  .blocks{display:grid;gap:1px;background:var(--rule);font-size:.8rem}
  .blk{background:var(--bg);padding:.4rem .6rem;display:grid;
    grid-template-columns:7.5rem 1fr;gap:.7rem}
  .blk .n{color:var(--dim);font-size:.68rem;letter-spacing:.1em;
    text-transform:uppercase;padding-top:.15rem}
  .blk .v{white-space:pre-wrap;word-break:break-word}
  .blk .v.long{max-height:7rem;overflow:auto}
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
  <span class="stat">contacts <i id="contacts">-</i></span>
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
<!-- ONE COLUMN, ORDERED BY WHAT A PILOT NEEDS IN THE AIR.

       "The diag page is pretty crowded on the kneeboard. We should probably
        just move to 1 column with the most important info on top - that is the
        board and the ATC attribution. The untracked and flight plans are things
        I can scroll down to see on the ground easily. The board and attribution
        is my primary diag instrument now."

     A two-column grid assumes a monitor. This is read on a kneeboard, in the
     air, at a glance -- so the two panels that answer "what does he think is
     happening, and which brain decided it" come first and everything else is a
     scroll away. Nothing is removed; the order is the feature. -->
<div class="stack">
  <section><h2>Tracked
    <span class="hint">&mdash; on the board, and exactly one controller owns each</span></h2>
    <div id="board"></div></section>
  <section><h2>The last turn, stage by stage
    <span class="hint">&mdash; who decided it: engine, agent or guard</span></h2>
    <div id="last"></div></section>
  <section><h2>Untracked
    <span class="hint">&mdash; the sim knows who and where; nobody is working him</span></h2>
    <div id="untracked"></div></section>
  <section><h2>Flights</h2><div id="flights"></div></section>
  <section><h2>Flight plans
    <span class="sub">every strip on file, and who ATC can attach it to</span></h2>
    <div id="plans"></div></section>
  <section><h2>What the controller was handed
    <span class="hint">&mdash; behaviour follows from this and nothing else</span></h2>
    <div id="handed"></div></section>
</div>
<script>
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/[&<>]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
// THE PAGE KNOWS NOTHING. No player names, no phases, no frequencies, no
// notion that `radar` outranks `plan`. Every meaning arrives in `legend`,
// published by the thing that defines the words. All this file knows is how to
// colour ok / warn / bad and how to lay out a table.
let LEGEND = {};
const lvl = (group, key) => (LEGEND[group] || {})[key] || '';

function who(rs) {
  if (!rs.length) return '<p class="empty">no transmissions recorded yet</p>';
  return '<table><tr><th>radio</th><th>heard</th><th>is</th><th>auth</th>'
    + '<th>track</th><th>ago</th></tr>' + rs.map(r => {
      const cls = lvl('authority', r.authority);
      return `<tr><td>${esc(r.radio)}</td>`
        + `<td class="dim">${esc(r.heard) || '&mdash;'}</td>`
        + `<td class="acc">${esc(r.is) || '&mdash;'}</td>`
        + `<td class="${cls}"><span class="pill">${esc(r.authority) || 'none'}</span></td>`
        + `<td class="dim">${esc(r.track) || '&mdash;'}</td>`
        + `<td class="dim">${r.ago}s</td></tr>`
        + (cls !== 'ok' && r.why
            ? `<tr><td></td><td colspan="5" class="dim">${esc(r.why)}</td></tr>` : '');
    }).join('') + '</table>';
}

function board(d) {
  const b = d.board || [];
  if (!b.length) return '<p class="empty">nobody on the board</p>';
  // THE ROW, AS PUBLISHED. Nothing here is looked up, matched or worked out.
  //
  // This table used to open by searching the scope list for the first contact
  // whose squashed name equalled the squashed track, falling back to an empty
  // object -- the page doing the board join itself, with its OWN copy of the name
  // squasher, against a track it had to match by string. That is a fourth
  // implementation of the join that `HANDOFF-board.md` is about, in JavaScript,
  // in the surface whose whole contract is that it decides nothing. When it
  // missed, `|| {}` turned the miss into four blank columns and the page looked
  // like a working page reporting an aeroplane with no position.
  //
  // The bridge already sends heading, altitude, speed and range on the row. It
  // always did. The page was re-deriving what it had been handed.
  //
  // THREE COLUMNS, THREE AUTHORITIES, kept apart on purpose: `state` is what the
  // sim observes, `intent` is what the pilot said, `doing` is where the
  // separation engine has got to. Collapsing them into one word is how an
  // observation comes to overwrite something a man actually told a controller.
  return '<div class="scroll"><table>'
    // WHAT IS HAPPENING, FIRST. The three state columns sit immediately after
    // the callsign because they are the question the page is open to answer,
    // and this table is twelve columns wide inside a horizontal scroller -- on
    // a kneeboard-width display `intent` was in the middle and scrolled out of
    // sight, which reads exactly like a column that was never added.
    //
    // Three authorities, still kept apart: `state` is what the sim observes,
    // `intent` is what the pilot asked for, `doing` is where the separation
    // engine has got to. Position follows, because it is context rather than
    // the answer.
    + '<tr><th>who</th><th>state</th><th>intent</th><th>doing</th>'
    + '<th>owner</th><th>type</th><th>freq</th><th>hdg</th><th>alt</th>'
    + '<th>gs</th><th>range</th><th>known by</th></tr>'
    + b.map(r => {
      const cls = lvl('confirmed', r.confirmed);
      return `<tr class="${cls === 'bad' ? 'ghost' : ''}">`
        + `<td class="${cls}">${esc(r.callsign)}${members(r)}`
        + `${cls !== 'ok' ? ' <span class="pill">' + esc(r.confirmed) + '</span>' : ''}</td>`
        // WHAT HE IS FLYING. The bridge has always sent this on the row and
        // the table simply had no column for it, so the board named a man and
        // never said what he was in -- while the untracked table two panels
        // down showed the type for every contact.
        //
        // Printed exactly as the sim states it. Shortening "P-51D-30-NA" to
        // something friendlier would be the page deciding what an airframe is
        // called, and the type is what the engine reads to decide whether he
        // can be sent to a beacon or needs a racetrack -- so what is displayed
        // must be what was used.
        + `<td class="${lvl('state', r.state)}">${esc(r.state) || '&mdash;'}</td>`
        + `<td class="${lvl('intent', r.intent)}">${esc(r.intent)
             || '<i class="dim">not established</i>'}</td>`
        + `<td>${phase(r)}</td>`
        + `<td class="${lvl('owner', r.owner)}">${esc(r.owner) || '&mdash;'}</td>`
        + `<td class="dim">${esc(r.type)}</td>`
        + `<td class="dim n">${r.freq_mhz ? r.freq_mhz.toFixed(3) : '&mdash;'}</td>`
        + `<td class="dim n">${num(r.heading, 0, '&deg;')}</td>`
        + `<td class="dim n">${num(r.alt_ft, 0, ' ft')}</td>`
        + `<td class="dim n">${num(r.speed_kt, 0, ' kt')}</td>`
        + `<td class="dim n">${num(r.range_nm, 1, ' nm')}</td>`
        + `<td class="${lvl('authority', r.authority)}">${esc(r.authority || 'none')}</td>`
        + '</tr>';
    }).join('') + '</table></div>';
}

// WHO CAME OFF THE BOARD, AND WHAT THE SCOPE HELD AT THE TIME.
//
// The one panel here that exists to make a bug visible rather than to show
// state working. A release destroys its own evidence -- the row is gone, so
// nothing afterwards can be asked why -- and nine wrong ones went unnoticed for
// a whole sortie because the only record was a print statement.
//
// The page applies NO judgement about whether a release was wrong. It cannot:
// deciding that would mean matching the released callsign against those scope
// labels, which is the very operation under suspicion. It prints both and a
// human sees "released Sockeye; the scope held 362nd_Sockeye" instantly.
function releases(d) {
  const rs = d.releases || [];
  if (!rs.length) return '';
  return '<h4>came off the board</h4><table>'
    + '<tr><th>who</th><th>track</th><th>on the scope at the time</th></tr>'
    + rs.map(r => `<tr><td class="warn">${esc(r.callsign)}</td>`
      + `<td class="dim">${esc(r.track) || '&mdash;'}</td>`
      + `<td class="dim">${(r.scope || []).map(esc).join(', ') || 'nothing'}</td>`
      + '</tr>').join('') + '</table>';
}

// "bullseye 185 for 35 (blue)" -- said the way it is said on the radio, bearing
// first. An em dash when the sim has given us no bullseye or the contact has no
// position: absent, never a plausible wrong number.
function bulls(u) {
  const b = u.bulls || {};
  if (b.range_nm === undefined || b.range_nm === null) return '&mdash;';
  const pad = String(Math.round(b.radial)).padStart(3, '0');
  return `${pad}&deg; / ${b.range_nm.toFixed(1)} nm`
    + (b.ref ? ` <span class="dim">${esc(b.ref)}</span>` : '');
}

function untracked(d) {
  // Radar sees it, nobody is working it. Together with the board this is a
  // complete account of what is on the scope -- every contact is in exactly
  // one of the two.
  // Aircraft only. Whether a thing is traffic is the bridge's judgement,
  // published as `is_aircraft` -- the page does not know what a T-55 is.
  const loose = (d.scope || []).filter(u => !u.controlled && u.is_aircraft);
  const lost = d.unidentified || [];
  if (!loose.length && !lost.length)
    return '<p class="empty">every contact is on the board</p>';
  let out = '';
  if (loose.length) {
    // FROM BULLSEYE, not from this controller's threshold. Nobody on this board
    // is working these aircraft, so a range off one field's beacon says nothing
    // -- and bullseye is the point everyone on the map shares, which is what the
    // pilot's own HSI is referenced to. The bridge computes it against the
    // contact's OWN coalition and names which one in `bulls.ref`; this prints
    // what it was handed and knows nothing about coalitions or great circles.
    // BOTH NAMES, SIDE BY SIDE.
    //
    //     "I want untracked to show the dcs callsign and the derived callsign -
    //      so that I can see the translation."
    //
    // The left cell is the string the sim published; the right is the board key
    // it derives to. They are one fact and its derivation, and printing only the
    // answer is how a bad translation stays invisible until a controller uses
    // the wrong name on the radio. The page does no deriving of its own -- the
    // bridge sends `derived`, for the same reason it sends `bulls`.
    //
    // NEITHER CELL FALLS BACK TO THE OTHER. The first version of this printed
    // `u.derived || u.callsign || '-'`, which is the page picking which of three
    // values to believe -- and it would have shown a plausible name in the
    // column whose entire purpose is to reveal that the derivation is broken.
    // An empty cell is the honest answer and the one worth seeing.
    out += '<div class="scroll"><table>'
      + '<tr><th>dcs name</th><th>callsign</th><th>type</th><th>state</th>'
      + '<th>hdg</th><th>alt</th><th>gs</th><th>from bullseye</th><th></th></tr>'
      + loose.map(u => `<tr><td class="dim">${esc(u.name)}</td>`
        + `<td class="${u.level || ''}">${esc(u.derived)}</td>`
        + `<td class="dim">${esc(u.type || '')}</td>`
        + `<td class="${lvl('state', u.state)}">${esc(u.state)}</td>`
        + `<td class="dim n">${num(u.heading, 0, '&deg;')}</td>`
        + `<td class="dim n">${num(u.alt_ft, 0, ' ft')}</td>`
        + `<td class="dim n">${num(u.speed_kt, 0, ' kt')}</td>`
        + `<td class="dim n">${bulls(u)}</td>`
        + `<td>${(u.tags || []).map(t => '<span class="pill">' + esc(t)
             + '</span>').join(' ')}</td></tr>`).join('') + '</table></div>';
  }
  if (lost.length) {
    out += '<h4>heard on the radio, tied to no aeroplane</h4><table>'
      + lost.map(r => `<tr><td class="bad">${esc(r.radio)}</td>`
        + `<td class="dim">said &ldquo;${esc(r.heard) || '?'}&rdquo;</td>`
        + `<td class="dim">${esc(r.why)}</td></tr>`).join('') + '</table>';
  }
  return out;
}

function num(v, dp, suffix) {
  return (v === null || v === undefined) ? '&mdash;'
    : Number(v).toFixed(dp) + suffix;
}

// `key()` LIVED HERE. It squashed a name to letters and digits so the page could
// match a board row's track against a scope contact -- the fourth implementation
// of that squash in this codebase (`identity._key`, `agent_atc._key_name`,
// `diag._key` are the others) and the only one in a language nobody was testing.
// It went with the join it existed for. If a lookup ever seems to be needed here
// again, the field is missing from the snapshot and that is the bug.

function members(r) {
  return (r.members && r.members.length)
    ? ' <span class="dim">+' + r.members.map(esc).join(', +') + '</span>' : '';
}

function phase(r) {
  return esc(r.phase || '')
    + (r.assigned_ft ? ' <span class="dim">' + r.assigned_ft + ' ft</span>' : '')
    + (r.in_letdown ? ' <span class="pill warn">letdown</span>' : '');
}

function last(l) {
  if (!l || !l.heard) return '<p class="empty">nothing heard yet</p>';
  const auth = lvl('authority', l.authority);
  // DID THE AGENT SAY THE ENGINE'S NUMBERS? The deterministic half owns
  // separation so a model cannot invent it -- but the model is what speaks, so
  // the guarantee only holds if it VOICES the instruction instead of rewording
  // it. Reported, never enforced: a dropped number is sometimes correct.
  const v = l.voiced || {};
  const say = {voiced: ['ok', 'the agent said every figure the engine issued'],
               paraphrased: ['bad', 'PARAPHRASED &mdash; it spoke and dropped one'],
               silent: ['bad', 'SILENT &mdash; the engine issued a clearance and '
                               + 'nothing went out']};
  const verdict = !v.wanted ? '' : (() => {
    const [cls, msg] = say[v.verdict] || ['', ''];
    return `<li><span class="k">voiced</span><span class="${cls}">${msg}`
      + (v.missing && v.missing.length
          ? ` &mdash; engine issued ${v.wanted.map(esc).join(', ')}, `
            + `not said: ${v.missing.map(esc).join(', ')}` : '')
      + '</span></li>';
  })();
  let out = '<ul class="trail">'
    + `<li><span class="k">heard</span><span class="heard">${esc(l.heard)}</span></li>`
    + `<li><span class="k">who</span><span>${esc(l.who) || '<i class="dim">unidentified</i>'}`
    + ` <span class="pill ${auth}">${esc(l.authority) || 'none'}</span>`
    + `<span class="dim"> ${esc(l.track)}</span></span></li>` + verdict;
  (l.trail || []).forEach(t => {
    const meta = (LEGEND.kind || {})[t.kind] || {};
    // WHO SAID IT, beside WHEN. `stage` answers when in the turn; `origin`
    // answers which brain -- engine (deterministic), agent (the model), or
    // guard (the loop's own rules, refusing before either brain sees the
    // call). The page does not know which is which; the bridge publishes it.
    const org = (LEGEND.origin || {})[t.kind] || '';
    out += `<li><span class="k">${esc(meta.stage || t.kind)}</span>`
      + (org ? `<span class="pill org-${esc(org)}">${esc(org)}</span>` : '')
      + `<span class="${meta.level || ''}">${esc(t.gate || t.text)}`
      + (t.seconds ? `<span class="dim"> ${t.seconds}s ${esc(t.tier || '')}</span>` : '')
      + '</span></li>';
  });
  return out + `</ul><p class="empty">${l.ago}s ago on ${l.freq || '?'}</p>`;
}

function handed(blocks) {
  if (!blocks || !blocks.length)
    return '<p class="empty">nothing sent yet this session</p>';
  // The block's own first word is its name -- the bridge wrote it, the page
  // does not know what the names mean or which ones matter.
  return '<div class="blocks">' + blocks.map(b => {
    const cut = b.indexOf(':');
    const name = cut > 0 && cut < 40 ? b.slice(0, cut) : '';
    const body = cut > 0 && cut < 40 ? b.slice(cut + 1).trim() : b;
    return `<div class="blk"><span class="n">${esc(name.split('(')[0].trim())}</span>`
      + `<span class="v${body.length > 400 ? ' long' : ''}">${esc(body)}</span></div>`;
  }).join('') + '</div>';
}

// Every strip the director holds, and whether anything is flying under it.
// The page decides nothing here: `flying`, `is_flight` and `on_ground` are all
// joined upstream, because working out that a plan filed as "Pony 1-1" belongs
// to the man the board calls "sockeye" needs the identity registry, and a web
// page has no business holding one.
function plans(d) {
  const p = d.plans || [];
  if (!p.length) return '<p class="empty">no flight plans on file</p>';
  return '<table><tr><th>plan</th><th>filed as</th><th>approach</th>'
    + '<th>active</th><th>flying it</th><th>where</th></tr>'
    + p.map(x => {
      const who = x.attributed_to
        ? `<span class="acc">${esc(x.attributed_to)}</span>`
          + (x.is_flight ? ' <span class="dim">(flight)</span>' : '')
        : '<span class="dim">nobody</span>';
      // Three states, not two: airborne, on the ground, or radar cannot see him
      // at all -- and "we do not know" must not render as "parked".
      const where = x.on_ground === null || x.on_ground === undefined
        ? '<span class="dim">&mdash;</span>'
        : (x.on_ground ? 'on the ground' : 'airborne');
      return `<tr><td>${esc(x.name || '')}</td>`
        + `<td class="dim">${esc(x.callsign || '&mdash;')}</td>`
        + `<td class="dim">${esc(x.approach || '&mdash;')}</td>`
        + `<td>${x.active ? '<span class="ok">active</span>' : '<span class="dim">no</span>'}</td>`
        + `<td>${who}</td><td class="dim">${where}</td></tr>`;
    }).join('') + '</table>';
}

function flights(d) {
  const f = d.flights || [];
  return f.length
    ? '<table><tr><th>flight</th><th>lead</th><th>members</th></tr>'
      + f.map(x => `<tr><td class="acc">${esc(x.name)}</td><td>${esc(x.lead)}</td>`
        + `<td class="dim">${x.members.length ? esc(x.members.join(', ')) : '&mdash;'}`
        + `</td></tr>`).join('') + '</table>'
    : '<p class="empty">no flights formed</p>';
}

async function tick() {
  try {
    const d = await (await fetch('/diag.json', {cache: 'no-store'})).json();
    LEGEND = d.legend || {};
    $('sess').textContent = d.session || 'none';
    $('age').textContent = d.recorder_age == null ? 'no file' : d.recorder_age + 's';
    $('age').className = (d.recorder_age != null && d.recorder_age > 120) ? 'warn' : '';
    $('contacts').textContent = (d.scope || []).length;
    $('contacts').className = (d.scope || []).length ? 'ok' : 'warn';
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
    $('untracked').innerHTML = untracked(d);
    $('board').innerHTML = board(d) + releases(d);
    $('last').innerHTML = last(d.last);
    $('flights').innerHTML = flights(d);
    $('plans').innerHTML = plans(d);
    $('handed').innerHTML = handed(d.handed);
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
