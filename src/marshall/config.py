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


def _path(env: str, default: Path) -> Path:
    return Path(os.environ[env]) if os.environ.get(env) else default


# Generated output (git-ignored). One tree so the server and the deploy step
# have a single place to look.
BUILD_DIR = _path("MARSHALL_BUILD", REPO_ROOT / "build")
KNEEBOARD_OUT = BUILD_DIR / "kneeboard"
SOUNDS_DIR = BUILD_DIR / "sounds"
MISSION_OUT = BUILD_DIR / "missions"

# Deployment targets. No default is a real path on anyone's machine -- set these
# in your environment. The placeholders only exist so an import never crashes;
# the mission tools check for existence before writing.
DCS_MISSIONS = _path("DCS_MISSIONS", BUILD_DIR / "missions")
DCS_INSTALL = _path("DCS_INSTALL", Path("/opt/dcs"))
DCS_LOGS = _path("DCS_LOGS", BUILD_DIR / "logs")

KNEEBOARD_PORT = int(os.environ.get("KNEEBOARD_PORT", "8362"))


def ensure_dirs() -> None:
    for d in (BUILD_DIR, KNEEBOARD_OUT, SOUNDS_DIR, MISSION_OUT):
        d.mkdir(parents=True, exist_ok=True)
