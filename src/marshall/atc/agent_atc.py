"""Voice bridge: SRS <-> the Batumi agent. The agent IS the controller brain.

The rigid state machine (fast_atc) could only match five clean intents; a real
pilot doesn't talk that way ("bearing 360, four thousand level, can I get a
DME?"), so it kept re-greeting and lost the thread. This loop hands the raw
transcript to the strands-pg agent instead. The agent knows the plate (soul +
rules), holds one shared session per channel+mission, asks for clarification
when it's lost, and answers in radio phraseology.

    STT (Whisper) -> POST /chat (agent, ~2-4s) -> Polly -> SRS transmit

The agent may NOT invent a level -- its rules pin the assignable altitudes to
the published plate. Separation-critical sequencing across multiple aircraft is
still the deterministic controller's job (exposed to the agent as a tool, later);
for a single ship in the letdown the plate levels are the whole story.

    uv run --extra voice python -m marshall.atc.agent_atc --srs $SRS_HOST 132.0 Matthew
"""

from __future__ import annotations

import dataclasses
from collections import Counter
import json
import os
import pathlib
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from marshall import config
from marshall.atc import identity

BASE_URL = "http://localhost:8000"
AGENT_URL = f"{BASE_URL}/atc"          # two-tier routed turn (tier picks the model)
RADAR_URL = f"{BASE_URL}/radar"
HOOKS_URL = f"{BASE_URL}/hooks/due"
HOOK_POLL_SEC = 2.0

# Two-tier router, kept wired but OFF by default. Everything goes to the smart
# tier -- the radar-aware, fluent "color" the controller is valued for -- because
# Haiku 4.5 doesn't reliably hold the approach sequence even when handed the exact
# clearance. Flip MARSHALL_FAST_TIER=1 to route standard phraseology to the fast
# model (reserved for a future stronger cheap model, or a speak-the-directive fast
# path); a question / odd request / trouble always stays on the smart tier.
FAST_TIER_ON = os.environ.get("MARSHALL_FAST_TIER", "").lower() in ("1", "true", "yes", "on")
# Engage the deterministic separation engine only when there's real traffic (radar
# shows >=2), so a single ship stays pure Sonnet -- radar-aware, fluent, no classify
# on the path. The voice-only rehearsal has no radar tracks, so it forces this on.
SEP_ALWAYS = os.environ.get("MARSHALL_SEP_ALWAYS", "").lower() in ("1", "true", "yes", "on")
_COMPLEX = re.compile(
    r"\?|\bcan i\b|\bcould you\b|\bunable\b|\bhow\b|\bwhy\b|\bwhat\b|\bsay again\b|"
    r"\bproblem\b|\bemergenc|\bmayday\b|\bnot sure\b|\bi need\b|\bhelp\b|\bexplain\b|"
    r"\badvise\b|\bconfus|\bunsure\b|\bdon'?t (?:copy|understand|know)\b", re.I)


def route_tier(transcript: str) -> str:
    if not FAST_TIER_ON:
        return "sonnet"
    return "sonnet" if _COMPLEX.search(transcript or "") else "haiku"


# A note to the log, not to the controller. Saying "debug log, the vectors are
# taking me at the field" during a sortie should record the thought and produce
# SILENCE -- the pilot is talking to the project, not to ATC, and a controller
# who answers has both broken the fiction and buried the note in a reply. Kept
# loose because it arrives through Whisper: "debug log", "debug note", and the
# bare "debug" all count.
_DEBUG = re.compile(r"\b(?:debug|de-bug)\b[\s,:-]*(?:log|note|entry)?\b", re.I)


def debug_note(transcript: str) -> str | None:
    """The note, if this transmission was one. None means it is a real call."""
    m = _DEBUG.search(transcript or "")
    if not m:
        return None
    return (transcript[m.end():].strip(" ,.:-") or transcript.strip())


_CHECK = re.compile(r"radio check|how do you (?:read|copy)|how copy|read you|comm check", re.I)
_CLOSE = re.compile(r"down and stopped|clear of the (?:runway|active)|off the runway|"
                    r"parking|shutting down|clear of active", re.I)


def simple_response(transcript: str) -> str | None:
    """Instant canned reply for the handful of calls where the rich agent adds
    nothing -- a radio check, a closing acknowledgement. Returns None for anything
    with substance, which goes to the agent. Deterministic simple responses inside
    the rich experience, at zero cost/latency."""
    from marshall.atc import intents
    m = re.search(r"\b([A-Za-z]+(?:\s+(?:one|two|three|four|five|six|seven|eight|"
                  r"niner|nine|\d+))+)", transcript, re.I)
    cs = intents.normalize_callsign(m.group(1)) if m else "Station calling"
    if _CHECK.search(transcript):
        return f"{cs}, loud and clear."
    if _CLOSE.search(transcript):
        return f"{cs}, roger, welcome, taxi to parking when ready, good day."
    return None

# When woken by a hook (or asked anything) the agent may decide no call is
# warranted; it replies with this and the bridge stays off the air.
NO_CALL = {"(no call)", "no call", "(none)", "standby."}


def for_voice(text: str, agent: bool = False) -> str:
    """Reduce the agent's reply to the words that actually go over the air.

    Two problems, both seen live:

    * The model narrates. With extended thinking disabled it reasons in the
      OUTPUT instead, and Polly reads every word of it -- a real run transmitted
      "This is a different transmitter, a wingman, reporting his level. He's
      holding, not yet identified individually. Since the flight isn't broken up
      on radar... Pony one two, roger, level four thousand." The pilot hears the
      controller's inner monologue. Telling it not to in the prompt helps and
      does not hold, so the reply carries an explicit RADIO: marker and
      everything before the last one is thinking, not talking.
    * It emits markdown. A radio does not speak asterisks.

    `agent=True` for anything the MODEL wrote, where a missing marker means the
    reply is thinking and must not be heard. Deterministic strings -- the mile
    calls, the canned replies -- carry no marker by design and pass through.
    """
    if "RADIO:" in text:
        text = text.rsplit("RADIO:", 1)[1]
    elif agent:
        # No marker at all, from the AGENT. The reply is malformed and the
        # whole of it is thinking -- which is precisely when the model has
        # decided NOT to speak and written its reasoning instead. Transmitting
        # it read a pilot ten seconds of "his readback was correct, no
        # acknowledgment needed, but I notice he's turning through heading
        # 042... the ASR line contradicts what I just told him" in a
        # controller's voice. Silence is the right answer to a malformed reply:
        # the model meant to say nothing, and saying nothing is free.
        return ""
    text = re.sub(r"[*_`#>]+", "", text)          # emphasis / code / heading marks
    text = re.sub(r"(?m)^\s*[-•]\s+", "", text)    # list bullets
    text = re.sub(r"\s*\n+\s*", " ", text)          # collapse newlines to one line
    return re.sub(r"\s{2,}", " ", text).strip()



def record(session_id: str, **fields) -> None:
    """Append one machine-readable line to the flight recorder.

    The console log already carries the radar picture on every call, but as
    prose and as the WHOLE scope -- which is why diagnosing a bad vector meant
    hand-copying positions out of a transcript into a script. One JSON object
    per transmission makes a sortie replayable: the geometry can be re-run
    against a real flight after a fix, without flying it again.
    """
    try:
        path = config.BUILD_DIR / "logs" / f"flight-{session_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": time.time(), **fields}) + "\n")
    except (OSError, TypeError, ValueError) as e:
        print(f"  !! recorder: {e}", flush=True)     # never cost a transmission


def fetch_radar(session_id: str = "", url: str = RADAR_URL,
                timeout: float = 5.0) -> str:
    """Grab the current scope (tagged with this session's radar-identified
    callsigns) to hand the controller with the pilot's call. Best-effort -- a
    radar hiccup must not eat the transmission."""
    q = f"{url}?{urllib.parse.urlencode({'session_id': session_id})}" if session_id else url
    try:
        with urllib.request.urlopen(q, timeout=timeout) as resp:
            return json.load(resp).get("picture", "").strip()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return ""


def ask_agent(session_id: str, message: str, tier: str = "sonnet",
              url: str = AGENT_URL, timeout: float = 30.0) -> str:
    """POST one transcript to the routed ATC endpoint; `tier` picks the model."""
    body = json.dumps({"session_id": session_id, "message": message,
                       "tier": tier}).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp).get("response", "").strip()


def _put_json(url: str, obj: dict, timeout: float = 6.0) -> None:
    req = urllib.request.Request(url, data=json.dumps(obj).encode(), method="PUT",
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout):
        pass


def _get_json(url: str, timeout: float = 6.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.load(resp)


def _post_json(url: str, obj: dict, timeout: float = 6.0) -> dict:
    req = urllib.request.Request(url, data=json.dumps(obj).encode(), method="POST",
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


# ---- the one aircraft state -------------------------------------------------
#
# Every write here is something a controller and a pilot AGREED. Nothing in this
# section may write a position: that is what the radar is for, and keeping a
# second copy of it is the bug the table exists to kill.
#
# Failures are swallowed on purpose. The state store makes the controller
# better, and it must never make him mute -- an aeroplane on final does not care
# that Postgres is unreachable, and a bridge that raises here would stop talking
# at the worst possible moment.

MISSION = os.environ.get("MARSHALL_MISSION", "default")
APPROACH_NAME = ""              # set when the active flight plan is loaded

# What a mission commander is, as opposed to an air traffic controller. Handed
# to the agent only when it answers on the overlord's frequency, because the two
# jobs share a voice pipeline and nothing else: one owns separation and the
# runway, the other owns the war.
OVERLORD_BRIEF = """OVERLORD ROLE — you are the mission commander, not an air
traffic controller. You do not own runways, approaches, separation or the
holding stack, and you must never issue an approach clearance or vector anyone
onto a final; if a pilot wants to recover, send him to the appropriate
controller.

What you own is the JOB:
- **Tasking.** Give a flight something to do and where: a target area, what is
  believed to be there, and any time on station. Say it the way a controller
  actually would — "armour reported in the town at the north end of the valley,
  two miles east of your present position" — and expect a readback of the
  essentials.
- **The picture.** You have the same radar the controllers do. Use it for
  threat calls, bearing and range to a contact, and to answer "where am I".
- **Never estimate a bearing or a range. Call `vector`.** It computes them
  exactly off the live track cache. Asked how far the field was, one sortie got
  "three miles", "eight miles" and "four miles northwest" within a minute, all
  invented, all confident, from a controller who had the tool and did not
  reach for it. A pilot cannot tell a computed number from a guessed one, which
  is the whole reason the guess is unacceptable. If `vector` cannot resolve
  what he asked for, say so plainly — "no fix for that, call it off your own
  nav" is a good answer and a made-up mile count is not.
- **Check-in and check-out.** A flight checks in with fuel and weapons and you
  acknowledge; when it is done or bingo, you release it and send it home.
- **Honesty about what you do not know.** You know what was reported, not what
  is there. "Reported" and "believed" are the right words for intelligence that
  came from somewhere else.
- **You can actually put something on the ground.** `spawn_ground` places enemy
  units at a bearing and range from a named aerodrome -- armour, trucks,
  infantry, guns. Use it when the frag calls for a target that is not there
  yet, then task the flight onto what you just placed. It reports back what the
  sim ACTUALLY created; if that does not match what you asked for, say so and
  do not send anybody. NEVER describe a target you have not either seen on
  radar or placed yourself: a pilot will fly out and look for it.
- **A pilot may ASK for a target, and the answer is yes.** "Can you give me a
  tank south of the field", "put something in the valley for me" — that is a
  request to place one, not a question about what is already there, and
  refusing it because the area is friendly is the wrong answer. Place it with
  `spawn_ground`, then task him onto it with a bearing and range he can fly:
  "roger, armour on the road two miles south of the field, cleared in hot".
  If the spot is genuinely a bad idea — over the runway, on top of our own
  troops — offer the nearest one that is not, and place it there. The only
  refusal is a target you cannot actually create; say that plainly if the sim
  gives you something other than what you asked for.

Keep transmissions short. You are talking to somebody flying an aeroplane."""

# The separation engine's own phase names, mapped onto the official phase list
# in atc/phases.py. Two vocabularies for one idea is how three components ended
# up disagreeing about what was happening; this is the seam where the older one
# is translated rather than allowed to spread.
_PHASE_OF = {
    "UNKNOWN": "unknown", "ENROUTE": "enroute", "HOLDING": "holding",
    "CLEARED": "approach", "MISSED": "missed", "BANISHED": "holding",
    "LANDED": "landed",
}


def flight_bind(base: str = BASE_URL, **names) -> dict:
    """Attach a name to an aeroplane; create the row if it is the first one."""
    try:
        return _post_json(f"{base}/flights/bind", {"mission": MISSION, **names})
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        print(f"  !! flight bind failed: {e}", flush=True)
        return {}


def flight_agree(flight_id: int, base: str = BASE_URL, **fields) -> dict:
    """Record what was agreed: a clearance, a level, a place in the queue."""
    if not flight_id:
        return {}
    try:
        return _post_json(f"{base}/flights/{flight_id}/agree", fields)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        print(f"  !! flight agree failed: {e}", flush=True)
        return {}


def flight_handoff(flight_id: int, to: str, base: str = BASE_URL) -> dict:
    """Give him to the next controller, with everything we know attached."""
    if not flight_id:
        return {}
    try:
        return _post_json(f"{base}/flights/{flight_id}/handoff", {"to": to})
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        print(f"  !! flight handoff failed: {e}", flush=True)
        return {}


def flight_strip(f: dict) -> str:
    """The row as a controller would read a paper strip.

    This is what a handoff actually delivers, and the reason the table earns its
    place: the next controller starts knowing where he is going and what he was
    cleared to, instead of interrogating a pilot who has already answered.
    """
    if not f:
        return ""
    bits = [f.get("callsign") or "unidentified"]
    if f.get("claimed_size", 1) and f["claimed_size"] > 1:
        bits.append(f"flight of {f['claimed_size']}")
    if f.get("intent") or f.get("destination"):
        bits.append(f"{f.get('intent') or 'inbound'} "
                    f"{f.get('destination') or ''}".strip())
    if f.get("procedure"):
        bits.append(f"on the {f['procedure']}"
                    + (f" runway {f['runway']}" if f.get("runway") else ""))
    if f.get("cleared") and f["cleared"] != "unknown":
        bits.append(f"cleared: {f['cleared']}")
    if f.get("assigned_ft"):
        bits.append(f"assigned {f['assigned_ft']:,} ft")
    if f.get("promised"):
        bits.append(f"we promised: {f['promised']}")
    return "STRIP: " + ", ".join(b for b in bits if b) + "."


def load_and_push_plate(profile, base: str = BASE_URL):
    """Seed this field's approach + a flight plan that flies it from route.py
    (idempotent bootstrap), then generate the plate from the ACTIVE flight plan's
    approach -- the DB is the source of truth, route.py the seed -- and push it as
    the 'plate' prompt part. Returns the profile the ATC should run (the loaded
    flight plan's approach, or the route.py fallback), so the separation Controller
    and the plate share one profile."""
    from marshall.atc import briefing
    from marshall.core import route as R

    try:
        _put_json(f"{base}/approaches/batumi-asr",
                  {"field": profile.beacon.name, "data": R.profile_to_dict(profile)})
        _put_json(f"{base}/flightplans/362nd-batumi-asr",
                  {"callsign": R.FLIGHT_CALLSIGN, "approach": "batumi-asr",
                   "active": True})
        fp = _get_json(f"{base}/flightplan/active")
        if fp.get("approach"):
            # Remember which procedure this is, so a flight's row can say what
            # it was cleared FOR and not merely that it was cleared.
            global APPROACH_NAME
            APPROACH_NAME = fp["approach"].get("name") or APPROACH_NAME
            profile = R.profile_from_dict(fp["approach"]["data"])
            print(f"  loaded flight plan '{fp['name']}' -> approach "
                  f"'{fp['approach']['name']}'", flush=True)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as e:
        print(f"  !! flight-plan bootstrap failed, using route.py: {e}", flush=True)

    try:
        n = push_fixes(base, profile)
        print(f"  pushed {n} named fixes (projected by the sim)", flush=True)
    except Exception as e:      # a fix table is not worth failing to start for
        print(f"  !! fix push failed, controller has the field only: {e}",
              flush=True)

    try:
        _put_json(f"{base}/prompts/plate", {"body": briefing.plate(profile)})
        print(f"  pushed plate for {profile.controller} to the director", flush=True)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"  !! could not push plate: {e}", flush=True)
    return profile


def fetch_due(session_id: str, url: str = HOOKS_URL, timeout: float = 5.0) -> list:
    """Poll the agent for hooks whose timer has expired (each is removed server
    side). Best-effort -- a poll failure just means we try again next tick."""
    q = f"{url}?{urllib.parse.urlencode({'session_id': session_id})}"
    try:
        with urllib.request.urlopen(q, timeout=timeout) as resp:
            return json.load(resp).get("due", [])
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return []


# SRS client GUID -> the callsign that radio has been using. The GUID is the
# only stable, free, per-transmission identity we get, and its VALUE is
# irrelevant -- nobody cares that a radio is registered as "Sockeye". What
# matters is that it is the same radio as last time, so once the controller has
# worked out that this one calls itself Rifle 1-1 (and correlated Rifle 1-1 to
# a radar track), every later transmission from it is Rifle 1-1 even when
# Whisper mangles the callsign or the pilot omits it entirely.
_transmitters: dict[str, str] = {}

# ...and the layer above it, which decides whether that vote is BELIEVED.
#
# `_transmitters` answers "what has this radio called itself", which is still a
# question about words. The registry answers "which aeroplane is this radio
# sitting in", which is a question about the sim, and only accepts the vote when
# a track or a filed strip agrees. See identity.py and [ARCH-2] / #40.
_identity = identity.Registry()


def transmitter_callsign(guid: str | None, transcript: str) -> str:
    """Who this radio is, learning from the transcript when it says so.

    Uses the free offline regex rather than the classifier: this has to work on
    every call, including the single-ship ones where the LLM classifier never
    runs, and getting a callsign out of "Pony one one, level four thousand" does
    not need a model.
    """
    if not guid:
        return ""
    from marshall.atc import callsign
    from marshall.atc.callsign import parse as C_parse
    # By the convention, not by position -- see callsign.speaker_in. Taking the
    # first callsign bound a pilot's radio to the wingman he was calling.
    # The same roster-or-position test that guards the separation stack, applied
    # where a radio is actually BOUND to a name -- and applied to the CANDIDATES,
    # before the speaker convention runs on them. Without it, "request clearance,
    # Samovar Three" bound the pilot's radio to his own flight PLAN: a proper
    # noun with a number after it is indistinguishable from a callsign by shape,
    # the convention says the second name is the speaker, and so the second name
    # won. Everything afterwards came from an aeroplane that had never flown, and
    # the controller spent the exchange asking a man who had said his callsign
    # twice to say it again.
    #
    # Filtering first rather than filtering the answer matters: throwing away an
    # implausible SPEAKER leaves the radio unidentified even though the pilot
    # named himself perfectly well one clause earlier.
    real = [cs for cs in callsign.extract_all(transcript)
            if _plausible_callsign(cs, transcript)]
    heard = real[1] if len(real) > 1 else (real[0] if real else "")
    seen = _transmitters.setdefault(guid, Counter())
    order = _order.setdefault(guid, {})

    # NAMING YOURSELF MORE PRECISELY ALWAYS WINS, IMMEDIATELY.
    #
    # A radio bound to "Pony 1" that says "Pony one one" has not changed its
    # mind, it has become specific: the flight designator covers two aeroplanes
    # and the member names one. Counting votes is right while a callsign is
    # stable and wrong here -- a lead who identified as the flight three times
    # cannot out-vote himself by saying his own callsign once, so he keeps the
    # formation's name after the formation has stopped existing. That is how a
    # pilot ended up being addressed as "Pony 1" while his wingman was "Pony
    # 1-1": adjacent, confusable, and one of them not an aeroplane at all.
    #
    # Independent of whether anyone noticed the break-up, which is the point --
    # it needs no cooperation from the controller, the classifier, or the sim.
    if heard and seen:
        was = max(seen, key=lambda k: (seen[k], order.get(k, 0)))
        w, h = C_parse(was), C_parse(heard)
        if w.is_flight and not h.is_flight and w.flight == h.flight:
            seen.clear()
            order.clear()

    if heard:
        seen[heard] += 1
        order["__n"] = order.get("__n", 0) + 1
        order[heard] = order["__n"]
    if not seen:
        return ""
    # Most often, ties to the newest. A pilot who says a different callsign
    # twice has re-identified; one who says it once against an established
    # binding has probably been misheard. Count alone would freeze the first
    # thing ever heard, recency alone would chase every garble -- together they
    # follow the pilot and ignore the noise.
    return max(seen, key=lambda k: (seen[k], order.get(k, 0)))


# What a radio has called itself, and how often. A COUNT rather than the last
# thing heard, because the last thing heard is whatever Whisper made of a
# gusty transmission -- one Jug bound itself to "Waypoint 3" off a single
# garbled call and then overrode every correct "Hammer one two" that followed,
# which is worse than having no binding at all. Real callsigns repeat; noise
# does not, so the mode is right and gets righter with every transmission.
_order: dict = {}          # per-GUID recency, to break count ties

_SHIPS = re.compile(r"(\d+)\s+ships\b", re.I)


def count_contacts(scope: str) -> int:
    """How many AIRCRAFT the scope is showing, not how many lines it has.

    Radar collapses a formation into one line ("... IN FORMATION with ... — 4
    ships ..."), which is right for the controller to read but wrong to count:
    the bridge engages the deterministic separation engine at two or more
    contacts, so counting lines makes a four-ship look like a single ship and
    switches the engine OFF for the one arrival that most needs sequencing.
    """
    if not scope or scope == "no contacts":
        return 0
    total = 0
    for line in scope.split(" | "):
        m = _SHIPS.search(line)
        total += int(m.group(1)) if m else 1
    return total


def _stack_summary(ctl) -> str:
    """The deterministic holding stack, one aircraft per clause."""
    parts = []
    for cs, ac in sorted(ctl.aircraft.items()):
        alt = f"{ac.assigned_ft} ft" if ac.assigned_ft else "-"
        parts.append(f"{cs} {ac.phase.name.lower()} {alt}")
    return "; ".join(parts)


_RESOLVED = ("LANDED", "BANISHED", "UNKNOWN")

# How far off the beacon a "I am over the beacon" report may be before the scope
# is believed instead. Generous: a Mustang at pattern speed covers a mile in
# fifteen seconds, and the report, the transcription and the radar sample are
# never quite simultaneous.
OVERHEAD_NM = 4.0
_RANGE = re.compile(r"\[([^\]]+)\][^|]*?(\d+(?:\.\d+)?)\s*nm", re.I)


# Groundspeed is optional on the end: the sim gives it, but a picture built
# before the streamer had it -- or a hand-written one in a test -- must still
# parse. A missing speed is 0, which the descent planner reads as "not known"
# and handles by assuming a slow aeroplane.
_FIX = re.compile(
    r"\[([^\]]+)\][^|]*?(\d+(?:\.\d+)?)\s*nm[^|]*?on the (\d+)\s*radial"
    r"[^|]*?([\d,]+)\s*ft(?:[^|]*?heading\s*(\d+))?"
    r"(?:[^|]*?(\d+)\s*knots)?", re.I)


# "362nd_sockeye [Pony 1-1] (P-51D-30-NA): 8.0 nm on the ..." -- the airframe,
# in brackets after the callsign. It is the equipment suffix an IFR flight plan
# would carry, except that the sim states it and no pilot can get it wrong.
_TYPE = re.compile(r"\[([^\]]+)\]\s*\(([^)]+)\)")


def aircraft_type_on_scope(scope: str, cs: str) -> str:
    """What HE is flying, off the radar line. "" when the scope does not say."""
    from marshall.atc import callsign as C
    want = C.parse(cs).flight.lower()
    for tag, typ in _TYPE.findall(scope or ""):
        if C.parse(tag).flight.lower() == want:
            return typ.strip()
    return ""


def true_heading(grid_hdg: float, profile) -> float:
    """A radar heading, out of the sim's grid frame and into true.

    DCS reports an aircraft's heading in its own x/z grid, which is a transverse
    Mercator; the RADIALS in the same radar line come from lat/lon and are true.
    At Batumi they differ by 5.74 degrees, and mixing the two is what drew every
    centreline six degrees off the runway.

    The conversion belongs HERE, where a radar line becomes a Position, and not
    in the geometry. Everything downstream of this point -- `asr.guide`, the
    sweep, the tests -- lives in one frame and should not have to know that a
    simulator has an opinion about north. Putting it in `guide` instead made the
    sweep fly one frame while the engine graded it in another, and the dither
    count went from 1 to 118 in a single run, which is the sound of that
    mistake.
    """
    return (grid_hdg + getattr(profile, "grid_convergence_deg", 0.0)) % 360


def radar_fix(scope: str, cs: str, profile=None) -> object | None:
    """Range, radial, altitude and heading of the track bound to this callsign.

    Only radar-IDENTIFIED contacts (the [tagged] ones) -- guidance computed from
    a blip that might not be him is worse than no guidance, because it sounds
    exactly as confident.
    """
    if not scope or not cs:
        return None
    from marshall.atc import asr, callsign as C
    want = C.parse(cs).flight.lower()
    for tag, nm, radial, alt, hdg, kt in _FIX.findall(scope):
        if C.parse(tag).flight.lower() == want:
            h = float(hdg) if hdg else 0.0
            return asr.Position(float(nm), float(radial),
                                int(alt.replace(",", "")),
                                true_heading(h, profile) if profile else h,
                                speed_kt=float(kt) if kt else 0.0)
    return None


# How often the scope is re-read while somebody is on final. A Mustang at
# pattern speed covers a mile in about fifteen seconds, so four seconds is
# frequent enough to catch each mile boundary without the controller ever
# talking twice about the same one.
ASR_POLL_SEC = 4.0
# A new vector goes out only when the required heading has genuinely moved, and
# never more often than this. Without the first he is corrected by a degree at a
# time; without the second, a turning aircraft is nagged every few seconds while
# it is already doing what was asked.
VECTOR_CHANGE_DEG = 12
VECTOR_MIN_SEC = 20.0


def radar_fixes(scope: str, profile=None) -> list[tuple[str, object]]:
    """Every radar-IDENTIFIED contact as (callsign, Position).

    Untagged blips are deliberately skipped: an unidentified aircraft on final
    is not somebody we can talk to, and guessing produces a confident call to
    the wrong man.
    """
    from marshall.atc import asr
    out = []
    for tag, nm, radial, alt, hdg, kt in _FIX.findall(scope or ""):
        h = float(hdg) if hdg else 0.0
        out.append((tag, asr.Position(float(nm), float(radial),
                                      int(alt.replace(",", "")),
                                      true_heading(h, profile) if profile else h,
                                      speed_kt=float(kt) if kt else 0.0)))
    return out


def spoken_deviation(g) -> str:
    """How far off, not just which side.

    "Left of course" is an assertion a pilot can disagree with, and on a live
    approach he did -- repeatedly, while two and a half miles left of the
    centreline and certain he was lined up. He was not being difficult: from
    the cockpit of a Mustang with no navaid there is nothing to disagree WITH,
    so a bare direction is one man's word against another's.

    A distance ends the argument. "Two miles left of course" is a number he can
    act on, and it tells him the size of the correction as well as its
    direction, which is most of what the call is for.
    """
    if not g.deviation or g.deviation == "on course":
        return g.deviation
    off = abs(g.xtk_nm)
    if off < 0.4:
        return f"slightly {g.deviation}"
    if off < 1.5:
        return f"about a mile {g.deviation}"
    words = ["zero", "one", "two", "three", "four", "five", "six", "seven",
             "eight", "nine"]
    n = round(off)
    return f"{words[n] if n < len(words) else n} miles {g.deviation}"


def relative_correction(g, pos) -> str:
    """"Turn left ten degrees" -- a correction against what he is FLYING.

    Hoover's, and it removes a whole class of error at a stroke:

        "when in the final phases they say left 10 right 5 and don't bother with
         headings... this would avoid all dg drift and mag compass problems"

    An absolute heading is only as good as the gyro he sets it on, and a
    directional gyro DRIFTS -- his read seven degrees off the compass on the
    runway, and the compass read sixteen off the map. Every absolute heading we
    give is computed in true, converted to magnetic, and then flown against an
    instrument that is wrong by an unknown amount.

    A relative correction needs none of that. It is the difference between two
    headings, so every constant frame offset -- grid convergence, magnetic
    variation, a mis-set gyro -- cancels. The controller watches the track on
    radar; the pilot just turns.

    Rounded to five, because "turn left seven degrees" is not something anybody
    flies, and returns "" when there is nothing worth saying.
    """
    from marshall.atc.geometry import angle_diff
    delta = angle_diff(g.heading_true, pos.heading_deg)
    step = int(round(delta / 5.0)) * 5
    if step == 0:
        return ""
    # Words, not digits. Everything here reaches Polly as text and a bare "10"
    # is read out as a digit; a controller says "ten degrees".
    words = {5: "five", 10: "ten", 15: "fifteen", 20: "twenty",
             25: "twenty five", 30: "thirty", 35: "thirty five",
             40: "forty", 45: "forty five"}
    n = min(abs(step), 45)          # more than forty five is a vector, not a nudge
    return f"turn {'right' if step > 0 else 'left'} {words[n]} degrees"


def altitude_instruction(g, profile) -> str:
    """What to SAY about his altitude -- an instruction, not an observation.

        "this is an anticipatory call so I can be there on time rather than a
         reactive call"

    "Altitude should be twelve hundred" describes where he ought to already be.
    By the time he has heard it, started down and got there, he is a mile
    further in and behind the profile again -- permanently chasing it from
    above, which is what "I was always too high" partly was.

    So the call carries the NEXT mile's altitude as an instruction he has a mile
    to fly. "Descend to" when it is a step down, "maintain" when it is not, and
    "minimums" at the bottom rather than an odd number nobody sets on a
    subscale.
    """
    from marshall.atc import controller as ctl
    want = g.descend_to_ft
    if not want:
        return (f", altitude should be {ctl.spell_alt(g.altitude_ft)}"
                if g.altitude_ft else "")
    if want <= profile.mda_ft:
        return ", descend to minimums"
    if g.altitude_ft and want < g.altitude_ft:
        return f", descend to {ctl.spell_alt(want)}"
    return f", maintain {ctl.spell_alt(want)}"


# A talkdown call the AGENT should never have made: a range, or a heading, while
# the engine owns the approach.
_TALKDOWN_WORDS = re.compile(
    r"\b(miles? from the runway|of course|come (?:left|right)|"
    r"turn (?:left|right) heading|fly heading|heading (?:one|two|three|zero|"
    r"four|five|six|seven|eight|niner)\b|descend (?:and maintain |to )|"
    r"altitude should be)", re.I)


# What we last TOLD each aeroplane to fly. Not what we want him to fly now --
# those are different things and confusing them is a bug with a name.
_issued: dict[str, set[str]] = {}
# "one four zero" becomes "1 4 0" once the spoken digits are converted, so the
# number to compare is a RUN of single digits, not a word-bounded integer.
# Matching \b\d{2,4}\b against "heading 1 4 0" finds nothing at all, which is
# how the first version of this quietly never fired.
_DIGIT_RUN = re.compile(r"\d(?:\s*\d){1,3}")


def _callsign_numbers(cs: str) -> set[str]:
    """The digits in his own callsign, in every form they arrive in.

    Stored canonically as "Falcon 1-1", said as "Falcon one one". The hyphen
    form defeats a digit-run match, so the SPOKEN form is what gets compared --
    without this, "Falcon one one, say again" counted as a correct read-back of
    an instruction containing 11.
    """
    from marshall.atc import callsign as C
    try:
        spoken = C.parse(cs).spoken
    except Exception:
        spoken = cs
    return _spoken_numbers(spoken) | _spoken_numbers((cs or "").replace("-", " "))


def _spoken_numbers(said: str) -> set[str]:
    """Every number in a transmission, however it was said.

    "one four zero", "140" and "one forty" all have to come out as 140, because
    a controller says one, a pilot reads back another, and a transcriber writes
    the third.
    """
    from marshall.atc import callsign as C
    text = C._digits(said or "")
    out = {m.group(0).replace(" ", "") for m in _DIGIT_RUN.finditer(text)}
    # An altitude spoken as "two thousand" survives _digits as "2 thousand".
    for n, word in ((1000, "thousand"), (100, "hundred")):
        for m in re.finditer(rf"(\d)\s*{word}", text):
            out.add(str(int(m.group(1)) * n))
    return {o for o in out if len(o) >= 2}


def note_issued(cs: str, said: str) -> None:
    """Remember the numbers in an instruction, so a read-back can be judged
    against what he was ACTUALLY given."""
    if not cs or not said:
        return
    # HIS OWN CALLSIGN IS NOT AN INSTRUCTION. "Falcon one one" carries a 11,
    # and without removing it every transmission he makes "matches" the last
    # thing we said, including "say again".
    got = _spoken_numbers(said) - _callsign_numbers(cs)
    if got:
        _issued[cs] = got


def reads_back_what_we_said(cs: str, transcript: str) -> bool:
    """Is he correctly repeating the last instruction we gave him?

    THE BUG THIS EXISTS FOR, and it is a good one because it makes an aeroplane
    feel at fault when it is not:

        "sometimes he gives me a heading/alt -- say 140 -- then I read back 140
         and he says incorrect, 135. The reason is that he is making an
         aggressive move to get me on track... The result is that it feels like
         I misspoke it when I didn't."

    Exactly right. The engine recomputes continuously, so between issuing 140 and
    hearing the read-back it has moved on to 135 -- and the controller, holding
    the CURRENT directive, answers a perfectly correct read-back with "negative".
    The pilot is told he was wrong about something he got right.

    A read-back is judged against what was SAID TO HIM. If the engine now wants
    something different that is not a correction, it is a NEW instruction, and it
    is spoken as an amendment.
    """
    want = _issued.get(cs)
    if not want or not transcript:
        return False
    return bool(want & (_spoken_numbers(transcript) - _callsign_numbers(cs)))


def hush_a_second_talkdown(reply: str, g) -> tuple[str, str]:
    """Keep the agent OFF the talkdown while the engine is flying it.

    The metronome is transmitting a range, a correction and an altitude every
    mile. The agent kept transmitting its own beside it -- "six miles from the
    runway, mile left of course, come right heading one three zero" -- and the
    brief has told it not to since the day the pilot called it "too chatty on
    final". It does it anyway, and the cost is not merely noise:

    THE AGENT'S CHATTER SUPPRESSES THE ENGINE'S CALLS. The metronome holds its
    transmission while the channel is busy, and by the time the channel clears
    the aeroplane is into the next mile -- so the 6, 5, 4 and 3 mile calls never
    went out at all, and with them the descent instructions for those miles. The
    pilot heard nothing about coming down until two miles:

        "he missed the descent call until the last 900'"

    So it stops being advice. On final the agent may acknowledge and nothing
    else; anything that looks like a talkdown call is replaced with the
    acknowledgement it should have been. Returns (reply, why) so the log can say
    what was taken out rather than silently editing the controller.
    """
    if g is None or getattr(g, "phase", "") not in ("final", "map"):
        return reply, ""
    if not reply or not _TALKDOWN_WORDS.search(reply):
        return reply, ""
    return "", "the engine is flying the talkdown"


def asr_call(cs: str, g, pos=None, profile=None) -> str:
    """The controller's spoken range call. Deterministic on purpose.

    A talk-down is the most rote transmission in aviation -- "six miles from the
    runway, on course" -- and it has to arrive every mile, on time, with the
    right number. Routing that through a model would add a second of latency and
    a chance of drift to a sentence that has no judgement in it at all. The
    agent still handles everything a pilot actually says; this is the metronome
    underneath.
    """
    from marshall.atc import asr, callsign as C, controller as ctl
    who = C.parse(cs).spoken
    rng = asr.spoken_range(g.range_nm)
    # "one miles from the runway" is the sort of thing that is invisible in a
    # diff and unmissable over a radio.
    miles = "mile" if rng.strip() in ("one",) else "miles"
    # Spelled, not printed: "1900" reaches Polly as digits.
    alt = altitude_instruction(g, profile) if profile else (
        f"altitude should be {ctl.spell_alt(g.altitude_ft)}"
        if g.altitude_ft else "")
    if g.phase == "map":
        return (f"{who}, over the missed approach point. Runway in sight, land; "
                f"if not, execute missed approach.")
    if g.off_course:
        # ESTABLISHED: correct him relative to what he is flying. Absolute
        # headings belong to the vectoring phase, where he has time to set a
        # gyro; inside the final approach course they put an instrument we
        # cannot see between the controller and the aeroplane. See #37.
        turn = relative_correction(g, pos) if pos is not None else ""
        if g.phase in ("final", "map") and turn:
            return (f"{who}, {rng} {miles} from the runway, {spoken_deviation(g)}, "
                    f"{turn}{alt}.")
        return (f"{who}, {rng} {miles} from the runway, {spoken_deviation(g)}, "
                f"turn heading {ctl.spell_hdg(g.heading)}{alt}.")
    return (f"{who}, {rng} {miles} from the runway, on course"
            f"{alt}.")


def vector_call(cs: str, g) -> str:
    """An unprompted turn, issued because he has reached the point -- not
    because he said something."""
    from marshall.atc import callsign as C, controller as ctl
    who = C.parse(cs).spoken
    turn = f"turn {g.turn} " if g.turn else "fly "
    alt = f", maintain {ctl.spell_alt(g.altitude_ft)}" if g.altitude_ft else ""
    # Rounded to five while vectoring. A pilot repositioning has to set this on
    # a gyro and read it back, and "one three zero" is easier to do both with
    # than "one two eight" -- which is also how it is issued for real.
    hdg = int(round(g.heading / 5.0)) * 5 % 360
    return f"{who}, {turn}heading {ctl.spell_hdg(hdg)}{alt}."


def asr_context(profile, scope: str, cs: str) -> str:
    """Radar guidance for a vectored approach -- the controller's next call.

    This is what replaces the deterministic engine for a single ship. The engine
    is blind and sequences aircraft against each other; on an ASR with one
    aeroplane there is nothing to sequence, but there is still a procedure to
    fly, and ALL of it is geometry: where he is, how far off the course, what
    heading regains it, when he comes down. None of that needs a classify, so
    the picture costs nothing and a lone pilot stops getting an improvised
    approach.
    """
    from marshall.atc import asr
    if not getattr(profile, "vectored", False):
        return ""
    pos = radar_fix(scope, cs, profile)
    if pos is None:
        return ""
    g = asr.guide(pos, profile)
    rng = asr.spoken_range(g.range_nm)
    if g.phase == "map":
        return ("ASR: he is over the missed approach point. Runway in sight, "
                "land; if not, missed approach now.")
    turn = "" if not g.off_course else f", {spoken_deviation(g)}"
    swing = f" Turn {g.turn}." if g.turn else ""
    if g.phase == "final":
        # The mile calls are already going out automatically, every mile. If the
        # agent ALSO reports range and heading on each transmission the pilot
        # hears the same numbers twice from the same controller -- which is what
        # "too chatty on final" meant. Acknowledge and get off the air.
        return (f"ASR: he is on final, {rng} miles, {spoken_deviation(g)}. The talk-down "
                f"is being transmitted automatically every mile — do NOT repeat "
                f"his range, heading or altitude. Acknowledge what he said in a "
                f"few words and stop.")
    if g.phase == "missed":
        # He has flown the approach and not landed. What he needs is the
        # PUBLISHED missed approach, and he must not be told anything about the
        # final approach course -- he is deliberately leaving it.
        return (f"ASR: he has gone around, {rng} miles. Missed approach: fly "
                f"heading {g.heading:03d}, climb {g.altitude_ft}. Do NOT tell "
                f"him he is off course — he is flying the missed approach and "
                f"is exactly where he should be. Re-sequence him after the "
                f"climb.")
    return (f"ASR: vectoring, {rng} miles{turn}.{swing} Fly heading "
            f"{g.heading:03d}, maintain {g.altitude_ft} until established on the "
            f"final approach course.")


def radar_range_for(scope: str, cs: str) -> float | None:
    """Range from the beacon of the track bound to this callsign, if any.

    Only reads contacts the controller has already radar-identified (the [tagged]
    ones). An unidentified blip near the beacon proves nothing about who is
    talking, and guessing is how you end up rejecting a truthful report.
    """
    if not scope or not cs:
        return None
    from marshall.atc import callsign as C
    want = C.parse(cs).flight.lower()
    for tag, nm in _RANGE.findall(scope):
        if C.parse(tag).flight.lower() == want:
            return float(nm)
    return None


def reconcile(directive: str, stack: str, vectoring: str,
              g=None) -> tuple[str, str, str, str]:
    """Decide which authority owns this aeroplane, and silence the others.

    Three things have an opinion about what happens next. The separation engine
    owns the queue and cannot see. The vectoring owns the geometry and cannot
    remember. The agent owns the words. Until now all three were appended to the
    agent's context side by side, each labelled authoritative, and the agent was
    left to work out which applied.

    It does not work it out. Asked to arbitrate between two confident and
    contradictory instructions, a model says both -- and a pilot established on
    the final approach course at ten miles was told, in one transmission, that
    he was on final AND to climb to five thousand and hold. Neither half was
    wrong about its own job. The bridge was wrong to ask the question.

    So the bridge answers it here, from the geometry, because the geometry is
    the only one of the three that can actually see where he is:

      flying the missed approach   the published missed approach is the whole
                                   instruction. He is deliberately leaving the
                                   final approach course and he is not in the
                                   queue -- a holding clearance now is noise at
                                   the busiest moment of his sortie.

      on the approach              the talk-down owns him. Any holding
                                   instruction is stale by definition: you
                                   cannot both be on final and be waiting to
                                   start. The stack still goes, because it is
                                   about the OTHER aircraft.

      anything else                the separation engine owns him -- hold,
                                   sequence, wait -- and the vector is only how
                                   he reaches the gate. If he has been told to
                                   hold, the vector is suppressed too: two
                                   altitudes in one transmission is how this
                                   started.

    Returns the three parts as they should be used, plus a note of what was
    dropped and why, so a suppression is visible in the log rather than silent.
    """
    if g is None:
        return directive, stack, vectoring, ""
    if g.phase == "missed":
        dropped = "holding/vector suppressed: he is flying the missed approach"
        return "", stack, vectoring, dropped if (directive or stack) else ""
    if g.established or g.phase in ("final", "map"):
        if directive and "hold" in directive.lower():
            return "", stack, vectoring, ("holding clearance suppressed: radar "
                                          "shows him established on the approach")
        return directive, stack, vectoring, ""
    if directive and "hold" in directive.lower():
        return directive, stack, "", ("vector suppressed: he has been told to "
                                      "hold, and two altitudes in one "
                                      "transmission is the bug this prevents")
    return directive, stack, vectoring, ""


# WHO IS FLYING THE PUBLISHED MISSED APPROACH, and has not finished it.
#
# The one thing `asr.guide` cannot work out for itself, so it belongs to this
# side. The procedure commands a two-hundred-degree turn and half way round it
# the aeroplane is on nobody's track -- so every stateless test for it flickers,
# and every flicker is a reversal on the radio. This is what makes him STAY on
# it once the geometry has recognised he started.
_flying_missed: set[str] = set()
_missed_count: dict[str, int] = {}     # go-arounds already seen, per aircraft


def flying_the_missed(cs: str, pos, profile, ctl=None) -> bool:
    """Maintain and read the missed-approach latch for one aircraft.

    Set when the geometry recognises the procedure has begun, or when the pilot
    has SAID he is going around and the controller recorded it -- the two ways a
    controller finds out, and either is enough. Released at the missed approach
    altitude or on leaving the terminal area, because a latch with no release is
    a worse bug than the one it fixes.
    """
    key = ctl._resolve(cs) if ctl is not None else cs
    if (pos.alt_ft >= profile.missed_climb_ft
            or pos.range_nm > profile.final_intercept_nm):
        _flying_missed.discard(key)
        return False
    if ctl is not None:
        ac = ctl.aircraft.get(key)
        if ac is not None:
            # His APPROACH COUNT, not his phase. `report_missed` sets the phase
            # to MISSED and `_try_clear` re-clears him for another attempt in
            # the same breath, so by the time anyone looks he reads as CLEARED
            # again -- correct for sequencing and useless as a signal. The count
            # only ever goes up, and it goes up exactly once per go-around.
            been = _missed_count.get(key, 0)
            if ac.approaches > been:
                _missed_count[key] = ac.approaches
                _flying_missed.add(key)
    return key in _flying_missed


def note_missed(cs: str, phase: str, ctl=None) -> None:
    """The geometry has just handed out the missed approach. Remember it."""
    if phase == "missed":
        _flying_missed.add(ctl._resolve(cs) if ctl is not None else cs)


# HOW LONG A CONVERSATION STAYS OPEN.
#
# Real ATC does not harass a man for his callsign during a quick back and forth
# -- he knows the voice, and demanding identification on every "roger" would be
# its own kind of unrealistic. But "four thousand level" out of a silent
# frequency gets "who is calling level four thousand?", because the controller
# genuinely does not know and will not act on a report he cannot attribute.
#
# Ninety seconds is a readback, a follow-up question and a moment to think. Past
# that he has stopped talking to you and started again.
CONVERSATION_SEC = 90.0
_last_heard: dict[str, float] = {}      # per RADIO, not per callsign


def in_conversation(guid: str, now: float | None = None) -> bool:
    return (now or time.time()) - _last_heard.get(guid, 0.0) < CONVERSATION_SEC


def challenge_for(transcript: str) -> str:
    """"Who is calling ...?" -- quoting back what was actually heard.

    Repeating it matters: it tells the pilot he WAS heard and only the identity
    is missing, which is a different problem from a dead radio and should not
    sound like one.
    """
    said = " ".join((transcript or "").split())[:60].rstrip(" ,.")
    return (f"Station calling {said}, say your callsign." if said
            else "Station calling, say your callsign.")


# Which frequency each aircraft was last heard on. A controller works the men on
# HIS channel, and nobody else -- see `may_be_vectored`.
_heard_on: dict[str, float] = {}


def may_be_vectored(ctl, cs: str, traffic: bool = False,
                    freq_hz: float | None = None) -> bool:
    """May the radar thread turn this aircraft right now?

    The separation invariant, as one question. With a queue, exactly one
    aircraft is being flown and everybody else is holding -- so a vector, which
    IS the invitation to start the approach, may only go to whoever owns it.

    The case that matters, and the one that was wrong: a full stack with nobody
    cleared yet. There the answer is NO for everyone, not YES for everyone. Two
    Mustangs holding at five and six thousand were each told to turn onto the
    intercept and climb to twelve, seconds after being told to hold -- "we have
    duplicate controllers again". They were the same controller, disagreeing
    with itself.
    """
    # TRAFFIC IS WHAT THE SCOPE SEES, not what the stack remembers.
    #
    # Keying this on ctl.aircraft alone left the hole that the fix was meant to
    # close. The blind engine only learns of an aeroplane when somebody says its
    # name on the radio, so a restart empties it -- and the very next radar
    # sweep, with two Mustangs plainly on the scope, found fewer than two
    # aircraft "known" and vectored them both: "Pony one, turn right one eight
    # zero, maintain four thousand five hundred" and "Pony one one, turn left
    # one six nine, maintain one two thousand", seconds apart on one frequency.
    #
    # Radar does not forget over a restart and does not need to be told. If the
    # scope shows two, there is traffic, and queue discipline applies whatever
    # the stack believes.
    # HE HAS TO HAVE ASKED. The radar thread flies approaches; an aeroplane
    # that never requested one is not on one, and the scope cannot tell the
    # difference between an arrival and somebody transiting at four hundred
    # feet on his way to a target. Two Jugs on a CAS sortie, feet wet and
    # outbound, were vectored onto the Batumi final the whole way to their
    # ingress point -- turn right one four nine, turn left three zero zero,
    # turn left two eight eight -- while they were talking to Sentry about
    # something else entirely.
    #
    # Knowing him is the test, because the controller only knows an aeroplane
    # that has spoken to it about arriving.
    if ctl._resolve(cs) not in ctl.aircraft:
        return False

    # Cleared for a VISUAL: he is flying it, not us. Reading ranges to a man
    # looking at the runway is chatter over somebody busy, and it is the
    # difference between a visual approach and a talkdown he did not ask for.
    _ac = ctl.aircraft.get(ctl._resolve(cs))
    if _ac is not None and getattr(_ac, "on_visual", False):
        return False

    # HE HAS TO HAVE CHECKED IN WITH ME, on this frequency.
    #
    # Otherwise Approach starts working an aeroplane the moment Center hands it
    # over -- while the pilot is still reaching for the radio:
    #
    #   "when we got a handoff from center to approach, by the time I switched
    #    over, approach was already half done with the first instruction"
    #
    # He then arrives mid-sentence, has missed a heading and an altitude, and
    # has no way of knowing what he missed. A real controller waits for the
    # check-in; it is what the check-in is FOR.
    if freq_hz is not None:
        was = _heard_on.get(ctl._resolve(cs))
        if was is None or abs(was - freq_hz) > 1000:
            return False

    if len(ctl.aircraft) < 2 and not traffic:
        return True                     # single ship: no queue, no question
    turn = ctl.owns_the_approach()
    if turn is None:
        return False                    # nobody cleared -> nobody vectored
    # Compare ENTITIES, not flight names. Matching on the flight lets a wingman
    # through on his leader's clearance -- "Pony 1-1" and "Pony 1-2" are one
    # flight by name, and the whole point of the break-up is that they are two
    # aeroplanes flying two approaches. Resolving through the controller gets
    # this right in both states: while they are joined both members resolve to
    # the flight, and once broken up each resolves to himself.
    return ctl._resolve(cs) == turn


def separation_context(ctl, transcript: str, scope: str = "",
                       known: str = "") -> tuple[str, str]:
    """The two-brain seam. Advance the deterministic Controller from the call and
    return its authoritative (next-step directive, holding stack).

    The DIRECTIVE is the correct approach sequence for a recognised call (check-in,
    beacon report, landing, ...). It is handed to whichever model voices the reply,
    so even the fast tier just *phrases* the right step instead of guessing it and
    skipping a leg. It is empty for an off-script call the machine doesn't handle
    (a question, a request) -- there the agent reasons freely (and the router will
    have sent that to the smart tier). The STACK is shown only with real traffic."""
    from marshall.atc import bedrock_intent, intents
    from marshall.atc import callsign as C_
    directive = ""
    try:
        intent = bedrock_intent.classify(transcript)

        # ONE RADIO IS ONE AEROPLANE. Whose call this is comes from the GUID
        # that keyed the mic, never from what Whisper made of the words.
        #
        # The transcript is the least reliable thing in the system. In one
        # sortie a single P-47 entered the separation stack as "Hammer 1-1",
        # "Hammer 1-3", "All 4" and "Maintained 2" -- four aeroplanes, three of
        # them imaginary, each with its own place in the queue. With one ship
        # flying that is untidy. With two it is dangerous: the sequencer works
        # whoever owns the approach and holds everybody else, so a ghost at the
        # head of the queue holds two real pilots for an aircraft that does not
        # exist and never will arrive.
        #
        # The GUID arrives free on every transmission and survives any mangling
        # of the words, so where it has told us a callsign before, that is the
        # callsign -- and the classifier's guess is overruled.
        # The classifier is a model, and a model asked "whose call is this?"
        # will answer even when the transcript has no callsign in it. Whisper
        # turned "Pony one two, say my altitude" into "21-2, same by altitude"
        # and the classifier dutifully filed it as an aircraft called 21-2,
        # which took a place in the holding stack behind two real ones.
        #
        # The offline extractor already refuses this -- a callsign needs a NAME
        # -- so hold the model to the same bar. Rejecting leaves him unidentified
        # for one transmission, which costs nothing; accepting invents an
        # aeroplane the controller then sequences.
        if intent.callsign and not _plausible_callsign(intent.callsign, transcript):
            print(f"  .. ignoring '{intent.callsign}' -- that is not a callsign",
                  flush=True)
            intent = dataclasses.replace(intent, callsign=known or "")

        # The same precision rule as the radio binding: if this radio answers to
        # the FLIGHT and the classifier heard a MEMBER of it, the member is more
        # specific and wins. Otherwise a lead who checked in for the formation
        # keeps its name after it has stopped existing, and his own callsign is
        # rejected as a mishearing every time he says it.
        if (known and intent.callsign
                and C_.parse(known).is_flight
                and not C_.parse(intent.callsign).is_flight
                and C_.parse(known).flight == C_.parse(intent.callsign).flight):
            known = intent.callsign

        # ONLY A RADIO MAY BE AN AEROPLANE.
        #
        # This is the rule three ghosts in one evening cost us, and every one of
        # them was a patch to a symptom: "21-2", then "Left 3-8" and "Write 2-5",
        # then "Maintained 2" -- which filed itself as an aircraft, took a
        # clearance for the approach, and had a real pilot held at five thousand
        # behind it. Each time the answer was another word on a denylist, and
        # each time a different sentence got through, because ANY word before a
        # number looks exactly like a callsign and a read-back is made of our own
        # words and numbers.
        #
        # The words were never the right evidence. Every transmission arrives
        # with the SRS GUID of the radio that sent it -- that is not a guess, it
        # is the transport telling us who keyed the mic -- and `known` is the
        # callsign that radio has told us it answers to. So the separation
        # engine hears from RADIOS, never from sentences:
        #
        #   * whatever the classifier thought it heard, the aeroplane is the one
        #     this radio belongs to;
        #   * and if we do not yet know whose radio it is, nothing reaches the
        #     engine at all.
        #
        # The cost of the second half is that an unidentified caller gets no
        # separation until he is identified, which is exactly right: a
        # controller who does not know who is calling asks, and he cannot
        # sequence somebody he cannot name. The cost of the old behaviour was a
        # holding stack with three aeroplanes in it, two of which were sentences.
        if intent.callsign and known and intent.callsign != known:
            print(f"  .. heard '{intent.callsign}', but this radio is {known}",
                  flush=True)
            intent = dataclasses.replace(intent, callsign=known)
        elif intent.callsign and not known:
            # TWO sources count, and neither of them is a sentence: a radio we
            # have bound, or a radar track already tagged with that callsign.
            # Radar is how an aeroplane that has not spoken yet -- or whose
            # first call was garbled -- still gets separated, and dropping that
            # would have been a worse bug than the one being fixed.
            tagged = radar_fix(scope, intent.callsign, ctl.profile) is not None
            if not tagged:
                print(f"  .. '{intent.callsign}' is neither a radio we have "
                      f"identified nor a track on the scope; the engine will "
                      f"not be told about it", flush=True)
                intent = dataclasses.replace(intent, callsign="")

        # The engine is blind: it believes position reports, and it has no way
        # to notice a wrong one. Seen live -- a flight called "over the beacon"
        # at eight miles, the agent correctly refused on radar, but the engine
        # had ALREADY broken the formation up on the strength of the report. The
        # two brains then disagreed about where four aeroplanes were. So when
        # the scope contradicts a claimed station passage, the report never
        # reaches the engine at all.
        # ...but ONLY where there is a beacon to be over. On a radar approach
        # there is none, and the classifier files any ordinary position report
        # as REPORT_BEACON because that is the nearest thing it knows. The
        # result, heard on a live sortie: every single position call the pilot
        # made was answered with "negative, you are not over the beacon",
        # including "on final, runway one three" at two miles. He said the
        # controller seemed confused about where he was. It was contradicting
        # him about a fix that does not exist.
        nm = radar_range_for(scope, intent.callsign)
        beacon_flown = not getattr(ctl.profile, "vectored", False)
        if (beacon_flown and intent.kind is intents.IntentKind.REPORT_BEACON
                and nm is not None and nm > OVERHEAD_NM):
            print(f"  !! rejected: claims the beacon, radar shows {nm:.1f} nm",
                  flush=True)
            return (f"POSITION REJECTED: he reports over the beacon but radar "
                    f"shows him {nm:.0f} miles out. Correct him and have him "
                    f"continue inbound; he has NOT reached the fix.", "")

        # WHAT HE IS FLYING, before the engine decides anything about him.
        # In the real world a controller reads the equipment suffix off the IFR
        # flight plan; here the sim states the airframe on every radar return,
        # which is better -- nobody declares it and no pilot can get it wrong.
        # It decides whether he can be sent to hold at a beacon or has to be
        # given a racetrack in headings and minutes.
        # RADAR CONTACT, or its absence. The blind engine cannot see, and this
        # is the fact everything else on a radar approach depends on -- see
        # Controller.may_be_sequenced. Told on every transmission, so losing him
        # is as visible as finding him.
        if intent.callsign:
            ctl.note_radar_contact(
                intent.callsign,
                radar_fix(scope, intent.callsign, ctl.profile) is not None)

        _typ = aircraft_type_on_scope(scope, intent.callsign)
        if _typ:
            from marshall.atc import equipment as _eq
            ctl.note_equipment(intent.callsign, _eq.receivers(_typ))

        # Seed the blind engine from the scope BEFORE it decides anything. An
        # aircraft radar shows established on the approach must not be filed as
        # a new arrival and stacked -- see Controller.seen_on_final.
        fix = radar_fix(scope, intent.callsign, ctl.profile)
        if fix is not None:
            from marshall.atc import asr as _asr
            g = _asr.guide(fix, ctl.profile,
                           on_missed=flying_the_missed(intent.callsign, fix,
                                                       ctl.profile, ctl))
            if g.established and ctl.seen_on_final(intent.callsign):
                print(f"  .. {intent.callsign} is already on final per radar; "
                      "not stacking him", flush=True)

        # An intent with no callsign never reaches the engine. Belt to the
        # braces above: `dispatch` would otherwise be free to invent a key.
        if intent.callsign and intents.dispatch(ctl, intent):
            directive = " | ".join(tx.text for tx in ctl.out)
            ctl.out.clear()
    except Exception as e:                       # must not break the call
        print(f"  !! controller classify failed: {e}", flush=True)

    # A radar-equipped controller doesn't say "radar not available" -- that's the
    # blind engine's stock phrase; strip it so the agent doesn't parrot it.
    if directive and ctl.profile.atc.radar:
        directive = directive.replace("radar not available, ", "")

    # Stack only when there's a live multi-ship sequence (latched until everyone's
    # resolved, so the last ship's clearance still flows when the one ahead lands).
    resolved = all(a.phase.name in _RESOLVED for a in ctl.aircraft.values())
    stack = _stack_summary(ctl) if (len(ctl.aircraft) >= 2 and not resolved) else ""
    return directive, stack


# What we register as on the SRS roster. The system, not any one controller --
# see the note where the client is built.
SRS_NAME = "Marshall"

# Roster names that are OURS, and must never be mistaken for a pilot.
#
# Marshall is the obvious one. Engineering is the one that cost a sortie: a
# transmit-only radio for talking to a pilot mid-flight, on the same frequency
# because that is where his ears are. The controller heard it, transcribed it,
# and answered -- "station calling, say your callsign" -- and worse, attributed
# a long engineering explanation to Hammer 1-1 and fed it to the model as
# something the pilot had said. A controller arguing with its own maintenance
# channel is indistinguishable, from the cockpit, from a controller losing the
# plot.
OUR_STATIONS = frozenset({SRS_NAME, "Engineering", "Eartest"})
# Engineering is no longer a separate SRS client -- the bridge speaks for it
# in its own voice -- but the name stays here so an older engineer.py left
# running on a frequency is still never mistaken for a pilot.


# --- engineering: getting a human on the line -----------------------------
#
# The most valuable debugging tool of the squadron night was being able to talk
# to the pilot mid-sortie: he reports what the controller just did wrong, the
# fix goes in, he flies it again, all without leaving the aeroplane. That loop
# is worth protecting, and the version that earned it was held together with
# tape -- a separate process, launched by hand, once per frequency, transmit
# only. When the pilot moved from 124 to 118 there was nothing there, and when
# he asked "are you there?" the system had no way to tell him whether the
# channel was even alive. Silence from a dead process and silence from an
# engineer who is heads-down in code look exactly the same from the cockpit.
#
# So the bridge owns it. It is already on every frequency and already
# transcribing, which is the whole cost of the thing.
#
# NO FREQUENCY OF ITS OWN, deliberately: the SCR-522 has four presets and the
# comms ladder uses all four, so a dedicated engineering channel would be one
# the pilot physically cannot tune. It answers wherever it was called.

# ASKING for engineering, in whatever words. Two failure modes, and this sits
# between them.
#
# A fixed list of phrasings is a list of ways to be ignored: of twenty-five
# natural ways to ask, the first pattern missed twelve, and a pilot who is
# ignored has no way of telling that from a dead channel -- the exact bug this
# channel exists to end.
#
# Matching the bare noun is the other ditch. "Engineering said the vectors are
# fixed", said to a controller, is not a request to be transferred, and quietly
# routing it away from ATC is its own kind of not-listening.
#
# So: the word, plus anything that makes it an ADDRESS or a REQUEST. Wide on
# purpose -- being wrong costs one transmission in the log and "back to
# approach" undoes it.
_ENG_CALL = re.compile(
    r"\bengineering\b[\s,]*[?!]"                            # "Engineering?" -- a query
    r"|\bengineering\b.{0,28}?\b(?:on the line|come up|are you|you there|"
    r"you up|you on|you got|check in|checking in|read me|copy|how do you|"
    r"standing by|got a (?:sec|minute|moment)|there\b|available|this is)"
    r"|\b(?:get|need|want|call|raise|reach|ask|talk to|speak to|for|this is)"
    r"\b.{0,20}?\bengineering\b"
    r"|\bengineering\b[\s,]*(?:radio )?check\b"
    r"|\bis engineering\b", re.I)
# Letting him go. The release vocabulary has to be as wide as the summons, and
# it was not: it knew "thanks" and "clear" and did not know GOODBYE, which is the
# most ordinary way in English to end a conversation. Hoover said "goodbye,
# engineering" twice on the ramp and stayed on the channel both times, so his
# next transmission -- a bug report -- went to the engineer instead of the
# controller he thought he was calling.
#
# Being wrong in this direction is cheap: he says it again, or asks for
# engineering back. Being wrong the other way holds a pilot on a channel the
# controller cannot hear him on.
_ENG_FAREWELL = (r"clear|out|thanks|thank you|done|goodbye|good bye|bye|"
                 r"so long|see you|cheers|that.s all|all set|we.re good")
_ENG_DONE = re.compile(
    rf"\bengineering\b.{{0,16}}?\b(?:{_ENG_FAREWELL})\b|"
    rf"\b(?:{_ENG_FAREWELL})[,\s]+engineering\b|"
    r"\bback to (?:approach|tower|center|centre|the controller)\b", re.I)

# Where a human says "I am at the bench". Touched while an engineer is actually
# working; anything older than this is treated as nobody home, because a stale
# claim is worse than an honest "he is not here".
ENG_ATTENDED = config.BUILD_DIR / "engineering.attended"
ENG_ATTENDED_SEC = 45 * 60
ENG_SPOOL = "/tmp/marshall-say"


def engineering_attended() -> bool:
    try:
        return (time.time() - ENG_ATTENDED.stat().st_mtime) < ENG_ATTENDED_SEC
    except OSError:
        return False


def engineering_ack(summoned: bool) -> str:
    """What the pilot hears the moment he calls, before any human is involved.

    Deterministic and instant on purpose. The failure this exists to prevent is
    a pilot transmitting into what he thinks is a live channel and getting
    nothing back -- "I tried talking to you, no response" -- with no way to tell
    a broken radio from a busy engineer. Either answer is fine; not knowing is
    not.
    """
    if not summoned:
        return "Copied, logged."
    if engineering_attended():
        return ("Engineering is up, go ahead. I am reading your notes as you "
                "make them.")
    return ("Engineering is not at the bench right now. Keep talking, every "
            "word is recorded and he will read it.")



# --- one bridge at a time ------------------------------------------------

BRIDGE_LOCK = config.BUILD_DIR / "bridge.lock"
_lock_fd = None                      # held open for the life of the process


def claim_the_frequency(path=None) -> bool:
    """Take the bridge lock, or refuse to start. Returns False if taken.

    Two bridges on one frequency is the most expensive failure this system has,
    and it is trivially easy to cause: killing the `uv run` launcher does not
    kill the python child, so "restart the bridge" quietly leaves the old one
    logged into SRS. Both then hear the pilot, both answer, and each hears the
    other's reply as a pilot call. On squadron night it happened twice and was
    reported both times as "duplicate controllers" -- the two had separate
    holding stacks and separate conversations, so one believed a pilot was
    inbound while the other believed he was outbound, and both were fluent.

    An advisory flock, not a PID file. The kernel releases it when the process
    dies however it dies, so a crash or a kill -9 cannot leave a stale lock that
    stops the next start -- which would swap one failure for a worse one.
    """
    global _lock_fd
    import fcntl

    path = pathlib.Path(path) if path else BRIDGE_LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    # Deliberately NOT a context manager: the handle is held for the life of
    # the process, because closing it releases the lock. That is the whole
    # mechanism.
    fd = open(path, "a+")  # noqa: SIM115
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fd.seek(0)
        who = fd.read().strip() or "unknown"
        fd.close()
        print(f"!! another bridge already holds the frequency (pid {who}).\n"
              f"   Two controllers on one channel is the bug this prevents.\n"
              f"   Stop it first:  kill {who}", flush=True)
        return False
    fd.seek(0)
    fd.truncate()
    fd.write(str(os.getpid()))
    fd.flush()
    _lock_fd = fd            # keep the handle; closing it drops the lock
    return True


def leaving_my_airspace(base: str, session_id: str, callsign: str, me,
                        profile, fix, mission: str = "default") -> object | None:
    """The station he should be with now, if he has flown out of mine.

    ONLY the outbound direction, deliberately. Arrivals are sequenced by
    route.py's rules, which are tested and which encode the one exception that
    matters -- a talkdown keeps him to the missed approach point -- and airspace
    must not get a second vote on that. What airspace adds is the case range
    cannot express at all:

        "georgia center handed us off the approach oftly early... should have
         given us vectors and kept us with him until we left his airspace"

    Range does not know whether he is arriving or departing, so a flight leaving
    Batumi on a CAS sortie was given to Approach at 25 miles and then never
    handed back, because leaving resolved to nobody. It does now.
    """
    # A talkdown in progress outranks any question of geography. Tower's volume
    # has a 4,000 ft ceiling, so an aircraft descending the final sits inside it
    # -- and handing him over there is precisely the bug that took a pilot off
    # the frequency that was flying his approach.
    if (getattr(me, "role", "") == "approach"
            and getattr(profile, "guidance", "") == "talkdown"
            and fix is not None
            and fix.range_nm <= profile.final_intercept_nm):
        return None
    try:
        row = _get_json(f"{base}/flights/airspace?"
                        + urllib.parse.urlencode({"callsign": callsign,
                                                  "mission": mission}))
    except Exception:
        return None                    # airspace is an improvement, not a crutch
    want = (row or {}).get("should_be_with") or ""
    if not want:
        return None
    role = want.rsplit("-", 1)[-1]     # 'georgia-center' -> 'center'
    if role == getattr(me, "role", ""):
        return None                    # he is where he should be
    nxt = (profile.station_for(role)
           if hasattr(profile, "station_for") else None)
    # Outbound only: hand him DOWN the ladder (approach -> center), never up.
    # Climbing the ladder is an arrival, and arrivals belong to route.py.
    order = {"center": 0, "approach": 1, "tower": 2}
    if (nxt is None
            or order.get(role, 9) >= order.get(getattr(me, "role", ""), 9)):
        return None
    return nxt


def handoff_phrase(nxt, fix) -> str:
    """Hand him over, whether or not we have a radar fix of our own.

    `fix` is optional and that is the entire point of this function existing.
    An airspace handoff is answered from the PostGIS view, which needs no fix --
    and the range in the sentence is decoration. Reading it unconditionally
    crashed the bridge DEAD on a live rehearsal: a flight whose radar label had
    not yet been bound to its callsign produced a handoff with no fix, and the
    process went down mid-sortie, silent, with pilots on the frequency.

    No phrase should be able to do that. Wording is the least important thing
    here and it took down the most important one.
    """
    from marshall.atc import controller
    where = (f"he is {fix.range_nm:.0f} miles out and past your boundary"
             if fix is not None else "he has left your airspace")
    return (f"HANDOFF: {where} — hand him to {nxt.name} on "
            f"{controller.spell_freq(nxt.freq_mhz)} and say goodbye.")


def addressed_to_another_aircraft(transcript: str, speaker: str,
                                  stations=()) -> str:
    """Whose name this call opens with, if it is somebody else's aeroplane.

    Real ATC assumes a pilot is talking to it -- which is why nobody says
    "Omaha Approach" on every transmission, and why ours answers everything on
    its frequency. But two aircraft occasionally talk to each other on it:

        "Pony one two, Pony one one, join up"

    A controller hears that, understands it is not his, and says nothing. The
    giveaway is the ADDRESSEE, and it is readable: a transmission opening with
    an aircraft callsign that is not the speaker's own is ship-to-ship. Opening
    with a station name, or with his own callsign, or with nothing, is a call to
    the controller exactly as before.

    Returns the addressee, or "" when the call is ours. Refuses to decide
    without knowing who is speaking: guessing that a transmission is not for us
    is worse than answering one that was not, because the pilot gets silence and
    no way to tell why.
    """
    from marshall.atc import callsign as C

    if not speaker or not transcript:
        return ""
    head = transcript.strip()[:44]
    for name in stations:                    # "Batumi Approach, ..." is ours
        if name and name.lower() in head.lower():
            return ""
    first = C.extract(head)
    if not first or not _plausible_callsign(first):
        return ""
    if C.parse(first).flight == C.parse(speaker).flight \
            and C.parse(first).canonical == C.parse(speaker).canonical:
        return ""                            # his own name: talking to us
    return first


# Names that are allowed to become an aeroplane on the strength of one
# transmission: the mission roster, plus anyone named on the command line.
# Everything else has to earn it -- see `_plausible_callsign`.
_heard_names: dict[str, int] = {}


def known_flight_names() -> set[str]:
    from marshall.core import route as R
    out = {n.lower() for n in getattr(R, "SQUADRON_CALLSIGNS", ())}
    out |= {n.strip().lower()
            for n in os.environ.get("MARSHALL_CALLSIGNS", "").split(",")
            if n.strip()}
    return out


# The channel the last transmission was on. A one-element list because it is
# written from the pilot thread and read from the scheduler thread, and a bare
# module global rebound in a closure is the kind of thing that works until
# somebody adds a `global` and it does not.
_last_active_hz: list[float | None] = [None]


# What the controller last said, and who is owed an answer to a read-back.
#
# An IFR clearance is the one transmission on the whole frequency that MUST be
# read back and MUST be answered. Getting that right was left to the brief, and
# the brief lost: "readback correct" competes with the airborne rule that a good
# read-back is met with silence, and the airborne rule won often enough that
# Hoover read a clearance back on the ramp, got nothing, and had to ask "did you
# hear my read back?" -- after which he was told it was correct.
#
# So it stops being a matter of judgement. The bridge SEES the clearance go out,
# knows the next thing that pilot says is his read-back, and says so.
_last_said: list[str] = [""]
_awaiting_readback: dict[str, float] = {}

# How long a clearance stays outstanding. Long enough for a pilot to write five
# elements down and read them back; short enough that it is not still armed when
# he calls for taxi three minutes later.
READBACK_WINDOW_SEC = 150


def is_a_clearance(said: str) -> bool:
    """Did we just issue an IFR clearance? Read off the words, because that is
    what a clearance IS -- there is no other transmission on this frequency that
    carries a squawk and a routing together."""
    low = (said or "").lower()
    return "squawk" in low and ("cleared to" in low or "as filed" in low)


def readback_due(callsign: str, now: float | None = None) -> bool:
    """Is this transmission the read-back of a clearance we just gave him?"""
    when = _awaiting_readback.get(callsign)
    if when is None:
        return False
    return ((now if now is not None else time.time()) - when) <= READBACK_WINDOW_SEC


def hook_frequency(why: str, heard_on: dict, last_hz: float | None) -> float | None:
    """Which channel a promised callback is spoken on.

    A5, live: Hoover asked Georgia Center on 139 for a call in sixty seconds.
    The hook fired on time and the controller said "calling as requested" -- on
    124, the frequency the bridge happened to be started on. He waited eighty
    seconds on 139 and reported no callback, which from the cockpit is
    indistinguishable from a hook that never fired.

    So the frequency comes from the man it is owed to. The hook's own reason
    names him ("Call back Pony 1-1 as he requested on Georgia Center 139.0"), and
    the bridge already knows which channel it last heard that callsign on.
    Failing that, the last channel anybody spoke on -- a hook whose reason names
    nobody still has to be spoken where somebody is listening. Failing that,
    None, and the caller falls back to its own default.
    """
    from marshall.atc import callsign as C

    for cs in C.extract_all(why or ""):
        if cs in heard_on:
            return heard_on[cs]
    return last_hz


def _plausible_callsign(cs: str, said: str = "") -> bool:
    """May this name become an aeroplane the controller sequences?

    A name and a number is not enough, and six ghosts proved it: 21-2, Have 2,
    Waypoint 3, Need 3, Transmission 2, Busy 4. Each was fixed by adding a word
    to a denylist, which cannot converge -- any English word in front of a digit
    is a candidate, and one of those fixes CREATED the next ghost.

    Two things are enumerable where English words are not.

    The ROSTER: route.py knows the squadron and the command line adds visitors,
    so those names are aeroplanes on sight.

    And POSITION. A callsign opens a transmission -- "Hoover one one, request
    the approach", or "Batumi Approach, Hoover one one" after a station. Noise
    sits in the middle of a sentence: "I am going to be busy for a minute", "I
    have two aircraft in sight", "a deliberately long transmission to hold the
    frequency". Every ghost this project has produced was mid-sentence and every
    real callsign was in the first few words, which is not a coincidence -- it
    is how radio works.

    Repetition was tried first and is weaker: the same mis-hearing repeats
    happily if the pilot says the same phrase twice.

    The cost of being wrong is one transmission answered as "station calling".
    The cost of the old behaviour was a ghost at the head of a holding stack
    with real aeroplanes queued behind it.
    """
    from marshall.atc import callsign as C
    flight = C.parse(cs).flight
    name = flight.split()[0] if flight else ""
    if len(name) < 3 or not name.isalpha():
        return False
    if name.lower() in known_flight_names():
        return True
    if not said:
        return True          # no transcript to judge by; do not block on nothing
    # AT THE START OR AT THE END, because those are the two places radio
    # procedure puts a callsign:
    #
    #     "Batumi Approach, Falcon one one, request..."   addressing
    #     "Left zero nine zero, Falcon one one"           reading back
    #
    # Only the first was accepted, and the omission was doing real damage in
    # both directions. A pilot's own callsign at the end of a read-back was
    # rejected as noise -- so the aeroplane vanished from the board every time
    # he did the correct thing -- while our own words at the START of that same
    # read-back sat exactly where a callsign was expected and were let through.
    # The rule was precisely backwards for the commonest transmission there is.
    #
    # Three words at each end. "Batumi Approach, Hoover one one" puts a real
    # callsign third and that is the longest legitimate run-up; a fourth lets
    # "give me a minute two sort this out" in as "Minute 2".
    words = said.split()
    edges = " ".join(words[:3] + words[-3:]).lower()
    return name.lower() in edges


_plan_labels: list[str] = []


def plan_labels(url: str = f"{BASE_URL}/plans") -> list[str]:
    """The spoken names of the plans on file, for priming the transcriber.

    Cached after the first success and never re-fetched on failure, because this
    runs inside the transcribe path: a director that is slow to answer must cost
    a plan name, not a transmission.
    """
    if _plan_labels:
        return _plan_labels
    try:
        for p in _get_json(url, timeout=3.0).get("plans") or []:
            if p.get("label"):
                _plan_labels.append(p["label"])
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        pass
    if _plan_labels:
        # And the same list keeps them from becoming aeroplanes. "Samovar Three"
        # is a callsign by shape -- an ordinary word with a number after it --
        # and only knowing the names we assigned ourselves can say otherwise.
        from marshall.atc import callsign as C
        C.these_are_not_aircraft(_plan_labels)
    return _plan_labels


# WHO HAS A STRIP. The second authority on identity, and the only one a
# procedural controller has -- see identity.py.
#
# Not `plan_labels`, which was the near-miss: those are ROUTE names ("Samovar
# Three") and the same function goes on to register them as explicitly NOT
# aircraft. What is wanted here is the callsigns of flights on the board, which
# were typed before the sortie and so cannot be mis-heard.
_filed: dict[str, object] = {"at": 0.0, "names": []}
FILED_TTL_SEC = 45.0            # pilots bind mid-session; a strip is not static


def filed_plans(url: str = f"{BASE_URL}/flights", now: float | None = None) -> list[str]:
    """Callsigns with a flight on the board. Never costs a transmission."""
    t = time.time() if now is None else now
    if t - float(_filed["at"]) < FILED_TTL_SEC:
        return list(_filed["names"])          # type: ignore[arg-type]
    _filed["at"] = t
    try:
        got = [f.get("callsign") for f in _get_json(url, timeout=2.5).get("flights") or []]
        _filed["names"] = [c for c in got if c]
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        pass                                   # keep the last good list
    return list(_filed["names"])               # type: ignore[arg-type]


def whisper_vocabulary(profile) -> str:
    """The priming text for the transcriber, from what is actually on the air.

    Rebuilt as radios identify themselves, because the callsigns are the half
    that cannot be known in advance and are also the half that does the damage
    when it is wrong -- a mangled callsign does not merely mis-transcribe a
    word, it invents an aeroplane and gives it a place in the holding stack.
    """
    from marshall.atc import callsign as C
    from marshall.core import route as R
    from marshall.srs import stt

    # Seed with who COULD be flying before anyone has spoken, plus anybody
    # named on the command line -- a visiting pilot or a test callsign. Without
    # this the very first transmission, which is the one that binds a radio to a
    # name, is the only one with no priming behind it.
    spoken = list(getattr(R, "SQUADRON_CALLSIGNS", ()))
    spoken += [c for c in os.environ.get("MARSHALL_CALLSIGNS", "").split(",")
               if c.strip()]
    for seen in _transmitters.values():
        for cs in seen:
            try:
                spoken.append(C.parse(cs).spoken)
            except Exception:
                spoken.append(cs)
    stations = [s.name for s in (getattr(profile, "stations", None) or [])]
    fixes = [f.name for _, f in R.sortie_points()]
    field = getattr(getattr(profile, "beacon", None), "name", "Batumi")
    return stt.domain_prompt(stations, fixes, spoken, field, plan_labels())


def push_fixes(base: str, profile) -> int:
    """Project route.py's fixes with the SIM's own converter and push them.

    The controller must never estimate a bearing or a range, so it needs a fix
    table it can compute against -- and the director cannot build one, because
    it holds lat/lon while route.py holds DCS metres and the two containers do
    not share code.

    The projection is the sim's, not ours, and that is not fussiness. Caucasus
    is a transverse Mercator; a flat-earth offset from the field was measured
    against `coord.LOtoLL` and came out 1.2 miles wrong at the coast and 7.6
    miles wrong at the target area. A controller confidently seven miles out is
    worse than one who says he does not know.

    Best effort by design. If the sim is not up, or gRPC is not reachable, the
    table keeps only the field, `vector` answers "no fix for that", and the
    approach -- which needs none of this -- carries on unaffected.
    """
    import sys
    from pathlib import Path as _Path
    from marshall.core import route as R

    # The generated DCS-gRPC stubs live beside the director and are not a
    # package this process imports normally. pydcs also claims the name `dcs`,
    # and a regular package shuts the namespace search down -- so the stub tree
    # has to be bound before anything touches it. Same dance as the tools.
    _root = _Path(__file__).resolve().parents[3]
    _stubs = _root / "director" / "_grpc"
    if str(_stubs) not in sys.path:
        sys.path.insert(0, str(_stubs))
    if "dcs" not in sys.modules or not hasattr(sys.modules["dcs"], "__path__"):
        import types as _types
        _pkg = _types.ModuleType("dcs")
        _pkg.__path__ = [str(_stubs / "dcs")]
        sys.modules["dcs"] = _pkg

    # EVERY fix route.py publishes, not only the ones on tonight's sortie. A
    # filed flight plan may route via any of them -- a ferry up the coast goes to
    # KOBULETI, which no sortie leg touches -- and a plan naming a fix the table
    # does not hold is refused at clearance delivery. The rule is the simple one:
    # if route.py publishes it as a Fix, the controller can compute against it.
    fixes = {f.name: f for f in vars(R).values() if isinstance(f, R.Fix)}
    fixes.update({f.name: f for _, f in R.sortie_points()})
    for attr in ("beacon", "outer_hold", "arrival_fix"):
        f = getattr(profile, attr, None)
        if f is not None and getattr(f, "name", None):
            fixes.setdefault(f.name, f)
    if not fixes:
        return 0
    lua = "local o = {} "
    for name, f in fixes.items():
        lua += (f'do local la, lo = coord.LOtoLL({{x = {f.x}, y = 0, z = {f.z}}}) '
                f'o[#o+1] = string.format("%s|%.6f|%.6f", "{name}", la, lo) end ')
    lua += 'return table.concat(o, ";")'

    from dcs.custom.v0 import custom_pb2, custom_pb2_grpc
    import grpc
    addr = os.environ.get("DCS_GRPC_ADDR", "127.0.0.1:50051")
    with grpc.insecure_channel(addr) as ch:
        raw = str(custom_pb2_grpc.CustomServiceStub(ch).Eval(
            custom_pb2.EvalRequest(lua=lua), timeout=30).json).strip('"')

    out = {}
    for rec in raw.split(";"):
        if rec.count("|") == 2:
            name, la, lo = rec.split("|")
            out[name] = [float(la), float(lo)]
            # Steerpoint NUMBERS too -- "distance to waypoint three" is how a
            # pilot asks, and the name is what the chart shows.
    for n, f in R.sortie_points():
        if f.name in out:
            out[f"waypoint {n}"] = out[f.name]
            out[f"steerpoint {n}"] = out[f.name]
    _put_json(f"{base}/fixes", {"fixes": out})
    return len(out)


def _run_srs(host: str, freq_mhz: float, voice_id: str = "Matthew",
             session_id: str | None = None, url: str = AGENT_URL) -> None:
    from marshall.atc import asr, controller
    from marshall.core import route as R
    from marshall.srs import stt, tts
    from marshall.srs.client import AM, SRSClient, radio

    freq_hz = freq_mhz * 1_000_000
    session_id = session_id or f"batumi-approach:{freq_mhz:.3f}"
    profile = load_and_push_plate(R.BATUMI_ASR)       # DB is the source of truth
    radar_on = profile.atc.radar          # a no-radar mission works purely procedural
    # One voice per controller. Changing frequency should sound like meeting a
    # different person -- that is most of what makes a sector split feel real,
    # and it costs nothing but picking the right Voice before transmitting.
    voice = tts.Voice(voice_id=voice_id)
    voices: dict[float, tts.Voice] = {}
    for _s in getattr(profile, "stations", None) or []:
        voices[round(_s.freq_mhz, 3)] = tts.Voice(voice_id=_s.voice)

    def voice_for(hz: float | None):
        """The voice of whoever owns this channel, falling back to the default."""
        return voices.get(round((hz or freq_hz) / 1_000_000, 3), voice)
    model = stt.load_model()
    # Monitor EVERY channel this approach uses, not just one. A WW2 set has
    # four presets and the ARA-8 homes on whatever it is tuned to, so the pilot
    # is always listening on the beacon he is currently flying -- enroute that is
    # the arrival fix, in the letdown it is the approach beacon, and a banished
    # aircraft is out at the outer hold. A controller sitting on one frequency
    # is simply not audible for two thirds of the arrival.
    # Where the controllers actually are. On a vectored approach that is the
    # STATION list -- Center, Approach, Tower -- and deriving it from the beacon
    # fixes instead put the controller on 132 and 124 while the pilot's radio
    # card said 119, 120 and 131: two of the three channels on his kneeboard had
    # nobody on them, and the failure is silent from both ends. He calls into an
    # empty frequency; we hear nothing and assume he has not called.
    channels: list[float] = []
    if getattr(profile, "stations", None):
        channels = [s.freq_mhz for s in profile.stations if s.freq_mhz]
    else:
        for fix in (profile.arrival_fix, profile.beacon, profile.outer_hold):
            if fix is not None and fix.freq_mhz and fix.freq_mhz not in channels:
                channels.append(fix.freq_mhz)
    if freq_mhz not in channels:
        channels.insert(0, freq_mhz)
    # One SRS client, several controllers. It used to register under
    # profile.controller -- "Batumi Approach" -- which is a lie on any frequency
    # but one: the same client is also Georgia Center on 139 and Batumi Tower on
    # 118, and a listener watching the roster sees one of the three claiming to
    # be all of them. SRS_NAME is the SERVICE; who is speaking is the voice and
    # the callsign in the transmission, which is how a pilot tells them apart in
    # the air anyway.
    client = SRSClient(host, name=SRS_NAME,
                       eam_password=config.SRS_EAM_PASSWORD).connect(
                           [radio(mhz * 1_000_000, AM) for mhz in channels])
    ctl = controller.Controller(profile)  # deterministic separation, seeded from the approach
    print(f"agent ATC live as {profile.controller} (voice {voice_id}, "
          f"session {session_id})", flush=True)
    print("  monitoring " + ", ".join(f"{c:.3f}" for c in channels), flush=True)

    # One lock over the whole exchange (POST /chat + transmit). The pilot loop and
    # the hook scheduler both drive the same agent session and the same radio, so
    # they must never overlap -- no talking over the pilot, no racing the session.
    radio_lock = threading.Lock()

    # When the metronome must stay off the air. Two different courtesies:
    #
    #   someone_is_talking  -- a pilot has the channel. A radio is half duplex
    #                          and so is the manners; wait.
    #   readback_until      -- we have just issued a clearance and he is owed
    #                          room to read it back. Filling that gap ourselves
    #                          is how "he never gave me time for a readback"
    #                          happens, and it also destroys the readback we
    #                          would otherwise get to check.
    #
    # Both apply only to the UNPROMPTED threads. A direct answer to something
    # the pilot just said is a reply, and replies are not interruptions.
    readback_until = [0.0]
    READBACK_SEC = 7.0
    # A pilot has spoken and the model is composing his answer. The transmission
    # is over, so `someone_is_talking` is already false, and the metronome would
    # cheerfully fill the three to nine seconds of thinking time -- so the pilot
    # hears a mile call for somebody else where his own answer should have been.
    # With two aeroplanes working one controller that is most of the traffic.
    answering = [False]

    def channel_is_free(now: float | None = None) -> tuple[bool, str]:
        now = now or time.monotonic()
        if client.someone_is_talking():
            return False, "a pilot is transmitting"
        if answering[0]:
            return False, "answering a pilot"
        if now < readback_until[0]:
            return False, f"readback window, {readback_until[0] - now:.0f}s left"
        return True, ""

    def hold_the_channel_for_a_readback() -> None:
        readback_until[0] = time.monotonic() + READBACK_SEC

    # Who has engineering up, and on which frequency they called from -- so the
    # reply goes back where it was asked rather than wherever the bridge was
    # started. A distinct voice, because a pilot must never mistake engineering
    # for a controller.
    engineering_line: dict[str, float] = {}
    # The same pilots, by CALLSIGN, because the metronome works aeroplanes and
    # does not know a radio GUID from a hole in the ground.
    #
    #     "when I'm talking to you on engineering, the controller continues to
    #      talk to me"
    #
    # Reported airborne, at seven miles, while a vector call landed on top of
    # every sentence -- both on 124, because engineering answers wherever he
    # called from. A pilot who has stopped flying the approach to report a bug
    # has stopped flying the approach; talking over him loses the report AND the
    # vector, since he is not writing either one down.
    engineering_callsigns: set[str] = set()
    eng_voice = tts.Voice(voice_id="Amy")

    # CALLING A CONTROLLER BY NAME LETS YOU GO.
    #
    # Everything a pilot says goes to engineering until he releases the line, so
    # forgetting the goodbye means the controller has gone deaf to him -- and the
    # moment he is most likely to forget is the moment it costs most, four miles
    # out with other things to think about. Addressing a station by name is an
    # unambiguous statement about who he is talking to, and the system should not
    # need it said twice.
    _station_names = [s.name for s in (getattr(profile, "stations", None) or [])]
    _ADDRESSING = (re.compile("|".join(re.escape(n) for n in _station_names), re.I)
                   if _station_names else None)

    def interact(message: str, kind: str, tier: str = "sonnet",
                 on_hz: float | None = None, guide=None,
                 to_callsign: str = "") -> None:
        answering[0] = True
        try:
            _interact(message, kind, tier, on_hz, guide, to_callsign)
        finally:
            answering[0] = False

    def _interact(message: str, kind: str, tier: str = "sonnet",
                  on_hz: float | None = None, guide=None,
                  to_callsign: str = "") -> None:
        with radio_lock:
            t0 = time.monotonic()
            try:
                reply = ask_agent(session_id, message, tier, url)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                print(f"  !! agent error: {e}", flush=True)
                reply = "Standby."
            dt = time.monotonic() - t0
            reply = for_voice(reply, agent=True)
            # THE ENGINE OWNS THE TALKDOWN. See hush_a_second_talkdown: the
            # agent's parallel mile calls do not merely duplicate, they hold the
            # metronome off the air and take the descent instructions with it.
            reply, hushed = hush_a_second_talkdown(reply, guide)
            if hushed:
                print(f"  .. hushed the agent on final: {hushed}", flush=True)
            if not reply or reply.lower() in NO_CALL:
                print(f"  ATC[{kind}/{tier}] ({dt:.1f}s): (no call)", flush=True)
                return
            print(f"  ATC[{kind}/{tier}] ({dt:.1f}s): {reply}", flush=True)
            _last_said[0] = reply
            if to_callsign:
                note_issued(to_callsign, reply)
            record(session_id, kind=f"atc/{kind}", tier=tier,
                   seconds=round(dt, 1),
                   freq_mhz=(on_hz or freq_hz) / 1_000_000, text=reply)
            # Answer on the channel he called from -- that is the beacon he is
            # homing, and therefore the only one he can hear.
            client.transmit(voice_for(on_hz).frames(reply),
                            on_hz or freq_hz, AM)
            # He is owed room to read that back, and we want to HEAR the
            # readback -- it is the only check on whether he got the numbers
            # right, and several were mangled on the sortie that prompted this.
            hold_the_channel_for_a_readback()

    def scheduler() -> None:
        # Fire the agent's own wake-up hooks: when a timer expires, re-invoke it
        # with the hook's reason so it makes the call it scheduled.
        while True:
            time.sleep(HOOK_POLL_SEC)
            for hook in fetch_due(session_id):
                scope = fetch_radar(session_id) if radar_on else ""
                why = hook.get("why") or ""
                # WHICH CHANNEL THE PROMISE WAS MADE ON.
                #
                # Without this the callback went out on the bridge's primary
                # frequency whatever channel the pilot was actually on. Hoover
                # asked Georgia Center on 139 for a call in sixty seconds; the
                # hook fired on time, the controller said "calling as requested,
                # go ahead" -- on 124, where nobody was listening. From the
                # cockpit that is indistinguishable from a hook that never
                # fired, and it is worse than never promising.
                #
                # The frequency comes from the man it is owed to: the channel we
                # last heard HIM on. Falling back to the last channel anybody
                # spoke on, and only then to the primary.
                on_hz = hook_frequency(why, _heard_on, _last_active_hz[0])
                print(f"HOOK fired (+{hook.get('seconds')}s) on "
                      f"{(on_hz or freq_hz) / 1e6:.3f}: {why}", flush=True)
                interact(
                    f"EVENT -- your scheduled hook just fired. Reason you set it: "
                    f"{why}\nRADAR: {scope}\n"
                    f"Make the radio call now if it is warranted. If nothing is "
                    f"needed, reply exactly: (no call).",
                    "hook", on_hz=on_hz)

    def asr_monitor() -> None:
        """Talk him down: a range call every mile while he is on final.

        This is the first thing the controller says because of where an
        aeroplane IS rather than because somebody keyed a mic, and it is what
        makes a radar approach a radar approach -- a pilot descending on a
        surveillance approach expects to hear a mile call every mile, and
        silence is indistinguishable from having been forgotten.

        Deterministic and un-modelled: one call per whole mile, transmitted
        under the same radio lock as everything else so it can never talk over
        the pilot or over the agent mid-sentence.
        """
        # WHICH FREQUENCY THE FINAL IS FLOWN ON. One controller, one channel.
        #
        # This used to go out on Tower's frequency while the model's answers
        # went out on Approach's, and the result was exactly what it sounds
        # like: a pilot heard a conversation from one voice on one channel and
        # vectors from a different voice on another, disagreeing, and reported
        # "two personalities" and "he's sending me south of the field". They
        # were two halves of one controller, split across two radios.
        #
        # On a talkdown the radar controller flies the approach, so his channel
        # carries all of it -- the conversation, the vectors and the mile calls
        # -- and Tower's landing clearance is relayed rather than collected on
        # another frequency. That matches both the procedure and the handoff
        # rule in route.py, which now keeps him here to the missed approach
        # point. On any other approach the aeroplane has its own aid and Tower
        # genuinely does take him at the intercept, so the old behaviour stands.
        _final = None
        if hasattr(profile, "station_for"):
            _final = (profile.station_for("approach")
                      if getattr(profile, "guidance", "") == "talkdown"
                      else profile.station_for("tower"))
        final_hz = (_final.freq_mhz * 1_000_000) if _final else freq_hz
        called: dict[str, int] = {}
        vectored: dict[str, int] = {}      # last heading issued, per aircraft
        vec_at: dict[str, float] = {}      # and when, so he is not nagged
        # A proposed REVERSAL has to be seen twice before it is spoken. The
        # geometry can flip between "intercept" and "reposition" at a boundary,
        # and this thread transmits on every poll -- so a pilot heard turn right
        # 148, turn left 306, turn left 291, turn left 249, turn right 264, turn
        # right 295, and said it felt like two controllers, one of whom thought
        # he was outbound. He was not wrong: those are two answers to the same
        # question, alternating.
        #
        # This does not fix the flip. It stops the radio carrying it, which is
        # the difference between a controller who is thinking and one who is
        # unusable, and it costs one poll of latency on a genuine reversal.
        pending: dict[str, int] = {}
        grounded: set[str] = set()   # already noticed on the runway
        while True:
            time.sleep(ASR_POLL_SEC)
            if not (radar_on and getattr(profile, "vectored", False)):
                continue
            try:
                scope = fetch_radar(session_id)
                # Sequencing: with a queue, only the aircraft that owns the
                # approach is vectored. Everyone else is holding, and a vector
                # is an invitation to start -- issue two and two aeroplanes fly
                # the same intercept to the same fix at the same time, which is
                # not a talk-down, it is a collision brief. With nobody queued
                # the question does not arise and the single ship is worked
                # normally.
                # NOBODY CLEARED MEANS NOBODY VECTORED.
                #
                # The filter used to apply only when somebody owned the
                # approach, so the one state it had to cover -- a full stack
                # with nobody cleared yet -- was the one where it switched
                # itself off and vectored everyone. Two Mustangs holding at five
                # and six thousand were each told to turn onto the intercept and
                # climb to twelve, seconds after being told to hold where they
                # were. From the cockpit that is two controllers, and the pilot
                # said so: "we have duplicate controllers again".
                #
                # With traffic a vector IS the invitation to start the approach.
                # Issuing it to a man who has been told to hold contradicts the
                # only instruction that matters, and issuing it to two men at
                # once is the collision brief this whole thread exists to avoid.
                # So the queue decides, and silence is the correct output until
                # it does.


                fixes = radar_fixes(scope, profile)
                # Two contacts is traffic, and traffic means one at a time.
                traffic = len(fixes) >= 2
                for cs, pos in fixes:
                    # He is on the ground. Stop flying him.
                    #
                    # The approach ends when the aeroplane is on the runway, and
                    # the scope says so plainly -- at the field, at field
                    # elevation. Waiting to be TOLD leaves the controller working
                    # a parked aircraft: "I'm sitting on the ground at Batumi,
                    # and Batumi Tower thinks I'm on the missed approach". He
                    # was, because nothing had read the one source that knew.
                    #
                    # This is the session's rule in miniature -- the stack holds
                    # what was agreed, the scope holds what is true -- and a
                    # landing is one of the few places the scope may simply
                    # overrule the conversation, because an aeroplane at zero
                    # feet on the aerodrome is not a matter of opinion.
                    if asr.on_the_ground(pos, profile):
                        if cs in grounded:
                            continue
                        # Only somebody we were actually working. `report_landed`
                        # creates an aircraft it has never heard of, so without
                        # this every parked machine on the ramp gets a farewell.
                        if ctl._resolve(cs) not in ctl.aircraft:
                            grounded.add(cs)
                            continue
                        # SAY GOODBYE. The controller already composes one --
                        # a taxi instruction -- and the bridge
                        # used to drop it on the floor, so the observable end of
                        # an approach was SILENCE. A pilot cannot tell that from
                        # a controller who has crashed or lost him, which is the
                        # same bug as an engineering channel that says nothing,
                        # and it is worse here because it is the last thing that
                        # happens on every flight.
                        if cs in engineering_callsigns:
                            # Not recorded as issued: he never heard it, and
                            # marking it sent would suppress the repeat once he
                            # comes back to the frequency.
                            print(f"  .. holding a vector for {cs}: he is on "
                                  f"the engineering line", flush=True)
                            continue
                        free, why = channel_is_free()
                        if not free:
                            print(f"  .. holding {cs}'s goodbye: {why}", flush=True)
                            continue          # not marked down; it will repeat
                        grounded.add(cs)
                        print(f"  {cs} is on the ground — approach complete",
                              flush=True)
                        try:
                            ctl.report_down(cs)
                            bye = for_voice(" ".join(tx.text for tx in ctl.out))
                            ctl.out.clear()
                        except Exception:
                            bye = ""          # a stale stack is not fatal
                        called.pop(cs, None)
                        vectored.pop(cs, None)
                        pending.pop(cs, None)
                        if bye:
                            with radio_lock:
                                print(f"  ATC[down] {bye}", flush=True)
                                record(session_id, kind="atc/landed",
                                       callsign=cs, text=bye)
                                client.transmit(voice_for(final_hz).frames(bye),
                                                final_hz, AM)
                        continue
                    grounded.discard(cs)        # airborne again: a new sortie

                    if not may_be_vectored(ctl, cs, traffic=traffic,
                                           freq_hz=final_hz):
                        continue                # holding, or nobody's turn yet
                    g = asr.guide(pos, profile,
                                  on_missed=flying_the_missed(cs, pos, profile,
                                                              ctl))
                    note_missed(cs, g.phase, ctl)

                    # Being VECTORED. The controller has to turn him when he
                    # reaches the point, not when he next happens to transmit --
                    # a real sortie flew twenty miles between calls, sailed past
                    # the intercept on a heading that had been right when it was
                    # issued, and ended up on the far side of the field with the
                    # controller none the wiser. Watching the scope is the job.
                    if g.phase == "vector":
                        called.pop(cs, None)
                        want = g.heading
                        last = vectored.get(cs)
                        drifted = last is None or abs(
                            asr.angle_diff(want, last)) >= VECTOR_CHANGE_DEG
                        if not drifted or time.time() - vec_at.get(cs, 0) < VECTOR_MIN_SEC:
                            continue
                        # A big change is a reversal, not a correction. Hold it
                        # for one poll and only speak if it is still wanted.
                        if last is not None and abs(asr.angle_diff(want, last)) > 60:
                            prev = pending.get(cs)
                            if prev is None or abs(asr.angle_diff(want, prev)) > 20:
                                pending[cs] = want
                                print(f"  .. holding a {abs(asr.angle_diff(want, last)):.0f}"
                                      f" degree reversal for {cs} to see if it "
                                      "persists", flush=True)
                                continue
                        if cs in engineering_callsigns:
                            # Not recorded as issued: he never heard it, and
                            # marking it sent would suppress the repeat once he
                            # comes back to the frequency.
                            print(f"  .. holding a vector for {cs}: he is on "
                                  f"the engineering line", flush=True)
                            continue
                        free, why = channel_is_free()
                        if not free:
                            # Do NOT record it as issued -- he never heard it,
                            # and marking it sent would suppress the repeat.
                            print(f"  .. holding a vector for {cs}: {why}",
                                  flush=True)
                            continue
                        pending.pop(cs, None)
                        vectored[cs], vec_at[cs] = want, time.time()
                        text = for_voice(vector_call(cs, g))
                        note_issued(cs, text)
                        with radio_lock:
                            print(f"  ATC[vec] {text}", flush=True)
                            record(session_id, kind="atc/vector", callsign=cs,
                                   range_nm=round(g.range_nm, 2),
                                   heading=want, alt=g.altitude_ft, text=text)
                            client.transmit(voice_for(final_hz).frames(text),
                                            final_hz, AM)
                            hold_the_channel_for_a_readback()
                        continue

                    if g.phase not in ("final", "map"):
                        called.pop(cs, None)
                        continue
                    vectored.pop(cs, None)
                    mile = 0 if g.phase == "map" else int(round(g.range_nm))
                    if called.get(cs) == mile:
                        continue
                    free, why = channel_is_free()
                    if not free:
                        print(f"  .. holding the {mile} mile call for {cs}: "
                              f"{why}", flush=True)
                        continue        # not marked as called; it repeats
                    called[cs] = mile
                    text = for_voice(asr_call(cs, g, pos, profile))
                    note_issued(cs, text)
                    with radio_lock:
                        print(f"  ATC[asr] {text}", flush=True)
                        record(session_id, kind="atc/range", callsign=cs,
                               range_nm=round(g.range_nm, 2), phase=g.phase,
                               heading=g.heading, text=text)
                        client.transmit(voice_for(final_hz).frames(text),
                                        final_hz, AM)
                        if g.phase != "map":
                            # A range call with a correction in it is an
                            # instruction; the bare "over the point" is not.
                            hold_the_channel_for_a_readback()
            except Exception as e:                 # never kill the metronome
                print(f"  !! asr monitor: {e}", flush=True)

    def engineering_radio() -> None:
        """Speak whatever the engineer types, on the frequency he was called on.

        A file rather than an API because the whole point is that it is
        reachable from anywhere in one line -- an editor, a shell, a script
        that just finished a rebuild:

            echo "that vector was mine, fix is loading" >> /tmp/marshall-say

        Consumed before speaking, so a slow transmission can never repeat it.
        """
        spool = pathlib.Path(ENG_SPOOL)
        try:
            spool.touch(exist_ok=True)
        except OSError:
            return
        while True:
            time.sleep(1.0)
            try:
                lines = [l for l in spool.read_text().splitlines() if l.strip()]
                if not lines:
                    continue
                spool.write_text("")
            except OSError:
                continue
            # Wherever he was last spoken to. With nobody on the line it still
            # goes out on the channel the bridge was started on, so a broadcast
            # to an unattended frequency is possible on purpose.
            hz = (list(engineering_line.values())[-1] if engineering_line
                  else freq_hz)
            for line in lines:
                with radio_lock:
                    print(f"  ENG[tx] {line}", flush=True)
                    record(session_id, kind="engineering/tx", text=line)
                    try:
                        client.transmit(eng_voice.frames(line), hz, AM)
                    except Exception as e:
                        print(f"  !! engineering transmit failed: {e}", flush=True)
                time.sleep(0.3)

    threading.Thread(target=engineering_radio, daemon=True).start()
    threading.Thread(target=scheduler, daemon=True).start()
    threading.Thread(target=asr_monitor, daemon=True).start()

    while True:
        pcm, heard_hz = client.recv_utterance(max_wait=3600)
        if pcm is None or not pcm.size:
            continue
        transcript = stt.transcribe(model, pcm,
                                    prompt=whisper_vocabulary(profile))
        if not transcript:
            continue
        srs = client.name_for(client.last_sender_guid)   # who keyed the mic (free)

        # Never answer another controller. A second bridge left running on the
        # same frequency -- trivially easy, since killing the launcher does not
        # kill the python child -- hears this one, treats the transmission as a
        # pilot call, and replies; then this one hears THAT. The two talk to each
        # other forever, jamming the frequency and burning tokens, and the
        # transcripts look almost plausible. Cheap guard, unbounded saving.
        if srs in OUR_STATIONS or client.last_sender_guid == client.guid:
            print(f"  (ignoring {srs} -- that is one of ours, not a pilot)",
                  flush=True)
            continue

        # WHO IS TALKING, decided by something other than what he said.
        #
        # The scope is fetched FIRST now, because the strongest evidence about
        # identity is in it: SRS names a client after the human, DCS names the
        # unit after the slot he took, and one contains the other. That chain --
        # radio GUID to client name to unit to track -- has no microphone in it
        # anywhere, so a garbled callsign cannot move it. See identity.py and
        # [ARCH-2] / #40; 846 recorded transmissions say the words alone would
        # bind a radio to 37 distinct names, of which ten were aeroplanes.
        scope = fetch_radar(session_id) if radar_on else ""

        # What the WORDS claim, still by vote across the sortie: real callsigns
        # repeat and noise does not. Demoted from the answer to a claim, which
        # is then matched against a track or a filed strip.
        claim = transmitter_callsign(client.last_sender_guid, transcript)
        _ident = _identity.resolve(
            client.last_sender_guid or "", srs, spoken=claim, scope=scope,
            plans=filed_plans(), roster=list(ctl.aircraft))
        known = _ident.callsign
        if _ident.authority and _ident.authority != "radar":
            # Worth a line in the log every time it is NOT the physical chain:
            # the day this reads "roster" for a pilot who should be on radar,
            # something upstream has broken.
            print(f"  (identity: {_ident.why})", flush=True)
        if known:
            # He has checked in HERE. Until he does, no controller on this
            # channel may start working him -- see may_be_vectored.
            _heard_on[known] = heard_hz or freq_hz
            # And the channel the conversation is on, for anything owed to a
            # pilot later -- a hook whose reason names nobody still has to be
            # spoken where somebody is listening.
            _last_active_hz[0] = heard_hz or freq_hz

        n_contacts = count_contacts(scope)
        tag = f" [RADAR: {scope}]" if scope else ""
        print(f"PILOT [{known or srs}]: {transcript}{tag}", flush=True)
        _fix = radar_fix(scope, known, profile)
        record(session_id, kind="pilot", callsign=known or srs,
               # The provenance of the identity, not just the answer. Without
               # it a recording cannot be scored after the fact: "Pony 1-1" in
               # the log looks identical whether radar put it there or a
               # transcript did, and those are the two cases worth telling
               # apart. srs_name is here for the same reason -- it is the
               # strongest link and was not being preserved, so the replay of
               # every earlier sortie could only measure the weak paths.
               srs_name=srs, claimed=claim, authority=_ident.authority,
               track=_ident.track, why=_ident.why,
               freq_mhz=(heard_hz or freq_hz) / 1_000_000, transcript=transcript,
               range_nm=_fix.range_nm if _fix else None,
               radial=_fix.radial_deg if _fix else None,
               alt_ft=_fix.alt_ft if _fix else None,
               heading=_fix.heading_deg if _fix else None, scope=scope)
        # ...and what the ENGINE thinks is out there, at this instant. Recorded
        # beside the words that produced it: a ghost is created by a
        # transmission, so the transmission and the board have to be adjacent in
        # the record or the pairing is guesswork after the fact.
        record(session_id, kind="board", callsign=known or srs,
               board=ctl.board())

        # Engage the deterministic engine only with real traffic (or forced on for
        # the voice-only rehearsal, or once a stack already exists). A single ship
        # stays pure rich Sonnet: radar-aware, fluent, no classify on the path.
        engaged = SEP_ALWAYS or n_contacts >= 2 or len(ctl.aircraft) >= 2

        # Deterministic short-circuit: a radio check or a closing acknowledgement
        # gets an instant canned reply -- the rich agent adds nothing. Not mid-
        # sequence, where the controller may need to react to it.
        canned = simple_response(transcript)
        if canned and not engaged:
            canned = for_voice(canned)
            print(f"  ATC[simple] (0.0s): {canned}", flush=True)
            with radio_lock:
                client.transmit(voice_for(heard_hz).frames(canned),
                                heard_hz or freq_hz, AM)
            continue

        directive, stack = (separation_context(ctl, transcript, scope, known) if engaged
                            else ("", ""))
        # Radar guidance for a vectored approach. Costs no model call, so it
        # runs for a single ship too -- which is the case that was flying with
        # no deterministic picture at all.
        vectoring = asr_context(profile, scope, known)

        # The one aircraft state. Bind whatever names we have -- the radio GUID
        # always, the callsign once he says it, the track once radar ties them
        # together -- and remember the row so what is agreed can be written
        # against it. Identity arrives in pieces and this is where they are
        # joined.
        # The track name only goes in once radar has actually tied the callsign
        # to a blip -- binding a guess would attach one aeroplane's history to
        # another's, which is worse than being unidentified.
        _fix = radar_fix(scope, known, profile) if known else None
        _flight = flight_bind(
            srs_guid=client.last_sender_guid or None,
            srs_name=srs or None,
            callsign=known or None,
            track_name=known if _fix is not None else None,
        ) if (client.last_sender_guid or known) else {}
        _fid = _flight.get("id")

        # One aeroplane, one instruction. Decide here which authority owns him
        # rather than handing the agent three and hoping -- see reconcile().
        _g = (asr.guide(_fix, profile,
                        on_missed=flying_the_missed(known or "?", _fix, profile,
                                                    ctl))
              if _fix is not None else None)
        directive, stack, vectoring, dropped = reconcile(
            directive, stack, vectoring, _g)
        if dropped:
            print(f"  .. {dropped}", flush=True)

        if vectoring:
            print(f"  {vectoring}", flush=True)
            record(session_id, kind="asr", callsign=known, text=vectoring)
        if directive:
            record(session_id, kind="controller", text=directive)

        # Write down what was AGREED, so the next controller inherits it and so
        # the gap between it and the scope can be seen. Read off the engine that
        # made the decision rather than parsed back out of English -- the words
        # are for the pilot, the row is for us, and re-reading our own prose
        # would be a second chance to get it wrong.
        if _fid:
            _ac = ctl.get(known) if known else None
            _agreed = {}
            if _ac is not None:
                _agreed["cleared"] = _PHASE_OF.get(_ac.phase.name, "unknown")
                if _ac.assigned_ft:
                    _agreed["assigned_ft"] = int(_ac.assigned_ft)
                if getattr(_ac, "size", 1) > 1:
                    _agreed["claimed_size"] = int(_ac.size)
            if _g is not None and _g.phase in ("final", "map"):
                _agreed["cleared"] = "approach"
            elif _g is not None and _g.phase == "missed":
                _agreed["cleared"] = "missed"
            if APPROACH_NAME:
                _agreed.setdefault("procedure", APPROACH_NAME)
                _agreed.setdefault("runway", profile.runway or None)
            if _agreed:
                flight_agree(_fid, **_agreed)

        # ENGINEERING. Handled before the controller sees anything, because a
        # pilot who has called engineering up is not talking to ATC and must not
        # be answered by it.
        _eng_hz = heard_hz or freq_hz
        _on_the_line = client.last_sender_guid in engineering_line
        # Release is checked FIRST: "thanks engineering" and "engineering, clear"
        # both contain the word, so a summons that matched on the word alone
        # would re-open the line the pilot was trying to close and he could
        # never get back to the controller.
        # ADDRESSED, not merely MENTIONED. A controller's name in the OPENING of
        # a transmission is a pilot calling him; the same name in the middle of
        # a sentence is a pilot talking ABOUT him.
        #
        # Hoover's bug report -- "requested a call back, got no call back on one
        # three nine Georgia Center" -- was read as him calling Georgia Center,
        # so engineering stepped aside and the controller answered a bug report
        # with "say your callsign". The report was lost and the pilot got an
        # interrogation. Same rule as a callsign: an address opens a
        # transmission, which is how radio works and not a heuristic.
        # WHOEVER IS NAMED FIRST is who he is calling. Opening a transmission
        # with "engineering" and then naming a controller inside the sentence --
        # "engineering, Batumi Approach vectored me into the hill" -- is a bug
        # report about that controller, not a call to him.
        _opening = " ".join(transcript.split()[:6])
        _atc_at = _ADDRESSING.search(_opening) if _ADDRESSING else None
        _eng_at = re.search(r"\bengineering\b", _opening, re.I)
        _addressed_atc = bool(_atc_at) and not (
            _eng_at and _eng_at.start() < _atc_at.start())
        if _on_the_line and _addressed_atc and not _ENG_CALL.search(transcript):
            # He is talking to a controller. Step out of the way silently -- a
            # "clear" call here would be engineering talking over the very
            # transmission it just got out of the way of.
            engineering_line.pop(client.last_sender_guid, None)
            engineering_callsigns.discard(known)
            print(f"  ENGINEERING released {known or srs} — he called a controller",
                  flush=True)
            _on_the_line = False

        if _on_the_line and _ENG_DONE.search(transcript):
            engineering_line.pop(client.last_sender_guid, None)
            engineering_callsigns.discard(known)
            print(f"  ENGINEERING released {known or srs}", flush=True)
            with radio_lock:
                client.transmit(
                    eng_voice.frames("Engineering clear, back to the controller."),
                    _eng_hz, AM)
            continue
        _summoned = bool(_ENG_CALL.search(transcript))
        if _summoned or _on_the_line:
            engineering_line[client.last_sender_guid] = _eng_hz
            if known:
                engineering_callsigns.add(known)
            stamp = time.strftime("%H:%M:%S")
            who = known or srs
            print(f"  ENGINEERING [{stamp}] {who}: {transcript}", flush=True)
            record(session_id, kind="engineering", callsign=who, text=transcript)
            try:
                config.BUILD_DIR.mkdir(parents=True, exist_ok=True)
                with open(config.BUILD_DIR / "debug-notes.md", "a",
                          encoding="utf-8") as fh:
                    fh.write(f"- `{stamp}` **{who}** {transcript}\n")
            except OSError as e:
                print(f"  !! could not write the note: {e}", flush=True)
            # An explicit summons is ALWAYS answered with the greeting, even when
            # he is already on the line. Suppressing it because he was already
            # connected was tried for one minute of a live test and was much
            # worse: he asked for engineering, got "copied, logged", could not
            # tell whether the channel was open, and asked twice more. The whole
            # point of this ack is that a pilot never has to wonder.
            #
            # The cost is that a sentence merely MENTIONING engineering can
            # re-greet him -- "I'm going to ask that engineering go off the
            # line" did. That is a wasted sentence. The other way is a pilot
            # talking into what he believes is a dead radio, which is the bug
            # this whole channel exists to kill.
            reply = engineering_ack(_summoned)
            with radio_lock:
                print(f"  ENG[tx] {reply}", flush=True)
                client.transmit(eng_voice.frames(reply), _eng_hz, AM)
            continue
        # OUT OF THE BLUE, WITH NO CALLSIGN. We know who it is from his radio,
        # and a real controller does not -- so he asks, and does not act on a
        # report he cannot attribute. Inside a conversation he does not ask,
        # because by then he knows the voice.
        from marshall.atc import callsign as _C
        _guid = client.last_sender_guid or ""
        _said_who = bool(_C.extract(transcript))
        _open = in_conversation(_guid)
        _last_heard[_guid] = time.time()
        if not _said_who and not _open and known:
            reply = challenge_for(transcript)
            with radio_lock:
                print(f"  ATC[who] {reply}   (out of the blue, no callsign)",
                      flush=True)
                record(session_id, kind="atc/challenge", callsign=known,
                       text=reply)
                client.transmit(voice_for(heard_hz).frames(reply),
                                heard_hz or freq_hz, AM)
            continue

        # Not addressed to us. Two aircraft on our frequency talking to each
        # other -- a real controller hears it, understands, and says nothing.
        _other = addressed_to_another_aircraft(
            transcript, known, [s.name for s in (getattr(profile, "stations", None) or [])])
        if _other:
            print(f"  (ship-to-ship: {known or srs} calling {_other} — not ours)",
                  flush=True)
            record(session_id, kind="ship-to-ship", callsign=known,
                   text=transcript)
            continue

        # A debug note: record it and stay off the air entirely. The pilot is
        # talking to the project, not to the controller.
        note = debug_note(transcript)
        if note is not None:
            stamp = time.strftime("%H:%M:%S")
            print(f"  DEBUG NOTE [{stamp}] {note}", flush=True)
            record(session_id, kind="debug", text=note)
            try:
                config.BUILD_DIR.mkdir(parents=True, exist_ok=True)
                with open(config.BUILD_DIR / "debug-notes.md", "a",
                          encoding="utf-8") as fh:
                    fh.write(f"- `{stamp}` {note}\n")
            except OSError as e:
                print(f"  !! could not write the note: {e}", flush=True)
            continue

        # Which controller answered. The bridge monitors every channel at once,
        # which is an implementation convenience the pilot must never be able to
        # hear -- without this the same voice answers as "Batumi Approach" on
        # Center's frequency and the sector split is decoration.
        on_mhz = (heard_hz or freq_hz) / 1_000_000
        me = profile.station_on(on_mhz) if hasattr(profile, "station_on") else None
        fix = radar_fix(scope, known, profile)
        nxt = (profile.handoff_from(on_mhz, fix.range_nm)
               if me and fix is not None else None)
        if nxt is None and me is not None and known:
            # He may be on his way OUT rather than in -- the case range cannot
            # answer. Costs one lookup and only ever fires when the approach
            # rules had nothing to say.
            nxt = leaving_my_airspace(BASE_URL, session_id, known, me,
                                      profile, fix)
        if directive:
            print(f"  CONTROLLER: {directive}", flush=True)
        if stack:
            print(f"  SEPARATION: {stack}", flush=True)
        parts = []
        if scope:
            parts.append(f"RADAR: {scope}")
        parts.append(
            f"TRANSMITTER: the radio calling itself {known}. Same aircraft as "
            f"every other call from {known} -- keep them together."
            if known else
            "TRANSMITTER: a radio you have not identified yet.")
        _strip = flight_strip(_flight)
        if _strip:
            parts.append(
                _strip + " This is what is already known about him and it "
                "carries across a handoff -- do not ask him again for anything "
                "in it.")
        if directive:
            parts.append("CONTROLLER (deterministic next step of the approach — "
                         "voice its altitudes, headings and sequence exactly, add "
                         f"your radar read, never skip a leg): {directive}")
        if stack:
            parts.append(f"SEPARATION (holding stack, one in the letdown): {stack}")
        if vectoring:
            parts.append(
                "ASR (radar guidance, computed from the scope — voice these "
                "numbers exactly; you are navigating for him and he has no "
                f"approach aid of his own): {vectoring}")
        if me and getattr(me, "role", "") in ("approach", "tower"):
            parts.append(
                "VISUAL APPROACHES ARE AVAILABLE and are the normal thing to "
                "fly in decent weather. If he asks for one, give it to him -- "
                "\"cleared visual approach runway "
                f"{profile.runway or 'in use'}, report the field in sight\" -- "
                "and then get off the air: your job shrinks to spacing and he "
                "flies the approach. Do NOT tell him only the surveillance "
                "approach is published and make him argue for it. The radar "
                "approach is the bad-weather procedure, not the only one.")
        if me:
            parts.append(
                f"YOU ARE: {me.name} on {me.freq_mhz:.1f}. Identify as that and "
                "NOTHING else, even if he calls you by another name. A pilot "
                "who says \"Batumi Tower\" on Approach's frequency has the "
                "wrong button pressed, and agreeing with him puts Tower on a "
                "frequency Tower is not on — he then believes it, and so does "
                "everyone listening. Correct him in the same breath as the "
                "answer, and name the frequency he is ON as well as the one he "
                f"wanted: \"Pony one one, this is {me.name}, "
                f"{controller.spell_freq(me.freq_mhz)} — Tower is one one "
                "eight\" — then give him what he asked for. Saying only which "
                "frequency he wanted leaves him still not knowing which button "
                "he is holding, and a pilot who has lost track of that gets it "
                "wrong again on the next call. He is flying an aeroplane; do "
                "not make him ask twice.")
            also = [r for r in (getattr(me, "also", ()) or ()) if r]
            if also:
                # The other hats this man wears, read off the station rather than
                # remembered. A field this size does not staff a seat per phase
                # of flight: one man has ground, delivery and tower. Without this
                # he refuses work that is his and sends the pilot to a frequency
                # he invented -- a clearance request on Tower was answered with
                # "you want Ground, try one two one decimal five", which is a
                # channel with nobody on it.
                parts.append(
                    f"YOU ALSO WORK: {', '.join(also)} — on this same "
                    f"frequency, because this field does not staff a separate "
                    f"position for them. A pilot who calls you by one of those "
                    f"names has the RIGHT button pressed. Do the work; do not "
                    f"send him to another frequency for it, and never name a "
                    f"frequency that is not on the plate.")
            # WHOM HE CALLS AFTER HE ROLLS, from the published stations rather
            # than from the model's memory of what it said a minute ago.
            #
            # Hoover was cleared with "departure frequency one two four decimal
            # zero", read it back, and was then told on the taxi clearance to
            # contact Georgia Center one three nine when airborne. Two different
            # answers to "who do I call after takeoff", one minute apart, and the
            # pilot has no way to tell which one is wrong. The clearance is built
            # from this same station list, so quoting it here means the two
            # cannot disagree.
            if getattr(me, "role", "") in ("tower", "ground", "delivery") or (
                    "delivery" in [r for r in (getattr(me, "also", ()) or ())]):
                _dep = None
                for _s in (getattr(profile, "stations", None) or []):
                    _roles = [getattr(_s, "role", ""), *(getattr(_s, "also", ()) or ())]
                    if "departure" in _roles:
                        _dep = _s
                        break
                if _dep is not None:
                    parts.append(
                        f"DEPARTURE FREQUENCY: {_dep.name} on "
                        f"{controller.spell_freq(_dep.freq_mhz)}. That is the "
                        f"frequency in his IFR clearance and it is the ONLY one "
                        f"to send him to after takeoff. Do not send a departing "
                        f"aircraft to Center -- Center gets him from Departure, "
                        f"later, and telling him otherwise contradicts a "
                        f"clearance he has already read back.")
            if getattr(me, "role", "") == "overlord":
                parts.append(OVERLORD_BRIEF)
        if nxt:
            parts.append(handoff_phrase(nxt, fix))
        elif (me and getattr(me, "role", "") == "approach"
                and getattr(profile, "guidance", "") == "talkdown"
                and fix is not None and fix.range_nm <= profile.final_intercept_nm):
            # He is inside the final on a talkdown, so he is NOT going to
            # Tower -- you are flying him to the missed approach point. Do not
            # send him to another frequency; the clearance comes to him through
            # you. Telling him to change radios here is the one thing that
            # cannot be recovered, because the controller reading his ranges is
            # the one he just left.
            parts.append(
                f"TOWER RELAY: he is inside the final and stays with you to the "
                f"missed approach point — do NOT hand him to Tower. You have "
                f"his landing clearance from Tower; pass it on once, in your "
                f"own transmission, with the wind: \"cleared to land runway "
                f"{profile.runway}, wind {controller.spell_hdg(int(R.WIND_FROM_DEG))} "
                f"at {int(R.WIND_MPH)}\". Say it once and go back to the talk-down.")
        if known:
            # WHO THIS IS, settled. The model has the radar picture and the
            # transcript and was inferring the caller from both, which is how a
            # wingman who said "Pony one two, checking in" was answered as "Pony
            # one" -- his leader's formation. The radio GUID already knows;
            # nothing was telling the model.
            parts.append(
                f"THIS TRANSMISSION IS FROM {known} — identified by his radio, "
                f"not by the words. Address him as {known} and nobody else, "
                f"even if the transcript sounds like another callsign.")
        # THE READ-BACK IS ANSWERED. Deterministic, like a separation call:
        # the bridge decides that an answer is owed and the agent supplies the
        # words. See _awaiting_readback.
        if known and readback_due(known):
            _awaiting_readback.pop(known, None)
            parts.append(
                "READ-BACK EXPECTED: you have just issued this aircraft an IFR "
                "clearance and this transmission is his read-back of it. ANSWER "
                "IT. If every element matches what you gave him -- clearance "
                "limit, route, altitude, departure frequency, squawk -- say "
                "\"readback correct\" and nothing more. If any element is wrong, "
                "say which one, give the correct value, and ask for that element "
                "again. Silence is not an option here: he is on the ground with "
                "a pencil and no way to know whether you heard him.")
        # HIS READ-BACK IS CORRECT unless it disagrees with what he was GIVEN.
        # The engine recomputes continuously, so by the time a read-back arrives
        # it often wants a different number -- and the controller, holding the
        # new one, told a pilot he was wrong about something he got right. See
        # reads_back_what_we_said.
        if known and reads_back_what_we_said(known, transcript):
            parts.append(
                "READ-BACK CORRECT: those numbers are what you actually gave "
                "him. Do NOT say negative and do not correct him -- he got it "
                "right. If you now want something different, that is a NEW "
                "instruction: say \"amend\" and give it, so he knows it is a "
                "change and not a mistake he made.")
        parts.append(f"PILOT: {transcript}")
        # The current geometry goes with it so the transmit path can tell
        # whether the engine is already flying him down.
        _g = None
        if _fix is not None:
            from marshall.atc import asr as _asr2
            _g = _asr2.guide(_fix, profile,
                             on_missed=flying_the_missed(known, _fix, profile, ctl)
                             if known else False)
        interact("\n".join(parts), "pilot", route_tier(transcript),
                 on_hz=heard_hz, guide=_g, to_callsign=known or "")
        # If that answer WAS a clearance, his next transmission is the read-back.
        if known and is_a_clearance(_last_said[0]):
            _awaiting_readback[known] = time.time()


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--srs":
        if not claim_the_frequency():
            raise SystemExit(1)
        voice = sys.argv[4] if len(sys.argv) > 4 else "Matthew"
        session = sys.argv[5] if len(sys.argv) > 5 else None
        _run_srs(sys.argv[2], float(sys.argv[3]), voice, session)
    else:
        print("usage: agent_atc.py --srs <host> <freq_mhz> [voice] [session]")
