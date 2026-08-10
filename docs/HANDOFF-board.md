# Fix the board join

    Type: HISTORICAL DEBRIEF
    Validated against: a session handoff

> A snapshot of one problem at one moment. Superseded by the identity work; do not implement from it.


One aeroplane has four names in this system and nothing joins them:

| string | where it comes from |
|---|---|
| `Viper 1-4` | the sim's unit name |
| `362nd_sockeye` | the scope label, what the radar picture prints |
| `sockeye` | the identity's callsign — a case-folded handle |
| `Sockeye` | the separation engine's board key — `callsign.parse().canonical` |

Two places join them by comparing strings directly, and both are wrong.

## 1. Every board column is blank

`publish_state` in `src/marshall/atc/agent_atc.py` builds
`track_of = {identity.callsign: identity.track}` and looks up `ctl.board()`
rows in it by exact string. `track_of.get("Sockeye")` misses `"sockeye"`, so the
row gets no track — and with no track there is no type, no hdg/alt/gs, no plan,
and `confirmed` degrades to `claimed` instead of `radar`. `heard_on.get(cs)`
misses the same way, so the frequency is blank too. One failed lookup empties
the whole row; only `phase` and `assigned_ft` survive, because those come
straight from the engine.

## 2. He is dropped off the board every 8 minutes

`release_stale`, same file, refreshes an entry with:

```python
if ac.radar_identified or _key_name(cs) in here:
```

`_key_name("Sockeye")` is `sockeye`. `here` holds `_key_name` of the scope
labels — `362ndsockeye`. Never equal. So nothing ever accounts for him and he
ages out with a live aeroplane on radar at 0.4 nm. It happened **nine times** in
the 30 July sortie; grep `released` in `build/logs/flight-hooks.jsonl`.

This is the serious half. A board entry disappearing while radar can see the
aircraft is a separation fact, and today it prints one line to a log nobody
reads.

## The fix

**One join, used by both.** The identity registry is the only thing that knows
board-callsign → track, because the engine is blind and has never heard of a
track. Extract that join, make it case-insensitive, and have `release_stale`
use it instead of comparing a board key to a scope label.

Consider whether an entry ageing out while its track is on the scope should be
louder than a log line.

## How to verify

Not with a fixture where the strings happen to match. That is how this survived:
`tests/test_scope.py` was written with `label == name`, so the distinction could
not fail, and 831 tests passed either side of a live identity break.

Use the real four names above — they are one contact from the running sim, and
`tests/test_tonight.py` has the fixture. With the sim up:

```bash
curl -s "http://localhost:8000/radar?session_id=hooks" | python3 -m json.tool
cat build/control/state.json | python3 -m json.tool   # what /diag renders
```

## Read first

`docs/LAYERS.md`, then `tests/test_tonight.py` — its docstring is the postmortem
of four faults found by a pilot on the radio in one evening. All four were the
same shape: **a guard reading the wrong input.** The logic was defensible every
time; the input was not what it was assumed to be.

So: when a guard does not fire, print what it is reading before you change what
it does. Three of those four were "fixed" twice before anybody checked the value.

`uv run python tools/check.py` must stay green — ten checks.
