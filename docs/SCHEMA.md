# The schema, proposed

A draft to mark up, not a thing that has been applied.

## The test this has to pass

Not "does Batumi work". **Is the second airfield cheap?**

    "We have multiple airports, and multiple approaches and multiple maps ALL
     that need this. That's why we have to get the fundamentals working so that
     we can BUILD."

Everything below is arranged around that. If adding Kobuleti means writing
Python, the design has failed regardless of how clean the tables look.

## The one line that everything hangs off

There are two kinds of state here and they have been in one pile.

**THE WORLD AS CONFIGURED.** Maps, airfields, runways, approaches, fixes,
stations and frequencies, controllers. Authored or measured once. Survives
everything. This is the half where "cheap to add an airport" lives.

**THE WORLD AS FLOWN.** Tracks, the board, identity, conversation. Wiped
completely when the mission restarts, because it describes a universe that no
longer exists.

Every data bug of the last week was these two being confused: a fifteen-second
timeout applied to a fact that should have been permanent, and eleven-hour-old
tanks kept alive by the same rule that deleted a parked pilot.

## What is MEASURED and what is AUTHORED

This is the part that decides whether the second airfield is cheap, and it is
the part today's design gets wrong -- `BATUMI_ASR` is a Python constant holding
numbers that the sim already knows.

**MEASURED FROM THE SIM. Never typed.** One `Eval` returns every airbase on the
map at once:

    Batumi   | elev 33ft   | 41.60328,41.60928 | rwy 31@54.4
    Kobuleti | elev 59ft   | 41.93211,41.87648 | rwy 25@110.0
    Kutaisi  | elev 148ft  | 42.17915,42.49568 | rwy 25@106.0

  * field position and elevation
  * runway identifier, and its course in the DCS GRID frame:
    `heading = (-course_deg) mod 360`. Batumi returns 54.4 -> **305.6**, which
    is exactly the number `route.py` documents after a night of measuring it.
  * **grid convergence**, which is not a Batumi fact at all -- it is the
    difference between that grid course and the geodesic bearing between the
    two thresholds. Computable anywhere. It is currently the hand-entered
    constant `grid_convergence_deg = 5.74`, and getting it wrong cost a sortie:
    the same runway is 305.6 in one frame and 311.3 in the other.
  * touchdown offset -- half the runway length, currently typed as 0.559 nm.

**SELF-VALIDATING, which is why this is trustworthy.** The runway's NAME checks
the computed course: runway 25 must come out near 250 degrees. An import that
disagrees with the sign convention fails loudly at every field instead of
silently at one.

**DERIVED, NOT AUTHORED: the runway in use.** It is a function of the wind, and
the wind is measurable -- `atmosphere.getWind` at any point and altitude, plus
temperature and pressure:

    10ft: from 180 at 4 kt | 500ft: from 180 at 9 kt | temp 20C  QFE 1012 hPa

Batumi's runways are 13 (125) and 31 (305). Wind from 180 gives 13 a 2.3 kt
headwind and 31 the same as tailwind, so **13 is in use** -- which is what
`route.py` hardcodes as `runway="13"`. It is right today and silently wrong the
first time the weather changes, which is the whole argument: a stored answer to
a question that has a live input is a bug with a delay on it.

So `approach` has no "runway in use" column. It has one row per published
procedure, and which one is ACTIVE is computed per mission from the wind. The
same call gives the altimeter setting, which a controller ought to be reading
out anyway.

**AUTHORED. Procedure design, which no sim knows.** Minima, platform altitude,
hold base, the outer hold fix, the approach kind (asr / ils / ndb), and the
controller capability (radar or not, DME or not). Half a dozen numbers.

So a new airfield is: run the importer, supply six numbers. Not a Python file.

## Tables

### Configured — never wiped

**`airfield`** — one per field per map. `map`, `name`, `icao`, `lat`, `lon`,
`elev_ft`. All measured.

**`runway`** — `airfield_id`, `ident` ("13"), `grid_course_deg`,
`true_course_deg`, `length_m`, `threshold_lat/lon`. All measured. Both frames
stored explicitly and named, because storing one and converting on the fly is
how six degrees goes missing.

**`approach`** — `airfield_id`, `runway_id`, `kind`, `guidance`, `platform_ft`,
`hold_base_ft`, `ceiling_ft`, `mda_ft`, `outer_hold_fix_id`, `capability`.
The authored half. One row per published procedure, for EVERY runway, not just
the one in use -- which runway is active is computed from the wind and is not a
property of the procedure.

**`station`** — `airfield_id`, `role` ("approach"), `name` ("Batumi Approach"),
`freq_mhz`, `also` (roles he doubles). The NAME is what a board's `owner`
points at; a role cannot identify a controller once there are two fields.

**`fix`** — `map`, `name`, `lat`, `lon`, `kind`. Already a table. Should be
scoped by map rather than global.

### Flown — wiped when the mission restarts

**`track`** — what the sim currently has. Exists until `gone` or a world reset;
never expires on a clock. `in_air` from `Unit.inAir()`.

**`aircraft`** — THE BOARD. One row per entity a controller is separating.
`callsign`, `track_name`, `srs_guid`, `owner_station_id`, `intent`, `phase`,
`assigned_ft`, `sequence_no`, `missed_count`, `lead_of`.

  * unique `(mission, track_name)` — one aeroplane, one row. Already enforced
    since migration 012 and never consulted, while Python grew its own version
    and let a Mustang onto the board twice.
  * unique `(mission, callsign)` — added tonight as migration 014.
  * unique `(mission, srs_guid)` — one radio, one aeroplane.

**`identity`** — replaces `contacts`, which duplicates `aircraft` today: both
hold callsign + track + srs_name, one keyed by session and one by mission. Two
tables for one relationship. What is missing from both is the thing worth
keeping: the AUTHORITY (radar / plan / roster) and the reasoning.

### Accumulated — survives a world reset

**`event`** — the sim's own events. Small, structured, and queried in
aggregate: "has `runway_touch` ever fired" was one `GROUP BY`. Keep as rows.

The bridge's transcript recorder stays as JSONL files. The line is **aggregate
-> table, replay -> log**.

## What this deletes

  * `contacts` — folded into `identity`.
  * `flight_state` — a view over `flights`; a third layer to reason about.
  * `route.py`'s airfield constants — become `airfield` / `runway` rows. The
    reasoning in its comments moves to the migration, which is where this
    project already keeps that kind of prose.
  * every in-memory copy: the board dict, `_atc_agents`, and the last of the
    per-aircraft dicts hanging off `Bridge`.

## Decided

**THE SCOPE KEY IS `mission`.** I floated a `sortie` row and could not define
it when asked, which is the answer: "mission" has a precise referent -- the
`.miz` that is loaded and the clock that started with it -- and "sortie" is a
word for a thing that happens inside one. A key nobody can define is a key that
will be used inconsistently.

Everything flown carries it, and a world reset is `DELETE ... WHERE mission =`.
Whether that becomes a `mission` TABLE with cascading foreign keys is an
implementation choice, not a modelling one, and a table is probably right: it
turns "remember to clear this too" into something the database enforces.

**THE BOARD KEEPS NO HISTORY.** A released aircraft is gone, and coming back is
being met as a stranger:

    "Go to untracked and then come back, you get
     'xxx - radar contact - what are your intentions'"

Which is what a controller actually does, and it removes `left_at`, the
`WHERE left_at IS NULL` on every query, and the question of when a row stops
counting. Anything worth keeping about a flight that ended is in `event` and in
the JSONL recorder, both of which survive the reset.

## Still open

**MAP SCOPING** -- the question I asked badly. Concretely: `fixes` is a global
table with no map column, and the configured half above is per-map. Caucasus
has BATUMI and KOBULETI; Syria has none of those and its own; the Marianas
likewise. Because configuration is NOT wiped on a mission change, loading a
Syria mission would leave Caucasus fixes sitting in the table, and a fix lookup
would answer with a point two thousand miles away rather than saying it does not
know the name. That is the same shape as the T-55s: stale rows that look live
because nothing scopes them.

So: does `map` go on `fix`, `airfield` and the rest -- or does the importer
simply own a map at a time and rebuild the configured tables when the map
changes? The second is less schema and more ceremony; the first is one column
and lets two maps coexist. I lean to the column.
