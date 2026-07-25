# Marshall — start here

Procedural + agentic radio ATC, mission generation, and kneeboard charts for DCS
World. **Before touching anything, read `docs/DESIGN.md`, then `docs/GOTCHAS.md`,
then `docs/BACKLOG.md`.** They hold the architecture, the hard-won gotchas (trust
them), and the deferred work.

## The core idea
**Real ATC by default.** A capable, radar-equipped agent (Bedrock Sonnet) is the
controller's brain. "Handicaps" — no radar, no DME, blind procedural separation,
period phraseology — are a per-mission `AtcCapability` you dial in; the 1944
Batumi beacon letdown is one such flavour, not the baseline. `core/route.py` is
the single source of truth (fixes, wind, the `ApproachProfile` + its capability);
the mission builder, the chart, and the ATC all read it, so they can't disagree.

## Two brains (the invariant)
- The **agent** (the strands-pg director, its own repo/container) owns language,
  judgment, radar-grounded guidance, three-way identity correlation, and hooks.
- The deterministic **`atc/controller.py`** owns *separation* — the holding stack,
  one-in-the-letdown, sequencing — which must never be an LLM's guess when there
  is traffic. **An LLM never invents separation between aircraft.**

## Shape
- **`marshall/`** (this repo): `core/route.py` (truth), `atc/` (the SRS bridge
  `agent_atc.py`, the deterministic `controller.py`, `intents`/`bedrock_intent`,
  `briefing.py` which generates the plate), `srs/` (two-way SRS voice client, STT,
  TTS, plus the synthetic-pilot + multi-ship rehearsal test harness), `mission/`
  (pydcs `.miz` builder + `ai_control.lua`), `kneeboard/` (charts).
- **`marshall-director/`** (separate repo/container): the Bedrock agent on
  strands-pg (Postgres + PostGIS + pgvector). Holds the prompts (`soul`/`plate`/
  `rules`, `plate` generated from `route.py` and pushed by the bridge), the
  identity graph (`contacts`), the live PostGIS track cache (`tracks`), the
  `approaches` + `flight_plans` tables, and the DCS-gRPC tools. The bridge talks
  to it over HTTP (`/atc`, `/radar`, `/hooks/due`, `/prompts`, ...).

## How it runs
The **SRS bridge** (`python -m marshall.atc.agent_atc --srs <host> <freq> <voice>
<session>`) is the live ATC; it injects radar + any controller directive and POSTs
each call to the director's `/atc`. The **director** runs under `docker compose`
in `marshall-director/`. Model tier is all-Sonnet by default (thinking disabled
for speed); a Haiku fast tier is wired but dormant (`MARSHALL_FAST_TIER=1`).
Deterministic separation engages only with real traffic (or `MARSHALL_SEP_ALWAYS=1`
for the voice-only rehearsal).

Live ops specifics — hosts, credentials, the current running state — live in the
**private memory notes**, not here.

## The repo is PUBLIC
No personal paths, emails, IPs, or secrets in committed files. Keep ops specifics
in private memory.
