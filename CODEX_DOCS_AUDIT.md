# Documentation audit — 2026-08-10

## Verdict

The documentation is strong in depth, but it is not yet safe as a new-agent
onboarding system. A capable new agent can eventually understand Marshall; it
will spend too long deciding which document describes today versus history or a
proposed future.

No documentation was modified by this audit.

## What works well

- `CLAUDE.md` gives strong operating principles, test commands, and safety
  constraints.
- `docs/LAYERS.md` has an excellent architectural rule: dependencies only flow
  downward, with clear ownership by layer.
- `docs/WIRING.md` is unusually good operational archaeology: runtime flow,
  ownership between the deterministic engine and agent, and symptom-based
  troubleshooting.
- `docs/ISSUES.md` is a rigorous work record with acceptance criteria and test
  linkage.

## Evidence gathered

- The repository has 10,707 lines of Markdown across its principal documents;
  `docs/ISSUES.md` is 3,755 lines, `docs/WIRING.md` is 3,005, and
  `docs/TEST_PLAN.md` is 857.
- The local quality gate passed lint, 1,351 tests, and the approach sweeps, but
  correctly failed its issue/card synchronization check: #65 and #66 are
  labelled `needs-flight-test` without a cited card row.
- The current tree contains major post-history refactors: route splitting,
  state-machine wiring, two-field generalisation, Nevada support, Card-based
  kneeboard work, and unwired-code auditing.
- Existing `CODEX_FINDINGS.md` independently records documentation/configuration
  drift at the operational boundary.

## Onboarding blockers

### 1. README-level architectural contradiction

`README.md` frames Marshall as a blind deterministic controller with AI as
"ears and mouth." Current design and wiring instead describe radar-grounded
agentic control with deterministic separation. A new agent can make changes to
the wrong model before it reaches the deeper documentation.

### 2. No short, authoritative current-state path

The prescribed reading starts with broad documents and quickly leads into a
large mix of system reference, debriefs, and backlog history. There is no
two-page answer to:

- what runs today;
- which process owns which decision;
- where current state lives;
- how to test a change; and
- which documents are authoritative when they disagree.

### 3. Current-state drift across documents and GitHub

Examples:

- `docs/ISSUES.md` describes #40 as shipped, while `docs/WIRING.md` describes
  the Whisper-derived separation-board key as still TODO.
- The backlog audit found GitHub stale relative to `docs/ISSUES.md` for #3,
  #50, and #70.
- `docs/WIRING.md` contains current operational claims that need a freshness
  check against deployment configuration; `CODEX_FINDINGS.md` records a
  conflict around published API/database ports.

### 4. Proposal, history, and current reference are interleaved

`docs/SCHEMA.md` is clearly labelled a superseded proposal, which is good.
`docs/STRUCTURE.md` is less bounded: it mixes a target layout, proposal text,
and statements about today. `docs/LAYERS.md` likewise mixes current architecture
with the future brief/extraction design. Historical diagnosis is valuable, but
must not look like an instruction to implement today.

### 5. Missing change recipes

The system has good principles but no short procedural guides for common,
cross-cutting changes. A new agent needs explicit recipes for:

- adding a field or theatre;
- adding an approach/procedure;
- adding a kneeboard page;
- changing a controller decision or handoff; and
- changing prompts without bypassing deterministic authority.

## Recommended cleanup order

### P0 — make orientation reliable

1. Create `docs/START_HERE.md` (one or two pages), linked first from README and
   `CLAUDE.md`. It should state:
   - what Marshall does today;
   - the two-brain invariant;
   - deployables and entry points;
   - current source-of-truth documents;
   - test commands and what each proves; and
   - the known architectural limits.

2. Rewrite README's architecture/status section to match current reality, then
   link to `START_HERE.md` rather than historical design prose.

3. Specify precedence when sources disagree. Recommended order:
   current code and executable configuration; current tests; `docs/WIRING.md`
   only when dated/verified; `docs/ISSUES.md` for intended remaining work;
   historical debriefs and GitHub issue bodies last.

### P1 — separate reference from history and proposals

4. Add a compact header to every architecture/work document:

   ```text
   Type: current reference | proposal | historical debrief
   Validated against: <commit/date>
   ```

5. Make one current-architecture reference authoritative. It should cover
   component ownership, dependency direction, state authority, cross-process
   contracts, and known limits. `WIRING.md` can remain the deep troubleshooting
   reference rather than also serving as the onboarding architecture document.

6. Put clearly superseded material in an archive directory or visibly fence it
   at the top. Preserve the reasoning; remove ambiguity about its authority.

### P1 — make safe changes discoverable

7. Add change recipes for field/theatre, procedure, kneeboard, controller
   decision, and prompt changes. Each recipe should name the source-of-truth
   data, allowed layer boundary, required test tiers, and any flight-test/card
   consequence.

8. Add lightweight documentation consistency checks for endpoint names,
   entry-point commands, model/configuration claims, issue/card linkage, and
   document freshness markers.

## Bottom line

The architecture itself has clear guidance; the main problem is discoverability
and freshness, not lack of thought. The smallest high-value intervention is a
short, current `START_HERE.md` plus explicit document status/validation headers.
