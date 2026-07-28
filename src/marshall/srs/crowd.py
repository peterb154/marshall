"""How badly does a crowded frequency confuse the board? Measure it.

    "the fact that this can happen -- that there is some dictionary with ghost
     aircraft -- makes me concerned about the foundational architecture of what
     we've built. My concern is that it's been working well for one human
     aircraft as long as whisper transcriptions are perfect.. But wait till
     there are 10 guys on."

The concern is right and the flaw is one line: `Controller.aircraft` is a
`dict[callsign -> Aircraft]` and the callsign arrives through Whisper, so the
primary key of the separation engine is a string a machine guessed at from
audio. See [ARCH-2] / #40.

This does not fix that. It MEASURES it, because the fix is a change to the
foundation and the last four times this project guessed at a fix instead of
measuring it, the guess was wrong. Two questions, and they have different
answers:

  ATTRIBUTION   when several aeroplanes with confusable names share a
                frequency, how often does a transmission move the WRONG
                aeroplane's state? That is not noise. It is a separation error,
                and nothing in the system reports it.

  GHOSTS        how often does something that is not an aeroplane end up on the
                board, take a level in the stack, and hold a real pilot behind
                it?

Two modes, because the second question can be asked of a sortie that has
already been flown:

    # synthetic: N radios, deliberately confusable callsigns, full accounting
    uv run --extra voice python -m marshall.srs.crowd --srs <host> 132.0 --ships 4

    # any recording, including a live one with real pilots in it
    uv run python -m marshall.srs.crowd --analyse <session-id>

The synthetic mode is the only one that can score ATTRIBUTION, because scoring
it needs ground truth -- who actually keyed the mic -- and only a synthetic
pilot can be believed about that. The ghost census needs no ground truth at all
and so runs against tomorrow's real sortie for free.

WHY REAL SRS AND REAL WHISPER. The error being measured is introduced by the
audio path. A harness that hands the bridge clean text measures nothing except
its own string handling, and would have reported a perfect score on every
evening that produced a ghost.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from marshall import config
from marshall.atc import callsign as cs_mod

# DELIBERATELY CONFUSABLE. This is not a stress test if the names are distinct:
# a controller who can tell "Pony" from "Viper" proves nothing about a
# controller who has to tell "Pony one one" from "Pony one two".
#
# Three kinds of collision, all of which happen on a real frequency:
#   same flight, adjacent numbers   Pony 1-1 / Pony 1-2   -- one syllable apart
#   different name, same numbers    Hoover 1-1            -- the digits collide
#   a name that rhymes with a digit Niner 1-1             -- "niner" IS a digit
#
# (SRS client identity, Polly voice, spoken callsign, canonical callsign)
ROSTER = [
    ("Sockeye", "Joey",    "Pony one one",   "Pony 1-1"),
    ("Bandit",  "Justin",  "Pony one two",   "Pony 1-2"),
    ("Ranger",  "Stephen", "Hoover one one", "Hoover 1-1"),
    ("Dagger",  "Kevin",   "Colt two one",   "Colt 2-1"),
    ("Musket",  "Gregory", "Pony one three", "Pony 1-3"),
    ("Anvil",   "Matthew", "Colt two two",   "Colt 2-2"),
]

# What each of them says, in order. Every line names the speaker, because that
# is what a pilot does and because a line that does not name anybody is a
# measurement of the binding rather than of the transcription.
#
# The position reports differ per ship on purpose: if two aeroplanes say the
# same words, a mis-attribution and a correct attribution produce identical
# transcripts and the run cannot be scored.
def script_for(spoken: str, i: int) -> list[str]:
    alt = ["three thousand", "four thousand", "five thousand",
           "six thousand", "seven thousand", "eight thousand"][i % 6]
    rng = ["one zero", "one two", "one five", "one eight", "two zero",
           "two two"][i % 6]
    return [
        f"Batumi Approach, {spoken}, checking in.",
        f"{spoken}, {alt}, {rng} miles northwest of the field.",
        f"{spoken}, request the radar approach.",
        f"{spoken}, say my altitude.",
    ]


# -- scoring -----------------------------------------------------------------
#
# Pure functions, deliberately: the expensive half of this tool needs SRS, Polly,
# Whisper, Bedrock and a running bridge, and a scoring rule that can only be
# exercised by flying is a scoring rule nobody checks.

def _looks_like_a_guid(name: str) -> str | bool:
    """An SRS client we have no name for yet.

    `client.name_for` falls back to the first six characters of the GUID, which
    is base57 -- mixed case, no spaces, and never a callsign. Belt and braces
    beside the recorded authority, for recordings made before that field
    existed.
    """
    n = (name or "").strip()
    return len(n) == 6 and " " not in n and n.lower() != n and n.upper() != n


CORRECT = "correct"
DROPPED = "dropped"           # a guard fired and nothing moved -- the SAFE failure
MISATTRIBUTED = "MIS-ATTRIBUTED"   # somebody else's state moved -- the dangerous one
GHOST = "GHOST"               # an aeroplane was invented


def classify(spoke: str, attributed: str, roster: set[str],
             radios: set[str], authority: str | None = None) -> str:
    """What happened to one transmission.

    `attributed` is what the recorder wrote: the resolved callsign, or -- when
    nothing resolved -- the SRS client name, which is why `radios` is needed to
    tell "we could not identify him" from "we identified him as somebody else".

    The ordering matters more than it looks. DROPPED is a success, not a
    failure: a transmission the system declined to attribute changed nobody's
    altitude and nobody's place in the queue, and a controller who says "say
    again" is doing his job. The failure worth counting is a transmission
    confidently filed against the wrong aeroplane.
    """
    # THE RECORDED AUTHORITY SETTLES IT, when the recording has one. Nothing
    # else can: on a real run the recorder writes whatever the radio is called,
    # and an SRS client whose name has not reached us yet is logged as a short
    # GUID stub -- so a transmission the system correctly REFUSED came out
    # looking like an invented aeroplane.
    #
    # That mattered the first time this ran for real. Whisper turned "Pony one
    # two" into "Pony wants you", the controller said "station calling, say
    # your callsign again" -- exactly right, an aeroplane was not invented --
    # and this scored it a GHOST. A harness that cries wolf on correct
    # behaviour gets switched off, and then it is not measuring anything.
    if authority is not None and not authority:
        return DROPPED
    if not attributed or attributed in radios or _looks_like_a_guid(attributed):
        return DROPPED
    if attributed == spoke:
        return CORRECT
    if attributed in roster:
        return MISATTRIBUTED
    return GHOST


def ghost_census(entries: list[dict], real: set[str] | None = None) -> dict:
    """Everything that was ever on the board but never on radar.

    Needs no ground truth, which is the point: it can be run against a sortie
    flown by human beings who cannot be asked, afterwards, exactly which words
    they said at 21:14.

    On a radar approach every aeroplane must be identified before it may be
    sequenced, so a board entry that is NEVER identified for the whole recording
    is either a procedural contact -- which this profile does not have -- or a
    ghost. `real`, when the caller knows it, only sharpens the report; the
    census stands without it.
    """
    # WHAT VOUCHED FOR EACH NAME, from the transmissions themselves. Radar is
    # the strongest authority but not the only one: a procedural controller has
    # no radar at all and works filed strips, and a pilot identified off a strip
    # who radar has not painted yet is a normal arrival, not an invention.
    #
    # Scoring on radar alone called two correctly-identified aeroplanes ghosts
    # on the first real run, which is the same cry-wolf failure as `classify`
    # had -- and a census nobody believes is a census nobody reads.
    vouched: dict[str, set[str]] = {}
    for e in entries:
        if e.get("kind") == "pilot" and e.get("authority"):
            vouched.setdefault(e.get("callsign") or "", set()).add(e["authority"])

    seen: dict[str, dict] = {}
    for e in entries:
        if e.get("kind") != "board":
            continue
        for row in e.get("board") or []:
            cs = row.get("callsign") or ""
            g = seen.setdefault(cs, {"callsign": cs, "first_t": e["t"],
                                     "last_t": e["t"], "ever_identified": False,
                                     "held_letdown": False, "created_by": "",
                                     "transmissions": 0})
            g["last_t"] = e["t"]
            g["transmissions"] += 1
            g["ever_identified"] |= bool(row.get("identified"))
            g["held_letdown"] |= bool(row.get("in_letdown"))
    for g in seen.values():
        g["seconds"] = round(g["last_t"] - g["first_t"], 1)
        g["authority"] = ", ".join(sorted(vouched.get(g["callsign"], ()))) or ""
        g["ever_identified"] |= bool(g["authority"])
        g["ghost"] = not g["ever_identified"]
        if real is not None and g["callsign"] in real:
            g["ghost"] = False
    return seen


def retro_census(entries: list[dict]) -> dict:
    """The same census, for sorties flown BEFORE the board snapshot existed.

    Every evening already recorded is evidence, and throwing it away to wait for
    a fresh run would be measuring the future when the past is sitting on disk.
    The recorder has kept, per transmission, who the bridge attributed it to and
    the radar picture at that instant -- which is enough:

        a callsign the bridge worked, that never once appeared on the scope
        during the whole recording, was never an aeroplane.

    Weaker than the live census, and deliberately so. It cannot see an entity
    the bridge created and never addressed, it counts transmissions rather than
    stack levels, and a genuine aeroplane outside radar cover for an entire
    sortie would be a false positive. It is a floor on the ghost count, not the
    number itself.
    """
    seen: dict[str, dict] = {}
    scopes: list[str] = []
    for e in entries:
        if e.get("kind") != "pilot":
            continue
        cs = (e.get("callsign") or "").strip()
        scopes.append(e.get("scope") or "")
        if not cs:
            continue
        g = seen.setdefault(cs, {"callsign": cs, "first_t": e["t"],
                                 "last_t": e["t"], "transmissions": 0,
                                 "ever_identified": False, "held_letdown": False})
        g["last_t"] = e["t"]
        g["transmissions"] += 1
    corroborated = " ".join(scopes).lower()
    for g in seen.values():
        # The scope names the callsign once the bridge has correlated him; a
        # name that never appears in ANY radar picture all sortie was never
        # painted by anything.
        g["ever_identified"] = g["callsign"].lower() in corroborated
        g["ghost"] = not g["ever_identified"]
        g["seconds"] = round(g["last_t"] - g["first_t"], 1)
    return seen


def created_by(entries: list[dict], cs: str) -> str:
    """The transcript that first put this name on the board.

    A ghost is made of words. Naming them is the difference between "something
    invented an aeroplane" and a bug report somebody can act on.
    """
    last_pilot = ""
    for e in entries:
        if e.get("kind") == "pilot":
            # In a retrospective reading there are no board snapshots, and the
            # words that made the ghost ARE the transmission it was attributed
            # to -- the mis-hearing and the invention are the same event.
            if (e.get("callsign") or "") == cs:
                return e.get("transcript") or ""
            last_pilot = e.get("transcript") or ""
        elif e.get("kind") == "board":
            if any((r.get("callsign") or "") == cs for r in e.get("board") or []):
                return last_pilot
    return ""


def read_log(session_id: str) -> list[dict]:
    path = config.BUILD_DIR / "logs" / f"flight-{session_id}.jsonl"
    if not path.exists():
        raise SystemExit(f"no recording at {path}")
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue                       # a torn last line is not a failure
    return out


def report(entries: list[dict], truth: list[dict] | None = None,
           radios: set[str] | None = None) -> int:
    """Print the two numbers, and return non-zero if either is bad."""
    roster = {t["callsign"] for t in truth} if truth else set()
    bad = 0

    if truth:
        # Join ground truth to the recording on time: each transmission is
        # scored against the FIRST pilot entry the bridge logged after it.
        pilots = [e for e in entries if e.get("kind") == "pilot"]
        tally: dict[str, int] = {}
        print(f"{'said by':12} {'attributed to':14} {'verdict':16} transcript")
        for t in truth:
            match = next((p for p in pilots if p["t"] >= t["t"] - 0.5), None)
            if match is None:
                tally["no-record"] = tally.get("no-record", 0) + 1
                continue
            pilots.remove(match)
            got = match.get("callsign") or ""
            v = classify(t["callsign"], got, roster, radios or set(),
                         match.get("authority"))
            tally[v] = tally.get(v, 0) + 1
            heard = cs_mod.extract(match.get("transcript") or "")
            flag = "" if heard == t["callsign"] else f"   (whisper heard {heard or '-'})"
            print(f"{t['callsign']:12} {got:14} {v:16} "
                  f"{(match.get('transcript') or '')[:60]}{flag}")
        n = sum(tally.values()) or 1
        print(f"\n{n} transmissions")
        for k in (CORRECT, DROPPED, MISATTRIBUTED, GHOST, "no-record"):
            if tally.get(k):
                print(f"  {k:16} {tally[k]:4}   {100*tally[k]/n:5.1f}%")
        bad += tally.get(MISATTRIBUTED, 0) + tally.get(GHOST, 0)
        if not bad:
            print("\nno transmission moved the wrong aeroplane's state.")

    live = any(e.get("kind") == "board" for e in entries)
    census = (ghost_census(entries, roster or None) if live
              else retro_census(entries))
    ghosts = [g for g in census.values() if g["ghost"]]
    how = "board" if live else "retrospective (no board snapshots in this recording)"
    print(f"\n{how}: {len(census)} entities the bridge worked, {len(ghosts)} "
          f"never seen by radar")
    for g in sorted(ghosts, key=lambda g: -g["seconds"]):
        made = created_by(entries, g["callsign"])
        held = "  HELD THE LETDOWN" if g["held_letdown"] else ""
        print(f"  GHOST {g['callsign']!r:24} on the board {g['seconds']:7.0f}s "
              f"over {g['transmissions']} transmissions{held}")
        if made:
            print(f"        made by: {made[:88]}")
    bad += len(ghosts)
    return 1 if bad else 0


# -- the synthetic crowd -----------------------------------------------------


def run(host: str, freq_mhz: float, ships: int = 4, session_id: str = "",
        reply_wait: float = 30.0, rounds: int = 0) -> list[dict]:
    """N radios take turns on one frequency. Returns ground truth."""
    from marshall.srs import stt, tts
    from marshall.srs.client import AM, SRSClient, radio

    fleet = ROSTER[:max(2, min(ships, len(ROSTER)))]
    freq_hz = freq_mhz * 1_000_000
    model = stt.load_model()
    clients, voices = {}, {}
    for name, voice_id, _spoken, canon in fleet:
        voices[name] = tts.Voice(voice_id=voice_id)
        clients[name] = SRSClient(host, name=name,
                                  eam_password=config.SRS_EAM_PASSWORD).connect(
            [radio(freq_hz, AM)])
        print(f"[{name}] up as {canon} ({voice_id})", flush=True)
        time.sleep(1.0)

    # ROUND ROBIN, not ship by ship. Adjacent transmissions from confusable
    # aeroplanes is the whole experiment: a run where Pony 1-1 says all four of
    # its lines before Pony 1-2 speaks gives the system a fresh context every
    # time and measures nothing.
    scripts = {n: script_for(sp, i) for i, (n, _v, sp, _c) in enumerate(fleet)}
    lines = max(len(s) for s in scripts.values())
    if rounds:
        lines = min(lines, rounds)
    order = [(n, scripts[n][r]) for r in range(lines)
             for (n, _v, _s, _c) in fleet if r < len(scripts[n])]

    canon_of = {n: c for n, _v, _s, c in fleet}
    truth: list[dict] = []
    for name, line in order:
        client = clients[name]
        client.udp.settimeout(0.0)          # drop audio meant for somebody else
        try:
            while True:
                client.udp.recvfrom(4096)
        except OSError:
            pass
        t0 = time.time()
        print(f"{canon_of[name]}(tx): {line}", flush=True)
        client.transmit(voices[name].frames(line), freq_hz, AM)
        truth.append({"t": t0, "callsign": canon_of[name], "radio": name,
                      "said": line})
        pcm, _f = client.recv_utterance(max_wait=reply_wait, silence=1.6)
        heard = stt.transcribe(model, pcm) if (pcm is not None and pcm.size) else "<no reply>"
        print(f"   ATC: {heard}", flush=True)
        time.sleep(2.0)
    print("crowd complete\n", flush=True)
    return truth


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--srs", metavar="HOST", help="run the synthetic crowd")
    ap.add_argument("--freq", type=float, default=132.0)
    ap.add_argument("--ships", type=int, default=4)
    ap.add_argument("--rounds", type=int, default=0, help="lines per ship (0=all)")
    ap.add_argument("--session", default="", help="bridge session id to score")
    ap.add_argument("--analyse", metavar="SESSION",
                    help="score an existing recording (ghost census only)")
    ap.add_argument("--truth", metavar="FILE",
                    help="ground truth JSON from an earlier --srs run")
    args = ap.parse_args()

    if args.analyse:
        return report(read_log(args.analyse))

    if not args.srs:
        ap.error("give --srs HOST to fly it, or --analyse SESSION to score one")

    if not args.session:
        ap.error("--session is the bridge's session id; without it there is "
                 "nothing to score against")

    truth = run(args.srs, args.freq, args.ships, rounds=args.rounds)
    out = Path(config.BUILD_DIR) / "logs" / f"crowd-truth-{args.session}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(truth, indent=1), encoding="utf-8")
    print(f"ground truth -> {out}\n")

    time.sleep(3)                            # let the last exchange land
    radios = {r[0] for r in ROSTER}
    return report(read_log(args.session), truth, radios)


if __name__ == "__main__":
    raise SystemExit(main())
