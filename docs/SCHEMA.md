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

## Three causes, not one

An earlier draft of this document said every data bug of the last week was those
two halves being confused. That is not true, and the correction matters, because
these have three different remedies and a schema only fixes one of them.

**1. CONFIGURED AND FLOWN IN ONE PILE.** A fifteen-second timeout applied to a
fact that should have been permanent, keeping eleven-hour-old tanks alive by the
same rule that deleted a parked pilot. *Fixed by the split above.*

**2. IN-MEMORY COPIES MISALIGNED WITH THE AUTHORITY.** `_on_ground` rebuilt from
events instead of asking the sim. The board in a dict while the table that
should hold it took writes nobody ever read. `_atc_agents` holding a
conversation whose rows had been deleted. *Fixed by there being one home for
each fact, which is what moving to the database is for.*

**3. THE SAME LOGIC WRITTEN SEVERAL TIMES, DIFFERENTLY.** *Fixed by neither.*
No schema prevents the fourth copy of a function.

This one is the most dangerous because each copy looks correct in isolation.
The name squasher exists THREE times right now -- `identity._key`,
`agent_atc._key_name`, `kneeboard.diag._key` -- and a fourth lived in the page's
JavaScript until tonight. Two of the three are not the same function:

    identity._key   re.sub(r"[^a-z0-9]", "", s.lower())
    diag._key       "".join(c for c in s.lower() if c.isalnum())

`isalnum()` is Unicode-aware and the regex is not, so they agree on ASCII and
disagree on everything else:

    Jörg      -> "jrg"  vs "jörg"
    Соколов   -> ""     vs "соколов"

An empty key is below `unit_for_radio`'s three-character floor, so a
Cyrillic-named pilot is never identified by the physical chain -- the strongest
evidence in the system -- and falls through to elimination, which works with one
aeroplane up and fails with two. Nobody wrote that bug. It grew in the gap
between two copies of one idea.

The same shape produced the rest of the week: the board join done three ways,
`track_of` fixed while its sibling `auth_of` was missed an hour later, and the
29 July audit's own central finding -- *"a fix gets applied where the bug was
found and not at the sibling call sites, and nothing catches the misses."*

**The remedy is a shared module, and the obstacle is structural.** The bridge
and the director are two deployables that cannot import each other today, which
is exactly why `_key` exists three times in Python and once in JavaScript. So
the shared `models.py` this document proposes should not stop at table
definitions: the derivations that both sides need -- squash a name, take a
handle, turn a label into a board key -- belong beside them, imported rather
than reimplemented.

A schema gives one home to each FACT. This gives one home to each RULE.

### Push it as low as it goes

    "We need to keep things as low as possible. For example, GIS vector
     functions -- those need to be shared. There is no reason an ASR approach
     module is doing any of that math."

The name squasher is the small version. The geometry is the expensive one.
"Bearing and distance between two points" is implemented SIX times:

    picture.range_radial        geodesic -- correct
    agent_atc._range_radial     geodesic -- byte-for-byte the same function
    route.bearing_distance      flat-earth off the sim grid: 5.74 deg out, OPEN
    geometry.bearing_between    flat-earth east/north approximation
    asr.py:426, :449            more flat-earth atan2, inside the approach logic
    PostGIS ST_Azimuth          in the director

Two of those are the same code in two modules, and the copy in `agent_atc` says
in its own docstring that a THIRD one is wrong:

    "The same error is still open on the paper nav log ([#2] and the 29 July
     audit), and this is the shape of the fix."

Somebody found the correct implementation, knew another copy was broken, and
made a second copy instead of one home. That is the whole disease in one
comment. The audit's opening finding -- "the paper nav log is 5.74 degrees out
on every leg, TODAY" -- is the bill for it: 2.39 nm of cross-track error over a
23.9 nm leg, on the chart a pilot flies.

And `atc/geometry.py` already exists. It is the right home and it is bypassed,
which says the problem is not a missing module but a missing RULE about what may
live where.

**The rule.** A module may only implement what is specific to its own subject.
An approach module knows about platforms, minima and intercept angles; it must
not know how to turn two latitudes into a bearing. If it does the math itself,
the math will be a different math.

Concretely, three layers under everything:

  * **geo** -- great-circle range and bearing, projection, grid convergence,
    crosstrack. One implementation, used by the chart, the radar picture, the
    ASR guidance and the nav log alike. Where a frame is involved it is NAMED
    in the signature, because the six degrees between grid and true is what
    cost a sortie.
  * **names** -- squash, handle, canonical callsign, label-to-board-key. The
    fourth copy of `_key` cannot exist if there is one to import.
  * **models** -- the tables above.

All three are BELOW both deployables and imported by both. Today the bridge and
the director cannot import each other at all, which is the structural reason
these copies keep appearing: duplicating was the only thing available.

**The first proof is free.** Delete `agent_atc._range_radial`, point
`route.bearing_distance` at the shared one, and audit finding 1 closes -- the
nav log stops being 5.74 degrees out because there is no longer a second answer
to be out BY.

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

**`map` IS A COLUMN** on `fix`, `airfield`, `runway` and `approach`.

Every map's configuration is present all the time, and the mission picks out the
rows it needs. Nothing is loaded at mission start, so there is no load step to
get wrong, no window where the field is half-known, and two maps coexist without
either being torn down.

The alternative -- one map at a time, rebuilt when it changes -- is less schema
and more ceremony, and the ceremony is the part that gets forgotten. Without the
column, loading a Syria mission leaves Caucasus fixes in the table and a lookup
answers with a point two thousand miles away instead of saying it does not know
the name. The same shape as the eleven-hour-old T-55s: rows that look live
because nothing scopes them.

### The corollary: configuration is LIVE, so nothing may cache it

    "We can edit them anytime, while a mission is going on."

That is a property worth having and it is not free -- it means no module may
hold its own copy. Read through to the table, every time.

**IT IS BROKEN TODAY, in the other half of the same disease.** `_load_fixes` in
the director says so in its own docstring -- *"Once, lazily"* -- sets
`_fixes_loaded = True`, and never reads the table again for the life of the
process. It also merges with `setdefault`, so a second read would not overwrite
what it already had. Edit a fix mid-mission and the controller goes on using the
old one until somebody restarts a container, with nothing anywhere to say why.

`route.py` is the larger version of the same thing: an entire airfield held as
Python constants, which is a cache with a process lifetime and no way to
invalidate it short of a restart.

So the rule for the configured half is the mirror of the rule for the flown
half. Flown state has one home because copies drift. Configured state has one
home because copies go STALE, and a stale approach plate is worse than a missing
one -- it answers confidently.

Where a read per call is genuinely too expensive, the cache carries an explicit
TTL and says so, the way `_filed` does at 45 seconds. What is not acceptable is
a cache with no expiry pretending to be a lookup.

### Measured, so nobody has to argue about it again

300 iterations of each real query, pooled connection, this hardware:

    config lookup (the thing _FIXES caches)        0.071 ms   p95 0.107
    the board (what the bridge reads per turn)     0.086 ms   p95 0.146
    every fix on the map (a whole config table)    0.080 ms   p95 0.123
    the radar picture (PostGIS, heaviest we run)   0.079 ms   p95 0.131

    HTTP hop, bridge -> director -> db             1.389 ms   p95 2.426
    one Bedrock reply, observed the same night     6300    ms

**Seventy-three thousand board reads fit inside one sentence the controller
says.** Even the HTTP path -- sixteen times slower than talking to Postgres
directly -- is four thousand times faster than the model call it sits beside.

Put the other way round: saving one second of latency would take about 11,600
cached reads, and a whole sortie does a few hundred. `_FIXES` saves something
like THIRTY MILLISECONDS across an entire sortie. It cost a night of debugging
and a live outage where the controller quoted a fix it had been told about and
never reloaded.

There are two hard things in computer science, and this project spent a week
proving it can do both at once: cache invalidation -- `_FIXES`, `_on_ground`,
the board dict, `_atc_agents`, and a fifteen-second timeout standing in for a
mission reset -- and naming things, which is one aeroplane with four names and
three functions for squashing them that disagree.

So the rule is not "prefer the database". It is: **a cache must justify itself
with a measurement, and none of ours can.**

### And the director should not be an API in front of its own database

    "I don't think the director should be providing an experience API layer for
     data that could be accessed using a shared schema and direct queries to the
     source."

PostgREST, measured against the same rows on the same box:

    direct psycopg, pooled, in process     0.086 ms
    PostgREST over HTTP                    0.85  ms
    our own FastAPI /flights endpoint      1.34  ms

The hand-written endpoint is the SLOWEST of the three. PostgREST is compiled,
keeps its own pool and marshals nothing through Python, so it beats the code we
maintain -- at the data it serves, a REST layer is not a tax paid for
convenience, it is cheaper than the thing it replaces.

Of the director's 24 endpoints, about twelve are pure data access
(`/approaches`, `/flightplans`, `/flights`, `/fixes`, `/plans`,
`/events/departed`) and about eight are data with a little logic that wants to
be a VIEW or a shared function rather than a handler -- `/flights/due-handoff`
is a join, `/flights/airspace` is geometry, `/plans/resolve` is a naming rule.

Three are genuine capability, and they are the ones only the director can do:
**`/atc`** (the agent, its prompts and its conversation), **`/hooks/due`**
(timers), **`/mission/restart`**. Everything else is the director standing
between two things that could talk directly, and every one of those handlers is
a second place for a rule to live -- which is cause 3 again, wearing a REST
interface.

**THE PROSE SCOPE IS THE WORST CASE OF THIS.** `/radar` renders tracks into
English for the model, and the bridge then PARSES THAT ENGLISH BACK into structs
-- `units_on`, `_SCOPE_LINE`, `_FORMATION`, `flatten_formation`. A
serialise-and-reparse round trip of data that was structured when it left the
database and is structured again when it arrives. Every formation bug this
project has had lived in that parser, including the one that deleted wingmen so
that no member of a formation had a radar position at all.

That parser is not something to fix. If the bridge reads `tracks`, it is
something to DELETE, and [#47] closes with it. The prose stays -- the model
still needs a picture in words -- but it becomes a rendering of the rows, at the
edge, and never an interchange format between our own components.
