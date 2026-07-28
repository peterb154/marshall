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
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.models.bedrock import BedrockModel

from strands_pg import (
    PgPromptStore,
    PgSessionManager,
    make_app,
    memory_tools,
)

# DCS-gRPC live-world tools (stubs vendored under _grpc, on PYTHONPATH).
from tools.dcs import (
    spawn_ground,
    radar_picture,
)
from tools.approaches import (
    active_flight_plan,
    get_approach,
    list_approaches,
    list_flight_plans,
    upsert_approach,
    upsert_flight_plan,
)
from tools.clearance import clearance_tools
from tools.hooks import due_hooks, hook_tools
from tools.identify import bindings_for, identify_tools
from tools.events import start_events
from tools.tracks import start_streamer, vector

# TODO (identity): uncomment when you have per-user profile docs.
# from strands_pg import PgIdentity

PROMPT_DIR = Path(__file__).parent / "prompts"
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


def build_agent(session_id: str) -> Agent:
    return Agent(
        model=_bedrock(MODEL_ID),
        system_prompt=_system_prompt_for(session_id),
        # The APPROACH CONTROLLER's tools only. Radar is injected into every call
        # (no tool round-trip), so it's not here. The mission/ops tools
        # (load_mission, call_in_traffic, get_player_units, get_current_mission)
        # belong to a separate mission-director agent, not the controller — keeping
        # them off this agent trims the prompt and keeps latency down.
        tools=[
            *identify_tools(session_id),  # correlate a voice callsign to a radar track
            vector,                       # heading + distance to a fix or another aircraft
            *hook_tools(session_id),      # "wake me in N seconds" — proactive callbacks
            # Clearance delivery. The words come back finished because the
            # numbers in a clearance — route, altitude, frequency, squawk — are
            # facts about what was filed, and a controller who improvises them
            # has cleared somebody to an altitude nobody wrote down.
            *clearance_tools(),
            *memory_tools(namespace=session_id),
            # The OVERLORD's hands. One agent covers every position and picks
            # its manner from which frequency was called, so the tool is here
            # for all of them and the overlord brief is what says who may use
            # it. An approach controller has no reason to put armour in a
            # valley and its own brief tells it so.
            #
            # Without this, asking Sentry for a target produced a confident,
            # detailed answer and nothing on the ground -- which is the worst
            # kind of wrong, because a pilot flies out and looks for it.
            spawn_ground,
        ],
        session_manager=PgSessionManager(session_id=session_id),
        # Bound the context the model sees so latency doesn't compound over a long
        # approach: the controller re-injects its live state (radar, stack, plate)
        # every call, so it doesn't need deep history. Postgres still persists the
        # full transcript; only what's sent to Sonnet is windowed.
        conversation_manager=SlidingWindowConversationManager(window_size=16),
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
_atc_agents: dict[str, Agent] = {}

# One agent per session, and an agent cannot take two calls at once. The bridge
# gives up on a slow answer and moves on; the agent does not, so the NEXT
# transmission arrives while it is still thinking and strands raises
# ConcurrencyException -- which surfaced as an HTTP 500. One slow call then
# poisoned every transmission after it, and the pilot got silence with no way to
# tell why. Seen in a dry run: one 30-second answer, then three 500s in a row.
_atc_busy: dict[str, threading.Lock] = {}


@app.post("/atc")
def atc_endpoint(body: dict) -> dict:
    session_id, message = body["session_id"], body["message"]
    tier = body.get("tier", "sonnet")
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
        agent = _atc_agents.get(session_id)
        if agent is None:
            agent = build_agent(session_id)
            _atc_agents[session_id] = agent
        agent.model = _FAST if tier == "haiku" else _SMART
        result = agent(message)
        return {"session_id": session_id, "response": str(result), "tier": tier}
    finally:
        lock.release()


# The voice bridge reads this before every /chat and prepends it, so the
# controller always has a fresh scope with no tool round-trip in the hot path.
@app.get("/radar")
def radar_endpoint(session_id: str = "") -> dict[str, str]:
    # Annotate tracks with this session's radar-identified callsigns.
    return {"picture": radar_picture(bindings_for(session_id) if session_id else None)}


# The bridge scheduler polls this; each returned hook is due and has been
# removed (one-shot). The bridge then re-invokes the agent with the hook's `why`.
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
    from tools.tracks import set_fixes
    return {"fixes": set_fixes(body.get("fixes") or {})}


@app.get("/fixes")
def get_fixes_endpoint() -> dict:
    from tools.tracks import known_fixes
    return {"fixes": known_fixes()}


# Which sector actually contains him, versus which controller is working him.
# The disagreement IS the handoff trigger -- see migrations/005 and 008. Whether
# to act on it is the controller's judgement, which is why this reports and does
# not decide.
@app.get("/flights/airspace")
def flight_airspace_endpoint(callsign: str, mission: str = "default") -> dict:
    from strands_pg._pool import get_pool
    with get_pool().connection() as c:
        r = c.execute(
            "SELECT working_with, should_be_with, alt_ft FROM flight_airspace "
            "WHERE mission = %s AND callsign = %s LIMIT 1",
            (mission, callsign)).fetchone()
    if not r:
        return {}
    return {"working_with": r[0], "should_be_with": r[1], "alt_ft": r[2]}
