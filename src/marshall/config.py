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


def _load_dotenv(path: Path) -> None:
    """Read KEY=VALUE lines from .env into the environment, without a dependency.

    The real environment always wins -- a .env is a default for the box, not an
    override of what you just exported on the command line. Silently does nothing
    if the file is absent, which is the normal case in a container where the
    values are injected directly.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
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


def ensure_dirs() -> None:
    for d in (BUILD_DIR, KNEEBOARD_OUT, SOUNDS_DIR, MISSION_OUT, TTS_CACHE):
        d.mkdir(parents=True, exist_ok=True)
