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
import re
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


def named_no_other_field(mine: str):
    """He named a station, a runway or a frequency belonging to another field.

    THE FAULT THIS ROW EXISTS FOR is a controller claiming the wrong aerodrome
    -- a role is only unique within one, and the wrong answer is always
    plausible. It used to be written as `said("kobuleti clearance")`, which
    demanded he announce his own name in a reply to a pilot who had just used
    it. He does not, a human would not, and a harness that insists on it is
    teaching the controller to be unnatural to stay green.

    So: check for the WRONG field rather than for the right one. Silence about
    which aerodrome you are is correct on a frequency only one of them uses.
    """
    others = ("batumi", "senaki", "kutaisi", "sukhumi", "nellis", "tonopah")
    others = tuple(o for o in others if o != mine.lower())

    def check(ev):
        for e in ev:
            if not str(e.get("kind", "")).startswith("atc/"):
                continue
            text = (e.get("text") or "").lower()
            # A DESTINATION IS NOT A CLAIM. "Cleared to Batumi as filed" names
            # the other field correctly; "Batumi Ground, go ahead" does not.
            for o in others:
                for suffix in ("ground", "tower", "approach", "clearance",
                               "delivery", "departure", "atis"):
                    if f"{o} {suffix}" in text:
                        return False, f"he answered as {o.title()} {suffix.title()}"
        return True, ""
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


# A sentinel the runner replaces with the clearance actually issued. It cannot
# be built when the ladder is composed, because it does not exist until the
# controller has said it.
_READ_BACK = "\x00read-back\x00"


def read_back_of(ev) -> str:
    """What the controller just cleared him to, said back to him.

    The last clearance in the turn, minus the address. Reading back the words
    that were heard is what a pilot does and it is the only version that cannot
    disagree with the clearance -- a composed one has to guess the squawk, which
    is assigned per flight and is different every sortie.
    """
    for e in reversed(ev):
        if str(e.get("kind", "")).startswith("atc/") and "cleared" in (
                e.get("text") or "").lower():
            said = re.sub(r"^\s*\w+[,\s]+", "", e["text"]).strip()
            return said.rstrip(".") + ", Sockeye."
    return ""


def atis_confirmed(field: str):
    """Delivery names the information letter -- IF there is one on the air.

    #96 is "he confirms the letter", and the correct behaviour where no ATIS is
    broadcasting is to say NOTHING rather than invent one. So a field with no
    letter published cannot fail this row; it cannot answer it either, and the
    difference is the whole of "skipped is reported, never silent".

    Nevada's fields do broadcast, but the ATIS stands by while nobody is on the
    server -- which is deliberate, and which made this row fail on a controller
    doing exactly the right thing.

    ASKS ABOUT THIS FIELD, not about any field. The table outlives a theatre
    switch, so a Nevada run found Batumi and Kobuleti still listed as on the air
    from four hours earlier and would have failed Nellis for not naming a letter
    broadcast on another continent. The row is only ever about the aerodrome it
    is standing on.
    """
    def check(ev):
        text = " ".join(e.get("text", "") for e in ev
                        if str(e.get("kind", "")).startswith("atc/")).lower()
        if "information" in text:
            return True, ""
        try:
            import urllib.request
            with urllib.request.urlopen("http://localhost:8000/atis",
                                        timeout=5) as r:
                got = json.loads(r.read().decode("utf-8", "replace"))
            on_air = any(a.get("on_the_air")
                         and (a.get("field") or "").lower() == field.lower()
                         for a in got.get("atis", []))
        except Exception:
            on_air = False
        if not on_air:
            return None, ("nothing is broadcasting, so there is no letter to "
                          "confirm -- saying nothing is correct")
        return False, "an ATIS is on the air and he never named the letter"
    return check


def only_once_he_has_landed(*checks):
    """The recovery rungs, which cannot be judged against a fixture that flew.

    THE ENGINE IS RIGHT TO REFUSE IT. `phases.derive` will not take an aeroplane
    from `departure` to `landed`: you do not land from a take-off roll without
    flying an approach in between, and the refusal is printed. The fixture here
    is parked on a ramp and departs only in words, so it genuinely has not
    landed and the whole recovery half is unreachable from it.

    Saying SKIP is the honest answer. Failing would be scoring the controller
    for refusing to believe a fiction, and passing would be worse. What actually
    covers this ground is `tests/test_ground_procedure.py`, which walks the
    phases directly, plus row F5b -- which needs no landing, because refusing to
    park somebody is Tower's answer whatever rung he is on.
    """
    def check(ev):
        for e in reversed(ev):
            if e.get("kind") != "board":
                continue
            for ac in e.get("board") or []:
                if (ac.get("sortie_phase") or "") in ("landed", "taxi_in"):
                    return all_of(*checks)(ev)
            break
        return None, ("the fixture never flew, so the engine correctly refuses "
                      "to believe it landed -- see tests/test_ground_procedure.py")
    return check


def intent_recorded():
    """What he SAID HE WANTS reached the board.

    Not a phrase in a reply -- a row. `flights.intent` is read by the strip, the
    diag page and `handoff.py`, and until 11 August was written by nothing, so a
    pilot restated his intentions to every controller in turn and none of them
    could see what he had told the last one.
    """
    def check(ev):
        import urllib.parse
        import urllib.request
        try:
            q = urllib.parse.urlencode({"mission": _mission_key()})
            with urllib.request.urlopen(
                    f"http://localhost:8000/flights?{q}", timeout=8) as r:
                rows = json.loads(r.read().decode("utf-8", "replace"))["flights"]
        except Exception as e:
            return None, f"could not read the board ({type(e).__name__})"
        mine = [f for f in rows if (f.get("srs_name") or "").lower() == "sockeye"
                or (f.get("callsign") or "").lower() == "sockeye"]
        if not mine:
            return None, "no row for him yet -- nothing to have written it on"
        got = [f.get("intent") for f in mine if f.get("intent")]
        if got:
            return True, ""
        return False, ("he said what he wanted and the board did not write it "
                       "down")
    return check


def _mission_key() -> str:
    """The sortie the BRIDGE is working, read off its log.

    The harness must ask about the same instance the bridge is writing to, and
    the key is computed from the sim rather than configured -- so it is read
    back rather than recomputed, which is the same rule as everything else here.
    """
    import re
    try:
        with open("/tmp/marshall-bridge-live.log", errors="replace") as fh:
            txt = fh.read()
    except OSError:
        return "default"
    hits = re.findall(r"^\s*sortie: (\S+)", txt, re.M)
    return hits[-1] if hits else "default"


def nobody_after():
    """No handoff was authorised. Ground is the end of the ladder.

    The FAILURE this catches is a rung that hands backwards -- on 11 August
    Ground sent a taxiing pilot to Batumi Tower, a controller who had already
    finished with him. There is nothing after Ground and nobody to hand back to.
    """
    def check(ev):
        for e in ev:
            if e.get("kind") == "atc/handoff":
                return False, f"handed on after parking: {e.get('text', '')[:70]}"
        return True, ""
    return check


def nothing_lost():
    """No decided fact went missing on the way to the radio.

    A REPAIR IS NOT A LOSS. `not_voiced` says the agent's draft dropped a fact
    the engine decided; `repaired` says the bridge put it back before the words
    went out. Both are recorded, and only the pair without a repair is a fact
    the pilot never heard:

        not_voiced  cleared_takeoff: zero seven
        repaired    cleared_takeoff: runway zero seven, cleared for take-off
        ATC         "...Runway zero seven, cleared for take-off."

    which is the mechanism working exactly as designed, reported as a failure
    of the row it was protecting. Matched by KIND -- the two records describe
    the same decision and their texts differ by construction, since one is what
    went missing and the other is what replaced it.
    """
    def check(ev):
        def kinds(k):
            return {str(e.get("text", "")).split(":")[0].strip()
                    for e in ev if e.get("kind") == k}
        lost = kinds("not_voiced") - kinds("repaired")
        return (not lost), f"NOT VOICED and not repaired: {', '.join(sorted(lost))}"
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

def filed_plan(th) -> dict:
    """The theatre's bootstrap plan, off the director. One source, not two.

    The label a pilot asks for and the level he reads back are properties of the
    PLAN, and the plan lives in the database -- which is also where the bridge
    reads it from. Copying them into the harness would be a second copy of a
    fact that already exists, and the rows would go on passing after the plan
    changed underneath them.

    Empty when the director is unreachable; the caller then uses generic
    phrasing, which is honest -- a row that cannot know the number should not
    pretend to check it.
    """
    import urllib.request
    try:
        with urllib.request.urlopen("http://localhost:8000/plans", timeout=8) as r:
            plans = json.loads(r.read().decode("utf-8", "replace"))["plans"]
    except Exception:
        return {}
    return next((p for p in plans if p.get("name") == th.bootstrap_plan), {})


def ladder_for(th):
    """The rungs, spoken at THIS theatre's stations.

    ONE SORTIE, TWO MAPS. Every row was written with Kobuleti's frequencies and
    the word "Kobuleti" in the pilot's mouth, so the harness could only ever
    rehearse the Caucasus -- on a project whose whole recent argument is that a
    role is only unique within an aerodrome and a map is data.

    The rungs themselves are not theatre facts. "Ready to taxi" is ready to taxi
    at Nellis and at Kobuleti; what changes is which button he presses and whose
    name he says, and both come off the station table. So the sortie is written
    once and addressed at whichever field the theatre departs from.

    Runway comes from the wind, the same way the ATIS decides it, because a row
    that names 07 is a Caucasus row wearing a disguise: Nellis with a 210 at 8
    is using 21.
    """
    dep = th.field_named(th.departure)
    rwy = f"{dep.runway_in_use(th.wind_from_deg):02d}"
    spoken_rwy = " ".join(_SPELL[c] for c in rwy)

    def st(role):
        s = next((x for x in th.stations
                  if x.role == role and x.field == dep.name), None)
        return s or next((x for x in th.stations if x.role == role), None)

    clr, gnd, twr = st("clearance"), st("ground"), st("tower")
    plan = filed_plan(th)
    label = plan.get("label") or "the filed plan"
    # THE NUMBERS HE MUST READ BACK, from the plan and the station table. These
    # were "five thousand" and "one two three decimal three" -- Kobuleti's
    # clearance, hardcoded -- so on Nevada the harness read back a level and a
    # frequency belonging to another map. The engine would have refused it,
    # correctly, and the row would have failed for a reason that was the
    # harness's own.
    # A field with no separate Clearance is a real configuration -- the 1944
    # ladder is one man wearing every hat -- so fall back rather than crash.
    clr = clr or gnd
    name = dep.name

    return [
        # HE STATES WHAT HE WANTS, because a real pilot does and because the
        # board is supposed to write it down. On 11 August a pilot said "VFR to
        # Batumi, visual 13" on his first call and at every handoff and nothing
        # recorded it -- so every controller met him for the first time. [#119]
        ("Q1", clr.freq_mhz,
         f"{clr.name}, Sockeye, request clearance, "
         f"{'VFR' if th.name == 'Caucasus' else 'IFR'} to {th.arrival}, "
         f"visual runway {spoken_rwy}.",
         all_of(named_no_other_field(name), intent_recorded()),
         "nothing on this frequency belongs to another field, and what he "
         "wants is written down (#119)"),

        ("Q1a", clr.freq_mhz,
         f"{clr.name}, Sockeye, {label} please.",
         # THE PLAN HE ASKED FOR, proved by its own numbers rather than by the
         # controller repeating its name. He does not say "Redflag, cleared
         # to..." any more than he announces his own station, and a check that
         # demands it teaches him to be unnatural to stay green -- the same
         # mistake Q1 made and the same fix.
         all_of(said("cleared to", plan.get("destination", "").lower()),
                said(_alt_words(plan.get("cruise_ft") or 0))),
         "the clearance is issued from the plan on file"),

        ("Q3b", clr.freq_mhz,
         "Sockeye, say again the information letter.",
         atis_confirmed(name),
         "#96 -- Clearance confirms the ATIS letter"),

        # THE CLEARANCE HE WAS ACTUALLY ISSUED, not one composed here.
        #
        # The squawk was hardcoded `six five two one`. It is assigned per flight
        # at clearance time and Nevada's came out 0742 -- so the harness read
        # back a code nobody had given it, the controller said "negative, three
        # corrections", and the row failed. Correctly. A read-back row that
        # invents the numbers is testing the harness.
        #
        # `_issued` reads them off the recorder after Q1a, which is the only
        # place they exist, and is also what a pilot does: he reads back what he
        # heard.
        ("Q3", clr.freq_mhz, _READ_BACK,
         all_of(handed_to(gnd.name), phase_is("taxi")),
         "a correct read-back ends Delivery's business (#90)"),

        ("Q4", gnd.freq_mhz,
         f"{gnd.name}, Sockeye, ready to taxi.",
         engine_decided("taxi to runway", "hold short"),
         "Ground clears him TO the runway and no further"),

        ("Q5", gnd.freq_mhz,
         f"{gnd.name}, Sockeye, ready for departure.",
         all_of(engine_decided("tower"), said(_freq_words(twr.freq_mhz))),
         "Ground REFUSES the runway and names Tower with the frequency (#65)"),

        ("Q6", gnd.freq_mhz,
         f"{gnd.name}, Sockeye, holding short of runway {spoken_rwy}.",
         all_of(phase_is("holding_short"), handed_to(twr.name)),
         "holding short hands him to Tower (#88)"),

        ("Q7", twr.freq_mhz,
         f"{twr.name}, Sockeye, holding short runway {spoken_rwy}, "
         f"ready for departure.",
         all_of(engine_decided("cleared for take-off"), nothing_lost()),
         "Tower clears it, with the runway and the wind, and all of it is spoken"),

        # THE OTHER END OF THE SORTIE. The ladder was only ever rehearsed
        # outbound, which is why every fault in the recovery half -- Ground
        # handing back to Tower, parking owned by nobody -- was found by a pilot
        # at the end of a flight rather than here in four minutes. [#100]
        #
        # These rows work an aeroplane that is DOWN, so they follow the take-off
        # rather than standing alone: the fixture has to have flown for the
        # engine to believe it landed.
        ("F5", twr.freq_mhz,
         f"{twr.name}, Sockeye, on the ground, runway {spoken_rwy}.",
         only_once_he_has_landed(said("runway")),
         "Tower owns the runway and says to get off it"),

        ("F5b", twr.freq_mhz,
         "Sockeye, request taxi to parking.",
         all_of(said(gnd.name), handed_to(gnd.name)),
         "parking is not Tower's; he names Ground and hands him over (#100)"),

        ("F6", gnd.freq_mhz,
         "Sockeye, request taxi to parking.",
         only_once_he_has_landed(said("parking"), phase_is("taxi_in"),
                                 nobody_after()),
         "Ground parks him, and nothing hands him anywhere (#100)"),
    ]


def _alt_words(ft) -> str:
    """An altitude as a controller says it. 5000 -> five thousand."""
    ft = int(ft)
    if ft % 1000 == 0 and 1000 <= ft < 100000:
        th = ft // 1000
        if th < 10:
            return f"{_SPELL[str(th)]} thousand"
        return " ".join(_SPELL[c] for c in str(th)) + " thousand"
    return " ".join(_SPELL[c] for c in str(ft))


_SPELL = {"0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
          "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "nine"}


def _freq_words(mhz: float) -> str:
    """A frequency as a controller says it, for checking he said it."""
    whole, frac = f"{mhz:.3f}".split(".")
    said = " ".join(_SPELL[c] for c in whole)
    frac = frac.rstrip("0") or "0"
    return said + " decimal " + " ".join(_SPELL[c] for c in frac)


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
    return _spawn(name, "--ground", field, "--heading", "070")


def fly_an_aeroplane(name: str, bearing: float, range_nm: float,
                     alt_ft: int, at: str = "") -> bool:
    """Put a jet in the air, inbound, so there is an ARRIVAL to sequence.

    The ground fixture cannot exercise separation: an aeroplane on the ramp is
    never in the stack, never in the letdown, and never in anybody's way. The
    holding stack is the reason the deterministic engine exists and it has run
    about sixteen times in this project's life, every one of them synthetic --
    so this is the fixture that makes the invariant testable at all.

    Heading is set INBOUND from the spawn bearing, because an arrival flying
    away from the field is not an arrival and `handoff.due` reads the direction.
    """
    # THE THEATRE'S ARRIVAL FIELD by default. This said "BATUMI", so a Nevada
    # run asked the sim to place an arrival against a place that map does not
    # contain -- `unknown place 'BATUMI'; known: NELLIS, TONOPAH` -- and every
    # fixture failed to spawn.
    if not at:
        from marshall.core import theatre as _t
        _th = _t.current()
        at = (_th.arrival or _th.departure or "").upper()
    return _spawn(name, "--at", at, "--bearing", f"{bearing:.0f}",
                  "--range", f"{range_nm:.0f}", "--alt", str(int(alt_ft)),
                  "--heading", f"{int((bearing + 180) % 360):d}")


def _spawn(name: str, *where: str) -> bool:
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "spawn.py"),
         "--name", name, "--type", "viper", "--side", "blue", *where],
        check=False, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 or "FAILED" in out:
        last = out.strip().splitlines()[-1] if out.strip() else str(r.returncode)
        print(f"  !! could not put {name} on the scope: {last}")
        return False
    return True


def take_it_away(name: str) -> None:
    """Leave the scope as we found it. A fixture left behind is traffic in
    somebody else's sortie."""
    from marshall.feed.stubs import bind
    bind()
    import grpc
    from dcs.custom.v0 import custom_pb2, custom_pb2_grpc
    addr = config.DCS_GRPC_ADDR
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


# Spoken digits, as a radio says them and as Whisper writes them down. It does
# not drop them -- it NORMALISES them, and the difference matters:
#
#     said     "holding short of runway zero seven"
#     heard    "Holding Short of Runways 07"
#     said     "maintain five thousand, departure one two three decimal three"
#     heard    "maintained 5,000, Departure 123 Decimal Tree"
#
# Every number arrived. A word-by-word comparison called seven of them missing
# and reported the rows as unjudgeable, which is the harness lying in the
# conservative direction -- better than the other one, and still a lie.
_DIGITS = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3",
           "tree": "3", "four": "4", "fower": "4", "five": "5", "fife": "5",
           "six": "6", "seven": "7", "eight": "8", "nine": "9", "niner": "9"}
_SCALE = {"thousand": "000", "hundred": "00"}


def _words(s: str) -> set:
    """The content of a transmission, for comparing two transcripts.

    Numbers are reduced to their digits and run together, so "zero seven" and
    "07" are the same fact however either end chose to write it. Words shorter
    than three letters go, because "to"/"two" and "for"/"four" are noise at this
    resolution and nothing here turns on them.
    """
    out, run = set(), []
    for w in re.findall(r"[a-z0-9]+", s.lower().replace(",", "")):
        d = _DIGITS.get(w) or _SCALE.get(w) or (w if w.isdigit() else None)
        if d is not None:
            run.append(d)
            continue
        if run:
            out.add("".join(run))
            run = []
        if len(w) > 2:
            # "runway"/"runways", "maintain"/"maintained". Whisper hears the
            # word and writes a different inflection of it; nothing on this
            # radio turns on the ending.
            out.add(re.sub(r"(ed|es|s)$", "", w))
    if run:
        out.add("".join(run))
    return out


def arrived_intact(ev, said_it: str) -> tuple[bool, str]:
    """Did the BRIDGE hear what the pilot actually transmitted?

    THE ROW BEING JUDGED IS THE CONTROLLER'S, and a controller answering a
    mangled transmission correctly must not be marked wrong for it. Measured on
    one run, three of five failures were this:

        said     "Cleared to Batumi as filed, maintain five thousand,
                  departure one two three decimal three, squawk six five two
                  one, Sockeye."
        heard    "Cleared to bow to me as filed, maintain, sockeye."

    against which "that read-back was incomplete" is the RIGHT answer, and the
    harness called it a failure of #90.

    This is the Polly-against-Whisper limit the module docstring has always
    named, and naming it is not enough once the harness is a gate. A row whose
    question did not arrive cannot answer anything, so it reports MISHEARD --
    which is a skip, not a pass, and says which words went missing.

    Two thirds, by content word. Whisper drops a word or hears a name oddly on
    most transmissions and the controller copes with that exactly as a human
    would; the failure worth catching is the half-sentence.
    """
    # `transcript`, not `text`. A pilot record carries what Whisper made of the
    # audio under its own key -- `text` is what a CONTROLLER said -- and reading
    # the wrong one made every row report "nothing reached the bridge" while the
    # controller was visibly answering it.
    heard = " ".join(e.get("transcript", "") for e in ev
                     if e.get("kind") == "pilot")
    if not heard:
        return False, "nothing reached the bridge at all"
    want = _words(said_it)
    if not want:
        return True, ""
    lost = want - _words(heard)
    # EVERY NUMBER HAS TO ARRIVE, whatever the word count says. A dropped
    # adjective is noise; a dropped altitude is the test. Measured: "maintain
    # two four thousand" came back as "main", so the read-back genuinely was
    # missing its level -- the controller said "negative, you missed altitude"
    # and was RIGHT -- and the two lost tokens were under the two-thirds rule,
    # so the harness judged the transmission intact and scored the row against a
    # controller doing his job.
    if any(t.isdigit() for t in lost):
        return False, (f"a number went missing: "
                       f"{', '.join(sorted(t for t in lost if t.isdigit()))}")
    if len(lost) * 3 <= len(want):
        return True, ""
    return False, (f"the bridge heard {len(want) - len(lost)} of {len(want)} "
                   f"words -- missing {', '.join(sorted(lost))}")


def say_it(args, mhz, line, recorder, SRSClient, radio, AM, tts, first=True):
    """Transmit one line and collect the turn. Returns (events, intact, why).

    A FRESH CLIENT PER ROW, because each row is on a different frequency and the
    ladder is the point. `first` only decides whether the line is printed, so a
    repeat does not read like a second row.
    """
    mark = size(recorder)
    if first:
        print(f"   PILOT: {line}")
    client = SRSClient(args.srs, name=args.name,
                       eam_password=config.SRS_EAM_PASSWORD).connect(
        [radio(mhz * 1e6, AM)])
    try:
        client.transmit(tts.Voice(voice_id=args.voice).frames(line),
                        mhz * 1e6, AM)
        # WAIT FOR THE CONTROLLER, NOT FOR THE FILE.
        #
        # This watched the recorder for four seconds of quiet after any growth
        # -- and the pilot's own transmission and the board are written
        # IMMEDIATELY, while the reply is a model call six seconds behind them.
        # So every step ended before the controller spoke and reported him
        # silent. The harness was measuring itself.
        #
        # The step is over when the controller has answered and then gone quiet,
        # which is the same thing a pilot waits for.
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
    intact, why = arrived_intact(ev, line)
    return ev, intact, why


def a_clean_board() -> bool:
    """Restart the bridge, so the ladder starts where a sortie starts.

    THE CONTROLLER REMEMBERS, and that is the design -- the engine holds the
    phase, the assigned level, the approaches flown and whether the clearance
    was read back, because that is a controller's memory and it matters with one
    aeroplane as much as with four.

    It also means the second run of this harness is not the first. Measured:

        PILOT: Kobuleti Clearance, Sockeye, request clearance.
        ATC:   Sockeye, you are already cleared as filed, that clearance was
               read back correct.

    which is a CORRECT answer to a pilot who has already been cleared, and makes
    the row asking whether a clearance gets issued unrepeatable. A gate that
    passes only on a fresh process and fails on the second run is worse than no
    gate: it teaches people that red means "run it again".

    IT TAKES BOTH HALVES, and the first attempt only did one. Restarting the
    bridge empties the in-memory board -- and the CLEARANCE is not there. It is
    a row in the director's `assigned_plans`, which is the point of it being a
    row, so a fresh process read it straight back:

        ATC: Sockeye, Kobuleti Clearance. You're already cleared as filed and
             your read-back was correct.

    `DELETE /flights` is the director's own "forget the last sortie", written
    for exactly this and reachable over the API the bridge already uses.

    `--no-restart` keeps a live session, for watching one row against a sortie
    already in progress.
    """
    import urllib.request
    ok = True
    try:
        req = urllib.request.Request("http://localhost:8000/flights", method="DELETE")
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"  the director forgot the last sortie: "
                  f"{resp.read().decode('utf-8', 'replace')[:60]}")
    except Exception as e:
        ok = False
        print(f"  !! could not clear the director's flights ({type(e).__name__}); "
              "a clearance already on file makes the early rows unrepeatable")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "bridge.py"), "restart"],
                       check=False, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        ok = False
        print("  !! could not restart the bridge; the board carries over from "
              "the last run and the early rows may be unrepeatable")
    return ok


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
    ap.add_argument("--srs", default=config.SRS_HOST,
                    help="the SRS server the bridge is on")
    ap.add_argument("--session", default=os.environ.get("MARSHALL_SESSION", "hooks"),
                    help="the bridge's session id -- names the recorder file")
    ap.add_argument("--voice", default="Joey", help="the synthetic pilot's voice")
    ap.add_argument("--name", default="Sockeye", help="his SRS client name")
    ap.add_argument("--wait", type=float, default=22.0,
                    help="seconds to allow for a reply before calling it silence")
    ap.add_argument("--only", default="", help="run one row, by id")
    ap.add_argument("--field", default="",
                    help="where the fixture aeroplane is parked "
                         "(default: the theatre's departure field)")
    ap.add_argument("--no-spawn", action="store_true",
                    help="use whatever is already on the scope")
    ap.add_argument("--no-restart", action="store_true",
                    help="keep the running bridge, and its memory of this "
                         "callsign, instead of starting from a clean board")
    args = ap.parse_args(argv)
    if not args.srs:
        print("!! --srs is required (or SRS_HOST)", file=sys.stderr)
        return 2

    from marshall.radio import tts
    from marshall.radio.client import AM, SRSClient, radio

    from marshall.core import theatre as _theatre
    th = _theatre.current()
    recorder = config.BUILD_DIR / "logs" / f"flight-{args.session}.jsonl"
    steps = [s for s in ladder_for(th) if not args.only or s[0] == args.only]
    if not steps:
        print(f"!! no row called {args.only}", file=sys.stderr)
        return 2

    print(f"the ladder at {th.departure}, spoken by {args.name} "
          f"against the live bridge")
    print(f"  {th.name}, runway "
          f"{th.field_named(th.departure).runway_in_use(th.wind_from_deg):02d} "
          f"in a {th.wind_from_deg:.0f} at {th.wind_mph:.0f}")
    print(f"  recorder: {recorder}")
    print(f"  {len(steps)} rows\n")

    unit = f"362nd_{args.name}"
    parked = False
    # BEFORE THE AEROPLANE, because the restart is what clears the controller's
    # memory of the last run and the aeroplane is what he forms a new one about.
    if not args.no_restart:
        print("  restarting the bridge so the board starts empty")
        a_clean_board()
    if not args.no_spawn:
        # THE THEATRE'S OWN DEPARTURE FIELD by default. This was the string
        # "KOBULETI", so a Nevada run parked its fixture in Georgia -- on a map
        # that does not contain it -- and every engine-side row skipped.
        where = args.field or th.departure
        print(f"  parking {unit} at {where} so the engine has an aeroplane")
        parked = park_an_aeroplane(unit, where)
        if parked and not wait_for_radar(unit, "http://localhost:8000", args.session):
            print("  !! it never reached the scope; the engine-side rows will skip")
        print()

    results, skipped = [], []
    for rid, mhz, line, check, why in steps:
        print(f"── {rid}  on {mhz:.3f}")
        print(f"   {why}")
        # SAY IT AGAIN IF IT DID NOT ARRIVE. A pilot whose transmission was
        # stepped on repeats it; so does this. One retry, because a second
        # mishearing of the same audio is a fact about the pipeline rather than
        # bad luck, and repeating forever would hide it.
        if line is _READ_BACK:
            line = read_back_of(events_since(recorder, 0)) or (
                "Cleared as filed, Sockeye.")
        for attempt in (1, 2):
            ev, intact, gap = say_it(
                args, mhz, line, recorder, SRSClient, radio, AM, tts,
                first=(attempt == 1))
            if intact or attempt == 2:
                break
            print(f"   MISHEARD ({gap}) -- saying it again")
        for e in ev:
            if str(e.get("kind", "")).startswith("atc/") and e.get("text"):
                print(f"   ATC:   {e['text'][:120]}")
        ok, detail = check(ev) if intact else (None, gap)
        if not intact:
            print("   MISHEARD")
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
    print("\n  NOT COVERED HERE, whatever the result above: the RECOVERY rungs\n"
          "  need an aeroplane that has actually flown -- a parked fixture that\n"
          "  departs in words has not landed, and the engine is right to say so.\n"
          "  Also anything gated on\n"
          "  radar (there is no aeroplane unless one is spawned -- see\n"
          "  tools/ai_traffic.py), and whether a human voice survives Whisper.\n"
          "  This is our Polly against our Whisper.")
    return 1 if any(not ok for _r, ok in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
