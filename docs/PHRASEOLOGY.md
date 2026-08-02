# Where the controller's words come from

    "I don't know how/where that works today - I hope I can figure it out after
     this refactor."

Fair, and the reason was structural: the words came from four places, in three
different modules, one of which lived inside a container's directory. This is
the map. It describes what is TRUE today, not what should be.

**There are five stages now**, and the fifth is the useful one: everything bound
for a pilot passes through a single table at the radio, which is where
phraseology is finally settled no matter which of the other four composed it.

## The five sources, in the order they get their say

### 1. The engine builds the instruction — `atc/controller.py`

The deterministic half composes actual sentences, not just decisions:

    "hold at BATUMI as published, maintain four thousand"
    "cleared for the surveillance approach runway one three"

They go out as `Tx` objects on `ctl.out`, which `separation_context` joins into
the **directive**. This is the half that must never be a model's invention, and
the words exist so that what it decided survives being spoken.

Numbers are spelled by **`core/say.py`**, not here — `spell_alt(4000)` →
"four thousand" — because a controller says figures and leaving that to the
agent is leaving it to chance. They moved down out of `controller.py` on
2 August so the ATIS module could use them without importing sideways; a second
speller is how a runway gets said one way by the tower and another by the
recording. Six copies of the digit table came out in the same move.

### 2. The geometry builds the guidance — `atc/asr.py`, `agent_atc.asr_call`

`asr_call` and `vector_call` produce the talk-down and the vectors:

    "Sockeye, five miles, turn left heading one zero eight, maintain two thousand"

These are transmitted **directly**, with no model in the loop at all — the
monitor thread speaks them. So on final the controller you hear is not the agent
at all, which is why the agent is told to stop talking (see `rules`, and the
`atc/range` records in the flight recorder).

### 3. The guards speak for themselves — `agent_atc`

The receive loop refuses and corrects before either brain sees a call:

    "Quick four, I do not have you on the board, you are Sockeye, use that
     callsign"

That is `misnamed`, not a controller decision. `strip_unauthorised_handoff`,
the ship-to-ship refusal and `lead_lost_call` are the same category. They are
labelled `guard` in the diagnostics origin legend, because reading a mechanical
correction as judgement is how you misdiagnose the whole turn.

### 4. The agent phrases everything else — `atc/agent/prompts/`

Three parts, assembled in order:

| part | what it is | who writes it |
|---|---|---|
| `soul` | persona, 13 lines, nothing procedural | a human |
| `plate` | THIS mission's facts — field, runway, minima, frequencies | **generated** from `route.py`, pushed live by the radio bridge |
| `rules` | 325 lines of field-agnostic behaviour | a human, accreted |

`plate` is data wearing prose. It is never hand-edited; `briefing.plate(profile)`
renders it and the bridge PUTs it at startup, which is what keeps the plate, the
chart and the engine from disagreeing about the field.

`rules` is the one that has grown without an owner. Its sections today:

    Your radar / Radar identification    correlating a caller to a track
    Formations                            one entity, one clearance
    Frequency changes                     who may hand off, and how it is said
    What you do not know                  the refusals -- no DME, no weather
    Clearance delivery                    a plan on file, read back
    How you work                          brevity, readbacks, the general manner

## What is wrong with this, honestly

**`rules` is a bucket.** 325 lines covering six unrelated subjects, none of
which owns its own words. Adding progressive taxi means appending to it, and
nothing tells you which paragraphs a given procedure depends on — so nothing can
be removed safely either.

**The split between 1 and 4 is invisible at the point of use.** The engine
issues "maintain four thousand"; the agent is supposed to VOICE it. Whether it
did was unknowable until the `voiced` check was added to `/diag`, and scoring a
real sortie found seventeen turns where the engine issued a clearance and
nothing went out at all.

**Nobody owns tone.** `soul` sets a persona; `rules` sets manner; the plate sets
facts; and the engine's own sentences have their own voice baked in. Four
authors, one radio.

*(Partly answered since. Each `Station` carries a `manner` — a sentence, read
off the station beside its voice and injected per transmission — so the eight
controllers sound like eight people. It is fenced hard: manner owns the words
AROUND the numbers and never the numbers, may not decline work or skip a
read-back, and drops entirely if a pilot is in trouble. That fixes who sounds
like whom; it does not fix that four components still compose sentences.)*

### 5. The radio normalises it — `radio/tts.py`

**Added 2 August, and it is the one place phraseology is settled for everybody.**

Every string bound for a pilot passes through `pronounce()` on its way to Polly,
and that table does two different jobs:

    phraseology     three -> tree, five -> fife, nine -> niner
    pronunciation   Sockeye -> "sock eye", Batumi -> "bah-too-mee"

The first of those was going to live in `core/say.py` as ICAO digit words, which
is where a controller's phraseology belongs in principle. **The agent is what
settles it**: it writes its own prose, says "five thousand", and no prompt makes
that reliable — so the transcript and the audio diverge whatever we do. Doing it
in the speller gave "fife" from the engine and "five" from the model in the same
sortie, one transmission apart, which is the worst of both. A test caught it.

So every component writes plain English and this table makes it ICAO on the way
out. One rule, applied to prose nobody in this repo wrote. The cost is that the
transcript keeps the written word while the pilot hears the spoken one — the
documented trade of this table since it was created for "readback".

It also makes phraseology **era-swappable**: a 1944 controller says "five", not
"fife", which is one table rather than a rewrite of every speller. That is the
first concrete piece of the `soul.<era>` work.

## Where it goes

`STRUCTURE.md` settles the direction: **a procedure ships its own phraseology.**

    atc/procedure/ils.py      how an ILS works, AND how it is said
    atc/procedure/asr.py      the talkdown we fly today
    atc/procedure/taxi.py     not written -- and when it is, it brings its words

Then `rules` keeps only what is genuinely field- and procedure-agnostic — the
refusals, the brevity, the readback discipline — and a controller working an
approach is briefed with that approach's words rather than with all of them.

The agent package existing (`atc/agent/`) is the precondition. The split is not
done.
