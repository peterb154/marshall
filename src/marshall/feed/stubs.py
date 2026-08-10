"""Reach the DCS-gRPC stubs without losing a fight to `pydcs` over the name.

`dcs` IS AN AMBIGUOUS TOP-LEVEL PACKAGE and this module exists because of it.

  * `pydcs` -- the mission builder, a real dependency of `marshall.mission` --
    installs itself as `dcs`.
  * the vendored DCS-gRPC stubs are generated with absolute imports and also
    live under `dcs/`.

Which one `import dcs.common.v0` finds depends on `sys.path` order and on what
happens to be installed. Inside the director container pydcs is absent, so it
resolves to the stubs and everything works. On the host pydcs is present, so
the same line prints "Couldn't detect any installed DCS World version" a
hundred times and then raises `ModuleNotFoundError: No module named
'dcs.common'`.

That did not matter while this code lived in `director/` and nothing on the host
imported it. It matters now: `feed` is in the shared package, and a module that
cannot be imported outside one container is not shared.

THE COMMENT THAT USED TO EXPLAIN THIS WAS WRONG, which is worth recording. It
said these modules "bind the `dcs` namespace before importing anything from it,
so the imports genuinely cannot come first" -- true of `tools/spawn.py`, which
really does install a `ModuleType` first, and false of `feed/tracks.py`, where
the imports simply sat mid-file with nothing before them. A justification was
borrowed from a file where it applied to one where it did not, and an E402
ignore kept anybody from looking for eight months.

WHAT THIS DOES. Binds the vendored stub directory as `dcs` before importing
from it -- the thing the old comment claimed was already happening -- and does
it in ONE place instead of once per file, so `import marshall.feed.tracks` is
safe anywhere. Importing this shadows `pydcs` for the rest of the process, which
is correct for a process that talks to the sim over gRPC and wrong for one
building a `.miz`; those are different programs and neither needs both.

THE REAL FIX is to regenerate the stubs under a root of their own, so nothing
has to shadow anything. That is a protoc change and a vendoring change, and it
is not done. This is the honest interim: one place, explained, rather than a
lint suppression and a false comment.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

# Where the generated stubs are vendored: INSIDE the package, beside the code
# that uses them. They lived in `director/_grpc` because that is where the
# gRPC work started, which put a dependency of the shared `feed` module inside
# a deployable that `feed` no longer belongs to -- and made every consumer
# reach across a directory boundary to find it.
#
# Resolved from this file rather than assumed on PYTHONPATH, so it works the
# same whether or not anybody remembered to set one.
_ROOT = Path(__file__).resolve().parents[1] / "_grpc"


def bind() -> None:
    """Make `dcs.*` mean the gRPC stubs for the rest of this process.

    Idempotent, and a no-op when `dcs` already points at the stubs -- which is
    the container's case, where PYTHONPATH got there first.
    """
    got = sys.modules.get("dcs")
    if got is not None and getattr(got, "__path__", None) \
            and str(_ROOT) in str(next(iter(got.__path__), "")):
        return
    if not (_ROOT / "dcs").is_dir():
        # Nothing vendored: leave whatever `dcs` means alone and let the caller
        # fail on its own import, with its own error, rather than inventing a
        # package that is not there.
        return
    # EVICT THE SUBMODULES TOO, not just the parent. Rebinding `dcs` alone
    # leaves pydcs's ALREADY-IMPORTED children cached under their own keys --
    # `dcs.coalition`, `dcs.mission`, `dcs.terrain` -- and Python's import
    # machinery consults `sys.modules['dcs.coalition']` before it ever looks at
    # the new parent's `__path__`. So `import dcs.coalition.v0` finds pydcs's
    # coalition MODULE where a package is wanted and raises
    #
    #     ModuleNotFoundError: No module named 'dcs.coalition.v0';
    #     'dcs.coalition' is not a package
    #
    # which reads like the stubs are missing and is nothing of the kind.
    #
    # This never bit in production because the two are different programs: the
    # mission builder imports pydcs and never touches gRPC, the bridge is the
    # reverse. It bites in the TEST SUITE, where both run in one interpreter --
    # so the first test to cover `feed/dcs.py` at all is the one that found it.
    # Order-dependent, therefore: passing alone, failing in the full run.
    for name in [k for k in sys.modules
                 if k == "dcs" or k.startswith("dcs.")]:
        del sys.modules[name]
    pkg = types.ModuleType("dcs")
    pkg.__path__ = [str(_ROOT / "dcs")]
    sys.modules["dcs"] = pkg
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
