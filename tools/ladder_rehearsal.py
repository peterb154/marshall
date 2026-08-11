"""Fly the comms ladder with a synthetic pilot, and CHECK it, with nobody in a jet.

    "Can you test some of this using ai aircraft. It's getting tedious to test
     the same things over and over."

It is, and a pilot is the wrong instrument for the parts that do not need ears.
Seven of the last eight sorties re-flew the same eight rungs to find out whether
a handoff fired -- which is a structural fact, recorded, and checkable.

WHAT MAKES THIS DIFFERENT FROM `flight_rehearsal.py`, which already speaks over
real SRS: that one prints what a human should expect and leaves the judging to
him. This asserts. Every step names the card row it stands for and a predicate
over the flight recorder, so the answer is PASS or FAIL and the exit code means
something.

IT CHECKS THE RECORDER, NOT THE AUDIO. `record()` writes one JSON object per
transmission -- the engine's directive, the agent's reply, the handoff, the
board with every aircraft's phase and owner, and `not_voiced` / `repaired` when
a decided fact went missing. That is the structure the two-brain seam actually
turns on. Whether it SOUNDS right is still a human's job and always will be:
see card row S11, which no machine can answer.

    uv run --extra voice python tools/ladder_rehearsal.py --srs <host>
    uv run --extra voice python tools/ladder_rehearsal.py --srs <host> --only Q3

WHAT IT CANNOT PROVE, and must not be read as proving:

  * anything gated on RADAR. A synthetic pilot has no aeroplane unless one is
    spawned, so the checks that compare a claim against the scope -- the
    hold-short speed test, the vectoring altitudes -- report SKIPPED rather
    than passing quietly. Pair it with `tools/ai_traffic.py` or
    `tools/asr_autopilot.py` for those.
  * that a HUMAN voice survives Whisper. This is our Polly against our Whisper,
    which only shows the two agree with each other.

Both limits are printed at the end rather than left to be discovered, for the
same reason `check.py` names what it skipped.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from marshall import config


# --- what a step may ask of the recorder -----------------------------------
#
# Deliberately small, and about STRUCTURE rather than words. "He said the right
# thing" is not checkable; "a handoff to Kobuleti Ground was authorised" is,
# and it is the fact the card row actually turns on.

def said(*words: str):
    """The controller's reply to the pilot contained all of these."""
    def check(ev):
        text = " ".join(e.get("text", "") for e in ev
                        if str(e.get("kind", "")).startswith("atc/")).lower()
        missing = [w for w in words if w.lower() not in text]
        return (not missing), f"missing from the reply: {', '.join(missing)}"
    return check


def handed_to(who: str):
    """A handoff was AUTHORISED -- the bridge's, not a sentence the agent wrote.

    `atc/handoff` is only ever written when `next_controller` said so, which is
    the whole difference between a real handoff and the agent being helpful.
    """
    def check(ev):
        for e in ev:
            if e.get("kind") == "atc/handoff" and who.lower() in e.get("text", "").lower():
                return True, ""
        if not on_the_board(ev):
            return None, "no aeroplane on the scope -- nothing to hand over"
        # An agent-voiced one is not nothing -- it means the words happened and
        # the authorisation did not, which is a different bug and worth saying.
        spoken = any(who.lower() in e.get("text", "").lower()
                     for e in ev if str(e.get("kind", "")).startswith("atc/"))
        return False, ("the agent said it but the bridge never authorised it"
                       if spoken else f"nothing handed him to {who}")
    return check


def phase_is(want: str):
    """The board says he is on this rung of the ladder. The engine's own answer.

    `sortie_phase`, NOT `phase`. The board carries both and they answer
    different questions: `phase` is the separation enum -- where he sits in the
    arrival queue -- and a parked aeroplane is ENROUTE in it, forever, which is
    correct and useless here. `sortie_phase` is the rung, and it is what
    `handoff.py` reads to decide who has him next.
    """
    def check(ev):
        for e in reversed(ev):
            if e.get("kind") != "board":
                continue
            for ac in e.get("board") or []:
                got = (ac.get("sortie_phase") or "").lower()
                if got == want.lower():
                    return True, ""
                return False, f"the board says {got or '(none)'}"
        return None, "nothing on the board yet"
    return check


def owned_by(who: str):
    """The board agrees who is working him."""
    def check(ev):
        for e in reversed(ev):
            if e.get("kind") != "board":
                continue
            for ac in e.get("board") or []:
                got = ac.get("owner") or ""
                return (who.lower() in got.lower()), f"the board says {got or '(nobody)'}"
        return None, "nothing on the board yet"
    return check


def on_the_board(ev) -> bool:
    """Does the separation engine know about this aeroplane at all?

    It only ever hears from RADIOS, and a radio is bound to an aircraft by
    RADAR. A synthetic pilot with nothing on the scope is a voice the engine
    declines to act on -- correctly, and by design since 30 July.
    """
    for e in reversed(ev):
        if e.get("kind") == "board":
            return bool(e.get("board"))
    return False


def engine_decided(*words: str):
    """The DETERMINISTIC directive said it, whatever the agent then did.

    SKIPS RATHER THAN FAILS WITH NO AEROPLANE. The first run of this reported
    six red rows against a controller that was behaving perfectly: with nothing
    on the scope the engine is not engaged, so of course it decided nothing.
    A check that cannot be evaluated must say so -- reporting it as a failure is
    how a harness teaches people to ignore it, which is worse than not having
    one.
    """
    def check(ev):
        if not on_the_board(ev):
            return None, "no aeroplane on the scope -- the engine is not engaged"
        text = " ".join(e.get("text", "") for e in ev
                        if e.get("kind") == "controller").lower()
        missing = [w for w in words if w.lower() not in text]
        return (not missing), f"the engine never decided: {', '.join(missing)}"
    return check


def nothing_lost():
    """No decided fact went missing on the way to the radio."""
    def check(ev):
        lost = [e.get("text", "") for e in ev if e.get("kind") == "not_voiced"]
        return (not lost), f"NOT VOICED: {'; '.join(lost)}"
    return check


def all_of(*checks):
    def check(ev):
        for c in checks:
            ok, why = c(ev)
            if ok is not True:
                return ok, why
        return True, ""
    return check


# --- the sortie -------------------------------------------------------------
#
# One entry per card row we keep re-flying. The frequency matters as much as the
# words: a role is only unique within an aerodrome, and which button he pressed
# is what says which aerodrome.

LADDER = [
    ("Q1", 125.100,
     "Kobuleti Clearance, Sockeye, request clearance.",
     said("kobuleti clearance"),
     "he answers as Kobuleti Clearance, not Batumi anything"),

    ("Q1a", 125.100,
     "Kobuleti Clearance, Sockeye, Domino please.",
     engine_decided("kobuleti clearance"),
     "the clearance is issued from the plan on file"),

    ("Q3b", 125.100,
     "Sockeye, say again the information letter.",
     said("information"),
     "#96 -- Clearance confirms the ATIS letter"),

    ("Q3", 125.100,
     "Cleared to Batumi as filed, maintain five thousand, departure one two "
     "three decimal three, squawk six five two one, Sockeye.",
     all_of(handed_to("ground"), phase_is("taxi")),
     "a correct read-back ends Delivery's business (#90)"),

    ("Q4", 121.800,
     "Kobuleti Ground, Sockeye, ready to taxi.",
     engine_decided("taxi to runway", "hold short"),
     "Ground clears him TO the runway and no further"),

    ("Q5", 121.800,
     "Kobuleti Ground, Sockeye, ready for departure.",
     all_of(engine_decided("tower"), said("one three three")),
     "Ground REFUSES the runway and names Tower with the frequency (#65)"),

    ("Q6", 121.800,
     "Kobuleti Ground, Sockeye, holding short of runway zero seven.",
     all_of(phase_is("holding_short"), handed_to("tower")),
     "holding short hands him to Tower (#88)"),

    ("Q7", 133.000,
     "Kobuleti Tower, Sockeye, holding short runway zero seven, ready for departure.",
     all_of(engine_decided("cleared for take-off"), nothing_lost()),
     "Tower clears it, with the runway and the wind, and all of it is spoken"),
]


def park_an_aeroplane(name: str, field: str) -> bool:
    """Put a jet on the ramp so the engine has something to work.

    THE ENGINE HEARS FROM RADIOS, AND A RADIO IS BOUND BY RADAR. Without a
    contact the separation engine correctly declines to act on a voice, so the
    first version of this harness could only judge the language-only rows and
    honestly skipped the rest.

    The identity chain cannot tell this from a human: it matches the SRS client
    name against the name radar prints, and both ends are ours to choose --
    `362nd_Sockeye-1` derives to the handle `Sockeye`, which is exactly what the
    synthetic pilot calls himself.

    A FAILURE HERE IS NOT A TEST FAILURE and must not read like one. A fixture
    that could not be placed means there was nothing to test, which is a
    different thing from the controller being wrong -- `spawn.py` used to print
    "no such airfield" and "spawned" in consecutive lines, and a rehearsal built
    on that reports bugs against innocent code.
    """
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "spawn.py"),
         "--name", name, "--type", "viper", "--ground", field,
         "--side", "blue", "--heading", "070"],
        check=False, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 or "FAILED" in out:
        last = out.strip().splitlines()[-1] if out.strip() else str(r.returncode)
        print(f"  !! could not park {name} at {field}: {last}")
        return False
    return True


def take_it_away(name: str) -> None:
    """Leave the scope as we found it. A fixture left behind is traffic in
    somebody else's sortie."""
    from marshall.feed.stubs import bind
    bind()
    import grpc
    from dcs.custom.v0 import custom_pb2, custom_pb2_grpc
    addr = os.environ.get("DCS_GRPC_ADDR", "127.0.0.1:50051")
    lua = (f"local g=Group.getByName('{name}') "
           f"if g then g:destroy() return 'ok' end return 'gone'")
    try:
        with grpc.insecure_channel(addr) as ch:
            custom_pb2_grpc.CustomServiceStub(ch).Eval(
                custom_pb2.EvalRequest(lua=lua), timeout=20)
    except Exception as e:
        print(f"  !! could not remove {name}: {type(e).__name__}")


def wait_for_radar(name: str, base: str, session: str, seconds: float = 90.0) -> bool:
    """Wait for the sweep to pick him up. He is not there until radar says so."""
    import urllib.parse
    import urllib.request
    url = (f"{base}/radar?"
           + urllib.parse.urlencode({"session_id": session}))
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=8) as resp:
                if name.split("_")[-1].lower() in resp.read().decode(
                        "utf-8", "replace").lower():
                    return True
        except Exception:
            pass
        time.sleep(5.0)
    return False


def events_since(path: Path, mark: int) -> list:
    """Everything the recorder has written since the byte offset `mark`."""
    if not path.exists():
        return []
    with open(path, encoding="utf-8", errors="replace") as fh:
        fh.seek(mark)
        out = []
        for line in fh:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out


def size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--srs", default=os.environ.get("SRS_HOST", ""),
                    help="the SRS server the bridge is on")
    ap.add_argument("--session", default=os.environ.get("MARSHALL_SESSION", "hooks"),
                    help="the bridge's session id -- names the recorder file")
    ap.add_argument("--voice", default="Joey", help="the synthetic pilot's voice")
    ap.add_argument("--name", default="Sockeye", help="his SRS client name")
    ap.add_argument("--wait", type=float, default=22.0,
                    help="seconds to allow for a reply before calling it silence")
    ap.add_argument("--only", default="", help="run one row, by id")
    ap.add_argument("--field", default="KOBULETI",
                    help="where the fixture aeroplane is parked")
    ap.add_argument("--no-spawn", action="store_true",
                    help="use whatever is already on the scope")
    args = ap.parse_args(argv)
    if not args.srs:
        print("!! --srs is required (or SRS_HOST)", file=sys.stderr)
        return 2

    from marshall.radio import tts
    from marshall.radio.client import AM, SRSClient, radio

    recorder = config.BUILD_DIR / "logs" / f"flight-{args.session}.jsonl"
    steps = [s for s in LADDER if not args.only or s[0] == args.only]
    if not steps:
        print(f"!! no row called {args.only}", file=sys.stderr)
        return 2

    print(f"the ladder, spoken by {args.name} against the live bridge")
    print(f"  recorder: {recorder}")
    print(f"  {len(steps)} rows\n")

    unit = f"362nd_{args.name}"
    parked = False
    if not args.no_spawn:
        print(f"  parking {unit} at {args.field} so the engine has an aeroplane")
        parked = park_an_aeroplane(unit, args.field)
        if parked and not wait_for_radar(unit, "http://localhost:8000", args.session):
            print("  !! it never reached the scope; the engine-side rows will skip")
        print()

    results, skipped = [], []
    for rid, mhz, line, check, why in steps:
        mark = size(recorder)
        client = SRSClient(args.srs, name=args.name,
                           eam_password=config.SRS_EAM_PASSWORD).connect(
            [radio(mhz * 1e6, AM)])
        try:
            print(f"── {rid}  on {mhz:.3f}")
            print(f"   {why}")
            print(f"   PILOT: {line}")
            client.transmit(tts.Voice(voice_id=args.voice).frames(line),
                            mhz * 1e6, AM)
            # WAIT FOR THE CONTROLLER, NOT FOR THE FILE.
            #
            # This watched the recorder for four seconds of quiet after any
            # growth -- and the pilot's own transmission and the board are
            # written IMMEDIATELY, while the reply is a model call six seconds
            # behind them. So every step ended before the controller spoke and
            # reported him silent. The harness was measuring itself.
            #
            # The step is over when the controller has answered and then gone
            # quiet, which is the same thing a pilot waits for.
            deadline = time.monotonic() + args.wait
            spoke_at = None
            while time.monotonic() < deadline:
                time.sleep(1.0)
                got = events_since(recorder, mark)
                if any(str(e.get("kind", "")).startswith("atc/") for e in got):
                    spoke_at = spoke_at or time.monotonic()
                    # A turn can be two transmissions -- a reply and a handoff.
                    # Give the second one room rather than cutting it off.
                    if time.monotonic() - spoke_at >= 4.0:
                        break
        finally:
            client.close()

        ev = events_since(recorder, mark)
        for e in ev:
            if str(e.get("kind", "")).startswith("atc/") and e.get("text"):
                print(f"   ATC:   {e['text'][:120]}")
        ok, detail = check(ev)
        if ok is None:
            skipped.append((rid, detail))
            print(f"   SKIP   {detail}\n")
        else:
            results.append((rid, ok))
            print(f"   {'PASS' if ok else 'FAIL'}   {detail if not ok else ''}\n")

    print("=" * 62)
    for rid, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {rid}")
    for rid, detail in skipped:
        print(f"  SKIP  {rid}  ({detail})")
    if skipped:
        print("\n  Skipped is not passed. A row that could not be judged is a row\n"
              "  nothing is watching.")
    if parked:
        take_it_away(unit)
        print(f"\n  {unit} removed from the scope.")
    print("\n  NOT COVERED HERE, whatever the result above: anything gated on\n"
          "  radar (there is no aeroplane unless one is spawned -- see\n"
          "  tools/ai_traffic.py), and whether a human voice survives Whisper.\n"
          "  This is our Polly against our Whisper.")
    return 1 if any(not ok for _r, ok in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
