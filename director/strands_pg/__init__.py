"""Postgres-backed primitives for Strands agents."""

from strands_pg.agentmail import (
    FailureEvent,
    agentmail_operator_notify,
    walk_tool_trace,
)
from strands_pg.api import commit_sha, make_app
from strands_pg.identity import Identity, PgIdentity
from strands_pg.memory import PgMemoryStore
from strands_pg.memory_tools import memory_tools
from strands_pg.prompts import PgPromptStore, Prompt
from strands_pg.session import PgSessionManager, session_lock

__all__ = [
    "FailureEvent",
    "Identity",
    "PgIdentity",
    "PgMemoryStore",
    "PgPromptStore",
    "PgSessionManager",
    "Prompt",
    "agentmail_operator_notify",
    "commit_sha",
    "make_app",
    "memory_tools",
    "session_lock",
    "walk_tool_trace",
]
__version__ = "0.8.0"
