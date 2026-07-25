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

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from marshall import config

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


def for_voice(text: str) -> str:
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
    """
    if "RADIO:" in text:
        text = text.rsplit("RADIO:", 1)[1]
    text = re.sub(r"[*_`#>]+", "", text)          # emphasis / code / heading marks
    text = re.sub(r"(?m)^\s*[-•]\s+", "", text)    # list bullets
    text = re.sub(r"\s*\n+\s*", " ", text)          # collapse newlines to one line
    return re.sub(r"\s{2,}", " ", text).strip()


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
            profile = R.profile_from_dict(fp["approach"]["data"])
            print(f"  loaded flight plan '{fp['name']}' -> approach "
                  f"'{fp['approach']['name']}'", flush=True)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as e:
        print(f"  !! flight-plan bootstrap failed, using route.py: {e}", flush=True)

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
    heard = callsign.extract(transcript)
    if heard:
        _transmitters[guid] = heard
    return _transmitters.get(guid, "")


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


_FIX = re.compile(
    r"\[([^\]]+)\][^|]*?(\d+(?:\.\d+)?)\s*nm[^|]*?on the (\d+)\s*radial"
    r"[^|]*?([\d,]+)\s*ft(?:[^|]*?heading\s*(\d+))?", re.I)


def radar_fix(scope: str, cs: str) -> "object | None":
    """Range, radial, altitude and heading of the track bound to this callsign.

    Only radar-IDENTIFIED contacts (the [tagged] ones) -- guidance computed from
    a blip that might not be him is worse than no guidance, because it sounds
    exactly as confident.
    """
    if not scope or not cs:
        return None
    from marshall.atc import asr, callsign as C
    want = C.parse(cs).flight.lower()
    for tag, nm, radial, alt, hdg in _FIX.findall(scope):
        if C.parse(tag).flight.lower() == want:
            return asr.Position(float(nm), float(radial),
                                int(alt.replace(",", "")),
                                float(hdg) if hdg else 0.0)
    return None


# How often the scope is re-read while somebody is on final. A Mustang at
# pattern speed covers a mile in about fifteen seconds, so four seconds is
# frequent enough to catch each mile boundary without the controller ever
# talking twice about the same one.
ASR_POLL_SEC = 4.0


def radar_fixes(scope: str) -> list[tuple[str, "object"]]:
    """Every radar-IDENTIFIED contact as (callsign, Position).

    Untagged blips are deliberately skipped: an unidentified aircraft on final
    is not somebody we can talk to, and guessing produces a confident call to
    the wrong man.
    """
    from marshall.atc import asr
    out = []
    for tag, nm, radial, alt, hdg in _FIX.findall(scope or ""):
        out.append((tag, asr.Position(float(nm), float(radial),
                                      int(alt.replace(",", "")),
                                      float(hdg) if hdg else 0.0)))
    return out


def asr_call(cs: str, g) -> str:
    """The controller's spoken range call. Deterministic on purpose.

    A talk-down is the most rote transmission in aviation -- "six miles from the
    runway, on course" -- and it has to arrive every mile, on time, with the
    right number. Routing that through a model would add a second of latency and
    a chance of drift to a sentence that has no judgement in it at all. The
    agent still handles everything a pilot actually says; this is the metronome
    underneath.
    """
    from marshall.atc import asr, callsign as C
    who = C.parse(cs).spoken
    rng = asr.spoken_range(g.range_nm)
    if g.phase == "map":
        return (f"{who}, over the missed approach point. Runway in sight, land; "
                f"if not, execute missed approach.")
    if g.off_course:
        return (f"{who}, {rng} miles from the runway, {g.deviation}, "
                f"turn heading {g.heading:03d}.")
    return f"{who}, {rng} miles from the runway, on course."


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
    pos = radar_fix(scope, cs)
    if pos is None:
        return ""
    g = asr.guide(pos, profile)
    rng = asr.spoken_range(g.range_nm)
    if g.phase == "map":
        return ("ASR: he is over the missed approach point. Runway in sight, "
                "land; if not, missed approach now.")
    turn = "" if not g.off_course else f", {g.deviation}"
    swing = f" Turn {g.turn}." if g.turn else ""
    if g.phase == "final":
        return (f"ASR: {rng} miles from the runway{turn}. Fly heading "
                f"{g.heading:03d}, descend and maintain {g.altitude_ft}. "
                f"Call his range every mile.")
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


def separation_context(ctl, transcript: str, scope: str = "") -> tuple[str, str]:
    """The two-brain seam. Advance the deterministic Controller from the call and
    return its authoritative (next-step directive, holding stack).

    The DIRECTIVE is the correct approach sequence for a recognised call (check-in,
    beacon report, landing, ...). It is handed to whichever model voices the reply,
    so even the fast tier just *phrases* the right step instead of guessing it and
    skipping a leg. It is empty for an off-script call the machine doesn't handle
    (a question, a request) -- there the agent reasons freely (and the router will
    have sent that to the smart tier). The STACK is shown only with real traffic."""
    from marshall.atc import bedrock_intent, intents
    directive = ""
    try:
        intent = bedrock_intent.classify(transcript)

        # The engine is blind: it believes position reports, and it has no way
        # to notice a wrong one. Seen live -- a flight called "over the beacon"
        # at eight miles, the agent correctly refused on radar, but the engine
        # had ALREADY broken the formation up on the strength of the report. The
        # two brains then disagreed about where four aeroplanes were. So when
        # the scope contradicts a claimed station passage, the report never
        # reaches the engine at all.
        nm = radar_range_for(scope, intent.callsign)
        if (intent.kind is intents.IntentKind.REPORT_BEACON
                and nm is not None and nm > OVERHEAD_NM):
            print(f"  !! rejected: claims the beacon, radar shows {nm:.1f} nm",
                  flush=True)
            return (f"POSITION REJECTED: he reports over the beacon but radar "
                    f"shows him {nm:.0f} miles out. Correct him and have him "
                    f"continue inbound; he has NOT reached the fix.", "")

        if intents.dispatch(ctl, intent):
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
    voice = tts.Voice(voice_id=voice_id)
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
    client = SRSClient(host, name=profile.controller,
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

    def interact(message: str, kind: str, tier: str = "sonnet",
                 on_hz: float | None = None) -> None:
        with radio_lock:
            t0 = time.monotonic()
            try:
                reply = ask_agent(session_id, message, tier, url)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                print(f"  !! agent error: {e}", flush=True)
                reply = "Standby."
            dt = time.monotonic() - t0
            reply = for_voice(reply)
            if not reply or reply.lower() in NO_CALL:
                print(f"  ATC[{kind}/{tier}] ({dt:.1f}s): (no call)", flush=True)
                return
            print(f"  ATC[{kind}/{tier}] ({dt:.1f}s): {reply}", flush=True)
            # Answer on the channel he called from -- that is the beacon he is
            # homing, and therefore the only one he can hear.
            client.transmit(voice.frames(reply), on_hz or freq_hz, AM)

    def scheduler() -> None:
        # Fire the agent's own wake-up hooks: when a timer expires, re-invoke it
        # with the hook's reason so it makes the call it scheduled.
        while True:
            time.sleep(HOOK_POLL_SEC)
            for hook in fetch_due(session_id):
                scope = fetch_radar(session_id) if radar_on else ""
                print(f"HOOK fired (+{hook.get('seconds')}s): {hook.get('why')}",
                      flush=True)
                interact(
                    f"EVENT -- your scheduled hook just fired. Reason you set it: "
                    f"{hook.get('why')}\nRADAR: {scope}\n"
                    f"Make the radio call now if it is warranted. If nothing is "
                    f"needed, reply exactly: (no call).",
                    "hook")

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
        called: dict[str, int] = {}
        while True:
            time.sleep(ASR_POLL_SEC)
            if not (radar_on and getattr(profile, "vectored", False)):
                continue
            try:
                scope = fetch_radar(session_id)
                for cs, pos in radar_fixes(scope):
                    g = asr.guide(pos, profile)
                    if g.phase not in ("final", "map"):
                        # Left the final -- forget him, so a go-around and a
                        # second approach get their range calls too.
                        called.pop(cs, None)
                        continue
                    mile = 0 if g.phase == "map" else int(round(g.range_nm))
                    if called.get(cs) == mile:
                        continue
                    called[cs] = mile
                    text = for_voice(asr_call(cs, g))
                    with radio_lock:
                        print(f"  ATC[asr] {text}", flush=True)
                        client.transmit(voice.frames(text), freq_hz, AM)
            except Exception as e:                 # never kill the metronome
                print(f"  !! asr monitor: {e}", flush=True)

    threading.Thread(target=scheduler, daemon=True).start()
    threading.Thread(target=asr_monitor, daemon=True).start()

    while True:
        pcm, heard_hz = client.recv_utterance(max_wait=3600)
        if pcm is None or not pcm.size:
            continue
        transcript = stt.transcribe(model, pcm)
        if not transcript:
            continue
        srs = client.name_for(client.last_sender_guid)   # who keyed the mic (free)

        # Never answer another controller. A second bridge left running on the
        # same frequency -- trivially easy, since killing the launcher does not
        # kill the python child -- hears this one, treats the transmission as a
        # pilot call, and replies; then this one hears THAT. The two talk to each
        # other forever, jamming the frequency and burning tokens, and the
        # transcripts look almost plausible. Cheap guard, unbounded saving.
        if srs == profile.controller or client.last_sender_guid == client.guid:
            print(f"  (ignoring {srs} -- that is a controller, not a pilot)",
                  flush=True)
            continue

        # Who this RADIO is, from what it has called itself before. Survives a
        # garbled or omitted callsign, which is the whole point.
        known = transmitter_callsign(client.last_sender_guid, transcript)

        scope = fetch_radar(session_id) if radar_on else ""
        n_contacts = count_contacts(scope)
        tag = f" [RADAR: {scope}]" if scope else ""
        print(f"PILOT [{known or srs}]: {transcript}{tag}", flush=True)

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
                client.transmit(voice.frames(canned), heard_hz or freq_hz, AM)
            continue

        directive, stack = (separation_context(ctl, transcript, scope) if engaged
                            else ("", ""))
        # Radar guidance for a vectored approach. Costs no model call, so it
        # runs for a single ship too -- which is the case that was flying with
        # no deterministic picture at all.
        vectoring = asr_context(profile, scope, known)
        if vectoring:
            print(f"  {vectoring}", flush=True)

        # A debug note: record it and stay off the air entirely. The pilot is
        # talking to the project, not to the controller.
        note = debug_note(transcript)
        if note is not None:
            stamp = time.strftime("%H:%M:%S")
            print(f"  DEBUG NOTE [{stamp}] {note}", flush=True)
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
        fix = radar_fix(scope, known)
        nxt = (profile.handoff_from(on_mhz, fix.range_nm)
               if me and fix is not None else None)
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
        if me:
            parts.append(
                f"YOU ARE: {me.name} on {me.freq_mhz:.1f}. Identify as that and "
                "nothing else — he called this frequency and does not know one "
                "controller is covering several.")
        if nxt:
            parts.append(
                f"HANDOFF: he is {fix.range_nm:.0f} miles out and past your "
                f"boundary — hand him to {nxt.name} on "
                f"{controller.spell_freq(nxt.freq_mhz)} and say goodbye.")
        parts.append(f"PILOT: {transcript}")
        interact("\n".join(parts), "pilot", route_tier(transcript),
                 on_hz=heard_hz)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--srs":
        voice = sys.argv[4] if len(sys.argv) > 4 else "Matthew"
        session = sys.argv[5] if len(sys.argv) > 5 else None
        _run_srs(sys.argv[2], float(sys.argv[3]), voice, session)
    else:
        print("usage: agent_atc.py --srs <host> <freq_mhz> [voice] [session]")
