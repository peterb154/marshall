# Naming the parts, and the layout that follows

    Type: PROPOSAL — reconciled claim by claim against the tree. Roughly half
          of it is now code; the marks below say which half.
    Validated against: 12 August 2026, at 6b835f8 — every claim read against
          the working tree and `git log`, and marked APPLIED, PARTLY APPLIED,
          STILL INTENT or SUPERSEDED

> **This used to be unsafe to read.** It was written on 31 July in the present
> tense, describing a layout we did not have, and its own warning said so: *a
> new reader cannot tell the target from the tree.* That warning was not enough
> — the decisions in here were made, several of them shipped, and a later
> search for "the renaming decision" concluded it had never been written down.
> A document nobody can date is a document nobody can find.
>
> So every claim now carries its status and, where it landed, the commit that
> landed it. **The reasoning is untouched** — the argument for why a name was
> wrong is the part worth keeping, and it stays true whether or not the rename
> happened.

A proposal, now marked up. Companion to `SCHEMA.md` (superseded) and to
`CONFIG.md` (current, and the thing that actually answered half of this): those
are about where FACTS live, this one is about where CODE lives, and they have
the same root cause.

---

## What to call the parts

> **This section is CURRENT REFERENCE, inside a document that is otherwise a
> proposal.** The rest of the file argues; this table is the agreed vocabulary
> and is what `CLAUDE.md`, `START_HERE.md`, `WIRING.md` and `LAYERS.md` point
> at. Written 13 August, when the pilot said what the naming argument had cost
> him and it turned out not to be aesthetics:
>
>     "i'm having a hard time validating the work you are doing and at what
>      layer when it's all lumped into 'bridge' and 'director' -- which are
>      legacy names."
>
> A part named for the folder it grew in cannot say what layer it is, so a
> reviewer cannot tell whether a change landed at the right altitude. That is a
> review cost, paid every time, and the deferral below priced only the
> technical risks.

**Say these.** The layer column is `LAYERS.md`'s stack, and it is the point of
the table: a part that cannot name its layer cannot be reviewed at one.

| say this | layer | what it does | the code |
|---|---|---|---|
| **`marshall-radio`** | **0 Transport** | the SRS voice client — one ear on every frequency, ten mouths, serialised per frequency. Knows nothing of aerodromes; a frequency is a number | `src/marshall/radio/` |
| **`marshall-atc`** | **4–5 Control + Procedure** | separation, the board, the holding stack, sequencing, approaches, clearances, handoffs, the ground. The half that must never be a model's guess | `src/marshall/atc/` |
| **`marshall-feed`** | **1 World** | the sim mirrored into Postgres: the unit stream, events, the reconciling sweep, the world reset | `src/marshall/feed/` |
| **`marshall-kneeboard`** | **7 Surfaces** | the page server. Plate, route map, E6B, plans, the test card, `/diag`, the documents | `src/marshall/kneeboard/` |
| **the language brain** | **6 Language** | what we ask Bedrock and in what words: the prompts, the conversation window, the tools a seat is handed, the promises it makes. Owns nothing it says | `src/marshall/atc/agent/` + the HTTP door |
| **the stores** | **1–3** | Postgres + PostGIS + pgvector, and the migrations: tracks, contacts, flights, approaches, flight plans, sessions | `director/{db,migrations}/`, read through `marshall.atc.*` and `marshall.core.db` |
| **ATIS** | **1 World** | observes the wind at each field, decides the runway in use, writes it down. A sibling of ATC, not a layer under it | `src/marshall/atis/` |

**Do not say these.** They are DIRECTORY names. They name where a file happened
to sit after a git subtree merge on 25 July, and they are deprecated as
vocabulary even while the folders keep their names.

| deprecated | what it actually is | say instead |
|---|---|---|
| "the bridge" | one host process that today runs `marshall-radio`, `marshall-atc` and ATIS together, and calls the language brain over HTTP | name the LAYER you mean: `marshall-radio` for anything about audio, GUIDs or frequencies; `marshall-atc` for anything about separation, procedure or a clearance |
| "the director" | one container that today runs the language brain's HTTP door, the stores, and `marshall-feed`'s threads | "the language brain" for the model half, "the stores" for Postgres, `marshall-feed` for the sim mirror |
| "`director/tools/`" | it held the air traffic control until #147 | `marshall.atc.*` — see the module table in the entry for item 3 |

**A deployable is an entrypoint, not a directory**, which is why the first
column is a command name rather than a folder. One of the four exists today
(`marshall-kneeboard`); `marshall-radio` and `marshall-atc` wait on `_run_srs`
coming out of `agent_atc.py` (#55), and `marshall-feed` is not yet its own
process. Whether they end up as four containers or one is a deployment choice,
made in compose, that moves no files.

**And the folders keep their names, deliberately.** `director/` is pinned to
`name: marshall-director` in its compose file because its Postgres volume is
`marshall-director_pgdata`; compose otherwise derives the project from the
DIRECTORY and a rename that forgets the pin brings the stores up EMPTY while
looking entirely healthy. See the decision section below. **The vocabulary does
not wait for the folder** — it never did, and treating the two as one question
is what kept this unsaid for a fortnight.

---

## The scoreboard

| the claim | status | evidence |
|---|---|---|
| The subtree seam stops `marshall` and the director importing each other | **APPLIED** | `574906a` — image builds from the repo root, `../src/marshall` mounted |
| `feed` — the sim mirror as its own part | **APPLIED** | `574906a` — `src/marshall/feed/` |
| `srs` → `radio` | **APPLIED** | `574906a` — 13 modules, 63 references |
| `agent` is not a part; the words belong to the domain | **APPLIED** | `ebea93a` — `src/marshall/atc/agent/prompts/` |
| `core.llm` as the mechanism beside `core.geo` | **STILL INTENT** | no `core/llm.py`; model calls sit in `atc/bedrock_intent.py`, `atc/fast_atc.py`, `director/app.py` |
| `core` — `names`, `geo`, `schema`, `field` | **APPLIED**, finer than proposed | `df6ea5b` — `field` shipped as `fields` + `fixes` + `stations` |
| `route.py` gets taken apart | **APPLIED** in shape | `df6ea5b` — six modules and a façade |
| …into database rows | **SUPERSEDED** | `config/theatres/*.toml` under `CONFIG.md` / #137, not rows |
| The wind is MEASURED, not declared | **PARTLY APPLIED** | ATIS measures it; seven call sites still print `WIND_FROM_DEG` |
| `kneeboard` is one module, `diag` is a page on it | **APPLIED** | `e15c57c` — `kneeboard/diag.py` |
| The plate is two things: the picture and the procedure | **PARTLY APPLIED** | procedure is data (`311028a`); `kneeboard/plate.py` still opens on one constant |
| `atc.procedure` as a package | **STILL INTENT** | nothing under `src/marshall/atc/procedure/` |
| A procedure INSTANCE is data | **APPLIED**, as files not rows | `03edb35`, `311028a`, `118a9e6` — `[[approach]]` in TOML |
| A procedure KIND is a module carrying its own words | **STILL INTENT** | `ApproachProfile.kind` is a string tested with `if` |
| `atc` minus the radio loop | **STILL INTENT** | `_run_srs` is still `agent_atc.py:5044`; the file is 6,656 lines |
| Deployables are entrypoints, not directories | **PARTLY APPLIED** — and see the decision below | `[project.scripts]` exists; `marshall-kneeboard` is real, the other three are blocked on #55 or are not processes |
| `director/tools/` holds no ATC domain reasoning | **APPLIED** | #147 item 3 — ten modules into `marshall.atc.*`, `busy` and `ops` left; `tests/test_the_atc_is_not_in_a_container.py` is the grep |
| "director" names a bundle of two unrelated things | **SUPERSEDED** | the bundle was unbundled; what is left is a smaller, more honest one |
| Delete the `/radar` prose round trip | **PARTLY APPLIED** | `c6afa12` built the replacement; six callers still parse the prose (#47) |
| Delete twelve CRUD endpoints | **STILL INTENT, going backwards** | 24 routes on 31 July, **34** today |
| the flights SQL module — 326 lines of SQL | **STILL INTENT for the deletion; it has MOVED** | `src/marshall/atc/board.py`, 377 lines |
| Horizontal parts / vertical domains | **STILL INTENT** as a taxonomy | no `traffic`, `planner` or `opfor` |

Two rows in that table are worth more than the rest, because they point the
same way. **The parts that were about SHAPE mostly landed. The parts that were
about DELETION mostly did not** — and two of them have grown since the proposal
was written. A structure change is easy to celebrate and a deletion has to be
argued for one caller at a time.

---

## The layout caused the bug

> **APPLIED, `574906a`.** The seam is closed in the direction that mattered.
> The director's image now builds from the repo root and mounts
> `../src/marshall` at `/app/marshall`, so `director/app.py` imports
> `marshall.feed.tracks` and `marshall.core.geo` directly. The bridge reads
> Postgres itself (`tools/bridge.py::_compose_dsn`) rather than asking over
> HTTP. What has NOT happened is the deletion this made possible — see the
> endpoint counts above.

`director/` is not a design decision. It was a separate repository, merged in by
git subtree on 25 July (`c5c5617`), and the folder is the seam where the merge
happened.

That seam is why `marshall` and the director could not import each other. Which
is why `_key` was written three times and "bearing between two points" six, and
why `/radar` rendered structured rows into English so the other side could parse
them back into structs. **Duplicating was the only thing available.**

So the structure is not cosmetics. It is the thing that makes "one home per
rule" possible or impossible.

## The name

> **SUPERSEDED, and this is the reconciliation's most useful finding.** The
> argument below is against a bundle that has since been unbundled — by two of
> this document's own recommendations. The sim feed left the director on 31
> July (`574906a`, `src/marshall/feed/`). The prompts left on the same axis
> (`ebea93a`, `src/marshall/atc/agent/prompts/`). What remains behind the name
> "director" is the agent's HTTP door, Postgres, the migrations, the vendored
> upstream stamp, and — until 13 August — `director/tools/`, twelve modules of
> ATC domain logic (`approaches`, `clearance`, `flights`, `identify`, `plans`,
> `frequencies`, `capability`, `filing`, `hooks`, `context`, `ops`) that were
> the prompts' problem one layer down: **domain reasoning living in a
> deployable's directory, findable only by somebody who already knows to look
> in a container.** That, not the word, was what was left of this complaint,
> and #147 item 3 answered it: ten are `marshall.atc.*`, and the two that
> stayed serve the agent over HTTP rather than controlling aeroplanes.

"Director" describes a bundle, not a responsibility. It was, when this was
written, two unrelated things sharing a container:

  * the Bedrock agent -- prompts, conversation, judgement
  * the sim feed -- the unit stream, the sweep, events, the world reset

Those change for different reasons, are written by different people on different
days, and one of them is on the voice path while the other is not. A name that
covers both cannot say anything useful about either.

It also invites the mistake we just spent the evening undoing: if a thing is
called "the director" then routing data through it feels like architecture,
and twelve CRUD endpoints appear in front of a database that everybody could
have read directly.

## The parts, named for what they do

**`core`** -- below everything, imports nothing of ours.
`names` (one aeroplane's four names), `geo` (range, bearing, projection, grid
convergence, crosstrack -- with the FRAME in the signature), `schema` (the
SQLAlchemy models), `field` (airfields, runways, fixes, frequencies -- the
MEASURED world; see below for why the procedure is not here).

> **APPLIED, `df6ea5b`, and the split that shipped is finer than the one
> proposed.** `core/` today is `names`, `geo`, `schema`, `units`, `db`, `say`,
> `scope`, `theatre`, `catalogue`, `airspace`, `fields`, `fixes`, `stations`,
> `approach`, `route`, `dtc`, `nevada`. The single `field` in this list turned
> out to be three subjects — the aerodromes (`fields`), the places
> (`fixes`) and the controllers (`stations`) — and separating them is what made
> "adding an aerodrome" stop meaning "edit a station four hundred lines from
> the field it belongs to". `route.py` survives at 283 lines as a façade over
> the six, deliberately, because three hundred call sites read `R.BATUMI_ASR`.

**`feed`** -- the sim mirrored into Postgres. The unit stream, `gone`, the
reconciling sweep, `inAir`, land/takeoff, the mission-clock world reset. It
writes `track` and nothing reads through it.

> **APPLIED, `574906a`** — `src/marshall/feed/{tracks,events,dcs,stubs}.py`,
> and it took `strands_pg._pool` with it: `core.db.pool()` is the same database
> without the framework's pgvector registration, and it belongs to everybody.
> **"Nothing reads through it" is not true and never was.** `feed/tracks.py`
> exports `contacts`, `radar_cached`, `bullseyes`, `known_fixes`,
> `known_sectors` and `_render` — the prose picture is rendered *inside the
> mirror*. `core/scope.py` is the reader that was supposed to replace that path
> (`c6afa12`) and it exists; the old one was never removed. See #47.

**`atc`** -- the deterministic controller. Separation, the holding stack,
identity resolution, ASR guidance. The part that must never be an LLM's guess.

> **STILL INTENT for the "minus the radio loop" half.** `_run_srs` is still
> `agent_atc.py:5044` and the module is still its own `__main__`. The file has
> gone from 3,688 lines (`LAYERS.md`, 30 July) to 6,656 — and note that three
> current documents quote three different figures for it, which is its own
> small lesson about numbers in prose. Tracked as #55.

**`radio`** -- the voice. SRS transport, STT, TTS, the receive loop, the
synthetic pilots. `srs` is a vendor's name for a transport, not a description of
what this does.

> **APPLIED for the rename, `574906a`; STILL INTENT for the move.** The package
> is `src/marshall/radio/` and holds `client`, `pool`, `stt`, `tts`, `receive`,
> `pilot`, `rehearsal`, `crowd`, `loopback`, `converse`, `selftest`,
> `atc_session`. The receive LOOP did not come with it.

**`agent` IS NOT A PART.** An earlier draft had it as one, and that was the
`director` mistake at a higher altitude: "the thing that calls Bedrock" is a
MECHANISM, not a responsibility. The moment a second domain has a brain, that
drawer holds an air traffic controller and an enemy commander, which have
nothing in common but an SDK.

So `core.llm` is a capability -- tiers, structured output, retries, token
accounting -- alongside `core.geo`. And what you ASK a model belongs to the
domain asking: `atc.agent` has the controller's prompts, conversation and
phraseology, exactly as `atc.procedure.ils` carries its own words.

Whether a domain uses an agent at all is ITS business:

    "If we have a 'traffic' module, it might, or might not use a Strands agent.
     That's an implementation detail for traffic to figure out."

Which is the test of a good boundary -- the part list does not change when a
domain changes its mind about implementation.

> **APPLIED for the half that mattered, `ebea93a`.** `src/marshall/atc/agent/`
> exists and holds `soul.md`, `plate.md` and `rules.md` — the controller's
> words, in the domain that speaks them, rather than in a container's
> directory next to a Dockerfile. Its own docstring records the pilot quote
> that forced it: *"I don't know how/where that works today."*
>
> **`core.llm` is STILL INTENT.** There is no `core/llm.py`. Tiering, retries
> and structured output are spread across `atc/bedrock_intent.py`,
> `atc/fast_atc.py` and `director/app.py`, which is the duplication this
> paragraph predicted, now with a name.

**`kneeboard`** -- the web server. It renders pages from the database and holds
no state of its own. The plate, the route map, the E6B, the plans page, the test
card and the diagnostics page are all PAGES on it, not separate parts.

> **APPLIED.** `src/marshall/kneeboard/` holds nineteen modules and every one
> of them is a page or a renderer: `diag`, `plate`, `asr_plate`, `aip_plate`,
> `routemap`, `e6b`, `plans`, `filing`, `card`, `flighttest`, `navlog`,
> `comms`, `docs`, `brief`, `check_plate`, `control`, `site`, `serve`.

**`mission`** -- the `.miz` builder and the AI control Lua. Unchanged.

> **APPLIED** (trivially — it was already right). `build.py`, `validate.py`,
> `nevada.py`, `ai_control.lua`, `beacons.lua`, `survey/`.

### Why `procedure` is ATC and not core

`route.py` feels like core because it is currently TWO things.

**Facts about the world** -- field elevation, runway threshold, grid
convergence, beacon position, station frequencies. Measured, not decided, and
read by `atc`, `chart` and `mission` alike. That half is core, and under
`SCHEMA.md` most of it stops being Python at all and becomes measured rows.

**Procedure design** -- hold base, platform, minima, the missed approach,
guidance style, the capability handicaps. Nobody measures those; somebody
decides them. They are doctrine: how a controller works this approach.

The consumer test settles it. Procedure is read by exactly two parts, `atc` and
`chart`, and `chart` already sits above `atc`, so `chart -> atc.procedure` is a
downward dependency and legal. `mission` wants the geography, not the doctrine.
`feed` wants neither once fixes are rows. `agent` is handed a rendered plate,
never the profile.

So: **`core.field`** (airfield, runway, fix, frequency) and
**`atc.procedure`** (how it is flown).

> **The distinction was honoured; the package was not.** `core.field` landed as
> `core/fields.py`. `atc.procedure` does not exist — `AtcCapability` and
> `ApproachProfile` are `core/approach.py`, still in `core`, and their
> INSTANCES became `[[approach]]` tables in `config/theatres/*.toml`.
>
> **Why that is a supersession rather than a failure.** The argument here is
> "doctrine is not measurement, so it does not belong beside the survey data",
> and `CONFIG.md` (#137) answered it on a different axis: *shapes and behaviour
> are code, instances are configuration*. Once the four Caucasus procedures
> were TOML, "which Python package holds the dataclass" stopped being the
> question that decides whether adding an approach costs a commit. It does not.
> The consumer test in this section is still the right test — it is just no
> longer the binding constraint.

### And `procedure` is three things, not one

    "There is 'how does an ILS work' that should be shared in Nevada and in
     Caucasus. ILS is ILS -- this is constant, and it's probably a combination
     of deterministic code and prompt, especially for ILS approach phraseology.
     Then there are the specific parameters for a given ILS approach -- this is
     database. And there are a hundred other things we'll need to program --
     progressive taxi, forward air controller."

**THE KIND is code, and it carries its own words.** How an ILS works does not
vary by continent: intercept the localizer, capture the glideslope, decision
height, missed approach. Written once, deterministic where it must be. And the
PHRASEOLOGY belongs with it -- how you say an ILS clearance is part of knowing
what an ILS is, so a procedure module ships its own prompt fragment rather than
having one grown in a shared system prompt where nothing owns it. That is the
brief mechanism [LAYERS.md](LAYERS.md) already describes, made per-procedure.

> **STILL INTENT.** `ApproachProfile.kind` is a string —
> `"ndb" | "asr" | "ils" | "visual"` — and it is read with `if self.kind ==
> "asr"`. The shared phraseology is still `atc/agent/prompts/rules.md`, which
> its own package docstring calls out as the next thing to break up. The
> precondition (a package for the words) is built; the split is not.

**THE INSTANCE is data.** "Batumi ILS 13": localizer course, glideslope angle,
decision height, the missed approach point, the hold. A row naming its kind.

> **APPLIED — as files, not rows** (`03edb35`, `311028a`, `118a9e6`).
> `config/theatres/caucasus.toml` carries four `[[approach]]` tables, each with
> its `kind`, its `[approach.atc]` capability and its `[approach.own_point]`.
> The Python definitions are **deleted**: `core/fields.py`, `core/stations.py`
> and `core/approach.py` no longer DEFINE `FIELDS`, `STATIONS`, the nine seats
> or the four procedures. A module `__getattr__` in `route.py` resolves the old
> names against the configured theatre, which is how ~300 call sites survived
> the move untouched. Nevada is unconverted, blocked on #141.

**THE CATALOGUE is the reason this shape matters.** Progressive taxi, forward
air control, GCA, the overhead break, formation join, clearance delivery. Each
is a new KIND -- a module behind one interface -- and not a new branch inside
the existing one. Adding Kobuleti ILS is a row. Adding progressive taxi is a
module, and nothing already written has to change to accommodate it.

    atc/procedure/__init__.py     the interface every kind implements
    atc/procedure/ils.py          + its phraseology
    atc/procedure/asr.py          the talkdown we fly today
    atc/procedure/ndb.py          the 1944 beacon letdown
    atc/procedure/visual.py
    atc/procedure/taxi.py         not written yet
    atc/procedure/fac.py          not written yet

> **STILL INTENT, and the first half of the promise came true anyway.** Adding
> Kobuleti's ILS *was* a row — that is what `118a9e6` bought. Adding a new KIND
> is still a branch: the talkdown lives in `atc/asr.py` and `atc/talkdown.py`,
> the descent geometry in `atc/descent.py`, and the four kinds are `if`
> statements across `core/approach.py` and `atc/controller.py`. #113 (no
> procedure model: no SIDs, no STARs, no transitions) is the same gap seen from
> the other end.

This is also the answer to "what happens to `route.py`". It is EIGHT things --
unit constants, mission settings, a gazetteer, one sortie's flight plan,
airspace design, stations, arithmetic, and a capability model -- which is why
its name never fit. It does not get renamed. It gets taken apart:

    NM, MPH_PER_KT, INHG_PER_FT       core.units    (constants, like gravity)
    qfe_inhg, ias_mph, msa_for        core.geo      (arithmetic)
    KOBULETI, BATUMI, INGRESS, ...    fix rows      (a gazetteer, measured)
    MSA_SECTORS, MVA_CELLS            airspace rows (per field)
    CENTER/APPROACH/TOWER/OVERLORD    station rows
    SORTIE, SORTIE_LEGS, SORTIE_ALT   flight_plan rows (ONE mission's route)
    CRUISE_TAS, WIND_*, QNH_*         mission settings -- and the wind is now
                                      MEASURED, not declared
    AtcCapability                     atc.procedure (doctrine)

> **It was taken apart, `df6ea5b` — but line by line the destinations differ,
> and the differences are informative rather than sloppy.**
>
> | proposed | where it went |
> |---|---|
> | `NM, MPH_PER_KT, INHG_PER_FT` → `core.units` | **as proposed** |
> | `qfe_inhg, ias_mph, msa_for` → `core.geo` | `ias_mph` and `altimeter_spoken` are `core/units.py`; `msa_for` is `core/airspace.py`. Arithmetic followed its SUBJECT, not the word "arithmetic" |
> | the gazetteer → fix rows | `[[fix]]` and `[[field]]` in `config/theatres/*.toml`. **The sortie's own turning points stayed in `core/fixes.py` on purpose** — publishing them to every controller as though they were navaids was the original bug (#137, #145) |
> | `MSA_SECTORS, MVA_CELLS` → airspace rows | `core/airspace.py` holds the logic; per-field values are TOML |
> | the four stations → station rows | **as proposed**, `[[station]]` (`03edb35`), and `PRESET_LADDER` is now DERIVED from them rather than kept by hand |
> | `SORTIE*` → flight_plan rows | `flight_plans` is a real table with its own legs (#131, #142, migration 031) — but `core/fixes.py` still holds `SORTIE`, `SORTIE_LEGS`, `SORTIE_ALT_FT` for the 1944 mission |
> | `CRUISE_TAS, WIND_*, QNH_*` → mission settings | **STILL INTENT.** They are module constants in `core/units.py` |
> | `AtcCapability` → `atc.procedure` | `core/approach.py`, with instances as `[approach.atc]` |

The wind one is worth stopping on. `WIND_FROM_DEG = 180.0` is a hardcoded
constant that the sim will now tell us, and the runway in use is computed from
it. A declared wind is a stored answer to a question with a live input.

> **PARTLY APPLIED, and the unfinished half is a live disagreement.**
>
> The measurement exists and is good: `atis/weather.py` samples the sim's wind
> ten metres above **each field** — deliberately not at the surface, because
> DCS's boundary layer reports calm on a usable day — and `atis/store.py`
> writes the runway in use to the `atis` table. `Controller._runway_in_use`
> ASKS that table rather than recomputing, which is the whole point of it.
>
> **The wind itself was never rewired.** `WIND_FROM_DEG = 90.0` is still a
> constant in `core/units.py`, and it is what the plate, the navlog, the E6B,
> the printed brief, `atc/briefing.py`, `atc/assembly.py`, the `.miz` builder
> and `Controller._wind_phrase` all say out loud. `controller.py:1862` puts
> both in one sentence — the runway asked from the measurement, the wind read
> from the constant — so a landing clearance can name a wind that contradicts
> the ATIS broadcast that chose its runway. `Field_.active_end` falls back to
> the same constant when nobody hands it a measurement.
>
> That is the exact failure this repo exists to prevent, one field over: the
> chart and the radio disagreeing about a number. Filed as **[ATIS-4] #148**.

### The kneeboard is one module, and diag is a page on it

An earlier draft split `chart` from `diag` by AUDIENCE -- in-world versus
out-of-world. That was over-splitting. They share a delivery mechanism: both are
web pages, both render from the database, both arrive through the same server.

    "The kneeboard is its own module. It's a web server that pulls data from the
     database mostly. And diag, this is a page on the kneeboard (could also be
     on a computer screen). We are using a hack that OpenKneeboard allows me to
     publish a web page to my kneeboard so I can diagnose issues."

So `kneeboard` is the part, and the pages are pages. That OpenKneeboard will
display an arbitrary web page is a delivery trick, not an architecture: the same
page opens on a monitor, and neither is a different module.

THE AUDIENCE RULE SURVIVES, as a rule about PAGE CONTENT rather than about
module boundaries. A plate is what a pilot flies with and must never show what
the controller believes -- an aeroplane drawn on it that the engine has wrong
would be worse than no aeroplane at all. The diagnostics page exists precisely
to show that: identity and its authority, released board entries with the scope
that contradicted them, the ghost banner. Same server, opposite obligations.

> **APPLIED, `e15c57c`.** One module, `diag.py` beside `plate.py`, and the
> audience rule survives as a rule about content.

AND THE PLATE IS TWO THINGS, which is worth separating while we are here. There
is the PICTURE the pilot sees -- drawn, and belonging to the kneeboard. And
there is the PROCEDURE that picture depicts -- the fixes, altitudes, courses and
minima ATC needs in order to direct him -- which is static data in the database,
read by `atc.procedure` to fly the approach and by the kneeboard to draw it.
Today one Python object is both, so the drawing and the directing cannot
disagree only because they happen to share a variable.

> **PARTLY APPLIED.** The procedure is data (`[[approach]]`, `311028a`) and the
> drawing reads it. But `kneeboard/plate.py` still opens with
> `P = R.BATUMI_APPROACH` — one module constant — which is #137's own
> outstanding item: *the "NDB 13" page is correctly bound to the NDB procedure
> and wrongly bound to the Caucasus; it renders a Batumi plate on any map.*

## Deployables are entrypoints, not directories

This is the whole fix. One installable package, several ways to start it:

    marshall-radio     the bridge: voice in, voice out
    marshall-atc       the controller -- deterministic half and agent half
    marshall-feed      the sim mirror
    marshall-kneeboard the page server

Whether those are three containers or one is a deployment choice, made in
compose, changed without moving a file. What matters is that all four import the
same `core`, so there is one squash, one bearing, one schema -- and adding a
fifth process costs nothing.

`strands_pg`, `_grpc` and `migrations` stay where an upstream stamp can still be
diffed (`diff -r /tmp/fresh-stamp`), because that is a real constraint and not
a naming one.

> **STILL INTENT — and the decision, 12 August, is DO NOT DO THIS YET. Read the
> next section before touching a directory name.**
>
> The one part of this paragraph that DID land: `_grpc` is
> `src/marshall/_grpc/`, out of the stamp, because the stubs are ours and
> everybody needs them. `strands_pg` and `migrations` stayed.

### The decision on the names, 12 August 2026

**"Bridge" and "director" stay. They are directory names that everybody can say
out loud, and the cost of changing them today is paid in the one place this
project cannot afford to spend it.** What follows is why, and what the
migration would actually involve, so that the next person to have this idea
does not have to rediscover it.

**The database is the blocker, and it is not negotiable.** The director's
compose project name is pinned in `director/docker-compose.yml`:

    name: marshall-director

Its Postgres volume is `marshall-director_pgdata`. Compose derives the project
from the DIRECTORY unless told otherwise, so the pin is the only thing standing
between a folder rename and an agent that comes up with an empty database — no
contacts, no sessions, no approaches, no flight plans — while looking entirely
healthy. **Any rename must keep `name: marshall-director` and the volume name
exactly as they are**, which means the deployable's real identity does not
change even if every file moves. A rename that must preserve the old name in
the one place a machine reads it is a rename of the documentation only.

**The subtree is the second cost.** `director/` was created by
`git subtree add --prefix=director` (`c5c5617`), and `diff -r /tmp/fresh-stamp
director/` is how upstream changes to `strands-pgsql-agent-framework` are
pulled. The prefix is part of that workflow; moving it means re-establishing
the subtree relationship for a benefit that is entirely cosmetic.

**The third cost is the one nobody counts.** `director/.env` is where this
machine's credentials live — `src/marshall/config.py` reads it deliberately,
as the single door, and `tools/sim.py`, `tools/spawn.py`, `tools/draw.py` and
`tools/asr_autopilot.py` name it in comments. It is git-ignored, so a rename
moves a file that is not in the repository, on a live box, during a sortie.

**What the migration would involve, if it is ever worth it.** Not a rename —
the argument above is really an argument for *entrypoints*, and the honest
sequence is:

1. `console_scripts` in `pyproject.toml` for what already exists:
   `marshall-kneeboard` → `marshall.kneeboard.serve`, `marshall-radio` →
   the voice client. Costs nothing, changes no directory, and makes the four
   names real for the first time. **DONE, 13 August**, for the one of the four
   that has an importable entrypoint; the table says why the others do not.
2. `_run_srs` out of `agent_atc.py` (#55). Until the voice loop's entrypoint is
   a function somebody can import, "the deployable is an entrypoint" is a
   sentence with no referent. **STILL THE BLOCKER**, now for two names rather
   than one: `marshall-radio` and `marshall-atc` are the same process today.
3. `director/tools/` into `src/marshall/atc/`, the same move the prompts made
   in `ebea93a`, and for the same reason. This is the part with real value:
   domain logic stops living in a container's directory. **DONE, 13 August** —
   ten modules moved, `busy` and `ops` left because they serve the agent over
   HTTP rather than control aeroplanes, and nothing redirects.
4. Only then does the directory hold nothing but deployment artefacts, and
   only then is its name uninteresting enough to change safely. **NOT DONE, and
   the vocabulary did not wait for it** — see *What to call the parts* at the
   top of this file. The folder rename buys nothing the words did not.

Steps 1–3 are worth doing on their own merits and none of them requires the
name to change. Which is the actual finding: **the naming argument was a proxy
for a layering argument, and the layering argument can be won without it.**
Tracked as **[ARCH-26] #147**.

**Meanwhile, say what the words mean.** "Bridge" and "director" are the names
of two DIRECTORIES that grew into deployables, not two designed
responsibilities. This paragraph used to end *"`CLAUDE.md` and `START_HERE.md`
use them because a shared vocabulary beats a correct one nobody says"*, and
that was the wrong trade: the pilot could not tell which LAYER a change had
landed at, because the folder name carries no layer. **The vocabulary is now
the table at the top of this file, the folder names are deprecated as words,
and the folders themselves have not moved.**

## What this deletes on the way

  * `/radar`'s prose round trip: `feed` writes rows, `atc` reads rows. The
    English rendering stays for the model and stops being an interchange format
    between our own components. `_SCOPE_LINE`, `_FORMATION`, `_OTHER_SHIP`,
    `flatten_formation`, `_split_ships` go with it.
  * about twelve CRUD endpoints and the HTTP client functions that call them.
  * `src/marshall/atc/board.py`, the flights SQL module -- 326 lines
    of SQL wrapped in Python that the
    schema and a session can do.

> **This is the half that did not happen, and two of the three have gone
> backwards. It is the most useful thing on the scoreboard.**
>
> * **The prose round trip: PARTLY.** The replacement was built —
>   `core/scope.py` (`c6afa12`) reads contacts from the table and does the
>   formation clustering with named fields instead of positional indices. And
>   `/radar` is additive: it returns `picture` (prose, for the model) beside
>   `contacts` (data). But all five named regexes are still in
>   `atc/identity.py`, and `agent_atc.py` calls `flatten_formation` in six
>   places. The old path was never switched off. #47.
> * **Twelve CRUD endpoints: WORSE.** `director/app.py` had 24 routes when this
>   was written and has **34** today. Every one was added for a good local
>   reason, which is exactly how this shape grows.
> * **the flights SQL module: WORSE.** 326 lines then, **377** now. It has since
>   moved to `src/marshall/atc/board.py` and is the same 377 lines; a move is
>   not a deletion.
>
> A deletion nobody is accountable for does not happen. The endpoints and
> `flights.py` are the concrete work item behind step 3 above.

## Open

SETTLED: `feed`, `radio`, `mission`, `agent`, `core`. `procedure` belongs to
`atc`; `diag` splits out of `chart`.

1. **Does `atc` keep that name?** It is accurate and it is what the docs already
   call it, but it is also the name of the whole product.
2. **One container or how many?** Deployment, not layout, now that entrypoints
   rather than directories define the boundary. `radio+atc` on the voice path
   and `agent+feed+kneeboard` behind it may be the honest middle.
3. **Does `agent` become plural?** Multiple controllers, or multiple fields,
   each with their own conversation -- the part name stays singular either way,
   the same as `radio` covering many frequencies.

> **1 — ANSWERED, yes**, by this document's own last paragraph: Marshall is an
> ATC and several other things, and `atc` is literally the air traffic control
> part.
>
> **2 — STILL OPEN**, and the decision above defers it deliberately: the
> container count is not worth arguing about until the entrypoints exist.
> Today it is three: the bridge as a host process, `marshall-kneeboard` in
> `deploy/docker-compose.yml`, and the `marshall-director` project.
>
> **3 — ANSWERED in the direction that mattered.** `81c4e31` gave each flight
> its own profile (#2, #111), so "there can never be two of anything" is no
> longer true of the approach. The part name stayed singular, as predicted.
> The 15 module globals in `agent_atc.py` are the remainder.

## Horizontal parts, vertical domains

> **STILL INTENT as a taxonomy, and the horizontal row is done.** `core`,
> `feed`, `radio` and `kneeboard` all exist as described. `traffic`, `planner`
> and `opfor` do not exist — `docs/PLANNER.md` is a plan with phase 1 built
> inside `kneeboard/` and `core/dtc.py`, not a domain package. So this section
> has never been tested by a second domain, which is the only thing that could
> validate it.

The list above mixes two kinds of thing, and the distinction is what keeps it
honest as the product grows past ATC.

**HORIZONTAL -- shared by everyone, owned by nobody.**

    core       names, geo, units, field, schema, llm
    feed       the sim mirrored into Postgres; every domain needs tracks
    radio      transport, STT, TTS, "somebody transmitted on 124.0"
    kneeboard  the page server

**VERTICAL -- a domain, owning its full stack: deterministic logic, its own
procedures, its own prompts, and an agent if it wants one.**

    atc        control, identity, guidance, procedure/{ils,asr,ndb,taxi,fac}
    traffic    (later) what exists, what is materialised, and when
    planner    (later) mission generation, the dynamic war
    opfor      (later) the adversary that deploys against you

THE TEST FOR WHICH: would a second domain need this? Yes, horizontal. No, it
belongs to the domain that has it.

**DOMAINS DO NOT IMPORT EACH OTHER.** `traffic` spawns units, `feed` mirrors
them, `atc` sees contacts -- and neither module knows the other exists. That is
not an accident of the current design, it is the property being bought: the
coupling that would rot this is `traffic` reaching for `atc` to ask "is it safe
to spawn here", which is the same shape as every bug of the last week, a module
reaching sideways for a fact it should read from shared state.

`control` + `agent` is turning out to be the SHAPE OF A DOMAIN rather than a
peculiarity of ATC -- traffic wants exactly the same split, with a spatial query
deciding relevance and judgement reserved for what should be there. Worth naming
rather than rediscovering.

And Marshall is not an ATC. It is an ATC, a kneeboard, a mission planner, and
one day a war fought against something that deploys against you. `atc` is
literally the air traffic control part of that, which is why it keeps its name.

---

## What the reconciliation turned up that nobody had noticed

Four things, none of which was the point of the exercise.

1. **A landing clearance can name a wind the ATIS contradicts.** The runway in
   use is measured and asked for; the wind spoken beside it is a Python
   constant. One sentence, two sources. **[ATIS-4] #148**.
2. **`director/tools/` is the prompts problem, one layer down.** Twelve modules
   of ATC domain reasoning inside a deployable's directory. `ebea93a` moved the
   words out for exactly this reason and stopped there. **[ARCH-26] #147**.
3. **`agent_atc.py` is 6,656 lines**, and the two current references quote two
   smaller and different figures for it — 3,688 (`LAYERS.md`, 30 July) and
   ~4,950 (`START_HERE.md`, 10 August). Both were true when written; neither is
   now, and nothing will ever tell us. A number in prose is a fact with no
   owner. #55.
4. **The deletion list went backwards.** Endpoints 24 → 34, `flights.py`
   326 → 377. The shape changes landed because somebody could point at the new
   directory afterwards; the deletions did not because nobody could point at
   anything.
