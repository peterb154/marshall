"""Your agent. Edit freely — you own this file.

The `build_agent(session_id)` callable is the single extension point; everything
else (prompts, identity, domain tools) plugs into the Agent you construct here.
Copy the commented-out blocks out of TODO as you grow.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

# Logging: so every iteration's transcript -- prompts, tool calls with args and
# results, and the model's replies -- is visible in `docker compose logs agent`.
# STRANDS_DEBUG=1 turns on full tool-arg/result tracing. The durable transcript
# also lives in Postgres (the session store), queryable per session_id.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
logging.getLogger("strands").setLevel(
    logging.DEBUG if os.environ.get("STRANDS_DEBUG") else logging.INFO)
log = logging.getLogger(__name__)

from strands import Agent
from strands.models.bedrock import BedrockModel

from strands_pg import (
    PgPromptStore,
    PgSessionManager,
    make_app,
    memory_tools,
)

# The sim feed (marshall.feed) and the agent's own tools (director/tools).
import marshall.atc.agent as marshall_atc_agent
from marshall.feed.dcs import (
    spawn_ground,
    radar_picture,
)
from tools.capability import capabilities, describe
from tools.approaches import (
    active_flight_plan,
    get_approach,
    list_approaches,
    list_flight_plans,
    upsert_approach,
    upsert_flight_plan,
)
from tools.clearance import clearance_tools
from tools.context import RadioContext, scrub
from tools.frequencies import frequency_tools
from tools.hooks import due_hooks, hook_tools
from tools.identify import bindings_for, identify_tools
from marshall.feed.events import start_events
from marshall.feed.tracks import start_streamer, vector
from datetime import UTC

# TODO (identity): uncomment when you have per-user profile docs.
# from strands_pg import PgIdentity

# THE PROMPTS BELONG TO THE DOMAIN, not to the deployable that serves them.
# How a controller SAYS an ILS clearance is part of knowing what an ILS is, so
# the words live beside the logic in `marshall.atc.agent` -- see
# docs/STRUCTURE.md. This file keeps the HTTP door and the session locking,
# which is a deployable's job and nobody else's.
PROMPT_DIR = Path(marshall_atc_agent.__file__).parent / "prompts"
# soul (persona) -> plate (this mission's facts, generated from route.py and
# pushed live by the SRS bridge) -> rules (field-agnostic behaviour).
SYSTEM_PROMPT_PARTS = ["soul", "plate", "rules"]
MODEL_ID = os.environ.get("STRANDS_PG_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
# Two-tier: a fast/cheap model for the routine 90% of calls, the smart model for
# the hard ones. The bridge routes; the /atc endpoint swaps the agent's model per
# call. Our own router -> full control, current models.
FAST_MODEL_ID = os.environ.get("STRANDS_PG_FAST_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

prompts = PgPromptStore()
prompts.seed_from_dir(PROMPT_DIR)

# TODO (identity):
# identities = PgIdentity()
# identities.seed_from_dir(Path(__file__).parent / "identities")


def _system_prompt_for(session_id: str) -> str:
    base = prompts.assemble(SYSTEM_PROMPT_PARTS) or "You are a helpful assistant."
    # TODO (identity):
    # identity = identities.get_by_email(session_id)
    # if identity:
    #     base = f"{base}\n\n## USER CONTEXT\n{identity.body}"
    return base


def _bedrock(model_id: str) -> BedrockModel:
    # Extended thinking roughly doubles ATC latency (and doubles again on a tool-call
    # round-trip) for little gain -- the controller's smarts come from the injected
    # radar/plate/directive, not chain-of-thought. Turn it off for snappy radio.
    return BedrockModel(model_id=model_id,
                        additional_request_fields={"thinking": {"type": "disabled"}})


def store_id(session_id: str, role: str = "", station: str = "") -> str:
    """The key this controller's CONVERSATION is stored under.

    ONE AGENT PER SEAT MEANS ONE SESSION PER SEAT, and missing that cost a
    landing clearance. #81 keyed the agent cache on the seat -- correctly, since
    one bridge works every frequency under one session id -- but left every one
    of those agents constructing `PgSessionManager(session_id="hooks")`. Seven
    agents, seven independent message counters, one table:

        psycopg.errors.UniqueViolation: duplicate key value violates unique
        constraint "session_messages_pkey"
        DETAIL: Key (session_id, agent_id, message_id)=(hooks, default, 38)
                already exists.

    The endpoint returned 500, the bridge logged an agent error, and "cleared to
    land runway one three" was never transmitted. A pilot on short final heard
    nothing.

    Separating them is also the more honest model. Kobuleti Ground and Batumi
    Approach are different people; a pilot's conversation with one is not the
    other's to remember. `context.py` already says the window belongs to a
    CHANNEL rather than to a pilot -- this makes that true, where before every
    seat in the theatre shared one transcript.
    """
    # THE STATION, NOT THE ROLE, and getting that wrong is what put the crash
    # back. Keyed on the role, "Kobuleti Ground" and "Batumi Ground" are both
    # `ground` -- two different controllers at two aerodromes writing one
    # conversation, computing the same next message_id, and one losing:
    #
    #     UniqueViolation: Key (session_id, agent_id, message_id)
    #                      =(hooks:ground, default, 28) already exists
    #
    # Which is the same fault as the original, one layer in: a role is only
    # unique WITHIN an aerodrome. It is the lesson this project has learned more
    # times than any other, and I still keyed on the role.
    #
    # Falls back to the role, then to the bare session, so an older bridge that
    # sends neither behaves as it always did.
    key = (station or role or "").strip().lower().replace(" ", "-")
    return f"{session_id}:{key}" if key else session_id


def build_agent(session_id: str, role: str = "", also=(),
                station: str = "") -> Agent:
    """One controller's agent. `role` decides which tools he is GIVEN.

    THE SEAT IS THE KEY, not a paragraph of prose. `spawn_ground` used to be in
    every controller's hands with the Overlord brief telling an approach
    controller not to use it -- which costs tokens on every call and relies on
    the model obeying rather than on the capability being absent. See
    `tools/capability.py`; what is absent cannot be called.

    Empty `role` keeps the full set, so an older bridge or a direct call behaves
    exactly as before.
    """
    may = capabilities(role, also)
    store = store_id(session_id, role, station)
    log.info("agent for %s [%s]", store, describe(role, also))
    return Agent(
        model=_bedrock(MODEL_ID),
        system_prompt=_system_prompt_for(session_id),
        # The APPROACH CONTROLLER's tools only. Radar is injected into every call
        # (no tool round-trip), so it's not here. The mission/ops tools
        # (load_mission, call_in_traffic, get_player_units, get_current_mission,
        # unpause_sim) belong to a separate mission-director agent, not the
        # controller — keeping them off this agent trims the prompt and keeps
        # latency down.
        #
        # That list is the WHOLE of the deliberately-unregistered set, named so
        # it stays a decision rather than a drift. A controller has no business
        # unpausing the sim; whoever sets a sortie up does.
        tools=[
            *(identify_tools(session_id) if "identify" in may else []),
            *([vector] if "vector" in may else []),
            *(hook_tools(session_id) if "hooks" in may else []),
            # Clearance delivery. The words come back finished because the
            # numbers in a clearance — route, altitude, frequency, squawk — are
            # facts about what was filed, and a controller who improvises them
            # has cleared somebody to an altitude nobody wrote down.
            *(clearance_tools() if "clearance" in may else []),
            # ANY FREQUENCY ON THE MAP, on demand. His OWN field's are in the
            # brief -- a controller works one aerodrome and knows it cold -- and
            # everywhere else is unbounded: thirty fields at four to eight seats
            # each would be two hundred lines carried on every transmission to
            # answer a question a pilot asks twice a night.
            #
            # It also removes a real failure rather than saving tokens. Asked
            # for a frequency it had not been given, the controller invented one,
            # confidently and in correct phraseology, and a pilot sent to an
            # invented frequency calls into silence.
            *(frequency_tools() if "frequency" in may else []),
            *(memory_tools(namespace=store) if "memory" in may else []),
            # THE OVERLORD'S HANDS, AND ONLY HIS. This was given to every seat,
            # with the overlord brief left to say who might use it -- an
            # approach controller carrying, on every single transmission, the
            # ability to put armour in a valley and a paragraph asking it not
            # to. Prose is not a permission system; absence is.
            #
            # Sentry still needs it. Without it, asking for a target produced a
            # confident, detailed answer and nothing on the ground -- the worst
            # kind of wrong, because a pilot flies out and looks for it.
            *([spawn_ground] if "spawn" in may else []),
        ],
        # PER SEAT. See `store_id` -- sharing one session across seven agents
        # collided on the message primary key and cost a landing clearance.
        session_manager=PgSessionManager(session_id=store),
        # WHAT HE IS HANDED versus WHAT HE REMEMBERS -- see tools/context.py.
        # The live state (radar, stack, strip, plate) is re-derived and injected
        # on every call, so keeping the old copies bought nothing and cost 2,448
        # characters a turn in stale radar pictures the model could not tell
        # from the current one. History keeps the words; the window is sized
        # against the conversation it has to survive, not picked. Postgres still
        # persists the full transcript -- only what is SENT is trimmed.
        conversation_manager=RadioContext(),
    )


app = make_app(build_agent, prompt_store=prompts)

# Mirror the sim's unit stream into the PostGIS `tracks` cache so radar reads a
# single local query instead of fanning out gRPC on every call.
start_streamer()
# The sim's own account of what happened, beside its account of where
# everything is. See tools/events.py and [ARCH-3] / #41.
start_events()


# --- two-tier routed ATC turn -----------------------------------------------
# One agent + one Postgres session per channel; the bridge picks the tier and we
# swap the model for this call, so Haiku (routine) and Sonnet (hard) share one
# consistent conversation.
_FAST = _bedrock(FAST_MODEL_ID)
_SMART = _bedrock(MODEL_ID)
# Keyed on (session_id, role, also) -- see `atc_endpoint`. One bridge works
# every frequency under one session, so the seat is part of the key.
_atc_agents: dict[tuple, Agent] = {}

# One agent per session, and an agent cannot take two calls at once. The bridge
# gives up on a slow answer and moves on; the agent does not, so the NEXT
# transmission arrives while it is still thinking and strands raises
# ConcurrencyException -- which surfaced as an HTTP 500. One slow call then
# poisoned every transmission after it, and the pilot got silence with no way to
# tell why. Seen in a dry run: one 30-second answer, then three 500s in a row.
_atc_busy: dict[str, threading.Lock] = {}


def forget_sessions() -> int:
    """Drop every live controller. Called when the world restarts.

        "so should the controller memory be wiped. It doesn't need to remember
         conversation from last mission. It's a different universe"

    AND CLEARING THE TABLES IS NOT ENOUGH ON ITS OWN, which is the whole reason
    this exists. `session_messages` is where a conversation is PERSISTED, but
    these Agent objects hold it in process memory as well -- so a controller
    whose rows had been deleted would go on referring to an approach flown in a
    world that no longer exists, and the wipe would look like it had worked.

    The same shape as the ground-state dict and the in-memory board: a copy
    outliving the thing it copied. Third one this week.

    Dropping the object is the whole of it. The next transmission on that
    session builds a fresh agent, which is exactly what a new universe wants.
    """
    n = len(_atc_agents)
    _atc_agents.clear()
    # The locks go too: a lock guards an agent that no longer exists, and
    # keeping them would leak one entry per session for the life of the process.
    _atc_busy.clear()
    return n


@app.post("/atc")
def atc_endpoint(body: dict) -> dict:
    session_id, message = body["session_id"], body["message"]
    tier = body.get("tier", "sonnet")
    # WHICH SEAT IS SPEAKING, from the TRUSTED side. The bridge resolves the
    # station from the frequency before the call is made; nothing the pilot says
    # can change it. It decides which tools this agent is given -- see
    # `tools/capability.py`.
    role = (body.get("role") or "").strip().lower()
    also = tuple(body.get("also") or ())
    # WHICH SEAT, by name. Two aerodromes have a Ground and a Tower each; the
    # role alone cannot tell them apart, and their conversations are not one.
    station = (body.get("station") or "").strip()
    lock = _atc_busy.setdefault(session_id, threading.Lock())
    # Non-blocking on purpose. QUEUEING would be worse on a radio than dropping:
    # the caller has already given up and moved on, so a queued answer arrives
    # after the next exchange has started and the controller replies to a
    # transmission two ago. Better to say nothing and let him ask again.
    if not lock.acquire(blocking=False):
        log.warning("session %s is still answering the previous call; "
                    "dropping this one rather than queueing it", session_id)
        return {"session_id": session_id, "response": "", "busy": True,
                "tier": tier}
    try:
        # KEYED ON THE SEAT AS WELL AS THE SESSION. One bridge monitors every
        # frequency in the theatre under ONE session id, so the role varies
        # within a session -- caching on the session alone would hand Batumi
        # Approach whatever tool set Sentry was built with, which is exactly the
        # leak this is closing. The session is still the session, so the
        # conversation on a shared channel is unchanged.
        _key = (session_id, station, role, also)
        agent = _atc_agents.get(_key)
        # THE PLATE CAN CHANGE UNDER A CACHED AGENT. The bridge pushes a fresh
        # plate to /prompts at startup, built from route.py for the mission it
        # is about to fly -- but the Agent's system prompt was assembled when it
        # was constructed, and this cache is keyed on the session, which is the
        # frequency. So restarting the BRIDGE without restarting the DIRECTOR
        # left the controller flying the previous mission's plate: right field,
        # wrong altitudes, and no symptom anywhere except a pilot being given
        # numbers his chart does not show. Audit finding 6.1, 29 July.
        #
        # Comparing the assembled prompt is one Postgres read on a path that
        # already does several, and it is the only check that cannot be wrong --
        # a version counter would need every writer to remember to bump it.
        if agent is not None and agent.system_prompt != _system_prompt_for(session_id):
            log.info("prompt changed under session %s; rebuilding the agent",
                     session_id)
            agent = None
        if agent is None:
            agent = build_agent(session_id, role, also, station)
            # A restart restores the transcript from Postgres exactly as it was
            # written, situation blocks and all. `apply_management` would clean
            # it up -- but only AFTER the first call had already paid for it, so
            # the one turn following a director restart would be the most
            # expensive of the sortie. Scrub on the way in instead.
            scrub(agent.messages)
            _atc_agents[_key] = agent
        agent.model = _FAST if tier == "haiku" else _SMART
        result = agent(message)
        return {"session_id": session_id, "response": str(result), "tier": tier}
    finally:
        lock.release()


# The voice bridge reads this before every /chat and prepends it, so the
# controller always has a fresh scope with no tool round-trip in the hot path.
@app.get("/radar")
def radar_endpoint(session_id: str = "") -> dict:
    """The picture, and the facts it was drawn from.

    ADDITIVE ON PURPOSE ([#47]). `picture` is byte-identical prose and stays the
    agent's input; `contacts` is the same tracks as data, with ABSOLUTE
    positions and no opinion about who is asking. Consumers migrate one at a
    time, and the geometry stops being a parser.

    `bullseye` travels with it because a shared reference is useless if each
    consumer has to go and find it separately -- that is how Batumi's ARP ended
    up as a module constant in the first place.
    """
    from marshall.feed.dcs import contacts_live
    from marshall.feed.tracks import bullseyes, contacts
    binds = bindings_for(session_id) if session_id else None
    # THE CACHE FIRST, THE LIVE SCAN BEHIND IT -- the same order `radar_picture`
    # uses, so the prose and the data can never come from different sources and
    # disagree. `contacts` returns None (not []) when the cache cannot be read,
    # which is what distinguishes "cold cache" from "empty sky".
    got = contacts(binds)
    if got is None:
        try:
            got = contacts_live(binds)
        except Exception:
            got = []
    return {"picture": radar_picture(binds),
            "contacts": got,
            "bullseye": bullseyes()}


# The bridge scheduler polls this; each returned hook is due and has been
# removed (one-shot). The bridge then re-invokes the agent with the hook's `why`.
@app.post("/mission/restart")
def mission_restart() -> dict:
    """Reload the mission that is ALREADY loaded. Nothing else.

    Deliberately cannot load a different one. `LoadMission` swaps the sim and
    leaves ASYNCNET -- the multiplayer layer -- serving whatever the server
    booted with, so a client who connects afterwards is offered a mission that
    is not running and hangs on the loading screen with no error anywhere. That
    cost two sorties; see docs/GOTCHAS.md. Reloading the SAME file is safe
    precisely because the file on offer does not change.

    To change the mission for a human, write it into serverSettings.lua's
    missionList and restart the server -- `tools/deploy_mission.sh`.
    """
    # THE PATH, NOT THE PROSE. `get_current_mission` returns a sentence for a
    # human -- "Current mission: X  (file: Y.miz)" -- and `load_mission` wants
    # the full server-side path. Passing the sentence returns success and
    # reloads nothing, which is the worst possible outcome for a button whose
    # entire job is to have visibly done something.
    from marshall.feed.dcs import _channel, load_mission

    from dcs.hook.v0 import hook_pb2, hook_pb2_grpc
    try:
        with _channel() as ch:
            hook = hook_pb2_grpc.HookServiceStub(ch)
            path = hook.GetMissionFilename(
                hook_pb2.GetMissionFilenameRequest(), timeout=10).name
    except Exception as e:
        return {"ok": False, "error": f"cannot ask the sim what is loaded: {e}"}
    if not path:
        return {"ok": False, "error": "the sim reports no mission loaded"}
    try:
        load_mission(path)
    except Exception as e:
        return {"ok": False, "error": str(e), "mission": path}
    return {"ok": True, "mission": path.replace(chr(92), "/").split("/")[-1],
            "path": path}


@app.get("/events/departed")
def events_departed(since_sec: float = 900.0) -> dict:
    """Units a player has left recently.

    The bridge holds the separation board in its own process, so the sim's
    `player_leave_unit` cannot reach it without being asked for. It already
    polls /hooks/due every couple of seconds; this rides the same tick.
    """
    from marshall.feed.events import departed_since
    return {"departed": departed_since(since_sec)}


@app.get("/hooks/due")
def hooks_due_endpoint(session_id: str) -> dict[str, list]:
    return {"due": due_hooks(session_id)}


# Approaches (static) + flight plans (dynamic). The bridge seeds an approach from
# route.py and the active flight plan drives the ATC plate.
@app.get("/approaches")
def approaches_endpoint() -> dict:
    return {"approaches": list_approaches()}


@app.get("/approaches/{name}")
def approach_endpoint(name: str) -> dict:
    return get_approach(name) or {}


@app.put("/approaches/{name}")
def put_approach_endpoint(name: str, body: dict) -> dict:
    upsert_approach(name, body.get("field", ""), body["data"])
    return {"ok": True, "name": name}


@app.get("/flightplans")
def flightplans_endpoint() -> dict:
    return {"flight_plans": list_flight_plans()}


@app.put("/flightplans/{name}")
def put_flightplan_endpoint(name: str, body: dict) -> dict:
    upsert_flight_plan(name, body.get("callsign", ""), body["approach"],
                       body.get("weather", ""), bool(body.get("active", False)))
    return {"ok": True, "name": name}


# The one aircraft state. Who he is, what he wants, what he is doing -- and
# deliberately never where he is, which is what `tracks` is for. See
# tools/flights.py and migrations/004_flights.sql.
@app.get("/flights")
def flights_endpoint(mission: str = "default",
                     controller: str = "") -> dict:
    from tools import flights as F
    return {"flights": F.working(mission, controller or None)}


@app.post("/flights/bind")
def flights_bind_endpoint(body: dict) -> dict:
    """Attach a name to an aeroplane. Safe to call with partial information and
    safe to repeat -- which is how identity actually arrives."""
    from tools import flights as F
    mission = body.pop("mission", "default")
    return F.bind(mission, **body)


@app.post("/flights/{flight_id}/agree")
def flights_agree_endpoint(flight_id: int, body: dict) -> dict:
    """Record something that was AGREED. The only way state changes."""
    from tools import flights as F
    return F.agree(flight_id, **body) or {}


@app.post("/flights/{flight_id}/handoff")
def flights_handoff_endpoint(flight_id: int, body: dict) -> dict:
    from tools import flights as F
    return F.hand_off(flight_id, body["to"]) or {}


@app.get("/flights/due-handoff")
def flights_due_handoff_endpoint(mission: str = "default") -> dict:
    """Inside one controller's airspace, on another's frequency."""
    from tools import flights as F
    return {"due": F.due_handoff(mission)}


@app.delete("/flights/{flight_id}")
def flight_forget_endpoint(flight_id: int) -> dict:
    """He is out of the aeroplane. One row, gone.

    `player_leave_unit` frees the in-memory board through `Controller.release`,
    and until now nothing freed the ROW -- so a callsign and a track name stayed
    claimed for ever by somebody who had gone home. See docs/STATE.md.
    """
    from tools import flights as F
    return {"deleted": F.forget(flight_id)}


@app.post("/flights/expire")
def flights_expire_endpoint(mission: str = "default",
                            older_than_sec: float = 900.0) -> dict:
    """Reconcile the board against the world, the way `tracks` already does.

    A flight nobody has heard from and radar cannot see is not on the aerodrome.
    This is the belt to `player_leave_unit`'s braces: a client that vanishes
    without an event -- a crash, an alt-F4, a dropped connection -- leaves no
    event to act on and would otherwise sit on the board indefinitely.

    Deliberately generous. Fifteen minutes of total silence, not two: a pilot
    holding at a quiet moment of a long sortie is still flying, and taking him
    off the board mid-hold would be a far worse failure than leaving a stale row
    for a quarter of an hour.
    """
    from tools import flights as F
    return {"expired": F.expire(mission, older_than_sec)}


@app.delete("/flights")
def flights_clear_endpoint(mission: str = "default") -> dict:
    """Forget the last sortie. Stale aircraft are worse than none."""
    from tools import flights as F
    return {"deleted": F.clear_mission(mission)}


@app.get("/flightplan/active")
def active_flightplan_endpoint() -> dict:
    return active_flight_plan() or {}


# --- filed plans, and giving one to a flight --------------------------------
# `flight_plans` is what was FILED; `assigned_plans` is what an aeroplane was
# GIVEN. Assignment copies, so amending one flight's routing never edits the plan
# somebody else is flying. See migrations/009 and tools/clearance.py.
@app.get("/plans")
def plans_endpoint() -> dict:
    """Everything on file. Unfiltered: any pilot may request any plan."""
    from tools.clearance import filed
    return {"plans": filed()}


# --- filing a plan, which until #22 meant writing a migration ----------------
# The validation is the substance and it lives in `tools/filing.py`, server-side,
# because the kneeboard form is one caller and curl is another. A check that
# lives in the page is a check the next caller does not run.
@app.post("/plans")
def file_plan_endpoint(body: dict) -> dict:
    """File a plan, or refuse it and say which part cannot be flown."""
    from tools.filing import file_plan
    return file_plan(body, updating=body.get("updating", ""))


@app.post("/plans/check")
def check_plan_endpoint(body: dict) -> dict:
    """What would be refused, without filing anything. Lets a form say so while
    somebody is still typing rather than after they have pressed the button."""
    from tools.filing import check_live
    bad, warn = check_live(body, updating=body.get("updating", ""))
    return {"refused": bad, "warnings": warn}


@app.delete("/plans/{name}")
def unfile_plan_endpoint(name: str) -> dict:
    from tools.filing import unfile
    return unfile(name)


@app.get("/plans/fixes")
def plan_fixes_endpoint() -> dict:
    """Every place a route may name. The form offers these and nothing else, so
    a typo is a thing you cannot make rather than a thing you are told about."""
    from tools.filing import known_fixes
    return {"fixes": sorted(known_fixes())}


@app.get("/plans/approaches")
def plan_approaches_endpoint() -> dict:
    """The procedures a filed plan may name on arrival."""
    from tools.filing import known_approaches
    return {"approaches": sorted(known_approaches())}


@app.get("/plans/resolve")
def resolve_plan_endpoint(said: str, callsign: str = "") -> dict:
    """Which plan he means, without assigning it. The dry run for the radio, and
    what the sweep script scores against."""
    from tools.clearance import resolve
    return resolve(said, callsign or None)


@app.post("/flights/{flight_id}/assign-plan")
def assign_plan_endpoint(flight_id: int, body: dict) -> dict:
    """Copy a filed plan onto this flight, by name or by what he said."""
    from tools.clearance import assign, filed, resolve
    plan = None
    if body.get("plan"):
        plan = next((p for p in filed() if p["name"] == body["plan"]), None)
        if plan is None:
            return {"error": f"no plan on file called {body['plan']}"}
    else:
        hit = resolve(body.get("said", ""), body.get("callsign"))
        if not hit.get("plan"):
            return hit
        plan = hit["plan"]
    return assign(flight_id, plan, mission=body.get("mission", "default"),
                  route=body.get("route"))


@app.post("/flights/{flight_id}/clearance-ack")
def clearance_ack_endpoint(flight_id: int) -> dict:
    """He read it back. Cleared and agreed are not the same thing."""
    from tools.clearance import ack
    return ack(flight_id)


# Named fixes, pushed from route.py at bridge startup. The bridge owns WHERE a
# fix is and the sim owns the projection; this end just stores the answer so
# `vector` can compute a real bearing and range to a steerpoint instead of the
# controller estimating one out loud.
@app.put("/fixes")
def set_fixes_endpoint(body: dict) -> dict:
    from marshall.feed.tracks import set_fixes
    return {"fixes": set_fixes(body.get("fixes") or {})}


# WHAT IS ON THE AIR, per aerodrome. The `atis` table has been the shared source
# of the runway in use since controllers stopped recomputing it from the wind --
# and nothing outside the bridge process could read it back, so "is anybody
# broadcasting, and on what letter" was unanswerable to the diagnostics page and
# to the rehearsal harness. A row asking whether Delivery confirmed the letter
# cannot tell "he forgot" from "there is nothing to confirm" without this.
@app.get("/atis")
def atis_endpoint() -> dict:
    """Read off the TABLE, not off a theatre.

    The first version walked `theatre.current().fields`, and this container has
    no `MARSHALL_THEATRE` -- so on a Nevada sortie it confidently reported
    Batumi and Kobuleti. The bridge knows which map is loaded and the director
    does not, which is the whole shape of the NTTR audit and not a thing to
    paper over with a second copy of the flag.

    The table needs no such help: a row exists only because something recorded a
    broadcast, so the rows ARE what is on the air. A field with no row has no
    ATIS, which is exactly what the schema says.
    """
    from datetime import datetime

    from marshall.core import db
    from marshall.core.schema import Atis
    out = []
    try:
        with db.session() as s:
            for row in s.query(Atis).order_by(Atis.field).all():
                age = None
                if row.recorded_at is not None:
                    at = row.recorded_at
                    if at.tzinfo is None:
                        at = at.replace(tzinfo=UTC)
                    age = (datetime.now(UTC) - at).total_seconds()
                out.append({"field": row.field, "letter": row.letter or "",
                            "runway": row.runway,
                            "on_the_air": bool(row.letter),
                            "age_sec": age})
    except Exception as e:
        return {"atis": [], "error": f"{type(e).__name__}: {e}"}
    return {"atis": out}


@app.get("/fixes")
def get_fixes_endpoint() -> dict:
    from marshall.feed.tracks import known_fixes
    return {"fixes": known_fixes()}


# Which sector actually contains him, versus which controller is working him.
# The disagreement IS the handoff trigger -- see migrations/005 and 008. Whether
# to act on it is the controller's judgement, which is why this reports and does
# not decide.
@app.get("/flights/airspace")
def flight_airspace_endpoint(callsign: str, mission: str = "default") -> dict:
    from marshall.core.db import pool as get_pool
    with get_pool().connection() as c:
        r = c.execute(
            "SELECT working_with, should_be_with, alt_ft FROM flight_airspace "
            "WHERE mission = %s AND callsign = %s LIMIT 1",
            (mission, callsign)).fetchone()
    if not r:
        return {}
    return {"working_with": r[0], "should_be_with": r[1], "alt_ft": r[2]}
