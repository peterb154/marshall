# Marshall — Design

Procedural radio ATC, mission generation and kneeboard charts for flight sims.
Sim- and aircraft-agnostic: a P-51 beacon letdown and an F-16 ILS are different
`ApproachProfile`s driving the same machinery.

## Principles

**The controller is blind.** No radar, no telemetry, no connection to the sim.
Its whole world model is pilot radio reports plus a clock. Deliberate: the
moment it can see you, the navigation stops mattering. You get exactly the
service your flying earns; separation is by *assigned altitude* and holds only
if pilots fly their level. A false position report cannot be detected — that is
the point.

**One source of truth.** `core/route.py` holds fixes, legs, wind and the
per-field `ApproachProfile`. The mission generator, the chart generator and the
ATC all read it, so a chart can never disagree with the sim. Change a stack
level in the profile and the clearances *and* the plate's table move together.

**The AI is ears and mouth, never the brain.** Speech-to-text and language
understanding turn a transmission into one structured `Intent`; a deterministic
state machine decides every clearance. An LLM never invents an altitude —
separation depends on them being exact.

## The ATC stack

Forced by a single-beacon letdown where aircraft descend *in the hold*, so only
one may be in the letdown block at a time:

- **Enter at the top** — a new arrival takes the lowest free slot above the
  current holders (they fill bottom-up).
- **Step down on vacate** — when the bottom aircraft commences its approach,
  everyone above drops 1,000 ft.
- **One in the letdown** — the next approach is cleared only when the current
  one reports landed or missed (event-based), with a ~12-min timeout so a silent
  aircraft cannot deadlock the stack. Event-based is not slower than a *safe*
  time-based cadence here: the ~8–10 min descent is the real bottleneck.
- **Missed → front of the line** — a go-around climbs below the stack and gets
  the next approach. It is the only clean option: on a single beacon you cannot
  climb from below the stack back to the top through occupied levels, so
  front-of-line means it never has to. (Realistic too — go-arounds get fuel
  priority.)
- **Repeat miss (≥2) → banish** to the outer hold (the departure beacon, whose
  channel is free by the destination) so one aircraft cannot block the field.

Field-agnostic: the procedure is identical everywhere; only the `ApproachProfile`
differs (controller name, beacon, altitude ladder, outer hold). MDA / runway /
terrain are the *plate's* business, not ATC's — it is blind.

## The intent seam (`atc/intents.py`)

Everything upstream — Whisper, Haiku, Nova Sonic — produces one
`Intent{kind, callsign, altitude_ft}`; `dispatch(controller, intent)` drives the
brain. Swap STT or parser without touching `atc/controller.py`; test the brain
in plain text.

**Haiku is the intent parser, for every call — no regex grammar.** Decided after
the first live flight: real pilot speech (free-form, half-garbled proper nouns,
numbers as words) is far too varied for a regex grammar to catch most of it, and
Haiku is <1s, costs a fraction of a cent, and does the thing regex cannot —
*normalise* ("But to me approach" → Batumi Approach, "one one" → 11) before the
Intent reaches the brain. Regex-first was a premature optimisation for a
cost/offline problem we do not have. The invariant is untouched: Haiku is still
only ears — constrained structured output (kind is an enum, altitude a number),
validated before dispatch — and the deterministic state machine decides every
clearance. It never invents an altitude, and separation is by *assigned*
altitude, so a misread *reported* altitude cannot compromise it.

## The approach — a no-DME beacon letdown

Anchored to the real Batumi (UGSB) ILS RWY 12 AIP, flown as an aural-only
procedure because the P-51 has no DME and the real LU NDB is 430 kHz LF (the
AN/ARA-8 cannot steer on it). We put a **scripted VHF homing beacon** at the real
beacon's position and fly the real geometry:

- Hold over the field beacon, racetrack out over the water, inbound on the
  runway heading.
- Cleared, descend to a **platform** on the reversal, then to **MDA — only while
  established on the beam.** A steady tone *is* the proof you are established;
  a broken tone means stop descending. The airplane self-enforces the gate.
- **Station passage** — the cone of silence over the field beacon — is the
  missed approach point. No DME, no timing: the null overhead is the fix.
- This works *only* at a coastal, sea-level field: true altimetry and water under
  the whole approach, so MDA can sit just under the briefed cloud base.
- MDA is **derived from the ceiling**, and the mission weather reads the same
  ceiling, so the sim can never contradict the plate.

The 500 fpm / 240 kt descent limit sizes the inbound beam at ~13.6 nm, which
independently reproduces the real plate's D13.5 racetrack.

## Voice stack (planned)

The hard part is a two-way **SRS client** (DCS-SR-ExternalAudio only transmits) —
fork [SkyEye](https://github.com/dharmab/skyeye)'s Go client. Then Whisper STT
(CPU, short PTT clips) → regex/Haiku intent → the state machine → Piper/Polly
TTS → transmit. Nova Sonic is a later drop-in for STT+NLU+voice, used via
structured output so it emits an Intent, never free speech.

## Topology

```
external Nginx Proxy Manager  (public :443, terminates TLS)
        │ reverse-proxy -> http://<lxc>:80
   marshall LXC  (plain HTTP :80 -> app :8362)
  ├─ kneeboard + flight-planning (FastAPI)
  └─ SRS client / ATC (outbound to the SRS server)
        │ ssh
   dcsserver.epetersons.com        gaming rig (Windows)
   (runs missions, dcs.log)        (DCS client; Edge render; DCS files)
```

Marshall stays deliberately simple: plain HTTP, no TLS or front-door proxy in
this repo. An external Nginx Proxy Manager owns the public name and cert and
proxies to the LXC on :80. Develop on the LXC; deploy with `docker compose`;
test on the DCS server; fly from the gaming rig. GitHub is the sync hub. Public
exposure: static charts under `/kneeboard/` are safe to serve; the
flight-planning app at `/` (it shells out to pydcs and deploys files) must be
behind auth before it faces the internet. The SRS client is outbound-only and
exposes no public port.

## Open questions (need the cockpit)

- **Station passage:** does DCS produce a clean, detectable cone of silence (tone
  null / U-D reversal) as you overfly the scripted beacon? The whole MAP mechanic
  depends on it. ~10-min test with the AN-Beacon-Test rig; if mushy, fall back to
  a timed MAP.
- **Homing sense:** with the station off your left wing, is the first Morse
  element a dit or a dah? Determines the plate's steering annotation.
- **INITIAL fix** is currently offshore (invalid — beacons are on land) and must
  be relocated onto a coastal point.
