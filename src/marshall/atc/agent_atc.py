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
from marshall.core import names as _names
from marshall.core import geo as _geo
from marshall.atc import handoff as _handoff
from marshall.atc import flights as fl
from marshall.atc import identity
from marshall.atc import picture as _picture

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
    from marshall.atc import callsign as C, intents
    m = re.search(r"\b([A-Za-z]+(?:\s+(?:one|two|three|four|five|six|seven|eight|"
                  r"niner|nine|\d+))+)", transcript, re.I)
    # SPOKEN, not canonical. This interpolated "Falcon 1-1" straight into
    # speech, and Polly reads the hyphen: it comes out "Falcon one TO one",
    # which a pilot hears as "Falcon one two one" and reports as the controller
    # not knowing who he is.
    #
    #     "batumi tower thought I was falcon 121 again.. approach never did that"
    #
    # Approach never did it because every other path spells the callsign with
    # .spoken. Only the canned replies -- a radio check, a closing
    # acknowledgement -- took the shortcut, and closing calls are exactly what
    # Tower gets. Verified through Polly and Whisper rather than guessed at.
    cs = intents.normalize_callsign(m.group(1)) if m else "Station calling"
    if m:
        cs = C.parse(cs).spoken or cs
    if _CHECK.search(transcript):
        return f"{cs}, loud and clear."
    if _CLOSE.search(transcript):
        return f"{cs}, roger, welcome, taxi to parking when ready, good day."
    return None

# When woken by a hook (or asked anything) the agent may decide no call is
# warranted; it replies with this and the bridge stays off the air.
NO_CALL = {"(no call)", "no call", "(none)", "standby."}


# "Falcon 1-1" -- the way a callsign is WRITTEN. It must never reach Polly.
_SPOKEN_CALLSIGN = re.compile(r"\b([A-Z][a-z]+)\s+(\d)-(\d)\b")


def _digit_words(digits: str) -> str:
    words = ["zero", "one", "two", "three", "four", "five", "six", "seven",
             "eight", "nine"]
    return " ".join(words[int(d)] for d in digits)


_SENDS_HIM_AWAY = re.compile(
    r"[^.!?]*\b(?:contact|switch to|go to|monitor)\b[^.!?]*"
    r"\b(?:approach|tower|center|centre|departure|ground|sentry)\b[^.!?]*[.!?]?",
    re.I)


def strip_unauthorised_handoff(text: str, authorised, keep_him: str = "") -> tuple[str, str]:
    """Remove a frequency change nobody authorised. Returns (text, what went).

    A HANDOFF IS A CONTROL ACTION, NOT LANGUAGE, and it is the same rule that
    keeps an LLM out of separation: whether this pilot should be worked by
    somebody else depends on where he is, whose airspace that is, and who is
    free to take him -- none of which the model can see. When a handoff is due
    the bridge hands it over as a `HANDOFF:` line. No line, no handoff.

    THE RULES ALREADY SAY SO and it was not enough. Told plainly not to invent
    one, the model obeyed on a dry run and did it anyway on the radio the same
    evening -- to a pilot parked on the ramp, who was sent from Tower to
    Approach, back to Tower, and round again with nowhere to go. A prompt is
    guidance; this is a guarantee, and the difference matters for the same
    reason it matters in the separation engine.

    Deliberately narrow. It removes a SENTENCE that tells him to contact
    somebody, and leaves everything else -- including "this is Batumi Tower, one
    one eight decimal zero", which names the frequency he is ON and is a
    correction rather than a handoff.
    """
    if authorised is not None or not text:
        return text, ""
    gone = []

    def drop(m):
        gone.append(m.group(0).strip())
        return " "
    out = _SENDS_HIM_AWAY.sub(drop, text)
    if not gone:
        return text, ""
    out = re.sub(r"\s{2,}", " ", out).strip()
    # NEVER HAND BACK NOTHING, and never hand back the thing we just refused.
    # When the whole reply was the handoff -- which is the commonest shape, "X,
    # contact Y, good day" -- stripping leaves an empty string, and returning
    # the original would make the guard a no-op in exactly the case it exists
    # for. So the fallback keeps him on this frequency in the plainest words a
    # controller has.
    return (out or keep_him or text), " | ".join(gone)


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
    # NO CANONICAL CALLSIGNS OVER THE AIR. "Falcon 1-1" is how this system
    # WRITES a callsign; Polly reads the hyphen and says "Falcon one TO one",
    # which a pilot hears as a different aeroplane. One path did this and the
    # rest happened to spell it properly, which is luck rather than design --
    # so it is caught here, where every transmission passes, instead of in each
    # place that composes one.
    text = _SPOKEN_CALLSIGN.sub(
        lambda m: f"{m.group(1)} {_digit_words(m.group(2))} "
                  f"{_digit_words(m.group(3))}", text)
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


def _correlated(session_id: str) -> dict:
    """Track label -> the callsign something has correlated it to.

    From the director's `contacts` table, which is where the correlation is
    recorded. Best effort: an untagged picture is a worse picture, never a
    broken one, and this must not be able to fail a transmission.
    """
    if not session_id:
        return {}
    try:
        from sqlalchemy import text

        from marshall.core import db
        with db.session() as s:
            return {label: cs for cs, label in s.execute(text(
                "SELECT callsign, track_label FROM contacts WHERE session_id=:s"),
                {"s": session_id}).all() if cs and label}
    except Exception:
        return {}


def fetch_radar(session_id: str = "", url: str = RADAR_URL,
                timeout: float = 5.0, profile=None, field: str = "") -> Scope:
    """Grab the current scope (tagged with this session's radar-identified
    callsigns) to hand the controller with the pilot's call. Best-effort -- a
    radar hiccup must not eat the transmission."""
    # THE TABLE, AND THE ENDPOINT ONLY WHEN IT CANNOT BE REACHED.
    #
    # `tracks` and `bullseye` are what the endpoint serves from anyway, so
    # asking over HTTP was a round trip to read our own database -- and it kept
    # the prose parser alive, because the payload's `picture` was the only
    # reason anybody ever needed to read English back into structs.
    #
    # The bullseye was the last thing holding this back: it comes from the sim
    # rather than the track stream, so the table did not have it and switching
    # would have blanked the "from bullseye" column -- the reference a pilot's
    # HSI is set to, and the only one that means anything for a contact nobody
    # is working. `feed` stores it now (migration 016).
    #
    # The fallback stays for a bridge with no DSN -- a laptop, the dry-run
    # tools -- and for a database that is unreachable while the director is not.
    # It is a second SOURCE, not a second copy: the same rows either way.
    # THE SPEAKING CONTROLLER'S FIELD, not the profile's. See `field_origin`:
    # without it Kobuleti's controllers measure every range from Batumi.
    origin = field_origin(profile, field) if profile is not None else None
    got = None
    try:
        from marshall.core import scope as _scope
        # BINDINGS, so the picture the MODEL reads still names who we have
        # correlated. Dropping them is what silenced the talk-down: the tag went
        # missing, `radar_fixes` matched nothing, and the controller obediently
        # stopped talking on final. It reads the board now and no longer depends
        # on this -- but the agent still benefits from seeing a contact named,
        # and a picture that quietly stops naming people is a regression whether
        # or not anything downstream currently parses it.
        cs = _scope.contacts(origin=origin, bindings=_correlated(session_id))
        got = {"contacts": cs, "bullseye": _scope.bullseyes(), "picture": ""}
    except Exception:
        got = None
    if got is None:
        q = (f"{url}?{urllib.parse.urlencode({'session_id': session_id})}"
             if session_id else url)
        try:
            with urllib.request.urlopen(q, timeout=timeout) as resp:
                got = json.load(resp)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return Scope("")
    # A Scope IS the prose -- every existing caller keeps working -- and it
    # carries the facts the prose was drawn from, so the geometry can stop
    # parsing it. See the class.
    contacts = got.get("contacts") or []
    # AND WE DRAW IT OURSELVES, from our own field.
    #
    #     "why is that using batumi and not bull?"
    #
    # Because the director was drawing it, and drawing needs an origin it has no
    # business owning. Every range in that prose was measured from a module
    # constant -- Batumi's aerodrome reference -- and the lines came sorted by
    # distance from it, so a controller anywhere else read somebody else's
    # ranges in somebody else's order.
    #
    # The director's `picture` is kept as the fallback for exactly the case that
    # justifies one: no contacts, or no projected field of our own, where
    # drawing from a stale constant beats drawing nothing. Byte-identical for a
    # shared origin -- `tests/test_picture.py` proves it against prose captured
    # from the running director.
    drawn = _picture.picture(contacts, origin) if (contacts and origin) else ""
    return Scope(drawn or got.get("picture", "").strip(),
                 contacts=contacts, origin=origin,
                 bullseye=got.get("bullseye"))


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


# HOW LONG A BOARD ENTRY MAY SURVIVE WITHOUT EVIDENCE.
#
# Long enough that a pilot who goes quiet on a long downwind is never dropped,
# short enough that last sortie's callsign is gone before the next one starts.
STALE_BOARD_SEC = 8 * 60

# (callsign -> when we last had any evidence he exists. Now Bridge.seen_at.)


def note_alive(bridge, callsign: str, now: float | None = None) -> None:
    """He transmitted, or radar painted him."""
    if callsign:
        bridge.seen_at[callsign] = time.time() if now is None else now


# Enough releases to cover a sortie's worth of them without the snapshot
# growing without bound. Nine in one evening is the number this is sized against.
RELEASES_KEPT = 20


def accounted_for(ac, cs: str, here: set, called: set,
                  scope_working: bool = True) -> bool:
    """Is there ANY evidence this board entry is a real aeroplane right now?

    EVERY ROUTE, not the best one. This function replaced a single string
    comparison that was right about one case and silently wrong about the rest,
    and the temptation on finding the better route (the bound track) was to swap
    one for the other. That would have been the same mistake again: dropping an
    entry radar can see is a separation event, so evidence is only ever ADDED
    here. Four ways, any one of which is enough:

      1. Radar identified him. The engine's own flag, set when a controller
         said "radar contact", and nothing on a scope can contradict it.
      2. His bound track is on the picture. The strongest, because both sides
         are the sim's own string and no derivation happens at all -- but it
         needs `Controller.bind` to have run, so it is not always available.
      3. A label on the picture DERIVES to his key. "362nd_Sockeye" -> "Sockeye",
         which is what the board is keyed on. This is the one that was missing:
         it is how a man on the scope at 0.4 nm was dropped nine times in one
         sortie while the comparison asked whether "sockeye" equalled
         "362ndsockeye".
      4. His key is a label outright. Only true when the sim's name for an
         aeroplane happens to be its callsign -- an AI flight, and every fixture
         written before the distinction was understood.
    """
    if getattr(ac, "track", "") and _key_name(ac.track) in here:
        return True
    if _key_name(cs) in called or _key_name(cs) in here:
        return True
    # `radar_identified` IS HISTORY, NOT OBSERVATION -- it means "a controller
    # said radar contact", which was true once and says nothing about now.
    # Treating it as present-tense evidence made every aircraft that had ever
    # been identified IMMORTAL: two landed pilots sat on the board as `unseen`
    # ghosts with nothing in the sim, and `release_stale` refused to touch them
    # because the flag was still set from an hour earlier.
    #
    # It is still worth something, but only when the scope is EMPTY. An absent
    # answer is not a negative answer: radar hiccups, the director restarts, the
    # sim pauses -- and dropping a live aeroplane because one poll came back
    # blank is the failure this whole function was written to prevent.
    #
    # So: if the picture has ANY aircraft on it, radar is working and his
    # absence from it is real. If the picture is empty we know nothing, and the
    # flag buys him the benefit of the doubt.
    return bool(ac.radar_identified and not scope_working)


def release_stale(bridge, ctl, scope: str = "", now: float | None = None) -> list[str]:
    """Drop board entries nothing can account for any more.

    THE PROBLEM THIS SOLVES, and it is not hypothetical: a pilot flew as
    Falcon 1-1, landed, left the slot, and came back an hour later as Pony 1-1.
    Falcon 1-1 stayed on the board -- and TWO ENTRIES ARE WHAT MAKES THE
    DETERMINISTIC ENGINE ENGAGE, so a single-ship approach became a sequencing
    problem between a pilot and his own former self: assigned ten thousand,
    held at five, banished to Kobuleti, all over the top of correct vectors.

    WHY NOT THE DEPARTURE EVENT, which the sim publishes and which says exactly
    this. Because the two identifiers do not join. `player_leave_unit` names
    the UNIT ("Pony 1-1"); the radar picture labels a manned contact by PLAYER
    ("362nd_sockeye"), and that is what identity resolves a track to. Matching
    on the player instead was a live outage -- a pilot's own track matches every
    slot he has EVER left, so his identity was released and re-derived every
    two seconds, his callsign flickered between the one he had an hour ago and
    the one he was using, and the board emptied under a live approach. The
    person is precisely the thing that persists across a slot change.

    So this asks the question that needs no join: is there any evidence this
    aeroplane still exists? Radar sees him, or he has spoken recently. Neither,
    for eight minutes, and he comes off. It cannot misfire on somebody flying,
    because flying is what the evidence IS. See [#41] for doing it properly on
    the event once the identifiers are reconciled.
    """
    t = time.time() if now is None else now
    # THE BOARD'S OWN TRACKS AGAINST THE SCOPE'S OWN NAMES. Both sides are the
    # sim's string for the aeroplane, so this is an identity comparison and not
    # a join.
    #
    # It used to ask `_key_name(cs) in here` -- the board KEY against the scope
    # LABEL, "sockeye" against "362ndsockeye", which can never be equal. So
    # nothing ever accounted for a man radar could see and he aged off the board
    # nine times in one sortie, at 0.4 nm, with the aeroplane on the scope. A
    # board entry vanishing under a live approach is a separation fact.
    on_scope = identity.units_on(scope)
    here = {_key_name(u.name) for u in on_scope}
    # AND WHAT EACH OF THOSE LABELS IS CALLED. "362nd_Sockeye" derives to
    # "Sockeye", which IS the board's key -- so this is the join done once, by
    # the same function the untracked table uses, rather than a comparison
    # between two names that were never going to be equal.
    called = {_key_name(_derived_callsign(u.name))
              for u in on_scope if not u.category}
    for cs, ac in list(ctl.aircraft.items()):
        # Start the clock the first time we ever see an entry, so one that
        # arrives with no evidence at all still ages out. Without this the
        # default "assume seen now" made every unaccounted entry immortal --
        # which is precisely the leftover this exists to remove.
        bridge.seen_at.setdefault(cs, t)
        if accounted_for(ac, cs, here, called, bool(here)):
            bridge.seen_at[cs] = t
    freed = []
    for cs in list(ctl.aircraft):
        if t - bridge.seen_at.get(cs, t) <= STALE_BOARD_SEC:
            continue
        # WHAT WAS ON THE SCOPE WHEN HE CAME OFF IT, kept with the release.
        #
        # A GUARD HERE WOULD BE DEAD CODE, and writing one first is how I found
        # that out. "Refuse to release while radar paints him" reads like the
        # obvious safety net, but the refresh loop above asks `accounted_for`
        # already -- so anything radar can account for has had its clock reset
        # and cannot reach this line. The net could never catch anything.
        #
        # And the failure it was meant to catch is exactly the one it cannot
        # see: the entries that get dropped wrongly are the ones our own
        # matching failed to relate to a contact, and a second call to the same
        # matcher fails the same way. There is no automatic version of this.
        #
        # So publish the evidence instead and let a human be the guard. A row
        # saying "released Sockeye; the scope held 362nd_Sockeye" is the whole
        # bug, legible at a glance, on the page somebody is already reading.
        ac = ctl.aircraft.get(cs)
        if ctl.release(cs):
            bridge.releases.append(
                {"callsign": cs, "track": getattr(ac, "track", ""),
                 "at": t, "scope": sorted(u.name for u in on_scope
                                          if not u.category)})
            del bridge.releases[:-RELEASES_KEPT]
            bridge.seen_at.pop(cs, None)
            freed.append(cs)
    return freed


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

# WHAT IS STILL A MODULE GLOBAL, AND WHY EACH ONE IS RIGHT TO BE. Eighteen of
# these became `Bridge` fields on 30 July; four did not, and they are not
# leftovers:
#
#   _lock_fd        the frequency lock's file descriptor, held open for the life
#                   of the PROCESS. Per-process is what it means.
#   _heard_names    the mission roster -- names allowed to become an aeroplane
#                   on one transmission. A property of the mission, not of a
#                   frequency, and two bridges flying the same mission should
#                   agree about it.
#   _plan_labels    filed plan labels, read once from the director.
#   _filed          the filed strips, with the timestamp of the read.
#
# The last two are caches of DIRECTOR state. The director is shared, so caching
# it per bridge would fetch the same rows twice and let two bridges disagree
# about what is on file. Moving them would be finishing the job wrongly.


class Bridge:
    """Everything ONE bridge knows, for one frequency. [LAYERS.md] step 2.

    These were three module globals, which is the same as saying there could
    only ever be one of each: one identity registry, one flight roster, one
    board-freshness clock, for the whole process. That is fine while there is
    one field and one frequency, and it is the wall in front of a second --
    [ARCH-1] / #2 is usually described as "_run_srs holds a single profile",
    but the profile was never the only singleton.

    Held rather than global so a second bridge -- another field, another
    frequency, a test -- has its own. The stages take it as an argument, which
    is also what makes them testable without reaching into a module to reset
    state between cases.
    """

    def __init__(self):
        self.identity = identity.Registry()
        self.flights = fl.Roster()
        # When each board entry was last accounted for. See release_stale.
        self.seen_at: dict[str, float] = {}
        # WHO CAME OFF THE BOARD, AND WHAT WAS ON THE SCOPE WHEN HE DID.
        #
        # A release is the one board event with no trace of itself: the entry is
        # gone, so afterwards nothing can be asked why. `HANDOFF-board.md`
        # documents nine wrong ones in a single sortie, found by grepping a log
        # nobody reads, and the reason they were invisible is that the evidence
        # died with the row.
        #
        # Kept WITH the scope contents, because that is what makes a wrong
        # release self-evident: "released Sockeye; the scope held 362nd_Sockeye"
        # is the entire bug on one line. No judgement is applied here -- the
        # matcher that would judge it is the thing under suspicion.
        self.releases: list[dict] = []
        # WHAT THIS RADIO HAS BEEN DOING. All per-frequency, all previously
        # module globals -- which meant two bridges in one process would have
        # shared one pilot's conversation window, one readback queue and one
        # callsign vote. See [LAYERS.md] step 2.
        self.transmitters: dict[str, str] = {}     # GUID -> voted callsign
        self.order: dict = {}                      # per-GUID recency, tie-break
        self.last_heard: dict[str, float] = {}     # per RADIO, not per callsign
        self.heard_on: dict[str, float] = {}       # which channel he was on
        self.awaiting_readback: dict[str, float] = {}
        # (GUID, wrong name) already corrected. A callsign nobody answers to is
        # worth telling him about ONCE; saying it again on every transmission
        # would fill the frequency with the correction instead of the approach,
        # and he has already heard it. See `misnamed`.
        self.corrected: set = set()
        # The handoff the BRIDGE authorised for this turn, or None. Read by the
        # transmit path, which refuses to let the agent invent one -- see
        # `strip_unauthorised_handoff`. A one-element list for the same reason
        # `last_said` is: written on the pilot thread, read on the scheduler's.
        self.handoff_due: list = [None]
        self.last_said: list[str] = [""]
        self.last_active_hz: list[float | None] = [None]
        # PER AIRCRAFT, AND THIS IS NOT THEIR RIGHT HOME. What we last told each
        # aeroplane to fly, the speed we asked for and when, and whether he is
        # latched onto the missed approach -- all keyed by callsign, so they
        # belong on `controller.Aircraft` beside his phase and his level.
        #
        # They cannot go there yet. `controller.py` is BLIND by design -- "no
        # telemetry, no radar, no connection to DCS; its whole world model is
        # what pilots report plus a clock" -- and every one of these is derived
        # from RADAR. Putting them on the board would be smuggling the scope
        # into the blind engine, which is exactly the thing that already
        # produced `seen_on_final`, `note_radar_contact` and `release_stale`.
        #
        # So they sit here, which is at least per-bridge rather than
        # per-process, and they move to the aircraft when the engine is allowed
        # to see -- [LAYERS.md] violation 6, which goes last and alone because
        # it is a behaviour change wearing an architecture hat.
        self.issued: dict[str, set[str]] = {}
        self.speed_asked: dict[str, tuple[float, float]] = {}
        self.flying_missed: set[str] = set()
        self.missed_count: dict[str, int] = {}




def _track_of(scope: str, handle: str) -> str:
    """The scope label whose handle is this person.

    Reads `units_on`, which reads structure when the Scope has it -- so this
    finds a wingman now, where the prose collapsed him into his lead.
    """
    for u in identity.units_on(scope):
        if identity.handle(u.name).lower() == (handle or "").lower():
            return u.name
    return ""


def _track_tagged(scope: str, spoken: str) -> str:
    """The unit radar has tagged with this callsign, if any.

    The inverse of `_track_of`, and the only legitimate use left for a spoken
    callsign at this layer: not to NAME anybody, but to find the aeroplane an
    earlier correlation hung that name on, so it can be worked under its handle.
    """
    from marshall.atc import callsign as C
    # A SCOPE WITH CONTACTS IS NOT AN EMPTY SCOPE, however the prose reads.
    # `Scope` is a str subclass, so `not scope` asks about the PICTURE -- and a
    # picture can be empty while the facts behind it are not (a controller with
    # no projected field of his own draws nothing, and the tests build scopes
    # from contacts alone). Reading the string here made the structured path
    # unreachable in exactly those cases, silently, and it is the same shape as
    # the bug it replaced: asking prose a question the data can answer.
    if not (scope or getattr(scope, "contacts", None)) or not spoken:
        return ""
        return ""
    me = C.parse(spoken)
    # NO FLATTENING when the Scope carries structure: nothing was collapsed, so
    # there is nothing to undo. `flatten_formation` exists only to paper over
    # the lossy string and goes when the last prose reader does.
    src = scope if getattr(scope, "contacts", None) else identity.flatten_formation(scope)
    tagged = [u for u in identity.units_on(src) if u.callsign]
    # THE SAME TWO PASSES AS `radar_fix`, and deliberately so -- if this
    # disagreed with it about which aeroplane a callsign means, the engine
    # would be keyed on one contact and guided from another. Exact first;
    # a FLIGHT tag only as a fallback, because a formation is tagged once and
    # its members have no track of their own, so "Pony 1-3" legitimately finds
    # "Pony one flight" while it must never find Pony 1-2's own track.
    for u in tagged:
        if C.parse(u.callsign).canonical.lower() == me.canonical.lower():
            return u.name
    for u in tagged:
        c = C.parse(u.callsign)
        if c.is_flight and c.flight.lower() == me.flight.lower():
            return u.name
    # A FLIGHT-MATE'S TAG, but only when radar says they are actually FLYING as
    # a formation -- which is a fact we hold now and could only guess at from
    # prose. The old rule had to refuse this outright, and the comment on
    # `radar_fix` says why: "two pilots who merely share a flight NUMBER are a
    # different case entirely, and the scope says which is which". It does, in a
    # field. So Pony 1-3 finds the section he is welded to, and Falcon 1-1 still
    # never gets Falcon 1-2's track, because two singles are in no formation.
    by_name = {_key_name(c.get("name", "")): c
               for c in (getattr(scope, "contacts", None) or [])}
    for u in tagged:
        c = C.parse(u.callsign)
        got = by_name.get(_key_name(u.name)) or {}
        if got.get("formation") and c.flight.lower() == me.flight.lower():
            return u.name
    return ""


def _between(scope, a_track: str, b_track: str):
    """Separation of two tracks from their own coordinates.

    NEEDS NO ORIGIN, which is the tell that the old version should never have
    been doing polar-to-cartesian on ranges from somebody else's beacon: the
    gap between two aeroplanes is a fact about the two of them. It also works
    for a wingman, who under the prose had no position at all.
    """
    a = scope.of(a_track) if hasattr(scope, "of") else None
    b = scope.of(b_track) if hasattr(scope, "of") else None
    if not a or not b or a.get("lat") is None or b.get("lat") is None:
        return None
    return _range_radial((a["lat"], a["lon"]), b["lat"], b["lon"])[0]


def miles_between(scope: str, a_track: str, b_track: str) -> float | None:
    """How far apart two contacts are, from the radar picture alone.

    Structure first ([#47]) -- see `_between`, which needs no origin. The prose
    path below is the fallback: both positions are a range and a radial from the
    field, so it is two polar-to-cartesian conversions and a hypotenuse, and it
    silently returns None for any wingman. Returns None when either
    aeroplane is not on the scope -- which the caller must not read as zero:
    "I cannot see you both" and "you are together" are opposite answers.
    """
    import math
    # STRUCTURE FIRST. Exact for any pair, wingmen included, and computed from
    # the two aeroplanes rather than from their ranges off a third point.
    exact = _between(scope, a_track, b_track)
    if exact is not None:
        return exact
    pos, offset = _scope_geometry(scope)
    a, b = _key_name(a_track), _key_name(b_track)
    p, q = pos.get(a), pos.get(b)
    if p is not None and q is not None:
        return math.hypot(p[0] - q[0], p[1] - q[1])

    # ONE OF THEM IS A WINGMAN, and the picture prints a formation as one
    # contact -- so he has no position of his own, only a lead and a distance
    # off it. That is enough, and it is the case the join rule actually runs
    # in: a man asks to join the flight he has just formed on.
    #
    # Where the exact gap is not recoverable the answer is an UPPER BOUND, and
    # the direction matters. Every caller compares against a radius and refuses
    # when it is exceeded, so over-estimating costs a false refusal -- he says
    # it again, or closes up -- while under-estimating puts a man in a formation
    # radar cannot confirm he is in. Refusing is the recoverable mistake.
    la, da = offset.get(a, (None, None))
    lb, db = offset.get(b, (None, None))
    if la is not None and la == b:
        return da                          # he is a wingman of the other
    if lb is not None and lb == a:
        return db
    if la is not None and lb is not None and la == lb:
        return None if da is None or db is None else da + db
    # A wingman and somebody else entirely: his lead's position plus his own
    # offset bounds it.
    if la is not None and da is not None and q is not None \
            and (r := pos.get(la)) is not None:
        return math.hypot(r[0] - q[0], r[1] - q[1]) + da
    if lb is not None and db is not None and p is not None \
            and (r := pos.get(lb)) is not None:
        return math.hypot(r[0] - p[0], r[1] - p[1]) + db
    return None


def _scope_geometry(scope: str) -> tuple[dict, dict]:
    """Where everything is: absolute fixes, and wingmen as lead-plus-offset.

    Two dictionaries because a formation genuinely has two kinds of member. The
    lead has a range and a radial from the field like any other contact; the
    others have only "0.3 nm off him", which is what the picture prints and all
    it can print without un-collapsing the formation the controller reads as one
    thing.
    """
    import math
    pos: dict[str, tuple[float, float]] = {}
    offset: dict[str, tuple[str, float]] = {}
    for chunk in (scope or "").split("|"):
        m = _FIX_BY_TRACK.search(identity.flatten_formation(chunk))
        if not m:
            continue
        tag, nm, radial = m.group(1), m.group(2), m.group(3)
        lead = _key_name(tag)
        r, th = float(nm), math.radians(float(radial))
        pos.setdefault(lead, (r * math.cos(th), r * math.sin(th)))
        fm = identity._FORMATION.search(chunk)
        if not fm:
            continue
        for ship in identity._split_ships(fm.group(1)):
            om = identity._OTHER_SHIP.match(ship)
            if not om:
                continue
            k = _key_name(om.group(1) or "")
            gap = re.search(r"([\d.]+)\s*nm", om.group(2) or "")
            if k and k != lead and k not in offset:
                # None, NOT ZERO, when the picture does not print the offset.
                # The bridge and the director are separate deployables and one
                # can be restarted without the other, so an older picture with
                # no offsets is a real thing to be handed -- and reading it as
                # zero says "they are touching" when what we know is only "they
                # are inside the formation threshold", which is twice the join
                # radius. That is the under-estimate that joins a man to a
                # flight radar cannot confirm he is with.
                offset[k] = (lead, float(gap.group(1)) if gap else None)
    return pos, offset


def transmitter_callsign(bridge, guid: str | None, transcript: str) -> str:
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
    seen = bridge.transmitters.setdefault(guid, Counter())
    order = bridge.order.setdefault(guid, {})

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

_SHIPS = re.compile(r"(\d+)\s+ships\b", re.I)


def count_contacts(scope: str) -> int:
    """How many AIRCRAFT the scope is showing, not how many lines it has.

    Radar collapses a formation into one line ("... IN FORMATION with ... — 4
    ships ..."), which is right for the controller to read but wrong to count:
    the bridge engages the deterministic separation engine at two or more
    contacts, so counting lines makes a four-ship look like a single ship and
    switches the engine OFF for the one arrival that most needs sequencing.
    """
    if not getattr(scope, "contacts", None) and (not scope or scope == "no contacts"):
        return 0
    # AIRCRAFT ONLY, since 30 July. This counted every line, so four T-55s
    # parked seventy miles away made `engaged` true for a lone pilot -- which
    # switched the separation engine on to sequence him against armour, and
    # routed every transmission including a radio check through the 2.2-second
    # intent classifier. Measured: one pilot alone counted 1; the same pilot
    # with that armour counted 5. Audit #45.
    #
    # The category comes from the streamer, which has always known it and used
    # to discard it before the picture was rendered.
    # NO SHIP-COUNT ARITHMETIC ANY MORE. `units_on` returns every aeroplane in
    # a formation as its own unit -- it has since the formation parser was
    # fixed on 29 July -- so counting the "N ships" text as well counted each
    # formation twice over. Count the units.
    return sum(1 for u in identity.units_on(scope) if not u.category)


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


def _type_of(scope, track: str) -> str:
    """Airframe from the contact, not from a regex over the parenthetical."""
    c = scope.of(track) if hasattr(scope, "of") else None
    return (c or {}).get("type", "")


def aircraft_type_on_scope(scope: str, cs: str) -> str:
    """What HE is flying, off the radar line. "" when the scope does not say."""
    from marshall.atc import callsign as C
    # THE AEROPLANE, NOT THE FLIGHT -- the same word that gave two pilots each
    # other's position gave them each other's AIRFRAME, which decides the speed
    # he is assigned and what he can receive. A wingman in a Mustang beside a
    # lead in a Viper would have been told to fly three hundred knots.
    me = C.parse(cs)
    rows = _TYPE.findall(identity.flatten_formation(scope or ""))
    hits = [r for r in rows
            if C.parse(r[0]).canonical.lower() == me.canonical.lower()]
    if not hits:
        hits = [r for r in rows
                if C.parse(r[0]).is_flight
                and C.parse(r[0]).flight.lower() == me.flight.lower()]
    for _tag, typ in hits:
        if True:
            # "(P-51D-30-NA, manned)" -- the marker saying a human is in it
            # rides in the same brackets, and everything downstream looks the
            # type up by EXACT string. Left on, it turned a Mustang into an
            # unknown airframe, which falls back to "assume modern" -- so the
            # controller believed a 1944 fighter carried TACAN, ILS and an
            # inertial platform, and would have offered it a hold on a station
            # it cannot receive.
            return typ.split(",")[0].strip()
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


# The same line, found by the UNIT NAME instead of the callsign tag. The tag is
# a label and the unit name is the track, and only one of those can be wrong.
_FIX_BY_TRACK = re.compile(
    r"([^|\[(]+?)\s*(?:\[[^\]]*\])?\s*\([^)]*\)\s*:"
    r"[^|]*?(\d+(?:\.\d+)?)\s*nm[^|]*?on the (\d+)\s*radial"
    r"[^|]*?([\d,]+)\s*ft(?:[^|]*?heading\s*(\d+))?"
    r"(?:[^|]*?(\d+)\s*knots)?", re.I)


# The second copy, gone. Its own docstring said a THIRD one was wrong -- "the
# same error is still open on the paper nav log" -- so somebody found the
# correct implementation, knew another was broken, and made a copy rather than
# one home. See `core.geo`.
_range_radial = _geo.range_bearing_true


def radar_fix_by_track(scope: str, track: str, profile=None) -> object | None:
    """Where he is, found by the TRACK the identity ladder resolved.

    The callsign lookup below searches the scope for a bracketed tag, which is
    a LABEL -- and a label can be stale, mis-heard, or simply not yet applied.
    That is not theoretical: a pilot checked in as Pony 1-1, renamed himself
    Falcon 1-1, and radar tagged his track "Falcon one one" while the engine
    went on looking for "Pony 1-1". It found nobody, so he was told he was not
    radar identified for an entire approach -- with a clean, correct radar line
    for him sitting in the picture the whole time.

    The track has no such failure mode. It is the sim's own unit name, it is
    never spoken, and identity.py has already resolved which one this radio is
    in. Asking the geometry by track rather than by name closes the gap between
    the two halves of that work.

    It also finds an UNTAGGED contact, which the callsign regex cannot do at
    all -- it requires the brackets, so an aeroplane nothing has correlated yet
    is invisible to it even when radar can see him perfectly.
    """
    if not track:
        return None
    from marshall.atc import asr
    # STRUCTURE FIRST ([#47]). The contact carries an absolute position and the
    # Scope carries this controller's own origin, so the range is computed here
    # rather than read out of prose that measured it from another process's
    # module constant. Falls through to the regex when either is missing -- an
    # older director, or a radar hiccup -- until the parsers are deleted.
    c = scope.of(track) if isinstance(scope, Scope) and scope.origin else None
    if c is not None and c.get("lat") is not None:
        nm, radial = _range_radial(scope.origin, c["lat"], c["lon"])
        h = c.get("heading") or 0.0
        return asr.Position(nm, radial, int(c.get("alt_ft") or 0),
                            true_heading(h, profile) if profile else h,
                            c.get("speed_kt") or 0.0)
    want = _key_name(track)
    for name, nm, radial, alt, hdg, kt in _FIX_BY_TRACK.findall(
            identity.flatten_formation(scope or "")):
        if _key_name(name) != want:
            continue
        h = float(hdg) if hdg else 0.0
        return asr.Position(float(nm), float(radial), int(alt.replace(",", "")),
                            true_heading(h, profile) if profile else h,
                            speed_kt=float(kt) if kt else 0.0,
                            type=aircraft_type_on_scope(scope, "") or "")
    return None


def said_who(transcript: str, names: list[str]) -> bool:
    """Did he identify himself in this transmission?

    A HANDLE IS A CALLSIGN. `callsign.extract` wants the numbered shape --
    "Pony 1-1" -- so "Batumi Approach, Sockeye, request creation of Apex
    flight" read as a man who had not said who he was, and he was challenged
    for the name he had just given. Under the flight model that is backwards: a
    person IS his handle, only a flight has a name of its own, and "Sockeye" is
    complete self-identification.

    Matched against the CLOSED SETS -- the flights that exist and the handle
    this radio resolved to -- and never against open English, which is the rule
    the whole design rests on.
    """
    from marshall.atc import callsign as _C
    if _C.extract(transcript or ""):
        return True
    return any(re.search(rf"\b{re.escape(n)}\b", transcript or "", re.I)
               for n in names if n)


# The same squash the rest of the system uses. See `core.names`: this was the
# second of three copies, and they disagreed on every non-ASCII name.
_key_name = _names.squash


def radar_fix(scope: str, cs: str, profile=None) -> object | None:
    """Range, radial, altitude and heading of the track bound to this callsign.

    Only radar-IDENTIFIED contacts (the [tagged] ones) -- guidance computed from
    a blip that might not be him is worse than no guidance, because it sounds
    exactly as confident.
    """
    # A SCOPE WITH CONTACTS IS NOT AN EMPTY SCOPE, however the prose reads.
    # `Scope` is a str subclass, so `not scope` asks about the PICTURE -- and a
    # picture can be empty while the facts behind it are not (a controller with
    # no projected field of his own draws nothing, and the tests build scopes
    # from contacts alone). Reading the string here made the structured path
    # unreachable in exactly those cases, silently, and it is the same shape as
    # the bug it replaced: asking prose a question the data can answer.
    if not (scope or getattr(scope, "contacts", None)) or not cs:
        return None
        return None
    from marshall.atc import asr, callsign as C
    me = C.parse(cs)
    # STRUCTURE FIRST ([#47]), with the same two passes the prose path uses
    # below: his own tagged contact, then the FLIGHT tag, never another
    # member's. Reading the contacts also fixes finding 1.3 for wingmen -- the
    # regex needs a bracketed tag on a LINE, and a formation prints one line,
    # so only a lead could ever be found.
    got = getattr(scope, "contacts", None)
    if got:
        tagged = [c for c in got if c.get("callsign")]
        hit = next((c for c in tagged
                    if C.parse(c["callsign"]).canonical.lower()
                    == me.canonical.lower()), None)
        if hit is None:
            hit = next((c for c in tagged
                        if C.parse(c["callsign"]).is_flight
                        and C.parse(c["callsign"]).flight.lower()
                        == me.flight.lower()), None)
        if hit is not None and hit.get("lat") is not None and getattr(
                scope, "origin", None):
            nm, radial = _range_radial(scope.origin, hit["lat"], hit["lon"])
            h = hit.get("heading") or 0.0
            return asr.Position(nm, radial, int(hit.get("alt_ft") or 0),
                                true_heading(h, profile) if profile else h,
                                hit.get("speed_kt") or 0.0)
    # THE AEROPLANE, NOT THE FLIGHT. This matched on `.flight`, and Falcon 1-1
    # and Falcon 1-2 ARE THE SAME FLIGHT -- so with two pilots up, each one's
    # lookup returned whichever of them appeared first in the picture. Every
    # range, every off-course call and every altitude for one was computed from
    # the other's position.
    #
    # Live, with two humans on the frequency: one was told "one mile from the
    # runway, descend to minimums" at thirty six miles, while the other was
    # told he was thirty eight miles northwest and not on final -- as he
    # touched down. It reads as the controller having lost his mind, and it is
    # a single word.
    #
    # A JOINED WINGMAN STILL USES HIS FLIGHT'S TRACK, and that is not the same
    # thing. Four aeroplanes in formation are ONE contact -- only the flight is
    # tagged, the members have no track of their own, and asking for Pony 1-3
    # must find it. Two pilots who merely share a flight NUMBER are a different
    # case entirely, and the scope says which is which:
    #
    #     if he has his own tagged track, he is his own aeroplane.
    #
    # So EXACT first, across the whole picture, and the flight only as a
    # fallback when nothing matched him individually. That keeps the formation
    # behaviour the tests were written for and stops two humans being handed
    # each other's geometry.
    rows = _FIX.findall(identity.flatten_formation(scope))
    hits = [r for r in rows
            if C.parse(r[0]).canonical.lower() == me.canonical.lower()]
    if not hits:
        # ONLY A FLIGHT TAG, never another member's. A formation is tagged with
        # the FLIGHT designator and its members have no track of their own, so
        # Pony 1-3 legitimately finds "Pony one flight". Falling back to any
        # matching flight number would hand Falcon 1-1 the track of Falcon 1-2,
        # which is the bug this whole change is about.
        hits = [r for r in rows
                if C.parse(r[0]).is_flight
                and C.parse(r[0]).flight.lower() == me.flight.lower()]
    for _tag, nm, radial, alt, hdg, kt in hits:
            h = float(hdg) if hdg else 0.0
            return asr.Position(float(nm), float(radial),
                                int(alt.replace(",", "")),
                                true_heading(h, profile) if profile else h,
                                speed_kt=float(kt) if kt else 0.0,
                                type=aircraft_type_on_scope(scope, cs))
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


def radar_fixes(scope: str, profile=None, ctl=None) -> list[tuple[str, object]]:
    """Every aircraft we can talk down, as (callsign, Position).

    THE BOARD, NOT A BRACKET IN THE PROSE. This used to match `[Sockeye]` in the
    rendered picture with a regex, which meant the talk-down could only find
    somebody the DIRECTOR had tagged -- a weaker correlation than the one the
    bridge already holds, and one that vanishes the moment the picture is drawn
    without bindings.

    That is exactly what happened on 31 July: `fetch_radar` moved to reading the
    tracks table and stopped passing bindings, so every contact rendered
    untagged, this returned an empty list, and the automatic talk-down went
    silent for a whole sortie -- while the controller was being told "the
    talk-down is being transmitted automatically every mile, do NOT repeat his
    range". It obeyed, and nothing filled the silence. The pilot noticed before
    any test did.

    The board already knows `Sockeye -> 362nd_sockeye` with authority `radar`.
    Reading it is both stronger evidence and immune to how the picture is drawn.

    Untagged blips are still skipped, for the original reason: an unidentified
    aircraft on final is not somebody we can talk to, and guessing produces a
    confident call to the wrong man. "Unidentified" now means "not on the
    board", which is the same question asked of a better source.
    """
    from marshall.atc import asr
    if ctl is not None:
        out = []
        for row in ctl.board():
            cs, track = row.get("callsign", ""), row.get("track", "")
            if not (cs and track):
                continue
            fix = radar_fix_by_track(scope, track, profile)
            if fix is not None:
                out.append((cs, fix))
        return out
    # NO BOARD TO ASK -- the dry-run tools and the older tests. The prose path
    # stays for them and dies with the last caller that cannot supply one.
    out = []
    for tag, nm, radial, alt, hdg, kt in _FIX.findall(
            identity.flatten_formation(scope or "")):
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


# SPEED CONTROL.
#
#     "An airplane going any speed should get sequenced. If that's not
#      reasonable, have the controller tell the aircraft to slow down. It's not
#      reasonable to fly an approach at 500 kts anyway."
#
# Both halves of that are right, and the second is the one that was missing.
# route.py has always known what speed each leg wants -- `speed_kt_at`, which
# the descent planner and the mission's AI tasking both read -- and the
# controller had no way to SAY it. So an F-16 arriving at three hundred knots
# was flown as though it were a Mustang at a hundred and fifty, and the base
# turn to final that works at pattern speed overshoots at twice it (#39).
#
# Speed is the cheapest instrument a controller has. It is also the realistic
# one: real approach control assigns speed on nearly every vector, and a pilot
# who is asked to slow down is being helped rather than corrected.
SPEED_TOLERANCE_KT = 30.0     # below this he is fast, not wrong -- do not nag
SPEED_REPEAT_SEC = 75.0       # ...and do not say it again every radar sweep

# Callsign -> (speed we asked for, when). Repetition is the failure mode here:
# the guidance is recomputed on every transmission, so an unguarded instruction
# is repeated in every single call and reads as the controller not listening.


def speed_instruction(bridge, g, pos=None, cs: str = "", now: float | None = None,
                      aircraft_type: str = "") -> str:
    """"reduce speed to one eight zero" -- when, and only when, it is needed.

    Silent unless the sim gives a real groundspeed AND the leg wants one AND he
    is meaningfully faster than it. Guessing at a speed he might be doing would
    be worse than saying nothing: an instruction to slow down issued to an
    aeroplane already at approach speed is a controller who cannot see.

    TWO THINGS KEEP IT SAFE, and the second matters more than the first.

    The floor is per-airframe, because the published profile's 174 knots is the
    P-51's and an F-16 is on the back side of the drag curve there. See
    equipment.MIN_VECTOR_KT.

    And on FINAL the controller stops assigning speed at all. This is not a
    concession, it is how it is done: the pilot knows his aeroplane's approach
    speed, its fuel state and what it is carrying, and the controller knows
    none of those. Speed control exists to fix the geometry of the turn onto
    final, and once he is on final there is no geometry left to fix. "Resume
    normal speed" is a real instruction and this is the moment for it.
    """
    from marshall.atc import controller as ctl, equipment as E
    phase = str(getattr(g, "phase", "") or "")
    if phase in ("final", "map", "missed"):
        # Release him ONCE, and only if we actually had him restricted --
        # "resume normal speed" to a pilot who was never given a speed is a
        # controller answering a question nobody asked.
        if bridge.speed_asked.pop(cs, None):
            return ", resume normal speed"
        return ""
    want = float(getattr(g, "speed_kt", 0.0) or 0.0)
    have = float(getattr(pos, "speed_kt", 0.0) or 0.0) if pos is not None else 0.0
    if want > 0:
        want = E.safe_speed_kt(want, aircraft_type)
    if want <= 0 or have <= 20 or have <= want + SPEED_TOLERANCE_KT:
        return ""
    t = time.time() if now is None else now
    asked, when = bridge.speed_asked.get(cs, (0.0, 0.0))
    if abs(asked - want) < 10 and t - when < SPEED_REPEAT_SEC:
        return ""                       # already told him, and it still stands
    bridge.speed_asked[cs] = (want, t)
    return f", reduce speed to {ctl.spell_speed(want)} knots"


# A talkdown call the AGENT should never have made: a range, or a heading, while
# the engine owns the approach.
_TALKDOWN_WORDS = re.compile(
    r"\b(miles? from the runway|of course|come (?:left|right)|"
    r"turn (?:left|right) heading|fly heading|heading (?:one|two|three|zero|"
    r"four|five|six|seven|eight|niner)\b|descend (?:and maintain |to )|"
    r"altitude should be)", re.I)


# What we last TOLD each aeroplane to fly. Not what we want him to fly now --
# those are different things and confusing them is a bug with a name.
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


def note_issued(bridge, cs: str, said: str) -> None:
    """Remember the numbers in an instruction, so a read-back can be judged
    against what he was ACTUALLY given."""
    if not cs or not said:
        return
    # HIS OWN CALLSIGN IS NOT AN INSTRUCTION. "Falcon one one" carries a 11,
    # and without removing it every transmission he makes "matches" the last
    # thing we said, including "say again".
    got = _spoken_numbers(said) - _callsign_numbers(cs)
    if got:
        bridge.issued[cs] = got


def reads_back_what_we_said(bridge, cs: str, transcript: str) -> bool:
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
    want = bridge.issued.get(cs)
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


def asr_call(bridge, cs: str, g, pos=None, profile=None) -> str:
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
    # Appended to the ALTITUDE clause rather than made its own transmission:
    # a controller says "descend to two thousand, reduce speed to one eight
    # zero" in one breath, and an extra call per sweep would crowd a frequency
    # that already carries a range every mile.
    alt += speed_instruction(bridge, g, pos, cs,
                             aircraft_type=getattr(pos, "type", "") or "")
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


def vector_call(bridge, cs: str, g, pos=None) -> str:
    """An unprompted turn, issued because he has reached the point -- not
    because he said something."""
    from marshall.atc import callsign as C, controller as ctl
    who = C.parse(cs).spoken
    turn = f"turn {g.turn} " if g.turn else "fly "
    alt = f", maintain {ctl.spell_alt(g.altitude_ft)}" if g.altitude_ft else ""
    # The turn onto base is where speed matters most: it is the leg the
    # overshoot happens on, and a man told to slow down BEFORE the turn can
    # make it. Told during it, he cannot.
    alt += speed_instruction(bridge, g, pos, cs,
                             aircraft_type=getattr(pos, "type", "") or "")
    # Rounded to five while vectoring. A pilot repositioning has to set this on
    # a gyro and read it back, and "one three zero" is easier to do both with
    # than "one two eight" -- which is also how it is issued for real.
    hdg = int(round(g.heading / 5.0)) * 5 % 360
    return f"{who}, {turn}heading {ctl.spell_hdg(hdg)}{alt}."


# What "he is on the ground" looks like on radar. Generous on altitude because
# Batumi is near sea level, and strict on speed because that is the half that
# actually separates taxiing from flying.
GROUND_ALT_FT = 200
GROUND_SPEED_KT = 60


def asr_context(profile, scope: str, cs: str, track: str = "") -> str:
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
    # Track first: this is the guidance a pilot actually hears, and it was
    # silently unavailable for a whole approach because the label had gone
    # stale while radar could see him perfectly.
    pos = radar_fix_by_track(scope, track, profile) or radar_fix(scope, cs, profile)
    if pos is None:
        return ""
    # ON THE GROUND IS NOT A PHASE OF FLIGHT.
    #
    # After landing, the geometry still reads "past the missed approach point,
    # low, near the field" -- which is what a go-around looks like, so the
    # engine went on telling a taxiing aeroplane to fly heading one two five
    # and climb to three thousand. He heard Tower trying to turn him back and
    # correctly ignored it:
    #
    #     "i had tower attempt to reverse me on go-arround again - i just
    #      ignored him and things went fine"
    #
    # Altitude alone cannot say it (he is low on final too) and speed alone
    # cannot (a warbird taxis at what a Spitfire flies a base leg at). Together
    # they are unambiguous, and neither is a guess -- both come off radar.
    #
    # THE SIM'S ANSWER FIRST. `land` and `takeoff` come off StreamEvents and
    # say outright what altitude and speed could only imply -- see
    # director/tools/events.py and [ARCH-3] / #41. The guess below stays as the
    # fallback, because the stream drops whenever the sim pauses and a director
    # restart begins knowing nothing: silence must not read as "airborne".
    if is_on_the_ground(scope, track or cs, pos):
        return ""
    # ZERO IS THE COMMONEST GROUND SPEED THERE IS, and excluding it was a bug I
    # shipped an hour ago. The `0 <` was meant to stop a MISSING speed reading
    # as slow -- but a parked aeroplane reports exactly zero, so the one case
    # this guard most obviously exists for was the one it let through. Sitting
    # on the ramp at thirty-nine feet, he was told he had gone around and to
    # fly the missed approach.
    #
    # Below two hundred feet the ambiguity it was guarding against does not
    # arise: nothing in the air at that height is doing zero knots.

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
    # "UNTIL ESTABLISHED" IS AN ILS INSTRUCTION AND HE CANNOT OBEY IT HERE.
    #
    #     "A pilot doesn't know when he is established -- everything he gets he
    #      gets from the talk down. That instruction belongs in the ils module."
    #
    # On a surveillance approach the aeroplane has no localiser and no
    # glideslope: the controller IS the approach aid. Telling him to hold an
    # altitude "until established" hands him a trigger he has no instrument to
    # detect, so he either holds it forever or guesses -- and guessing on final
    # in cloud is the thing this whole procedure exists to avoid.
    #
    # It is the same rule `_report_phrase` states and did not apply: never give
    # him a trigger he cannot see. Here the CONTROLLER owns the descent and
    # calls it off the table, so the altitude stands until he says otherwise.
    return (f"ASR: vectoring, {rng} miles{turn}.{swing} Fly heading "
            f"{g.heading:03d}, maintain {g.altitude_ft}. You will call his "
            f"descent; do not ask him to report established.")


def radar_range_for(scope: str, cs: str) -> float | None:
    """Range from the beacon of the track bound to this callsign, if any.

    Only reads contacts the controller has already radar-identified (the [tagged]
    ones). An unidentified blip near the beacon proves nothing about who is
    talking, and guessing is how you end up rejecting a truthful report.
    """
    # A SCOPE WITH CONTACTS IS NOT AN EMPTY SCOPE, however the prose reads.
    # `Scope` is a str subclass, so `not scope` asks about the PICTURE -- and a
    # picture can be empty while the facts behind it are not (a controller with
    # no projected field of his own draws nothing, and the tests build scopes
    # from contacts alone). Reading the string here made the structured path
    # unreachable in exactly those cases, silently, and it is the same shape as
    # the bug it replaced: asking prose a question the data can answer.
    if not (scope or getattr(scope, "contacts", None)) or not cs:
        return None
        return None
    from marshall.atc import callsign as C
    # Structure first, and it agrees with `radar_fix` by construction because it
    # asks the same function. Two readers of one picture that could disagree is
    # how a controller ends up quoting two different ranges for one aeroplane.
    if getattr(scope, "contacts", None):
        fix = radar_fix(scope, cs)
        return fix.range_nm if fix is not None else None
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


def flying_the_missed(bridge, cs: str, pos, profile, ctl=None) -> bool:
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
        bridge.flying_missed.discard(key)
        return False
    if ctl is not None:
        ac = ctl.aircraft.get(key)
        if ac is not None:
            # His APPROACH COUNT, not his phase. `report_missed` sets the phase
            # to MISSED and `_try_clear` re-clears him for another attempt in
            # the same breath, so by the time anyone looks he reads as CLEARED
            # again -- correct for sequencing and useless as a signal. The count
            # only ever goes up, and it goes up exactly once per go-around.
            been = bridge.missed_count.get(key, 0)
            if ac.approaches > been:
                bridge.missed_count[key] = ac.approaches
                bridge.flying_missed.add(key)
    return key in bridge.flying_missed


def note_missed(bridge, cs: str, phase: str, ctl=None) -> None:
    """The geometry has just handed out the missed approach. Remember it."""
    if phase == "missed":
        bridge.flying_missed.add(ctl._resolve(cs) if ctl is not None else cs)


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


def in_conversation(bridge, guid: str, now: float | None = None) -> bool:
    return (now or time.time()) - bridge.last_heard.get(guid, 0.0) < CONVERSATION_SEC


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


def may_be_vectored(bridge, ctl, cs: str, traffic: bool = False,
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
        was = bridge.heard_on.get(ctl._resolve(cs))
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


# "Nobody asked the classifier", which is not the same as "the classifier
# does not know". See separation_context.
_UNASKED = object()


def separation_context(bridge, ctl, transcript: str, scope: str = "",
                       known: str = "", track: str = "",
                       intent=_UNASKED) -> tuple[str, str]:
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
        # ALREADY CLASSIFIED, USUALLY. `decide` runs the classifier once per
        # transmission now, because what a pilot WANTS has to be recorded
        # whether or not there is anybody to separate him from -- and this
        # function is skipped entirely for a single ship. Kept optional so the
        # tests and tools that call this directly still work unchanged.
        # A SENTINEL, NOT None. `decide` classifies once per transmission and
        # passes the result down -- and a classifier that FAILED returns None,
        # which is a real answer meaning "we do not know". Treating None as
        # "not provided" made this classify a second time, which put a live
        # Bedrock call into the offline test suite and took it from six seconds
        # to fifty-four.
        if intent is _UNASKED:
            intent = bedrock_intent.classify(transcript)
        if intent is None:
            return "", ""

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

        # GONE, 30 July: a block here let the classifier's MEMBER callsign
        # overwrite `known`, on the reasoning that "Apex 1-2" is more specific
        # than "Apex" and a lead should not keep the flight's name after the
        # flight has stopped existing. Both halves are somebody else's job now.
        # A member designation is not a name anybody is addressed by, and what
        # to call a man is decided by `flights.speaking_as` -- the flight while
        # he is in one, his own handle the moment he is not. So the second half
        # is handled at the source, and the first was the self-designated
        # callsign wearing a hat.

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
            tagged = _track_tagged(scope, intent.callsign)
            if not tagged:
                print(f"  .. '{intent.callsign}' is neither a radio we have "
                      f"identified nor a track on the scope; the engine will "
                      f"not be told about it", flush=True)
                intent = dataclasses.replace(intent, callsign="")
            else:
                # AND IT GOES IN UNDER THE HANDLE, not under the tag. This was
                # the last door a spoken callsign could still walk through into
                # the engine: the bracketed name on a scope line is only there
                # because something correlated him FROM SPEECH earlier, so
                # keying him by it puts "Pony 1-1" on the board by a longer
                # route. One key everywhere -- the human, out of the sim's own
                # name for the aeroplane -- or the two brains are back to
                # holding two different aeroplanes under two different names.
                intent = dataclasses.replace(intent,
                                             callsign=identity.handle(tagged))
                # And the geometry follows him. Everything below that asks
                # where he is must ask by TRACK from here on -- the engine no
                # longer holds him under a name the scope has printed anywhere.
                track = track or tagged

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
        # BY TRACK. This read `radar_range_for(scope, intent.callsign)`, which
        # searched the picture for a bracketed tag -- and the engine's callsign
        # is a HANDLE now, which the scope never prints in brackets. So the
        # lookup quietly returned None for everybody, and a check that returns
        # None declines to reject: the blind engine went back to believing a
        # beacon report from eight miles out, which is the exact failure this
        # guard was added for. Found by the guard's own test, which is the
        # argument for having written it.
        _at = radar_fix_by_track(scope, track) if track else None
        nm = _at.range_nm if _at is not None else radar_range_for(
            scope, intent.callsign)
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
            # BY TRACK. This asked the scope for the CALLSIGN, and the picture
            # labels a manned contact by player name -- so unless something had
            # already tagged the line, radar_fix found nobody and he was marked
            # NOT radar identified on every single transmission. Everything on a
            # vectored approach depends on that flag, so he was never really on
            # the approach at all:
            #
            #     "im not sure batumi approach ever REALLY had me on the
            #      approach until the very end"
            #
            # The board bears him out: UNSEEN for the whole sortie.
            seen = (radar_fix_by_track(scope, track, ctl.profile) is not None
                    if track else
                    radar_fix(scope, intent.callsign, ctl.profile) is not None)
            ctl.note_radar_contact(intent.callsign, seen)

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
                           on_missed=flying_the_missed(bridge, intent.callsign, fix,
                                                       ctl.profile, ctl))
            if g.established and ctl.seen_on_final(intent.callsign):
                print(f"  .. {intent.callsign} is already on final per radar; "
                      "not stacking him", flush=True)

        # An intent with no callsign never reaches the engine. Belt to the
        # braces above: `dispatch` would otherwise be free to invent a key.
        if intent.callsign:
            intents.dispatch(ctl, intent)
        # DRAINED WHETHER OR NOT THE INTENT WAS HANDLED. This used to run only
        # when `dispatch` returned True, so a turn it did not handle left the
        # outbox dirty and those words reappeared beside a LATER turn's -- which
        # is how a hold and a clearance ended up in one directive.
        directive = " | ".join(tx.text for tx in ctl.take_out())
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
    # ADDRESSED TO HIM, which is the whole rule and was the one form missing.
    #
    #     "Engineering, Sakai."   -> nothing. Twice.
    #
    # Every branch below wants a PHRASE -- "come up", "are you there", "radio
    # check" -- so saying his name and then your own, which is what the design
    # tells a pilot to do and what anybody does on a shared frequency, summoned
    # nobody. It is the same shape as the callsign bug: a list of the ways
    # somebody might say a thing, instead of the rule that they said it.
    #
    # First word of the transmission AND punctuated as an address -- the comma
    # is what separates "Engineering, Sockeye" from "engineering said the
    # vectors are fixed", which is a pilot telling ATC something about him and
    # must not drag him onto the call. Bare "engineering" on its own is not
    # enough either; it is what Whisper leaves behind when it eats the rest of a
    # sentence. Allows the ums a real pilot makes.
    r"^[\s,]*(?:uh|er|um)?[\s,]*engineering\s*,"
    # "SOCKEYE TO ENGINEERING", which is how half the world addresses anybody on
    # a radio and was the second form to be missed in one evening. The pattern
    # here has been a list of the ways somebody might summon him rather than the
    # rule that they did, and each miss reads to the pilot as a dead channel.
    r"|\bto engineering\b"
    r"|\bengineering\b[\s,]*[?!]"                            # "Engineering?" -- a query
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


def is_on_the_ground(scope: str, track: str, pos=None) -> bool:
    """Is he down? The sim's answer if it has one, otherwise the old guess.

    One function so the two callers cannot drift: what silences the approach
    guidance and what hands him to Tower have to be the same fact, or he gets
    told to taxi while still being vectored.
    """
    if track:
        for u in identity.units_on(scope):
            if _key_name(u.name) == _key_name(track) and u.on_ground:
                return True
    # The fallback, for a session where no event has been seen -- the stream
    # drops when the sim pauses and a director restart begins knowing nothing.
    return bool(pos is not None
                and pos.alt_ft < GROUND_ALT_FT
                and pos.speed_kt < GROUND_SPEED_KT)


# The takeoff/landing roll begins somewhere above a taxi and below flying. Only
# used to tell three GROUND states apart, so nothing separation-related turns on
# it -- an aeroplane at 39 kt on a taxiway called "taxiing" and one at 41 kt
# called "rolling" are the same fact to every other consumer.
TAXI_SPEED_KT = 40


def sim_state(scope: str, track: str, pos=None) -> str:
    """What the aeroplane is DOING, as the sim reports it. Never as anyone says.

        "It could be parked, taxing, taking off, asr approach, en route."

    The first three are here. The others are INTENTIONS, they come from the
    pilot's mouth, and mixing the two into one word is how an observation ends up
    overwriting something a man actually said -- see `Aircraft.intent`.

    ON `is_on_the_ground` RATHER THAN THE RAW FLAG, and this is the whole reason
    the function exists. `on_ground` comes from the sim's land/takeoff EVENTS, so
    an aeroplane that spawned on the ramp never generated one and the flag reads
    False while it sits at thirty-nine feet and zero knots. Reading it directly
    is the fourth-caller mistake `tests/test_tonight.py` was written about.
    """
    if not track:
        return ""
    # NOT ON THE SCOPE AT ALL IS NOT "AIRBORNE". The obvious reading of
    # `is_on_the_ground` -- false means flying -- is wrong for the one case that
    # matters most: an aeroplane radar has stopped seeing. It finds no unit, the
    # position is None, so the geometry fallback is false too, and a board entry
    # for an aircraft that has left the world reads as cruising along.
    #
    # Absence of evidence, read as evidence. Empty is the honest answer and the
    # board already has a column that says he cannot be seen -- `confirmed`.
    if not any(_key_name(u.name) == _key_name(track)
               for u in identity.units_on(scope)):
        return ""
    if not is_on_the_ground(scope, track, pos):
        return "airborne"
    kt = getattr(pos, "speed_kt", None)
    if kt is None:
        # DOWN, AND THAT IS ALL WE KNOW. No position means no speed, and
        # guessing "parked" would be inventing the commonest case as a fact.
        return "on the ground"
    if kt < 1:
        return "parked"
    return "taxiing" if kt < TAXI_SPEED_KT else "rolling"


def next_controller(scope, track: str, me, profile, fix, *, known: str = "",
                    session_id: str = "", vectoring=None, mission: str = "",
                    phase: str = ""):
    """WHO HAS HIM NEXT. The one answer, and there used to be three.

    A handoff is decided by three different kinds of evidence, and each is
    right about something the others cannot see:

        1. THE SIM'S EVENTS       he touched down; he got airborne. A fact,
                                  and it outranks any geometry.
        2. THE RULE TABLE         the ladder -- who hands to whom, at what
                                  range, in which direction. `atc/handoff.py`.
        3. THE AIRSPACE VOLUMES   he has flown out of my block altogether, so
                                  whoever owns where he is now should have him.
                                  The case a ladder rule cannot express.

    They are a CASCADE and not alternatives: the event wins, then the ladder,
    then the volume, and each only runs when the one above it had nothing to
    say. That order is the design -- a landing is not a matter of opinion, and
    "he left my airspace" must not override "he is on the runway".

    WHY THIS IS A FUNCTION. The cascade lived inline in the receive loop, so
    nothing else could ask the question the same way. The proactive monitor
    asked only step 2; `tools/handoff_check.py` asked only step 3 and reported
    "all cases behaved" while step 2 could not hand anybody off Center at all.
    A pilot found that one at 44 nm, holding, and declared an emergency. [#51]

    One caller asking one question is the whole point; a check that exercises
    a different path from the bridge is not a check, it is a second opinion.
    """
    down = is_on_the_ground(scope, track, fix)
    nxt = handoff_on_the_event(scope, track, me, profile)
    if down:
        # A man on the runway is Tower's and is going nowhere. The event
        # branch may have said otherwise; being down outranks it.
        nxt = None
    elif nxt is None:
        # `phase` is what he is DOING, and it is the only thing that can hand
        # over the ground half of a sortie -- see `handoff.due`. A parked
        # aeroplane has no geometry to argue from, so without it Clearance,
        # Ground and Tower can never let go of anybody.
        v = (_handoff.due(profile, me,
                          _handoff_state(scope, track, fix, phase))
             if me is not None else None)
        # Same man, different name -- Approach answering as Departure is not a
        # handoff and must never be spoken.
        nxt = None if (v is None or v.same_station) else v.station
    if nxt is None and not down and me is not None and known:
        # NOT WHILE HE IS ON THE RAMP, and leaving that out undid the guard
        # above three lines after setting it: a parked jet asking Tower for a
        # departure is "obviously leaving", so the handoff came straight back.
        nxt = leaving_my_airspace(BASE_URL, session_id, known, me, profile,
                                  fix, under_our_vectors=bool(vectoring),
                                  **({"mission": mission} if mission else {}))
    return nxt


def _handoff_state(scope, track: str, pos, phase: str = "") -> object:
    """The three facts a handoff rule is allowed to look at.

    INBOUND IS A TREND, not a position, and it is the whole reason this is not
    a bare distance test: five miles outbound climbing and five miles inbound
    descending are the same range and opposite events. He is inbound when his
    heading points back towards the field -- within a quadrant of the reciprocal
    of the radial he is sitting on.
    """
    from marshall.atc import handoff as _h
    ground = is_on_the_ground(scope, track, pos)
    nm = getattr(pos, "range_nm", None)
    hdg = getattr(pos, "heading_deg", None)
    radial = getattr(pos, "radial_deg", None)
    inbound = False
    if hdg is not None and radial is not None:
        from marshall.atc import asr as _asr
        inbound = abs(_asr.angle_diff((radial + 180) % 360, hdg)) < 90
    return _h.State(on_ground=ground, range_nm=nm, inbound=inbound, phase=phase)


def handoff_on_the_event(scope: str, track: str, me, profile) -> object | None:
    """Touching down ends the approach. Getting airborne ends Tower's business.

        "Landing / takeoff event should be triggers to switch to/from tower"

    Which is what the real thing does, and what a RANGE could never express: a
    go-around at half a mile is closer than a landing at one, so the two states
    that most need telling apart are the two a distance cannot separate. The
    range rule had already been special-cased once for exactly this -- handing
    a man to Tower mid-talkdown abandoned him at the moment the procedure
    began.

    Both directions, because only one was ever wired. A departing flight was
    given to Approach at twenty-five miles and never handed back, since nothing
    marked the moment Tower was done with him.

    Silent unless the sim has actually said so. `on_ground` is False both for an
    aeroplane in the air and for one nothing has been reported about, and this
    must not fire on the second -- see events.ground_state.
    """
    if me is None or not track:
        return None
    unit = next((u for u in identity.units_on(scope)
                 if _key_name(u.name) == _key_name(track)), None)
    if unit is None:
        return None
    role = getattr(me, "role", "")
    if unit.on_ground and role == "approach":
        return profile.station_for("tower")
    if not unit.on_ground and role == "tower":
        # Airborne again: Tower owns the runway, not the departure.
        return profile.station_for("approach")
    return None


def leaving_my_airspace(base: str, session_id: str, callsign: str, me,
                        profile, fix, mission: str = "default",
                        under_our_vectors: bool = False) -> object | None:
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
    # A MAN I AM VECTORING IS NOT LEAVING MY AIRSPACE.
    #
    #     "when flying around the IF area, several times he tried to hand me off
    #      to georgia center -- i never went.. have a feeling this is a separate
    #      thread than the one flying the approach"
    #
    # He was right about the shape of it: this is a different decision path from
    # the one flying the approach, and the two disagreed. The guard below only
    # protected him INSIDE the final intercept range, so while approach control
    # was vectoring him downwind at eleven to eighteen miles -- taking him
    # outbound ON PURPOSE, as part of the approach -- the airspace rule saw an
    # aeroplane heading away and offered him to Center. Eight times in one
    # sortie.
    #
    # Being taken outbound by MY OWN vectors is the opposite of leaving, and no
    # range test can tell the two apart because the geometry is identical. What
    # separates them is whether this controller is working him, which is a fact
    # we have and were not using.
    if under_our_vectors:
        return None
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
    # HIS FIELD. The airspace name gives a role and the role is only unique
    # within an aerodrome -- unqualified this returned whichever Tower was
    # listed first, which became Kobuleti's the moment the departure field got
    # one, so an aircraft leaving Batumi Approach's airspace was handed to a
    # tower forty miles up the coast. The third place this same fault has
    # surfaced; the direction of the fix is always to say which field you mean.
    nxt = (profile.station_for(role, field=getattr(me, "field", ""))
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


def misnamed(bridge, ctl, claim: str, known: str, who: str) -> str:
    """What the controller says when a pilot uses a callsign nobody answers to.

        "if a pilot says 'falcon 1-1, approach' and there is no falcon 1-1 (a
         dcs/srs matching pilot ON the board) atc should say - falcon 1-1 I dont
         have you on the board or similar - even if he KNOWS it's sockeye.
         Sockeye screwed up by using Falcon1-1 on the radio and needs to be
         corrected."

    EVEN THOUGH WE KNOW, and that is the whole point. The radio tells us this is
    Sockeye and nothing about that is in doubt; what is wrong is the name he put
    on the air, and silently absorbing it teaches him it works. With one pilot
    up that is untidy. With four it is how a clearance ends up read back by the
    wrong man, because everybody on the frequency heard a callsign that belongs
    to nobody and each of them had to guess who it meant.

    DETERMINISTIC, and handed to the agent as words to voice rather than left to
    its judgement. Whether a name is on the board is a fact about the board --
    the same class as separation -- and an LLM asked "do you know a Falcon 1-1?"
    will find a way to be helpful about it.

    NAMES THAT ARE FINE: his own handle, the flight he is in, and anybody else
    actually on the frequency -- calling another pilot by name is ordinary radio
    and not his callsign. Everything else is a correction.

    Returns "" when there is nothing to correct, which is the normal case.
    """
    from marshall.atc import callsign as C
    if not claim:
        return ""
    ok = {n.lower() for n in bridge.flights.names()}
    ok |= {n.lower() for n in known_flight_names()}
    for n in (known, who):
        if n:
            ok.add(n.lower())
    # Everybody the engine is actually working, so addressing a wingman by name
    # is not a correction.
    ok |= {r.get("callsign", "").lower() for r in ctl.board()}
    ok.discard("")
    c = C.parse(claim)
    if any(_matches_name(claim, n) or _matches_name(c.flight, n) for n in ok):
        return ""
    # SAID BACK TO HIM THE WAY HE SAID IT, so he can hear which words were the
    # problem. Then the name that will work, when we have one for him.
    said = c.spoken or claim
    if known:
        return (f"{said}, I do not have you on the board. "
                f"You are {C.parse(known).spoken} — use that callsign.")
    return f"{said}, I do not have you on the board. Say your callsign."


def _matches_name(a: str, b: str) -> bool:
    """Two names for one entity, allowing for how Whisper punctuates."""
    from marshall.atc import callsign as C
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return False
    return a == b or C.parse(a).canonical.lower() == C.parse(b).canonical.lower()


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

# How long a clearance stays outstanding. Long enough for a pilot to write five
# elements down and read them back; short enough that it is not still armed when
# he calls for taxi three minutes later.
READBACK_WINDOW_SEC = 150


def addressed_to(said: str) -> str:
    """Who the controller just spoke TO, off his own words.

    The FIRST callsign, not the speaker convention `callsign.extract` uses --
    that one takes the second name, which is right for a pilot saying "Batumi
    Approach, Pony one one" and exactly wrong for a controller saying "Pony one
    one, turn left". A controller leads with the addressee.

    Deliberately reports what he SAID rather than who we resolved, because the
    interesting failure is the two disagreeing: a reply that answers the right
    pilot by the wrong name is a different bug from one that answers the wrong
    pilot, and a log that records only our own conclusion cannot tell them
    apart.
    """
    from marshall.atc import callsign as C
    names = C.extract_all(said or "")
    return names[0] if names else ""


def is_a_clearance(said: str) -> bool:
    """Did we just issue an IFR clearance? Read off the words, because that is
    what a clearance IS -- there is no other transmission on this frequency that
    carries a squawk and a routing together."""
    low = (said or "").lower()
    return "squawk" in low and ("cleared to" in low or "as filed" in low)


def readback_due(bridge, callsign: str, now: float | None = None) -> bool:
    """Is this transmission the read-back of a clearance we just gave him?"""
    when = bridge.awaiting_readback.get(callsign)
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
_filed: dict[str, object] = {"at": 0.0, "names": [], "rows": []}
FILED_TTL_SEC = 45.0            # a plan can be filed mid-session


def filed_plans(url: str = f"{BASE_URL}/flightplans",
                now: float | None = None) -> list[str]:
    """Callsigns on a filed flight plan. Never costs a transmission.

    /flightplans, NOT /flights, and the difference is the whole value of this
    rung. `/flights` is the live board -- rows CREATED BY the binding this is
    supposed to corroborate, so believing it is circular in exactly the way
    that made the naive radar check useless: an aeroplane cannot vouch for the
    process that invented it.

    A flight plan is typed, before the sortie, by a human at a keyboard. It is
    the only identity evidence in the system that exists before anybody keys a
    microphone, which is what makes it the right authority for a FIRST
    transmission -- the moment when radar has not correlated anyone yet and
    there is nothing else to go on.

    So a visiting pilot gets a clean first approach by having a plan on file
    before he flies, which is also what a real controller would have.
    """
    t = time.time() if now is None else now
    if t - float(_filed["at"]) < FILED_TTL_SEC:
        return list(_filed["names"])          # type: ignore[arg-type]
    _filed["at"] = t
    try:
        rows = _get_json(url, timeout=2.5).get("flight_plans") or []
        _filed["rows"] = rows
        _filed["names"] = sorted({p.get("callsign") for p in rows
                                  if p.get("callsign")})
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        pass                                   # keep the last good list
    return list(_filed["names"])               # type: ignore[arg-type]


def filed_plan_rows() -> list[dict]:
    """The same strips, whole, for anything that wants more than the name.

    Deliberately a reader of the cache `filed_plans` fills rather than a second
    fetch: two callers polling the same endpoint on two timers is how a board
    and a controller come to disagree about whether a plan is active. Whoever
    calls `filed_plans` refreshes this; nobody refreshes it alone.
    """
    return list(_filed["rows"])                # type: ignore[arg-type]


def whisper_vocabulary(bridge, profile, roster=None) -> str:
    """The priming text for the transcriber, from what is actually on the air.

    Rebuilt as radios identify themselves, because the callsigns are the half
    that cannot be known in advance and are also the half that does the damage
    when it is wrong -- a mangled callsign does not merely mis-transcribe a
    word, it invents an aeroplane and gives it a place in the holding stack.
    """
    from marshall.atc import callsign as C
    from marshall.core import route as R
    from marshall.radio import stt

    # Seed with who COULD be flying before anyone has spoken, plus anybody
    # named on the command line -- a visiting pilot or a test callsign. Without
    # this the very first transmission, which is the one that binds a radio to a
    # name, is the only one with no priming behind it.
    spoken = list(getattr(R, "SQUADRON_CALLSIGNS", ()))
    spoken += [c for c in os.environ.get("MARSHALL_CALLSIGNS", "").split(",")
               if c.strip()]
    # THE HANDLES, which are the names actually said on this frequency now.
    #
    #     "I can also see we're going to need a pronunciation engine... certain
    #      words like sockeye"
    #
    # Whisper wrote "Sakai" for Sockeye, and that is not a pronunciation problem
    # so much as a vocabulary one: it is a word the model has no reason to
    # expect and every reason to hear as a commoner name. Priming is the lever
    # -- it already carries squadron callsigns and fixes -- and the handles were
    # the one category missing, which was survivable while a callsign named him
    # and is not now that his handle IS his name.
    #
    # Known BEFORE he speaks, which is the valuable part: the SRS roster gives
    # every connected client's name, so the very first transmission -- the one
    # that used to be the only one with no priming behind it -- is covered.
    for who in (roster or {}).values():
        h = identity.handle(who or "")
        if h:
            spoken.append(h)
    for i in bridge.identity.by_guid.values():
        for n in (i.callsign, getattr(i, "who", ""), identity.handle(i.track)):
            if n:
                spoken.append(n)
    for seen in bridge.transmitters.values():
        for cs in seen:
            try:
                spoken.append(C.parse(cs).spoken)
            except Exception:
                spoken.append(cs)
    stations = [s.name for s in (getattr(profile, "stations", None) or [])]
    fixes = [f.name for _, f in R.sortie_points()]
    field = getattr(getattr(profile, "beacon", None), "name", "Batumi")
    return stt.domain_prompt(stations, fixes, spoken, field, plan_labels())


# name -> (lat, lon), from the sim's own projection of route.py's fixes.
# Filled by `push_fixes` on startup; empty until then, and empty is handled --
# a Scope with no origin renders no ranges rather than wrong ones.
PROJECTED: dict[str, tuple] = {}


def field_origin(profile, field: str = "") -> tuple | None:
    """Where THIS controller measures from.

    The beacon when the field has one, because that is the published reference
    every range on the plate is quoted against; the arrival fix otherwise. Not a
    module constant, and not the director's -- see `Scope`.

    `field` IS WHICH AERODROME IS ASKING, and without it every controller in the
    theatre measured from the profile's beacon -- which is Batumi's. That was
    invisible while Batumi was the only field and wrong the moment Kobuleti
    existed: an aeroplane sitting on Kobuleti's own runway was handed to
    Kobuleti Clearance as "23 miles on the 033 radial", because it IS 23 miles
    from Batumi. Every range and radial that controller spoke would have been
    measured from an airport forty miles away, and each one is a plausible
    number, so nothing looks wrong until a pilot flies it.
    """
    if field:
        # His own field first. PROJECTED is keyed by fix name and the fields are
        # named for their aerodromes, so a field with a fix of the same name --
        # KOBULETI, BATUMI -- resolves directly.
        got = PROJECTED.get(field.upper())
        if got:
            return got
    for attr in ("beacon", "arrival_fix", "outer_hold"):
        f = getattr(profile, attr, None)
        name = getattr(f, "name", "") if f is not None else ""
        if name and name.upper() in PROJECTED:
            return PROJECTED[name.upper()]
    return None


class Scope(str):
    """The radar picture, and the facts it was drawn from.

    A STRING SUBCLASS, deliberately, and it is worth saying why rather than
    leaving somebody to find it. The prose IS the agent's input -- it goes
    straight into the prompt -- and it is threaded through about forty call
    sites as a plain `scope: str`. Making it a str keeps every one of those
    working untouched while the geometry migrates off the regexes one function
    at a time ([#47]). The alternative was a second parameter through all forty,
    which would have had to land in one commit.

    `contacts` is the same tracks as data, with ABSOLUTE positions. `origin` is
    where THIS controller measures from, which the director has no opinion
    about. Anything asking "how far is he" computes it here, from those two,
    instead of parsing a number out of the prose that was measured from a
    constant in another process.

    Both may be empty -- an older director, or a radar hiccup -- and callers
    fall back to the parsers until those are gone.
    """

    # Annotated only; every instance sets them in __new__. A str subclass has
    # no __init__ to put them in, and a bare default here would be shared.
    contacts: list
    origin: tuple | None
    bullseye: dict

    def __new__(cls, picture: str = "", contacts=None, origin=None, bullseye=None):
        self = super().__new__(cls, picture or "")
        self.contacts = list(contacts or [])
        self.origin = origin
        self.bullseye = dict(bullseye or {})
        return self

    def of(self, track: str):
        """The contact for a track, or None. The join everything wants.

        BY LABEL FIRST, because "track" in this process means the SCOPE LABEL --
        what the picture prints and what identity resolves a radio to. The sim's
        own unit name is checked second so a caller holding either one finds
        him; they are usually different strings ("362nd_sockeye" against
        "Viper 1-4") and confusing them severs the identity chain.
        """
        want = _key_name(track or "")
        if not want:
            return None
        for c in self.contacts:
            if _key_name(c.get("label", "")) == want:
                return c
        for c in self.contacts:
            if _key_name(c.get("name", "")) == want:
                return c
        return None


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
    from marshall.core import route as R

    # THE FIFTH COPY OF THIS DANCE, and the one place the real reason
    # survived in a comment: "pydcs also claims the name `dcs`". Ruff's
    # per-file ignores said it was about import ORDER, which was false. One
    # implementation now, in `feed.stubs`, with the reason written down.
    from marshall.feed.stubs import bind as _bind_dcs_stubs
    _bind_dcs_stubs()

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
    # KEPT, not just pushed. The bridge projected these through the sim's own
    # converter and then discarded them, so the one process that knows where its
    # own field is had to ask the director for ranges measured from somebody
    # else's. See `Scope`: rendering a picture for a controller needs an origin,
    # and this is where it comes from.
    PROJECTED.clear()
    PROJECTED.update({k.upper(): tuple(v) for k, v in out.items()})
    return len(out)


def engineering_turn(tx, transcript, srs, known, heard_hz, freq_hz,
                     eng_voice, radio_lock, AM, session_id):
    """The engineer, on the same frequency as everybody else.

    ONE CHANNEL, THREE PARTIES -- ATC, engineering and the pilots -- and each
    transmission is addressed to one of them out loud. Returns True when this
    one was for the engineer.

    THE MODE IS GONE, and it was most of the code. There used to be a LINE: a
    pilot summoned engineering, was held on it, and everything he said went to
    the engineer until he released it -- which meant detecting the summons,
    detecting the release, checking the release FIRST because "thanks
    engineering" contains the word, and a heuristic for noticing he had gone
    back to the controller without saying so. A hundred lines, all of it
    tracking who was in which conversation.

    None of it was engineering. It was the cost of two conversations sharing a
    radio while pretending they were on separate ones -- and it left an
    implicit mode nobody in the cockpit could see. "Am I still on the
    engineering line?" is not a question a pilot should have to hold in his
    head at two hundred knots, and it is not one he can answer from the
    aeroplane.

    Say his name instead, every time, which is what you would do on any shared
    frequency: "engineering, H4 failed". The same rule the controller now
    follows -- explicit addressing beats inferring intent, because intent is
    not in the words and identity never was either.
    """
    if not _ENG_CALL.search(transcript):
        return False
    _eng_hz = heard_hz or freq_hz
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
    reply = engineering_ack(True)
    # `tx` is the transmit POOL now, not the listening client -- it serialises
    # per frequency itself, so `radio_lock` is only holding the print in step
    # with the air.
    with radio_lock:
        print(f"  ENG[tx] {reply}", flush=True)
        tx.transmit(eng_voice.frames(reply), _eng_hz, AM)
    return True


def speak(bridge, interact, message, transcript, known, heard_hz, fix, profile, ctl):
    """Hand the turn to the agent, and mark what it commits us to.

    EXTRACTED VERBATIM, 30 July -- [LAYERS.md] step 1. `interact` is passed in
    rather than reached for: it is still a closure inside `_run_srs`, over
    twelve things including the radio lock and the contexts of three threads.
    Converting THAT to a function changes how state is shared between the loop,
    the hook scheduler and the metronome, and most of its captures become stores
    at step 3 -- so writing its signature now means writing it twice. It stays a
    closure until the stores exist, and this stage takes it as an argument,
    which at least makes the dependency visible instead of ambient.

    THE `asr.guide` HERE IS THE SECOND CALL of the transmission. `settle` made
    the first, for reconcile, passing `known or "?"`; this one passes `known`.
    Same geometry, computed twice, with different callsigns -- so the two can
    disagree about whether he is flying the missed approach. Preserved exactly
    as it was, because this step moves rather than improves, and written down in
    both places so it cannot be lost.
    """
    # The current geometry goes with it so the transmit path can tell
    # whether the engine is already flying him down.
    _g = None
    if fix is not None:
        from marshall.atc import asr as _asr2
        _g = _asr2.guide(fix, profile,
                         on_missed=flying_the_missed(bridge, known, fix, profile, ctl)
                         if known else False)
    interact(message, "pilot", route_tier(transcript),
             on_hz=heard_hz, guide=_g, to_callsign=known or "")
    # If that answer WAS a clearance, his next transmission is the read-back.
    if known and is_a_clearance(bridge.last_said[0]):
        bridge.awaiting_readback[known] = time.time()


def membership(bridge, _who, transcript, scope, _ident, session_id):
    """Create, join, break out -- and what the controller must SAY about it.

    EXTRACTED VERBATIM, 30 July -- [LAYERS.md] step 1. Not pure: it mutates
    the roster and writes to the recorder, which is why it returns only the
    words. The roster is a module global today and becomes a store at step 3;
    when it does, this signature loses `session_id` and gains the store, and
    the last of the hidden state goes with it.

    GATED ON `_who` THROUGHOUT, and that is load-bearing rather than
    defensive: a person is his handle, the handle comes from the TRACK, and
    a flight formed from a name nobody can corroborate is the ghost problem
    with a different noun. When identity does not close, nothing here runs --
    which is exactly what happened when formations were unparseable and the
    whole flight model was unreachable for two days.
    """
    # WHAT THE CONTROLLER MUST SAY ABOUT THE FLIGHT. The verdicts below
    # are decided here, deterministically, and were recorded and never
    # VOICED -- so the rehearsal showed a flight created, a wingman
    # joined and an outsider refused at nine miles, while every pilot
    # heard "station calling, say your callsign". A decision the pilot
    # cannot hear has not been made as far as he is concerned.
    _flight_say = ""

    # CREATING A FLIGHT. He says a name; he is its lead and its only member
    # until somebody joins.
    if _who:
        _name = fl.parse_create(transcript)
        if _name:
            _f, _why = bridge.flights.create(_name, _who)
            print(f"  .. {_name}: "
                  + (f"created, lead {_who}" if _f else _why), flush=True)
            if _f is not None:
                record(session_id, kind="flight/created", callsign=_name,
                       who=_who)
                _flight_say = (f"{_who}, you are now the lead of {_name} "
                               f"flight. Each member of {_name} check in "
                               f"to be joined.")
            else:
                _flight_say = f"{_who}, unable -- {_why}."

        # JOINING ONE, on his own radio and in the right place. A pilot can
        # only join himself, and only when radar puts him with the flight
        # -- joining is the moment the controller stops separating him, so
        # a man who says it from forty miles away would go unseparated and
        # unwatched believing he was somebody's wingman.
        _want, _said_name = fl.parse_joining(transcript, bridge.flights.names())
        if _want:
            _lead = bridge.flights.flights[_want].lead
            _gap = miles_between(scope, _ident.track,
                                 _track_of(scope, _lead))
            _f, _why = bridge.flights.join(_want, _who, _gap)
            print(f"  .. {_want}: "
                  + (f"{_who} joined" if _f else _why), flush=True)
            record(session_id, kind="flight/joined" if _f else "flight/refused",
                   callsign=_want, who=_who, miles=round(_gap or 0, 1),
                   text="" if _f else _why)
            _flight_say = (f"Roger {_who}, joined to {_want}."
                           if _f else f"{_why}.")
        elif _said_name:
            # HE TRIED TO JOIN SOMETHING THAT IS NOT THERE, and still
            # deserves an answer -- silence reads as a controller who did
            # not hear him, which is the one thing worse than "unable".
            print(f"  .. {_who}: no flight called {_said_name}", flush=True)
            record(session_id, kind="flight/refused", callsign=_said_name,
                   who=_who,
                   text=f"{_who}, unable, {_said_name} flight doesn't exist")
            _flight_say = (f"{_who}, unable, {_said_name} flight doesn't "
                           f"exist.")

        # BREAKING HIMSELF OUT, without needing the lead. A lost wingman
        # who transmits is otherwise answered as the FLIGHT, so the
        # controller vectors the lead -- the man who needs help gets none
        # and somebody who did not ask gets turned. It is also the case
        # where the lead is least likely to be on the ball.
        _out = fl.parse_leaving(transcript, bridge.flights.names())
        if _out and (_mine := bridge.flights.of(_who)) is not None:
            _was_lead = _mine.lead == _who
            _survivors = [m for m in _mine.members if m != _who]
            _gone = bridge.flights.leaves(_who)
            if _was_lead and _gone:
                print(f"  .. {_gone} dissolved — its lead left", flush=True)
                record(session_id, kind="flight/dissolved", callsign=_gone,
                       who=_who,
                       text=fl.lead_lost_call(_gone, _who, _survivors))
                _flight_say = fl.lead_lost_call(_gone, _who, _survivors)
            else:
                print(f"  .. {_who} is out of {_out}", flush=True)
                record(session_id, kind="flight/left", callsign=_out,
                       who=_who,
                       text=f"Roger {_who}, you are no longer in {_out} "
                            f"flight, what are your intentions?")
                _flight_say = (f"Roger {_who}, you are no longer in {_out} "
                               f"flight, what are your intentions?")
    return _flight_say


# WHAT EACH INTENT MEANS AS A STANDING INTENTION, in the words a controller
# would use on a strip. Only the kinds that say something about what he is
# TRYING TO DO -- a position report and a check-in are things he is doing right
# now, not what he wants, and overwriting "asr approach" with "check in" the
# moment he reads a heading back would lose the very fact the column is for.
_INTENT_SAID = {
    "request_approach": "asr approach",
    "request_visual": "visual approach",
    "request_breakup": "break up the flight",
    "report_missed": "going around",
    "report_landed": "landing",
}


def intent_said(intent) -> str:
    """The standing intention this transmission establishes, if any.

    Empty for everything else, and `note_intent` ignores an empty -- so a
    request survives the twenty read-backs that follow it. That is what makes
    the column mean "what he is here for" rather than "the last thing he said".
    """
    return _INTENT_SAID.get(getattr(getattr(intent, "kind", None), "value", ""), "")


def classify_intent(transcript: str):
    """Ask the classifier what this was, and never let it break the call.

    Its own function because it now has two consumers -- the separation engine
    and the intent column -- and because a classifier failure must cost a label,
    never a transmission. The bridge has fallen silent on a raised exception
    here before; an empty directive reads to a pilot as a controller who has
    stopped listening.
    """
    from marshall.atc import bedrock_intent
    try:
        return bedrock_intent.classify(transcript)
    except Exception as e:                        # must not break the call
        print(f"  !! intent classify failed: {e}", flush=True)
        return None


def become_tracked(ctl, known: str, track: str) -> bool:
    """He has contacted a controller and the sim can see him. He is now tracked.

    THE BOARD HAD NO DOOR. Entries appeared as SIDE EFFECTS of whichever code
    path happened to call `Controller.get` first, and for a single ship that was
    a block near the end of the turn whose actual job is writing down what was
    agreed -- gated, incidentally, on his having a filed flight plan. The
    separation engine never admitted him at all, because `engaged` is False with
    one aeroplane up and `intents.dispatch` is inside the branch that is skipped.

    So a lone pilot's presence on the board was a coincidence of two unrelated
    features, and everything hung on it: his owner, his track, whether the
    staleness clock could account for him. "Tracked" is the central noun in this
    system and nothing was responsible for it.

    ONLY FROM UNTRACKED, which is what the track argument enforces. A track
    means the physical chain closed -- this radio is sitting in that aeroplane,
    per the sim -- so an aircraft can only become tracked if it was a real
    contact first. No transcript can produce one: Whisper turned this pilot's
    name into "362 and D. Underscore Sockeye" on the very call that identified
    him correctly, because the words are not what identifies anybody.

    That is the non-circular corroboration [#40] went looking for. The untracked
    list is populated from the sim before anyone speaks, so checking against it
    is not checking a binding against itself.
    """
    if not (known and track):
        return False
    # ONE AEROPLANE, ONE ROW. A track already on the board under another name
    # must not open a second entry, and this is not a tidiness rule -- TWO
    # ENTRIES ARE WHAT MAKES THE SEPARATION ENGINE ENGAGE, so a duplicate turns
    # a single ship into a sequencing problem between a pilot and himself.
    #
    # IT HAPPENED WHILE THIS WAS BEING BUILT. The pilot said "established ON the
    # final approach course"; the flight parser took "on" for a name and created
    # a flight; `speaking_as` duly reported he was called "On"; and this
    # function, seeing a perfectly real track, admitted him. The board then read
    #
    #     SEPARATION: Andre unknown -; On cleared 5000 ft
    #
    # -- one Mustang, two rows, being separated from itself.
    #
    # The name was wrong and the TRACK was right, which is the whole reason the
    # check belongs here rather than in the parser that misheard him. Parsers
    # will keep mishearing: the supply of English words is unbounded and [#40]
    # measured 37 of them binding as names in 846 real transmissions. What
    # cannot be allowed is for a misheard name to become a second aeroplane,
    # and the track is the identifier no transcript can reach.
    key, want = ctl._resolve(known), _key_name(track)
    for cs, ac in ctl.aircraft.items():
        if cs != key and _key_name(getattr(ac, "track", "")) == want:
            print(f"  !! {known} would be a second entry for {track}, which is "
                  f"already {cs} -- refused", flush=True)
            return False
    # OWNED BY A STATION, NOT A ROLE. "Batumi Approach", never "approach" --
    # see where `ctl.station` is set. Falls back to the role for a controller
    # built without stations (the tests, and the dry-run tools), because an
    # owner of the wrong shape is still better than no owner at all.
    ctl.bind(known, track=track,
             owner=(getattr(ctl, "station", "") or getattr(ctl, "working", "") or ""))
    return True


def decide(bridge, ctl, transcript, scope, known, track, engaged, profile):
    """What the DETERMINISTIC side says about this transmission.

    EXTRACTED VERBATIM, 30 July -- [LAYERS.md] step 1. Two answers, and they
    come from different places on purpose:

      directive/stack   the blind engine's next step and the holding stack,
                        and ONLY when it is engaged -- there is nothing to
                        separate a lone aeroplane from.
      vectoring         radar guidance, which costs no model call and so runs
                        for a single ship too. That case used to fly with no
                        deterministic picture at all.

    This is the half of the two-brain seam that must never be a model's guess.
    Whatever comes out of here is phrased by the agent and not invented by it.
    """
    # HE IS TRACKED BEFORE ANYTHING IS DECIDED ABOUT HIM, because everything
    # below reads the board and an entry that appears afterwards is an entry
    # this turn cannot see.
    become_tracked(ctl, known, track)
    # WHAT HE WANTS, ONCE PER TRANSMISSION, and outside the `engaged` branch.
    #
    #     "The first thing a controller should do is figure out what my
    #      intentions are"
    #
    # True whether or not anybody else is flying -- and the classifier used to
    # live entirely inside `separation_context`, which is skipped for a single
    # ship because there is nothing to separate one aeroplane from. So the one
    # question a controller asks first could only be answered when the airspace
    # was busy. Classified here and handed down, so it is one model call serving
    # both rather than two.
    # ONLY FOR SOMEBODY ON THE BOARD. No row, no intention to record -- and
    # `note_intent` refuses to create one, so classifying first would be paying
    # a model call for an answer with nowhere to go. It also keeps the offline
    # test suite offline: everything below this line is network.
    intent = None
    if known and ctl._resolve(known) in ctl.aircraft:
        intent = classify_intent(transcript)
        if intent is not None:
            ctl.note_intent(known, intent_said(intent))
    # THE ENGINE ALWAYS RUNS. `engaged` used to gate this, and with ONE
    # aeroplane it was False -- so `intents.dispatch` never ran, no controller
    # method was ever called, and `phase` stayed UNKNOWN from wheels-up to
    # touchdown. The deterministic half of a two-brain system was asleep for
    # every single-ship sortie, which is the case this project actually flies.
    #
    # A pilot found it on the radio: "the DOING while tracked remained UNKNOWN
    # the whole time". The board proved the gate was the cause rather than any
    # missing vocabulary -- `intent` filled in and `phase` did not, on the same
    # transmission, purely because one was hoisted outside this branch tonight
    # and the other was not.
    #
    # THE FLAG ANSWERED TWO QUESTIONS. "Is there traffic to sequence?" and
    # "should I remember what I agreed with him?" are different, and the engine
    # holds far more than separation: phase, assigned altitude, approaches
    # flown, radar-identified, on-visual, missed count. That is the controller's
    # MEMORY, and it matters with one aeroplane exactly as much as with four.
    #
    # Sequencing still needs traffic and still gets it: `_stack_summary` is
    # already gated on `len(ctl.aircraft) >= 2` inside, so the queue, the
    # letdown and the holding stack are unchanged. And the cost argument for
    # the gate went when the classifier moved up here -- it runs for anybody on
    # the board now whether or not this branch is taken.
    directive, stack = separation_context(bridge, ctl, transcript, scope, known,
                                          track, intent)
    # Radar guidance for a vectored approach. Costs no model call, so it
    # runs for a single ship too -- which is the case that was flying with
    # no deterministic picture at all.
    vectoring = asr_context(profile, scope, known, track)
    return directive, stack, vectoring


def settle(bridge, directive, stack, vectoring, fix, profile, known, ctl):
    """One aeroplane, one instruction. Which authority owns him this turn.

    EXTRACTED VERBATIM, 30 July. `reconcile` exists because a pilot was once
    told, in a single transmission, that he was on final AND to climb to five
    thousand and hold -- so the choice is made here rather than by handing the
    agent three authorities and hoping.

    NOTE FOR THE NEXT STEP, not fixed here because this commit moves rather
    than improves: `asr.guide` is called TWICE per transmission. Once here, for
    reconcile, with `known or "?"`; and again just before `interact`, with
    `known`. Same geometry, computed twice, and the two calls do not pass the
    same callsign -- so they can disagree about whether he is flying the missed
    approach. Worth a look once the stages are out.
    """
    from marshall.atc import asr

    guide = (asr.guide(fix, profile,
                       on_missed=flying_the_missed(bridge, known or "?", fix, profile,
                                                   ctl))
             if fix is not None else None)
    directive, stack, vectoring, dropped = reconcile(
        directive, stack, vectoring, guide)
    return directive, stack, vectoring, guide, dropped


def _derived_callsign(label: str) -> str:
    """The board key this contact would take, from the sim's label alone.

    "362nd_Sockeye" -> handle "Sockeye" -> canonical "Sockeye". No radio, no
    GUID, no transcript and no clock: every input is on the radar contact the
    moment a pilot takes the slot.

    THE POINT IS THAT THERE IS ONE OF THESE. The four names for one aeroplane --
    slot name, scope label, handle, board key -- are not four facts, they are
    one fact and three derivations, and every join bug in this system has been
    two of those derivations run by different code and compared as strings.
    """
    from marshall.atc import callsign as C
    return C.parse(identity.handle(label or "")).canonical


def _contact(u, scope: str, board_tracks: set) -> dict:
    """One radar contact, with where it is and whether anybody is working it.

    The POSITION comes from the same parser the guidance uses, so the page and
    the controller cannot disagree about where an aeroplane is -- which they
    would the moment a second reader of that prose existed. See [#47]; the
    right answer is that none of this is prose, and until then there is exactly
    one parser.
    """
    # By TRACK, which now reads the structured contact -- so a wingman gets a
    # position on the board like anybody else. This used to be the third
    # independent parse of the same prose in one process.
    fix = radar_fix_by_track(scope, u.name)
    controlled = _key_name(u.name) in board_tracks
    return {
        "name": u.name, "callsign": u.callsign, "type": u.type,
        # WHAT HE WILL BE CALLED, worked out here rather than when he speaks.
        #
        #     "The sim even knows what my callsign will be 'Sockeye' - because
        #      the process of stripping a squad off a name should be
        #      deterministic and instant."
        #
        # It is both, and it always was: `handle` is a pure function over a
        # string the sim publishes on every poll. It was simply unreachable
        # except through `Registry.resolve`, which is the TRANSMISSION path --
        # so a name available for free sat underived until somebody keyed a
        # microphone, and this table printed the raw label.
        #
        # CANONICAL, because that is the board's own primary key. Deriving it
        # here is what stops the name-join existing at all: `track_of` and
        # `release_stale` have both been matching a handle against a canonical
        # against a scope label, three routes to one aeroplane's name. One
        # derivation, from the sim, and there is nothing left to match.
        #
        # AIRCRAFT ONLY. A tank has a label and the rule would happily turn it
        # into "Ural", which is a callsign-shaped string for a thing that will
        # never have one -- and a callsign-shaped string is precisely what gets
        # picked up later by something that should have known better.
        "derived": _derived_callsign(u.name) if not u.category else "",
        # WHAT HE IS DOING, from the same function the board uses, so the two
        # tables cannot disagree about a man who is about to move between them.
        #
        # `tags` is NOT this. It carries the raw `on_ground` EVENT flag, which
        # is false for an aeroplane that spawned parked and false again after a
        # director restart loses the in-memory event history -- both of which
        # were true of the aircraft on the scope while this was written. The
        # tag is what the sim announced; `state` is what is actually so.
        "state": sim_state(scope, u.name, fix) if not u.category else "",
        "tags": [t for t, on in (("manned", u.manned),
                                 ("on the ground", u.on_ground)) if on]
                + ([u.category] if u.category else []),
        "category": u.category,
        # AIRCRAFT ONLY for "nobody is working this". A tank is not traffic and
        # never will be; listing armour as uncontrolled would bury the one
        # entry that matters -- a manned aeroplane nobody has on the board.
        "is_aircraft": not u.category,
        "controlled": controlled,
        # A MANNED contact nobody is working is the one worth a second look:
        # either he has not checked in, or -- worse, and invisible until now --
        # he is talking and his identity never closed, so every call is
        # answered and nothing is ever sequenced.
        "level": "warn" if u.manned and not controlled and not u.category else "",
        "range_nm": getattr(fix, "range_nm", None),
        "radial": getattr(fix, "radial_deg", None),
        "alt_ft": getattr(fix, "alt_ft", None),
        "heading": getattr(fix, "heading_deg", None),
        "speed_kt": getattr(fix, "speed_kt", None),
        # AND FROM BULLSEYE.
        #
        #     "update the UNTRACKED page to show aircraft relative to bulls"
        #
        # Right, and it is the correct reference for exactly this table: an
        # untracked contact is one NOBODY on this board is working, so quoting
        # him relative to one controller's threshold says nothing useful. The
        # bullseye is the point everyone on the map shares -- it is what the
        # pilot's own HSI is referenced to, so it is also what he would say if
        # you asked him where he was.
        #
        # Computed here, never in the page. The page is not allowed to know
        # what a bullseye is, which coalition owns which one, or how to walk a
        # great circle. Same rule that took the ghost check out of it.
        "bulls": _from_bullseye(scope, u.name),
    }


def _from_bullseye(scope, track: str) -> dict:
    """Range and bearing from the bullseye the CONTACT'S OWN coalition uses.

    His own, not ours, and the reference is named in the result so the page can
    print it. Referencing a red contact to the blue bullseye would produce a
    number no pilot in it could confirm, and an unlabelled mixture of two
    origins in one table is precisely the confusion this whole day was spent
    removing.

    Empty when the sim has not given us a bullseye or the contact has no
    position -- absent, rather than a plausible wrong number.
    """
    c = scope.of(track) if hasattr(scope, "of") else None
    if not c or c.get("lat") is None:
        return {}
    # DCS: 2 is red, 3 is blue (`common_pb2.COALITION_*`). Neutral and "all"
    # have no bullseye of their own.
    ref = {2: "red", 3: "blue"}.get(c.get("coalition"))
    b = (getattr(scope, "bullseye", None) or {}).get(ref or "")
    if not b:
        return {}
    nm, radial = _range_radial((b["lat"], b["lon"]), c["lat"], c["lon"])
    return {"ref": ref, "range_nm": round(nm, 1), "radial": round(radial)}


def _plan_row(plan: dict, flying_it: str, on_board: dict, track_of: dict,
              unit_of: dict) -> dict:
    """One filed strip, and what -- if anything -- is flying under it.

    Everything here is a join of facts somebody upstream already stated: the
    strip came from the director's `flight_plans` table, the board row from the
    separation engine, the track from the identity registry and the parked flag
    from the scope. Nothing is inferred, which is why the page can be told to
    print it and nothing else.
    """
    # The strip's own callsign is the key it was FILED under; `flying_it` is
    # whoever the registry matched to it, which is the name the board uses.
    cs = flying_it or ""
    row = on_board.get(cs)
    track = track_of.get(cs, "")
    unit = unit_of.get(_key_name(track)) if track else None
    return {
        **plan,
        "attributed_to": cs if row is not None else "",
        "track": track,
        # A FLIGHT OR A SINGLE, from the engine's own `members` -- which is the
        # authority, because a joined formation IS one entity to it and that is
        # the whole reason the field exists.
        "is_flight": bool(row and row.get("members")),
        "members": list(row.get("members") or []) if row else [],
        "phase": row.get("phase") if row else "",
        # None, not False, when radar cannot see him: "parked" and "we do not
        # know" are different answers and only one of them is about the ground.
        "on_ground": unit.on_ground if unit is not None else None,
    }


def publish_state(bridge, ctl, scope: str, session_id: str,
                  units=None, handed=None, names=None, plans=None) -> None:
    """Write down what THIS BRIDGE believes, for anything that wants to show it.

    THE DASHBOARD WAS INVENTING THIS. `/diag` reconstructed the flight roster by
    replaying recorder events, decided for itself whether a board entry was a
    ghost by matching names, and re-parsed the radar prose a third time. Every
    one of those is a surface acting as an authority it is not -- and the ghost
    check got it wrong in exactly the way audit finding 1.1 got it wrong,
    comparing a spoken label against a printed radar name.

    The bridge already knows all of it, correctly, because it is the thing that
    decided it. So it publishes and the page renders. A file rather than an
    endpoint for the same reason the control spool is a file: the bridge is a
    host process, the kneeboard is a container, and a shared mount needs no
    open port.

    THE BOARD CARRIES ITS TRACK HERE, which is the part that makes the ghost
    question answerable at all. `controller.board()` cannot supply it -- the
    engine is blind and has never heard of a track -- so it is joined on at the
    one place that knows both, which is here.
    """
    from marshall.atc import identity as _id

    # callsign -> the track it was resolved to, from the registry that resolved
    # it. This is the join the dashboard could not make and should not have
    # been guessing at.
    track_of = {i.callsign: i.track
                for i in bridge.identity.by_guid.values() if i.callsign}
    # THE SAME MAP, SQUASHED, so a board key can find a handle that differs only
    # by case or decoration. This is the join `HANDOFF-board.md` asks for -- and
    # it is deliberately the LAST resort, below the track the row carries,
    # because a join that has to be got right in more than one place is the
    # thing that was wrong in the first place.
    _by_handle = {_key_name(k): v for k, v in track_of.items() if v}
    # AND BY FLIGHT: the board key for a formation is the FLIGHT's name, which
    # is nobody's handle. One entity, one clearance, one place in the letdown --
    # so the track that represents it is the LEAD's, which is also the only
    # answer that is safe, since every number read out has to describe the same
    # aeroplane every time.
    for _f in bridge.flights.flights.values():
        _lead = track_of.get(_f.lead) or _by_handle.get(_key_name(_f.lead), "")
        if _f.name and _lead:
            _by_handle.setdefault(_key_name(_f.name), _lead)
    # HOW he came to be that callsign, carried onto the board row. It used to
    # be a panel of its own; it belongs beside him, because "who does ATC think
    # this is" and "on what evidence" are one question.
    auth_of = {i.callsign: i.authority
               for i in bridge.identity.by_guid.values() if i.callsign}
    # SQUASHED, FOR THE SAME REASON `track_of` IS, and this one was missed on
    # the first pass -- which is the audit's central finding happening in real
    # time: a fix applied where the bug was found and not at the sibling call
    # site. The board is keyed "Sockeye", the registry "sockeye", so the live
    # board read `authority: ''` -- no provenance at all -- for a pilot whose
    # identity had in fact closed on radar. Found by flying it, not by the suite.
    _auth_by_handle = {_key_name(k): v for k, v in auth_of.items() if v}
    units = units if units is not None else _id.units_on(scope)
    on_scope = {_key_name(u.name) for u in units}
    unit_of = {_key_name(u.name): u for u in units}
    # THE STRIP, BY WHOEVER IS FLYING IT. Not by the callsign it was filed
    # under -- that stopped being anybody's name when the self-designated
    # callsign came out, so joining the two tables on it would now match
    # nothing. The registry holds the link, because matching the claim against
    # the strip is what it did to resolve him in the first place.
    by_plan = {i.plan: i.callsign
               for i in bridge.identity.by_guid.values() if i.plan and i.callsign}
    plan_of = {by_plan[p["callsign"]]: p for p in (plans or [])
               if p.get("callsign") in by_plan}

    board = []
    # FILLED FROM THE FINISHED BOARD, BELOW, not from the identity registry.
    #
    # It used to read `track_of` -- the registry -- and the registry only knows
    # a track for somebody whose RADIO has been resolved. An entry bound by
    # `Controller.bind` (or admitted any other way) had a perfectly good track on
    # its own row and was still absent here, so it counted as uncontrolled and
    # the man appeared on the board AND in the untracked table at the same time.
    #
    # Which breaks the one invariant that makes those two tables readable
    # together: every contact is in exactly one of them. Tracked and untracked
    # are complements, so the set has to come from the thing that defines
    # tracked -- the board.
    board_tracks: set = set()
    # The engine's own rows, by callsign, so a strip can be asked whether
    # anything is flying under it.
    on_board = {r.get("callsign", ""): r for r in ctl.board()}
    # What frequency the bridge last heard each one on. `may_be_vectored` uses
    # this to decide he has actually checked in here, so it is the same fact
    # that governs whether he gets worked -- worth showing beside what he is
    # doing rather than leaving as an invisible precondition.
    for row in ctl.board():
        cs = row.get("callsign", "")
        # THE ROW'S OWN TRACK, bound at the door by the caller that held both
        # names. The registry is the fallback for an entry admitted before this
        # existed, and it is a fallback rather than the answer because it was
        # the WRONG answer: `{i.callsign: i.track}` is keyed on a lowercase
        # handle and the board is keyed on a canonical, so `get("Sockeye")`
        # missed `"sockeye"` and emptied every derived column in this row --
        # type, position, plan, and `confirmed` degraded to `claimed`. Case is
        # not the whole of it either: in a flight the board key is the FLIGHT
        # name and no folding relates "Apex" to "sockeye".
        track = row.get("track") or track_of.get(cs, "") or _by_handle.get(
            _key_name(cs), "")
        # WHAT HE IS FLYING AND WHERE, joined on the TRACK rather than the name.
        # The engine is blind -- it has never seen a radar picture and holds no
        # type, heading or altitude -- so every one of these comes off the scope
        # and none of it is the page's to work out. The join is by track for the
        # same reason the ghost check is: a spoken label and a printed radar
        # name are different strings for the same aeroplane.
        u = unit_of.get(_key_name(track)) if track else None
        fix = radar_fix_by_track(scope, track) if track else None
        if track:
            board_tracks.add(_key_name(track))
        board.append({**row, "track": track,
                      "freq_mhz": bridge.heard_on.get(cs, 0) / 1e6 or None,
                      "authority": (auth_of.get(cs)
                                    or _auth_by_handle.get(_key_name(cs), "")),
                      # WHAT THE SIM SAYS HE IS DOING -- parked, taxiing,
                      # rolling, airborne. Beside `intent` (what he asked for)
                      # and `phase` (what the engine has decided), because the
                      # three answer different questions from different
                      # authorities and only one of them can be wrong quietly.
                      "state": sim_state(scope, track, fix) if track else "",
                      # WHO IS WORKING HIM, and what he said he wants. Both from
                      # the engine, which is where they are now recorded.
                      "owner": row.get("owner", ""),
                      "intent": row.get("intent", ""),
                      "type": getattr(u, "type", ""),
                      "range_nm": getattr(fix, "range_nm", None),
                      "radial": getattr(fix, "radial_deg", None),
                      "alt_ft": getattr(fix, "alt_ft", None),
                      "heading": getattr(fix, "heading_deg", None),
                      "speed_kt": getattr(fix, "speed_kt", None),
                      "plan": plan_of.get(cs),
                      # Three answers, not two. RADAR means his track is on the
                      # scope now. CLAIMED means the ladder resolved him from a
                      # filed strip or the roster and there is no track to
                      # check -- he is real but unconfirmed, which is not the
                      # same as a ghost. UNSEEN means nothing accounts for him.
                      "confirmed": ("radar" if track and _key_name(track) in on_scope
                                    else "claimed" if not track
                                    else "unseen")})

    state = {
        "at": time.time(),
        "session": session_id,
        "board": board,
        "flights": [{"name": f.name, "lead": f.lead, "members": list(f.members)}
                    for f in bridge.flights.flights.values()],
        # EVERY STRIP ON FILE, AND WHO IT LANDED ON.
        #
        #     "so that I can see what atc knows about available flight plans and
        #      if it can attribute those plans to a single or flight - both on
        #      the ground and in the air"
        #
        # Attribution is the question, and it is not the same as "is there a
        # plan". A plan filed under a callsign nobody is using is inert; a plan
        # whose callsign is on the board is doing work -- it is the rung of the
        # identity ladder that resolved him. Which of those it is has been
        # decidable only by reading two panels and joining them by eye.
        #
        # ON THE GROUND vs IN THE AIR comes from the scope, because it changes
        # what the plan means: a strip attached to an aeroplane still parked is
        # a clearance waiting to be delivered, and the same strip attached to
        # something airborne is a controller's record of what he is working.
        # Unattributed says neither, and shows nothing rather than guessing.
        "plans": [_plan_row(p, by_plan.get(p.get("callsign"), ""),
                            on_board, track_of, unit_of)
                  for p in (plans or [])],
        # RADIOS THAT TRANSMITTED AND NEVER BECAME AN AEROPLANE. Empty when
        # things are working, which is the point: a man talking on the
        # frequency who is on no board and tied to no track is answered
        # conversationally while nothing is ever sequenced, and until now that
        # showed up nowhere at all.
        "unidentified": [{"radio": names.get(g, g[:8]) if names else g[:8],
                          "callsign": i.callsign, "authority": i.authority,
                          "why": i.why, "heard": bridge.transmitters.get(g, "")}
                         for g, i in bridge.identity.by_guid.items()
                         if not i.track],
        # WHAT THE CONTROLLER WAS ACTUALLY HANDED, block by block. Behaviour
        # follows from this and from nothing else -- if he did something
        # inexplicable, the explanation is in here or it is in the model. Every
        # other panel on that page is a derived view of state; this is the
        # input itself, which is why it is worth the 2.5 kB.
        #
        # The blocks arrive already separated because `compose_message` built
        # them as a list. Splitting the joined string back up would be the page
        # inventing structure again, one layer down.
        "handed": list(handed or []),
        # THE ONES RADAR CANNOT ACCOUNT FOR. Something admitted them and nothing
        # confirms them now, which is the only one of the three `confirmed`
        # answers that is a fault rather than a stage.
        #
        # PUBLISHED BECAUSE THE PAGE WAS READING IT AND IT WAS NEVER SENT. The
        # verdict banner asked for `ghosts`, no such key was ever written, so
        # `(d.ghosts || []).length` was 0 on every render and the page reported
        # "board and radar agree" for the whole life of the field -- including
        # while it was displaying a ghost row underneath. An indicator that
        # cannot go red reads exactly like one that is green.
        "ghosts": [r["callsign"] for r in board if r["confirmed"] == "unseen"],
        # BOARD ENTRIES THAT CAME OFF, with the scope as it stood at the time.
        # Empty when things are working. See `Bridge.releases`: a release is the
        # only board event that destroys its own evidence, and nine wrong ones
        # went unnoticed for a sortie because the only record was a print.
        "releases": list(bridge.releases),
        # EACH CONTACT, AND WHETHER ANYBODY IS CONTROLLING IT. The judgement is
        # made here rather than in the page for the usual reason: deciding that
        # a MANNED contact with no board entry is worth a second look means
        # knowing what manned means, and the page is not allowed to.
        #
        # A manned aeroplane radar can see and the engine has never heard of is
        # either somebody who has not checked in, or -- worse and invisible
        # until now -- somebody who IS talking whose identity never closed, so
        # every call he makes is answered and nothing is ever sequenced.
        "scope": [_contact(u, scope, board_tracks) for u in units],
        # THE MEANING OF THE VALUES, published with them. A page that knows
        # `radar` is better than `plan`, or which recorder kinds belong to which
        # stage, is a page holding domain knowledge -- and it will be wrong the
        # first time either changes without anybody thinking to look in the
        # JavaScript. So the levels come from here, where the words are defined,
        # and the page only knows how to colour ok / warn / bad.
        "legend": {
            "authority": {"radar": "ok", "plan": "warn", "roster": "warn",
                          "": "bad"},
            "confirmed": {"radar": "ok", "claimed": "warn", "unseen": "bad"},
            # WHAT THE SIM SAYS HE IS DOING. No level on any of them: parked is
            # not worse than airborne, it is somewhere else in the sortie. The
            # empty string is the exception and it IS worth a colour -- it means
            # we have no track for a board entry, so nothing can be said about
            # where he is at all.
            "state": {"parked": "", "taxiing": "", "rolling": "",
                      "airborne": "", "on the ground": "", "": "warn"},
            # WHETHER ANYBODY HAS ASKED HIM WHAT HE WANTS. Blank is a warning
            # and not an error: a controller who has not established intentions
            # has not finished his first job, which is exactly the thing worth
            # seeing on a page and never worth guessing at.
            "intent": {"": "warn"},
            # WHO OWNS HIM. Unowned while on the board is the contradiction --
            # he is being separated by nobody in particular.
            "owner": {"": "bad"},
            # WHICH BRAIN SAID IT. The stage says WHEN in the turn; this says
            # WHO, and they are different questions the page had no way to ask.
            #
            #   engine  deterministic -- separation and geometry. Never a guess,
            #           and the half that must never be a model's invention.
            #   agent   Bedrock. Language and judgement.
            #   guard   the receive loop's own rules, refusing or correcting
            #           BEFORE either brain sees the call. "You are Sockeye, use
            #           that callsign" is a guard speaking, not a controller
            #           deciding -- and reading it as the controller is how a
            #           mechanical correction gets mistaken for judgement.
            #
            # Published here for the same reason every other meaning is: the
            # page is not allowed to know that `asr` is deterministic.
            "origin": {
                "controller": "engine", "asr": "engine",
                "atc/vector": "engine", "atc/range": "engine",
                "atc/landed": "engine",
                "atc/pilot": "agent", "atc/simple": "agent",
                "dropped": "guard", "ship-to-ship": "guard",
                "atc/challenge": "guard", "atc/misnamed": "guard",
                "released": "guard", "flight/created": "guard",
                "flight/joined": "guard", "flight/refused": "guard",
                "flight/left": "guard", "flight/dissolved": "guard",
            },
            "kind": {k: {"stage": st, "level": lv} for k, st, lv in (
                ("dropped", "admit", "bad"),
                ("ship-to-ship", "admit", "bad"),
                ("atc/challenge", "admit", "warn"),
                ("flight/created", "membership", "ok"),
                ("flight/joined", "membership", "ok"),
                ("flight/refused", "membership", "warn"),
                ("flight/left", "membership", "ok"),
                ("flight/dissolved", "membership", "warn"),
                ("controller", "decide", "ok"),
                ("asr", "decide", "ok"),
                ("atc/pilot", "speak", ""),
                ("atc/simple", "speak", ""),
                ("atc/vector", "speak", ""),
                ("atc/range", "speak", ""),
                ("atc/landed", "speak", ""),
            )},
        },
    }
    try:
        out = config.BUILD_DIR / "control"
        out.mkdir(parents=True, exist_ok=True)
        (out / "state.json").write_text(json.dumps(state))
    except (OSError, TypeError, ValueError) as e:
        print(f"  !! could not publish state: {e}", flush=True)


def hear(bridge, client, model, profile):
    """One transmission off the radio, as words. [LAYERS.md] L0 -> the turn.

    EXTRACTED VERBATIM, 30 July. Returns None where the loop used to
    `continue` -- for no audio and for an empty transcript, which both led to
    the same `continue` and are therefore the same answer. That is the only
    change of shape, and it is what a function can express that a loop body
    cannot.

    Knows nothing about aviation: audio in, a transcript and the name of the
    radio that keyed the mic out. It is the lowest stage and should stay the
    most boring one.
    """
    from marshall.radio import stt

    pcm, heard_hz = client.recv_utterance(max_wait=3600)
    if pcm is None or not pcm.size:
        return None
    transcript = stt.transcribe(
        model, pcm,
        prompt=whisper_vocabulary(bridge, profile,
                                  roster=getattr(client, "roster", None)))
    if not transcript:
        return None
    return transcript, client.name_for(client.last_sender_guid), heard_hz


def attribute(bridge, client, transcript, srs, session_id, radar_on, ctl,
              field: str = ""):
    """WHO is talking, decided by something other than what he said.

    EXTRACTED VERBATIM, 30 July. Returns the five things the rest of the turn
    keys on: the scope it was decided against, what the words CLAIMED, the
    identity, the label to address him by, and the person.

    THE SCOPE IS FETCHED FIRST and that ordering is the design, not an
    accident of where the line sits: the strongest evidence about identity is
    in it, and the chain radio GUID -> client name -> unit -> track has no
    microphone in it anywhere. A garbled callsign cannot move it. See
    identity.py and [ARCH-2] / #40; 846 recorded transmissions say the words
    alone would bind a radio to 37 distinct names, of which ten were
    aeroplanes.
    """
    # `field` is the SPEAKING controller's aerodrome, so his ranges and
    # radials are measured from his own field rather than from the
    # profile's beacon at the other end of the route. See `field_origin`.
    scope = (fetch_radar(session_id, profile=getattr(ctl, "profile", None),
                         field=field)
             if radar_on else Scope(""))

    # What the WORDS claim, still by vote across the sortie: real callsigns
    # repeat and noise does not. Demoted from the answer to a claim, which
    # is then matched against a track or a filed strip.
    claim = transmitter_callsign(bridge, client.last_sender_guid, transcript)
    # "APEX 1-2" IS NOT A NAME ANYBODY IS ADDRESSED BY. It is how a flight
    # speaks to itself, and it used to be grounds for DROPPING the
    # transmission -- the controller said nothing at all. That gate is gone:
    # ATC answers everything on this frequency, because ship-to-ship does not
    # belong on it and a pilot who hears silence cannot tell it from a dead
    # radio.
    #
    # The knowledge is still worth having, one step further in. Left as a
    # claim it would become his LABEL, and the controller would start calling
    # a man by a member number nobody uses on the air.
    if claim and fl.is_intra_flight(claim, bridge.flights.names()):
        claim = ""
    _ident = bridge.identity.resolve(
        client.last_sender_guid or "", srs, spoken=claim, scope=scope,
        plans=filed_plans(), roster=ctl.identified())
    known = _ident.callsign
    # The human, out of the squadron name -- unique per person, never
    # spoken, and the same whatever callsign he is using. It is what a
    # formation split falls back to; see identity.handle.
    #
    # THE IDENTITY'S OWN LABEL WHEN THERE IS NO TRACK, which is not a second
    # source of truth: since the self-designated callsign came out, that label
    # IS the handle -- taken from the radio's name when the chain stopped short
    # of an aeroplane. Deriving it only from the track meant `_who` was empty
    # for every pilot a NO-RADAR field identified from a strip, so `flights.of`
    # was never consulted and a wingman went on being addressed by a member
    # number. Precisely the capability this system is meant to support well.
    _who = identity.handle(_ident.track) if _ident.track else _ident.callsign
    return scope, claim, _ident, known, _who


def compose_message(bridge, scope, known, transcript, profile, me, fix, nxt,
                    directive, stack, vectoring, _flight, _flight_say,
                    claim="", name_say=""):
    """Everything the controller is handed for one transmission, as one string.

    EXTRACTED VERBATIM from the receive loop, 30 July -- [LAYERS.md] step 1.
    Not one line of the body changed; it moved. The loop had no home for the
    turn, so the turn became a file, and this was 164 lines of it sitting in the
    middle of a `while True`. It is a pure function of its arguments with no
    side effects, which is why it went first: the extraction is provably
    behaviour-preserving and `tests/test_loop.py` already asserts on exactly
    what it returns.

    THE TWELVE PARAMETERS ARE THE FINDING, not an accident of the mechanical
    move. This block genuinely depends on twelve pieces of loop state, which is
    what "the assembly is entangled" means when you count it. Several of them
    are about to become stores rather than locals ([LAYERS.md] step 3), and the
    signature will shrink on its own when they do. Shrinking it by hand now
    would be improving rather than moving, and those are not the same commit.

    `parts` order is the prompt's order and it is load-bearing: the situation
    comes first and `PILOT:` comes last, because `director/tools/context.py`
    strips everything before that marker out of the conversation history. Move
    the marker and [CTX-1] silently stops working.
    """
    from marshall.atc import controller
    from marshall.core import route as R

    parts = []
    if scope:
        parts.append(f"RADAR: {scope}")
    if not known:
        parts.append("TRANSMITTER: a radio you have not identified yet.")
    else:
        # WHO HE IS, ON EVIDENCE THAT IS NOT HIS VOICE. This said "the radio
        # calling itself {known}" -- which stopped being true the day the label
        # stopped coming off the radio. `known` is now his HANDLE, taken from
        # the sim's name for his aeroplane or from the name his radio arrived
        # with, and a pilot may perfectly well say something else.
        #
        # WITHOUT THE SECOND SENTENCE THE AGENT ARGUES WITH HIM, and it is not
        # a small failure. Seen in the dry run the hour this changed: a man
        # checked in as "Pony one one", the controller directive named "Sockeye
        # flight", and the agent -- handed two names and no statement that they
        # were one man -- answered "I show no flight plan under that callsign,
        # say your callsign again", then "station calling, I have you as
        # Sockeye flight, say again to confirm". Three transmissions of a
        # controller challenging a pilot who had done nothing wrong.
        _also = (f" He called himself {claim} on this transmission; that is the "
                 f"same man and it is not a discrepancy to raise with him."
                 if claim and claim.lower() != known.lower() else "")
        parts.append(
            f"TRANSMITTER: {known}, identified from his aircraft rather than "
            f"from anything he said, so this is certain. Address him as "
            f"{known}.{_also} Same aircraft as every other call from {known} "
            f"-- keep them together.")
    _strip = flight_strip(_flight)
    if _strip:
        parts.append(
            _strip + " This is what is already known about him and it "
            "carries across a handoff -- do not ask him again for anything "
            "in it.")
    if name_say:
        # ABOVE EVERYTHING ELSE, because it is about who he is and the rest of
        # the transmission is addressed to whoever that turns out to be. It does
        # not replace the answer -- he still gets worked -- it precedes it.
        parts.append(
            "CALLSIGN CORRECTION (already decided — SAY THIS FIRST, in these "
            f"words, then answer his call normally): {name_say}")
    if _flight_say:
        # DECIDED HERE, NOT BY YOU. Who is in which flight is roster state
        # and radar geometry -- the same class of fact as separation, and
        # the same reason it is not the model's to invent. The verdict is
        # already computed; the agent's whole job is to say it.
        #
        # It sits ABOVE the approach directive on purpose. A man who has
        # just been refused a join needs that answer first, and the two are
        # never in conflict because they are about different things.
        parts.append(
            "FLIGHT (already decided from the roster and radar — SAY THIS "
            "and do not reword the callsigns, the flight name or the "
            f"distances): {_flight_say}")
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
            "eight decimal zero\" — then give him what he asked for. Saying only which "
            "frequency he wanted leaves him still not knowing which button "
            "he is holding, and a pilot who has lost track of that gets it "
            "wrong again on the next call. He is flying an aeroplane; do "
            "not make him ask twice.")
        # WHO HE IS, as distinct from what he does. See `Station.manner`.
        #
        # Fenced hard, and the fence is the point rather than boilerplate: a
        # personality that can decline work or round a heading has stopped
        # being a voice and become a fault -- and it would be diagnosed by
        # somebody reading the separation engine, which would be innocent.
        # So the manner is explicitly told it owns the words AROUND the
        # numbers and never the numbers.
        if getattr(me, "manner", ""):
            parts.append(
                f"YOUR MANNER: {me.manner}\n"
                "This is HOW YOU SOUND and nothing more. It never changes "
                "WHAT you say: the altitudes, headings, frequencies, "
                "sequence and required read-backs are decided elsewhere and "
                "are identical whoever is on the microphone. A short-tempered "
                "controller issues exactly the same clearance as a cheerful "
                "one and is merely briefer about it. You may never refuse "
                "work that is yours, skip a read-back, omit a number, round "
                "one off, or be slower to help because of your manner -- and "
                "if a pilot is in trouble, lost, or asking for help, every "
                "personality here drops it instantly and becomes plain, "
                "clear and useful.")
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
    # words. See bridge.awaiting_readback.
    if known and readback_due(bridge, known):
        bridge.awaiting_readback.pop(known, None)
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
    if known and reads_back_what_we_said(bridge, known, transcript):
        parts.append(
            "READ-BACK CORRECT: those numbers are what you actually gave "
            "him. Do NOT say negative and do not correct him -- he got it "
            "right. If you now want something different, that is a NEW "
            "instruction: say \"amend\" and give it, so he knows it is a "
            "change and not a mistake he made.")
    parts.append(f"PILOT: {transcript}")
    # The joined message AND the blocks it was built from. The blocks go
    # to /diag so a pilot can see what the controller was handed; splitting
    # the joined string back up there would be the page inventing structure
    # that existed here all along.
    return "\n".join(parts), parts


def _start_atis(host: str, ear, profile, session_id: str) -> None:
    """Put every broadcasting aerodrome on the air, each on its own client.

    NOT FROM THE TRANSMIT POOL, deliberately. An ATIS is twenty-two seconds of
    audio every thirty -- near enough continuous -- so five fields would hold
    half a pool of ten permanently and starve the controllers. A dedicated
    client costs 4 ms and two file descriptors, and there is no practical
    ceiling: 100 opened in 0.4 s against 524,288 descriptors.

    The ear ignores these too. They are our own voices coming back, and a
    controller must not stand off for the weather.
    """
    from marshall.atis import serve as _serve
    from marshall.core import route as _R
    from marshall.radio import tts as _tts
    from marshall.radio.client import AM as _AM, SRSClient as _Cl, radio as _rad

    fields = [f for f in _R.FIELDS if getattr(f, "atis_mhz", 0)]
    if not fields:
        return
    mouths = {}
    for f in fields:
        c = _Cl(host, name=f"ATIS {f.name}").connect([_rad(f.atis_mhz * 1e6, _AM)])
        mouths[f.name] = c
        ear.ignore_guids.add(c.guid)

    by_hz = {round(f.atis_mhz, 3): mouths[f.name] for f in fields}

    def transmit(frames, mhz):
        by_hz[round(mhz, 3)].transmit(frames, mhz * 1e6, _AM)

    def anybody_flying() -> bool:
        # A broadcast to an empty server costs money and means nothing -- see
        # `serve`. Best-effort: if we cannot tell, assume somebody is there,
        # because going silent by mistake is worse than a few cents.
        try:
            from marshall.feed import dcs as _dcs
            return "No player-controlled units" not in _dcs.get_player_units()
        except Exception:
            return True

    def run():
        _serve.serve(fields, transmit,
                     _tts.Voice(voice_id=_serve.broadcast.ATIS_VOICE,
                                engine=_serve.broadcast.ATIS_ENGINE),
                     _eval_lua, mission_clock=None,
                     anybody_flying=anybody_flying,
                     log=lambda m: print(m, flush=True))

    threading.Thread(target=run, daemon=True).start()


def _eval_lua(lua: str) -> str:
    """Run Lua in the sim. Its own function so `atis` can be handed a callable
    and never import the gRPC stubs."""
    from marshall.feed import stubs
    stubs.bind()
    import grpc
    from dcs.custom.v0 import custom_pb2, custom_pb2_grpc
    from marshall.feed.dcs import DCS_GRPC_ADDR
    with grpc.insecure_channel(DCS_GRPC_ADDR) as ch:
        r = custom_pb2_grpc.CustomServiceStub(ch).Eval(
            custom_pb2.EvalRequest(lua=lua), timeout=25.0)
    return str(r.json).strip('"')


def _run_srs(host: str, freq_mhz: float, voice_id: str = "Matthew",
             session_id: str | None = None, url: str = AGENT_URL) -> None:
    from marshall.atc import asr, controller
    from marshall.core import route as R
    from marshall.radio import stt, tts
    from marshall.radio.client import AM, SRSClient, radio
    from marshall.radio import pool

    freq_hz = freq_mhz * 1_000_000
    session_id = session_id or f"batumi-approach:{freq_mhz:.3f}"
    # THIS bridge's state. Not a module global, so a second one -- another
    # field, another frequency, a test -- gets its own. [LAYERS.md] step 2.
    bridge = Bridge()
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
    def channels_of(hz: float | None):
        """Every frequency the facility on this channel is heard on.

        ONE TRANSMISSION, ALL ITS FREQUENCIES. A facility can own several -- the
        published one a modern radio tunes and a rounded one an SCR-522 can
        reach -- and answering on only the channel a call ARRIVED on leaves the
        other aeroplane listening to silence. The SRS packet carries a frequency
        list, so this costs nothing: one voice, one moment, every radio.

        Falls back to the single channel when no station claims it, which is the
        engineering line and anything else off the plate.
        """
        st = (profile.station_on((hz or freq_hz) / 1_000_000)
              if hasattr(profile, "station_on") else None)
        if st is None:
            return hz or freq_hz
        return [f * 1_000_000 for f in st.freqs]

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
        # EVERY frequency of every facility, not one each. A station can be
        # heard on several -- the published one a modern radio tunes and the
        # rounded one an SCR-522 can reach -- and a warbird checking in on the
        # channel we are not listening to is a pilot talking to nobody.
        channels = [f for st in profile.stations for f in st.freqs if f]
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
    _radios = [radio(mhz * 1_000_000, AM) for mhz in channels]
    # THE EAR. One client, every frequency, and it never transmits -- so it can
    # never be blocked by a transmission in progress. It is also the only thing
    # that decides whether a channel is busy, per channel: see `last_rx_hz`.
    client = SRSClient(host, name=SRS_NAME,
                       eam_password=config.SRS_EAM_PASSWORD).connect(_radios)
    # THE MOUTHS. A pool, because one client plays one stream at a time and
    # controllers at two aerodromes should not queue behind each other -- see
    # `radio/pool.py` for the measurements that sized it.
    _pool = pool.TransmitPool(host, size=config.RADIO_POOL_SIZE,
                              radios=_radios, log=lambda m: print(m, flush=True))
    # AND THE EAR IGNORES THEM. With one client this was impossible: SRS does
    # not echo a client to itself. With a pool our own voice comes back and
    # looks exactly like a pilot, so a controller would stand off for himself
    # for a second and a half after every word.
    client.ignore_guids |= _pool.guids
    print(f"  transmitting on {config.RADIO_POOL_SIZE} clients", flush=True)
    ctl = controller.Controller(profile)  # deterministic separation, seeded from the approach
    # PUBLISH BEFORE THE FIRST TRANSMISSION. Otherwise a restarted bridge shows
    # the PREVIOUS one's beliefs until somebody keys a mic -- a board with
    # aircraft on it, from an engine that has just been emptied. The age field
    # gives it away, but a page that has to be read twice to be believed is not
    # doing its job.
    publish_state(bridge, ctl, "", session_id, plans=filed_plan_rows())
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

    def channel_is_free(now: float | None = None,
                        on_hz: float | None = None) -> tuple[bool, str]:
        """Is it courteous to speak? `on_hz` is WHICH channel we mean.

        Omitting it asks "is anybody talking anywhere", which is what this
        always used to mean and stopped being right when the theatre grew a
        second aerodrome: one client listens on twelve frequencies, so a pilot
        checking in with Kobuleti Clearance held Batumi Approach silent forty
        miles away. A courtesy applied to the wrong conversation.

        A facility's OTHER frequencies count as the same channel -- 124.425 and
        124.000 are one conversation reaching two kinds of radio -- which is why
        this asks about `channels_of` rather than the single number.
        """
        now = now or time.monotonic()
        if client.someone_is_talking(freq_hz=channels_of(on_hz) if on_hz else None):
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
        # THE MODEL CALL DOES NOT NEED THE RADIO, and holding it across one
        # serialised the wrong thing entirely.
        #
        # `radio_lock` exists so two voices are never on the air at once. It was
        # wrapped around this whole function, which also contains a Bedrock call
        # -- measured across 372 real transmissions at a median of 3.3 s, p90
        # 6.4 s and a worst case of 13.5 s. Add the settle and the audio and the
        # radio was held for roughly 7 to 13 seconds per reply, of which only
        # the last few were actually speech.
        #
        # With one pilot that is invisible: he is waiting for his own answer and
        # it reads as latency. With two pilots at two aerodromes it is a
        # controller who has gone deaf -- Kobuleti Tower silent for thirteen
        # seconds because Batumi Approach is thinking.
        #
        # Two controllers may compose at the same time. They contend only for
        # the moment they speak.
        #
        # WHAT THE LOCK WAS ALSO PROTECTING, by accident: `handoff_due` is set
        # by the receive loop just before this runs, and reading it after a long
        # unlocked model call could pick up a LATER turn's authorisation. So it
        # is captured here, while the caller's turn is still the current one.
        _authorised = bridge.handoff_due[0]
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
        # NOBODY IS SENT AWAY WITHOUT THE BRIDGE SAYING SO. The rules ask
        # the model not to invent a handoff and it did anyway, live, to a
        # pilot parked on the ramp. Guidance where a guarantee was needed.
        _me_here = (profile.station_on((on_hz or freq_hz) / 1_000_000)
                    if hasattr(profile, "station_on") else None)
        reply, sent = strip_unauthorised_handoff(
            reply, _authorised,
            keep_him=(f"{to_callsign}, {_me_here.name}, go ahead."
                      if to_callsign and _me_here else ""))
        if sent:
            print(f"  .. refused an unauthorised handoff: {sent}",
                  flush=True)
        if not reply or reply.lower() in NO_CALL:
            print(f"  ATC[{kind}/{tier}] ({dt:.1f}s): (no call)", flush=True)
            return
        # RENDERED BEFORE THE LOCK. Polly is a network call too, and it is
        # cached -- so this is free on a repeat and must not be a reason to
        # hold the air on a miss.
        _frames = voice_for(on_hz).frames(reply)
        # ONLY THE SPEAKING IS SERIALISED, from here down.
        with radio_lock:
            print(f"  ATC[{kind}/{tier}] ({dt:.1f}s): {reply}", flush=True)
            bridge.last_said[0] = reply
            if to_callsign:
                note_issued(bridge, to_callsign, reply)
            record(session_id, kind=f"atc/{kind}", tier=tier,
                   seconds=round(dt, 1), to=addressed_to(reply),
                   freq_mhz=(on_hz or freq_hz) / 1_000_000, text=reply)
            # Answer on the channel he called from -- that is the beacon he is
            # homing, and therefore the only one he can hear.
            _pool.transmit(_frames, channels_of(on_hz), AM)
            # He is owed room to read that back, and we want to HEAR the
            # readback -- it is the only check on whether he got the numbers
            # right, and several were mangled on the sortie that prompted this.
            hold_the_channel_for_a_readback()

    def scheduler() -> None:
        # Fire the agent's own wake-up hooks: when a timer expires, re-invoke it
        # with the hook's reason so it makes the call it scheduled.
        while True:
            time.sleep(HOOK_POLL_SEC)
            # Anybody who has left his aeroplane comes off the board first, so
            # a stale callsign cannot make the separation engine engage against
            # a pilot who is alone. Rides this tick because it is already here;
            # it costs one request and usually returns nothing.
            _scope = (fetch_radar(session_id, profile=profile)
                      if radar_on else Scope(""))
            for gone in release_stale(bridge, ctl, _scope):
                print(f"  .. {gone} — nothing has accounted for him in "
                      f"{STALE_BOARD_SEC // 60} minutes, off the board", flush=True)
                record(session_id, kind="released", callsign=gone)
            # AND PUBLISH, ON THE PICTURE THIS TICK ALREADY FETCHED.
            #
            #     "F16 on the ground at Batumi. Looking at diag. I would expect
            #      myself to be in the untracked column since I have not checked
            #      in. Nothing here"
            #
            # Right, and the snapshot was written on TRANSMISSIONS only, plus
            # once at startup with an empty scope. So a diagnostic board showed
            # nothing at all until somebody keyed a microphone -- and the whole
            # point of the untracked column is the aeroplanes that have NOT
            # spoken. It could not have worked.
            #
            # This tick is the right home for it: it already has the radar
            # picture for `release_stale`, so the board refreshes at the poll
            # rate for no extra request and no extra latency on the voice path.
            # `filed_plans` is what REFRESHES the strip cache; `filed_plan_rows`
            # only reads it. On this tick nothing else called it, so the plans
            # panel stayed empty for the whole sortie -- the cache was never
            # filled and the reader dutifully returned nothing. It is TTL'd at
            # 45 s, so calling it here costs one request a minute.
            filed_plans()
            publish_state(bridge, ctl, _scope, session_id,
                          plans=filed_plan_rows(),
                          names=getattr(client, "roster", None))
            for hook in fetch_due(session_id):
                scope = (fetch_radar(session_id, profile=profile)
                         if radar_on else Scope(""))
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
                on_hz = hook_frequency(why, bridge.heard_on, bridge.last_active_hz[0])
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
        # SEEN AIRBORNE AT LEAST ONCE. Without it, "he is on the ground and on
        # the board" reads as "he has just landed" -- and a pilot taxiing OUT
        # got the arrival farewell before he had flown anywhere:
        #
        #     PILOT: Batumi Tower, Depart, holding short runway one three,
        #            ready for departure.
        #     ATC:   Depart, Batumi Tower, welcome. Exit the runway when able,
        #            taxi to parking. Good day.
        #
        # Landing is a TRANSITION, not a state: air, then ground. The state
        # alone cannot tell an arrival from somebody who has not left yet, and
        # the same confusion is why `test_tonight.py` exists -- a jet that
        # spawned on the ramp looks exactly like one that just rolled out.
        flown: set[str] = set()
        # Handed over already, so the offer is made ONCE. Cleared when the
        # handoff stops being due -- he changed frequency, or turned back.
        handed_off: set[str] = set()
        while True:
            time.sleep(ASR_POLL_SEC)
            if not (radar_on and getattr(profile, "vectored", False)):
                continue
            try:
                scope = fetch_radar(session_id, profile=profile)
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


                fixes = radar_fixes(scope, profile, ctl)
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
                    # THE EVENT FIRST. `asr.on_the_ground` is geometry, and it
                    # called the approach complete NINETEEN SECONDS before the
                    # sim's own `land` -- so the goodbye went out while he was
                    # still in the flare:
                    #
                    #     "Pretty sure it called me 'down' before the landed
                    #      event"
                    #
                    # The geometry stays as the fallback for a session where no
                    # event has been seen; it must not be the answer when the
                    # sim has one.
                    # HIS TRACK, NOT HIS CALLSIGN. `is_on_the_ground` matches
                    # the name the PICTURE prints -- "362nd_sockeye" -- and was
                    # being handed the board key, "Sockeye". Those never match,
                    # so the sim's own `on_ground` was skipped entirely and this
                    # fell through to the geometry fallback: below 100 ft AND
                    # under the speed gate. Rolling out at ninety-odd knots a
                    # pilot is plainly down and this said no, which is exactly
                    # what was reported --
                    #
                    #     "on touchdown, my status didn't change to on ground on
                    #      the board - I had to tell approach I was on the
                    #      ground"
                    #
                    # The board knows the track. The four names of one aeroplane
                    # again, in the one thread that decides when an approach is
                    # over.
                    _ac = ctl.aircraft.get(ctl._resolve(cs))
                    _track = getattr(_ac, "track", "") or cs
                    if is_on_the_ground(scope, _track, pos):
                        if cs in grounded:
                            continue
                        if cs not in flown:
                            # On the ground and never seen flying: he is
                            # departing, not arriving. Say nothing and wait.
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
                        free, why = channel_is_free(on_hz=final_hz)
                        if not free:
                            print(f"  .. holding {cs}'s goodbye: {why}", flush=True)
                            continue          # not marked down; it will repeat
                        grounded.add(cs)
                        print(f"  {cs} is on the ground — approach complete",
                              flush=True)
                        try:
                            ctl.report_down(cs)
                            bye = for_voice(" ".join(tx.text for tx in ctl.take_out()))
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
                                _pool.transmit(voice_for(final_hz).frames(bye),
                                                channels_of(final_hz), AM)
                        continue
                    grounded.discard(cs)        # airborne again: a new sortie
                    flown.add(cs)               # and now a landing is possible

                    # A HANDOFF NOBODY HAD TO ASK FOR.
                    #
                    #     "After departure, I had to initiate contact with tower
                    #      to get him to switch me to approach."
                    #
                    # `handoff_on_the_event` was already written and already
                    # correct -- on the ground under approach means Tower, and
                    # airborne under Tower means Approach. It just lived only
                    # inside the receive loop, so it fired when the PILOT SPOKE
                    # and never on its own. A controller who waits to be asked
                    # before handing you over is not watching, he is answering.
                    #
                    # This thread already has the picture and already knows who
                    # he is talking to, so the same call belongs here too. The
                    # loop keeps its copy: a handoff that becomes due mid-
                    # transmission should not wait for the next poll.
                    _who = ctl.aircraft.get(ctl._resolve(cs))
                    _tk = getattr(_who, "track", "") or cs
                    # WHICH CONTROLLER HE IS TALKING TO, not which frequency
                    # this thread transmits on. `final_hz` is the monitor's own
                    # channel -- Approach -- so asking it who "I" am made the
                    # answer Approach for everybody, and the rule that hands an
                    # airborne aircraft from TOWER to Approach could never fire.
                    # Measured: a departure sat at six thousand feet under Tower
                    # and was never offered anything.
                    #
                    # `heard_on` is where he actually checked in, which is the
                    # only thing that says whose aeroplane he is.
                    _hz = bridge.heard_on.get(ctl._resolve(cs)) or final_hz
                    _me = (profile.station_on(_hz / 1_000_000)
                           if hasattr(profile, "station_on") else None)
                    # Same evidence the receive path uses. Without the phase
                    # the monitor can watch a ramp all day and never move
                    # anybody off Clearance or Ground.
                    _v = _handoff.due(profile, _me, _handoff_state(
                        scope, _tk, pos,
                        getattr(_who, "sortie_phase", "") or ""))
                    # SAME MAN, DIFFERENT NAME. Approach and Departure are one
                    # controller on one frequency, so there is nobody to contact
                    # -- he simply answers as Departure while you are going out.
                    # Telling a pilot to call the person he is already talking
                    # to is nonsense on the radio.
                    _nxt = None if (_v is None or _v.same_station) else _v.station
                    if _nxt is not None and cs not in handed_off:
                        free, why = channel_is_free(on_hz=_hz)
                        if free:
                            handed_off.add(cs)
                            _say = for_voice(
                                f"{cs}, contact {_nxt.name} "
                                f"{controller.spell_freq(_nxt.freq_mhz)}.")
                            note_issued(bridge, cs, _say)
                            with radio_lock:
                                print(f"  ATC[handoff] {_say}", flush=True)
                                record(session_id, kind="atc/handoff",
                                       callsign=cs, text=_say, to=_nxt.role)
                                # ON HIS CHANNEL. Telling a man on Tower to
                                # contact Approach, over Approach, is a message
                                # to everyone except him.
                                _pool.transmit(
                                    voice_for(_hz).frames(_say), channels_of(_hz), AM)
                    elif _nxt is None:
                        handed_off.discard(cs)

                    if not may_be_vectored(bridge, ctl, cs, traffic=traffic,
                                           freq_hz=final_hz):
                        continue                # holding, or nobody's turn yet
                    g = asr.guide(pos, profile,
                                  on_missed=flying_the_missed(bridge, cs, pos, profile,
                                                              ctl))
                    note_missed(bridge, cs, g.phase, ctl)

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
                        free, why = channel_is_free(on_hz=final_hz)
                        if not free:
                            # Do NOT record it as issued -- he never heard it,
                            # and marking it sent would suppress the repeat.
                            print(f"  .. holding a vector for {cs}: {why}",
                                  flush=True)
                            continue
                        pending.pop(cs, None)
                        vectored[cs], vec_at[cs] = want, time.time()
                        text = for_voice(vector_call(bridge, cs, g, pos))
                        note_issued(bridge, cs, text)
                        with radio_lock:
                            print(f"  ATC[vec] {text}", flush=True)
                            # TELL THE ENGINE WHAT WE JUST CLEARED HIM TO.
                            # The board is the record of what was agreed, and
                            # this thread agrees things.
                            ctl.note_vectored(cs, g.altitude_ft)
                            record(session_id, kind="atc/vector", callsign=cs,
                                   range_nm=round(g.range_nm, 2),
                                   heading=want, alt=g.altitude_ft, text=text)
                            _pool.transmit(voice_for(final_hz).frames(text),
                                            channels_of(final_hz), AM)
                            hold_the_channel_for_a_readback()
                        continue

                    if g.phase not in ("final", "map"):
                        called.pop(cs, None)
                        continue
                    vectored.pop(cs, None)
                    mile = 0 if g.phase == "map" else int(round(g.range_nm))
                    if called.get(cs) == mile:
                        continue
                    free, why = channel_is_free(on_hz=final_hz)
                    if not free:
                        print(f"  .. holding the {mile} mile call for {cs}: "
                              f"{why}", flush=True)
                        continue        # not marked as called; it repeats
                    called[cs] = mile
                    text = for_voice(asr_call(bridge, cs, g, pos, profile))
                    note_issued(bridge, cs, text)
                    with radio_lock:
                        print(f"  ATC[asr] {text}", flush=True)
                        ctl.note_vectored(cs, g.altitude_ft)
                        record(session_id, kind="atc/range", callsign=cs,
                               range_nm=round(g.range_nm, 2), phase=g.phase,
                               heading=g.heading, text=text)
                        _pool.transmit(voice_for(final_hz).frames(text),
                                        channels_of(final_hz), AM)
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
            # THE CHANNEL THE BRIDGE WAS STARTED ON. There is no longer a
            # "line" to have been last spoken on: ATC, engineering and the
            # pilots share one frequency and each transmission says who it is
            # for. A broadcast to an unattended frequency is still possible,
            # still on purpose.
            hz = freq_hz
            for line in lines:
                with radio_lock:
                    print(f"  ENG[tx] {line}", flush=True)
                    record(session_id, kind="engineering/tx", text=line)
                    try:
                        _pool.transmit(eng_voice.frames(line), hz, AM)
                    except Exception as e:
                        print(f"  !! engineering transmit failed: {e}", flush=True)
                time.sleep(0.3)

    threading.Thread(target=engineering_radio, daemon=True).start()
    threading.Thread(target=scheduler, daemon=True).start()
    threading.Thread(target=asr_monitor, daemon=True).start()
    _start_atis(host, client, profile, session_id)

    while True:
        heard = hear(bridge, client, model, profile)
        if heard is None:
            continue
        transcript, srs, heard_hz = heard

        # Never answer another controller. A second bridge left running on the
        # same frequency -- trivially easy, since killing the launcher does not
        # kill the python child -- hears this one, treats the transmission as a
        # pilot call, and replies; then this one hears THAT. The two talk to each
        # other forever, jamming the frequency and burning tokens, and the
        # transcripts look almost plausible. Cheap guard, unbounded saving.
        if srs in OUR_STATIONS or client.last_sender_guid == client.guid:
            print(f"  (ignoring {srs} -- that is one of ours, not a pilot)",
                  flush=True)
            # RECORDED, not merely printed. A dropped transmission is the most
            # confusing thing there is from the cockpit -- it is indistinguish-
            # able from a dead radio -- and until the diagnostics page existed
            # the only account of WHICH gate ate it was a line on somebody's
            # stdout. See kneeboard/diag.py.
            record(session_id, kind="dropped", gate="one of ours",
                   srs_name=srs, text=transcript)
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
        # WHOSE SCOPE THIS IS. The station he called determines the field
        # every range is measured from -- an aeroplane on Kobuleti's ramp
        # read as 23 miles out while Kobuleti's own controllers were being
        # handed Batumi's geometry.
        _me_fld = profile.station_on((heard_hz or freq_hz) / 1_000_000) \
            if hasattr(profile, "station_on") else None
        scope, claim, _ident, known, _who = attribute(
            bridge, client, transcript, srs, session_id, radar_on, ctl,
            field=getattr(_me_fld, "field", "") or "")

        _flight_say = membership(bridge, _who, transcript, scope, _ident,
                                 session_id)

        # A CALLSIGN NOBODY ANSWERS TO gets corrected, even when we know exactly
        # who is talking. Deterministic -- whether a name is on the board is a
        # fact about the board -- so the agent is handed the words rather than
        # the question. Once per radio per wrong name; see `Bridge.corrected`.
        _name_say = ""
        _key = (client.last_sender_guid or "", (claim or "").lower())
        if claim and _key not in bridge.corrected:
            _name_say = misnamed(bridge, ctl, claim, known, _who)
            if _name_say:
                bridge.corrected.add(_key)
                print(f"  .. correcting {claim!r} — nobody answers to it",
                      flush=True)
                record(session_id, kind="atc/misnamed", callsign=known or srs,
                       claimed=claim, text=_name_say)

        # THERE IS NO ADOPTION, and there was a block here that called
        # `fl.parse_adopting` for it. The design settled the other way: a pilot
        # joins HIMSELF, on his own radio, because that is the transmission
        # radar can corroborate -- and rejoining after a break-out is joining
        # rather than a case of its own. `parse_adopting` went with the
        # simplification; this call site did not, and it crashed the bridge with
        # an AttributeError on the first transmission from anybody the ladder
        # identified by RADAR.
        #
        # It survived because it needs `_who`, `_who` needs a TRACK, and the two
        # ways a track was reachable were both blocked: a pilot resolved from a
        # filed strip has a callsign and no track, and formations resolved to
        # nothing at all until the line above them was fixed. So repairing
        # identity is what exposed it -- the flight rehearsal created Apex and
        # the bridge died on the very next call.

        # WHAT THE CONTROLLER CALLS HIM: the flight while he is in one, his own
        # handle otherwise, and never a member number.
        if _who and bridge.flights.of(_who) is not None:
            known = bridge.flights.speaking_as(_who)
        if _ident.authority and _ident.authority != "radar":
            # Worth a line in the log every time it is NOT the physical chain:
            # the day this reads "roster" for a pilot who should be on radar,
            # something upstream has broken.
            print(f"  (identity: {_ident.why})", flush=True)
        if known:
            # He has checked in HERE. Until he does, no controller on this
            # channel may start working him -- see may_be_vectored.
            # UNDER THE KEY THE BOARD USES, normalised at the WRITE. `known` is
            # a handle ("sockeye") or a flight name; the board is keyed on the
            # canonical ("Sockeye"), so writing it raw left three readers each
            # to fold it back and each to get it wrong differently -- the diag
            # frequency column was blank all sortie, and `may_be_vectored` asks
            # this same map whether he has checked in HERE.
            #
            # Both keys, because a reader holding the spoken form is still
            # right and this map is a cache, not an authority.
            bridge.heard_on[known] = heard_hz or freq_hz
            bridge.heard_on[ctl._resolve(known)] = heard_hz or freq_hz
            # And the channel the conversation is on, for anything owed to a
            # pilot later -- a hook whose reason names nobody still has to be
            # spoken where somebody is listening.
            bridge.last_active_hz[0] = heard_hz or freq_hz

        # WHO THE ENGINE IS BEING, from the frequency this call arrived on. The
        # engine is blind by design, and this is the one fact it cannot do
        # without: only Tower may clear a landing.
        _me_now = (profile.station_on((heard_hz or freq_hz) / 1_000_000)
                   if hasattr(profile, "station_on") else None)
        ctl.working = getattr(_me_now, "role", None)
        # AND WHICH ONE OF HIM, WHICH IS NOT THE SAME QUESTION.
        #
        # `working` is a ROLE and is right to be: it answers "what may this
        # controller do", and only Tower may clear a landing whichever field he
        # is at. OWNERSHIP is an identity -- "who has this aeroplane" -- and a
        # role cannot express it the moment there are two aerodromes, because
        # Batumi Approach and Kobuleti Approach are both `role="approach"`.
        #
        # A board reading `owner: approach` with two fields up does not say who
        # has him, and a handoff between the two would look like no change at
        # all. `Station` has carried the name the whole time; the bridge was
        # dropping it on the floor.
        ctl.station = getattr(_me_now, "name", "") or ""


        n_contacts = count_contacts(scope)
        tag = f" [RADAR: {scope}]" if scope else ""
        print(f"PILOT [{known or srs}]: {transcript}{tag}", flush=True)
        # BY TRACK FIRST. The callsign is a label and can be stale; the track
        # is the sim's own name for the aeroplane this radio is sitting in.
        #
        # THE LEAD'S AEROPLANE WHEN HE IS IN A FLIGHT, whoever keyed the mic.
        #
        #     "if a flight wants to fly an approach in formation - they can.
        #      That's up to the flight lead. But only the lead's a/c is used
        #      for vectors."
        #
        # Which is also the only answer that is safe. A formation is ONE entity
        # to the engine -- one level, one clearance, one place in the letdown --
        # so every number the controller reads out has to describe the same
        # aeroplane every time. Taking the transmitter's own track meant a
        # wingman asking a question got the whole flight vectored off HIS
        # position, three hundred feet and a few seconds displaced from the man
        # actually flying the approach, and the next call moved it back. The
        # geometry would wander with whoever spoke last.
        _lead_track = ""
        if (_mine := bridge.flights.of(_who)) is not None and _mine.lead:
            _lead_track = _track_of(scope, _mine.lead)
        _fix = (radar_fix_by_track(scope, _lead_track or _ident.track, profile)
                or radar_fix(scope, known, profile))
        record(session_id, kind="pilot", callsign=known or srs,
               # The provenance of the identity, not just the answer. Without
               # it a recording cannot be scored after the fact: "Pony 1-1" in
               # the log looks identical whether radar put it there or a
               # transcript did, and those are the two cases worth telling
               # apart. srs_name is here for the same reason -- it is the
               # strongest link and was not being preserved, so the replay of
               # every earlier sortie could only measure the weak paths.
               srs_name=srs, claimed=claim, authority=_ident.authority,
               track=_ident.track, who=_who, why=_ident.why,
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
        # ...and publish it, so the dashboard renders what this bridge believes
        # instead of reconstructing it from the log. See publish_state.
        publish_state(bridge, ctl, scope, session_id, plans=filed_plan_rows(),
                      names=getattr(client, 'roster', None))   # before the turn
        note_alive(bridge, known)          # he just spoke; that is evidence he exists

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
            # RECORDED, like every other transmission. This one was not, and it
            # cost most of an evening: the pilot reported the controller
            # calling him by the wrong name, and the offending words were
            # nowhere in the flight recorder -- so the search went to the sim's
            # own ATC, to Polly's voices, to anything except the line we had
            # actually said. A transmission nobody can see is one nobody can
            # debug.
            record(session_id, kind="atc/simple", to=addressed_to(canned),
                   freq_mhz=(heard_hz or freq_hz) / 1_000_000, text=canned)
            print(f"  ATC[simple] (0.0s): {canned}", flush=True)
            with radio_lock:
                _pool.transmit(voice_for(heard_hz).frames(canned),
                                channels_of(heard_hz), AM)
            continue

        directive, stack, vectoring = decide(
            bridge, ctl, transcript, scope, known, _ident.track, engaged, profile)

        # The one aircraft state. Bind whatever names we have -- the radio GUID
        # always, the callsign once he says it, the track once radar ties them
        # together -- and remember the row so what is agreed can be written
        # against it. Identity arrives in pieces and this is where they are
        # joined.
        # The track name only goes in once radar has actually tied the callsign
        # to a blip -- binding a guess would attach one aeroplane's history to
        # another's, which is worse than being unidentified.
        #
        # AND `_fix` IS NOT RECOMPUTED HERE. It was, by callsign only, throwing
        # away the track-first value computed above and used for the record.
        # `radar_fix` needs a BRACKETED tag, which the picture carries only once
        # the agent has bound the callsign with `identify` -- so from check-in
        # until that lands, and again any time the label went stale, this was
        # None for a pilot radar could see perfectly. Everything downstream took
        # the loss: `asr.guide` got nothing, `reconcile` returned with both the
        # holding directive AND the talkdown still attached, and the pilot was
        # told in one transmission that he was on final and to climb and hold --
        # the exact contradiction reconcile exists to prevent. It also disabled
        # `hush_a_second_talkdown`, so the metronome called a callsign the agent
        # was not answering. Audit finding 1.3, 29 July.
        #
        # Nothing between here and that assignment touches `scope`, `known` or
        # `profile`, so reusing it is the same computation with the better
        # answer kept.
        _flight = flight_bind(
            srs_guid=client.last_sender_guid or None,
            srs_name=srs or None,
            callsign=known or None,
            # THE TRACK, not the callsign. This bound a flight's track_name to
            # its own CALLSIGN, so the airspace view's join to `tracks` never
            # matched, every aeroplane came back with no geography, and the
            # COALESCE fell through to "Center owns the rest" -- which is how a
            # pilot being vectored at eleven miles was offered to Georgia Center
            # eight times in one approach. He was never leaving anybody's
            # airspace; he had no airspace at all.
            track_name=(_ident.track or None) if _fix is not None else None,
        ) if (client.last_sender_guid or known) else {}
        _fid = _flight.get("id")

        directive, stack, vectoring, _g, dropped = settle(bridge,
            directive, stack, vectoring, _fix, profile, known, ctl)
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

        if engineering_turn(_pool, transcript, srs, known, heard_hz,
                            freq_hz, eng_voice, radio_lock, AM, session_id):
            continue
        # OUT OF THE BLUE, WITH NO CALLSIGN. We know who it is from his radio,
        # and a real controller does not -- so he asks, and does not act on a
        # report he cannot attribute. Inside a conversation he does not ask,
        # because by then he knows the voice.
        _guid = client.last_sender_guid or ""
        # A HANDLE IS A CALLSIGN. `extract` wants the numbered shape -- "Pony
        # 1-1" -- so "Batumi Approach, Sockeye, request creation of Apex
        # flight" read as a man who had not said who he was, and got challenged
        # for the name he had just given. Under the flight model that is
        # backwards: a person IS his handle, and only a flight has a name of
        # its own, so "Sockeye" is complete self-identification.
        #
        # Matched against the CLOSED SETS -- the flights that exist and the
        # handle this radio resolved to -- never against open English, which is
        # the rule the whole design rests on.
        _said_who = said_who(transcript, [*bridge.flights.names(), _who])
        _open = in_conversation(bridge, _guid)
        bridge.last_heard[_guid] = time.time()
        # AND NEVER SWALLOW A DECISION. If the flight logic just ruled on this
        # transmission, that ruling is the answer he is owed -- challenging him
        # instead throws away a join, a refusal or a dissolve that has already
        # taken effect, and leaves the roster and the pilot disagreeing.
        if not _said_who and not _open and known and not _flight_say:
            reply = challenge_for(transcript)
            with radio_lock:
                print(f"  ATC[who] {reply}   (out of the blue, no callsign)",
                      flush=True)
                record(session_id, kind="atc/challenge", callsign=known,
                       text=reply)
                _pool.transmit(voice_for(heard_hz).frames(reply),
                                channels_of(heard_hz), AM)
            continue

        # OUT OF THE BLUE, WITH NO CALLSIGN. We know who it is from his radio,
        # and a real controller does not -- so he asks, and does not act on a
        # report he cannot attribute. Inside a conversation he does not ask,
        # because by then he knows the voice.
        _guid = client.last_sender_guid or ""
        # A HANDLE IS A CALLSIGN. `extract` wants the numbered shape -- "Pony
        # 1-1" -- so "Batumi Approach, Sockeye, request creation of Apex
        # flight" read as a man who had not said who he was, and got challenged
        # for the name he had just given. Under the flight model that is
        # backwards: a person IS his handle, and only a flight has a name of
        # its own, so "Sockeye" is complete self-identification.
        #
        # Matched against the CLOSED SETS -- the flights that exist and the
        # handle this radio resolved to -- never against open English, which is
        # the rule the whole design rests on.
        _said_who = said_who(transcript, [*bridge.flights.names(), _who])
        _open = in_conversation(bridge, _guid)
        bridge.last_heard[_guid] = time.time()
        # AND NEVER SWALLOW A DECISION. If the flight logic just ruled on this
        # transmission, that ruling is the answer he is owed -- challenging him
        # instead throws away a join, a refusal or a dissolve that has already
        # taken effect, and leaves the roster and the pilot disagreeing.
        if not _said_who and not _open and known and not _flight_say:
            reply = challenge_for(transcript)
            with radio_lock:
                print(f"  ATC[who] {reply}   (out of the blue, no callsign)",
                      flush=True)
                record(session_id, kind="atc/challenge", callsign=known,
                       text=reply)
                _pool.transmit(voice_for(heard_hz).frames(reply),
                                channels_of(heard_hz), AM)
            continue

        # THERE IS NO SHIP-TO-SHIP GATE. A transmission addressed to another
        # aeroplane used to be heard, understood and answered with silence,
        # which is what a real controller does on a busy frequency -- and it
        # was the wrong model for this one. Ship-to-ship does not belong here:
        # real aircraft carry a second radio for it and this squadron uses
        # Discord. So anything arriving on this channel is addressed to
        # somebody on it, and the controller answers rather than guessing at
        # intent from the words. Guessing at intent from words is the same
        # mistake as guessing at identity from words, which cost two days.
        #
        # `addressed_to_another_aircraft` has no caller now. It is left in
        # place with its tests until [LAYERS.md] step 2, when the gates become
        # one stage and it can go with a clear conscience rather than in the
        # middle of a behaviour change.

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
        # By track, for the same reason everything else is: a stale label made
        # this None for a whole approach, which silently disabled the talkdown
        # guard below as well.
        fix = (radar_fix_by_track(scope, _ident.track, profile)
               or radar_fix(scope, known, profile))
        # NOBODY IS HANDED OFF FROM THE RAMP.
        #
        #     "Tower handed me to approach, approach handed me to tower"
        #
        # A handoff keys on RANGE, and to a rule that only knows the range an
        # aeroplane parked 0.4 nm from the field is indistinguishable from one
        # on short final -- so Approach dutifully gave a stationary jet to
        # Tower, and Tower's own answer sent him back. A pilot on the ramp
        # bounced between two frequencies with nowhere to go.
        #
        # The sim says who is down, it has said so all along (`on_ground`, from
        # the land/takeoff events rather than from a guess at altitude), and it
        # now reaches the bridge as a field on the contact. A man on the ground
        # is Tower's, and he is not going anywhere until he moves.
        # THROUGH `is_on_the_ground`, not off the raw field, and the difference
        # cost three attempts at this bug. `on_ground` comes from the sim's
        # land/takeoff EVENTS, so it is false for an aeroplane that SPAWNED on
        # the ramp -- it never landed, so nothing ever fired. A pilot cold-start
        # at Batumi read `on_ground=False` at 39 feet and zero knots, the ramp
        # guard never engaged, and Tower went on handing him to Approach.
        #
        # That function is the one place the two facts are combined -- the
        # event if there is one, the radar geometry if not -- and it exists
        # precisely so its callers cannot drift. Reading the field directly is
        # how a fourth caller drifts.
        # ONE FUNCTION, THREE KINDS OF EVIDENCE. See `next_controller`: the
        # sim's events, then the ladder, then the airspace volumes, each only
        # asked when the one above had nothing to say.
        #
        # This was fifty lines inline, which is why nothing else could ask the
        # question the same way -- the monitor asked only the ladder and the
        # live check only the volumes, and between them they reported healthy
        # while Center could not hand anybody over at all. [#51]
        _down = is_on_the_ground(scope, _ident.track, fix)
        # WHAT HE IS DOING comes off the board. It is the only evidence that
        # can hand over the ground half of a sortie -- a parked aeroplane has
        # no range and no direction to argue from.
        _ac = ctl.aircraft.get(ctl._resolve(known)) if known else None
        nxt = next_controller(scope, _ident.track, me, profile, fix,
                              known=known, session_id=session_id,
                              vectoring=vectoring,
                              phase=getattr(_ac, "sortie_phase", "") or "")
        # SETTLED. This is the handoff the bridge authorises for this turn, and
        # the transmit path refuses any other -- see `strip_unauthorised_handoff`.
        bridge.handoff_due[0] = nxt
        if directive:
            print(f"  CONTROLLER: {directive}", flush=True)
        if stack:
            print(f"  SEPARATION: {stack}", flush=True)
        message, message_parts = compose_message(
            bridge, scope, known, transcript, profile, me, fix, nxt,
            directive, stack, vectoring, _flight, _flight_say, claim,
            _name_say)
        # Republish with what he was handed, now that it exists. The board is
        # the same; the input is the part worth having.
        publish_state(bridge, ctl, scope, session_id, handed=message_parts,
                      plans=filed_plan_rows(),
                      names=getattr(client, 'roster', None))
        speak(bridge, interact, message, transcript, known, heard_hz, _fix, profile, ctl)


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
