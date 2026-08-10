# NTTR portability audit — 2026-08-10

## Verdict

The Nevada work is a useful and valuable portability test, but Marshall is **not
ready for the proposed Nellis → range → Nellis ILS sortie** as an end-to-end
ATC workflow. It is ready to demonstrate selected foundations: Nevada field
data, surveyed terrain minima, station ladders, radio presets, and one ILS
profile per field.

It is not yet ready for a reliable IFR departure, enroute/range service, STAR,
or return arrival at the departure field. The highest-risk defects are not
missing values in `core/nevada.py`; they are cases where runtime code still
uses the Caucasus `core.route` module as the active theatre.

No production code was changed by this audit.

## What is genuinely portable and looks sound

- `core/theatre.py` selects a coherent Nevada world: fields, stations,
  approach, bootstrap plan, and bridge flag.
- Nellis and Tonopah carry their own coordinates, runway designators, magnetic
  variation, grid convergence, and 48-cell terrain surveys. This correctly
  exposed that variation and terrain cannot be theatre-wide constants.
- Station lookup is field-aware; the Nevada comms card and mission presets use
  the Nevada station list. `tests/test_nevada.py` exercises those properties.
- `NELLIS_ILS` and `TONOPAH_ILS` are separate data-driven profiles. The ILS
  profile shape is reusable; it is not a Batumi ASR disguised with new numbers.

Those are meaningful wins. They prove that parts of the model were made
parameterised after the two-aerodrome work.

## Findings

### P0 — bridge startup publishes Caucasus fixes on Nevada

`agent_atc.push_fixes()` imports `marshall.core.route as R`, gathers `R`'s
global `Fix` values and `R.sortie_points()`, and projects that set. It adds the
active profile's beacon/hold fixes, but it never selects the current theatre's
published fix catalogue.

On the Nevada profile this happens to add `TONOPAH` via the `TPH` beacon, but
not the Nellis `LSV`/`NELLIS` fix. The filed Nevada plan is
`NELLIS, TONOPAH`; clearance delivery resolves every route name against the
persisted `fixes` table, so a clean Nevada startup can reject the plan because
`NELLIS` was never published. Any old row in the database could conceal that
failure, which is precisely the sort of accidental success this mission is
meant to find.

**Root fix:** make the theatre own an explicit complete fix catalogue (including
field-reference fixes and route/mission fixes). `push_fixes`, STT priming,
flight-plan validation, kneeboard routes, and the mission builder must consume
that catalogue—not reach into `core.route`.

### P0 — Nellis departure has no enroute handoff target

`handoff.RULES` routes an outbound Departure aircraft to `center` at 25 nm.
`NEVADA_STATIONS` contains Nellis and Tonopah stations only: no Center/range
controller is available. `handoff.due()` then gets no station for `center` and
silently returns no handoff. The later PostGIS-sector fallback has no Nevada
sector configuration in this repository.

Therefore a Nellis departure may work through Clearance, Ground, Tower, and
Departure, then remain with Departure once it leaves terminal airspace. There
is no modelled range service to work the requested mission, nor a dependable
return path from enroute control to Nellis Approach.

**Root fix:** model regional/range service as theatre data (stations plus
airspace/handoff ownership), and test the entire controller ladder in both
directions. Do not patch a Nellis-specific exception into `handoff.py`.

### P0 — only one active approach/flight plan can drive a bridge

`Theatre.nevada()` selects `TONOPAH_ILS` as its sole active approach and
`nevada-nellis-tonopah` as its bootstrap plan. `load_and_push_plate()` sets that
plan active and pushes one `plate` prompt. The bridge is explicitly designed to
work one arrival profile at a time.

Nellis has an ILS profile, but a flight that departs Nellis, works the range,
and returns to Nellis needs that profile and its arrival state during the same
sortie. It cannot be selected concurrently with the Tonopah recovery simply
because it is listed in `Theatre.approaches`.

**Root fix:** separate the theatre's procedure catalogue from each flight's
selected arrival procedure. The active procedure must be chosen per flight (or
per controller/arrival stream), not once globally at bridge startup.

### P1 — the proposed mission has neither SIDs nor STARs

This is candidly stated in `core/nevada.py` and `tests/test_nevada.py`: only
one ILS end at each field is modelled; SIDs, STARs, and remaining procedures are
not modelled. The Nevada mission builder supplies waypoints to TPH and the
opposite field, not a published departure, range route, arrival, or STAR.

The current product can provide vectors and a single selected ILS recovery. It
cannot truthfully claim a Nellis SID, a range transit, a Tonopah/Nellis STAR, or
coverage for every procedure on a map.

**Root fix:** introduce a procedure model with typed legs and transitions:
SID, enroute/range route, STAR, approach, missed. The route/flight plan must
choose instances of these procedures rather than carrying only a comma-separated
fix string and one approach key.

### P1 — controller context and speech recognition are still Caucasus-biased

`agent_atc.stt_prompt()` gets fixes from `R.sortie_points()` where `R` is
`core.route`; on Nevada Whisper is therefore primed with Caucasus route names,
not the Nevada theatre/range fixes. The same module-level dependency is what
causes the startup fix-push error above.

The direct radar path is better: `fetch_radar()` redraws structured contacts
from the speaking controller's selected origin. But if it cannot use the local
database or lacks that projected origin, it falls back to the director picture;
the fallback renderer in `feed/dcs.py` and `feed/tracks.py` still uses Batumi
coordinates and a fixed 6° Caucasus magnetic variation. A fallback must be
conservatively unavailable, not confidently wrong on another map.

**Root fix:** pass a `Theatre`/`OperationalContext` through the bridge services;
remove the global fallback origin and variation. If no valid origin is
available, return structured contacts without a controller-relative rendering
and suppress range-dependent guidance.

### P1 — mission validation is still hard-coded to the 1944 Caucasus sortie

`mission/validate.py` always opens `362nd-Blind-Flying.miz`, requires theatre
`Caucasus`, expects P-51/SCR-522 constraints, and validates `route.FIXES`.
It cannot validate the Nevada F-16 mission. The normal quality gate therefore
does not prove that the mission a pilot will fly is structurally valid.

**Root fix:** parameterise validation by a mission/theatre specification and
run it for every supported theatre in CI. The Nevada mission should have a
first-class build-and-validate test, not only data-module tests.

## Expected result for the next sortie

| Segment | Likely result today |
|---|---|
| Nellis ramp through Tower | Promising; station/radio data are present. |
| IFR clearance | At risk of rejection on a fresh database because `NELLIS` is not published as a fix. |
| Departure to range/enroute | Not ready; no Nevada Center/range station or sector/handoff model. |
| Return arrival/STAR | Not implemented; no STAR or per-flight return procedure selection. |
| Nellis ILS | The profile exists, but is not the bridge's active Nevada recovery; a Tonopah-selected bridge cannot reliably run it for the return. |

## Recommended order

1. Fix the root theatre-context leak: one theatre-owned catalogue of fields,
   fixes, stations, procedures, and regional controllers; eliminate runtime
   `core.route` imports from Nevada-capable paths.
2. Add a deterministic two-direction Nevada integration test that proves:
   fix publication, plan validation, controller ladder, origin-relative radar
   rendering, and both Nellis and Tonopah procedure selection.
3. Model Center/range airspace and handoffs as theatre data, then fly the
   Nellis outbound/return boundary before adding more phraseology.
4. Add a typed procedure graph for SID → enroute/range → STAR → approach.
   Start with one Nellis SID, one range route, one Nellis STAR, and the existing
   ILS; make every later procedure data rather than a controller-code branch.
5. Parameterise mission validation and test each generated mission artifact.

Until steps 1–3 are complete, use NTTR as a smoke test for the field/ILS data,
not as evidence that Marshall can yet control the full proposed sortie.
