# Marshall — start here

Procedural + agentic radio ATC, mission generation, and kneeboard charts for DCS
World.

**Read `docs/START_HERE.md` first.** Two pages: what runs today, which process
decides what, where state lives, and — the part that was missing — **which
document to believe when two disagree**. Then `docs/GOTCHAS.md` (trust it) and
`docs/RECIPES.md` if you are about to add a field, an approach, a page, a
handoff rule or a prompt.

Every document under `docs/` now declares its `Type:` — current reference, work
record, proposal, or historical debrief — because the depth was never the
problem; telling today from history was. `tools/docs_check.py` enforces it.

`docs/WIRING.md` is the companion to those: DESIGN says what the system is FOR,
WIRING says what it actually DOES — what talks to what, in what order, and which
of the two brains produced a given transmission. Read it when a sortie did
something inexplicable; it is organised symptom-first at the end.

**`docs/STATE.md` is the one to read before adding anything that REMEMBERS.**
Where the truth lives, who owns it, and when it dies — the axis every
foundational bug this month has fallen along. Written 11 August after a sortie
whose three separate complaints had one cause: the board cannot remember who is
flying, because `flights` is append-only, scoped to nothing, and cleaned by hand.

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
the ONE PLACE EVERYTHING READS FROM (fixes, wind, the `ApproachProfile` + its
capability); the mission builder, the chart, and the ATC all read it, so they
can't disagree.

**It is not where those facts belong, and this line used to say it was.** It
called `route.py` "the single source of truth" while `docs/STATE.md` said
Postgres was — the same phrase, in two documents, with opposite answers, and
`LAYERS.md` placing `route.py` in Layer 1 beside `tracks`. So the architecture
declared *code* foundational for the fixes, the frequencies and the procedures,
and every agent who read this file went to Python to change them. That is how
"add an aerodrome" and "add a pilot's callsign" both became *edit code and
restart*, and how the speech recogniser ended up primed for a 1944 Mustang
sortie while an F-16 flew the mission.

**Read `docs/CONFIG.md` before adding a constant.** One rule — *would a
different map, era, pilot or flight plan change this value? then it is data* —
and the split it implies: reference and sortie facts are rows in Postgres,
seeded from a citable source; the RULES of controlling stay in code and stay
tested. Numbers in the database, logic in code. `route.py` keeps its job as the
one thing everybody reads, as a typed reader over those tables rather than
their author. Tracked in #137.

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
- The **language brain** (Bedrock on strands-pg, its own container) owns language,
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

## The radio: one ear, ten mouths
`radio/client.py` listens on every frequency and never transmits, so it can
never be blocked; `radio/pool.py` holds ten clients that speak. Serialisation is
per FREQUENCY — two controllers at two aerodromes talk at once, two
transmissions on one channel wait, which is what a blocked transmission is.

Three things that are not obvious and cost real bugs:

- **SRS does not echo a client to itself, but it does echo one client to
  another.** With a pool our own voice comes back looking exactly like a pilot,
  so the ear ignores the pool's GUIDs. Without that a controller stands off for
  himself for 1.5 s after every word.
- **A warm client skips the 0.4 s settle; a fresh one cannot** — it clips the
  first frame about one run in four, intermittently. That is why there is a
  pool rather than a client per transmission, which would otherwise be simpler.
- **The model call must not hold the radio.** It used to, at a median 3.3 s and
  a worst case of 13.5 s.

**ATIS is outside all of it** — one client per broadcasting aerodrome, because
22 seconds of audio every 30 would hold the pool permanently. It decides the
runway in use and writes it to the `atis` table; controllers READ it rather
than recomputing from the wind, so the broadcast and a taxi clearance cannot
name different runways.

## Shape
One repo, two deployables. They are a single system with a contract between them,
so a change that spans the seam (a new clearance the agent must voice, say) lands
as one commit.

### Say the part, not the folder

**The parts are named for what they DO and each one sits at a layer.** A part
named for the folder it grew in cannot say what layer it is, which is a review
cost paid every time — *"i'm having a hard time validating the work you are
doing and at what layer when it's all lumped into 'bridge' and 'director'."*

| say this | layer (`docs/LAYERS.md`) | what it does | code |
|---|---|---|---|
| `marshall-radio` | 0, transport | the SRS voice client: one ear, ten mouths, no aviation | `radio/` |
| `marshall-atc` | 4–5, control + procedure | separation, the board, approaches, clearances, handoffs, the ground | `atc/` |
| `marshall-feed` | 1, world | the sim mirrored into Postgres | `feed/` |
| `marshall-kneeboard` | 7, surfaces | the page server, and a real command since #147 | `kneeboard/` |
| the **language brain** | 6, language | what we ask Bedrock, in what words; the conversation, the tools a seat is handed | `atc/agent/` + the HTTP door in `services/app.py` |
| the **stores** | 1–3 | Postgres + PostGIS + pgvector and the migrations | `services/db`, `services/migrations`, read through `marshall.atc.*` |

**"Bridge" and "director" are deprecated as words, AND THE FOLDERS ARE GONE.**
Both were directories that grew into processes — the second was a separate
repository merged in by subtree on 25 July, and the folder was the seam.
`director/` is **`services/`** as of 18 August (#147). Say the
layer you mean instead: `marshall-radio` for audio, GUIDs and frequencies;
`marshall-atc` for separation, procedure and clearances; "the language brain"
for the model half; "the stores" for Postgres. The canonical table, with the
reasoning, is [`docs/STRUCTURE.md` → **What to call the parts**](docs/STRUCTURE.md#what-to-call-the-parts).

**THE FOLDERS HAVE MOVED NOW, and the vocabulary did not wait for them.**
`director/` became `services/` on 18 August; the words were correct a fortnight
earlier. That gap IS the lesson: the rename and the vocabulary were treated as
one question, so the words went unsaid while the folders had not moved (#147).
The same conflation blocked `marshall-atc` from `[project.scripts]` — it was
filed under #55 beside `marshall-radio`, and only one of the two ever needed
the extraction.

### Where the code is

- **`src/marshall/`** — `core/route.py` (the façade over `units`, `airspace`,
  `fixes`, `fields`, `stations`, `approach`), `atc/` (the receive loop
  `agent_atc.py`, the deterministic `controller.py`, `intents`/`bedrock_intent`,
  `briefing.py` which generates the plate, the domain modules that came out of
  the container in #147 — `board`, `approaches`, `clearance`, `filing`, `plans`,
  `frequencies`, `identify` — and `agent/`, the language brain's half: the
  prompts `soul`/`plate`/`rules` plus `capability`, `context` and `hooks`),
  `radio/` (two-way SRS voice client, STT, TTS, plus the synthetic-pilot +
  multi-ship rehearsal test harness — it was `srs/` until 31 July, and SRS is a
  vendor's name for a transport), `feed/` (the sim mirrored into Postgres),
  `mission/` (pydcs `.miz` builder + `ai_control.lua`), `kneeboard/` (charts).
- **`services/`** (its own container stack, `director/` until 18 August) — the language brain's HTTP door and
  the stores on strands-pg (Postgres + PostGIS + pgvector): the identity graph
  (`contacts`), the live PostGIS track cache (`tracks`), the `approaches` +
  `flight_plans` tables, and the DCS-gRPC tools. `marshall-atc` talks to it over
  HTTP (`/atc`, `/radar`, `/hooks/due`, `/prompts`, ...). Run it with
  `cd services && docker compose up -d`.

  **The ATC is no longer in here, and neither are the prompts.** The words moved
  to `src/marshall/atc/agent/prompts/` in `ebea93a`; the twelve modules of
  domain reasoning under `director/tools/` followed them in #147, ten into
  `marshall.atc.*`. What is left in `services/tools/` is `busy` (one lock per
  agent identity) and `ops` (`escalate`) — properties of running an agent behind
  HTTP, not of controlling aeroplanes. Nothing redirects: the old
  `tools.<name>` spelling raises, and `tests/test_the_atc_is_not_in_a_container.py`
  keeps it that way.

  Its compose project name stays **pinned to `marshall-director`** in
  `docker-compose.yml`, and the pin is what made the folder safe to rename:
  compose derives a project from the DIRECTORY unless told otherwise, and it
  has been told, so `cd services && docker compose up -d` still reaches the
  same containers. **The pin does not follow the folder and must not** — the
  running deployable's identity is `marshall-director` whatever the directory
  is called, and changing it would orphan the containers.

  **The `marshall-director_pgdata` hazard this note used to describe never
  survived to bite, and saying so is the point.** It warned that letting
  compose derive the project would mount an empty volume and bring the agent up
  with no contacts, sessions or approaches. That was true when the database
  lived in a named volume. It does not: `docker volume ls` shows no marshall
  volume, and the data is a **bind mount to `/srv/pgdata/data`** — a dedicated
  LVM volume — which no project name can miss. Verified 17 and 18 August; the
  rename was done with the containers up and the row counts were identical
  either side.

  A documented constraint that has stopped being true is worse than no note:
  this one deferred the rename for a fortnight (#147), and the correction that
  killed it landed HERE on 17 August and not in `docs/STRUCTURE.md`, which is
  the document `START_HERE.md` tells you to read before renaming a directory.
  It sat there wrong for another day. **A correction is not landed until it
  reaches the document somebody will actually consult.**

  It is also a stamp of `strands-pgsql-agent-framework`. The subtree prefix
  moved with the folder: `diff -r /tmp/fresh-stamp services/`, and a future
  pull is `git subtree pull --prefix=services`. That workflow was the second
  stated cost of the rename and it is a flag, not a blocker.

## How it runs
**`marshall-radio` + `marshall-atc` are one host process today**
(`marshall-atc --srs <host> <freq> <voice> <session>`, or the `python -m
marshall.atc.agent_atc` form `tools/bridge.py` starts it by): it
injects radar plus any controller directive and POSTs each call to the language
brain's `/atc`. Splitting them into two commands waits on #55. The language
brain and the stores run under `docker compose` in `services/`. Model tier is all-Sonnet by default (thinking disabled
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
voice process running, and cost model calls, so they are run before a session rather than on
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
3. **`tools/atc_dryrun.py`** — `marshall-atc` without the radio. Same message
   assembly as the live loop, typed input, so the two-brain seam (does the agent
   VOICE the controller's altitudes or paraphrase them?) is testable in seconds.
4. **`radio/rehearsal.py` / `radio/pilot.py`** — synthetic pilots over real SRS with
   Polly and Whisper in the loop.
5. **A live mission** with AI flights, driven by `mission/ai_control.lua`.

## Committing while somebody else is working

`git commit` commits the **whole index**, and on a shared tree the index is not
yours. Staging your own files with an explicit `git add` does NOT protect you:
another process's staged work rides along into your commit, under your message.
That happened five times on 13 August, in both directions, between agents that
were each adding paths explicitly.

    git commit --only <paths> -m ...     commits those paths and nothing else

Use it whenever anything else might be writing. The same trap has a sharper
edge: `git commit --allow-empty` is **not** empty on a shared tree — it commits
the index too, and swept up 23 of another agent's staged files. An empty commit
has to be empty by construction (`git commit-tree` off HEAD's own tree), not by
flag.

Nothing was ever lost, because the content is still committed — but
`git log --follow` names the wrong commit and the issue trailer belongs to
somebody else's work, so "what changed for this, and why" stops being one click.
That correlation is the whole reason the trailers exist.

For parallel agents the real answer is a worktree each (`isolation: "worktree"`),
which turns a silent clobber into a visible merge conflict. Keep the
file-ownership briefs anyway: a conflict you have to resolve is cheaper than a
clobber you never see, but it is not free.

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

**A synthetic pilot may fly the STRUCTURAL half.** `tools/ladder_rehearsal.py`
and `tools/stack_rehearsal.py` speak over real SRS through real Whisper and judge
the flight recorder, and what they check is structure: did the handoff fire, did
the phase move, was the number spoken, did two aircraft share a level. That is a
pilot flying the card for those rows, and an attestation naming the run closes
them.

What a machine still cannot answer stays a human's, and the line is not fuzzy:

    a machine can    a handoff fired · a phase moved · a number reached the air ·
                     no two aircraft at one level · the right field's frequency
    only a pilot     whether it SOUNDS like one person · whether a seam is
                     audible · whether the guidance was USEFUL · whether a
                     transmission arrived at a moment that made sense

Card row S11 is the standing example — "listen for a transmission with a seam in
it" — and no rehearsal will ever score it. When the harness closes a row, the
attestation says which run, so the evidence is as revisitable as a pilot's.

Everything merges straight to `main`; there are no PRs. The issue reference IS
the correlation — GitHub threads the commit onto the issue, so "what changed for
this, and why" is one click rather than an archaeology exercise. A change worth
committing that fits no issue means the issue is missing: write it into
`docs/ISSUES.md` and `uv run python tools/file_issues.py`.

## The repo is PUBLIC
No personal paths, emails, IPs, or secrets in committed files. Keep ops specifics
in private memory.
