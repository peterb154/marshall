# Naming the parts, and the layout that follows

A proposal to mark up. Companion to `SCHEMA.md`: that one is about where FACTS
live, this one is about where CODE lives, and they have the same root cause.

## The layout caused the bug

`director/` is not a design decision. It was a separate repository, merged in by
git subtree on 25 July, and the folder is the seam where the merge happened.

That seam is why `marshall` and the director cannot import each other. Which is
why `_key` was written three times and "bearing between two points" six, and why
`/radar` renders structured rows into English so the other side can parse them
back into structs. **Duplicating was the only thing available.**

So the structure is not cosmetics. It is the thing that makes "one home per
rule" possible or impossible.

## The name

"Director" describes a bundle, not a responsibility. It is currently two
unrelated things sharing a container:

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

**`feed`** -- the sim mirrored into Postgres. The unit stream, `gone`, the
reconciling sweep, `inAir`, land/takeoff, the mission-clock world reset. It
writes `track` and nothing reads through it.
*(today: `director/tools/tracks.py`, `events.py`, `dcs.py`)*

**`atc`** -- the deterministic controller. Separation, the holding stack,
identity resolution, ASR guidance. The part that must never be an LLM's guess.
*(today: `src/marshall/atc/` minus the radio loop)*

**`radio`** -- the voice. SRS transport, STT, TTS, the receive loop, the
synthetic pilots. `srs` is a vendor's name for a transport, not a description of
what this does.
*(today: `src/marshall/srs/` plus `_run_srs` out of `agent_atc.py`)*

**`agent`** -- the Bedrock controller: prompts, conversation, tools, the three
endpoints only it can serve (`/atc`, `/hooks/due`, `/mission/restart`).
*(today: `director/app.py`, `director/prompts/`)*

**`chart`** -- IN-WORLD. The approach plate, the route map, the E6B, the
kneeboard server. Things a pilot flies with.
*(today: `src/marshall/kneeboard/` minus `diag.py`)*

**`diag`** -- OUT-OF-WORLD. The state page: the board, identity and its
authority, releases with the scope at the time, the ghost banner. An engineer's
instrument, not a pilot's.
*(today: `src/marshall/kneeboard/diag.py`)*

**`mission`** -- the `.miz` builder and the AI control Lua. Unchanged.

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
brief mechanism [LAYERS.md] already describes, made per-procedure.

**THE INSTANCE is data.** "Batumi ILS 13": localizer course, glideslope angle,
decision height, the missed approach point, the hold. A row naming its kind.

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

The wind one is worth stopping on. `WIND_FROM_DEG = 180.0` is a hardcoded
constant that the sim will now tell us, and the runway in use is computed from
it. A declared wind is a stored answer to a question with a live input.

### Why `diag` is not part of `chart`

They have different audiences, and this project already draws that line on
purpose: *"engineering is out-of-world, the controller is in-world"* ([#28]).
A plate is a thing a pilot flies with. The diagnostics page is a thing an
engineer watches on a second screen while he does -- it shows identity
authority, released board entries and the scope that contradicted them, none of
which belongs in a cockpit.

Keeping them in one part would be the `director` mistake again: a name covering
two responsibilities that change for different reasons. It also matters for what
each is ALLOWED to know -- `diag` may show that the controller believes
something wrong, which is exactly what a pilot's chart must never do.

"Kneeboard" was never the right name for either. It is the delivery mechanism --
an OpenKneeboard tab -- not the content, the same category of error as naming
the voice layer after the transport it happens to use.

## Deployables are entrypoints, not directories

This is the whole fix. One installable package, several ways to start it:

    marshall-radio     the bridge: voice in, voice out
    marshall-agent     the Bedrock controller behind an HTTP door
    marshall-feed      the sim mirror
    marshall-chart     the kneeboard server

Whether those are three containers or one is a deployment choice, made in
compose, changed without moving a file. What matters is that all four import the
same `core`, so there is one squash, one bearing, one schema -- and adding a
fifth process costs nothing.

`strands_pg`, `_grpc` and `migrations` stay where an upstream stamp can still be
diffed (`diff -r /tmp/fresh-stamp`), because that is a real constraint and not
a naming one.

## What this deletes on the way

  * `/radar`'s prose round trip: `feed` writes rows, `atc` reads rows. The
    English rendering stays for the model and stops being an interchange format
    between our own components. `_SCOPE_LINE`, `_FORMATION`, `_OTHER_SHIP`,
    `flatten_formation`, `_split_ships` go with it.
  * about twelve CRUD endpoints and the HTTP client functions that call them.
  * `director/tools/flights.py` -- 326 lines of SQL wrapped in Python that the
    schema and a session can do.

## Open

SETTLED: `feed`, `radio`, `mission`, `agent`, `core`. `procedure` belongs to
`atc`; `diag` splits out of `chart`.

1. **Does `atc` keep that name?** It is accurate and it is what the docs already
   call it, but it is also the name of the whole product.
2. **One container or how many?** Deployment, not layout, now that entrypoints
   rather than directories define the boundary. `radio+atc` on the voice path
   and `agent+feed+chart+diag` behind it may be the honest middle.
3. **Does `agent` become plural?** Multiple controllers, or multiple fields,
   each with their own conversation -- the part name stays singular either way,
   the same as `radio` covering many frequencies.
