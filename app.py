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
from strands.models.bedrock import BedrockModel

from strands_pg import (
    PgPromptStore,
    PgSessionManager,
    make_app,
    memory_tools,
)

# DCS-gRPC live-world tools (stubs vendored under _grpc, on PYTHONPATH).
from tools.dcs import get_current_mission, get_player_units, load_mission
from tools.ops import escalate

# TODO (identity): uncomment when you have per-user profile docs.
# from strands_pg import PgIdentity

PROMPT_DIR = Path(__file__).parent / "prompts"
SYSTEM_PROMPT_PARTS = ["soul", "rules"]
MODEL_ID = os.environ.get("STRANDS_PG_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")

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


def build_agent(session_id: str) -> Agent:
    return Agent(
        model=BedrockModel(model_id=MODEL_ID),
        system_prompt=_system_prompt_for(session_id),
        tools=[
            get_current_mission,      # what .miz is loaded
            load_mission,             # hot-load a mission, no restart
            get_player_units,         # god's-eye: who's flying and where
            *memory_tools(namespace=session_id),
        ],
        session_manager=PgSessionManager(session_id=session_id),
    )


app = make_app(build_agent, prompt_store=prompts)
