# Codex audit findings — 2026-08-10

## Scope and result

I reviewed the design, wiring, schema, test-plan and issue documents against
the current implementation, then ran the repository checks available without a
DCS/SRS/director deployment.

The deterministic core has a substantial and useful test suite: `pytest -q`
passed **1,340 tests** (with 6 skips and 1,002 subtests), and Ruff passed.
That is a real strength. The issues below are principally at the seams the
tests cannot currently exercise: identity/radar correlation, deployment, and
operational documentation.

## Findings

### High — An identified track is discarded for final-approach seeding

`separation_context()` correctly checks radar contact by immutable track name,
but immediately falls back to a callsign/tag lookup for aircraft type and the
critical `seen_on_final()` seed ([agent_atc.py:1769](/opt/marshall/src/marshall/atc/agent_atc.py:1769),
[agent_atc.py:1774](/opt/marshall/src/marshall/atc/agent_atc.py:1774),
[agent_atc.py:1782](/opt/marshall/src/marshall/atc/agent_atc.py:1782)).
`radar_fix()` needs a bracketed callsign tag; an untagged, but otherwise
identified, radar contact therefore reports `seen=True` and then has no `fix`.

Impact: an aircraft already established on final can be treated as a new
arrival and put into the holding logic—the precise condition the radar seed is
meant to prevent. Equipment detection can similarly fail until the agent has
written a tag back to the scope.

Recommendation: derive one `fix` from `radar_fix_by_track(scope, track,
profile)` when `track` exists, with the callsign lookup only as fallback; use
that same result for contact, equipment, `seen_on_final`, ground state, and the
later guidance path. Add a regression test with an untagged contact, a resolved
track, and an established-final position.

### High — The default director deployment exposes Postgres and agent APIs without transport or access controls

The director Compose file publishes `5432:5432` and `8000:8000` on all host
interfaces ([director/docker-compose.yml:21](/opt/marshall/director/docker-compose.yml:21),
[director/docker-compose.yml:80](/opt/marshall/director/docker-compose.yml:80)).
The database credentials are fixed in the file (`strands`/`strands`), and the
wiring document confirms that the HTTP surface has no authentication
([docs/WIRING.md:333](/opt/marshall/docs/WIRING.md:333)).

Impact: any host able to reach those ports can connect directly to the world
state database or invoke director endpoints. An external reverse proxy does not
protect ports published directly by Docker. This is especially risky because
the service owns prompts, sessions, flight state, and mutating endpoints.

Recommendation: bind both ports to loopback or a private Docker network by
default; use secrets/environment-provided credentials rather than committed
defaults; firewall the database; and require service authentication for the
director API. If LAN access is intentional, make the network boundary and its
firewall rule explicit and enforce it in deployment configuration.

### Medium — `tools/check.py` succeeds while important checks were never run

The check runner records skipped checks but returns failure only for explicit
failures ([tools/check.py:143](/opt/marshall/tools/check.py:143)). In this audit
it returned success for every runnable local check while skipping director,
DCS/SRS, handoff, contention, visual-approach, formation, and go-around
coverage. It also failed `issue_sync` solely because GitHub was unreachable,
making the standard local quality gate network-dependent.

Impact: a green check is not a release-quality signal; critical radio and
integration regressions can ship unnoticed, while offline development gets a
spurious failure.

Recommendation: provide explicit modes such as `--unit` (skips allowed) and
`--release` (required checks must run), make CI use `--release`, and separate
remote issue synchronization from code correctness or make it an opt-in check.

### Medium — The system-level voice/radio path remains difficult to safely change

`agent_atc.py` is 4,948 lines and contains the receive loop, identity policy,
HTTP orchestration, radio scheduling, and nested background-thread functions
in one module ([agent_atc.py:1](/opt/marshall/src/marshall/atc/agent_atc.py:1)).
The nested `_run_srs()` and `asr_monitor()` paths cannot be called directly by
unit tests, and the check runner labels their most consequential scenarios as
live-only.

Impact: local helper tests can be green while ordering, locking, dropped
messages, and data propagation fail in the actual radio loop. The repository's
own audit history documents this exact class of wiring regression.

Recommendation: continue extracting the loop into injected, testable
components (radio input, turn coordinator, agent client, scheduler, output),
then add deterministic integration tests with fake SRS, clock, director, and
radar clients. Keep the live rehearsal as an additional acceptance test rather
than the only coverage of orchestration.

### Medium — The design documents are internally contradictory and several describe superseded behavior

Examples verified against the tree:

- The README says the SRS bridge, Whisper STT, and TTS are “next”
  ([README.md:48](/opt/marshall/README.md:48)), while the implementation has a
  radio package and bridge, and DESIGN calls the voice stack built
  ([docs/DESIGN.md:198](/opt/marshall/docs/DESIGN.md:198)).
- DESIGN and the module docstring say the bridge calls `/chat`
  ([docs/DESIGN.md:35](/opt/marshall/docs/DESIGN.md:35),
  [agent_atc.py:10](/opt/marshall/src/marshall/atc/agent_atc.py:10)); the
  executable configuration calls `/atc` ([agent_atc.py:75](/opt/marshall/src/marshall/atc/agent_atc.py:75)).
- `docs/SCHEMA.md` announces an unapplied proposal and says it would delete
  in-memory agent state ([docs/SCHEMA.md:1](/opt/marshall/docs/SCHEMA.md:1),
  [docs/SCHEMA.md:244](/opt/marshall/docs/SCHEMA.md:244)); current code and
  migrations implement a different, live schema and retain `_atc_agents`.
- WIRING says prompt edits do not refresh `/atc` agents
  ([docs/WIRING.md:354](/opt/marshall/docs/WIRING.md:354)), but the endpoint
  now compares the assembled prompt and rebuilds the cached agent
  ([app.py:240](/opt/marshall/director/app.py:240)).

Impact: operators following the wrong document can debug the wrong endpoint,
expect unavailable behavior, or make an unsafe deployment decision.

Recommendation: mark proposals/historical investigations prominently and move
them to an archive; establish one short “current operational architecture”
document generated or checked against configuration; and add a lightweight docs
consistency check for endpoint names, package paths, and declared component
status.

## Verification performed

```text
UV_CACHE_DIR=/tmp/marshall-uv-cache uv run pytest -q
# 1340 passed, 6 skipped, 1002 subtests passed

UV_CACHE_DIR=/tmp/marshall-uv-cache uv run ruff check .
# All checks passed

UV_CACHE_DIR=/tmp/marshall-uv-cache uv run python tools/check.py
# Core checks passed; issue synchronization failed because GitHub was
# unreachable; several director/live checks were skipped as documented above.
```

No source files were modified by this audit; this report is the only added
file.
