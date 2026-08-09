"""Drive the whole ATC brain in text -- the bridge without the radio.

Calls the SAME `assembly.compose_message` the live loop calls -- radar line, SRS
identity, the deterministic CONTROLLER directive, the SEPARATION stack, the
pilot's words -- and POSTs it to the director, but takes typed lines instead of
Whisper and prints the reply instead of speaking it.

"The same", literally, and not "mirrors": this file used to assemble its own
copy and it had already drifted from the bridge it claimed to mirror. A dry run
that shows you something other than what the bridge sends is worse than no dry
run, because you believe it.

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

from marshall.atc import agent_atc, assembly
from marshall.atc import identity, controller as atc
from marshall.core import route as R

# One store for this module -- see agent_atc.Bridge.
_BRIDGE = agent_atc.Bridge()

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

# Clearance delivery from a plan on file (#1). The seam under test is the same
# one as the CONTROLLER line: the tool hands back a finished CRAFT clearance and
# the question is whether the agent VOICES those numbers or improvises around
# them. Watch for the route being shortened, the level rounded, or a squawk that
# is not the one the tool gave -- a clearance a controller made up is an
# aeroplane cleared to an altitude nobody wrote down.
#
# The middle exchange is the one worth reading. "The CAS over Tsutsnvati" fits
# two filed plans, so the correct behaviour is a QUESTION; a controller who
# picks the likelier one sounds decisive and clears him on somebody else's
# sortie.
CLEARANCE = [
    # Card section G, in the order a pilot flies it, so the dry run and the
    # cockpit are testing the same conversation. Two radios, because G9 is two
    # men asking for the same sortie.
    ("Sockeye", "Batumi Ground, Hoover one one, request IFR clearance, Marlin."),
    # G2. Read back what he ACTUALLY said -- the squawk is derived from the
    # flight id and cannot be written into a script, which is the same reason a
    # correct read-back is a thing only a pilot can test. @readback echoes the
    # controller's last transmission, so the path gets exercised here too.
    ("Sockeye", "@readback"),
    ("Sockeye", "Hoover one one, cleared to Batumi as filed, three thousand, "
                "departure one two four decimal zero, squawk four one two six."),
    ("Sockeye", "Hoover one one, request clearance for the weather run out to "
                "Ingress."),
    ("Sockeye", "Hoover one one, request clearance for the CAS over Tsutsnvati."),
    ("Sockeye", "Hoover one one, the beacon letdown one."),
    ("Sockeye", "Hoover one one, request clearance to Vaziani."),
    ("Sockeye", "Hoover one one, request a change, make it Anvil."),
    ("Bandit",  "Batumi Ground, Shooter one one, request clearance, Marlin."),
]

# G1 and G2 alone. A correct read-back must be ANSWERED, and the rule that says
# so competes with the airborne one that says a correct read-back is met with
# silence -- so it is worth being able to run those two exchanges on their own,
# several times, rather than inferring stability from one pass of a ten-row card.
READBACK = CLEARANCE[:2]

# THE NEW TEST BED: a departure from the OTHER field.
#
# Everything above happens at Batumi, which was the only aerodrome when they
# were written. This one is the thing that could not be tested before -- a
# clearance issued by Kobuleti Clearance, for a flight to Batumi, with a
# departure frequency that has to be KOBULETI Departure's 123.300 and not the
# arrival field's. Getting that number wrong is a pilot switching to a
# controller forty miles away and calling into silence.
KOBULETI_DEP = [
    ("Sockeye", "Kobuleti Clearance, Viper one one, request IFR clearance to "
                "Batumi."),
    ("Sockeye", "@readback"),
    ("Sockeye", "Kobuleti Ground, Viper one one, ready to taxi."),
    ("Sockeye", "Kobuleti Departure, Viper one one, airborne, passing one "
                "thousand for five thousand."),
]

SCRIPTS = {"formation": FORMATION, "single": SINGLE, "visual": VISUAL,
           "clearance": CLEARANCE, "readback": READBACK,
           "kobuleti": KOBULETI_DEP}


def run(script, session_id: str, sep_always: bool = True,
        scope: str = "", station: str = "approach", field: str = "") -> None:
    """Drive `script` through the brain. `scope` is a canned radar picture --
    empty means no radar, so position reports are taken at face value exactly as
    they are on a non-radar field."""
    # The SAME profile the live bridge runs. It used to seed the beacon letdown
    # here, which is not merely a different script: `load_and_push_plate` WRITES
    # what it is given, so a dry run replaced the stored radar approach -- and
    # the stored approach is where the controllers and their frequencies live.
    # Every station vanished from the database, and the first thing to notice was
    # a clearance with no departure frequency in it.
    profile = agent_atc.load_and_push_plate(R.BATUMI_ASR)
    ctl = atc.Controller(profile)
    # This run's own state -- see agent_atc.Bridge. It used to reach into the
    # module for the identity registry, which is the singleton [LAYERS.md]
    # step 2 removed.
    bridge = agent_atc.Bridge()
    # Which position is speaking. The live loop derives this from the frequency
    # the transmission arrived on and tells the agent in a YOU ARE line; without
    # it every script is answered by Approach, and a clearance delivery script is
    # then being read by the wrong man.
    # WHICH FIELD'S. A role is only unique within an aerodrome now: ask for
    # "clearance" with no field and you get whichever is listed first, which is
    # Kobuleti's -- so a Batumi clearance script was about to be answered by a
    # controller at the other end of the route, in the right words, with the
    # wrong frequencies in them.
    me = profile.station_for(station, field=field)
    print(f"\n=== dry run: {session_id} ===", flush=True)

    # The plans on file, registered so their spoken names cannot be read as
    # callsigns -- the live bridge does this when it primes the transcriber.
    agent_atc.plan_labels()

    last = ""
    for srs, text in script:
        if text.startswith("@readback"):
            # A read-back is the pilot saying the numbers back. Strip the
            # controller's opening callsign and lead with the pilot's own.
            body = last.split(",", 2)[-1].strip() if last else "say again"
            text = f"Hoover one one, {body}"
        print(f"\nPILOT [SRS:{srs}]: {text}", flush=True)
        # IDENTITY FIRST, then separation -- the order the live loop uses, and
        # the order matters rather than being tidiness. `separation_context`
        # takes the resolved callsign, and called without it the engine refuses
        # the transmission as unidentified: this tool was printing "neither a
        # radio we have identified nor a track on the scope" for a pilot the
        # bridge would have known perfectly well. A mirror that fails where the
        # real thing succeeds is worse than no mirror, because it sends you
        # hunting a bug that is not there.
        #
        # The words are a CLAIM; the ladder decides whether to believe it,
        # preferring the radio-to-track chain that has no microphone in it.
        # See identity.py and [ARCH-2] / #40.
        claim = agent_atc.transmitter_callsign(bridge, f"guid-{srs}", text)
        ident = bridge.identity.resolve(
            f"guid-{srs}", srs, spoken=claim, scope=scope,
            plans=agent_atc.filed_plans(), roster=ctl.identified())
        known = ident.callsign
        if ident.authority != "radar":
            print(f"  IDENTITY: {ident.why}", flush=True)

        # A CALLSIGN NOBODY ANSWERS TO. Same call the live loop makes, and it
        # belongs here for the reason this tool exists: the correction is
        # decided deterministically and VOICED by the agent, which is precisely
        # the two-brain seam a dry run is for. It was wired into `_run_srs` and
        # not into this loop, so the first dry run after building it showed
        # nothing at all and looked like the feature had failed.
        _key = (f"guid-{srs}", (claim or "").lower())
        name_say = ""
        if claim and _key not in bridge.corrected:
            name_say = agent_atc.misnamed(bridge, ctl, claim, known,
                                          identity.handle(ident.track or srs),
                                          said=text)
            if name_say:
                bridge.corrected.add(_key)
                print(f"  CORRECTION: {name_say}", flush=True)

        engaged = sep_always or len(ctl.aircraft) >= 2
        directive, stack = (agent_atc.separation_context(_BRIDGE, ctl, text, scope, known)
                            if engaged else ("", ""))
        if directive:
            print(f"  CONTROLLER: {directive}", flush=True)
        if stack:
            print(f"  SEPARATION: {stack}", flush=True)

        # A flight exists on the board because a radio was heard and bound to a
        # name. The live bridge does this on every transmission, and the tools
        # that work a FLIGHT -- clearance delivery among them -- answer "no
        # flight on the board" without it. Bind the TRANSMITTER only: binding
        # every callsign in the sentence hands one radio to whoever was named
        # last, which is how a pilot ends up filed as his own flight plan.
        if known:
            agent_atc.flight_bind(callsign=known, srs_name=srs,
                                  srs_guid=f"guid-{srs}")
        # THE SAME BLOCKS THE LIVE LOOP BUILDS -- literally the same function
        # now, and that is the whole reason this file is trustworthy.
        #
        # It used to assemble its own copy, with a comment admitting the hazard:
        # every change to `compose_message` had to be made twice or the mirror
        # drifted. It HAD drifted. "the radio calling itself {known}" survived
        # here for weeks after the label stopped coming off the radio, so a dry
        # run was quietly telling you the opposite of what the bridge says --
        # in a tool whose entire purpose is to show you what the bridge says.
        #
        # `assembly.compose_message` takes everything as arguments and fetches
        # nothing, so there is no radio to fake. The blanks below are the things
        # a dry run genuinely does not have: no live handoff, no flight verdict,
        # no talkdown in progress.
        message, _blocks = assembly.compose_message(
            bridge, scope=scope, known=known, transcript=text, profile=profile,
            me=me, fix=None, nxt=None, directive=directive, stack=stack,
            vectoring="", _flight={}, _flight_say="", claim=claim,
            name_say=name_say)

        t0 = time.monotonic()
        try:
            reply = agent_atc.ask_agent(session_id, message, "sonnet")
        except Exception as e:
            print(f"  !! agent error: {type(e).__name__}: {e}", flush=True)
            continue
        dt = time.monotonic() - t0
        # agent=True, because the MODEL wrote this. Without it a reply with no
        # RADIO: marker prints in full here and is SILENCE on the live radio --
        # so the dry run showed four turns of the controller narrating his own
        # reasoning that a pilot would never have heard, and hid the failure
        # that actually matters, which is that he said nothing at all.
        #
        # The same drift as the hand-built message this file used to carry: a
        # tool that shows you something other than what the bridge does is worse
        # than no tool, because you believe it.
        last = agent_atc.for_voice(reply, agent=True)
        print(f"  ATC ({dt:.1f}s): {last}", flush=True)

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
    # WHO ANSWERS EACH SCRIPT, and it is a field as well as a role now.
    #
    # Clearance delivery happens on the ground with nobody in the letdown, so the
    # separation engine has nothing to say and forcing it on would put a holding
    # instruction under a request for a route.
    #
    # Batumi no longer folds delivery onto Tower -- it has its own Ground seat
    # wearing that hat -- so the clearance scripts ask for "clearance" at Batumi
    # rather than for Tower, and get the man who actually issues it.
    on_ground = name in ("clearance", "readback")
    station, field = "approach", R.ARRIVAL_FIELD
    if on_ground:
        station, field = "clearance", R.ARRIVAL_FIELD
    if name == "kobuleti":
        station, field = "clearance", R.DEPARTURE_FIELD
    run(SCRIPTS[name], session_id=f"dryrun-{name}-{stamp}",
        sep_always=not on_ground and name != "kobuleti",
        station=station, field=field)
