"""Live diagnostics: what the two brains believe, right now, on a kneeboard.

    "I feel like the diag page might need revamping. I feel like it might have
     been lying a little to console me. I want to make sure that it represents
     what atc is seeing and thinking so that I can rationalize why something is
     happening"

CONSOLING IS THE FAULT THIS FILE IS ABOUT. Every panel here used to print a
plausible value with no account of where it came from, how old it was, or
whether anything had actually decided it -- and four of them printed a value
nothing had decided at all:

    active            a column deleted from `flight_plans` by migration 031.
                      `x.active` was undefined on every row, so the page
                      rendered "no" for every plan, for ever. An answer.
    filed as          `esc('&mdash;')` -- the em dash was escaped into the
                      LITERAL TEXT "&mdash;", which is what a reader saw.
    came off the board  `releases` is published by the bridge and `state()`
                      never forwarded it, so the one panel that exists to make
                      a wrong release visible could not draw a row.
    recorder 8106.7s  the only clock on the page. It measures the RECORDER, and
                      it was labelled and banner-ed as though it measured the
                      bridge: "this is the LAST sortie, not live state. Is the
                      bridge running?" -- printed while the bridge was running
                      and had published its snapshot one second earlier.

FOUR QUESTIONS, and the shape of the page is now just those four:

  WHAT DOES ATC THINK IS TRUE   one card per aeroplane, every belief the bridge
                                published about him, blanks left blank.
  WHERE DID IT COME FROM        the provenance the bridge already publishes --
                                `authority` (how the callsign was resolved) and
                                `confirmed` (whether radar can still see him) --
                                and, per panel, WHICH SOURCE it was read from.
  HOW OLD IS IT                 two clocks, never one: the bridge's snapshot and
                                the flight recorder age independently, and only
                                the first says whether the board is live.
  WHAT DID IT DECIDE NOT TO DO  `handoff/none` carries a sentence -- "Georgia
                                Center keeps him -- departure, 35 nm, inbound"
                                -- and it appeared nowhere. `watching_him` was
                                written to record deciding NOTHING (read its
                                docstring); the page then dropped it. That was
                                the largest single gap and it is now the second
                                panel down, because "why is nothing happening"
                                is the question this page is opened to answer.

NOTHING NEW IS INSTRUMENTED, and that is still the point. The bridge publishes
what it believes (`agent_atc.publish_state` -> `build/control/state.json`) and
appends a JSON line per transmission to `build/logs/flight-<session>.jsonl`.
This reads those two and renders. It cannot perturb the thing it is measuring:
a diagnostic that can break a sortie is one nobody dares run during one.

THE PAGE NEVER JUDGES AND NEVER COMPUTES. It renders what was recorded. Where a
fact is missing the answer is to record it at the source, and #155 lists the
five this page still cannot show honestly because nothing publishes them: which
values were RESTORED from a database row rather than heard on the radio, whether
a clearance was AGREED, which plan a pilot was CLEARED on, the anomalies the
engine repaired, and the capability of the controller working him. Every one is
known inside the bridge and stops at `publish_state`.

PORTRAIT FIRST. It is read on a knee, in the air, by somebody with two seconds.
The thirteen-column board lived in a horizontal scroller and this file's own
comments admitted what that costs -- `intent` "scrolled out of sight, which
reads exactly like a column that was never added" -- and the `.scroll` class it
relied on was never defined in the stylesheet, so it did not scroll either. One
aeroplane is one card now, and nothing on this page scrolls sideways.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from marshall import config
from marshall.core import names as _names


def _logs():
    """Where the flight recorder writes. RESOLVED PER CALL, for exactly the
    reason `published` is -- a module constant computed from `config.BUILD_DIR`
    survives a test that redirects the build dir, so the test reads the LIVE
    recorder and passes only for as long as nothing is flying. That fault was
    found and fixed in the snapshot half of this file and left standing in this
    one, which is the shape of most of the bugs it exists to display."""
    return config.BUILD_DIR / "logs"


# Same variable the PLANS page already reads, for the same reason: inside the
# container `localhost` is the container, and the director is published on the
# host. See kneeboard/plans.py and the extra_hosts note in the compose file.
DIRECTOR = os.environ.get("MARSHALL_DIRECTOR_URL", "http://localhost:8000")
RADAR_URL = f"{DIRECTOR}/radar"

# How much of the recorder to read. A sortie is a few hundred lines; this is
# generous and still one cheap read.
TAIL_BYTES = 512_000


def newest_session() -> str:
    files = sorted(_logs().glob("flight-*.jsonl"), key=lambda p: p.stat().st_mtime)
    return files[-1].stem[len("flight-"):] if files else ""


def _events(session: str) -> list[dict]:
    path = _logs() / f"flight-{session}.jsonl"
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


def published() -> dict:
    """What the BRIDGE says it believes. The page renders this; it derives
    nothing from it.

    THE DASHBOARD USED TO WORK ALL THIS OUT ITSELF -- replaying the roster from
    recorder events, deciding ghost status by matching a spoken label against a
    printed radar name, and re-parsing the scope prose a third time. All three
    were a surface acting as an authority it is not, and the ghost check was
    wrong in precisely the way audit finding 1.1 was wrong.

    The bridge knows, because it is the thing that decided. See
    `agent_atc.publish_state`.

    THE AGE IS PART OF THE ANSWER. The bridge publishes on every transmission
    and on its own tick, so on a quiet frequency this is seconds old and on a
    stopped bridge it is hours old -- and the two look identical unless the
    number travels with the values. It is reported, never hidden and never
    silently believed.
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

# THE RECORDS OF DOING NOTHING, which is the half nothing displayed.
#
# A transmission leaves a trail of what was said. These are the other kind of
# record -- a decision the system declined to take, took back, or refused --
# and every one of them carries the reason in its own text:
#
#   handoff/none    "Batumi Approach keeps him -- approach, 20 nm, inbound"
#   not_voiced      the engine issued a figure and the agent did not say it
#   repaired        ...and the guard put it back afterwards
#   released        he came off the board, and nothing afterwards can be asked
#   dropped         the receive loop refused the call before either brain
#   ship-to-ship    heard, and not addressed to us
#   atc/challenge   answered with a question instead of a clearance
#   atc/misnamed    he used a callsign that is not his
#   flight/refused  a formation that was asked for and not formed
#
# A LIST, HERE, RATHER THAN A RULE. Like `_TRAIL` above it names recorder kinds
# and nothing else -- no meaning is attached to them in this file and none is
# attached in the page. If the bridge grows another kind of "no", it belongs in
# this tuple and needs no other change.
_QUIET = ("handoff/none", "not_voiced", "repaired", "released", "dropped",
          "ship-to-ship", "atc/challenge", "atc/misnamed", "flight/refused")

# How many of those to keep. A knee is not a log viewer: thirty of these filled
# the page and pushed the last turn below the fold, which is the crowding the
# one-column layout was asked for in the first place. Each aeroplane also
# carries his own on his card, so this panel is the catch-all -- including for
# a record whose callsign matches nothing on the board.
QUIET_KEPT = 12
# ...and per aeroplane, on his own card. The newest is the current answer --
# `watching_him` only records when the answer CHANGES, so the top line of this
# is what it decided most recently and is still deciding.
QUIET_PER_AIRCRAFT = 3


def _reasons(events: list[dict], now: float) -> tuple[list[dict], dict]:
    """Everything the system recorded about NOT acting, newest first.

    Returns the flat list and the same records grouped by the callsign the
    RECORDER wrote on them.

    THE GROUPING IS AN EXACT-STRING LOOKUP AND IT IS ALLOWED TO MISS. Both
    sides of it are written by the bridge from the same board key -- `record(...
    callsign=cs)` and `ctl.board()`'s `callsign` are the same variable -- so
    there is nothing to fold, normalise or squash here, and no fourth copy of
    the name squasher is going anywhere near it. That is the bug in
    `HANDOFF-board.md` and this file has already had it once.

    THE FLAT LIST IS THE SAFETY NET. Every record appears in it whether or not
    its callsign matches anything on the board, so a card showing no reasons is
    never the only account of a decision: the panel below it still has the line,
    with the name the recorder actually wrote. A miss is visible rather than
    silently swallowed, which is the difference between a lookup that fails
    honestly and `|| {}`.
    """
    flat: list[dict] = []
    for e in events:
        if e.get("kind") not in _QUIET:
            continue
        flat.append({"kind": e.get("kind") or "",
                     "callsign": e.get("callsign") or "",
                     # `gate` is what the refusing kinds carry instead of prose.
                     "text": (e.get("text") or e.get("gate") or "")[:300],
                     "ago": round(now - e.get("t", now), 1)})
    flat.reverse()                            # newest first
    by: dict[str, list[dict]] = {}
    for r in flat:
        if not r["callsign"]:
            continue
        got = by.setdefault(r["callsign"], [])
        if len(got) < QUIET_PER_AIRCRAFT:
            got.append(r)
    return flat[:QUIET_KEPT], by


def state(session: str = "", scope: str | None = None) -> dict:
    """Everything the page draws. Read, not derived.

    TWO SOURCES AND THEY AGE SEPARATELY, which is the whole of the "how old is
    it" question and was the whole of the lie:

        the bridge's snapshot   what the system BELIEVES, now. If this is old,
                                everything on the board is that old.
        the flight recorder     what was SAID, and what was decided about it. A
                                history. If this is old, the radio has been
                                quiet -- which is not the same fault at all.

    The page had one clock, measuring the second, labelled as though it measured
    the first. So a running bridge with a quiet frequency was reported as a dead
    bridge, and -- the direction that consoles -- a dead bridge's last board was
    reported as the current one for as long as somebody was still talking.
    """
    session = session or newest_session()
    events = _events(session) if session else []
    now = time.time()
    live = published()

    last = _last_turn(events, now)
    quiet, quiet_by = _reasons(events, now)
    recorder_age = (round(now - max((e.get("t", 0) for e in events), default=now), 1)
                    if events else None)
    board = live.get("board", [])
    return {
        "session": session,
        "at": now,
        # WHERE EVERY PANEL BELOW CAME FROM, and how old that source is. Named
        # by the thing that read them -- this module -- because this module is
        # the only thing that knows which file each answer arrived in.
        "sources": {
            "bridge": {"name": "bridge", "age": live.get("age"),
                       "at": live.get("at")},
            "recorder": {"name": "recorder", "age": recorder_age,
                         "at": (max((e.get("t", 0) for e in events), default=None)
                                if events else None)},
        },
        "recorder_age": recorder_age,
        "bridge_age": live.get("age"),
        "radar_ok": bool(live.get("scope")),
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
        # WHO CAME OFF THE BOARD. Published by the bridge since the day the
        # panel was written and never forwarded by this function, so the panel
        # could not draw a row -- see the header. A release destroys its own
        # evidence; this is the only record that it happened.
        "releases": live.get("releases", []),
        # What the controller was handed, block by block. Behaviour
        # follows from this and nothing else.
        "handed": live.get("handed", []),
        "unidentified": live.get("unidentified", []),
        # WHAT WAS DECIDED AGAINST. See `_reasons`.
        "quiet": quiet,
        "quiet_by": quiet_by,
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
#
# ONE COLUMN, PORTRAIT, NO SIDEWAYS SCROLL ANYWHERE. Everything wide enough to
# need a scroller has been turned into a card, because a fact that is off the
# right-hand edge of a kneeboard reads exactly like a fact nobody published.
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
    font-size:15px;line-height:1.45;-webkit-font-smoothing:antialiased;
    overflow-x:hidden}
  header{display:flex;gap:.9rem;align-items:baseline;flex-wrap:wrap;
    padding:.5rem 1rem;border-bottom:1px solid var(--rule);background:var(--panel)}
  header b{letter-spacing:.14em;font-size:.8rem;color:var(--dim);font-weight:600}
  header .stat{font-size:.75rem;color:var(--dim)}
  header .stat i{font-style:normal;color:var(--ink)}
  section{background:var(--bg);padding:.6rem 1rem .9rem;min-width:0;
    border-top:1px solid var(--rule)}
  h2{font-size:.7rem;letter-spacing:.16em;text-transform:uppercase;color:var(--dim);
    margin:0 0 .5rem;font-weight:600;display:flex;gap:.6rem;align-items:baseline;
    flex-wrap:wrap}
  /* WHICH SOURCE THIS PANEL WAS READ FROM, and how old it is. Every panel
     carries one; a panel with no stamp would be the old page again. */
  h2 .src{margin-left:auto;font-size:.62rem;letter-spacing:.08em;
    text-transform:none;color:var(--dim);font-weight:400}
  h2 .src.warn{color:var(--warn)} h2 .src.bad{color:var(--bad)}
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
     A measurement is one token. */
  td.n{white-space:nowrap;word-break:normal;text-align:right;
    font-variant-numeric:tabular-nums}
  tr:last-child td{border-bottom:0}
  .org-engine{background:#12303a;color:#7FB3D5;border-color:#1d4a5a}
  .org-agent{background:#2a2438;color:#b39ddb;border-color:#3d3352}
  .org-guard{background:#3a2a12;color:#E0A040;border-color:#5a4020}
  .ok{color:var(--ok)} .warn{color:var(--warn)} .bad{color:var(--bad)}
  .dim{color:var(--dim)} .acc{color:var(--accent)}
  .pill{display:inline-block;padding:0 .4em;border:1px solid currentColor;
    border-radius:2px;font-size:.7rem;letter-spacing:.05em;white-space:nowrap}
  /* --- one aeroplane, one card ------------------------------------------
     A definition list, not a row: on a kneeboard the label has to sit beside
     its value where a reader can find it, and thirteen headings across the top
     of a scroller put the value four inches from anything that named it. */
  .ac{border:1px solid var(--rule);border-radius:3px;margin:0 0 .55rem;
    background:var(--panel);overflow:hidden}
  .ac:last-child{margin-bottom:0}
  .ac.ghost{border-color:#5a2b24}
  .ac .hd{display:flex;gap:.5rem;align-items:baseline;flex-wrap:wrap;
    padding:.35rem .6rem;border-bottom:1px solid var(--rule)}
  .ac .cs{font-size:.95rem;letter-spacing:.05em}
  .ac .hd .rt{margin-left:auto;font-size:.72rem;color:var(--dim)}
  .kv{display:grid;grid-template-columns:6.4rem minmax(0,1fr);
    gap:.1rem .7rem;padding:.35rem .6rem .45rem;font-size:.83rem;
    background:var(--bg)}
  .kv .k{color:var(--dim);font-size:.66rem;letter-spacing:.09em;
    text-transform:uppercase;padding-top:.2rem}
  .kv .v{min-width:0;word-break:break-word}
  .kv .v .sep{color:var(--rule);padding:0 .35rem}
  .kv .v.num{font-variant-numeric:tabular-nums}
  .why{color:var(--warn)}
  .trail{margin:0;padding:0;list-style:none;font-size:.83rem}
  /* Column one is the stage label; column two is EVERYTHING else. Stated as a
     rule rather than left to child order, because grid's answer to an extra
     child is a new implicit column sized to min-content -- which is how one
     added pill turned the last turn into a column of single words. minmax(0,)
     so a long unbroken transcript wraps instead of widening the row. */
  .trail li{padding:.2rem 0;border-bottom:1px solid #14191D;display:grid;
    grid-template-columns:5.5rem minmax(0,1fr);gap:.7rem}
  .trail li>*:not(.k){grid-column:2}
  .trail li:last-child{border-bottom:0}
  .trail .k{color:var(--dim);font-size:.7rem;letter-spacing:.09em;
    text-transform:uppercase;padding-top:.15rem}
  .heard{color:var(--accent)}
  h4{font-size:.66rem;letter-spacing:.14em;text-transform:uppercase;
    color:var(--dim);margin:.9rem 0 .3rem;font-weight:600}
  h4:first-child{margin-top:0}
  .blocks{display:grid;gap:1px;background:var(--rule);font-size:.8rem}
  .blk{background:var(--bg);padding:.4rem .6rem;display:grid;
    grid-template-columns:7.5rem minmax(0,1fr);gap:.7rem}
  .blk .n{color:var(--dim);font-size:.68rem;letter-spacing:.1em;
    text-transform:uppercase;padding-top:.15rem}
  .blk .v{white-space:pre-wrap;word-break:break-word}
  .blk .v.long{max-height:7rem;overflow:auto}
  /* THE QUIET LOG: one line per decision not taken, with its age on the right
     where the eye can run down them. */
  .q{display:grid;grid-template-columns:minmax(0,1fr) 3.4rem;gap:.5rem;
    padding:.22rem 0;border-bottom:1px solid #14191D;font-size:.82rem}
  .q:last-child{border-bottom:0}
  .q .t{text-align:right;color:var(--dim);font-size:.72rem;
    font-variant-numeric:tabular-nums;white-space:nowrap}
  .q .who{color:var(--accent)}
  #stale{background:var(--warn);color:#0A0C0E;padding:.4rem 1rem;
    font-size:.78rem;letter-spacing:.02em}
  #stale div+div{margin-top:.2rem}
  #control{display:flex;align-items:center;gap:.55rem;flex-wrap:wrap;
    padding:.4rem 1rem;border-bottom:1px solid var(--rule);background:var(--panel)}
  #control .lbl{font-size:.66rem;letter-spacing:.16em;color:var(--dim)}
  #control .sep{width:1px;height:1.1rem;background:var(--rule);margin:0 .35rem}
  #control button{font-family:var(--mono);font-size:.72rem;letter-spacing:.06em;
    background:transparent;color:var(--ink);border:1px solid var(--rule);
    border-radius:2px;padding:.2rem .6rem;cursor:pointer}
  #control button:hover:not(:disabled){border-color:var(--accent);color:var(--accent)}
  #control button:disabled{opacity:.35;cursor:not-allowed}
  #control button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
  #cmsg{font-size:.72rem;color:var(--dim)}
  .empty{color:var(--dim);font-size:.8rem;padding:.3rem 0}
  /* A DESK GETS THE BONUS, not the design. The cards are laid out for a knee;
     a wide monitor simply fits two of them side by side. */
  @media (min-width:1200px){
    #board,#untracked{display:grid;grid-template-columns:1fr 1fr;
      gap:0 .55rem;align-items:start}
    #board>*,#untracked>*{min-width:0}
  }
</style></head><body>
<div id="stale" style="display:none"></div>
<header>
  <b>MARSHALL DIAG</b>
  <!-- TWO CLOCKS. The bridge's snapshot is the age of every belief below it;
       the recorder is the age of the last thing anybody said. One number
       standing for both is how a running bridge got reported as a dead one and
       a dead one's board got reported as live. -->
  <span class="stat">atc <i id="bage">-</i></span>
  <span class="stat">recorder <i id="age">-</i></span>
  <span class="stat">session <i id="sess">-</i></span>
  <span class="stat">contacts <i id="contacts">-</i></span>
  <span class="stat" id="verdict"></span>
</header>
<div id="control">
  <!-- MARSHALL-ATC, NOT "BRIDGE". "Bridge" is a DIRECTORY name and is
       deprecated as vocabulary (CLAUDE.md, docs/STRUCTURE.md) -- a folder name
       carries no layer, so a reader cannot tell what a control acts on. This
       one starts and stops the host process, which is `marshall-atc`: a real
       command on the PATH since #147, and the name a pilot should say. -->
  <span class="lbl">MARSHALL-ATC</span>
  <span id="bstate" class="pill">-</span>
  <button data-do="start">start</button>
  <button data-do="restart">restart</button>
  <button data-do="stop">stop</button>
  <span class="sep"></span>
  <span class="lbl">MISSION</span>
  <button data-do="mission">reload current</button>
  <span id="cmsg"></span>
</div>
<!-- ORDERED BY WHAT A PILOT NEEDS IN THE AIR.

       "The diag page is pretty crowded on the kneeboard. We should probably
        just move to 1 column with the most important info on top - that is the
        board and the ATC attribution. The untracked and flight plans are things
        I can scroll down to see on the ground easily."

     ...and then, the whole point of this revision:

       "I want to make sure that it represents what atc is seeing and thinking
        so that I can rationalize why something is happening"

     So: who he thinks is flying, then what he decided NOT to do about them --
     which is the answer when nothing is happening, and it is above the last
     turn because a pilot asking that question has by definition not just had
     one. -->
<section><h2>Who ATC is working<span class="src" id="s-board"></span></h2>
  <div id="board"></div></section>
<section><h2>Decided against<span class="src" id="s-quiet"></span></h2>
  <div id="quiet"></div></section>
<section><h2>The last turn, stage by stage<span class="src" id="s-last"></span></h2>
  <div id="last"></div></section>
<section><h2>Untracked<span class="src" id="s-untracked"></span></h2>
  <div id="untracked"></div></section>
<section><h2>Flights<span class="src" id="s-flights"></span></h2>
  <div id="flights"></div></section>
<section><h2>Flight plans on file<span class="src" id="s-plans"></span></h2>
  <div id="plans"></div></section>
<section><h2>What the controller was handed<span class="src" id="s-handed"></span></h2>
  <div id="handed"></div></section>
<script>
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/[&<>]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
// AN EM DASH IS A CHARACTER, NOT AN ENTITY. Passing the entity through the
// escaper rendered its literal text -- ampersand, m, d, a, s, h -- in three
// columns of the plans table for the whole life of that panel, the escaper
// doing exactly its job to a string that should never have been near it.
const DASH = '\\u2014';
// The arrow a strip uses between a route and where it ends.
const TO = '\\u2192';
// The separator between a reference point and the reason it is the reference.
const DOT = '\\u00b7';
// BLANK READS AS BLANK. A missing value is dimmed and dashed, never zeroed and
// never guessed at: an altitude nobody published shown as `0` is this page's
// whole failure in miniature.
const val = v => (v === null || v === undefined || v === '')
  ? `<span class="dim">${DASH}</span>` : esc(v);
// A number, with its units, or nothing at all.
const num = (v, dp, suffix) => (v === null || v === undefined)
  ? `<span class="dim">${DASH}</span>`
  : Number(v).toFixed(dp).replace(/\\B(?=(\\d{3})+(?!\\d))/, ',') + suffix;
// HOW OLD, IN WORDS A GLANCE CAN TAKE. "8106.7s" is a number a reader has to do
// arithmetic on, in an aeroplane, to find out that it means two hours.
const ago = s => {
  if (s === null || s === undefined) return DASH;
  if (s < 90) return Math.round(s) + 's';
  if (s < 5400) return Math.round(s / 60) + ' min';
  return (s / 3600).toFixed(1) + ' h';
};
// Colour for an age. THE ONLY THRESHOLDS IN THIS FILE, and they decide a
// colour and nothing else -- no value is hidden, rewritten or disbelieved
// because of them.
const OLD_WARN = 120, OLD_BAD = 900;
const aged = s => s === null || s === undefined ? 'bad'
  : s > OLD_BAD ? 'bad' : s > OLD_WARN ? 'warn' : '';
const sep = '<span class="sep">|</span>';
// THE PAGE KNOWS NOTHING. No player names, no phases, no frequencies, no
// notion that `radar` outranks `plan`. Every meaning arrives in `legend`,
// published by the thing that defines the words. All this file knows is how to
// colour ok / warn / bad and how to lay out a card.
let LEGEND = {};
const lvl = (group, key) => (LEGEND[group] || {})[key] || '';

// Join the parts that have a value; drop the ones that do not, rather than
// printing a row of dashes with separators between them.
function line(parts) {
  const got = parts.filter(p => p);
  return got.length ? got.join(sep) : `<span class="dim">${DASH}</span>`;
}

function kv(k, v, cls) {
  return `<span class="k">${esc(k)}</span>`
    + `<span class="v ${cls || ''}">${v}</span>`;
}

// A COLUMN THAT SAYS WHICH QUESTION IT ANSWERS.
//
//     separation   UNKNOWN
//     ladder       enroute        <- one aeroplane, one instant, both correct
//
//     "in this case, wasnt the aircraft ENROUTE and with GA Center? Why would
//      separation say UNKNOWN?"
//
// He was right to ask, and nothing on the page could answer him. Two columns
// printed one word between them and neither said what it measured -- that the
// first is his place in the ARRIVAL QUEUE, which only checking in with the
// arrival controller enters, and the second is the rung of the whole sortie
// that decides who has him next. The distinction is real and must not be
// collapsed; what was missing is that the page never stated it.
//
// AND `UNKNOWN` IS NOT IGNORANCE. It is a real answer -- nothing has ever put
// this man in the queue -- printed in the same word this page uses for a fact
// it never received, on the one screen whose whole job is telling those two
// apart.
//
// SO THE LABEL, THE GLOSS AND THE READING ALL ARRIVE IN THE LEGEND, published
// by the thing that defines the words. The page is not allowed to know that a
// queue has such a state, any more than it is allowed to know that `radar`
// outranks `plan` -- same rule, same reason, same mechanism. Falls back to the
// payload's own key, so a snapshot carrying no legend degrades to something
// true rather than to a blank label. [#171]
const col = k => (LEGEND.column || {})[k] || {};
const kvq = (k, v, cls) => kv(col(k).label || k,
  v + (col(k).gloss
        ? ` <span class="dim">${DOT} ${esc(col(k).gloss)}</span>` : ''), cls);
// The reading the bridge gives a value, when it gives one. Everything else
// prints exactly as it arrived, and a MISSING value still renders blank --
// this may explain a fact, never supply one.
const qval = (k, v) => {
  const said = (col(k).values || {})[v];
  return said ? esc(said) : val(v);
};

// " from BATUMI - the loaded approach". The reference a range was measured
// from, and why that point and not another.
//
// A BLANK DATUM RENDERS BLANK. Not "from the field", not the aerodrome this
// page happens to know about: a guessed reference is a real distance to a real
// airport and reads exactly like a right answer, which is the entire reason
// #160 survived from the first sortie. The page never supplies one -- if the
// bridge could not name its origin, the number stands alone and says so by
// saying nothing. Same rule as `bulls` and as every other cell here.
function datum(d) {
  if (!d || !d.name) return '';
  return ` <span class="dim">from</span> ${esc(d.name)}`
    + (d.why ? ` <span class="dim">${DOT} ${esc(d.why)}</span>` : '');
}

// ONE AEROPLANE, EVERYTHING THE BRIDGE PUBLISHED ABOUT HIM.
//
// Nothing here is looked up, matched or worked out. This table used to open by
// searching the scope list for the first contact whose squashed name equalled
// the squashed track, falling back to an empty object -- the page doing the
// board join itself, with its OWN copy of the name squasher. When it missed,
// `|| {}` turned the miss into four blank columns and the page looked like a
// working page reporting an aeroplane with no position.
//
// The three state fields stay APART on purpose, one row each: `state` is what
// the sim observes, `intent` is what the pilot asked for, `phase`/`doing` is
// where the separation engine has got to, and `sortie` is the rung of the
// ladder that decides who has him next. Collapsing them into one word is how an
// observation comes to overwrite something a man actually told a controller --
// and `sortie` was published by the engine and shown nowhere, while being the
// single input `handoff.py` reads.
function card(r, reasons) {
  const cls = lvl('confirmed', r.confirmed);
  const rs = reasons || [];
  return `<div class="ac ${cls === 'bad' ? 'ghost' : ''}">`
    + '<div class="hd">'
    + `<span class="cs ${cls}">${esc(r.callsign)}</span>`
    + ((r.members && r.members.length)
        ? `<span class="dim">+${r.members.map(esc).join(', +')}</span>` : '')
    // TWO PILLS, TWO QUESTIONS, and they print the same word often enough that
    // the first version showed a man two identical badges: `authority` is HOW
    // HE CAME TO BE THIS CALLSIGN and `confirmed` is WHETHER ANYTHING CAN SEE
    // HIM NOW. The words are the bridge's; only the "id" is added, and only so
    // that two pills reading the same value cannot be read as one fact twice.
    + `<span class="pill ${lvl('authority', r.authority)}">`
    + `id ${esc(r.authority || 'none')}</span>`
    + `<span class="pill ${cls}">${esc(r.confirmed || '')}</span>`
    + (r.in_letdown ? '<span class="pill warn">letdown</span>' : '')
    + (r.on_visual ? '<span class="pill">visual</span>' : '')
    + `<span class="rt">${val(r.type)}</span>`
    + '</div><div class="kv">'
    // WHO IS WORKING HIM, and on what. Unowned while on the board is the
    // contradiction the legend colours: he is being separated by nobody.
    + kv('worked by', line([
        `<span class="${lvl('owner', r.owner)}">${val(r.owner)}</span>`,
        r.freq_mhz ? `<span class="dim">${r.freq_mhz.toFixed(3)}</span>` : '']))
    + kv('he asked for', `<span class="${lvl('intent', r.intent)}">`
        + `${val(r.intent)}</span>`)
    // WHICH APPROACH HIS CLEARANCE NAMES, beside what he ASKED for -- the pair
    // that matters, and the reason this is its own row rather than a note on
    // `intent`:
    //
    //     "for the cleared_approach - shouldnt that be on the board i am
    //      looking at? Isnt it in the database?"
    //
    // The interesting reading is the DISAGREEMENT: he asked for the ILS and is
    // cleared for the surveillance approach, or he is cleared for nothing at
    // all while being vectored. Neither is visible if only one is printed.
    // THE PLAN HE IS CLEARED ON, and the route it names. Off `flights`, which
    // is where the clearance is written.
    //
    //     "I wonder if Kobuleti Clearance actually put me on the clearance
    //      because the board says cleared for Dash, but I'm guessing he just
    //      remembers that from the conversation history, not actually putting
    //      it in the database"
    //
    // The guess was reasonable and wrong: `assigned_plans` held it. The board
    // showed nothing, so a real clearance and an imaginary one looked the
    // same, and he taxied back to Clearance to find out which he had. [#191]
    + kv('flight plan', line([
        `<span class="${r.flight_plan ? '' : 'dim'}">${val(r.flight_plan)}</span>`,
        r.clearance_ack ? '<span class="pill">read back</span>'
                        : (r.flight_plan ? '<span class="pill warn">NOT read back</span>' : '')]))
    + (r.route ? kv('route', `<span class="dim">`
        + esc(String(r.route).split(/[,>]/).map(x => x.trim())
              .filter(Boolean).join(' > ')) + '</span>') : '')
    // ...AND THE APPROACH, WHICH IS A DIFFERENT QUESTION AND SAID SO NOWHERE.
    //
    // This label read "cleared for", which a pilot reads as "cleared for
    // WHAT" -- the whole clearance. It means the approach and nothing else,
    // so an aeroplane properly cleared to Batumi and not yet given an
    // approach showed a blank field that was entirely correct and read as a
    // missing clearance. Naming the question is the fix; the value never
    // changed. [#191]
    + kv('cleared approach', val(r.cleared_approach))
    // THE TWO PHASE COLUMNS, EACH NAMING ITS OWN QUESTION. See `kvq`: the
    // labels used to read `separation` and `ladder`, which are two words for
    // what a reader had no reason not to take as one fact. [#171]
    + kvq('phase', line([qval('phase', r.phase),
        r.assigned_ft ? num(r.assigned_ft, 0, ' ft assigned') : '',
        r.approaches ? 'approaches ' + esc(r.approaches) : '']), 'num')
    + kvq('sortie_phase', qval('sortie_phase', r.sortie_phase))
    // WHETHER THE ENGINE HAS BEEN TOLD RADAR SEES HIM, which is not the same
    // question as the `confirmed` pill above and can disagree with it. This one
    // decides whether he may take a place in the stack at all
    // (`may_be_sequenced`), so a man the scope holds and the engine believes
    // unidentified is a real state and one nothing displayed.
    + kv('radar id', r.identified === undefined ? val(null)
        : (r.identified ? 'yes' : '<span class="warn">no</span>'))
    + kv('sim says', `<span class="${lvl('state', r.state)}">`
        + `${val(r.state)}</span>`)
    // A RANGE MUST NAME WHAT IT IS MEASURED FROM, or it is not wrong -- it is
    // unfalsifiable, which is this page's whole subject in its purest form.
    // Every Center range in this project's history was measured from Batumi
    // because a fallback chose it, and no screen anywhere said so: you had to
    // read `field_origin` to find out. [#160]
    //
    // The bridge publishes the name AND why that point, and the page prints
    // both without judging either -- so today's card reads "from BATUMI, the
    // loaded approach", which is the bug printing its own name.
    + kv('position', line([
        r.range_nm === null || r.range_nm === undefined ? ''
          : num(r.range_nm, 1, ' nm') + (r.radial === null
              || r.radial === undefined ? '' : ' on ' + num(r.radial, 0, ''))
            + datum(r.datum),
        r.alt_ft === null || r.alt_ft === undefined ? '' : num(r.alt_ft, 0, ' ft'),
        r.heading === null || r.heading === undefined ? ''
          : num(r.heading, 0, '\\u00b0'),
        r.speed_kt === null || r.speed_kt === undefined ? ''
          : num(r.speed_kt, 0, ' kt')]), 'num')
    + kv('track', val(r.track))
    // THE STRIP HE WAS RESOLVED FROM, whole, as the bridge attached it to the
    // row. Published on the board row since the plans panel was written and
    // never once drawn.
    // ...AND WHERE IT GOES, which is the whole reason a controller wants the
    // strip in front of him.
    //
    //     "On nowhere on the board does it say marlin is going to batumi."
    //
    // It was on the wire the entire time -- the bridge attaches the plan ROW,
    // and `filing.derived` puts the destination on it (the last leg, since
    // migration 031). The card printed the label and dropped it. That is the
    // third time this exact shape has been reported on this page: the fact is
    // published, the renderer does not draw it, and the gap reads as the
    // system not knowing. `cleared_approach` was the first, the strip itself
    // the second.
    + kv('strip', r.plan
        ? val(r.plan.label || r.plan.name)
          + (r.plan.destination
              ? ` <span class="dim">${TO}</span> ${esc(r.plan.destination)}`
              : '')
        : val(null))
    // WHAT WAS DECIDED ABOUT HIM AND NOT DONE. His own lines out of the quiet
    // log -- the newest is the standing answer, because `watching_him` records
    // only when the answer changes.
    + kv('not done', rs.length
        ? rs.map(q => `<span class="why">${esc(q.text)}</span>`
            + ` <span class="dim">${esc(q.kind)}, ${ago(q.ago)}</span>`)
            .join('<br>')
        : `<span class="dim">${DASH}</span>`)
    + '</div></div>';
}

function board(d) {
  const b = d.board || [];
  if (!b.length) return '<p class="empty">nobody on the board</p>';
  const by = d.quiet_by || {};
  return b.map(r => card(r, by[r.callsign])).join('');
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
      + `<td class="dim">${val(r.track)}</td>`
      + `<td class="dim">${(r.scope || []).map(esc).join(', ') || 'nothing'}</td>`
      + '</tr>').join('') + '</table>';
}

// EVERY RECORD OF DECIDING NOTHING, newest first.
//
//   "why is nothing happening" is the question this page is opened to answer,
//   and the answer was already being written down -- "Georgia Center keeps him
//   -- departure, 35 nm, inbound" -- into a log nobody reads in the air.
//
// The page attaches no meaning to the kinds; it prints the word the recorder
// used and the sentence the bridge wrote.
function quiet(d) {
  const q = d.quiet || [];
  if (!q.length) return '<p class="empty">nothing declined, refused or taken '
    + 'back this session</p>';
  return q.map(r => '<div class="q"><span>'
    + (r.callsign ? `<span class="who">${esc(r.callsign)}</span> ` : '')
    + `<span class="dim">${esc(r.kind)}</span> ${esc(r.text)}</span>`
    + `<span class="t">${ago(r.ago)}</span></div>`).join('');
}

// "185 for 35 (blue)" -- said the way it is said on the radio, bearing first.
// An em dash when the sim has given us no bullseye or the contact has no
// position: absent, never a plausible wrong number.
function bulls(u) {
  const b = u.bulls || {};
  if (b.range_nm === undefined || b.range_nm === null) return '';
  const pad = String(Math.round(b.radial)).padStart(3, '0');
  // NAMED LIKE EVERY OTHER RANGE ON THIS PAGE, through the same function. This
  // row has always carried `ref` -- which bullseye, red or blue -- and that is
  // WHOSE, not WHAT: a reader still had to know that a bullseye is what these
  // two numbers are off. It is the one reference on the page that was already
  // half honest, and the datum makes it say the rest. [#160] [#155]
  return `${pad}\\u00b0 / ${b.range_nm.toFixed(1)} nm`
    + datum(b) + (b.ref ? ` <span class="dim">(${esc(b.ref)})</span>` : '');
}

function untracked(d) {
  // Radar sees it, nobody is working it. Together with the board this is a
  // complete account of what is on the scope -- every contact is in exactly
  // one of the two.
  // Aircraft only. Whether a thing is traffic is the bridge's judgement,
  // published as `is_aircraft` -- the page does not know what a T-55 is.
  const loose = (d.scope || []).filter(u => !u.controlled && u.is_aircraft);
  const lost = d.unidentified || [];
  // WHAT THIS PANEL IS NOT SHOWING, AND WHY, rather than a filtered list that
  // reads as a complete one. The comment above claims tracked and untracked
  // are complements -- every contact in exactly one -- and the filter quietly
  // breaks that claim for anything the bridge does not call an aircraft. A
  // contact in NEITHER table, while the header counts it, is the same fault as
  // an indicator that cannot go red: the page said "every contact is on the
  // board" with one on the scope and none on the board.
  const hid = (d.scope || []).filter(u => !u.controlled && !u.is_aircraft);
  const held = !hid.length ? '' : `<p class="empty">${hid.length} more on the `
    + 'scope the bridge does not count as aircraft: '
    + hid.map(u => esc(u.name)).join(', ') + '</p>';
  if (!loose.length && !lost.length)
    return (held || '<p class="empty">every contact is on the board</p>');
  let out = '';
  // BOTH NAMES, SIDE BY SIDE.
  //
  //     "I want untracked to show the dcs callsign and the derived callsign -
  //      so that I can see the translation."
  //
  // The left is the string the sim published; the right is the board key it
  // derives to. They are one fact and its derivation, and printing only the
  // answer is how a bad translation stays invisible until a controller uses the
  // wrong name on the radio. The page does no deriving of its own -- the bridge
  // sends `derived`, for the same reason it sends `bulls`.
  //
  // NEITHER FALLS BACK TO THE OTHER. The first version printed
  // `u.derived || u.callsign || '-'`, which is the page picking which of three
  // values to believe -- and it would have shown a plausible name in the field
  // whose entire purpose is to reveal that the derivation is broken.
  //
  // FROM BULLSEYE, not from this controller's threshold: nobody on this board
  // is working these aircraft, so a range off one field's beacon says nothing.
  // The bridge computes it against the contact's OWN coalition and names which
  // in `bulls.ref`.
  loose.forEach(u => {
    // THE SIM'S NAME, THEN THE KEY IT DERIVES TO, with the arrow the pilot
    // asked to see. Printed in that order because that is the direction the
    // derivation runs, and a translation shown backwards is one nobody can
    // check.
    out += '<div class="ac"><div class="hd">'
      + `<span class="dim">${val(u.name)}</span>`
      + `<span class="dim">\\u2192</span>`
      + `<span class="cs ${u.level || ''}">${val(u.derived)}</span>`
      + (u.tags || []).map(t => `<span class="pill">${esc(t)}</span>`).join(' ')
      + `<span class="rt">${val(u.type)}</span></div><div class="kv">`
      + kv('sim says', `<span class="${lvl('state', u.state)}">`
          + `${val(u.state)}</span>`)
      + kv('bullseye', bulls(u) || `<span class="dim">${DASH}</span>`, 'num')
      + kv('position', line([
          u.alt_ft === null || u.alt_ft === undefined ? '' : num(u.alt_ft, 0, ' ft'),
          u.heading === null || u.heading === undefined ? ''
            : num(u.heading, 0, '\\u00b0'),
          u.speed_kt === null || u.speed_kt === undefined ? ''
            : num(u.speed_kt, 0, ' kt')]), 'num')
      + '</div></div>';
  });
  if (lost.length) {
    out += '<h4>heard on the radio, tied to no aeroplane</h4>'
      + lost.map(r => '<div class="q"><span>'
        + `<span class="bad">${esc(r.radio)}</span> `
        + `<span class="dim">said</span> ${val(r.heard)} `
        + `<span class="dim">${esc(r.why || '')}</span></span>`
        + '<span class="t"></span></div>').join('');
  }
  return out + held;
}

// `key()` LIVED HERE. It squashed a name to letters and digits so the page could
// match a board row's track against a scope contact -- the fourth implementation
// of that squash in this codebase (`identity._key`, `agent_atc._key_name`,
// `diag._key` are the others) and the only one in a language nobody was testing.
// It went with the join it existed for. If a lookup ever seems to be needed here
// again, the field is missing from the snapshot and that is the bug.

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
    // THE PILL GOES INSIDE THE VALUE, not beside it.
    //
    // `.trail li` is a two-column grid -- the stage label, then everything
    // else. Emitted as a THIRD child the pill took the 1fr column for itself
    // and the text was pushed into an implicit fourth column, which grid sizes
    // to min-content: a hundred-pixel ribbon down the left of the page, one
    // word per line, under a badge stretched across the full width.
    //
    // Only DECIDE and SPEAK carry an origin, so `heard` and `who` -- two
    // children each -- went on looking perfect, which is why this survived. The
    // `who` row above already had it right: its pill is inline inside the
    // value, and that is the pattern.
    out += `<li><span class="k">${esc(meta.stage || t.kind)}</span>`
      + `<span class="${meta.level || ''}">`
      + (org ? `<span class="pill org-${esc(org)}">${esc(org)}</span> ` : '')
      + `${esc(t.gate || t.text)}`
      + (t.seconds ? `<span class="dim"> ${t.seconds}s ${esc(t.tier || '')}</span>` : '')
      + '</span></li>';
  });
  return out + `</ul><p class="empty">${ago(l.ago)} ago on ${l.freq || '?'}</p>`;
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
// The page decides nothing here: `attributed_to`, `is_flight` and `on_ground`
// are all joined upstream, because working out that a plan filed as "Pony 1-1"
// belongs to the man the board calls "sockeye" needs the identity registry, and
// a web page has no business holding one.
//
// NO APPROACH COLUMN AND NO ACTIVE COLUMN. Both were deleted from
// `flight_plans` by migration 031 -- "a plan does not name an arrival ...
// `active` was how the bridge used to read its own procedure out of a plan
// row" -- and this table went on printing a header for each. The approach cell
// read an undefined key and rendered the literal string "&mdash;"; the active
// cell read another and rendered "no", which is an ANSWER, to a question
// nothing has asked since 12 August.
function plans(d) {
  const p = d.plans || [];
  if (!p.length) return '<p class="empty">no flight plans on file</p>';
  return '<table><tr><th>plan</th><th>filed for</th><th>flying it</th>'
    + '<th>where</th></tr>'
    + p.map(x => {
      const who = x.attributed_to
        ? `<span class="acc">${esc(x.attributed_to)}</span>`
          + (x.is_flight ? ' <span class="dim">(flight)</span>' : '')
        : '<span class="dim">nobody</span>';
      // Three states, not two: airborne, on the ground, or radar cannot see him
      // at all -- and "we do not know" must not render as "parked".
      const where = x.on_ground === null || x.on_ground === undefined
        ? `<span class="dim">${DASH}</span>`
        : (x.on_ground ? 'on the ground' : 'airborne');
      return `<tr><td>${val(x.label || x.name)}</td>`
        + `<td class="dim">${val(x.callsign)}</td>`
        + `<td>${who}</td><td class="dim">${where}</td></tr>`;
    }).join('') + '</table>';
}

function flights(d) {
  const f = d.flights || [];
  return f.length
    ? '<table><tr><th>flight</th><th>lead</th><th>members</th></tr>'
      + f.map(x => `<tr><td class="acc">${esc(x.name)}</td><td>${esc(x.lead)}</td>`
        + `<td class="dim">${x.members.length ? esc(x.members.join(', ')) : DASH}`
        + `</td></tr>`).join('') + '</table>'
    : '<p class="empty">no flights formed</p>';
}

// WHICH SOURCE A PANEL WAS READ FROM, AND HOW OLD IT IS.
//
// Stamped on every panel because the page's central fault was a value with no
// account of where it came from. The two sources age independently and only one
// of them is the board: a quiet frequency ages the recorder, a stopped bridge
// ages the snapshot, and reading either as the other is what "lying a little to
// console me" was.
function stamp(id, src) {
  const s = src || {};
  const el = $(id);
  el.textContent = `${s.name || '?'} ${ago(s.age)}`;
  el.className = 'src ' + aged(s.age);
}

async function tick() {
  try {
    const d = await (await fetch('/diag.json', {cache: 'no-store'})).json();
    LEGEND = d.legend || {};
    const S = d.sources || {};
    $('sess').textContent = d.session || 'none';
    $('age').textContent = ago(d.recorder_age);
    $('age').className = aged(d.recorder_age);
    $('bage').textContent = d.bridge_age == null ? 'no snapshot'
      : ago(d.bridge_age);
    $('bage').className = aged(d.bridge_age);
    $('contacts').textContent = (d.scope || []).length;
    $('contacts').className = (d.scope || []).length ? 'ok' : 'warn';
    // HISTORY MUST NOT READ AS STATE, and the two sources fail differently.
    // With the bridge stopped the board sits there looking live; with the
    // frequency quiet the recorder does, and the old page had one banner for
    // both -- so it accused a running bridge of being dead while its snapshot
    // was a second old.
    const st = $('stale');
    let notes = [];
    if (d.bridge_age == null) {
      notes.push('No snapshot from the bridge \\u2014 nothing below is state, '
        + 'only history. Is it running?');
    } else if (d.bridge_age > OLD_WARN) {
      notes.push('The bridge last published ' + ago(d.bridge_age)
        + ' ago \\u2014 the board is that old.');
    }
    if (d.recorder_age == null) {
      notes.push('No flight recorder yet \\u2014 nothing has been said on the '
        + 'radio this mission.');
    } else if (d.recorder_age > OLD_WARN) {
      notes.push('Nothing heard on the radio for ' + ago(d.recorder_age)
        + ' \\u2014 the last turn below is that old.');
    }
    st.style.display = notes.length ? 'block' : 'none';
    st.innerHTML = notes.map(n => '<div>' + n + '</div>').join('');
    // "BOARD AND RADAR AGREE" IS AN ANSWER, and with no snapshot there is no
    // board to agree with anything -- so the green banner was reporting a
    // clean scope for a bridge that had published nothing at all. Same fault as
    // the ghost count that could never go red: a verdict has to be able to say
    // it does not know.
    const g = (d.ghosts || []).length;
    $('verdict').innerHTML = d.bridge_age == null
      ? '<span class="dim">no board published</span>'
      : g ? `<span class="bad">${g} on the board that radar cannot see</span>`
          : '<span class="ok">board and radar agree</span>';
    $('board').innerHTML = board(d) + releases(d);
    $('quiet').innerHTML = quiet(d);
    $('last').innerHTML = last(d.last);
    $('untracked').innerHTML = untracked(d);
    $('flights').innerHTML = flights(d);
    $('plans').innerHTML = plans(d);
    $('handed').innerHTML = handed(d.handed);
    stamp('s-board', S.bridge);
    stamp('s-quiet', S.recorder);
    stamp('s-last', S.recorder);
    stamp('s-untracked', S.bridge);
    stamp('s-flights', S.bridge);
    stamp('s-plans', S.bridge);
    stamp('s-handed', S.bridge);
  } catch (e) {
    $('verdict').innerHTML = '<span class="bad">diag unreachable</span>';
  }
}
// --- control ---------------------------------------------------------------
// The token is not in the page. That is the property worth keeping: `/diag`
// can be left open on a kneeboard, screenshotted and pasted into an issue
// without carrying the ability to stop the radio with it.
//
// KEPT PER BROWSER, NOT PER TAB. It was `sessionStorage`, which is scoped to
// one tab and dies with it -- so every fresh tab, every reopened kneeboard and
// every reload after a crash asked for it again, which is most of the times
// anybody wants this panel. A control you have to authenticate to reach in an
// emergency is a control you do not use. `localStorage` still keeps the token
// out of the page source and out of any screenshot; it just stops asking
// twenty times a sortie.
let TOKEN = localStorage.getItem('marshall-token') || '';

async function control(what) {
  if (!TOKEN) {
    TOKEN = prompt('Control token (MARSHALL_CONTROL_TOKEN in .env):') || '';
    if (!TOKEN) return;
    localStorage.setItem('marshall-token', TOKEN);
  }
  const url = what === 'mission'
    ? '/control/mission/restart?token=' + encodeURIComponent(TOKEN)
    : '/control/bridge/' + what + '?token=' + encodeURIComponent(TOKEN);
  $('cmsg').textContent = what + '...';
  $('cmsg').className = '';
  try {
    const r = await fetch(url, {method: 'POST', cache: 'no-store'});
    const d = await r.json();
    if (r.status === 403) { localStorage.removeItem('marshall-token'); TOKEN = ''; }
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
