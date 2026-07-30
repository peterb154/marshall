"""FastAPI server for the kneeboard pages -- and the seam the flight-planning
app grows onto later.

Layout of the site (room to grow):

    /               a small home page (placeholder; the flight planner lands here)
    /kneeboard/     the OpenKneeboard multi-page charts (point the Web Dashboard here)
    /diag           live diagnostics -- what the two brains believe, now
    /control/       start, stop and restart the bridge; reload the mission
    /docs           WIRING.md and the audit, rendered to read at a desk
    /vendor/        third-party assets, so the LAN needs no internet
    /healthz        liveness

It serves the generated charts in KNEEBOARD_OUT for OpenKneeboard's Web
Dashboard. Two hard-won constraints from docs/GOTCHAS.md are baked in:

* **Refuses to be cached.** OpenKneeboard's embedded Chromium caches
  aggressively; without no-cache headers an edit appears to do nothing and you
  end up debugging a page you are no longer serving. Every response carries
  no-store, and charts are sent with FileResponse (always 200) rather than a
  StaticFiles mount, so a conditional request can never get a 304 back.

* **Concurrent by construction.** Chromium holds a keep-alive connection open;
  the old single-threaded stdlib server wedged on it and every later request
  hung, which OpenKneeboard reported as "No Pages" -- indistinguishable from a
  page-API failure. uvicorn's async loop has no such single-connection block.

Run it as a module (unchanged from before) or point uvicorn at the app object:

    uv run python -m marshall.kneeboard.serve [port]
    uvicorn marshall.kneeboard.serve:app --port 8362

When the flight-planning app is added it goes on THIS app -- a home page at /
and authed routes for the planner (it shells out to pydcs and deploys files, so
an open endpoint is remote code execution). The static charts under /kneeboard/
stay public; mutating routes get a dependency guard, or an access list on the
external Nginx Proxy Manager that fronts this host. See deploy/docker-compose.yml.
"""

import importlib
import os
import sys
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse)

from marshall import config

ROOT: Path = config.KNEEBOARD_OUT

# --- freshness -------------------------------------------------------------
#
# The pages are RENDERED PER REQUEST, not served from disk. The whole build is
# about five milliseconds, so there is no reason to keep a stale copy around and
# every reason not to: for months the charts were generated once at container
# start, and editing one changed nothing until somebody remembered to bounce the
# server. That produced a kneeboard still showing beacon frequencies for a field
# that had moved to a radar approach -- wrong in the one document a pilot trusts
# without checking.
#
# Mounting the source fixed half of it. The other half is that a running Python
# process holds the modules it imported at start, so a live mount changes
# nothing on its own. These reload the chart builders when their FILES change,
# rather than restarting the process -- OpenKneeboard's Chromium holds a
# keep-alive connection, and dropping it shows up as "No Pages", which is
# indistinguishable from the server being broken.
# WHAT hot-reloads: the chart builders and the data they read. NOT this module.
# Reloading the file that defines the FastAPI app re-runs the decorators against
# a fresh app object while uvicorn keeps serving the original, so the routes a
# request actually reaches are the ones registered at start -- a change here
# would appear to do nothing, which is precisely the class of confusion the
# reload exists to end. Editing serve.py still needs a restart, and that is
# fine: it changes about once a month, while the charts change hourly.
_WATCHED = ("marshall.kneeboard", "marshall.core.route")
_NEVER_RELOAD = ("marshall.kneeboard.serve",)
_stamps: dict[str, float] = {}
_reload_lock = threading.Lock()


def _source_files() -> list[Path]:
    out = []
    for name, mod in list(sys.modules.items()):
        if not any(name == w or name.startswith(w + ".") for w in _WATCHED):
            continue
        if name in _NEVER_RELOAD:
            continue
        f = getattr(mod, "__file__", None)
        if f:
            out.append(Path(f))
    return out


def _seed() -> None:
    """Import every chart module and stamp it, at server start.

    Ordering matters and cost an hour: `refresh` only reloads a file it has SEEN
    before, so a module first imported lazily inside a request handler is merely
    stamped on that request -- and the edit that prompted the request is missed.
    Importing them here means the first request already has a baseline for
    everything.
    """
    from marshall.kneeboard import diag, docs, flighttest, site   # noqa: F401
    refresh()


def refresh() -> int:
    """Reload any chart module whose file changed. Returns how many.

    Cheap: a stat per module, and nothing is reloaded when nothing moved.
    """
    changed = []
    with _reload_lock:
        for path in _source_files():
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            key = str(path)
            if _stamps.get(key) != mtime:
                if key in _stamps:          # not the first sighting
                    changed.append(path)
                _stamps[key] = mtime
        for path in changed:
            for name, mod in list(sys.modules.items()):
                if getattr(mod, "__file__", None) == str(path):
                    try:
                        importlib.reload(mod)
                    except Exception as e:   # a broken edit must not 500 the site
                        print(f"  !! reload {name} failed: {e}", flush=True)
    return len(changed)

# Applied to every response. no-store is the one that actually matters to
# OpenKneeboard; the other two are for older caches on the path.
NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

app = FastAPI(title="Marshall", docs_url=None, redoc_url=None)


@app.on_event("startup")
async def _on_start() -> None:
    _seed()


@app.get("/healthz")
async def healthz() -> dict:
    """Liveness for the container/compose. Cheap, no filesystem dependency."""
    return {"ok": True}


# A placeholder home page. The flight-planning UI replaces this body later; for
# now it just points at the charts so a bare visit is not a dead end.
_HOME = """<!doctype html><meta charset="utf-8"><title>Marshall</title>
<style>
  html,body{margin:0;height:100%;background:#d9cfb4;color:#241f18;
    font-family:"Courier New",monospace;display:grid;place-items:center}
  main{text-align:center;padding:2rem}
  h1{letter-spacing:.15em;margin:0 0 .3em}
  p{margin:.2em 0;opacity:.8}
  a{color:#241f18;font-weight:bold;display:block;margin:.45em 0}
  .why{font-size:.8em;font-weight:normal;opacity:.7;display:inline}
</style>
<main>
  <h1>MARSHALL</h1>
  <p>Procedural radio ATC &middot; kneeboard charts</p>
  <a href="/kneeboard/">&rarr; kneeboard charts</a>
  <a href="/flighttest/">&rarr; flight test card</a>
  <a href="/diag">&rarr; live diagnostics</a>
  <a href="/docs">&rarr; documents</a>
  <p class="why">charts, card and diagnostics are OpenKneeboard Web Dashboard
     pages &mdash; point a tab at each. The documents are for a desk.</p>
</main>
"""


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse(_HOME, headers=NO_CACHE)


@app.get("/kneeboard")
async def kneeboard_root() -> RedirectResponse:
    # Normalise the no-slash form so OpenKneeboard (and humans) land on index.html.
    return RedirectResponse(url="/kneeboard/", headers=NO_CACHE)


def _render(page_list=None) -> str:
    """One multi-page document, built fresh. See the note on freshness."""
    refresh()
    from marshall.kneeboard import site
    return site.build(page_list)


@app.get("/flighttest")
async def flighttest_root() -> RedirectResponse:
    return RedirectResponse(url="/flighttest/", headers=NO_CACHE)


@app.get("/flighttest/", response_class=HTMLResponse)
async def flighttest() -> HTMLResponse:
    """The test card and the issue numbers, as a second kneeboard.

    Point a second OpenKneeboard Web Dashboard tab here. It is built from
    docs/TEST_PLAN.md and docs/ISSUES.md on every request, so editing the card
    -- or filing an issue -- shows up on the next page turn.
    """
    refresh()
    from marshall.kneeboard import flighttest as ft
    from marshall.kneeboard import site
    return HTMLResponse(site.build(ft.pages()), headers=NO_CACHE)


# --- control -----------------------------------------------------------------
#
# MUTATING ROUTES, and the repo already has a rule about them: "the static
# charts under /kneeboard/ are safe to serve openly... an open mutating
# endpoint is remote code execution. Its write routes MUST be behind auth
# before marshall.epetersons.com is reachable from the internet"
# (deploy/docker-compose.yml). This is that.
#
# MARSHALL_CONTROL_TOKEN in .env. Unset means the routes REFUSE rather than run
# open -- a control surface that silently defaults to unguarded is how the rule
# gets forgotten. The token is checked on the mutating routes only; reading the
# bridge's state is as harmless as /diag.
CONTROL_TOKEN = os.environ.get("MARSHALL_CONTROL_TOKEN", "")


def _may_control(token: str) -> None:
    if not CONTROL_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="control is disabled: set MARSHALL_CONTROL_TOKEN in .env "
                   "and restart the kneeboard")
    if token != CONTROL_TOKEN:
        raise HTTPException(status_code=403, detail="bad control token")


@app.get("/control/bridge")
async def bridge_state():
    """What the supervisor last reported. Read-only, no token."""
    from marshall.kneeboard import control
    return JSONResponse(control.bridge_state(), headers=NO_CACHE)


@app.post("/control/bridge/{action}")
async def bridge_control(action: str, token: str = ""):
    """start / stop / restart the SRS bridge.

    Writes a word to a spool the host-side supervisor reads -- see
    `tools/bridge.py watch`. This process is in a CONTAINER and the bridge runs
    on the HOST, so it cannot start it however the button is wired; a container
    has no way into its host's namespace and handing it one (the docker socket)
    would give a web page root on that box.
    """
    _may_control(token)
    from marshall.kneeboard import control
    if action not in ("start", "stop", "restart"):
        raise HTTPException(status_code=400, detail=f"no such action {action!r}")
    return JSONResponse(control.ask_bridge(action), headers=NO_CACHE)


@app.post("/control/mission/restart")
async def mission_control(token: str = ""):
    """Reload the mission already loaded. It cannot load a different one --
    see the director endpoint for why that would strand connected clients."""
    _may_control(token)
    from marshall.kneeboard import control
    return JSONResponse(control.restart_mission(), headers=NO_CACHE)


@app.get("/diag", response_class=HTMLResponse)
async def diag_page() -> HTMLResponse:
    """Live diagnostics: what the two brains believe, right now.

    A kneeboard page rather than a document -- it is read in the cockpit while
    the aeroplane is flying, which is the whole point. Static HTML; the state
    arrives from /diag.json on a two-second poll, so nothing here holds a
    long-lived connection open (see the keep-alive note at the top of this
    module).
    """
    refresh()
    from marshall.kneeboard import diag
    return HTMLResponse(diag.page(), headers=NO_CACHE)


@app.get("/diag.json")
async def diag_json(session: str = ""):
    """The state the page draws. Read-only: the flight recorder and /radar.

    It cannot perturb what it measures -- no bridge call, no controller state
    touched. A diagnostic that can break a sortie is one nobody dares run
    during one.
    """
    refresh()
    from marshall.kneeboard import diag
    try:
        return JSONResponse(diag.state(session), headers=NO_CACHE)
    except Exception as e:                  # a broken read must not blank the page
        return JSONResponse({"error": str(e), "radios": [], "board": [],
                             "scope": [], "ghosts": [], "flights": [],
                             "last": {}}, headers=NO_CACHE)


@app.get("/docs", response_class=HTMLResponse)
async def docs_index() -> HTMLResponse:
    refresh()
    from marshall.kneeboard import docs
    return HTMLResponse(docs.index(), headers=NO_CACHE)


@app.get("/docs/{slug}", response_class=HTMLResponse)
async def docs_page(slug: str) -> HTMLResponse:
    """A long-form document from `docs/`, rendered fresh.

    Not a kneeboard page: these are read at a desk, away from the aeroplane.
    Rendered per request for the same reason the charts are -- editing
    `docs/WIRING.md` shows up on the next page turn rather than the next time
    somebody remembers to bounce the server.
    """
    refresh()
    from marshall.kneeboard import docs
    if slug not in docs.PAGES:
        raise HTTPException(status_code=404, detail=f"no document {slug!r}")
    try:
        return HTMLResponse(docs.render(slug), headers=NO_CACHE)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"missing: {e}") from e
    except ImportError as e:
        # The renderer needs marshall[server]. Say which, rather than 500.
        raise HTTPException(
            status_code=500,
            detail=f"{e}. Install with: uv pip install -e '.[server]'") from e


@app.get("/vendor/{name}")
async def vendor(name: str):
    """Third-party assets served from disk so the LAN needs no internet.

    OpenKneeboard's embedded Chromium cannot be assumed to reach a CDN, and a
    diagram that silently fails to draw looks exactly like a diagram nobody
    wrote. Fetched by `tools/vendor.sh`; the pages fall back to the CDN and say
    so when this is missing.
    """
    if "/" in name or ".." in name:
        raise HTTPException(status_code=404, detail="no")
    from marshall.kneeboard import docs
    path = docs.VENDOR / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{name} not vendored")
    # These are content-addressed by version and safe to cache, unlike the
    # charts -- but the shared NO_CACHE keeps one rule for the whole server.
    return FileResponse(path, headers=NO_CACHE)


@app.get("/kneeboard/{path:path}")
async def chart(path: str = ""):
    """Serve a generated chart from KNEEBOARD_OUT, no-cache, always 200.

    A bare `/kneeboard/` is the multi-page index.html OpenKneeboard points at.
    Path traversal out of the build tree is refused.
    """
    # The multi-page document itself is generated, never read from disk, so it
    # cannot go stale. Everything else under /kneeboard/ is a real file (the
    # scanned plates), and those are served as before.
    if path in ("", "index.html"):
        return HTMLResponse(_render(), headers=NO_CACHE)

    root = ROOT.resolve()
    target = (root / (path or "index.html")).resolve()

    # Refuse anything resolving outside the build tree (../ escapes, symlinks).
    if target != root and root not in target.parents:
        raise HTTPException(status_code=404)
    if target.is_dir():
        target = target / "index.html"
    if not target.is_file():
        raise HTTPException(status_code=404)

    # FileResponse always returns the body (never a 304), which is what the
    # no-cache contract needs; the headers ride along on top.
    return FileResponse(target, headers=NO_CACHE)


if __name__ == "__main__":
    import sys

    import uvicorn

    port = int(sys.argv[1]) if len(sys.argv) > 1 else config.KNEEBOARD_PORT
    config.ensure_dirs()
    print(f"serving {ROOT} on http://localhost:{port}/kneeboard/  (FastAPI, no-cache)")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
