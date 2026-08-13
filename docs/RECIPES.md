# Recipes — how to make the five changes that cross everything

    Type: CURRENT REFERENCE
    Validated against: 10 August 2026

`LAYERS.md` says what *may* depend on what. This says what to actually touch,
in order, for the changes that reach across the system — and which of them puts
a new row on the flight test card.

Read [`START_HERE.md`](START_HERE.md) first if you have not.

**The rule under all five:** a fact has one owner, and everything else is handed
it. Most of the bug run this project has been through was one shape — something
reaching sideways for a fact it should have been given. If a recipe below has
you writing the same number in two places, stop; you have found the next issue.

---

## 1. Add an aerodrome

**Owner of the fact:** `core/fields.py` (or `core/nevada.py` for that theatre).

1. **`Field_`** — name, sim `x`/`z`, elevation, the runway's *magnetic* heading,
   and `ends=(designator, reciprocal)`.
   **`ends` is data, not arithmetic.** Do not derive a designator by rounding
   the heading: Batumi's is 124 magnetic and the plate says 13; Tonopah is
   painted 15 and its heading is 141. Rounding gives numbers on nobody's chart.
2. **`magvar_deg` and `grid_convergence_deg`** per field. Zero means "use the
   theatre default", which is right for the Caucasus and wrong the moment there
   are two maps — Nevada is 12°E against the Caucasus's 6.
3. **`lat` / `lon`** — the published position. Not used to fly anything; it is
   what lets `theatre.verify` prove the loaded map is the one we were told.
4. **Survey the terrain.** `tools/survey_terrain.py` for the MVA (what a
   controller may *assign*) and the MSA (published, the pilot's). **Do not
   borrow another field's** — Batumi's cells over Nevada are not conservative,
   they are fiction. Sample at 5° and half a mile: a 10°/1 nm pass missed 400 ft
   at Kobuleti and a peak between two samples is a peak nobody sees.
5. **Stations** in the theatre file, each carrying its `field`. A role is only
   unique *within* an aerodrome; `theatre.station_for` takes a field for that
   reason, and it is the theatre's table — never an approach's (#162).
6. **Add it to `FIELDS`** and to the theatre in `core/theatre.py`.

**Test:** `tests/test_two_fields.py` is the model — every test there names the
plausible wrong answer it prevents. **Card:** yes, if pilots will work it.

---

## 2. Add an approach or procedure

**Owner of the fact:** `core/approach.py` — an `ApproachProfile`.

1. Build the profile: final course (magnetic *and* true), minima, MDA, the
   hold, the fixes it references, and its `AtcCapability` — radar or not, DME or
   not, the phraseology era.
2. **Fixes** go in `core/fixes.py`; the bridge projects them through the sim at
   start, so their positions come from the terrain rather than from a
   flat-earth calculation (7.6 nm out at 50 nm — see `GOTCHAS.md`).
3. Add it to the theatre's `approaches`, and to the director's `approaches`
   table with a migration under `director/migrations/`.
4. The plate is **generated**, not written: `atc/briefing.py` renders it from
   the profile and the bridge pushes it to `/prompts/plate`. Do not hand-write
   procedure into the system prompt — that is the mechanism that keeps the
   agent's words and the chart in step.

**Test:** `tools/asr_sweep.py` flies it a thousand times; beat the recorded
baseline and move it in the same commit. **Card:** yes.

---

## 3. Add or change a kneeboard page

**Owner of the fact:** a `Card` (`kneeboard/card.py`).

1. A page is **a function of a Card**. Everything it may read arrives in the
   Card; nothing it may read is a module constant. `comms.py` is the worked
   example.
2. If the page needs a fact the Card does not carry, add it to the Card — do
   not import `route` inside the page. That is how seven pages came to take a
   `profile` argument and then read the theatre out of module globals anyway,
   which meant they could not be pointed at another field at all.
3. Some pages genuinely *are* the 1944 Caucasus sortie — the beacon letdown
   plate, the squadron brief. Those stay specific **and say so**. What must not
   happen is a page that means to be general and is accidentally specific.
4. **The container generates pages at start.** After any `core/` change,
   `docker restart marshall-kneeboard`, or a pilot flies a mission whose chart
   disagrees with it — silently, from both ends. `deploy_mission.sh` does this.

**Test:** render it. **Card:** only if a pilot must read it in flight.

---

## 4. Change who talks to whom, or what a controller decides

**Owner of the fact:** `atc/phases.py` (the 15-phase table) and
`atc/handoff.py` (`RULES`).

1. **Who has him next is one function** — `agent_atc.next_controller` — over
   three kinds of evidence in priority order: the sim's events, the `handoff.py`
   rule table, then the PostGIS airspace volumes. It was three separate
   mechanisms until 1 August and they disagreed; a pilot found that at 44 nm by
   declaring an emergency. **Do not add a fourth.**
2. **A ground transition is not a rule row.** A phase with no geometry is owned
   outright by the controller `phases.py` names, so moving into it *is* the
   handoff.
3. A distance rule must read the **trend**. `airborne_beyond` ignored direction
   and handed an aircraft 25 nm *inbound* away from the field it was arriving
   at; it is `outbound_beyond` now and a structural test asserts every distance
   rule reads direction.
4. **Separation stays deterministic.** If your change decides who follows whom,
   or how low, it belongs in `atc/controller.py` and never in a prompt.
5. Gate new actions on `atc/reachable.py` — an action must exist in the current
   procedure. A guard that deletes bad output is a referee for something that
   should never have been produced.

**Test:** `tests/test_handoff_rules.py` and `tests/test_phases.py`, both pure
stdlib. **Card:** yes — handoffs are the thing a suite cannot prove.

---

## 5. Change a prompt

**Owner of the fact:** the director's `prompts` table — `soul`, `plate`,
`rules`, assembled in that order (`director/app.py`, `SYSTEM_PROMPT_PARTS`).

1. **`plate` is generated and pushed by the bridge** from the `ApproachProfile`
   at start. Do not edit it by hand; edit the profile.
2. `soul` is manner and identity, `rules` is what the controller may and may not
   do. Procedure belongs in the plate, not in either.
3. **Never move a separation decision into a prompt.** Altitudes, sequence and
   spacing come from `controller.py` and the agent *voices* them. A prompt that
   says "assign a sensible altitude" has broken the invariant.
4. A live edit takes on the next transmission: `/atc` compares the assembled
   prompt against the cached agent and rebuilds when they differ. It did not
   always — a bridge restart without a director restart used to leave the
   controller on the previous mission's plate, right field and wrong altitudes.

**Test:** `tools/atc_dryrun.py` — the same message assembly as the live loop,
typed input, no radio. It is the cheapest way to see whether the agent *voices*
the controller's numbers or paraphrases them. Then
`tools/classify_bench.py` if you touched the intent taxonomy: its wording moves
the score more than the model does.

---

## Before you commit

```sh
uv run python tools/check.py
```

Then: the commit names an issue (`Refs #n` / `Closes #n`), and a
`needs-flight-test` issue is closed by a **pilot**, never by a green suite. If
your change fits no issue, the issue is missing — write it into `ISSUES.md` and
run `tools/file_issues.py`.
