"""Start, stop and restart the live SRS bridge -- without killing the caller.

Every restart tonight was done by hand, and two of them went wrong in the same
way: `pkill -f marshall.atc.agent_atc` matches the SHELL RUNNING THE PKILL,
because that string is in its command line too. The shell died mid-command, the
restart line after it never ran, and the pilot sat on a dead frequency waiting
for a controller that nobody had started. He noticed before I did, both times.

    uv run python tools/bridge.py status
    uv run python tools/bridge.py restart
    uv run python tools/bridge.py stop
    uv run python tools/bridge.py start

So: match on the PROCESS, not on a string that includes ourselves, and never
signal our own process group. It also carries the environment the bridge
actually needs -- `DCS_GRPC_ADDR`, which was defaulting to localhost while the
sim ran on another machine, so the fix table failed to push on every single
start and the controller had only the field to compute against.

`restart` waits for the old bridge to release the frequency lock before starting
the new one, because the new one refuses to start while the lock is held (which
is correct, and is exactly what makes an unchecked restart leave you with
nothing running).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = os.environ.get("MARSHALL_BRIDGE_LOG", "/tmp/marshall-bridge-live.log")
MODULE = "marshall.atc.agent_atc"

# The live configuration. Read from the director's .env so there is ONE place
# that says where the sim is -- the bridge defaulting to localhost while the
# director had the real address is how every start logged a fix-push failure.
DEFAULT_ARGS = ["--srs", os.environ.get("SRS_HOST", "192.168.0.35"),
                os.environ.get("MARSHALL_FREQ_MHZ", "124.0"),
                os.environ.get("MARSHALL_VOICE", "Matthew"),
                os.environ.get("MARSHALL_SESSION", "hooks")]


def _env() -> dict:
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(ROOT / "src"))
    if "DCS_GRPC_ADDR" not in env:
        for line in (ROOT / "director" / ".env").read_text().splitlines():
            if line.startswith("DCS_GRPC_ADDR="):
                env["DCS_GRPC_ADDR"] = line.split("=", 1)[1].strip()
    return env


def running() -> list[int]:
    """PIDs of live bridges, never including ourselves or our own group."""
    out = subprocess.run(["ps", "-eo", "pid,pgid,args"], capture_output=True,
                         text=True).stdout.splitlines()
    me, my_group = os.getpid(), os.getpgrp()
    pids = []
    for line in out[1:]:
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid, pgid, args = int(parts[0]), int(parts[1]), parts[2]
        if MODULE not in args or "tools/bridge.py" in args:
            continue
        if pid == me or pgid == my_group:
            continue          # never signal the shell that asked for this
        pids.append(pid)
    return pids


def stop(timeout: float = 15.0) -> None:
    pids = running()
    if not pids:
        print("no bridge running")
        return
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    print(f"stopping {', '.join(str(p) for p in pids)}")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not running():
            print("stopped")
            return
        time.sleep(0.5)
    for pid in running():
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    print("stopped (had to force it)")


def start() -> int:
    if running():
        print(f"already running: {running()}")
        return 1
    with open(LOG, "wb") as log:
        p = subprocess.Popen(
            [sys.executable, "-u", "-m", MODULE, *DEFAULT_ARGS],
            cwd=ROOT, env=_env(), stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True)
    print(f"starting pid {p.pid}, log {LOG}")

    # Wait for it to say it is on the air. A start that returns before the
    # frequency is claimed reads as success and is not one.
    deadline = time.time() + 60
    while time.time() < deadline:
        time.sleep(1.0)
        try:
            text = Path(LOG).read_text(errors="replace")
        except OSError:
            continue
        if "monitoring" in text:
            for line in text.splitlines():
                if line.strip().startswith(("agent ATC live", "monitoring")):
                    print("  " + line.strip())
            return 0
        if "already holds the frequency" in text:
            print("  !! refused: another bridge holds the frequency")
            return 1
        if p.poll() is not None:
            print(f"  !! exited early ({p.returncode}); see {LOG}")
            return 1
    print("  !! did not come up within 60s")
    return 1


def status() -> int:
    pids = running()
    print(f"bridge: {'running ' + str(pids) if pids else 'NOT RUNNING'}")
    return 0 if pids else 1


def main() -> int:
    what = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    if what == "status":
        return status()
    if what == "stop":
        stop()
        return 0
    if what == "start":
        return start()
    if what == "restart":
        stop()
        return start()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
