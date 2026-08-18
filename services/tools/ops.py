"""Operator tools — how the agent raises its hand.

`escalate` lets the agent flag something it can't confidently handle (an
ambiguous request, a suspected bug, something outside its remit) with a loud,
greppable marker in the logs. During development the builder watches for
`[ESCALATE]` (a Monitor on `docker compose logs`); in production this is where a
hand-off to a stronger model or a human notification would hook in.
"""

from __future__ import annotations

import logging

try:
    from strands import tool
except ImportError:
    def tool(fn):
        return fn

_log = logging.getLogger("marshall.escalate")


@tool
def escalate(summary: str, detail: str = "") -> str:
    """Escalate an issue you cannot confidently handle to the operator/builder:
    an ambiguous or out-of-scope request, a suspected bug, a tool that behaved
    unexpectedly, or anything you want a human to look at. Use sparingly.

    Args:
        summary: One line describing the issue.
        detail: Optional fuller context (what you tried, what you expected).
    """
    _log.warning("[ESCALATE] %s | %s", summary, detail or "(no detail)")
    return ("Escalated to the operator. If a pilot is waiting, acknowledge and "
            "say you're checking on it.")
