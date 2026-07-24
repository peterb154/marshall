# Backlog

Deferred work, captured so it isn't lost. Not a promise of order.

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
