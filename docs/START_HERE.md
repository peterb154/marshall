# Start here

    Type: CURRENT REFERENCE
    Validated against: 10 August 2026, live on the Nevada mission

Two pages. What runs today, who decides what, and which document to believe when
two of them disagree. Everything else is depth you can reach for later.

This exists because the documentation was deep and *unsafe to onboard from*: a
new reader could not tell today from history from a proposal, and the README —
the first thing anybody read — described the inverse of the architecture for
several weeks. Depth was never the problem. Knowing what is current was.

---

## What Marshall is, in one paragraph

A full radio ATC service for a flight sim. Human pilots talk to it over SRS and
it talks back in voice; it generates the mission they fly and the kneeboard
charts they read, all from one route definition, so the chart, the sim and the
controller cannot disagree. Today it works **Nellis → Tonopah** on Nevada and
**Kobuleti → Batumi** on the Caucasus, eight controller positions across two
aerodromes per theatre.

**Real ATC is the default.** A radar-equipped agent is the controller's brain.
Blind, non-radar, 1944-phraseology flying is a *handicap* you dial in per
mission (`AtcCapability`), not the baseline. If you read otherwise anywhere,
that document is out of date.

## The invariant, which nothing may break

> **An LLM never invents separation between aircraft.**

- The **agent** (Bedrock Sonnet, in `director/`) owns language, judgment,
  radar-grounded guidance, identity correlation and hooks.
- The deterministic **`atc/controller.py`** owns separation — the holding stack,
  one-in-the-letdown, sequencing.

Its aerodrome half: **nobody issues a clearance that is not his.** Ground clears
you *to* the runway; only Tower puts an aeroplane on it. And **a role is only
unique within an aerodrome** — anything resolving one takes a field, because the
wrong answer is always plausible: a real controller, a real frequency, belonging
to the wrong airport.

## What runs, and where

| | what | how it starts |
|---|---|---|
| **SRS bridge** | the live ATC. One ear on every frequency, ten mouths | `python -m marshall.atc.agent_atc --srs <host> <freq> <voice> <session> --theatre nevada` — normally via `tools/bridge.py watch` |
| **director** | the Bedrock agent + Postgres/PostGIS/pgvector. Prompts, identity, tracks, plans | `cd director && docker compose up -d` |
| **kneeboard** | charts + `/diag`, in a container. Generates pages **at start** | `docker restart marshall-kneeboard` after any `core/` change |
| **ATIS** | one client per broadcasting field; decides the runway in use | a thread inside the bridge |
| **DCS server** | the sim, on another box, gRPC on 50051 | `tools/deploy_mission.sh`, which restarts and unpauses it |

**Which map is a flag, not a guess.** The bridge and the kneeboard both take
`MARSHALL_THEATRE` / `--theatre`; the bridge then *confirms* it against the sim
by converting a known field. See `core/theatre.py`.

**A paused sim is the quietest failure here.** It boots paused and joining does
not unpause it; while paused every mission-Lua query hangs while the server
looks healthy. `uv run python tools/sim.py status`.

## Where state actually lives

| fact | owner | not |
|---|---|---|
| fields, fixes, frequencies, approaches, MVA/MSA | `src/marshall/core/` | anywhere else |
| which theatre | `MARSHALL_THEATRE`, via `core/theatre.py` | inferred from the mission |
| the runway in use | the `atis` table — controllers **read** it | each controller's own reading of the wind |
| separation, the stack, sequencing | `atc/controller.py`, in the bridge process | the agent |
| who has him next | `agent_atc.next_controller` — sim events, then `handoff.py`, then PostGIS volumes | any second mechanism |
| identity (radio ↔ track ↔ callsign) | the director's `contacts` | a Whisper transcript |
| prompts, sessions, plans, tracks | the director's Postgres | files |

## Testing, cheapest first

```sh
uv run python tools/check.py          # everything that needs no sim. Seconds.
uv run python tools/check.py --live   # adds the voice rehearsals and sim checks
```

`check.py` runs ruff, the unit suite, the unwired audit, the approach sweeps and
the issue/card sync. **Skipped is reported, never silent** — a check that quietly
does not run reads exactly like one that passed. The sweeps gate on a recorded
baseline, not on zero failures, because a check that is always red is a check
nobody reads.

Below that: `tools/atc_dryrun.py` (the bridge without the radio),
`tools/classify_bench.py` (the intent classifier), `radio/rehearsal.py`
(synthetic pilots over real SRS), then a live mission.

## Which document wins

When two sources disagree, believe them in this order:

1. **The code and the executable configuration.** `core/`, `docker-compose.yml`,
   the CLI flags. This always wins.
2. **The tests**, which are the code's own claims about itself.
3. **`docs/WIRING.md`** — what the system does, symptom-first. Deep and current,
   but archaeology accumulates; prefer 1 and 2 where they overlap.
4. **`docs/ISSUES.md`** for *intended remaining work* — read an issue's
   **Remaining scope** block, not its historical diagnosis.
5. **Historical debriefs and proposals** last. They are marked; see below.

## What each document is

| document | type | for |
|---|---|---|
| `START_HERE.md` | current reference | this. Orientation |
| `DESIGN.md` | current reference | what the system is *for* |
| `WIRING.md` | current reference | what it *does*; troubleshooting by symptom |
| `LAYERS.md` | current reference (+ future design, fenced) | what may depend on what |
| `GOTCHAS.md` | current reference | traps that cost real time |
| `ISSUES.md` | work record | the backlog, with acceptance criteria |
| `TEST_PLAN.md` | work record | the card a pilot flies |
| `PHRASEOLOGY.md` | current reference | where the controller's words come from |
| `PLANNER.md` | current reference | the flight planner, phase 1 built |
| `SCHEMA.md` | **superseded proposal** | kept for its argument only |
| `STRUCTURE.md` | **proposal** | a target layout, not today's |
| `BACKLOG.md` | pointer | superseded by `ISSUES.md` |
| `AUDIT-2026-07-29.md` | historical debrief | a dated audit; findings are issues now |
| `HANDOFF-board.md` | historical debrief | a session handoff |

## Issues: two copies, and the rules that keep them honest

`docs/ISSUES.md` is the **source**. GitHub is a **projection** of it, not a
second document.

- It reads with no network and no token, the kneeboard renders it in the
  cockpit, and it is versioned alongside the commit that fixed each issue.
- **Never edit an issue body or title on GitHub.** Edit the markdown and run
  `uv run python tools/file_issues.py --sync`.
- GitHub owns exactly one thing: **open/closed state**, because closing is a
  human act. `tools/issue_sync.py` reconciles that direction.
- `tools/issue_sync.py` (inside `check.py`) fails on state drift, body drift, an
  unfiled issue, a duplicate slug, or a `needs-flight-test` issue with no card
  row. It **skips**, loudly, when it cannot reach GitHub.

This was not always true: `file_issues.py` wrote a body once and never again, so
58 of 76 had drifted — including one that went on describing a terrain survey as
outstanding after it had been flown.

## Every commit names an issue

    Refs #11      touches it
    Closes #11    finishes it — but a `needs-flight-test` issue is closed by a
                  PILOT flying the card, never by a green test suite

Closing wants an attestation (`tools/attest.py`): who tested it, what was
exercised, at which commit. Everything merges straight to `main`; there are no
PRs. A change that fits no issue means the issue is missing.

## Known limits, so you do not rediscover them

- **One approach per bridge.** `load_and_push_plate` takes a single profile, so
  a bridge works one arrival at a time (#2).
- **`agent_atc.py` is ~4,950 lines** and its loop functions are not directly
  callable by tests (#55).
- **SIDs and STARs are not modelled**; departures are vectors and a cruise
  level (#70).
- **The director API is unauthenticated** and published on the LAN (#74).
- **The regex fallbacks in the radar path still exist** beside the structured
  one (#47).
- **Nothing hands a landed aircraft to Batumi Ground** (#77).

## Recipes

For "I want to add a field / an approach / a kneeboard page / a handoff rule /
change a prompt", see [`docs/RECIPES.md`](RECIPES.md). Each says which file owns
the fact, which layer boundary applies, what to run, and whether it puts a new
row on the flight test card.
