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
