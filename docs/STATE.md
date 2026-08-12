# State — where the truth lives, who owns it, and when it dies

    Type: CURRENT REFERENCE — the diagnosis is current; the target is DESIGN INTENT
    Written: 11 August 2026, after a sortie that went wrong for one reason

> Read this before adding anything that remembers. `DESIGN.md` says what the
> system is FOR, `WIRING.md` what it DOES, `LAYERS.md` what may depend on what.
> This says what may be REMEMBERED, by whom, and until when — which is the axis
> every foundational bug this month has fallen along.
>
> **`CONFIG.md` is its twin and was missing until 12 August.** This document
> owns what the system LEARNS while it runs; that one owns what it is TOLD
> before anybody flies. Nothing claimed the second, so configuration defaulted
> to Python — and `CLAUDE.md` had a sentence calling Python the source of truth
> for exactly the facts that should have been rows.

---

## The complaint that produced it

    "if the whole system requires claude code to keep the database clean, this
     isnt going to work."

    "there really shouldn't be much in memory data structures - we addressed
     this - database is fast and should be the single source of truth ... damn,
     these foundational architecture issues just keep biting us.. they seem so
     obvious to me."

Both correct. The rule was already decided; the code does not follow it, and the
gap is not one oversight but a shape that has produced at least eight separate
faults, several of which cost a flight test each.

---

## The rule, restated

**Postgres is the single source of truth for anything that outlives a
transmission.** It is fast, it is shared by both deployables, and it survives a
restart of either. A process may hold a cache; it may not hold a fact that
nothing else can see.

Three questions have to be answerable for every piece of state:

    WHO OWNS IT      one writer, named. Two writers is how a fact acquires two
                     values -- see #98 (two altitudes), #105 (two verdicts on
                     one read-back), #2 (two ideas of an approach).
    WHERE IT LIVES   a table, or a cache OF a table. Never only a process.
    WHEN IT DIES     every fact has an end. A fact with no lifecycle is not
                     state, it is sediment.

The third is the one nothing in this system answers, and it is what the
complaint is about.

---

## What is actually in memory today

`Controller` (the separation engine) holds:

    aircraft            the entire board -- phase, altitude, approach, clearance
    _letdown_by         who is on each approach
    _broken_up          formations that have split
    anomalies           impossible states, recorded
    working / t         who this seat is, and the clock

`Bridge` holds sixteen more dictionaries: `identity`, `flights`, `seen_at`,
`transmitters`, `order`, `last_heard`, `heard_on`, `awaiting_readback`,
`corrected`, `cleared_plan`, `handoff_due`, `refuse_due`, `decided`, `last_said`,
`last_active_hz`, `releases`.

Some of those are genuinely per-turn and belong in memory — `decided`,
`handoff_due`, `last_said` live and die inside one transmission. Most are not.
`aircraft`, `identity` and `flights` are the controller's MEMORY of who is
flying, and a restart forgets every one of them while the aeroplanes go on
flying.

**The database has the same facts and disagrees with them.** `flights`,
`flight_member`, `identities`, `assigned_plans` and `atis` are all written; none
is read back as authoritative. The bridge writes to `flights` and reads the
board from `Controller.aircraft`.

---

## What has no lifecycle

    flights            NOTHING ever deletes a row. `clear_mission` exists and
                       is called by exactly one thing: a human hitting
                       `DELETE /flights`.
    identities         same.
    assigned_plans     same. A clearance issued last Tuesday is still issued.
    flight_member      same.
    events             append-only by design, which is correct for a log.

Every row is `mission = 'default'`. There is no notion of A SORTIE or of a
mission instance, so yesterday's flights, today's, and a test fixture's all
occupy one bucket for ever.

`player_leave_unit` arrives from the sim, frees the in-memory board through
`Controller.release()`, and **does not touch the row**. That function's own
docstring explains why a leftover is dangerous — *"he flew as Falcon 1-1, came
back an hour later as Pony 1-1, and was assigned ten thousand, held at five, and
banished"* — and the reasoning was applied to the board and never to the table
underneath it.

A mission load wipes nothing. Rows outlive the world they describe.

---

## One table already does this correctly

`tracks` is reconciled to the world on every radar sweep:

    DELETE FROM tracks WHERE NOT (name = ANY(%s))

Whatever the sim no longer has, the table no longer has. Nobody cleans it by
hand, nobody has ever had to, and it has never carried a ghost. **That is the
model.** It works because the feed OWNS the table and reconciles it against
reality continuously, rather than appending to it and hoping.

`flights` is the same kind of fact — who is out there — maintained the opposite
way.

---

## What it cost, on one sortie

A pilot flew Kobuleti to Batumi on 11 August. Three separate complaints, one
cause:

    "ground switched me to tower right after the readback"
    "I've not gotten landing clearance, but I'm landing anyway"
    "I thought I was under my own navigation, then he just gave me 5,000"

His flight produced **three rows in thirty seconds**, none bound to him:

    id 1314  callsign sockeye  srs_name 362nd_sockeye  track 362nd_sockeye
    id 1315  callsign (none)   srs_name Sockeye        track (none)
    id 1316  callsign (none)   srs_name Sockeye        track (none)
    id 1317  callsign (none)   srs_name Sockeye        track (none)

Row 1314 belonged to a REHEARSAL FIXTURE that had used his callsign minutes
earlier and had been despawned. Rows 1315-17 are his: `bind()` matches on
`srs_guid`, `track_name` and `callsign` and **not on `srs_name`**, so a
transmission carrying only an SRS name matched nothing and inserted. Every
transmission minted a fresh row; every `flight_agree` wrote into a row that
identified nobody; the next transmission abandoned it.

So every controller met him for the first time. He had stated his intention —
*"VFR to Batumi, visual 13"* — on his first call and at every handoff, and the
strip that exists to carry exactly that was empty.

**And even bound, it would have been empty.** Nothing on the bridge ever writes
`intent`. The field is read in four places and written by none. `destination`
arrives only as a side effect of a filed clearance.

---

## Why it keeps happening

Every one of these is the same move: **something that was true when there was
one of a thing, and stopped being true.**

    one aerodrome      -> station_for, channels_for, "ABCD"[i], field_origin
    one approach       -> Controller.profile, the stack, the letdown        #2
    one altitude       -> assigned_ft answering two questions               #98
    one judge          -> the agent and the verifier both ruling on a
                          read-back                                        #105
    one authority      -> reconcile arbitrating three of four              #115
    one map            -> the fix catalogue, the radar origin, the magvar  #104
    one sortie         -> flights, identities, assigned_plans              THIS

The reason they feel obvious in hindsight and are invisible in advance is that
**a question with one possible answer cannot be answered wrongly.** While there
is one field, `station_for("tower")` is correct by construction. While there is
one sortie, an append-only `flights` table is indistinguishable from a
maintained one. The bug is not written; it is REVEALED, by a second instance
arriving.

The second reason is order of construction: state was put in memory because that
was the fastest way to make a demo work, and the tables were added later for
durability. Neither was then made authoritative, so both are half-true — and
which one a given reader believes depends on which one it happens to import.

---

## The target

**One writer per fact, a table for anything that outlives a transmission, and an
end for everything.**

### 1. A row belongs to a mission instance

`mission = 'default'` becomes a real instance key — the mission name and the
sim's own start time. A row from a previous instance is not stale data, it is A
DIFFERENT WORLD, and must never be found. This makes mission load a wipe without
anybody deleting anything.

### 2. Leaving the slot ends the row

`player_leave_unit` already arrives and already frees the board. It should free
the row in the same breath. One event, one meaning, both consequences.

### 3. Absence expires it

The belt and braces, and the `tracks` model: a flight with no radar contact and
no transmission for N minutes is gone. Reconciled continuously rather than
deleted on a schedule.

### 4. The board is read from the table

`Controller.aircraft` becomes a cache of `flights` + `assigned_plans`, not the
original. This is the largest of the four and should come last, because the
first three make it safe: there is no point caching a table that lies.

### 5. `srs_name` is a binding key

Weaker than a GUID, stronger than minting a row. One SRS client is one person,
exactly as one track is one aeroplane.

### 6. Intent is written down

A pilot's stated intention — destination, the approach he wants, the runway, VFR
or IFR — is a fact the controller records when he hears it, carried by the strip
and inherited at every handoff. Today it is heard, answered, and forgotten.

---

## What this is not

It is not a rewrite. The tables exist, the schema is close to right, and one
feed (`tracks`) already demonstrates the pattern working in production. What is
missing is a lifecycle and a decision about which copy is true.

It is also not urgent in the sense of "before the next sortie". It is urgent in
the sense that **every hour spent on phraseology, procedures or geometry above
this layer is spent on a foundation that forgets** — and three of the last four
flight tests were diagnosing symptoms of it.

---

## The order I would take it

1. **Lifecycle** (1-3). Small, mechanical, and it makes the board trustworthy.
2. **Binding + intent** (5-6). Small, and it is what the pilot actually noticed.
3. **The board reads from the table** (4). Large. Only worth doing on top of 1-3.

Nothing above this layer is worth building until at least 1 and 2 are done.
