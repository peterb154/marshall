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
    uv run python tools/bridge.py watch     # run it, and obey the dashboard

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


def config_build() -> Path:
    """build/, the same directory config.BUILD_DIR resolves to."""
    return Path(os.environ.get("MARSHALL_BUILD", str(ROOT / "build")))
LOG = os.environ.get("MARSHALL_BRIDGE_LOG", "/tmp/marshall-bridge-live.log")
MODULE = "marshall.atc.agent_atc"

# The live configuration. Read from the director's .env so there is ONE place
# that says where the sim is -- the bridge defaulting to localhost while the
# director had the real address is how every start logged a fix-push failure.
DEFAULT_ARGS = ["--srs", os.environ.get("SRS_HOST", "192.168.0.35"),
                os.environ.get("MARSHALL_FREQ_MHZ", "124.0"),
                os.environ.get("MARSHALL_VOICE", "Matthew"),
                os.environ.get("MARSHALL_SESSION", "hooks"),
                # WHICH MAP. The profile the bridge runs carries the station
                # list, so this decides which frequencies the ear opens and who
                # answers on them -- see core/theatre.py. Started with, never
                # inherited: `tools/bridge.py restart --theatre nevada`.
                "--theatre", os.environ.get("MARSHALL_THEATRE", "caucasus")]


def _env() -> dict:
    """The environment the bridge runs with, assembled from the ONE place the
    live configuration lives -- the director's compose file and its `.env`.

    THE BRIDGE IS A HOST PROCESS AND THE DATABASE IS IN COMPOSE. Everything the
    bridge shares with the director -- the ATIS letter, the runway in use, the
    fix table -- goes through Postgres, and it had no way to reach it: the
    container gets `STRANDS_PG_DSN` on the compose network, and nothing ever set
    the host equivalent. So `atis.serve` published nothing, every recording
    logged "PUBLISH FAILED", and the runway a controller names fell back to a
    computation instead of the broadcast -- which is the exact disagreement
    `atis/store.py` exists to prevent.

    It was loud, to its credit. It said so on every rotation for two days.
    """
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", str(ROOT / "src"))
    if "DCS_GRPC_ADDR" not in env:
        for line in (ROOT / "director" / ".env").read_text().splitlines():
            if line.startswith("DCS_GRPC_ADDR="):
                env["DCS_GRPC_ADDR"] = line.split("=", 1)[1].strip()
    # READ OFF THE COMPOSE FILE, not written out here. The credentials and the
    # published port are declared there; copying them into a second file is how
    # they come to disagree, and this repo is public so they may not be pasted
    # into it at all.
    if "MARSHALL_PG_DSN" not in env:
        got = _compose_dsn()
        if got:
            env["MARSHALL_PG_DSN"] = got
    return env


def _compose_dsn() -> str:
    """`postgresql://user:pass@localhost:PORT/db` from director/docker-compose.yml."""
    try:
        text = (ROOT / "director" / "docker-compose.yml").read_text()
    except OSError:
        return ""
    import re
    who = dict(re.findall(r"POSTGRES_(USER|PASSWORD|DB):\s*(\S+)", text))
    port = re.search(r'"(\d+):5432"', text)
    if not (who.get("USER") and who.get("DB") and port):
        return ""
    return (f"postgresql://{who['USER']}:{who.get('PASSWORD', '')}"
            f"@localhost:{port.group(1)}/{who['DB']}")


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



# --- the supervisor -------------------------------------------------------
#
# A COMMAND SPOOL, not an HTTP endpoint, and the reason is the deployment. The
# kneeboard runs in a CONTAINER and the bridge runs on the HOST, so the page
# cannot start a process however the button is wired -- a container has no way
# to spawn something in its host's namespace, and giving it one (the docker
# socket) would hand a web page root on this box.
#
# So the page writes a word to a file and this loop, which is on the host,
# reads it. The same shape as the engineering spool: reachable from anywhere in
# one line, no network surface at all, and the security boundary is a
# read-write mount rather than an open port.
#
#     uv run python tools/bridge.py watch
#
# That becomes how the bridge is run. It starts one and then stays up to accept
# start / stop / restart, so the dashboard button and the command line reach
# exactly the same code.
CONTROL = config_build() / "control"
CMD = CONTROL / "bridge.cmd"
STATE = CONTROL / "bridge.state"


def _write_state(text: str) -> None:
    try:
        CONTROL.mkdir(parents=True, exist_ok=True)
        STATE.write_text(f"{int(time.time())} {text}\n")
    except OSError:
        pass


def watch() -> int:
    """Run the bridge, and obey start/stop/restart written to the spool."""
    CONTROL.mkdir(parents=True, exist_ok=True)
    CMD.write_text("")                    # never act on a command left over
    print(f"supervisor up; commands from {CMD}")
    if not running():
        start()
    _write_state("running" if running() else "stopped")
    while True:
        time.sleep(1.0)
        try:
            want = CMD.read_text().strip().lower()
        except OSError:
            continue
        if not want:
            _write_state("running" if running() else "stopped")
            continue
        try:
            CMD.write_text("")            # consume before acting, never repeat
        except OSError:
            pass
        print(f"  supervisor: {want}", flush=True)
        _write_state(f"{want}ing")
        if want == "stop":
            stop()
        elif want == "start":
            start()
        elif want == "restart":
            stop()
            start()
        else:
            print(f"  !! unknown command {want!r}", flush=True)
        _write_state("running" if running() else "stopped")


def main() -> int:
    what = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    # `bridge.py restart --theatre nevada`. Set before DEFAULT_ARGS is read at
    # start, so the flag and the environment cannot say different things.
    if "--theatre" in sys.argv:
        os.environ["MARSHALL_THEATRE"] = sys.argv[sys.argv.index("--theatre") + 1]
        DEFAULT_ARGS[-1] = os.environ["MARSHALL_THEATRE"]
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
    if what == "watch":
        return watch()
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
