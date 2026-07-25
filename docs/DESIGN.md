# Marshall — Design

Procedural + agentic radio ATC, mission generation, and kneeboard charts for
flight sims. Sim- and aircraft-agnostic: a P-51 beacon letdown and an F-16 ILS are
different `ApproachProfile`s driving the same machinery.

> History note: this system began as a *blind, deterministic* controller (no
> radar, a state machine deciding every clearance, an LLM only as ears+mouth).
> Flying it made the case to invert that — see **Principles**. The deterministic
> core did not go away; it became the separation engine and the handicap mode.

## Principles

**Real ATC by default; handicaps per mission.** The controller is a capable,
radar-equipped agent that reasons about the actual situation. A mission can *dial
it back* — no radar, no DME, blind procedural separation, period phraseology — and
the classic 1944 no-DME beacon letdown is just one such configured flavour. This
is data, not a rewrite: `route.py`'s `AtcCapability(radar, dme, separation, era)`
sits on each `ApproachProfile`; the bridge reads it to gate radar and shape the
prompt.

**Two brains.** The **agent** (Bedrock Sonnet, in the strands-pg director) owns
language, judgment, and radar-grounded guidance. The **deterministic core**
(`atc/controller.py`) owns *separation* — the holding stack and sequencing that
must never be an LLM's guess when there is traffic. For a single ship the agent
recites the plate's fixed levels; the moment there are multiple aircraft, altitude
separation is the state machine's job. An LLM never invents separation.

**One source of truth.** `core/route.py` holds fixes, legs, wind, the per-field
`ApproachProfile`, and its `AtcCapability`. The mission generator, the chart
generator, and the ATC all read it, so a chart can never disagree with the sim.

## The agent controller

Runs in the strands-pg director (its own repo/container on the LXC), reached by
the SRS bridge over HTTP (`/chat`). Per pilot transmission the bridge hands it the
transcript plus, when radar is on, a **RADAR** line — every contact as range and
radial off the beacon, altitude, heading. The agent:

- **Reads the scope over the words** — corrects a bad position report, catches a
  wrong turn *before* it's flown ("you're right of course, come left"), gives
  range in lieu of DME.
- **Holds the plate** without inventing levels outside it (hold / platform / MDA /
  missed are the only assignable altitudes; outbound and inbound the only
  headings).
- **Writes radio-plain** — spoken numbers, one transmission, no markdown — because
  its words go straight to Polly. Tools are silent; the transmission is always
  the last thing it emits.
- **Session = one per channel per mission instance.** An open frequency is a
  shared context, never a private per-pilot chat.

## Identity & correlation

One aircraft has **three identities that never match**: the SRS transmitter
("Sockeye", free on every packet), the self-proclaimed callsign ("Pony 1-1"), and
the radar track ("Enfield11"). The bridge tags each call with the SRS identity;
the agent correlates the callsign to a track the real way — a **position report
that matches exactly one blip** — then binds them (`identify`). Tagged, the radar
line reads `Enfield11 [Pony 1-1]`.

Rules, all hard-won: correlate **only** on an unambiguous single match — no match
or two candidates → "not radar identified, continue," never a forced bind. Once
bound, the **track is the truth** (believe the blip over a later contradicting
report). Bindings are **superseding**: a positive re-ID clears any prior link for
that callsign *or* that track, because pilots change jets and jets change pilots
mid-mission. Stored in Postgres (`contacts`), so it survives a restart.

## Radar & the live map

The sim's unit stream (`mission.StreamUnits`) is mirrored into a PostGIS `tracks`
table — upsert on update, delete on `gone`. Radar then reads **one indexed spatial
query** (`ST_Distance` / `ST_Azimuth` off the beacon) instead of fanning out gRPC
on every call, and correlation becomes a natural nearest-neighbour. Freshness is
explicit: every row carries `last_seen`, reads filter on it, and because a
dedicated server **pauses when empty** (the stream then stops), a stale track
reads as *no-contact* — never confidently-wrong. Live gRPC is the cold-cache
fallback. This same table is the god's-eye map.

## Proactive control (hooks)

The agent is request/response — alive only while the pilot transmits, with no
timer. So it never promises a callback it can't keep; instead it calls
`set_hook(seconds, why)`, and the bridge's scheduler re-invokes it when the timer
fires, so "expect clearance in five" is actually paid back. A single lock
serialises hook-driven and pilot-driven transmissions so ATC never talks over
itself. (Later: gRPC telemetry triggers — "wake me when he crosses the beacon" —
against the live `tracks` table.)

## The separation core (`atc/controller.py`)

The deterministic engine, kept for traffic and for procedural-handicap missions.
Forced by a single-beacon letdown where aircraft descend *in the hold* (one in the
letdown at a time):

- **Enter at the top / step down on vacate** — arrivals fill bottom-up; when the
  bottom aircraft commences approach, everyone above drops 1,000 ft.
- **One in the letdown** — the next is cleared only when the current reports
  landed or missed, with a timeout so a silent aircraft can't deadlock the stack.
- **Missed → front of the line** — a go-around climbs below the stack and gets the
  next approach (the only clean option on a single beacon).
- **Repeat miss (≥2) → banish** to the outer hold so one aircraft can't block the
  field.

Field-agnostic: only the `ApproachProfile` differs. The stack itself is
*generated* — `hold_base_ft` + `hold_step_ft` up to `hold_top_ft` — because how
many levels you need depends on who turns up, and the only real ceiling is
oxygen (10,000 ft in a Mustang), not a hard-coded list length.

## Formations

Military aircraft arrive in flights of up to four, and ATC works them as **one
aeroplane** while they are together: one clearance, one altitude, lead answers
for everybody. Talking to four aircraft to move four aircraft wastes a
frequency, and lead — not the controller — owns separation *inside* the
formation.

Modelled by making a joined flight a single `Aircraft` with `members[]`, holding
one stack slot. The entire sequencing core needs no idea formations exist;
break-up replaces one entry with N and from that moment they are ordinary
singles.

**They break up at the holding fix, always.** You do not hold four ships in
formation through a letdown — a holding pattern is minutes of turning in cloud
with three wingmen welded to lead's wing, exactly when lead's attention is on
the plate and the clock. Lead takes the lowest level so he lands first, and the
break-up is announced once, with the levels they will actually fly.

Three consequences worth knowing:

- **Any member who transmits is the flight talking.** This is realism *and* the
  best defence we have against speech-to-text: Whisper hears "one two" for "one
  one" constantly, and without the mapping a single garbled digit forks one
  aeroplane into two entries in the stack, each holding its own level.
- **A formation is one radar contact.** Four blips a mile apart at one altitude
  would otherwise be permanently un-identifiable under the "ambiguous match →
  don't identify" rule. The detector's altitude window must stay well under the
  stack step, or a correctly separated stack reads as a formation.
- **A formation is several SRS transmitters.** Four aeroplanes are four radios,
  so an unfamiliar transmitter claiming a member of a known flight is a wingman
  keying up, not an impostor.

## The approach — a no-DME beacon letdown

Anchored to the real Batumi (UGSB) RWY 12 AIP, flown aural-only because the P-51
has no DME and the real LU NDB is 430 kHz LF (the AN/ARA-8 can't steer on it). A
**scripted VHF homing beacon** sits at the real position and we fly the real
geometry: hold over the beacon, racetrack out over the water, inbound on runway
heading; cleared, descend to a **platform** on the reversal, then to **MDA only
while established on the beam**. MDA is derived from the briefed ceiling and the
mission weather reads the same ceiling, so the sim can't contradict the plate.

**Station passage is the missed approach point — flown on a watch, not a null.**
Flight testing settled it: DCS produces no usable cone of silence, and a crosswind
crabs the homing track off the runway. So the pilot times the final (~3:24 from
established inbound) and, with radar on, ATC backs the timing and monitors the
track. Timed MAP is the mechanism, not a fallback.

## Voice stack (built)

- **Two-way SRS client** (`srs/`) — reverse-engineered from SkyEye's Go client
  (DCS-SR-ExternalAudio only transmits). Registers as an External AWACS client;
  RX decodes Opus + surfaces the sender GUID→name; TX paces Opus frames.
- **STT** — faster-whisper `base.en` on CPU, primed with a domain prompt
  (`srs/stt.py`, the one shared copy).
- **Brain** — the director agent over Bedrock (Sonnet); **TTS** — Amazon Polly, a
  distinct voice per controller.
- **Bridge** (`atc/agent_atc.py`) — STT → radar-inject → `/chat` → strip to
  radio-plain → transmit, plus the hook scheduler, all behind one radio lock.

## Autonomous testing

The whole loop runs headless: a **synthetic SRS pilot** (`srs/pilot.py`, Polly
out / Whisper back) flies a scripted letdown against the live ATC, and **AI
traffic** is spawned (late-activation + `group.Activate`) and *commanded* to fly
real profiles. gRPC can't task AI directly on this build, so the `.miz` embeds a
Lua tasker (`mission/ai_control.lua`) that watches named user flags; gRPC
`SetUserFlag` stages a maneuver (the server must be unpaused). Spawn traffic →
command a profile → radar tracks it → the pilot voices it → the agent controls it,
no human. See `docs/BACKLOG.md`.

## Persistence (Postgres + PostGIS + pgvector)

The director's database is the world state: chat sessions, the seeded prompts
(live-editable via `PUT /prompts`), agent memory (pgvector), the identity graph
(`contacts`), and the live track cache (`tracks`, PostGIS). In-memory spikes
(hooks) still exist; the durable state lives here.

## Topology

```
external Nginx Proxy Manager  (public :443, terminates TLS)
        │ reverse-proxy -> http://<lxc>:80
   marshall LXC
  ├─ kneeboard + flight-planning (FastAPI, :8362)
  ├─ SRS bridge / ATC        (outbound to the SRS server)
  └─ strands-pg director + Postgres/PostGIS  (agent brain, :8000)
        │ ssh + gRPC (LAN only, never public)
   <dcs-server>  (Windows)   — runs missions, DCS-gRPC, SRS server
   gaming rig    (Windows)   — DCS client, kneeboard render
```

Marshall stays deliberately simple: plain HTTP, no TLS in this repo; an external
proxy owns the public name. Static charts under `/kneeboard/` are safe to serve;
the flight-planning app at `/` (it shells out to pydcs and deploys files) must be
behind auth before it faces the internet. gRPC (`:50051`) is LAN-only and never
public. The SRS bridge is outbound-only.
