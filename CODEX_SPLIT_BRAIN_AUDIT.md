# Split-brain and context-management audit — 2026-08-10

## Verdict

Keep the invariant. It is Marshall's credible safety argument.

The useful formulation is not simply "two brains" but:

> **A deterministic safety kernel plus a probabilistic interaction layer.**

Use that formulation in new code and docs. “Split brain” is useful historical
shorthand, but implies two peers with overlapping authority. They must not be
peers: the deterministic side authorises constrained operational facts, while
the model participates in an interaction under those constraints.

The bugs found around this boundary do not argue for letting an LLM sequence
aircraft. They show that the boundary must become typed, ordered, and enforced
rather than being mediated mostly by competing prose and downstream guards.

## The invariant

```text
Deterministic control decides safety-critical facts.
The agent interprets language and speaks naturally.
The bridge arbitrates and transports, but must not invent aviation decisions.
```

### Deterministic safety kernel

The deterministic side owns decisions where a plausible but wrong answer is
unsafe or operationally material:

- admission to the separation board;
- holding levels, sequencing, and one-in-the-letdown;
- runway authority, taxi/takeoff/landing decisions;
- computed ASR guidance;
- roster and formation facts; and
- handoff eligibility where procedure/data answer the question.

`controller.py` produces instructions and increasingly also emits a structured
`Decision` containing facts such as altitude, heading, runway, frequency, and
station.

### Probabilistic interaction layer

The agent owns work that is inherently open-ended:

- interpreting conversational or ambiguous requests;
- deciding when a question deserves an answer;
- phrasing already-decided instructions clearly and naturally;
- discretionary, radar-grounded commentary where no deterministic procedure
  applies; and
- invoking domain tools for facts it does not carry.

The interaction layer is deliberately broader than *language*. A radar
controller may make discretionary judgments that cannot sensibly be encoded as
a state machine; the important restriction is that it cannot create a
safety-critical commitment, alter an authoritative fact, or call a capability
outside its role. Calling it the “probabilistic language side” would therefore
understate both its useful judgment and the boundary it must respect.

This avoids two bad extremes: an LLM inventing safety-critical clearances, or a
large and brittle deterministic parser attempting to encode all human radio
language.

## Why it is a good idea

- **Safety:** the LLM cannot be the source of a holding level, runway clearance,
  or sequencing decision.
- **Testability:** the safety kernel runs in the local suite without a model,
  network, or simulator.
- **Traceability:** an instruction can be recorded as facts and compared to what
  was actually voiced.
- **Cost and latency:** routine deterministic work avoids a model decision; the
  model is used for language and genuine judgement rather than arithmetic and
  state transitions.
- **Maintainability:** the model handles varied pilot phrasing, while the
  controller retains a closed, auditable state machine.

## Why it has produced bugs

The system currently has more than two effective authorities:

1. `controller.py` owns persistent separation state.
2. Geometry/talkdown owns current position and approach guidance.
3. The agent owns language and some judgement.
4. `agent_atc.py`'s `reconcile()` decides which authority wins when they
   disagree.
5. Post-output guards can suppress or rewrite what would otherwise be spoken.

That creates a referee layer. The historical failures are mostly coordination
failures in this layer, not failures of deterministic separation itself:

- the blind controller could act on a false position report before radar
  rejected it;
- geometry could show an aircraft established while the separation engine still
  supplied a hold, and the agent voiced both;
- agent chatter on final blocked the deterministic mile-call metronome;
- an unauthorised-handoff guard removed an engine-authorised Tower redirect;
- handoff logic existed in several mechanisms, allowing Center to strand an
  aircraft despite apparently healthy checks.

The pattern is: two components produce finished prose, then a later guard tries
to resolve the disagreement. That is inherently fragile.

## Current progress toward a sound seam

`atc/decision.py` is the correct direction. A `Decision` carries facts rather
than an English sentence, and `Decision.verify()` can check whether the agent's
reply included the altitude, heading, runway, frequency, or station the engine
decided.

This is currently **observability, not enforcement**. The bridge records
`NOT VOICED` when an agent reply omits a required fact, but it does not yet
retry, replace the reply with deterministic phrasebook output, or prevent a
conflicting transmission. `phrasebook.py` describes the intended fallback but
is not yet the enforced response path.

The existing `CONTROLLER:`, `SEPARATION:`, and `ASR:` prompt blocks therefore
remain a transitional, string-based contract. They are much better than giving
the model no constraints, but are not a complete authority boundary.

## Recommended technical direction

1. **Make a structured outgoing plan the sole seam.** Controller, geometry,
   roster, and handoff logic should produce typed decisions. The bridge should
   reconcile those decisions once, before language generation.

2. **Enforce fact delivery.** If the agent omits or alters a required fact,
   retry with a constrained prompt or transmit a deterministic phrasebook
   fallback. Record `decision -> rendered text -> transmitted audio`.

3. **Validate before mutation.** Identity/admission and any guard that rejects
   a call must run before `Controller` advances its board. A call later treated
   as debug-only or rejected must not silently change separation state.

4. **Make reconciliation first-class policy.** `reconcile()` should consume
   typed decisions with explicit precedence, and have integration tests for
   every authority conflict. It should not depend on substring tests such as
   whether a directive contains `hold`.

5. **Treat the agent as a proposer where it requests action.** Tools and
   free-form agent choices should return structured proposals that deterministic
   policy accepts, rejects, or renders—not unreviewed operational actions.

6. **Test a whole turn deterministically.** Use fake radio, radar, clock,
   director, and agent clients to test ordering, locks, dropped calls, and fact
   propagation. Keep live rehearsals as acceptance evidence, not the only seam
   coverage.

## Context management: intended model

One motivation for the invariant is to keep the interaction layer fast and
cheap. The desired division is sound:

```text
Deterministic/bridge layer selects current, relevant state.
Agent receives only the current situation and the active instruction.
Conversation retains dialogue, not old telemetry.
Tools supply infrequent or unbounded facts on demand.
```

This prevents the model from receiving stale radar pictures and large
all-purpose reference material merely because it might be useful later.

## Context management: what works today

### Fresh state, not remembered state — working

`director/tools/context.py` implements `RadioContext`:

- current radar, transmitter, strip, phase, controller directive, and similar
  situation blocks are injected fresh into each turn;
- after the turn, all older situation blocks are stripped from conversation
  history, retaining only `PILOT:` dialogue and replies;
- the newest situation-bearing message is kept during the active turn so tool
  calls do not lose the current picture;
- the selected conversation window is 24 messages, sized for a question to
  survive intervening traffic and tool-call pairs.

The implementation documents a measured reduction from roughly 6,613 tokens a
turn before scrubbing to roughly 3,470 at the chosen window—about **48% less**—
while retaining about 9.4 calls of shared-channel history. It is covered by
`tests/test_context.py`.

This is effective and exactly the right pattern. It also avoids a serious
correctness cost: old radar pictures otherwise sit beside current state with no
reliable temporal distinction for the agent.

### On-demand facts — working in selected places

The agent is given tools instead of large static catalogues for several facts:

- `vector` computes exact range/bearing rather than inviting an estimate;
- `look_up_frequency` supplies stations outside the controller's own field;
- clearance, identity, and hook tools fetch/act on their bounded domains.

The field-frequency design is particularly sound: the brief carries the small
set a controller should know cold, while all other aerodrome frequencies are
looked up on demand. This reduces prompt size and prevents confident invention.

## Context management: what is not working effectively enough

### The static system prompt is still monolithic

Every `/atc` call assembles `soul + plate + rules` as system prompt. At audit
time these source files total approximately **24 KB**, including a **21.9 KB
`rules.md`**. It is sent on every model invocation regardless of station, phase,
or request.

`docs/LAYERS.md` correctly identifies the intended next step—state-triggered
briefs—but that mechanism is not yet implemented. This is the largest remaining
gap between the context strategy and the current system.

### Per-turn assembly is still over-broad

`compose_message()` selects useful live facts, but also appends substantial
standing instructions for stations, visual approaches, manners, frequency
rules, runway ownership, and other role-specific material. Some is necessary;
some should become explicitly selected briefs with a known trigger and token
cost.

### Tools are not role-scoped

One agent is built with the complete controller tool list. For example,
`spawn_ground` is available to every controller, relying on an Overlord brief
to say who may use it. That is less safe and more expensive than constructing a
tool capability set from the station role. A normal approach controller should
not be offered an operational tool it is forbidden to call.

### Radar is injected wholesale

Injecting the current radar picture avoids a hot-path tool round trip and is a
reasonable default for a radar controller. But it is still an unbounded
per-turn block as traffic grows. The next step is not necessarily a radar tool;
it is a measured policy: compact nearby/relevant contacts in the brief and use
an exact lookup tool for the rest.

### Flight evidence is incomplete

The context-history work is marked shipped/unverified in the backlog (#43).
Unit tests establish its behavior; a live session still needs to show that the
chosen shared-channel window preserves a question through realistic intervening
traffic.

## Context recommendation

Build the state-triggered **brief** mechanism described in `docs/LAYERS.md`:

```text
Brief
  name       a bounded responsibility, such as clearance-readback or formation
  when       deterministic predicate over current state
  priority   explicit token-budget precedence
  cost       measured/token-counted
  body       only the applicable instructions and facts
```

Start with one high-value migration—clearance delivery, formation operations, or
approach procedure—and measure prompt size, latency, tool calls, and response
quality before moving all rules. Couple that with role-scoped tools and a compact
radar brief. The deterministic kernel should decide which capabilities and facts
the interaction layer sees; the interaction layer should not be asked to ignore
irrelevant capabilities or rediscover state it could have been handed.

### A concrete context contract

Build each turn from a deterministic `ContextPlan`, not by growing a prompt:

```text
ContextPlan
  invariant brief     small, universal radio/safety rules
  role brief          station authority, local responsibilities, voice/persona
  task brief          active phase or bounded duty (for example clearance or ASR)
  live situation      selected current contacts, current directive, runway/strip
  dialogue window     recent words and replies only; never prior telemetry
  capabilities        the exact read/write tools this role and task may invoke
  retrieval policy    exact lookup tools for facts intentionally left out
```

Every entry needs a deterministic inclusion predicate, a priority, a measured
token cost, and a version/name logged with the turn. The resulting manifest is
as important as the prompt text: it makes “why did Approach know that?” and
“why did this call cost 8,000 tokens?” answerable without asking the model.

“Texture of a real person” should come from a stable role/persona brief, the
shared radio dialogue, and explicit continuity facts (an outstanding clearance,
a promised callback, the last issued instruction). It should *not* come from
retaining old radar pictures or handing every controller the whole world. Keep
authoritative operational continuity in deterministic/persistent state; give
the model only the small, relevant rendering of it.

### Safest implementation order

1. Add a pure, unit-tested `ContextPlan` selector. Initially have it reproduce
   today's prompt and tools exactly while logging the proposed role/task/brief
   manifest and token count. This makes the refactor observable before it
   changes controller behaviour.
2. Split `rules.md` into the invariant brief, role briefs, and task briefs.
   Migrate one bounded workflow first (clearance delivery is a good candidate,
   because its facts are already deterministic).
3. Construct the agent's tools from the plan, rather than giving every station
   `spawn_ground` and relying on prose to prohibit it. The trusted bridge must
   supply the role/station; include it in the session key or assert it cannot
   change within that session, so histories cannot cross-contaminate roles.
4. Replace wholesale radar injection with a compact relevance-selected picture
   plus an exact lookup tool for the rest. Define relevance as a deterministic
   policy (addressed aircraft, active sequence, nearby conflicts, and current
   handoff), then measure it against busy traffic.
5. Add replay tests and flight-card evidence for three outcomes together:
   required facts still reach the radio, a question survives intervening shared
   traffic, and the model neither sees nor can invoke an irrelevant capability.
   Track prompt tokens, model latency, tool calls, and failed decision
   verification as release metrics.
