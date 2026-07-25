# Backlog

Deferred work, captured so it isn't lost. Not a promise of order.

## Formations debrief — 2026-07-25 (first four-ship, live AI + synthetic pilots)

Formations shipped and were flown against real AI traffic on the server. What
the runs actually taught us, worst first:

1. **The controller narrated its reasoning over the air.** With extended
   thinking disabled the model reasons in the OUTPUT, and Polly read all of it
   to the pilot in the controller's voice: *"This is a different transmitter, a
   wingman, reporting his level. He's holding, not yet identified
   individually..."* Prompting alone did not hold it. Fixed with a `RADIO:`
   marker — the bridge transmits only what follows the last one, so thinking has
   somewhere to go that is not the frequency. **This is a general hazard, not a
   formation one:** any prompt change that invites deliberation can put it on
   the air, and only the marker stands between the two.

2. **The identity rules made formations invisible to radar.** "Two candidates →
   do not identify" means four aeroplanes on one wing can *never* be radar
   identified — the bigger the formation, the less the controller sees it. Radar
   now collapses a tight group into one contact and the ambiguity rule is
   explicitly lifted for it. Watch the threshold: the altitude window MUST stay
   under the stack's 1,000 ft step, or a correctly-separated stack reads as a
   formation and the controller is told four aircraft he just separated are one.

3. **The SRS roster died silently.** `_drain_tcp` caught only `OSError`, so one
   malformed message ended GUID→name tracking for the whole session while the
   socket kept draining and calls kept working. Two wingmen logged as raw GUID
   stubs. It fails precisely for late-joining clients — which is what a
   formation is made of. Hardened, but the lesson generalises: **every
   background thread in the voice stack needs a catch-all, because its failure
   mode is silence, not a stack trace.**

4. **The prompt was the bottleneck, not the model.** Both Haiku and Sonnet read
   "level five thousand" as a check-in because the enum was *named*
   `report_beacon` and nothing said a bare level report was the same event.
   Spelling the taxonomy out in the schema: Haiku 11/17 → 16/17, Sonnet 12/17 →
   17/17. Reach for the wording before the bigger model. (`tools/classify_bench.py`)

5. **Structured output is not a guarantee.** Given an exhaustive seven-value
   enum, Sonnet still returned `report_approach`. `IntentKind(...)` raised, the
   bridge swallowed it, and the controller fell silent with an empty directive.
   Anything that turns a model's string into an enum needs a `coerce`.

6. **pydcs names units `<group> Pilot #n`,** not `<group>-<n>`. The assumption
   that a group called "Pony 1" yields units "Pony 1-1".."Pony 1-4" was wrong;
   they are renamed explicitly now. Radar labels still come from the DCS
   *callsign* (Enfield11…), which is deliberate — correlation is meant to be
   earned from a position report.

7. **Polly's newer voices are neural-only** and reject the standard engine with
   a `ValidationException`, killing a rehearsal at whichever synthetic pilot drew
   one. Falls back and remembers.

8. **Collapsing the formation switched the separation engine off.** The bridge
   engages the deterministic controller at ≥2 radar contacts, and it counted
   radar *lines*. The moment a four-ship became one line it counted as one
   contact, so the engine stayed off for the arrival that most needs sequencing
   — caught live, by a missing `CONTROLLER:` line. It counts ships now. **Any
   change to the radar picture's format is a change to a control-flow input.**

### Open, and the interesting one: radar vs. the blind engine

A pilot reported "over the beacon" while radar showed him **eight miles out**.
The agent correctly refused — *"negative, radar shows you eight miles northwest
of the beacon, continue inbound"* — but the deterministic controller had already
acted on the false report and **broken the flight up**. The two brains now
disagree about the world: the engine thinks four aircraft are stacked, the agent
told them to keep coming.

The engine is blind by design, so it cannot catch this itself. The fix belongs
in the bridge: **validate a position report against radar before feeding it to
the controller**, and drop or flag the ones the scope contradicts. Until then a
lying (or lost, or garbled-by-Whisper) position report silently corrupts the
separation state. This is the most important thing left open from tonight.

### Also deferred

- **The AI cannot actually fly the break-up.** A DCS group is tasked as a whole
  and wingmen follow lead, so the four-ship flies as one and the break-up is
  driven from the radio by synthetic pilots. Fine for testing the controller;
  if we ever want the AI to really split, it needs four single-ship groups.
- **`director/` has no tests.** The formation clustering was validated by hand
  through `docker exec`. It wants a test harness that can import `tools/`
  without Postgres — the two real bugs in it were found by poking, not by a
  suite.
- **Rejoin after a missed approach.** A broken-up member that goes around stays
  a single forever; it never rejoins its flight. Probably correct, but unstated.
- **Trail-spacing break-up** as an alternative to the altitude stack (more
  period-correct for 1944; needs timing machinery the engine does not have).

## Flight-test debrief — 2026-07-24 (first live voice ATC + beacon approach)

1. **No cone of silence, confirmed.** DCS produces no detectable station-passage
   null. The timed MAP (ApproachProfile.final_approach_sec, pilot flies a watch +
   ATC backup) is THE mechanism, not a fallback. Settled.

2. **Crosswind breaks beacon-homing alignment (the big one).** The ARA-8 *homes*
   -- it points the nose AT the beacon. In no wind that also lines the nose up
   with the runway, which is the whole premise. But in a crosswind, homing gives a
   *curved* ground track (you get blown downwind and keep turning in), so you
   arrive over the station NOT aligned with the runway -- and at MDA the runway
   isn't in front of you. To fly a straight track you must CRAB, but then the
   homing needle isn't centred and the ARA-8 doesn't show you the track. So the
   approach as designed is really only valid in light/aligned wind. Options: brief
   a wind-corrected inbound course; make the first mission light-wind and treat
   crosswind as an advanced condition; or accept it as brutally realistic. This
   also compounds #3 below (wind entry) -- the 270/20 both floats the landing AND
   crabs the tracking.

3. **Latency is the top system problem.** Agent-in-the-loop responses ran 20-30s.
   Fix is the core design: the deterministic state machine (atc/controller.py)
   must answer the routine 95% *instantly* (intent -> clearance -> TTS, no LLM),
   and the LLM/agent is invoked only for the unusual calls. Wire the intent seam
   -> controller -> TTS as the fast path; converse.py's readback and atc_session's
   hand-flying were the slow stand-in.

4. **Mission SCR-522 presets did not match the ATC/route frequencies.** The pilot
   came up on 105 MHz, not A/B/C = 124/128/132. Verify the loaded .miz actually
   carries the route.py freqs as its SCR-522 channel presets (write_presets), and
   that ATC, plate, and the in-cockpit radio all read the one source of truth.

5. **Single-radio homing (already captured above):** confirmed in flight -- can't
   switch stations independently, so the letdown controller lives on the beacon
   frequency.

## Wind favors the reciprocal of the approach runway

Surfaced by flying (2026-07-24): briefed wind is `WIND_FROM_DEG 270 / WIND_MPH 20`
but the approach lands **runway 12** (course 120). 270 vs 120 is ~150 deg off --
a right-quartering **tailwind**, so a break-out can still float long and force a
go-around in clear weather (which happened). Options: (a) set the wind to favor 12
(from ~120), (b) fly the approach to the reciprocal (30) when the wind is westerly,
or (c) leave it as a deliberately hard, realistic condition. Decide and encode in
`route.py` -- and note the wind is single-source (mission weather + nav log + ATC
wind-check all read it), so changing it moves everything together.

## Controller outputs must be frequency-tagged (single-radio homing constraint)

Surfaced by flying (2026-07-24): the SCR-522 is a **single-channel** radio, and
the ARA-8 homes only on the frequency it is tuned to. So to home on the BATUMI
beacon (132.0) the pilot MUST be on 132 -- he cannot simultaneously be on
"Batumi Approach" (128.0). Therefore the letdown/final control -- the
`report beacon inbound` and the timed station-passage/missed call -- must be
transmitted on the **beacon frequency (132 = Tower)**, not on Approach's 128.

**The key principle: a phase's controller frequency = the beacon the pilot homes
on in that phase.** The current channel scheme already encodes this --
124/KOBULETI (Departure), 128/INITIAL (Approach), 132/BATUMI (Tower) -- each
controller sits on the beacon flown in that leg. So the pilot never has to choose
between homing and talking; the controller is *on the beacon he's already tuned*.

The bug is only in the controller's flow: `atc/controller.py` runs the **entire**
letdown (beacon-inbound report + timed MAP + landing) as "Batumi Approach", but
that letdown is homing on the BATUMI beacon = **132/Tower**, not 128. Correct flow:
- **Approach (128 = INITIAL beacon)** -- enroute/sequence to the BATUMI beacon,
  then hand off: "contact Tower one three two".
- **Tower (132 = BATUMI beacon)** -- the whole approach: hold, letdown,
  beacon-inbound, the timed station-passage/missed call, landing. The pilot stays
  here start to finish because he's homing on this beacon.

So `say()` outputs need a **target frequency** from the aircraft's phase, and the
`ApproachProfile` should map phase -> controller frequency (which is just the
relevant fix's freq). `atc_session` already proves one client holds all three; the
brain just has to emit each output on the right one.

## Scriptable AI control — BUILT + PROVEN (extend maneuvers as needed)

Give AI units live instructions — fly an approach, orbit, vector — for scripted
test traffic, forcing ATC interactions with no human, and the director's
"spawn/command" vision. Working as of 2026-07-25.

**Why it isn't gRPC-native** (verified, so don't go looking again): the
`controller` service exposes only `GetDetectedTargets` + `SetAlarmState` (no
`SetTask`); `hook.Eval` runs in the GameGUI env where `Group`/`Unit`/`a_do_script`
are nil; `net.dostring_in('mission', …)` also has no `Group`. `Controller:setTask`
lives ONLY in the mission scripting env (MSE).

**The mechanism (implemented):** the `.miz` embeds `mission/ai_control.lua`
(appended to the generated beacons DoScript, so it runs in the MSE). It watches
**named user flags** and tasks groups on them. Drive it from outside with gRPC
`trigger.SetUserFlag(flag="ai_inbound", value=1)` (flags are STRING-named). The
tasker polls, consumes the flag (the flag reset to 0 is the proof it ran), and
calls `Group:getController():setTask{...}`. Spawn/enable traffic with
late-activation + `group.Activate` (already wired: `build --traffic` /
`call_in_traffic`); the server must be unpaused (`hook.SetPaused(false)`) or the
sim is frozen and tasks never process.

**Proven:** flag-commanded `ai_inbound` broke `Traffic` off its orbit into a
steady descending inbound — radar range 4.3→2.7 nm, alt 3,200→1,750 ft, heading
locked ~213 on the beacon.

**To extend:** add entries to the `MANEUVERS` table in `ai_control.lua`
(`ai_orbit`, `ai_missed`, `ai_hold`, …) — each a flag-triggered `setTask`. Next
step when wanted: a director tool `command_ai(maneuver)` so the harness/agent
stages scenarios by name instead of raw flags. Route points are `{x=north,
y=east}` = `{fix.x, fix.z}`.

## Two-brain latency: the separation classify on the hot path

Surfaced by the multi-ship rehearsal (2026-07-25). With traffic, every pilot call
runs a Haiku intent-classify (~0.5-1s) BEFORE the Sonnet agent reply, to drive the
deterministic Controller — replies climbed to 5-8s. It must be synchronous (the
current report has to affect the current reply), so it can't just be backgrounded.
Options: (a) for real missions, aircraft are sim units on radar, so gate the
classify on radar showing >=2 contacts (single ship stays on the fast, classify-
free path); (b) trim the growing /chat session history; (c) a cheaper/smaller
classify. Not broken, just slow under traffic; single-ship is unaffected (the
classify only runs once a stack exists). Note: the voice-only rehearsal can't use
the radar gate (synthetic pilots aren't tracks) — hence the always-classify path.

Also from the rehearsal, deeper follow-on: **proactive "you're now cleared."**
When the aircraft ahead lands, the Controller clears the next one, but that's a
transmission to a pilot who didn't just call — it needs the hook/telemetry
proactive-TX path, not the reply-to-caller flow. Today the next ship gets its
clearance when it next keys up (handled: request_approach re-affirms a cleared
aircraft instead of re-holding it).

## Approaches (static) + flight plans (dynamic) in the database

Wanted (surfaced 2026-07-25). Two separate concerns, both bound for Postgres:

- **Approaches = static reference data.** A published procedure for a field —
  beacon, runway, altitude ladder, headings, timing, `AtcCapability` — reusable
  across missions. Today this is the `ApproachProfile` constant in `route.py`;
  graduate it to a DB `approaches` table (a library). **Define the Batumi NDB
  approach first.**
- **Flight plans = dynamic per-sortie data.** Which flight (callsign, aircraft),
  what route, what weather, and *which approach* it flies — a row that references
  an approach. This is what a mission is; today it's baked into `build.py`.

The plate generator (`atc/briefing.py`) is the foundation: it already treats the
approach as data and renders it to the agent's prompt. Next step is to read the
`ApproachProfile` from the DB (loaded flight plan → its approach) instead of the
`route.py` constant, so the mission builder, the chart, and the ATC all read one
DB-backed approach. `route.py` stays the geometry source until then.

## Agent ATC: de-hardcode from Batumi / P-51 (generalize per mission)

Surfaced 2026-07-24 building the agent controller. The working Batumi Approach is
**over-fit**: the plate values (headings 300/120, levels 4000/2000/300, timing
3:24, runway 12), the callsign "Pony 1-1", and the beacon lat/lon are all
hand-written into the agent prompt (`marshall-director/prompts/`) and
`tools/dcs.py` (`BATUMI_LAT/LON` for the radar picture). Fine for one field; wrong
as a pattern.

The clean path: **generate the controller's soul/rules and the radar reference
fix from the single source of truth** -- `core/route.py` (ApproachProfile already
holds beacon, runway, platform/ceiling, final_approach_sec) and ultimately the
loaded `.miz` (flight callsign, SCR-522 presets, field). So spinning up "Kobuleti
Departure" or a different airframe is data, not a prompt rewrite. Radar's field
anchor should come from the same place (route.py beacon coords -> lat/lon), not a
constant. Until then: one good Batumi Approach, hand-tuned.

## Event-driven agent: gRPC telemetry triggers (proactive ATC)

Surfaced 2026-07-24. The agent is **reactive** -- it only runs when the pilot keys
the mic, has no timer, and cannot wake itself. That's why "expect further clearance
in 5 minutes" is a lie it can't honor (mitigated in the prompt: never promise
self-initiated action, always hand the pilot the next trigger). The real fix is an
**event loop**: stream DCS-gRPC telemetry (positions we already read for radar),
let the agent set triggers ("when Pony 1-1 crosses the beacon / reaches platform,
wake me"), and transmit **unprompted**. Radar eyes + triggers = a controller that
volunteers the next call instead of waiting to be asked. Pairs with the two-brain
split (deterministic sequencing + agent judgment).

## OpenKneeboard: split doodle pages from clickable pages

OpenKneeboard's Web Dashboard defaults to **mouse emulation** — the tablet pen
acts as a mouse (click links, press the page buttons, scroll). That is
**mutually exclusive** with the doodle/ink layer you get on PDFs and images: a
page can be clickable *or* drawable, not both.

Flipping to draw-on-top is per-page, via the experimental cursor-events API, and
it **disables all interaction** (including scrollbars), so it only suits
single-screen content:

```js
await OpenKneeboard.EnableExperimentalFeatures([
  {name: "DoodlesOnly", version: 2024071802},
  {name: "SetCursorEventsMode", version: 2024071801},
]);
await OpenKneeboard.SetCursorEventsMode("DoodlesOnly");
```

**Implication for our tabs:**
- **E6B** must stay **clickable** (its buttons/inputs) → mouse emulation, no doodles.
- **Charts / tables (briefing)** want **doodles** (annotate the plate) → DoodlesOnly,
  single-screen, no scrolling.

So these belong on **separate pages** with different cursor-events modes — the
E6B can't share a doodle-enabled sheet. `kneeboard/site.py` builds the multi-page
tab; the mode would be set per section when that section is shown. Note the
`SetCursorEventsMode` version stamp differs from `PageBasedContent`.
