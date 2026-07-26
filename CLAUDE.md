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
One repo, two deployables. They are a single system with a contract between them,
so a change that spans the seam (a new clearance the agent must voice, say) lands
as one commit.

- **`src/marshall/`** — `core/route.py` (truth), `atc/` (the SRS bridge
  `agent_atc.py`, the deterministic `controller.py`, `intents`/`bedrock_intent`,
  `briefing.py` which generates the plate), `srs/` (two-way SRS voice client, STT,
  TTS, plus the synthetic-pilot + multi-ship rehearsal test harness), `mission/`
  (pydcs `.miz` builder + `ai_control.lua`), `kneeboard/` (charts).
- **`director/`** (its own container stack) — the Bedrock agent on strands-pg
  (Postgres + PostGIS + pgvector). Holds the prompts (`soul`/`plate`/`rules`,
  `plate` generated from `route.py` and pushed by the bridge), the identity graph
  (`contacts`), the live PostGIS track cache (`tracks`), the `approaches` +
  `flight_plans` tables, and the DCS-gRPC tools. The bridge talks to it over HTTP
  (`/atc`, `/radar`, `/hooks/due`, `/prompts`, ...). Run it with
  `cd director && docker compose up -d`.

  Its compose project name is **pinned to `marshall-director`** — it predates the
  merge and its Postgres volume is `marshall-director_pgdata`. Don't let compose
  derive the project from the folder or it mounts an empty volume and the agent
  comes up with no contacts, sessions or approaches. It is also a stamp of
  `strands-pgsql-agent-framework`; `diff -r /tmp/fresh-stamp director/` still
  works for pulling upstream changes.

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

## Testing, cheapest first
1. **`uv run python -m unittest discover -s tests -t .`** — the separation
   engine and callsign parsing, pure stdlib, no LLM/network/sim. Milliseconds.
   This is what guards the invariant, so add to it when you touch `atc/`.
2. **`tools/classify_bench.py`** — scores the intent classifier against the
   phrasing pilots actually use, per model. Run it after touching the schema or
   the system prompt; the taxonomy wording moves the score more than the model
   does.
3. **`tools/atc_dryrun.py`** — the bridge without the radio. Same message
   assembly as the live loop, typed input, so the two-brain seam (does the agent
   VOICE the controller's altitudes or paraphrase them?) is testable in seconds.
4. **`srs/rehearsal.py` / `srs/pilot.py`** — synthetic pilots over real SRS with
   Polly and Whisper in the loop.
5. **A live mission** with AI flights, driven by `mission/ai_control.lua`.

## Every commit names an issue
Work is tracked in **`docs/ISSUES.md`** and mirrored to GitHub issues; the
flight test card (`docs/TEST_PLAN.md`) cites the same numbers. So a commit ends
with a trailer saying which one it belongs to:

    Refs #11            touches it
    Closes #11          finishes it — but a `needs-flight-test` issue is closed
                        by a PILOT flying the card, never by a green test suite

Closing also wants an **attestation**: who tested it, what was exercised, and the
commit it was tested at (`tools/attest.py`). An issue closed with "works now" is
one you cannot revisit.

Everything merges straight to `main`; there are no PRs. The issue reference IS
the correlation — GitHub threads the commit onto the issue, so "what changed for
this, and why" is one click rather than an archaeology exercise. A change worth
committing that fits no issue means the issue is missing: write it into
`docs/ISSUES.md` and `uv run python tools/file_issues.py`.

## The repo is PUBLIC
No personal paths, emails, IPs, or secrets in committed files. Keep ops specifics
in private memory.
