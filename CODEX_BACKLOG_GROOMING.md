# Backlog grooming — 2026-08-10

Review scope: open issues in `peterb154/marshall`, using the GitHub CLI. No
GitHub issues, labels, or states were changed.

## Working interpretation of issue state

Several issues say `FIXED` or `CLOSED` in their body while remaining open on
GitHub. Do not close those mechanically: in this repository, the body often
records that the implementation is complete, while the open issue and
`needs-flight-test` label represent outstanding operational proof.

## Recommended priority queue

### P1: safety and verification

1. **#70 — [ARCH-9] A second map: Nellis and Tonopah**
   - Complete the MVA and grid-convergence surveys at both fields before
     vectoring aircraft in Nevada.
   - The issue explicitly calls both surveys non-optional.

2. **#65 — [SEP-2] Ground cleared an aircraft for take-off**
   - Implementation is fixed; complete the flight-card regression, especially
     the runway-authority case.

3. **#58 — [BUG-5] The controller invented every frequency except Departure's**
   - Implementation has a two-field guard; verify it in a sortie before
     treating the frequency briefing as operationally safe.

4. **#50 — [SEQ-1] Nobody is number two behind himself**
   - The immediate deadlock is guarded, but the state transition that returned
     a cleared aircraft to `HOLDING` is still unexplained. Keep this open and
     investigate the root cause.

5. **#19 — [BUG-1] Outbound vector at ~14 nm while inbound**
   - Existing `p1`; live evidence says this is a genuine approach-safety issue.

6. **#13 — [ID-2] Noise must not become an aeroplane**
   - Existing `p1`, but it is explicitly a synthetic-check item rather than a
     flight-time item. Complete its general admission-rule proof.

### P1: engineering gates

1. **#60 — [OPS-4] The card check was blind to a quarter of the card**
   - Finish the distinction between a row that tracks an open finding and a row
     that regression-tests a closed fix. The present check produces misleading
     stale-row advice.

2. **#71 — [KB-3] A kneeboard page is a function of a Card**
   - `comms` proves the foundation. Convert the remaining pages: `navlog`,
     `asr_plate`, `aip_plate`, `e6b`, `brief`, and `site`.
   - This can be `p2` if Nevada safety surveys take precedence; it is the
     natural next generalisation task after those gates.

### Batch in the next flight-card session

These are implemented or substantially built and can share a flight session:

- **#1 — [FP-1] Flight plans: many on file, assigned per flight**: complete
  remaining G-card scenarios.
- **#56 — [FP-3] The sortie being flown was not on the board**: verify the
  filed Kobuleti-to-Batumi sortie and the kneeboard plans tab.
- **#66 — [PHR-4] The check-in greeting was one sentence for every seat**:
  verify departure vs arrival greeting behavior.
- **#48 — [ID-3] Nobody may name himself** and **#49 — [ID-5] Tracked and
  untracked, and who owns him**: both are built/unflown identity behaviors.

## Dependencies and issue clusters

- **#2 → #3:** [ARCH-1] (one approach profile per flight) is the explicit
  prerequisite for [TEST-1] (Kobuleti ILS proof). Do not schedule #3 as an
  independent implementation task.

- **Identity design cluster:** #38, #40, and #42 overlap deliberately but are
  not duplicates. Sequence the identity model in #38 before board-key work in
  #40 and person/flight/member naming in #42.

- **Nevada generalisation:** #70 and #71 are complementary rather than
  duplicates. #70 supplies valid field data and mission constraints; #71 makes
  the general kneeboard render from a Card.

- **Approach behavior:** #19, #20, #37, and #39 are related approach-control
  work but each addresses a distinct failure mode. Preserve separate issues;
  use a shared flight plan where practical.

- **Planning:** #1 is the data/assignment foundation; #46 is spoken plan
  selection; #22 is the pilot-facing UI. Keep that order.

## State and label hygiene

1. Add priority labels where the issue body has become clearer than the label:
   - Suggested `p1`: #70, #60, #65, #50, #58.
   - Suggested `p2`: #71 (unless it becomes the current engineering focus).

2. Keep #56 and #58 open despite their body saying `CLOSED`: both carry
   `needs-flight-test`, which indicates the intended remaining work.

3. **#51 — [HO-2] Georgia Center has no proactive handoff at all** meets all
   listed acceptance criteria. Before closing it, create or otherwise preserve
   a separate follow-up for the stated unintentional Batumi Ground handoff
   dead-end (F5 on the card). That work should not be silently lost with #51.

4. #50 should remain open even though the workaround is fixed, because its
   acceptance criteria explicitly retain the unexplained state transition.

## Lower-priority backlog

The existing `p2` and `p3` classification is broadly sensible. Retain the
feature work (#22–#31) behind the operational and verification queue, and keep
the `needs-design` items (#38, #40) out of implementation until their model and
measurement work is settled.

## Relevance audit — current tree, 2026-08-10

This audit was added after the initial grooming pass. It validates the older
backlog against the current repository; it does **not** claim to reproduce every
live-only failure in DCS.

### Evidence collected

- `uv run python tools/check.py` completed with lint clean; **1,351 passed, 6
  skipped, and 1,002 subtests passed**. The clean, sloppy, and non-turning
  approach sweeps all held their recorded baselines.
- The check failed exactly where it should: `tools/issue_sync.py` reports #65
  and #66 as `needs-flight-test` issues with no cited cockpit-card row.
- Current source and tests still explicitly exercise the active architecture:
  `tests/test_asr.py` / `tools/asr_sweep.py` for #19/#20/#39; identity and
  roster tests for #38/#40/#48/#49; handoff tests for #51; two-field tests for
  #56/#58; and Nevada tests for #70.
- Recent commits include the route split, state-machine wiring, two-field
  generalisation, Nevada mission/surveys, Card foundation, and an unwired-code
  audit. The old issue text must therefore be read as historical context, not
  an implementation plan.

### Classification

| Class | Issues | Assessment and action |
|---|---|---|
| Current, known-open behavior | #2, #19, #20, #37, #53 | Still relevant in the current architecture. #19/#20 remain represented by sweep baselines and card notes; #2 remains the one-profile-per-bridge limitation; #37 is unbuilt relative guidance; #53 is a real capability/data mismatch. Keep open. |
| Implemented, awaiting human proof | #1, #3, #41, #42, #43, #48, #49, #56, #58, #65, #66 | The code/tests and test-card material show that these are not stale reports. Their actionable work is a bounded flight test, not another redesign. Add or repair card rows before asking a pilot to validate them. |
| Implemented, but remaining scope is narrower than title | #39, #47, #50, #51, #55, #70, #71 | Keep open, but rewrite each issue's top status/acceptance criteria to say exactly what remains. See the issue-specific notes below. |
| Still-valid design or product work | #22, #23, #24, #26, #28, #31, #44, #45, #46 | These are roadmap items, not stale bugs. Keep them deliberately lower priority until the current flight and architecture gates are complete. |
| Needs re-triage/rewrite before implementation | #13, #38, #40 | Later identity work changed the safety boundary and the issue text now conflicts with current architecture documentation. Preserve the historical evidence, but restate the unresolved claim and its measurable closure condition before assigning work. |

### Issue-specific corrections

- **#70:** GitHub still says the Nevada MVA and convergence surveys are
  outstanding. `docs/ISSUES.md` records both as completed on 10 August, with
  measured values. Update GitHub before treating #70 as a safety blocker. If a
  Nevada sortie is required, create an explicit flight-test acceptance item;
  do not imply it through stale survey text.

- **#3:** GitHub says `TODO`; the repository says the Kobuleti ILS is built and
  test-covered, with only the human flight/card proof remaining. Align its
  GitHub status and restore/add `needs-flight-test` if the label is meant to
  drive the card.

- **#50:** GitHub says the cause of the requeue is still unknown. The current
  issue text identifies it: `Controller.check_in` unconditionally reset the
  phase during a frequency change. The remaining work is flight rows H18/H19,
  not root-cause investigation.

- **#51:** The single `next_controller` cascade and its guards are present.
  The still-dead Batumi Ground exit is a separate follow-up. Either file that
  follow-up and close #51, or rewrite #51 to own it; do not leave an
  all-criteria-checked issue open as a container for a different defect.

- **#65 and #66:** These are real current flight-test items, but are currently
  untestable by process because the synchronizer cannot find a row. Q5 cites
  #41, not #65; #66 has no cited row. Fix the card references first. This is
  the only failing required check in the audit.

- **#39:** The base-leg pattern is implemented. The remaining work is
  speed-scaled turn-in/intercept geometry (and the non-turning behavior), not
  the original point-vs-pattern design. Rename/rewrite the issue accordingly.

- **#47:** Structured radar contacts, category, and most consumers are now in
  the tree and tested. The remaining task is fixture migration plus deletion of
  the fallback regex/`flatten_formation` path. Keep it, but make that the title
  and acceptance scope.

- **#55:** The refactor has already extracted `voice`, `talkdown`,
  `addressing`, and `assembly`; dry-run/live assembly is shared. The open work
  is specifically separating loop-owned state and guards. Treat it as a scoped
  refactor, not evidence that the entire bridge remains monolithic.

- **#71:** The Card foundation, theatre-aware comms, and Nevada-safe hold
  behavior are implemented. Remaining scope is only the six named page
  migrations; retain it as that implementation task.

- **#13:** The original "no new ghost from a live sortie" closure condition is
  incompatible with its GitHub `needs-synthetic-check` label and is no longer
  the whole safety boundary after the identity work. Recast it as a bounded
  corpus/admission-rule regression issue, or close it with an attestation if
  the present test corpus is accepted as the contract.

- **#38 and #40:** Current documentation conflicts. `docs/ISSUES.md` describes
  #40 as shipped, while `docs/WIRING.md` still says the separation engine is
  keyed by a Whisper-derived string; #38's event/slot assumptions have also
  been changed by #41. Do not start a new identity refactor from either old
  narrative. First write a short current-state design note: actual keys,
  lifetime/cleanup, known collision path, and the exact failing test or live
  scenario to solve.

### Discipline changes recommended

1. Make the GitHub issue body, `docs/ISSUES.md`, labels, and card references a
   single completion gate. `tools/issue_sync.py` already detects much of this;
   keep it required and do not merge a new `needs-flight-test` label without a
   card row.
2. After an architectural refactor, add a one-line **remaining scope** section
   to each affected issue before scheduling it. Historical diagnosis belongs in
   the issue, but should not masquerade as the current implementation plan.
3. Use one of four explicit states in the body: `OPEN/REPRODUCIBLE`,
   `IMPLEMENTED—AWAITING FLIGHT`, `IMPLEMENTED—AWAITING SYNTHETIC CHECK`, or
   `TODO/DESIGN`. Avoid bare `FIXED` or `DONE` on an open issue.
4. When an issue discovers a different defect, file a follow-up instead of
   retaining the original as an unbounded container (#51 is the current
   example).
