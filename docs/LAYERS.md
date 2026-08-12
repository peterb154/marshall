# Layers — what stands on what

    Type: CURRENT REFERENCE
    Validated against: 10 August 2026

> What may depend on what. The dependency rule and the stages of a turn are CURRENT; the brief mechanism and the extraction plan later in the file are DESIGN INTENT, and the honest list of where we break the rule today is current.


`DESIGN.md` says what this is **for**. `WIRING.md` says what it **does** today.
This says what may depend on what, so complexity can be built on foundations
that are already trusted rather than beside them.

Written 30 July 2026, after three days in which most of the bugs turned out to
be one shape: **something reaching sideways or upward for a fact it should have
been handed.**

---

## The one rule

> **A module may depend only downward.**

That is the whole thing. Everything below is either a consequence of it or an
honest list of where we break it today.

A useful corollary, because it is the version that catches real mistakes:
**if a layer has to parse, guess at, or re-derive something a lower layer
already knows, the dependency is pointing the wrong way.**

---

## The stack

Each layer must be testable **without the layer above it**. That is the test of
whether the boundary is real, and it is why the unit suite runs in under six
seconds with no sim, no network and no model.

| | layer | owns | today |
|---|---|---|---|
| **7** | **Surfaces** | kneeboard charts, the plate, `/diag`, these documents | `kneeboard/` |
| **6** | **Language** | turning decisions into English and back. Owns nothing it says | the director agent, prompts, `context.py` |
| **5** | **Procedure** | what a controller DOES: approaches, clearances, handoffs, the ground | `handoff.py`, `phases.py`, `asr.py`, `decision.py`, `phrasebook.py` |
| **4** | **Control** | separation. The board, the stack, sequencing | `controller.py`, `geometry.py` |
| **3** | **Membership** | who is flying with whom | `flights.py` |
| **2** | **Identity** | which radio is which aeroplane is which person | `identity.py` |
| **1** | **World** | what exists, where it is, what is published | `tracks`, `events`, the catalogue tables read through `core/route.py`, `atis/` |
| **0** | **Transport** | audio, frequencies, GUIDs, client names. No aviation | `radio/client.py`, `radio/pool.py`, `radio/stt.py`, `radio/tts.py`, `core/say.py` |

**`decision.py` is the seam between 5 and 6.** The engine decides; the agent
says. A decision is verifiable and a sentence is not, which is what lets the
bridge check mechanically that the pilot heard the number the engine chose —
`phrasebook.py` is the fallback renderer for when he did not. Moving the prose
out of `controller.py` is in progress: 5 of 32 sites converted, and the
remaining 27 behave exactly as they did.

**`atis/` sits at layer 1 and that is the point of it.** It observes the world,
decides the runway in use, and writes it down; controllers at layer 4 and 5
*read* it. The runway is a decision with one author — two callers computing it
from the wind agree only while they read the same wind at the same instant.

**The radio is one ear and ten mouths.** `radio/client.py` listens on every
frequency and never transmits; `radio/pool.py` holds the clients that speak,
serialised per frequency rather than globally. Neither knows what an aerodrome
is — a frequency is a number to them, which is what makes layer 0 layer 0.

**`core/say.py` is layer 0** — pure text, no aviation. How a number is said out
loud, so `atc/` and `atis/` can both use it without either importing the other.
That is the whole reason it exists: ATIS is a sibling of ATC, not something
underneath it.

**The good news, and it is genuinely good:** the bottom is already sound.
`core/route.py` (2,047 lines), `identity.py` (547) and `flights.py` (403) each
depend on **nothing**. They are real layers with real
tests. Nobody has to be talked into this architecture; most of it is built.

**The bad news is one file.** `atc/agent_atc.py` is 6,656 lines (3,688 when this
was written on 30 July — it has not stopped growing) and imports from
L0, L1, L2, L3 and L4. That is what an orchestrator does and it is fine **if it
is thin**. It is not thin. It is where the work happens, and until 30 July no
test executed one line of its receive loop — which is not a coincidence, it is
the definition of the problem.

---

## The turn

The missing layer is not a noun, it is a verb. Every concept here got a module
except **the turn itself**, so the turn became a file.

A turn is a pipeline. Each stage is a function with a signature, testable with
fixtures:

```
hear        audio                → transcript + which radio
attribute   transcript + world   → identity, or a refusal with a reason
admit       identity             → is this a real transmission from a pilot
read        transcript           → intent   (closed sets first, a model second)
decide      intent + board       → instructions        ← deterministic
brief       state                → what the controller needs to know right now
compose     instructions + brief → words               ← the model
speak       words                → audio, on the frequency it arrived on
record      everything, always
```

**The invariant stops being discipline and becomes shape.** `decide` cannot call
`compose`, so the model structurally cannot invent an altitude — it can only
phrase one that was decided.

**A turn is not always a pilot.** The ASR metronome and the hook scheduler are
independent *drivers* that produce turns: a mile call, a promised callback.
They are not stages, and treating them as such is what makes the `fetch_radar`
call count confusing today.

---

## Briefs: context on demand

> "why would EVERY request get procedure info about ILS to the system prompt"

It should not, and today it does. Measured 30 July: **`rules.md` is 18,067
characters — about 4,500 tokens — sent on every single transmission**, plus the
plate, plus ~2,500 characters of per-call injection.

| section of rules.md | chars | actually applies |
|---|---|---|
| How you work | 7,696 | partly invariant, mostly procedure |
| Radar identification | 3,443 | while a correlation is outstanding |
| Formations | 2,456 | when a flight exists |
| Clearance delivery | 2,464 | at the ramp |
| Your radar | 1,153 | always |
| What you do not know | 850 | always |

A pilot strafing something sixty miles out, with no flight and no clearance
pending, pays for all of it on every push-to-talk. Roughly **80% is
inapplicable** on any given call.

So the building block is a **brief** — what a controller is handed when it
becomes relevant, and not before:

```
Brief
  name        "visual-approach" | "emergency" | "cas-check-in" | "formations"
  when        a predicate over STATE, not over the words
  priority    what wins when the budget is tight
  cost        known in advance, in tokens
  body        the text
```

**The trigger is STATE, not similarity.** Matching the transcript by embedding
means the brief arrives one beat after he asks, and not at all when he asks
obliquely. Phase, whether a flight exists, whether a clearance is pending, what
he is equipped for, what he is squawking — all of that is known **before** the
model is called, deterministically. This is a retriever with no surprises in it,
which is what makes it testable.

**Priority exists for the emergency case.** A mayday must displace the formation
text, not queue behind it.

**What loaded must be recorded.** Once the prompt varies per call, "what did the
controller actually know when he said that" becomes a question only the recorder
can answer. Without it a bad reply is undiagnosable in a way it is not today,
and that is the real cost of this design.

Approach procedure is the first brief, and the one that shows why this is a
layer rather than a file. **ASR is one approach type of several, and it is the
only one we have built:**

| | who flies it | what the controller does | mile calls |
|---|---|---|---|
| ASR | the controller, by voice | continuous headings and altitudes | every mile |
| ILS | the aeroplane | vector to intercept, clear, then monitor | none |
| Visual | the pilot | clear it, then spacing only | none |
| VOR/TACAN | the pilot, on the station | clear the procedure, monitor | none |
| NDB letdown | the pilot, blind | altitudes and times, no vectors | none |

Four of those five say *"and then stop talking"*. The one behaviour that is
built and hardened is the one that never stops. `ApproachProfile.kind` and
`.guidance` already exist; what does not exist is an object that owns the rules,
so they live as `if` statements and as a paragraph of prose in the prompt.

Emergencies, close air support, intercept work and whatever comes next are the
same mechanism with different predicates. None of them needs building now. The
mechanism does.

---

## Where we break the rule today

Each is an issue, and each is the same defect wearing different clothes.

| violation | why it is one | issue |
|---|---|---|
| The geometry parses the radar **prose** — six regexes over a string the director renders from data it already holds | L2/L4 depending on L7's rendering. A low layer reading a high layer's presentation | [#47] |
| `flatten_formation` deletes the wingmen, so no aircraft but a lead has a position | a workaround for the above, not a fix | [#47] |
| `count_contacts` cannot tell a T-55 from an F-16 | L1 discards the category the streamer already knows, so L4 has to guess | [#45] |
| One `profile` per bridge; 15 module globals including the identity registry and the flight roster | L1 and L2 are process singletons, so there can never be two of anything | [#2] |
| `release_stale` compares radar names to board keys | L4 doing L2's job, badly | audit 1.1 |
| Visual approaches implemented as a paragraph in the system prompt | L5 procedure implemented by asking L6 nicely | this document |
| The intent classifier runs on Sonnet, on the hot path, and fires for a lone pilot | cost and latency, and a consequence of the `count_contacts` violation | [#45] |

---

## Order of work

1. **Characterisation tests on the loop.** Done, 30 July — `tests/fakeradio.py`
   and `tests/test_loop.py`. Nothing else was safe without them.
2. **Extract the stages. No logic moves.** Same code, given signatures, with the
   characterisation tests unchanged throughout. A red test means either logic
   moved or a hidden dependency was found; both are worth stopping for.
3. **Stores stop being module globals.** This is what unblocks *two of
   anything*, and therefore everything below it.
4. **[#47] structured world.** Cheap once there is one reader instead of six.
5. **Briefs.** The mechanism, with approach procedure as the first one.
6. **[#2] a profile per flight.** Falls out of 3 and 5, and is the wall in front
   of a second airfield.

Note that 4, 5 and 6 stop being separate projects and become consequences. That
is the argument for doing this before multiple airports rather than after:
afterwards means porting six prose parsers and one hardcoded approach type to
two airfields first.

---

## What this does not change

The two brains and the invariant. `route.py` as the single source of truth.
Closed sets rather than open vocabulary for anything spoken. Events over
inference. The flight recorder. Every one of those survived contact with a
pilot, and none of them is what has been costing sorties.

And the scars in `GOTCHAS.md` are load-bearing. The 0.4 s pause before
transmitting, `settimeout(None)` on the roster socket, the busy lock dropping
rather than queueing, the no-cache headers, the ordering inside `radio_lock` —
each is invisible in the shape of the code and lives only in a comment. An
extraction carries them along. A rewrite rediscovers them in the air.
