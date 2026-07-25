"""Drive the whole ATC brain in text -- the bridge without the radio.

Mirrors exactly what `agent_atc._run_srs` assembles per transmission (radar line,
SRS identity, the deterministic CONTROLLER directive, the SEPARATION stack, the
pilot's words) and POSTs it to the director, but takes typed lines instead of
Whisper and prints the reply instead of speaking it.

That makes the two-brain seam testable in seconds rather than minutes: you find
out whether the agent VOICES the controller's break-up altitudes or paraphrases
them into fiction without standing up SRS, Polly, Whisper and a mission.

    uv run --extra voice python tools/atc_dryrun.py                 # formation
    uv run --extra voice python tools/atc_dryrun.py --script single
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from marshall.atc import agent_atc, controller as atc  # noqa: E402
from marshall.core import route as R  # noqa: E402

# (SRS transmitter identity, what the pilot says). The SRS name is deliberately
# not the callsign -- that three-way correlation is part of what we're testing.
FORMATION = [
    ("Sockeye", "Batumi Approach, Pony one one, flight of four, checking in."),
    ("Sockeye", "Pony one one, flight of four, over the beacon, six thousand."),
    # The controller asks whether they can maintain visual separation before he
    # breaks them up; nothing progresses until the flight answers.
    ("Sockeye", "Pony one flight, negative, we're in cloud."),
    ("Bandit",  "Pony one three, level five thousand."),
    ("Sockeye", "Pony one one, established inbound on the beam, starting my clock."),
    ("Sockeye", "Pony one one has the field, runway in sight."),
    ("Bandit",  "Pony one two, request approach."),
]

SINGLE = [
    ("Sockeye", "Batumi Approach, Pony one one, request approach."),
    ("Sockeye", "Pony one one, four thousand, five miles north of the field, inbound."),
    ("Sockeye", "Pony one one, can I get a DME to the field?"),
    ("Sockeye", "Pony one one, station passage, turning outbound three zero four."),
    ("Sockeye", "Pony one one has the field, runway in sight."),
]

VISUAL = [
    ("Sockeye", "Batumi Approach, Pony one one, flight of four, checking in."),
    ("Sockeye", "Pony one one, flight of four, over the beacon, six thousand."),
    ("Sockeye", "Pony one flight, affirmative, we can maintain visual separation."),
    ("Bandit",  "Pony one two, visual with lead, in trail."),
    ("Sockeye", "Pony one one, established inbound on the beam, starting my clock."),
    ("Sockeye", "Pony one one has the field, runway in sight."),
]

SCRIPTS = {"formation": FORMATION, "single": SINGLE, "visual": VISUAL}


def run(script, session_id: str, sep_always: bool = True,
        scope: str = "") -> None:
    """Drive `script` through the brain. `scope` is a canned radar picture --
    empty means no radar, so position reports are taken at face value exactly as
    they are on a non-radar field."""
    profile = agent_atc.load_and_push_plate(R.BATUMI_APPROACH)
    ctl = atc.Controller(profile)
    print(f"\n=== dry run: {session_id} ===", flush=True)

    for srs, text in script:
        print(f"\nPILOT [SRS:{srs}]: {text}", flush=True)
        engaged = sep_always or len(ctl.aircraft) >= 2
        directive, stack = (agent_atc.separation_context(ctl, text, scope)
                            if engaged else ("", ""))
        if directive:
            print(f"  CONTROLLER: {directive}", flush=True)
        if stack:
            print(f"  SEPARATION: {stack}", flush=True)

        known = agent_atc.transmitter_callsign(f"guid-{srs}", text)
        parts = [f"TRANSMITTER: the radio calling itself {known}. Same aircraft "
                 f"as every other call from {known} -- keep them together."
                 if known else
                 "TRANSMITTER: a radio you have not identified yet."]
        if directive:
            parts.append("CONTROLLER (deterministic next step of the approach — "
                         "voice its altitudes, headings and sequence exactly, add "
                         f"your radar read, never skip a leg): {directive}")
        if stack:
            parts.append(f"SEPARATION (holding stack, one in the letdown): {stack}")
        parts.append(f"PILOT: {text}")

        t0 = time.monotonic()
        try:
            reply = agent_atc.ask_agent(session_id, "\n".join(parts), "sonnet")
        except Exception as e:
            print(f"  !! agent error: {type(e).__name__}: {e}", flush=True)
            continue
        dt = time.monotonic() - t0
        print(f"  ATC ({dt:.1f}s): {agent_atc.for_voice(reply)}", flush=True)

    print("\n--- controller state ---")
    for cs, ac in sorted(ctl.aircraft.items()):
        alt = f"{ac.assigned_ft} ft" if ac.assigned_ft else "-"
        size = f" x{ac.size}" if ac.is_flight else ""
        print(f"  {cs:10} {ac.phase.name:9} {alt:9}{size}")


if __name__ == "__main__":
    name = "formation"
    if "--script" in sys.argv:
        name = sys.argv[sys.argv.index("--script") + 1]
    stamp = int(time.time())
    run(SCRIPTS[name], session_id=f"dryrun-{name}-{stamp}")
