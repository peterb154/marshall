"""FastAPI server for the kneeboard pages -- and the seam the flight-planning
app grows onto later.

Layout of the site (room to grow):

    /               a small home page (placeholder; the flight planner lands here)
    /kneeboard/     the OpenKneeboard multi-page charts (point the Web Dashboard here)
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

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from marshall import config

ROOT: Path = config.KNEEBOARD_OUT

# Applied to every response. no-store is the one that actually matters to
# OpenKneeboard; the other two are for older caches on the path.
NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

app = FastAPI(title="Marshall", docs_url=None, redoc_url=None)


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
  a{color:#241f18;font-weight:bold}
</style>
<main>
  <h1>MARSHALL</h1>
  <p>Procedural radio ATC &middot; kneeboard charts</p>
  <p><a href="/kneeboard/">&rarr; kneeboard charts</a></p>
</main>
"""


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    return HTMLResponse(_HOME, headers=NO_CACHE)


@app.get("/kneeboard")
async def kneeboard_root() -> RedirectResponse:
    # Normalise the no-slash form so OpenKneeboard (and humans) land on index.html.
    return RedirectResponse(url="/kneeboard/", headers=NO_CACHE)


@app.get("/kneeboard/{path:path}")
async def chart(path: str = "") -> FileResponse:
    """Serve a generated chart from KNEEBOARD_OUT, no-cache, always 200.

    A bare `/kneeboard/` is the multi-page index.html OpenKneeboard points at.
    Path traversal out of the build tree is refused.
    """
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
