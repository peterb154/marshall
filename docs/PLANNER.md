# The flight planner — what to build, and what to import instead

    Type: CURRENT REFERENCE
    Validated against: 10 August 2026

> The flight planner. Phase 1 is built; the rest is a plan and says so.


**Status:** researched 3 August 2026, **Phase 1 built 8 August**. For [UI-1] #22,
which has said "Evaluate Digital Kneeboard Simulator before writing one" since it
was filed. Phases 2 and 3 are open; Phase 2 is blocked on one sample file (§7).

This is that evaluation, and the answer is: **import from it, do not race it,
and build the thing it structurally cannot** — which turns out to be the thing
Marshall actually needs and the thing warbirds actually fly.

---

## 1. What DKB is

Digital Kneeboard Simulator (`digitalkneeboardsimulator.com`) is a mission
planning, briefing and debriefing platform aimed at DCS virtual squadrons. It is
closed-source, web-hosted, and considerably more polished than anything a side
project will produce.

What it does, from its own manual and its author's forum thread:

- Multi-page kneeboards: flight plans, frequency cards, loadouts, threat data
- **Personalised exports per pilot** — each man in the flight gets his own set
- Step-based briefings with an Excalidraw whiteboard
- Tacview ACMI debrief with 3D replay and BVR analysis
- "Realview" live telemetry, and Fox3 server integration

Supported aircraft: **A-10C, AV-8B, AH-64D, OH-58D, F-14B, F-15E, F-16C,
F/A-18C, C-130J.**

Exports: **PNG kneeboard sets, DCS-DTC profiles, TheWay Lua waypoint files,
Loadout Lua.**

There is **no API and no programmatic access**. Everything leaves through a
file the pilot downloads.

## 2. Its WW2 gap is structural, not an oversight

This is the finding that decides the whole question, and it is not what I
expected going in.

Every one of DKB's machine-readable outputs is a **data-cartridge transfer**.
DTC profiles load a nav computer. TheWay Lua feeds a mod that types waypoints
into an INS. Loadout Lua drives a mission script. The supported-aircraft list is
not a list of aircraft somebody liked — it is the list of DCS modules that have
a nav computer to load.

**A DCS warbird has no data cartridge, no INS and no nav computer.** A P-51
pilot navigates with a map, a compass, a clock and a whiskey compass card. There
is nothing for DKB to export *to*. Adding WW2 support is not a feature they
skipped; it is a product that shares a UI with theirs and nothing else.

Which also means: **the artifact a warbird pilot needs is one DKB does not
produce for anybody** — a timed nav log. Course, distance, wind correction
angle, ground speed, elapsed time, per leg. That is the whole instrument. And
`core/route.solve_route` plus `kneeboard/navlog.py` already generate it.

## 3. What Marshall's planner is actually for

The trap here is assuming we need what DKB has. We do not, and the difference
is worth being blunt about:

> **DKB produces a document for a pilot to read.
> Marshall needs a plan for a controller to work.**

A filed plan in this system is an ATC input. It is what lets Clearance say
"cleared to Batumi as filed", what a read-back is checked against, what
`assigned_plans` records when a flight is given one, and what
`tools/check.py`'s "filed plans, resolved" sweep already exercises. None of
DKB's four export formats is a filed flight plan in that sense — they are all
pilot-facing.

**And the database half is already built.** `flight_plans` carries exactly the
ICAO-shaped fields the controller needs:

    name  label  callsign  approach  origin  destination  route  cruise_ft
    task  active

with `route` a list of fix names that must exist in the fix table, `label` the
spoken name a pilot asks for ("Samovar One"), uniquely indexed so no two plans
answer to one name. `assigned_plans` keeps what a flight was actually cleared
on, so relabelling a template cannot retroactively change what somebody was
given. `flight_with_plan` joins it to the live flight.

So the gap in #22 is narrow and precise: **nothing lets a human compose a
plan.** Every plan on file today was authored in a SQL migration.

## 4. The three options

The framing was: import DKB plans and build something simpler for warbirds, or
duplicate DKB's features.

**(c) Duplicate DKB — no.** It is a polished, closed, actively-developed
squadron product with a debrief pipeline and live telemetry. Racing it costs
months and wins nothing, because its output is not what this system consumes.
Worse, it would pull the project toward being a kneeboard designer, which is not
what Marshall is for.

**(a) Import DKB plans — yes, and cheaply.** TheWay Lua is the interesting one:
it is a de-facto interchange format that CombatFlite, DCSPlan and others also
emit, so parsing it buys compatibility with the whole planning ecosystem rather
than with DKB alone. DTC JSON is the second-cheapest and is openly documented by
`the-paid-actor/dcs-dtc`. Neither needs DKB's cooperation and neither can be
withdrawn by them.

**(b) Build our own — yes, but not a "simpler DKB".** Build the *filing*
half: the way a plan gets composed, validated against the fix table, and put on
the board. That serves warbirds and F-16s identically, because a filed plan is
the same object either way. The warbird-specific deliverable is the nav log,
which already exists.

## 5. Recommendation

Three phases, each independently useful, each shippable alone.

### Phase 1 — file a plan without a migration — **DONE 8 August**

`POST /plans` on the director, `/file` on the kneeboard, and
`src/marshall/atc/filing.py` holding every rule — the narrowest thing that closes
#22, writing the row the schema already defines.

Validation is the substance, not the form: a route naming a fix nobody holds
must be **refused at filing time**, because the alternative is a controller
clearing an aeroplane to a place that does not exist and discovering it on the
radio. The fix table is the authority and it is already there.

*Acceptance:* ~~a plan filed through the page is assignable by voice on the
night, survives a mission reload, and a bad route is rejected with the offending
fix named.~~ All three, verified end to end: "Hammerhead" filed through the page,
resolved on two spoken phrasings with no further setup, and still on the board
after a bridge restart.

**The validation is server-side and takes the board as arguments**, so the rules
are tested with no Postgres, no container and no director — the same split
`atis/serve.py` uses for its clock and its radio. What it refuses is the list of
mistakes actually made in the week it was written: a fix nobody holds (named
individually, so a six-fix route says which of the six), a label already on the
board, a label with a spoken number in it, an approach that does not exist, and
deleting the ACTIVE plan out from under the bridge. What it only *warns* about is
judgement: a label that sounds like another, an altitude that is not a round
hundred, and a task repeating its own endpoints — the #57 mistake, caught at the
keyboard now instead of on the radio.

**The page decides nothing.** It asks `/plans/check` while you type and again on
submit, and its route box offers the fixes the director actually holds, so the
typo is a thing you cannot make rather than a thing you are told about. A form
that knew the rules would be a second copy of them.

### Phase 2 — import a planned route

`marshall.plan.importers` with one function per format, all returning the same
intermediate: an ordered list of `(name, lat, lon, alt_ft)`.

- **TheWay Lua** — needs one real sample file to pin the schema. An hour's work
  once we have one, and not before: guessing a format from a forum post is how
  you write a parser that silently drops the last waypoint.
- **DTC JSON** — documented, and `mission/build.py` already writes the F-16
  waypoint block, so the round trip is testable against something we generate.
- **`.miz` route** — free. pydcs already reads it, and it means "plan it in the
  mission editor" is a supported path.

Imported points are snapped to known fixes where they match and carried as
coordinates where they do not. **A plan must never invent a fix name**, because
the controller will say it out loud.

*Acceptance:* a route exported from a third-party planner is on the board and
clearable, with no hand-editing.

### Phase 3 — the warbird planner

Which is the nav log, and mostly exists. What is missing is composition: pick
fixes off a map, set a cruise altitude and a TAS, and get back the timed legs
`solve_route` already computes — course true and magnetic, WCA, ground speed,
distance, elapsed time — rendered onto the kneeboard page `navlog.py` already
renders.

This is the part no existing tool does, for the reason in §2. It is also the
smallest of the three, because the arithmetic has been in `route.py` since the
first sortie.

*Acceptance:* a plan composed for a P-51 produces a nav log a pilot can fly with
no nav computer, and the same plan produces DTC waypoints for an F-16 without
being re-entered.

## 6. What this deliberately does not do

- **No debrief.** Tacview analysis is a different product and DKB is good at it.
- **No loadout editor.** The mission builder owns loadouts.
- **No briefing whiteboard.** One pilot and a controller do not need one.
- **No per-pilot kneeboard designer.** The kneeboard server generates pages from
  `route.py`; a designer would be a second source of truth for the thing this
  project exists to keep singular.

## 7. Open question for the pilot

Phase 2 needs **one real TheWay Lua export** to pin the format. If DKB's free
tier will produce one, that unblocks the whole import path; if it will not, the
`.miz` and DTC routes still stand on their own and the DKB bridge waits.
