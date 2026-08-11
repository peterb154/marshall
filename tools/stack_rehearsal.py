"""Three arrivals at once, and the invariant this whole project exists for.

    "I do feel like we are over engineered for the stack that we haven't flown
     in a long time. We are fighting such simple behaviors now we haven't
     gotten to the complex stuff like stacked holds."

Half right, and the half that is right is worth acting on. The deterministic
engine is 1,988 lines whose reason for existing is that **an LLM never invents
separation between aircraft** -- and counted across every board snapshot this
project has ever recorded:

    turns with anybody HOLDING          53
    turns with TWO OR MORE holding      16      <- the stack, ever
    most aircraft on the board at once   3      once, in a rehearsal

Sixteen turns. Everything else has been one aeroplane, where a sequencer cannot
be wrong because there is no sequence. So the engine is not over-engineered so
much as **unexercised**, and the way to find out which is to fly it.

WHAT THIS ASSERTS, and it is different in kind from `ladder_rehearsal.py`. That
one checks a conversation: did he say the right thing on the right frequency.
This checks a STATE -- the board, after every transmission, against rules that
must hold no matter what anybody said:

    1. NO TWO AIRCRAFT AT ONE LEVEL. The reason for all of it. Two aeroplanes
       assigned the same altitude in cloud is the accident the deterministic
       half exists to make impossible.
    2. ONE IN THE LETDOWN. The approach is a single-occupancy resource; a
       second aircraft cleared into it is the same accident lower down.
    3. THE STACK FILLS FROM THE BOTTOM. A hole in it means somebody was put
       above an empty level and will be held longer than he needs to be.
    4. NOBODY IS FORGOTTEN. An aircraft that reports and is never given a level
       nor a clearance is one the sequencer has lost -- which reads as silence
       on the radio and is the failure a pilot notices last.

A violation is reported with the whole board, because "two at five thousand" is
useless without knowing which two and what else was going on.

    uv run --extra voice python tools/stack_rehearsal.py
    uv run --extra voice python tools/stack_rehearsal.py --ships 4

WHAT IT STILL CANNOT PROVE: that the aeroplanes actually fly the pattern. They
are spawned inbound and then hold their course -- the engine is being tested,
not the sim's autopilot. And, as ever, this is our Polly against our Whisper.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from marshall import config
# ONE HARNESS, NOT TWO. The spawn, the clean board, the transmit-and-collect and
# the misheard check are the same problems here as on the ladder, and the ladder
# already solved each of them the hard way -- reading `transcript` rather than
# `text`, folding Whisper's digits, clearing the director's flights as well as
# restarting the bridge. A second copy would be a second set of those bugs.
from ladder_rehearsal import (
    a_clean_board, events_since, fly_an_aeroplane, say_it, size, take_it_away)

# WHERE THEY COME FROM. Different radials so the scope can tell them apart, and
# far enough out that they are Center's before they are Approach's -- an arrival
# that appears inside the handoff range has skipped the half of the sortie this
# is meant to sequence. Altitudes deliberately NOT the stack levels: what they
# are flying when they call is not what they should be assigned.
# RADIALS AND RANGES, not altitudes: the level each one is flying when he calls
# is derived from the theatre's stack so it is NOT one of the levels he should
# be assigned, on a map where the stack starts at nine thousand as readily as at
# five. Different radials so the scope can tell them apart, and far enough out
# that they are Center's before they are Approach's.
ARRIVALS = [
    ("Sockeye", "Joey",     "Pony one one",   285.0, 32.0),
    ("Bandit",  "Justin",   "Pony one two",   310.0, 38.0),
    ("Hoover",  "Matthew",  "Pony one three", 255.0, 44.0),
    ("Shooter", "Stephen",  "Pony one four",  330.0, 50.0),
]


def arrivals_for(th, n):
    """The fixture flights, at levels this theatre would not assign them.

    Above the stack, spaced, so what they are FLYING when they call cannot be
    mistaken for what they were GIVEN -- which is the whole thing the invariants
    below are looking at. Written as fixed altitudes once, and 11,000 is inside
    Nellis's stack.
    """
    top = th.approach.stack_ft[-1]
    return [(srs, voice, cs, brg, rng, top + 1000 * (i + 1))
            for i, (srs, voice, cs, brg, rng) in enumerate(ARRIVALS[:n])]

# What each of them says, in order. Every ship checks in, then every ship
# reports the beacon, then every ship asks for the approach -- interleaved, so
# the engine is sequencing rather than working one aeroplane to completion and
# then the next. A stack that only ever holds one at a time is not a stack.
ROUNDS = [
    ("{who}, checking in, inbound.", "everybody arrives"),
    ("{who}, over the beacon, request approach.", "everybody wants it"),
    ("{who}, request approach.", "and asks again"),
]


def levels_of(board) -> dict:
    """Callsign -> assigned level, for everybody the engine has put somewhere."""
    return {a.get("callsign"): a.get("assigned_ft") for a in board
            if a.get("assigned_ft")}


def last_board(ev) -> list:
    for e in reversed(ev):
        if e.get("kind") == "board":
            return e.get("board") or []
    return []


# --- the invariants ---------------------------------------------------------
#
# Each returns a list of complaints. Empty is the only acceptable answer, and
# each one is phrased as what went wrong rather than which rule fired, because
# the rule's name tells a reader nothing he does not already know.

def two_at_one_level(board) -> list:
    """Two aircraft assigned one altitude -- and WHICH two matters.

    Two HOLDERS at one level is unambiguously wrong: they are in the same
    pattern over the same beacon and nothing separates them.

    A holder at the level of the aircraft in the LETDOWN is the same geometry
    and is arguable, because he is leaving. It is reported separately rather
    than lumped in, because the two have different answers and calling them one
    thing would get the wrong one fixed. See #108.
    """
    bad, by_level = [], {}
    for a in board:
        ft = a.get("assigned_ft")
        if ft:
            by_level.setdefault(ft, []).append(a)
    for ft, at in sorted(by_level.items()):
        if len(at) < 2:
            continue
        holders = [a for a in at if a.get("phase") == "HOLDING"]
        leaving = [a for a in at if a.get("in_letdown") or a.get("phase") == "CLEARED"]
        names = " and ".join(str(a.get("callsign")) for a in at)
        if len(holders) > 1:
            bad.append(f"{names} are BOTH HOLDING at {ft:,} ft")
        elif holders and leaving:
            bad.append(f"{names} are both at {ft:,} ft -- "
                       f"{leaving[0].get('callsign')} is in the letdown and "
                       f"{holders[0].get('callsign')} was put on his level [#108]")
        else:
            bad.append(f"{names} are BOTH assigned {ft:,} ft")
    return bad


def two_in_the_letdown(board) -> list:
    down = [a.get("callsign") for a in board if a.get("in_letdown")]
    if len(down) > 1:
        return [f"{' and '.join(down)} are all in the letdown at once"]
    cleared = [a.get("callsign") for a in board if a.get("phase") == "CLEARED"]
    if len(cleared) > 1:
        return [f"{' and '.join(cleared)} are all CLEARED for the approach"]
    return []


def a_hole_in_the_stack(board, stack_ft) -> list:
    """Somebody above an empty level is being held longer than he need be.

    HOLDERS ONLY, AND ONLY LEVELS THAT ARE IN THE STACK. This asked the question
    of every assigned altitude, so an aircraft under vectors at twelve thousand
    -- above the stack top, and not a holding level at all -- read as a hole
    below him and was reported three times as a separation violation. A check
    that fires on correct behaviour is one people learn to scroll past.

    The aircraft in the letdown is excluded for the same reason he RESERVES his
    level (#108): he is leaving, and the hole under a stack that is waiting for
    him to go is not a hole.
    """
    used = sorted({a.get("assigned_ft") for a in board
                   if a.get("phase") == "HOLDING"
                   and a.get("assigned_ft") in stack_ft})
    if len(used) < 2:
        return []
    below = [ft for ft in stack_ft if ft < used[0]]
    # Every level below the lowest holder must belong to somebody -- the
    # letdown, a missed approach -- or it is a rung nobody is standing on.
    taken = {a.get("assigned_ft") for a in board if a.get("assigned_ft")}
    empty = [ft for ft in below if ft not in taken]
    want = [ft for ft in stack_ft if ft >= used[0]][:len(used)]
    if empty:
        return [f"holders are at {', '.join(f'{f:,}' for f in used)} with "
                f"{', '.join(f'{f:,}' for f in empty)} empty beneath them"]
    if used != want:
        return [f"holders are at {', '.join(f'{f:,}' for f in used)} but the "
                f"stack has no gaps: {', '.join(f'{f:,}' for f in want)}"]
    return []


def forgotten(board) -> list:
    """On the board, radar-identified, and given nothing at all."""
    bad = []
    for a in board:
        if not a.get("identified"):
            continue
        if a.get("phase") in ("UNKNOWN", "") and not a.get("assigned_ft"):
            bad.append(f"{a.get('callsign')} is identified and has no level "
                       f"and no clearance -- the sequencer has lost him")
    return bad


_SENT_AWAY = ("contact ", "good day")
_ORDERED = ("hold at", "maintain ", "turn left", "turn right", "descend",
            "climb and", "cleared for the", "cleared radar", "expect the")


def sent_away_and_ordered(ev) -> list:
    """One transmission that both hands him over and tells him what to do.

    #115's third criterion. He cannot obey both: he has been given to somebody
    else and instructed by the man who gave him away. `reconcile` arbitrates it
    now, and this is the check that says so from the outside -- reading the
    words that actually went out rather than the decision that produced them.
    """
    bad = []
    for e in ev:
        if not str(e.get("kind", "")).startswith("atc/"):
            continue
        said = (e.get("text") or "").lower()
        if any(x in said for x in _SENT_AWAY) and any(x in said for x in _ORDERED):
            bad.append(f"handed over AND instructed in one breath: "
                       f"{(e.get('text') or '')[:110]}")
    return bad


def show(board) -> str:
    if not board:
        return "      (nobody on the board)"
    out = []
    for a in sorted(board, key=lambda x: str(x.get("callsign"))):
        out.append(f"      {a.get('callsign')!s:16} {a.get('phase')!s:9}"
                   f" {(str(a.get('assigned_ft')) + ' ft') if a.get('assigned_ft') else '-':>10}"
                   f"{'  <- letdown' if a.get('in_letdown') else ''}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--srs", default=config.SRS_HOST)
    ap.add_argument("--session", default="hooks")
    ap.add_argument("--ships", type=int, default=3,
                    help="how many arrivals (2-4). One is not a stack")
    ap.add_argument("--mhz", type=float, default=0.0,
                    help="the frequency they all work "
                         "(default: the arrival field's Approach)")
    ap.add_argument("--wait", type=float, default=25.0)
    ap.add_argument("--no-spawn", action="store_true")
    ap.add_argument("--no-restart", action="store_true")
    args = ap.parse_args(argv)

    n_ships = max(2, min(args.ships, len(ARRIVALS)))
    recorder = config.BUILD_DIR / "logs" / f"flight-{args.session}.jsonl"

    from marshall.atc import agent_atc as _aa
    from marshall.core import theatre as _th
    from marshall.radio import tts
    from marshall.radio.client import AM, SRSClient, radio

    th = _th.current()
    ships = arrivals_for(th, n_ships)
    profile = _aa.load_and_push_plate(th.approach)
    stack_ft = list(profile.stack_ft)

    if not args.mhz:
        # THE ARRIVAL FIELD'S APPROACH, not a Caucasus number. 124.425 is Batumi
        # and there is no such frequency on Nevada, so every transmission went
        # to a channel nobody was listening on and the whole run reported an
        # unresponsive controller.
        _app = next((s for s in th.stations
                     if s.role == "approach" and s.field == th.arrival), None)
        args.mhz = _app.freq_mhz if _app else 124.425
    print(f"the holding stack at {th.arrival}, flown by "
          f"{len(ships)} synthetic arrivals")
    print(f"  on {args.mhz:.3f}, stack levels "
          f"{', '.join(f'{f:,}' for f in stack_ft)}")
    print(f"  recorder: {recorder}\n")

    if not args.no_restart:
        print("  a clean board first")
        a_clean_board()

    parked = []
    if not args.no_spawn:
        for srs_name, _v, _cs, brg, rng, alt in ships:
            unit = f"362nd_{srs_name}"
            print(f"  {unit} inbound from the {brg:.0f} at {rng:.0f} nm, "
                  f"{alt:,} ft")
            if fly_an_aeroplane(unit, brg, rng, alt):
                parked.append(unit)
        # THEY HAVE TO REACH THE SCOPE BEFORE ANYBODY SPEAKS. The engine binds a
        # radio to an aeroplane by radar, so a check-in that arrives first is a
        # voice it correctly declines to sequence -- and every invariant below
        # would then be vacuously true.
        print("  waiting for the sweep")
        time.sleep(20.0)
        print()

    violations, turns, judged = [], 0, 0
    try:
        for line, why in ROUNDS:
            print(f"── {why}")
            for srs_name, voice, callsign, *_ in ships:
                said = line.format(who=callsign)
                a = argparse.Namespace(srs=args.srs, name=srs_name, voice=voice,
                                       wait=args.wait)
                mark = size(recorder)
                print(f"   {callsign:15} {said}")
                say_it(a, args.mhz, said, recorder, SRSClient, radio, AM, tts)
                ev = events_since(recorder, mark)
                for e in ev:
                    if str(e.get("kind", "")).startswith("atc/") and e.get("text"):
                        print(f"      ATC: {e['text'][:110]}")
                board = last_board(ev)
                turns += 1
                judged += 1 if board else 0
                bad = (two_at_one_level(board) + two_in_the_letdown(board)
                       + a_hole_in_the_stack(board, stack_ft) + forgotten(board)
                       + sent_away_and_ordered(ev))
                if bad:
                    for b in bad:
                        print(f"      !! {b}")
                    print(show(board))
                    violations.extend(bad)
                else:
                    print(show(board))
                print()
    finally:
        for unit in parked:
            take_it_away(unit)
        if parked:
            print(f"  removed {len(parked)} aircraft from the scope.")

    print("=" * 62)
    print(f"  {turns} transmissions, {len(ships)} arrivals")
    # A VACUOUS PASS IS NOT A PASS. Every invariant here is satisfied by an
    # empty board: nobody shares a level when nobody has one. The first Nevada
    # run reported "no aircraft shared a level, one letdown at a time, the stack
    # filled from the bottom, and nobody was forgotten" having spawned nothing
    # at all -- which is the harness lying green, and worse than failing.
    #
    # The rules cannot fire without traffic, so the run says what it saw and
    # refuses to call it a pass. Same bargain as `check.py`: skipped is
    # reported, never silent.
    if not judged:
        print("  NOTHING WAS JUDGED. No aircraft ever reached the board, so "
              "every rule above")
        print("  passed by being unreachable. That is not a green run.")
        return 2
    if violations:
        print(f"  {len(violations)} SEPARATION VIOLATION(S):")
        for v in violations:
            print(f"    {v}")
    else:
        print(f"  {judged} of {turns} turns had somebody on the board, and in "
              f"none of them")
        print("  did two aircraft share a level. One letdown at a time, the "
              "stack filled")
        print("  from the bottom, and nobody was forgotten.")
    print("\n  NOT PROVEN: that the aeroplanes fly the pattern -- they are")
    print("  spawned inbound and hold their course. This tests the engine,")
    print("  not the sim's autopilot. And it is our Polly against our Whisper.")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
