"""Where the sim and the radio server are is written down ONCE.

Two rules, and they are the same rule seen from two sides.

THE REPO IS PUBLIC. `CLAUDE.md` says no personal paths, emails, IPs or secrets
in committed files, and seven files carried a private LAN address as a default
anyway -- in `tools/`, where nobody looks for a leak.

AND A FACT WITH FOURTEEN IMPLEMENTATIONS HAS FOURTEEN ANSWERS. `DCS_GRPC_ADDR`
lives in `director/.env`, which compose reads for the container and no shell
reads for a tool run by hand. So every tool rolled its own
`os.environ.get("DCS_GRPC_ADDR", ...)`, most defaulted to localhost, three
hardcoded the LAN address, and `tools/sim.py` alone read the file -- privately,
behind a comment naming this exact failure.

The cost was not theoretical. The ladder rehearsal asked `sim.py` where the sim
was, got the truth, then asked `spawn.py` to park its fixture aeroplane there
and got `Connection refused` from localhost, two lines under a healthy status
report. Every row that needed an aeroplane reported SKIP -- honestly, and
uselessly.

`marshall/config.py` resolves both, once, and writes the answer back into the
environment so a subprocess cannot get a second opinion. This is what stops the
fourteen growing back one convenient default at a time.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# A PRIVATE address, which is the only kind that can leak from here: RFC1918.
# Loopback is publishable -- it reaches nobody's machine but your own, and is
# the only default that can honestly be written down in a public repo. A public
# address is not a leak either; it is somebody's deliberate choice.
#
# Narrow on purpose. A dotted-quad match alone flags `SRS_VERSION = "2.1.0.2"`,
# and a check with a false positive in it gets an exemption list and then gets
# ignored.
_IP = re.compile(r"\b(?:10(?:\.\d{1,3}){3}"
                 r"|192\.168(?:\.\d{1,3}){2}"
                 r"|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b")
# Docker's own bridge gateway. A fixed, universal constant of the runtime, the
# same on every machine -- naming it is documentation, not disclosure.
_NOT_PERSONAL = ("172.17.0.1",)

# The variables that name somebody's machine. A file may READ them -- that is
# what config.py does -- but only config.py may supply a default, because a
# default is an answer and there is only one.
_HOSTS = ("DCS_GRPC_ADDR", "SRS_HOST", "MARSHALL_PG_DSN")
_OWN_DEFAULT = re.compile(
    r"""environ(?:\.get\(|\[)\s*["'](""" + "|".join(_HOSTS)
    + r""")["']\s*,\s*["'][^"']+["']""")

_SEARCHED = ("src", "tools", "tests", "director", "deploy", "docs")
_SKIP_DIRS = {"__pycache__", ".git", "node_modules", "_grpc", "build"}
# The one file allowed to answer, and the example that exists to be copied.
_ALLOWED = {"src/marshall/config.py", "deploy/.env.example"}


def _files():
    for top in _SEARCHED:
        base = ROOT / top
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix not in (
                    ".py", ".sh", ".lua", ".yml", ".yaml", ".md", ".example"):
                continue
            if _SKIP_DIRS & set(p.parts):
                continue
            yield p


class NoPrivateAddressIsCommitted(unittest.TestCase):

    def test_no_file_carries_somebody_s_lan_address(self):
        """The repo is public. A LAN address in it is a leak and a stale fact.

        Loopback is fine -- it is the only default that reaches nobody.
        """
        found = []
        for p in _files():
            rel = p.relative_to(ROOT).as_posix()
            if rel in _ALLOWED:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for n, line in enumerate(text.splitlines(), 1):
                for m in _IP.finditer(line):
                    if m.group(0) in _NOT_PERSONAL:
                        continue
                    found.append(f"{rel}:{n}  {line.strip()[:90]}")
        self.assertEqual(found, [], "\n".join(
            ["a private address is committed to a PUBLIC repo -- "
             "put it in .env and read it through marshall.config:", *found]))


class OnlyConfigSuppliesTheDefault(unittest.TestCase):

    def test_nothing_else_invents_where_the_sim_is(self):
        """One door. `config.DCS_GRPC_ADDR` and `config.SRS_HOST`.

        Reading the variable is fine; supplying a fallback is not, because a
        fallback is an answer to "where is it" and there can only be one. This
        is exactly how fourteen callers came to disagree.
        """
        offenders = []
        for p in _files():
            rel = p.relative_to(ROOT).as_posix()
            if rel in _ALLOWED or p.suffix != ".py":
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            for n, line in enumerate(text.splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue          # a comment describing the bug is not it
                if _OWN_DEFAULT.search(line):
                    offenders.append(f"{rel}:{n}  {line.strip()[:90]}")
        self.assertEqual(offenders, [], "\n".join(
            ["these supply their own answer to where the sim or the radio "
             "server is; use marshall.config:", *offenders]))


if __name__ == "__main__":
    unittest.main()
