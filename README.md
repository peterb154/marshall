# Marshall

Procedural radio ATC, mission generation and kneeboard charts for flight sims.

Marshall makes a flight sim feel like real instrument flying: a blind,
non-radar approach controller that talks to human pilots over
[SRS](https://github.com/ciribob/DCS-SimpleRadioStandalone), missions generated
from a single route definition, and matching kneeboard charts served straight to
the cockpit. It is sim- and aircraft-agnostic — a P-51 beacon letdown and an
F-16 ILS are just different *profiles* driving the same controller.

> Named for the naval **Marshal** — the controller who runs the holding stack
> and pushes aircraft down the approach one at a time. That is exactly what the
> ATC does.

## Why it's built this way

**The controller is blind.** No radar, no telemetry, no connection to the sim.
Its entire world model is what pilots report on the radio, plus a clock. That is
deliberate: the moment it can see you, the navigation stops mattering. You get
exactly the service your flying earns, and separation is by *assigned altitude* —
it holds only if pilots fly their level.

**One route definition feeds everything.** Beacons, frequencies, the holding
stack and the approach live in one place (`core/`). The mission generator and
the chart generator both read it, so a chart can never disagree with the sim.

**The AI is ears and mouth, never the brain.** Speech-to-text and language
understanding turn a pilot transmission into one structured *intent*; a
deterministic state machine decides every clearance. An LLM never invents an
altitude — separation depends on them.

## Layout

```
src/marshall/
  core/        route + per-field ApproachProfile (the single source of truth)
  mission/     .miz generator (pydcs) + terrain survey tools
  kneeboard/   chart generators (nav log, approach plate, E6B) + HTTP server
  atc/         the field-agnostic controller state machine + the intent seam
  telemetry/   (future) live map for spectators
deploy/        docker-compose + env template
tools/         render.sh — screenshot a chart with headless Edge/Chrome
```

## Status

Early. The ATC state machine, the intent parser, the chart generators and the
mission generator all run and are testable in plain text. The SRS voice bridge
(fork of [SkyEye](https://github.com/dharmab/skyeye)'s client), Whisper STT and
TTS are next. See `deploy/` for how the pieces run beside a sim server.

## Docs

- [`docs/DESIGN.md`](docs/DESIGN.md) — architecture, the ATC stack, the approach mechanic
- [`docs/GOTCHAS.md`](docs/GOTCHAS.md) — hard-won, mostly-undocumented traps (pydcs, DCS radio, OpenKneeboard)

## Quick start

```sh
uv sync
cp deploy/.env.example .env        # optional; defaults write into ./build

uv run python -m marshall.atc.controller        # four-ship arrival, in text
uv run python -m marshall.atc.intents           # the intent parser
uv run python -m marshall.kneeboard.plate       # generate an approach plate
uv run python -m marshall.kneeboard.serve       # serve charts for OpenKneeboard
```

Every machine-specific path is an environment variable with a safe default
(`config.py`); nothing personal is baked into the source.

## License

MIT.
