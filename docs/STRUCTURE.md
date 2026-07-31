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
SQLAlchemy models), `procedures` (approaches and fixes, read from the tables).

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

**`chart`** -- the plate, the kneeboard pages, the diagnostics page.
*(today: `src/marshall/kneeboard/`)*

**`mission`** -- the `.miz` builder and the AI control Lua. Unchanged.

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

1. **`feed` or `sim`?** "Feed" says what it does; "sim" says where it comes
   from. I lean `feed`, because `sim` invites anything DCS-shaped to land in it.
2. **Does `atc` keep that name?** It is accurate and it is what the docs already
   call it, but it is also the name of the whole product.
3. **One container or four?** Four is cleaner to reason about and four times the
   compose. Two -- `radio+atc` on the voice path, `agent+feed+chart` behind it --
   may be the honest middle.
