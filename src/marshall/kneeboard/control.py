"""Starting and stopping things, from a page in the cockpit.

    "give me the power to start / restart and stop the bridge and restart the
     mission"

TWO DIFFERENT PROBLEMS, and they get different answers because of where each
thing runs.

THE BRIDGE RUNS ON THE HOST and this code runs in a CONTAINER. No amount of
wiring lets a container spawn a process in its host's namespace, and the usual
workaround -- mounting the docker socket -- hands a web page root on that box.
So the page writes a word to a spool and `tools/bridge.py watch`, which IS on
the host, reads it and acts. The same shape as the engineering spool: no
network surface at all, and the security boundary is a read-write mount rather
than an open port.

THE MISSION IS THE DIRECTOR'S because the director already holds the DCS-gRPC
connection. It is a plain HTTP call to an endpoint that can only reload the
mission ALREADY loaded -- see `services/app.py:mission_restart` for why loading
a different one strands every connected client.

WHY A COMMAND CAN GO UNANSWERED, which is worth knowing before trusting a
button: if the supervisor is not running, the spool is written and nothing ever
reads it. `bridge_state` reports how old the supervisor's last heartbeat is
precisely so the page can say "nobody is listening" instead of showing a button
that appears to work.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from marshall import config

CONTROL = config.BUILD_DIR / "control"
CMD = CONTROL / "bridge.cmd"
STATE = CONTROL / "bridge.state"
DIRECTOR = os.environ.get("MARSHALL_DIRECTOR_URL", "http://localhost:8000")

# How stale the supervisor's heartbeat may be before the page should stop
# believing it. It writes every second; ten is generous and still obvious.
STALE_SEC = 10.0


def bridge_state() -> dict:
    """What the supervisor last said, and whether it is still saying it."""
    try:
        raw = STATE.read_text().strip()
    except OSError:
        return {"supervisor": "absent", "bridge": "unknown", "age": None,
                "why": "no state file -- run `tools/bridge.py watch` on the host"}
    try:
        stamp, _, what = raw.partition(" ")
        age = round(time.time() - float(stamp), 1)
    except ValueError:
        return {"supervisor": "absent", "bridge": "unknown", "age": None,
                "why": f"unreadable state {raw[:40]!r}"}
    if age > STALE_SEC:
        return {"supervisor": "stopped", "bridge": what.strip(), "age": age,
                "why": f"the supervisor last reported {age:.0f}s ago; a command "
                       f"now would be written and never read"}
    return {"supervisor": "up", "bridge": what.strip(), "age": age, "why": ""}


def ask_bridge(action: str) -> dict:
    """Put one word in the spool. The supervisor does the rest.

    Refuses when nobody is listening, rather than writing into the void and
    reporting success -- a control that lies about having acted is worse than
    one that is missing.
    """
    state = bridge_state()
    if state["supervisor"] != "up":
        return {"ok": False, "asked": action, **state,
                "error": "no supervisor is listening"}
    try:
        CONTROL.mkdir(parents=True, exist_ok=True)
        CMD.write_text(action + "\n")
    except OSError as e:
        return {"ok": False, "asked": action, "error": str(e)}
    return {"ok": True, "asked": action,
            "note": "the supervisor acts within a second; watch the state"}


def restart_mission() -> dict:
    """Reload whatever the sim currently has. Nothing else."""
    req = urllib.request.Request(f"{DIRECTOR}/mission/restart", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        return {"ok": False, "error": f"the director did not answer: {e}"}


def spool_path() -> Path:
    """For the page to name in an error, so a stuck command is findable."""
    return CMD
