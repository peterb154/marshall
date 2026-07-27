"""Is an engineer at the bench? Turn it on, off, or ask.

The engineering channel answers differently depending on whether a human is
actually there:

    at the bench   "Engineering is up, go ahead."
    not            "Engineering is not at the bench right now. Keep talking,
                    every word is recorded and he will read it."

Which makes test A2 -- *the* test, because silence was the original bug --
impossible to fly while an engineer is holding the bench occupied. So the state
is a switch rather than a side effect:

    uv run python tools/bench.py            # ask
    uv run python tools/bench.py on         # an engineer is here, and stays here
    uv run python tools/bench.py off        # step away, so A2 can be flown

`on` runs a keep-alive: the claim goes stale after forty-five minutes, because a
stale claim is worse than an honest "he is not here" -- it promises a pilot
somebody is reading when nobody is. `off` stops it and clears the claim, so the
next call gets the not-at-the-bench answer within a second.

Nothing here touches the bridge. The claim is one file, checked per call.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from marshall import config

CLAIM = config.BUILD_DIR / "engineering.attended"
PID = config.BUILD_DIR / "engineering.keepalive.pid"
STALE_SEC = 45 * 60          # must match agent_atc.ENG_ATTENDED_SEC
TOUCH_SEC = 300


def _stop_keepalive() -> None:
    try:
        pid = int(PID.read_text().strip())
    except (OSError, ValueError):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    PID.unlink(missing_ok=True)


def status() -> str:
    if not CLAIM.exists():
        return "OFF — nobody at the bench; a pilot gets the recorded-not-read answer"
    age = time.time() - CLAIM.stat().st_mtime
    if age >= STALE_SEC:
        return (f"STALE — claimed {age / 60:.0f} min ago, past the {STALE_SEC // 60} "
                f"minute limit, so it counts as OFF")
    keep = "with keep-alive" if PID.exists() else "no keep-alive, will go stale"
    return f"ON — claimed {age / 60:.0f} min ago ({keep})"


def main() -> int:
    what = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    config.ensure_dirs()

    if what in ("on", "up", "here"):
        _stop_keepalive()
        CLAIM.touch()
        # Detached, so closing the shell does not silently vacate the bench.
        p = subprocess.Popen(
            [sys.executable, "-c",
             f"import time,pathlib\n"
             f"c=pathlib.Path({str(CLAIM)!r})\n"
             f"while True:\n    c.touch()\n    time.sleep({TOUCH_SEC})\n"],
            start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        PID.write_text(str(p.pid))
        print(f"bench ON (keep-alive pid {p.pid})")
    elif what in ("off", "away", "down"):
        _stop_keepalive()
        CLAIM.unlink(missing_ok=True)
        print("bench OFF — test A2 is now flyable; a call gets "
              "\"not at the bench, keep talking, every word is recorded\"")
    elif what in ("status", "?"):
        pass
    else:
        print(__doc__)
        return 2

    print(f"  {status()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
