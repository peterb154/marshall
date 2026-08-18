# Marshall

Procedural radio ATC and mission generation for flight sims.

Marshall makes a flight sim feel like real instrument flying: a full radio ATC
service that talks to human pilots over
[SRS](https://github.com/ciribob/DCS-SimpleRadioStandalone), missions generated
from a single route definition, and a live flight-test card and diagnostics
board served straight to the cockpit. It is sim-, map- and aircraft-agnostic — a P-51 beacon letdown at
Batumi and an F-16 ILS into Tonopah are different *profiles* driving the same
controller.

**New here?** Read [`docs/START_HERE.md`](docs/START_HERE.md) first. It is two
pages and it says what runs today, which process decides what, and which
document to believe when two disagree.

> Named for the naval **Marshal** — the controller who runs the holding stack
> and pushes aircraft down the approach one at a time. That is exactly what the
> ATC does.

## Why it's built this way

**Real ATC by default; blind flying is a setting.** A capable, radar-equipped
agent is the controller's brain. *Handicaps* — no radar, no DME, blind
procedural separation, 1944 phraseology — are a per-mission `AtcCapability` you
dial in. The Batumi beacon letdown is one such flavour, not the baseline.

> This paragraph used to say the opposite: *"the controller is blind, no radar,
> no telemetry, no connection to the sim"*, and *"the AI is ears and mouth,
> never the brain"*. That was true early and was left standing for weeks after
> it stopped being — so the first thing anybody read described the inverse of
> the system. Kept visible here rather than quietly overwritten, because a
> README that lies is the most expensive kind of stale document.

**Two brains, and the split is the invariant.** The agent owns language,
judgment, radar-grounded guidance and identity correlation. The deterministic
`atc/controller.py` owns *separation* — the holding stack, one-in-the-letdown,
sequencing. **An LLM never invents separation between aircraft.**

**One route definition feeds everything.** Fields, beacons, frequencies, the
holding stack and the approach live in one place (`core/`). The mission
generator, the chart generator and the controller all read it, so a chart can
never disagree with the sim.

**Nobody issues a clearance that is not his.** Ground clears you *to* the
runway and says hold short; only Tower puts an aeroplane on it. A role is only
unique *within an aerodrome*, which is the lesson the second airfield taught and
the third confirmed.

## Layout

```
src/marshall/
  core/        route, fields, stations, ApproachProfile, theatre (the truth)
  atc/         marshall-atc: separation, procedure, clearances, the board,
               identity, the receive loop, and agent/ — what we ask a model
  radio/       marshall-radio: two-way SRS client, STT, TTS, transmit pool
  atis/        per-field broadcast; decides the runway in use
  feed/        marshall-feed: DCS-gRPC live tracks, events, sim control
  mission/     .miz generators (pydcs) + terrain survey tools
  kneeboard/   marshall-kneeboard: flight test card, diagnostics, docs, planner
services/      a container stack: the language brain's HTTP door and the
               stores (Postgres + PostGIS + pgvector) with their migrations.
               `director/` until 18 August; the compose project is still
               pinned `marshall-director`, which is the deployable's identity
               and deliberately does not follow the folder
deploy/        docker-compose + env template
tools/         render.sh — screenshot a chart with headless Edge/Chrome
```

**The parts are named for what they do, not for the folder they grew in.**
`marshall-radio` (transport), `marshall-atc` (separation and procedure),
`marshall-feed` (the sim mirrored into Postgres) and `marshall-kneeboard` (the
pages) — with the language brain above them. "Bridge" and "director" are
directory names, deprecated as vocabulary; the canonical table, with the layer
each part sits at, is in
[`docs/STRUCTURE.md`](docs/STRUCTURE.md#what-to-call-the-parts).

## Status

Flying. The ATC state machine, the intent parser, the chart generators and the
mission generator all run and are testable in plain text. **The voice path is
built and live** — `marshall-radio` and `marshall-atc` in one host process today
(`marshall.atc.agent_atc`, `marshall/radio/`) — Whisper STT,
Polly TTS and a ten-client transmit pool — and sorties are flown against it on
two theatres, Caucasus and Nevada. See `deploy/` for how the pieces run beside a
sim server, and `docs/WIRING.md` for what actually talks to what.

## Docs

Start with [`docs/START_HERE.md`](docs/START_HERE.md), which lists the rest and
says which one wins when they disagree.

- [`docs/START_HERE.md`](docs/START_HERE.md) — **read first.** What runs today, in two pages
- [`docs/DESIGN.md`](docs/DESIGN.md) — what the system is *for*
- [`docs/WIRING.md`](docs/WIRING.md) — what it actually *does*, organised symptom-first
- [`docs/LAYERS.md`](docs/LAYERS.md) — what may depend on what
- [`docs/GOTCHAS.md`](docs/GOTCHAS.md) — traps that cost real time (pydcs, DCS radio, SRS)
- [`docs/ISSUES.md`](docs/ISSUES.md) — the work, with acceptance criteria
- [`docs/TEST_PLAN.md`](docs/TEST_PLAN.md) — the flight test card a pilot flies

## Quick start

```sh
uv sync
cp deploy/.env.example .env        # optional; defaults write into ./build

uv run python -m marshall.atc.controller        # four-ship arrival, in text
uv run python -m marshall.atc.intents           # the intent parser
uv run python -m marshall.kneeboard.serve       # flight test card, diagnostics, planner
```

Every machine-specific path is an environment variable with a safe default
(`config.py`); nothing personal is baked into the source.

## License

MIT.
