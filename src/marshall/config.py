"""Runtime configuration -- every machine-specific path lives here, and every
one is an environment variable with a sane default. Nothing personal is baked
into the source, so the same tree runs on a developer's WSL box and on the LXC
beside the DCS server with only env changes.

    MARSHALL_BUILD     where generated charts, missions and audio are written
    DCS_MISSIONS       the sim's Missions folder, where a built .miz is deployed
    DCS_INSTALL        the sim install root, read only by the terrain survey
    KNEEBOARD_PORT     port the chart server listens on

Copy deploy/.env.example to .env and adjust for your machine.
"""

import os
from pathlib import Path

# Repo root: src/marshall/config.py -> up three.
REPO_ROOT = Path(__file__).resolve().parents[2]


def _lines(path: Path) -> list[str]:
    """The stripped lines of a KEY=VALUE file, or none if it is not there."""
    try:
        return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    except OSError:
        return []


def _load_dotenv(path: Path) -> None:
    """Read KEY=VALUE lines from .env into the environment, without a dependency.

    The real environment always wins -- a .env is a default for the box, not an
    override of what you just exported on the command line. Silently does nothing
    if the file is absent, which is the normal case in a container where the
    values are injected directly.
    """
    for line in _lines(path):
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


# deploy/.env.example tells you to copy it to .env at the repo root -- so
# actually read it. Without this, every documented setting only worked if you
# happened to export it by hand.
_load_dotenv(REPO_ROOT / ".env")


def _path(env: str, default: Path) -> Path:
    return Path(os.environ[env]) if os.environ.get(env) else default


# Generated output (git-ignored). One tree so the server and the deploy step
# have a single place to look.
BUILD_DIR = _path("MARSHALL_BUILD", REPO_ROOT / "build")
KNEEBOARD_OUT = BUILD_DIR / "kneeboard"
SOUNDS_DIR = BUILD_DIR / "sounds"
# Rendered speech, kept between runs. See `radio/tts.py`: the same words in
# the same voice are the same audio, and Polly is a network call.
TTS_CACHE = BUILD_DIR / "tts"

# How many SRS clients the bridge transmits with. One client plays one
# stream at a time, so this is how many controllers can speak at once --
# and it scales with concurrent SPEECH, not with airports. Ten is generous
# for one to ten pilots and survives fifty; raising it costs 4 ms and two
# file descriptors each, so if the pool ever warns about waiting, raise it
# and stop thinking about it.
RADIO_POOL_SIZE = int(os.environ.get("MARSHALL_RADIO_POOL", "10"))
MISSION_OUT = BUILD_DIR / "missions"

# Deployment targets. No default is a real path on anyone's machine -- set these
# in your environment. The placeholders only exist so an import never crashes;
# the mission tools check for existence before writing.
DCS_MISSIONS = _path("DCS_MISSIONS", BUILD_DIR / "missions")
DCS_INSTALL = _path("DCS_INSTALL", Path("/opt/dcs"))
DCS_LOGS = _path("DCS_LOGS", BUILD_DIR / "logs")

KNEEBOARD_PORT = int(os.environ.get("KNEEBOARD_PORT", "8362"))

# The SRS server the voice bridge talks to, and the External AWACS Mode password
# it registers with (external clients are not relayed without it). Both are
# per-deployment facts about someone's LAN, not code -- this repo is public, so
# they live in the environment and the defaults reach nobody's server but your own.
SRS_HOST = os.environ.get("SRS_HOST", "127.0.0.1")
SRS_EAM_PASSWORD = os.environ.get("SRS_EAM_PASSWORD", "")

# WHERE THE SIM IS. Same kind of fact as SRS_HOST, and it belongs here for the
# same reason -- except that it also lives in `services/.env`, which compose
# reads for the container and no shell reads for a tool run by hand.
#
# So fourteen files rolled their own `os.environ.get("DCS_GRPC_ADDR", ...)` and
# they did not agree: most defaulted to localhost, three hardcoded a LAN address
# into a PUBLIC repo, and `tools/sim.py` alone read `services/.env` -- in a
# private helper, behind a comment naming this exact failure. The ladder
# rehearsal asked `sim.py` where the sim was, got the truth, then asked
# `spawn.py` to park an aeroplane there and got `Connection refused` from
# localhost, two lines under a healthy status report.
#
# One door. `services/.env` is consulted because it is the file that already
# holds this, and the value is written back into the environment so a
# subprocess, a later import or a library gets the same answer.
def _grpc_addr() -> str:
    got = os.environ.get("DCS_GRPC_ADDR")
    if not got:
        for line in _lines(REPO_ROOT / "services" / ".env"):
            if line.startswith("DCS_GRPC_ADDR="):
                got = line.split("=", 1)[1].strip()
                break
    # A sim on this machine is the only default that can be written down in
    # public, and it is right for anybody running DCS beside the bridge.
    os.environ["DCS_GRPC_ADDR"] = got = got or "127.0.0.1:50051"
    return got


DCS_GRPC_ADDR = _grpc_addr()


def ensure_dirs() -> None:
    for d in (BUILD_DIR, KNEEBOARD_OUT, SOUNDS_DIR, MISSION_OUT, TTS_CACHE):
        d.mkdir(parents=True, exist_ok=True)
