# Marshall — start here

Procedural + agentic radio ATC, mission generation, and kneeboard charts for DCS
World. **Before touching anything, read `docs/DESIGN.md`, then `docs/GOTCHAS.md`,
then `docs/BACKLOG.md`.** They hold the architecture, the hard-won gotchas (trust
them), and the deferred work.

`docs/WIRING.md` is the companion to those: DESIGN says what the system is FOR,
WIRING says what it actually DOES — what talks to what, in what order, and which
of the two brains produced a given transmission. Read it when a sortie did
something inexplicable; it is organised symptom-first at the end.

`docs/LAYERS.md` says what may depend on what, and is the one to read before
building something new. One rule — a module may depend only downward — plus the
stages of a turn, the brief mechanism that keeps procedure out of the system
prompt, and an honest list of where we break the rule today. Most of the recent
bug run was one shape: something reaching sideways for a fact it should have
been handed.

## The core idea
**Real ATC by default.** A capable, radar-equipped agent (Bedrock Sonnet) is the
controller's brain. "Handicaps" — no radar, no DME, blind procedural separation,
period phraseology — are a per-mission `AtcCapability` you dial in; the 1944
Batumi beacon letdown is one such flavour, not the baseline. `core/route.py` is
the single source of truth (fixes, wind, the `ApproachProfile` + its capability);
the mission builder, the chart, and the ATC all read it, so they can't disagree.

**Two aerodromes, and it changed what "truth" has to mean.** The sortie departs
**Kobuleti** and recovers into **Batumi** — an eight-rung comms ladder across
Clearance, Ground, Tower, Departure, Center, Approach, Tower, Ground. Adding the
second field broke four things that had been correct *by accident*, because a
question with one possible answer cannot be answered wrongly:

    station_for("tower")   one Tower existed, so first-match was right
    channels_for()         four presets, so `stations[:4]` lost nothing
    "ABCD"[i]              four buttons, so the string never ran out
    field_origin(profile)  one field, so the profile's beacon was his

None are findable by reading. **A role is only unique within an aerodrome** —
so anything resolving one takes a field, and the wrong answer is always
plausible: a real controller, a real frequency, a real distance, belonging to
the wrong airport. See `tests/test_two_fields.py`.

## Two brains (the invariant)
- The **agent** (the strands-pg director, its own repo/container) owns language,
  judgment, radar-grounded guidance, three-way identity correlation, and hooks.
- The deterministic **`atc/controller.py`** owns *separation* — the holding stack,
  one-in-the-letdown, sequencing — which must never be an LLM's guess when there
  is traffic. **An LLM never invents separation between aircraft.**

The aerodrome half of that invariant: **nobody issues a clearance that is not
his.** Ground clears you *to* the runway and says hold short; only Tower puts an
aeroplane on it. A controller who helpfully answers for the runway has issued a
clearance he does not own, which is how two aircraft end up on one strip.

**Who has him next is one function** — `agent_atc.next_controller` — over three
kinds of evidence in priority order: the sim's events, the `handoff.py` rule
table, then the PostGIS airspace volumes. It was three separate mechanisms until
1 August and they disagreed; a pilot found that at 44 nm by declaring an
emergency (#51). Ground transitions are not rows at all — a phase with no
geometry is owned outright by the controller `phases.py` names, so moving into
it IS the handoff.

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

## Regression: `tools/check.py`
`uv run python tools/check.py` runs everything that needs no sim — **ruff**, the
unit suite under **pytest**, and the approach sweep. A few seconds, no excuse for
skipping.

Both are dev dependencies (`uv pip install -e ".[dev]"`). The suite is
`unittest.TestCase` throughout and stays that way — pytest runs it unchanged and
the win is the failure OUTPUT, since most of these tests are about what a
controller said and `assertEqual` will not show you which two strings differed.
Ruff's config lists what is switched OFF and why: this codebase catches broadly
on purpose in the voice threads, and binds the gRPC stub path before importing
from it, and neither is a defect. `--live`
adds the voice rehearsals and the sim-backed checks, which need DCS, SRS and the
bridge and cost model calls, so they are run before a session rather than on
every edit.

**Skipped is reported, never silent**, and it names what is unguarded — a check
that quietly does not run reads exactly like one that passed.

The sweep exits non-zero on a REGRESSION against its recorded baseline, not on
the known-open bugs, because a check that is always red is a check nobody reads.
Beat the baseline and move it in the same commit.

**A tested thing is not deleted, it becomes the regression check.** Closed issues
drop off the cockpit list so they stop competing for a pilot's attention, but
their card row and their script stay — that is what tells us if a fix rots.

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
4. **`radio/rehearsal.py` / `radio/pilot.py`** — synthetic pilots over real SRS with
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
