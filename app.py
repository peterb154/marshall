"""Your agent. Edit freely — you own this file.

The `build_agent(session_id)` callable is the single extension point; everything
else (prompts, identity, domain tools) plugs into the Agent you construct here.
Copy the commented-out blocks out of TODO as you grow.
"""

from __future__ import annotations

import logging
import os
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
    call_in_traffic,
    get_current_mission,
    get_player_units,
    load_mission,
    radar,
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
from tools.hooks import due_hooks, hook_tools
from tools.identify import bindings_for, identify_tools
from tools.ops import escalate
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
            *memory_tools(namespace=session_id),
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


# --- two-tier routed ATC turn -----------------------------------------------
# One agent + one Postgres session per channel; the bridge picks the tier and we
# swap the model for this call, so Haiku (routine) and Sonnet (hard) share one
# consistent conversation.
_FAST = _bedrock(FAST_MODEL_ID)
_SMART = _bedrock(MODEL_ID)
_atc_agents: dict[str, Agent] = {}


@app.post("/atc")
def atc_endpoint(body: dict) -> dict:
    session_id, message = body["session_id"], body["message"]
    tier = body.get("tier", "sonnet")
    agent = _atc_agents.get(session_id)
    if agent is None:
        agent = build_agent(session_id)
        _atc_agents[session_id] = agent
    agent.model = _FAST if tier == "haiku" else _SMART
    result = agent(message)
    return {"session_id": session_id, "response": str(result), "tier": tier}


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


@app.get("/flightplan/active")
def active_flightplan_endpoint() -> dict:
    return active_flight_plan() or {}
