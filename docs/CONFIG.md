# Configuration — what the system is TOLD, before anybody flies

    Type: CURRENT REFERENCE — the split and the rule are current; the migration
          of each area to the database is DESIGN INTENT and is tracked in #137
    Written: 12 August 2026, after an audit found a 1944 Mustang sortie
             hard-coded into the speech recogniser

> Read this before adding a constant. `STATE.md` says what may be REMEMBERED —
> what the system LEARNS while it runs. This is its missing twin: what the
> system is TOLD, before a single word is spoken. Between them they own every
> fact that is not a line of logic.

---

## Why this document exists

Two sentences in the repo, both written in good faith, and they disagree:

    CLAUDE.md      core/route.py is the single source of truth
                   (fixes, wind, the ApproachProfile + its capability)

    docs/STATE.md  Postgres is the single source of truth for anything that
                   outlives a transmission

`LAYERS.md` then places `core/route.py` in **Layer 1 — World: what exists, where
it is, what is published**, beside `tracks` and `events`. So the architecture
does not merely permit the fixes and the frequencies to live in Python; it
declares them foundational, and every module above is entitled to reach for
them.

That is why "add an aerodrome" and "add a pilot's callsign" both mean *edit
Python and restart the bridge*, and why an audit on 12 August found:

  * fixes carrying DCS grid metres and no lat/lon, projectable only by asking
    the sim at start-up;
  * a 1944 strike sortie's own turning points published to every controller as
    though they were navaids;
  * the Whisper prompt primed for "Mustang callsigns: Pony one one" while an
    F-16 flew out of Kobuleti;
  * a pronunciation table as a Python dict, so a new pilot is mispronounced on
    the air until somebody edits code;
  * flight plans arriving with the database SCHEMA, in migrations.

`STATE.md` claimed Postgres for STATE and was right. Nothing ever claimed a home
for CONFIGURATION, so it defaulted to code — and code had a document calling it
truth.

    "all of that should be configuration stored in the database, not code ...
     I feel like we are still under-leveraging the database as a source of
     truth"

## The rule

> **Would a different map, era, pilot or flight plan change this value?
> Then it is DATA, and it lives in the database.**

Not "is it a constant". Not "does it change often". `TERMINAL_NM = 25.0` never
changes and is still data, because Nellis and Batumi do not want the same
number — and being a constant is exactly how it came to be 11 nm for a
procedure that starts at 22 (#139).

## The three kinds of fact

| | Lives in | Owned by | Examples |
|---|---|---|---|
| **Reference** — published, citable, changes on a chart cycle | database, seeded from a named source | navaids and fixes, aerodromes, runways, frequencies, approach procedures, magnetic variation, airspace radii and ceilings, pronunciation, recogniser vocabulary |
| **Sortie** — what somebody filed or is flying | database, owned by the pilot | flight plans, private steerpoints, callsigns, who is flying today, which approach he was cleared for |
| **Behaviour** — the rules of controlling | **code**, and tested | separation, the letdown, the phase machine, who owns which clearance, inbound/outbound geometry |

**The line between the last two is the one that matters**, and it was settled
deliberately:

    NUMBERS IN THE DATABASE, LOGIC IN CODE.

So `sectors(field, role, radius_nm, ceiling_ft, floor_ft)` and
`handoff_rules(from_role, to_role, condition, threshold_nm)` are rows, per
theatre, seeded from the procedure they serve. `_inbound_within`, the separation
engine and the phase machine read those rows and decide nothing about their
values. A new map tunes rows; a new RULE is a commit, with a test.

The alternative — the rule table itself becoming rows the engine interprets —
was considered and rejected. It would make the separation invariant into data,
and *an LLM never invents separation between aircraft* is the one sentence this
whole system is built to keep true. A bad row must not be able to reach it.

## What a source is

Reference data is seeded, never authored. Every row should be traceable to
something a pilot could also look at:

    the sim itself      `Beacons.lua` (vendored under vendor/dcs/), and
                        DCS-gRPC for anything positional -- the projection is
                        the sim's, never ours (see `push_fixes` on why: a
                        flat-earth offset was 7.6 nm wrong at 50 nm)
    the plates          DKS, and the AIP they were drawn from
    the mission         its own waypoints, which belong to IT and are not
                        published to anybody else

**Nothing invented gets published.** A name that only one party can resolve is
worse than no name, because it reads as agreement — the finding of #133, and
FEET WET is the same finding one level up.

## Seeding is not a migration

A migration creates the SHAPE. It must not create the CONTENTS.

Migrations 011, 012, 017, 022 and 024 `INSERT INTO flight_plans`, so every
deployment of Marshall anywhere is born believing somebody is flying Kobuleti to
Batumi on the ASR — and #131 was the bridge reading its approach out of exactly
that row. A flight plan is something a pilot files. Seeding belongs in a tool
that can be re-run, pointed at a theatre, and cited.

## Keeping the shape tight, and aligned with the database

    "how do we keep the schema tight and aligned with the database? pydantic?"

Yes, and the reason is not typing — it is that **valid TOML is not valid
configuration**, and the gap between them was silent. Both of these parse
clean and are ignored:

    [recognizer]        the American spelling
    [pronounciation]    a misspelling nobody would see

The bridge then comes up with no pronunciation table and an unprimed
recogniser, saying not one word about either — a plausible file that does
nothing, which is this project's oldest failure shape wearing a new hat.

So every config file is validated against a pydantic model with
`extra="forbid"`, and the error names the file and the key. Every fault at
once, so fixing a theatre is one pass rather than one restart per typo.

**The sections are schema; the values are data.** `[terms]` and
`[pronunciation]` are `extra="allow"` inside, because adding a respelling must
never need a code change — that is the whole point. Adding a SECTION is a
schema change and should be reviewed like one.

### Alignment with Postgres, without coupling the two deployables

Three shapes, and they are deliberately not one:

    pydantic model    the FILE, and the object held in memory
    SQLAlchemy model  the TABLE, for anything that needs SQL
    a test            asserts the two agree, field by field

The bridge and the director are separate deployables with a contract between
them, and `push_fixes` says plainly that they *do not share code*. So a shared
model across that seam would be the wrong kind of coupling — and the repo
already has the right pattern for this: `director/tools/flights.py` duplicates
`PHASES` from `phases.py` with the comment *"Duplicated deliberately: the
director must be able to reject a phase it does not know without importing the
ATC package"*.

Duplicate deliberately, and **test that they agree** — because the failure mode
is drift, and drift is exactly what a test catches and a shared import merely
postpones. Reference data that never reaches SQL (pronunciation, recogniser
hints) needs no table and gets none.

## Where we break this today

Honest, and the list is the audit in #137: `core/fixes.py`, `core/fields.py`,
`core/stations.py`, `core/approach.py`, `core/nevada.py`, `core/theatre.py`,
`radio/tts.py`, `radio/stt.py`, five kneeboard pages binding an approach at
import, and the five migrations above.

`core/route.py` stays — as a **typed reader over those tables**, not as their
author. Its real virtue was never that it held the numbers; it was that the
mission builder, the chart and the ATC all read ONE thing and therefore could
not disagree. That survives the move intact.

## The counter-example, already in the tree

`core/dtc.py` reads a cartridge the pilot exported and derives origin,
destination, route, altitudes and the comms ladder from it. It hard-codes
nothing about which map or which sortie, and works on Nevada and Caucasus
without knowing either exists. That is the shape.
