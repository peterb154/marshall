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
*(today: `feed/tracks.py`, `events.py`, `dcs.py`)*

**`atc`** -- the deterministic controller. Separation, the holding stack,
identity resolution, ASR guidance. The part that must never be an LLM's guess.
*(today: `src/marshall/atc/` minus the radio loop)*

**`radio`** -- the voice. SRS transport, STT, TTS, the receive loop, the
synthetic pilots. `srs` is a vendor's name for a transport, not a description of
what this does.
*(today: `src/marshall/radio/` plus `_run_srs` out of `agent_atc.py`)*

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

*(today: `director/app.py`, `director/prompts/`)*

**`kneeboard`** -- the web server. It renders pages from the database and holds
no state of its own. The plate, the route map, the E6B, the plans page, the test
card and the diagnostics page are all PAGES on it, not separate parts.
*(today: `src/marshall/kneeboard/`)*

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

AND THE PLATE IS TWO THINGS, which is worth separating while we are here. There
is the PICTURE the pilot sees -- drawn, and belonging to the kneeboard. And
there is the PROCEDURE that picture depicts -- the fixes, altitudes, courses and
minima ATC needs in order to direct him -- which is static data in the database,
read by `atc.procedure` to fly the approach and by the kneeboard to draw it.
Today one Python object is both, so the drawing and the directing cannot
disagree only because they happen to share a variable.

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
   and `agent+feed+kneeboard` behind it may be the honest middle.
3. **Does `agent` become plural?** Multiple controllers, or multiple fields,
   each with their own conversation -- the part name stays singular either way,
   the same as `radio` covering many frequencies.


## Horizontal parts, vertical domains

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
