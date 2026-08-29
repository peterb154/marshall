# The work, as issues

    Type: WORK RECORD
    Validated against: 10 August 2026

> The backlog. Read an issue's **Remaining scope** block, not its historical diagnosis — several describe a system that has since been rebuilt. GitHub is a projection of this file; never edit a body there.


The single list. Every shipped fix that a human still has to sign off on, every
open bug, and every feature not yet built — each with acceptance criteria you
could hand to somebody else.

`tools/file_issues.py` files these on GitHub and writes the numbers back here,
so this file stays readable whether or not you are online.

**Format.** `## [SLUG] Title` then the body. `Tests:` names rows on the flight
test card (`docs/TEST_PLAN.md`); `Code:` names where it lives. Acceptance
criteria are things that are either true or not — no "works well".

**Two ways an issue closes, and the label says which.**

`needs-flight-test` — **a human is the instrument.** Only for what a person
uniquely judges: whether it *felt* like two controllers, whether the timing was
usable, whether he was talked over, whether the phrasing was natural at the
moment it mattered. Also for conditions a synthetic pilot cannot create.

`needs-synthetic-check` — **a script is a better instrument, and a hundred times
faster.** Deterministic behaviour with an observable output: did the handoff
fire, did the ghost enter the stack, did the second bridge refuse. A pilot
tickling these one at a time is flight time spent badly, and he can only cover
the cases he happens to fly.

The split is not about importance. #18 (one bridge at a time) is the
most-repeated failure this project has had and a script closes it in a second;
#5 (talking over the pilot) is unglamorous and no script has yet contested a
channel the way two people do. **Flight time is the scarcest resource here** —
spend it only on what it is uniquely good for.

**Priority is a label, and it means what it says.** `p1` is next and has
evidence behind it — a transcript, a repro, or something blocking two other
issues. `p2` is real and queued. `p3` is wanted and not urgent.
`needs-triage` means it predates the current shape of things and somebody
should check it is still true before working it.

**Closing an issue needs an attestation, not a tick.** Who or what tested it,
what was actually exercised, and the COMMIT it was tested at — because six weeks
later the only questions that matter are those, and none of them survive a green
tick. `uv run python tools/attest.py <n> --by <who> --how "<what>" --close`
records it and closes. It flags a dirty tree, since "tested at abc1234" is a lie
if the working copy was not.

**Status key.** `SHIPPED/UNVERIFIED` — the code is in and the two cheap tiers
are clean, but no human has flown it. `OPEN` — known broken, with a repro.
`TODO` — not built. `VALIDATED` — a human used it and it did the job; this is
the only status a `needs-flight-test` issue can be closed on, and a green test
suite has never been sufficient for it. `CLOSED` — finished and closed on
GitHub; the attestation on the issue says by whom and how, which is the part
worth reading.

**The statuses here and the state on GitHub must agree**, and for a fortnight
they did not: twenty of thirty-seven read OPEN or TODO while GitHub had them
closed, [OPS-2] included, which is the issue about exactly this. `uv run python
tools/issue_sync.py` checks all three copies — these statuses, GitHub, and
whether the cockpit card still cites something closed — and runs in
`tools/check.py`, so the drift cannot be silent again.

---

## [CARD-4] The running order is never checked for being a running ORDER — #205

labels: tooling

**Status:** FLIGHT 1 re-ordered by hand (28 August). The GUARD is not built,
which is why this stays open.

`tests/test_the_card_is_flown_as_flights.py` checks that every row a flight
names exists, that no live row is in no flight at all, and that an `a..b` range
expands in card order. It does not check the one property the flights exist FOR
-- that the rows come in the order a pilot meets them. The card was reorganised
by flight on 16 August precisely because theme order is the wrong axis for
flying, and the sequence within a flight was then left unguarded.

Three rows in FLIGHT 1 could not be flown where they sat:

    P1 P2   "slot into a cold jet and SAY NOTHING" / "still silent"
            -- listed 19th and 20th, after clearance, taxi and departure
    G17     "open the sortie with an odd FIRST call" -- listed 11th
    G15     "AIRBORNE on your filed clearance" -- listed 9th, at the ramp

Four more were out of sequence (H10 after "once established"; H5 after H4;
H31, the roll-out, before V8 and V5, which are on final), and V10 -- "two
aircraft worked by seats at DIFFERENT aerodromes" -- was on the solo sortie.

**Nothing was wrong with any ROW.** Every one exists, is live, cites an open
issue and is in a flight, so every check passed. The card was wrong in the only
dimension nothing reads, which is the same shape as #204 one document over: a
guard that cannot see the axis the fault moves along reports green while the
thing it guards is unusable.

**What a guard would need.** Rows carry a `when` column, but it is prose --
"P1", "Holding short, ready for departure", "**Airborne on your filed
clearance**" -- and prose cannot be sorted. A checkable version needs the stage
as DATA: a small ordered vocabulary (ramp, clearance, taxi, departure, enroute,
approach, final, rollout, board) with each row declaring one, and the test
asserting a flight's stages never go backwards. That is the fix; hand-ordering
is not, and this entry exists so the next drift is not found by a pilot.

**Acceptance criteria**
1. Every row declares a stage from a closed vocabulary, as data rather than
   prose.
2. A flight whose rows go backwards through the stages fails the suite.
3. A row that needs a second aeroplane cannot appear in a solo flight.
4. FLIGHT 1 passes without hand-ordering.

---

## [STATE-9] A deslotted aeroplane is never reaped, so the next sortie inherits him — #207

labels: bug, needs-flight-test

**Status:** OPEN. Found by a pilot, live, 28 August, and visible on `/diag`
right now with nobody in the sim:

**28 AUGUST: THE REAPER WAS RIGHT AND UNREACHABLE.** `reconcile` runs every
thirty seconds and refused to act on an EMPTY set, because "the sim told us
about nobody" and "we failed to ask" were one value at that layer. They are
distinguishable one layer up, in `_sweep`, which knows whether its Eval
returned -- and that was thrown away at the boundary. So with an empty sky
nothing was ever reaped and two ghosts sat on the scope for three hours.
The caller says which it has now. Verified live: five stale rows, one sweep,
`reconcile: the sim reports an empty sky; 5 row(s) gone`.

**A STALENESS FILTER IS THE WRONG FIX AND WAS TRIED.** `StreamUnits` is a
CHANGE feed, so a parked aeroplane stops being reported -- filtering reads on
`last_seen` would delete a pilot sitting in a cold jet two minutes after he
sat down. Reverted. `STALE_POS_SEC` and `core/scope.contacts` both say so.

Also fixed: `ghost_flight` deletes its own track, and `POST /atc/forget` (#212)
clears a seat's memory without a container restart.

    Sockeye   phase=LANDED   sortie=landed   plan=(blank)   owner=Kobuleti Departure
    TRACKED:    (empty)
    UNTRACKED:  (empty)

He deslotted. The scope is empty. **Nothing removed him from the board**, so he
remains LANDED and owned by Kobuleti Departure indefinitely -- and the next
pilot to fly as Sockeye starts his cold-and-dark sortie already landed, already
somebody else's, on a rung eight steps down the ladder from the one he is on.

The pilot put it as a question -- *"is the sim not resetting the flight status
when the pilot deslots?"* -- and the answer is that the sim is not being ASKED
to. `birth` arrives (twice on 28 August: 17:11:53 and 17:13:46, a deslot and a
re-slot), and nothing treats it as the start of a sortie or the end of the
previous one.

This is the axis `docs/STATE.md` was written about on 11 August -- *the board
cannot remember who is flying, because `flights` is append-only, scoped to
nothing, and cleaned by hand.* Cleaned by hand is what has been happening:
`a_clean_board()` in the rehearsal harness, and me running it before the
sortie. A pilot has no such command.

**It also pollutes across pilots, not just across sorties.** `Harrier 2-3`, a
fixture from a `ladder_rehearsal.py --only Q1` smoke test at 16:54, was still
on the board when the pilot checked in at 17:16 and stayed there for his whole
sortie -- the harness removes its aeroplane from the SCOPE and leaves its row
on the BOARD.

**Acceptance criteria**
1. A `birth` for a callsign clears any prior state for that callsign: phase,
   owner, assigned level, clearance.
2. An aeroplane that leaves the sim leaves the board, rather than being owned
   by a controller who cannot see him.
3. A rehearsal fixture cleans up its board row as well as its track.
4. Two sorties in a row, without a bridge restart between them, and the second
   starts on the clearance rung.

---

## [ARCH-42] Nothing asks whether a clearance the controller spoke was ever issued — #185
labels: bug, architecture, needs-flight-test

**Status:** CLOSED 18 August, NEEDS A PILOT — card row G14. The prompt fault is fixed, the inverse check records unbacked claims, and a prompt/tool signature check now guards the two-brain seam. Verified end to end on `tools/atc_dryrun.py --script kobuleti` — the controller called the tool, was refused, spoke the refusal and stopped, inventing nothing. **Only a pilot can score criterion 1** because a fabricated clearance sounds exactly like a real one; what a machine can now say is whether the record backs it, which is criterion 3 and is guarded.

**29 AUGUST: THE RECORD HALF IS FIXED AND VERIFIED; THE WORDS HALF NEEDS EARS.**
Driven against the live stores: engine verdict True, `acked_at` written, and
the seat then reports

    ACKNOWLEDGED. G20Test was cleared on BatumiTest and read it back correctly.

so Ground has something true to read and the taxi refusal that ended the
28 August sortie cannot recur from THIS cause. What is not testable without a
pilot is criterion 2 itself -- whether the controller still SAYS "readback
correct" when nothing has been acknowledged. That is the agent's words against
the record, `unbacked_claims` reports it, and only somebody listening can
confirm the prompt rule holds. Card row G19.

    "so we never got a clearance ... Then everybody just played along?"

`decision.verify` asks which of the engine's facts did not survive being spoken
— the DROP — and has caught real transmissions since #102. **Nothing asked the
opposite.** On 18 August the engine issued no clearance at all and the
controller said:

    15:13:52  Sockeye, Kobuleti Clearance, cleared to Batumi, as filed,
              maintain five thousand, expect one zero thousand, departure
              frequency one two three decimal three, squawk ...
    15:14:33  Sockeye, readback correct, contact Kobuleti Ground ...

`assigned_plans` held no row; `flights` held none either. Ground taxied him,
Tower launched him, and he flew to another aerodrome on a clearance that
existed only in the air. **Every rung believed it, because nothing anywhere
asked whether it was real** — which is why it was the last of the seven
findings to be understood and took a day of reading transcripts.

**Where the numbers came from: nowhere.** Unlike #179, we did not tell it. The
per-turn prompt carries the departure frequency and nothing else; `found_but_
not_him` names the label and the endpoints; `flight_plan_help` needs an
assigned plan and refuses without one. The altitude and the squawk were
invented after the tool refused him.

**And the rules already forbade it** — *"never search your memory for a plan"*,
*"a clearance you improvised is an aeroplane cleared to an altitude nobody
wrote down"*. What they never said is that **a refusal is terminal**. Every
rule covered what to do with what comes BACK; none covered nothing coming back.
That is the prompt fault, and it is fixed.

**A LIVE DEFECT WAS FOUND WHILE FIXING THIS.** #183 changed the tool to
`request_clearance(callsign, plan)` and left `rules.md` telling the controller
to pass the pilot's words through unedited. Flown, every clearance request in
the next sortie would have been refused — `named("Roger Sock, I would like
Batumi Test...")` matches no label. The suite was green, ruff was clean, the
tool's own docstring was correct and tested, and the prompt is a markdown file
nothing parses. **The seam between the two brains was the only contract in the
system with no check on it.**

**What was built.**

    rules.md                   the contract corrected, plus the rule that was
                               missing: a refusal is not a clearance, and if
                               the tool did not hand you the words you have
                               none
    clearance.unbacked_claims  the inverse of `verify` — what did he say that
                               the record denies? Answered from the DATABASE,
                               because what the turn believes is the thing in
                               question, and silent when it cannot ask
    the receive loop           RECORDS it (`kind="unbacked"`), never edits it.
                               Cutting the clause would be a regex guard on a
                               model's words, which is #179
    a prompt/tool check        every `tool(args)` spelled in the prompts must
                               match the real tool. It fails on the exact
                               defect above

**Verified end to end** on `tools/atc_dryrun.py --script kobuleti`: the
controller called the tool, was refused, spoke the refusal and stopped.

**Acceptance criteria**
1. A controller refused a clearance says so and does not invent one.
2. "Readback correct" is not said before anything is acknowledged.
3. An unbacked claim reaches the recorder on the transmission it happened on.
4. No transmission is edited to achieve any of the above.

---

**REOPENED 28 AUGUST. IT WAS CLOSED ON HALF ITS CRITERIA.** A pilot flew G14 --
a clearance requested under a callsign the board does not have, then talked as
though cleared -- and the controller correctly refused to invent one. That is
criterion 1. It was attested and the issue was closed on it.

Criterion 2 was never exercised by that row and failed on the very next sortie:

    18:51:38  ATC    Sockeye, readback correct.
    18:52:55  ENGINE Sockeye, your IFR clearance has not been read back,
                     contact Kobuleti Clearance one two five decimal one.
    18:54:48  ATC    Sockeye, readback correct.
    18:55:04  PILOT  "he says my read back is correct, but on the diag page
                      it's still showing not read back. I'm going to abort
                      this flight"

`assigned_plans.acked_at` was NULL throughout. `_ack_the_clearance` is gated on
the ENGINE's verdict, correctly -- so the agent may SAY "readback correct" while
nothing records it, and Ground goes on refusing taxi for ever. The sortie was
unwinnable from the moment the words and the record diverged.

**Nothing reconciles the two**, which is the issue's own title pointed at the
acknowledgement instead of the clearance: nothing asks whether a "readback
correct" the controller spoke was ever recorded. A refusal the pilot cannot see
is the same fault as a clearance nobody issued.

**The closing lesson, which is the reason this note is here rather than in a new
issue:** an attestation names what was flown, and G14 did not fly criterion 2.
An issue with four criteria is not closed by evidence for one of them.

---

## [STATE-10] A controller's memory outlives the sortie, and cannot be pruned per pilot — #209

labels: bug, needs-flight-test

**Status:** OPEN. Found live, 28 August, with a pilot sitting on the ramp
unable to get a clearance.

Every seat keeps a conversation in `session_messages`, keyed `hooks:<seat>`.
`hooks` never changes, so the conversation outlives the mission instance, the
bridge restart and the sortie. Kobuleti Clearance held 36 messages reaching
back to 18:33 -- the PREVIOUS sortie, plus a `--only Q1` smoke test -- and
answered from them:

    ATC     Sockeye, information Sierra current, and you are already cleared
            on the BatumiTest flight plan, as filed, maintain five thousand.
    ATC     (Kobuleti Ground) negative, you have not been cleared yet
    PILOT   "Kobuleti Clearance is using memory, maybe, rather than the
             database to figure out what I'm filed for"

`assigned_plans` was EMPTY. He had never been cleared, Ground and `/diag` were
right, and Clearance was reciting a clearance it had issued an hour earlier in
a different mission instance. **It also contradicted its own tool**:
`clearance_state("Sockeye")` returned "IS NOT ON THE BOARD" at that moment.

**THE BLUNT FIX IS WRONG AND WAS TRIED.** Deleting `where session_id like
'hooks:%'` unblocked the pilot and would have been destructive with a second
aeroplane up:

    "we have to be careful clearing session history -- as when a new pilot
     comes in, we dont want the controller to forget everything."

A seat's conversation legitimately spans several pilots; a controller DOES
remember everyone he is working. What must not survive is the turns of a sortie
that has ENDED -- and that is not the same as "everything in this seat".

**Nor is keying the session on the mission instance enough.** It would handle a
mission change, and not the case that actually bit twice: a pilot deslots and
re-slots WITHIN one mission (28 August, births at 17:11:53 and 17:13:46), so
his old sortie's turns are still the same instance and still wrong.

**THE ROOT IS THAT THERE IS NOTHING TO PRUNE BY.** The schema is
`session_id, agent_id, message_id, data, created_at` -- no mission, no
callsign, no flight id. Identity was never recorded, so surgical cleaning is
impossible by construction and the only available tool is matching text inside
the JSON, which is regex over model output and the thing #179 exists to stop.
Whatever the policy turns out to be, it cannot be implemented until a message
says whose sortie it belonged to.

**Acceptance criteria**
1. A message records the mission instance and the flight it belongs to, at
   write time.
2. Ending a sortie removes that flight's turns and leaves every other pilot's
   in place.
3. Two aircraft on one seat's frequency: clearing one does not change what the
   controller remembers of the other.
4. A new mission instance starts every seat with no memory of the last one.
5. No pruning is done by matching text inside a message.

---

## [STATE-11] A capital letter took a pilot off his own board — #210

labels: bug, needs-flight-test

**Status:** FIXED 28 August in `board.find`, live, with a pilot in the seat.
Needs the sortie flown end to end to close.

**29 AUGUST: CRITERIA 1--3 MET AND VERIFIED, 4 IS A PILOT'S.** Bound a row as
`closetest` and asked the clearance seat about `CloseTest`:

    NOT ISSUED. CloseTest has no clearance. There are 2 plan(s) on file...

It finds him, and says the true thing rather than "I do not have you on the
board" while printing the board with him on it. `srs_guid` and `track_name`
stay exact, guarded by `tests/test_a_name_is_not_an_identifier.py`.

Criterion 4 is "a pilot is cleared, reads it back, and taxis -- end to end, no
seat disagreeing", and that is a sortie. It stays open for it. #185 was closed
on three criteria out of four and the fourth failed the next evening; this is
the same shape and gets the same answer.

`board.find` matched names with `=`:

    SELECT * FROM flight_state WHERE mission = %s AND callsign = %s

The row is bound `sockeye` -- lower case, as the identity ladder writes it --
and the controller asks for `Sockeye`, because that is how the agent says a
name. No match. Every clearance tool goes through `_flight()`, so all of them
answered as though the aeroplane did not exist, and the refusal printed the
row it had just failed to match:

    "Sockeye IS NOT ON THE BOARD ... On the board: sockeye."

**What it cost.** `request_clearance` could not clear him, `clearance_state`
could not tell him why, and the controller filled the gap with the reassurance
that fits: *"you are already cleared on the BatumiTest flight plan, as filed,
maintain five thousand"*, while `assigned_plans` held nothing at all. Ground --
which reads the record -- refused taxi, correctly. The pilot could neither be
cleared nor taxi, and spent twenty minutes on the ramp being told two opposite
things by two seats:

    ATC  (Clearance) you are already cleared on the BatumiTest flight plan
    ATC  (Ground)    negative, you have not been cleared yet
    PILOT "clearly, on the DIAG page, and with Kobuleti Ground, I'm not
           cleared for a flight plan, but Kobuleti Clearance thinks that I am"

**A NAME IS NOT AN IDENTIFIER, and the fix is that distinction.** `srs_guid`
and `track_name` are the sim's own strings and still match exactly -- a loose
comparison there would bind the wrong aeroplane, which is a separation fault.
`callsign` and `srs_name` are NAMES: written by whoever bound the row, spoken
by a pilot, title-cased on the way through the agent. They match without regard
to case now.

**It hid behind two better stories.** The seat's conversation really had gone
stale (#209) and really did need clearing, and clearing it changed nothing --
which is what ruled it out. And the fabricated clearance really is #185's
shape, an agent covering a refusal it could not voice. Both were true and
neither was the cause. The tell was in the tool's own output the whole time,
naming the row in the sentence that denied it.

**Acceptance criteria**
1. A callsign matches its row whatever the case, for `callsign` and `srs_name`.
2. `srs_guid` and `track_name` still match exactly.
3. A refusal that names the board cannot name the callsign it just refused.
4. A pilot is cleared, reads it back, and taxis -- end to end, no seat
   disagreeing with another about whether he holds a clearance.

---

## [ARCH-56] A cache is a second copy, and this project has been bitten by that eight times — #211

labels: architecture

**Status:** OPEN. The lever is built (`POST /atc/forget`, 28 August); the RULE
is not, and the rule is the issue.

A controller's conversation lives in two places: rows in `session_messages`,
and `agent.messages` inside a cached `Agent` in the director process. On 28
August a pilot spent forty minutes on the ramp being told he was *"already
cleared on the BatumiTest flight plan, maintain five thousand"* -- a verbatim
replay of a DIFFERENT sortie -- while `assigned_plans` was empty and every
tool said otherwise. The rows were deleted three times and nothing changed:
`_atc_agents` had been up nine days.

    "an in-memory cache of Agent objects, wtf man!? how many times we going
     to let this eat our lunch?"

**Eight, counting this one.** The archive is full of the same sentence:

    #120  ARCH-16  the board is in memory; the database is the source of truth
    #126  SEAM-12  clearance delivery searched an empty board
    #153  ARCH-28  the director states an absence as a fact, in three places
    #81   SEAM-3   one agent per session became seven, sharing one counter
    #137  ARCH-23  fixes are Python, published as though they were data
    #47   RAD-5    the geometry reads structure, not prose
    #209  STATE-10 a controller's memory outlives the sortie
    #212  ARCH-55  this one

**Every one was fixed as an instance and none as a class.** #120 is literally
titled "the board is in memory; the database is the source of truth", is
CLOSED, and the same shape bit again today in a different store. `docs/STATE.md`
says where truth lives and says nothing about who is holding a copy of it.

**The tell was already written down.** `/atc/transmitted`, four lines below the
cache it needs to know about:

    BOTH COPIES, because there are two. The row in `session_messages` is what
    a restart restores; `agent.messages` is what the live process is reasoning
    from, and correcting one leaves the other lying until the next restart.

That paragraph is correct, was there before today, and there was no endpoint
that acted on it -- so the only way to make a controller forget was to restart
his container, which nothing in the harness or the ops tooling ever did.

**What a rule would look like.** Every module-level mutable cache in a serving
path declares, in one registry: what it holds, what its key is, what evicts it,
and which durable copy it shadows. A test walks the AST for module-level
mutable state and fails on one that is not registered -- the same enforcement
shape as `test_a_phase_is_in_exactly_one_list.py` and
`test_the_atc_is_not_in_a_container.py`. The point is not to forbid caches; it
is that a cache with no documented eviction is a second source of truth, and
this codebase keeps discovering that one aeroplane at a time.

**Acceptance criteria**
1. A registry names every module-level mutable cache in `services/` and the
   bridge: contents, key, eviction, and the durable copy it shadows.
2. A test fails on module-level mutable state that is not in the registry.
3. Every registered cache has an eviction path reachable without a restart.
4. Clearing any state clears both copies, or says which one it did not.

---

## [SEP-27] Approach terminated radar service and sent him to Center, on the ILS — #213

labels: bug, needs-flight-test

**Status:** OPEN. Found by a pilot, live, 28 August, established inbound.

    20:09:04  ATC   Sockeye, cleared ILS approach runway one three, vector to
                    intercept, maintain at or above two thousand until
                    established, report established
    20:09:29  ATC   Sockeye, contact Georgia Center one three nine decimal zero.
    20:09:44  ATC   Sockeye, radar service terminated, contact Georgia Center
                    one three nine decimal zero.
    PILOT           "he just sent me to center while I'm on an approach"

Twenty-five seconds after clearing him for the approach, the seat working the
approach gave him away -- to the ENROUTE controller, backwards down the ladder,
with the words that mean he is on his own. He then had to ask Approach for the
same clearance again at 20:09:59 and was told "you remain cleared", so the
engine had not let go of him: the handoff was the agent's.

An approach clearance is the one instruction that says who is working you until
the runway. Handing him to Center after it is the same fault as #135's refusal
that also hands over -- an instruction and a farewell in one breath -- except
this one sends him to a controller who cannot take him.

**Acceptance criteria**
1. A flight cleared for an approach is not handed to an enroute controller.
2. "Radar service terminated" is not said to an aircraft being vectored to an
   intercept.
3. If a handoff really is due, the engine authorises it -- `atc/handoff` --
   rather than the agent voicing one.

---

## [SEAM-23] A frequency read-back is only accepted in one of its spoken forms — #214

labels: bug

**Status:** OPEN. Low priority, and named as such by the pilot -- it costs a
transmission, not a sortie.

A pilot reading back one two three decimal three says it however he says it:

    "one two three decimal three"      "123.3"
    "one two three point three"        "1-2-3-3"
    "one two three dot three"          "one twenty three three"

`decision.accepted_forms` builds a single spoken form and matches on it, so a
read-back that is CORRECT in a different idiom reads as missing -- and the
correction that follows asks for the number he just said. On 28 August a
read-back exchange ran four transmissions with the frequency right from the
second one.

    "we should accept 1,2,3,3  1,2,3,dot,3  1,2,3,decimal,3  1,2,3,point,3 ...
     all work. I dont really care - its a lower priority bug - but its a bug."

The renderer is settled -- `core.say.spell_freq` is the one place a frequency
is SAID, and #191 fixed a caller that had its own. This is the other
direction: one way of saying it, many ways of hearing it, and the reader is
the half that has to be generous.

**Acceptance criteria**
1. decimal / point / dot / bare-digit / grouped forms of one frequency all
   verify against the same decision.
2. A form that names a DIFFERENT frequency still fails.
3. The spoken form the controller uses is unchanged -- this widens what is
   accepted, never what is said.

---

## [TEST-1] Fly Kobuleti ILS to prove the data drives it — #3
labels: test, needs-flight-test

**Status:** BUILT, needs a pilot. `KOBULETI_ILS` exists and criteria 1, 2 and 4
are met and guarded by `tests/test_ils.py`. Closing it needs somebody to fly it.

The stated proof that this is data-driven and not Batumi-shaped. Load a Kobuleti
ILS profile and fly it with no code change.

**Acceptance criteria**
1. A Kobuleti ILS profile is loaded from data alone.
2. The talkdown does NOT run (`guidance: "intercept"` — the aircraft has its own
   aid) and Tower takes him at the intercept, not at the missed approach point.
3. ~~The plate, the kneeboard and the ATC agree on the field, course and minima.~~ **OBSOLETE 13 August** — the plate and the kneeboard were deleted (`69ce4dc`); the DTC carries the chart now. There is nothing left for the ATC to agree WITH, so this criterion has no subject rather than being unmet. Criteria 1, 2 and 4 stand and are met; what remains is a pilot, which is card section T.
4. No file under `src/marshall/atc/` changes to make it work.

**Criterion 4 held.** Adding a second approach, of a different kind, at a
different field, worked by a different controller, changed exactly one file:
`core/route.py`, and every line of it is a number off a chart or a measurement
off the sim. Nothing under `src/marshall/atc/` was touched.

What makes an ILS simpler is ONE field. On a surveillance approach the
controller IS the approach aid and keeps the aeroplane to the ground; on an ILS
the aeroplane has localiser and glideslope, so he positions him and lets go.
`guidance` already carried that and `_inbound_within` already read it.

**The terrain had to be surveyed first.** Kobuleti carried no MSA and no MVA,
with a comment saying that was a real gap and that the day somebody flew an
approach here it should stop them trusting a vectoring altitude. So the terrain
was asked: 5 degrees, half a mile, out to 25 nm. A first pass at 10/1 found
8,135 ft; the finer one found 8,556, and 2,731 became 3,760 on the western
side. A peak between two samples is a peak nobody sees, and the difference was
a thousand feet of clearance that did not exist.

**Still to check in the air:** the plate (criterion 3) is not drawn — the
kneeboard renders Batumi's ASR and nothing reads `KOBULETI_ILS` yet, so a pilot
has numbers with no chart.

---

## [APP-3] Visual approaches, without having to argue for one — #10
labels: needs-flight-test

**Status:** REOPENED 17 August — criterion 3 has regressed and criteria 1 and 2
have not. Found by `tools/visual_check.py` in a pre-flight sweep with the sim
up, on a bridge restarted onto current code.

    C1  PASS  granted without an argument
    C2  PASS  0 mile calls after the visual clearance
    C3  FAIL  "field in sight" answered with "Batumi approach, go ahead"

The controller ASKED for that report one transmission earlier — *"cleared
visual approach runway one three, report the field in sight"* — and then
treated the answer as somebody keying the mic for attention. From the cockpit
it is a man who has forgotten what he just asked for, and it arrives on short
final while the pilot is waiting for a landing clearance.

Deliberately not fixed before the 17 August sortie: a rushed change to the
intent path an hour before a flight is worse than a known defect a pilot has
been warned about.
---

## [UI-1] Flight planning front end — #22
labels: feature

**Status:** PHASE 1 DONE 8 August — a plan can be filed from a page and the
board no longer needs a migration. Phases 2 (import) and 3 (the warbird nav-log
planner) are open; the proposal is `docs/PLANNER.md`.

A pilot files a plan before the sortie and the ATC knows him when he calls. The
schema arrives with [FP-1]; this is the way in.

**The DKB evaluation this issue has always asked for.** Digital Kneeboard
Simulator is a closed squadron platform, well ahead of anything we would build,
and it should not be raced. But its WW2 gap is STRUCTURAL rather than an
oversight: every machine-readable thing it exports — DTC profiles, TheWay Lua,
Loadout Lua — is a data-cartridge transfer, and its supported-aircraft list is
exactly the DCS modules that have a nav computer to load. A warbird has none.
There is nothing for it to export to.

Which means the artifact a warbird pilot needs is one DKB does not produce for
anybody: a timed nav log. `solve_route` and `kneeboard/navlog.py` already make
it.

**And DKB does not produce what THIS system consumes either.** All four of its
formats are pilot-facing documents; a filed plan here is an ATC input — what
Clearance reads back against, what `assigned_plans` records. The `flight_plans`
schema is already ICAO-shaped and already validates routes against the fix
table. The gap is narrow: nothing lets a human COMPOSE a plan. Every plan on
file was authored in a migration.

So: import from DKB (via TheWay Lua, which CombatFlite and DCSPlan also emit —
compatibility with the ecosystem rather than with one vendor), build the filing
half, and build the nav-log planner nobody else does. Not a second kneeboard
designer, which would be a second source of truth for the one thing this project
exists to keep singular.

**Blocked on one thing:** a real TheWay Lua export to pin the format. Guessing a
schema from a forum post is how a parser silently drops the last waypoint. The
`.miz` and DTC import paths do not need it.

**Acceptance criteria**
1. ~~A plan can be filed without touching the database by hand.~~ `/file`.
2. ~~A filed plan is assignable by voice on the night with no further setup.~~
3. ~~It survives a mission reload.~~
4. ~~A route naming a fix nobody holds is refused AT FILING TIME, with the
   offending fix named — not discovered on the radio.~~ Named one at a time, so
   a six-fix route says which of the six.
5. One plan serves both cockpits: a nav log for the P-51, DTC waypoints for the
   F-16, without being entered twice. **STILL OPEN — this is Phase 3.**

---

## [MAP-1] Situation map — #23
labels: feature

**Status:** TODO

Mine the old dcs-dedicated-server repo. A live picture of who is where and who
is working them — most of the data already exists in `tracks` and `flights`.

**Acceptance criteria**
1. Live positions, current controller, and assigned altitude for every flight.
2. Readable while a sortie is running, without touching the bridge.

---

## [CTL-1] Controller personalities: a roster of people, not sectors — #24
labels: feature

**Status:** TODO

Tables exist already (`controllers`, `sector_staffing`) and nothing reads them.
A voice belongs to a person, never to a seat, so the same somebody can work
Center tonight and Tower tomorrow and a pilot recognises him.

**Acceptance criteria**
1. A controller's voice and manner follow the person across sectors.
2. Staffing is data, not code.

---

## [HOOK-2] A hook is a condition, a promise, and a lifetime — #44
labels: feature

**Status:** TODO

[HOOK-1] shipped the timer and closed. Its second acceptance criterion — "a hook
whose condition has passed does not fire anyway" — implies the conditional hook
that was never built. `set_hook(seconds, why)` is all there is, so the agent has
to guess a NUMBER for something it knows as a CONDITION, and "call him when he
is established" becomes "call him in ninety seconds and hope".

    "hooks - I think that they should probably be in the database, and a
     callback manager should poll to see if the hook state is met. the hooks can
     be time, gis based (he is off track or out of my airspace), or maybe even
     conversation based (there is a break in the conversation, i can take care
     of low priority tasks that ive backlogged)"

And the collapse that makes it simple: **a commitment IS a pending hook.** There
is no separate store of what the controller owes people — the hooks not yet
discharged are that list, and showing it to him closes a blindness nobody had
noticed. `set_hook` is fire-and-forget today: the agent cannot see what it has
already promised, so it cannot avoid promising twice, cannot say it is busy, and
cannot tell you what it owes. `pending_hooks()` already exists in
`src/marshall/atc/agent/hooks.py` and nothing calls it.

WHERE EACH CONDITION IS EVALUATED IS A SPLIT, and worth deciding rather than
discovering. Time is either. Geometry belongs to the DIRECTOR, where PostGIS can
answer "outside this airspace" or "more than 2 nm off course" as a query against
`tracks` — the condition becomes SQL. A quiet frequency is knowable only by the
BRIDGE, which owns the radio. Both feed one due-queue and the bridge speaks,
which is the seam `/hooks/due` already is.

THE INVARIANT IS AT RISK HERE and the rule goes in before the code. A hook may
cause the controller to SPEAK; it may never cause him to SEQUENCE. "You are
drifting right of course" and "you are leaving my airspace" are the point.
Anything that assigns a level, a hold or a place in the queue comes from
`atc/controller.py` or the two-brain split has been routed around by the back
door — geometry-triggered callbacks are one short step from an LLM-authored
separation engine, and nobody would have to decide to build one.

DURABLE HOOKS RESURRECT THE GHOST. A promise in Postgres outlives the pilot: he
lands, de-slots, the mission reloads, and forty minutes later the controller
says "Falcon 1-1, calling as requested" to an empty sky. That cannot happen
today only because `_HOOKS` is a module-level dict that dies with the director.
Making it durable without binding it to a track reintroduces the exact failure
class that [ARCH-2] and [ARCH-3] were written for.

**Acceptance criteria**
1. A hook survives a director restart, and one whose aircraft has gone does not.
   `player_leave_unit` takes his pending hooks with him.
2. A hook is bound to a TRACK, not a callsign — the same rule the board learned.
3. Three kinds of `when` fire correctly: a time, a position condition evaluated
   in PostGIS, and a quiet frequency.
4. A position condition fires ONCE per crossing. "He is off course" is true
   continuously; the rearm rule is chosen deliberately and written down.
5. Every hook has an expiry, and one whose condition can no longer be met is
   dropped rather than accumulated — visibly, in the recorder.
6. NO hook path writes to the holding stack, assigns an altitude, or changes the
   sequence. Guarded by a test, not by intention.
7. The quiet condition does not fire while anybody is on final. The
   deterministic controller already knows who is; it is the gate.
8. The agent is shown its pending hooks with ids, and can discharge one — a
   promise settled early in conversation dies rather than firing later and
   repeating itself.
9. A promise made on one frequency is still kept on that frequency. This works
   today (`hook_frequency`) and must not regress.
10. Backlogged hooks drain in priority order when the frequency goes quiet,
    which is the controller's deferred-work queue and the reason for the
    priority field.
11. `docs/WIRING.md` gains a hooks section and the test card gains its rows, in
    the commit that builds this rather than afterwards. The label
    `needs-flight-test` goes on when there is something to fly.

Related: [#25] (the timer this grows from), [CTX-1] (which defines the PENDING
slot this fills), [ARCH-2] (identity), [ARCH-3] (the events that end a hook).

---

## [INT-1] The intent classifier is on Sonnet, and it is in the way — #45
labels: feature

**Status:** TODO — the counting half is FIXED (30 July); the model swap is not.

**FIXED 30 July: the counter.** `tracks` has a `category` column now, written by
the streamer that always knew it, carried into the scope prose on the lead AND
its wingmen, and `count_contacts` skips anything that is not an aeroplane. It is
also no longer doing "N ships" arithmetic — `units_on` returns every ship in a
formation as its own unit, so counting the text as well double-counted every
formation. Measured after, against the table below:

    contacts  engaged  scope
           1    False  one pilot alone
           1    False  one pilot + three T-55s parked 70 nm away
           2     True  one pilot + one AI flight
           2     True  a two-ship formation, alone

So a lone pilot in a mission full of armour is back on the cheap path, which
also removes the classifier from his radio checks. Guards:
`tests/test_bridge.py:TestGroundUnitsAreNotTraffic`. Still wants a flight test —
the 2.2 s that disappears is only visible on the radio.

**STILL TODO: the model.** Everything below the table stands.

`bedrock_intent.classify` calls **Sonnet** (`bedrock_intent.py:28`, default
`us.anthropic.claude-sonnet-4-5`) to put a transcript into a fixed taxonomy with
a fixed schema. The 29 July audit benched it at **2.2 seconds**, and it runs
BEFORE `intents.dispatch` can advance the deterministic controller — so it is
not a background cost, it is dead air between the pilot releasing the button and
anything happening.

THIS IS A LATENCY ISSUE THAT HAPPENS TO SAVE MONEY, not the other way round. A
fixed label set with a schema is the job Haiku exists for, and the tier is
already wired and dormant: `FAST_MODEL_ID` in `director/app.py:68` is Haiku 4.5,
`MARSHALL_FAST_TIER` gates it, and `agent.model` is swapped per call at
`app.py:189`. Nothing needs building; something needs measuring and switching.

WHAT MAKES THIS SAFE TO TRY. `tools/classify_bench.py` already scores the
classifier against the phrasing pilots actually use, per model — it was written
for exactly this question. So the decision is a measurement rather than an
opinion, and the note in CLAUDE.md is worth heeding while making it: "the
taxonomy wording moves the score more than the model does." If Haiku scores
worse, the first thing to try is the prompt, not a bigger model.

AND IT FIRES TOO OFTEN, which is a separate defect on the same path and is NOT
free to fix. Measured 29 July:

    contacts  engaged  scope
           1    False  one pilot alone
           5     True  one pilot + four T-55s parked 70 nm away
           2     True  one pilot + one AI flight 62 nm away at FL200

`count_contacts` counts every ` | ` segment and every "N ships", so
`engaged = ... or n_contacts >= 2` goes true for a lone pilot as soon as the
mission contains armour or distant AI — which every test mission does. That
skips the canned short-circuit at `agent_atc.py:3208`, routes even a radio check
through `separation_context` and therefore through this 2.2 s classifier, and
engages the deterministic engine to sequence one aeroplane against a tank. It
defeats the design note at `:3192` that promises a single ship stays on the
cheap path.

THE OBVIOUS FIX WAS NOT AVAILABLE — it is now, and it is what was done. Kept as
written because the reasoning is what made the migration worth doing rather than
reaching for one of the cheap workarounds it rules out. The streamer subscribes
per category —
AIRPLANE, HELICOPTER, GROUND, SHIP (`tracks.py:231-234`) — and then drops it:
`tracks` has `name, type, coalition, player` and NO category column. So neither
the picture nor the counter can tell a T-55 from an F-16, and every cheap
workaround has a counter-case. Counting only MANNED contacts breaks the
AI-backed rehearsal harness and real AI traffic the controller does work.
Counting by type needs an allowlist that fails toward switching the engine OFF,
which is the dangerous direction. A radius filter is a design decision about what
counts as terminal-area traffic, not a bug fix.

So this wants a `category` column on `tracks`, written where it is already known,
and then a decision about whether the picture carries it. That is a migration
plus the radar-picture contract — the artefact with one producer and six
consumers that has bitten twice this week — and it is not a thing to do quickly
before a sortie. It is, however, probably worth more than the model swap.

**Acceptance criteria**
1. `classify_bench.py` is run against Sonnet and Haiku on the same corpus and
   both scores are recorded in the commit. The decision cites the numbers.
2. Measured round-trip latency for a classification, before and after, on the
   same box.
3. A wrong classification cannot reach the separation engine unchallenged --
   whatever the tier, `intents.dispatch` still owns what the controller does.
4. The single-ship path really does skip the classifier, verified with one
   aeroplane and AI traffic on the scope, which is the case that defeats it
   today.
5. If Haiku loses on the bench, the taxonomy wording is tried before the model
   is. The attempt is recorded either way, so nobody repeats it.
6. `docs/WIRING.md` says which model classifies intent and what it costs in
   time -- today it does not mention the classifier's tier at all.

Related: [#1] (the plans it routes to), the 29 July audit findings 2.x and 6.x.

---

## [FP-2] Which plan he means, without a hand-maintained word list — #46
labels: feature

**Status:** TODO

`plans.pick` matches a spoken request to a filed plan by word overlap, scored
against `_NOISE` -- **a stop-word list with 126 hand-maintained entries**
(`src/marshall/atc/plans.py`). It works until somebody says an ordinary thing that
is not on the list, and then it fails in the worst available way: a request that
names nothing scores zero, hits the "he named somewhere nobody filed for" branch,
and the pilot is told nothing on file matches.

That is not hypothetical. On 28 July a pilot said *"we'd like to open the flight
plan"* and was refused, because `open` was not in the list. The fix was to add
`open`, `activate`, `pick`, `pickup` and four more words -- which is the same
fix again, and will be the same fix next time.

NOTE WHAT THIS IS AND IS NOT. There is **no model call here today**; this is pure
Python. Embedding the request would ADD a small cost rather than save one, and
that is the honest trade: it buys the deletion of a list that has already failed
once, in the one place in this system where the meaning is genuinely open
vocabulary even though the ANSWERS are a closed set of six plans. Everywhere else
that speech is matched -- flight names, handles, callsigns -- the set is small
and known and edit distance is instant, deterministic and testable. Do not
generalise this to those.

WHY IT FITS HERE AND NOWHERE ELSE:

  * the answers are six rows, not open ended;
  * the plans have prose descriptions already (`task`, `route`) that read like
    what a pilot would say -- "CAS over Tsutsnvati", "weather reconnaissance out
    to Ingress";
  * `pgvector` is already an installed extension on that database and nothing
    uses it. So is `pg_trgm`, which would do the fuzzy half in SQL.

The plan embeddings are computed ONCE -- they change when somebody files a plan,
not per transmission -- so the per-request cost is one embedding of a short
utterance.

**Acceptance criteria**
1. The 126-entry `_NOISE` list is gone, or reduced to something nobody has to
   maintain by hand.
2. Every case in `tools/plan_sweep.py` still behaves, including the ones that
   must ASK rather than guess and the one that must REFUSE a plan nobody filed.
   Ambiguity is still answered with a question.
3. "Open the flight plan", "pick up my IFR", "activate my flight plan" and
   "ready to copy" all resolve without any of those verbs being enumerated
   anywhere.
4. A request naming somewhere nobody filed for -- "clearance to Vaziani" -- is
   still refused rather than matched to the nearest thing. Similarity has a
   floor, and the floor is chosen from measurement.
5. Plan embeddings are computed on file/update, not per request, and the
   per-transmission cost is stated in the commit.
6. It degrades honestly: if the embedding call fails, the controller asks which
   plan rather than guessing or erroring.
7. `docs/WIRING.md`'s flight-plan section describes how matching works after the
   change.

Related: [#1] (FP-1, the plans themselves), [INT-1] (the other place a model
belongs), and the 28 July finding recorded under FP-1.

---

## [RAD-5] The geometry reads structure, not prose — #47
labels: architecture

**Status:** BUILT 30 July, unflown. Five of six acceptance criteria met; the
sixth (deleting `flatten_formation` and the regexes) is gated on migrating the
test fixtures, not on the code.

**Remaining scope (10 Aug).** Structured contacts, category and most consumers
are in the tree and tested. What is left is **fixture migration, then deleting
the fallback regex path and `flatten_formation`** — the parsers are the thing
this issue exists to remove, and they are still reachable.

**What landed.** `/radar` serves `{picture, contacts, bullseye}`. Positions are
ABSOLUTE — the old `nm`/`radial` were measured from a module constant, so every
consumer on the map read ranges from Batumi and got its traffic sorted by
distance from it. The bridge draws its own picture (`atc/picture.py`) from its
own origin, projected through the sim by `push_fixes` and kept in `PROJECTED`.
Byte-identical for a shared origin, proved against prose captured from the
running director (`tests/test_picture.py`), and the golden earned its keep at
once: a parked aeroplane reports 3.66e-06 knots, which is truthy, so a `> 0`
test would have silently dropped the field.

**Bullseye is asked for, not defined** — DCS has one per coalition and every
pilot's HSI is referenced to it. It is a RENDERING, like field-relative and
BRAA; storing it would repeat this bug with a better-chosen point, and would
make a talkdown worse.

**Two things the prose could not express, now tested.** A wingman has a
position, so `miles_between` is exact for the case the join rule actually runs
in instead of returning an upper bound. And formation membership is a FACT, so
`_track_tagged` can let Pony 1-3 borrow the section's tag while Falcon 1-1 still
never gets Falcon 1-2's track.

**The cold-cache path was the last thing forcing prose**: `radar_live` returned
a string and nothing else, so the one moment consumers fell back to regexes was
also the moment the picture was degraded. `contacts_live` degrades in the data
too, with the unknowable fields empty rather than guessed.

**Still open:** ~six test files describe scopes as English strings, because that
is what the system consumed when they were written. Migrating those fixtures to
contacts is what lets `flatten_formation` and the six regexes be deleted.

**And it reframed [#2].** ARCH-1 is not "add another airfield" — it is **split
the world from the controller**. The director is currently both: a track cache
(one sim, one world, correctly shared) fused to one controller's brain (the
plate, the prompts, the approach, and until today the origin), and
`_system_prompt_for(session_id)` builds the same Batumi plate for every session.
A bridge is a RADIO HOST, not a controller — it already answers as four of them
by frequency via `profile.station_on` — so N controllers means N profiles,
origins and separation engines hosted in however many processes are convenient,
not N bridges.

**Was:** TODO

    "we've spent DAYS chasing ghosts (literally)"

We have, and this is where most of them came from. The director holds every
track in PostGIS with real coordinates, renders them down to one English string,
and the bridge parses that string back with **six separate regexes** to recover
numbers that existed as floats one process away.

  producer  `feed/tracks.py` — `_clusters`, `_unique_labels`,
            `_render`, `_other_ship`
  consumers `identity.units_on` (`_SCOPE_LINE`, `_FORMATION`, `flatten_formation`),
            and `agent_atc`'s `_FIX`, `_FIX_BY_TRACK`, `_TYPE`, `_scope_geometry`

WHAT IT HAS ALREADY COST, all of it in three days:

  * a formation line defeated **every** parser at once, so both aeroplanes in a
    formation vanished from the identity ladder -- and forming up is what a pilot
    does immediately before asking to join a flight;
  * `flatten_formation`, added to fix that, deletes the wingmen before the
    position regexes see them, so no aircraft but a lead has a position;
  * `radar_fix` needs a BRACKETED tag that only exists after `identify` has run,
    so guidance was None for a pilot radar could see perfectly (finding 1.3);
  * `count_contacts` cannot tell a T-55 from an F-16, because the streamer knows
    the category and `tracks` has no column for it.

Every one of those is the same defect: **a presentation decision applied to the
data.** The collapse is right for the controller -- four ships in trail ARE one
contact to a human -- and it is nonsense for geometry, which needs every
aeroplane's position regardless of how it is being drawn.

THE FIX IS ADDITIVE AND CAN BE MIGRATED ONE CONSUMER AT A TIME. `/radar` serves
both:

    {"picture": "...unchanged prose, for the agent's prompt...",
     "contacts": [{"name": ..., "label": ..., "callsign": ..., "type": ...,
                   "category": "airplane", "manned": true, "on_ground": false,
                   "range_nm": ..., "radial": ..., "alt_ft": ..., "heading": ...,
                   "speed_kt": ..., "formation": "362nd_Sockeye-1"}]}

The prose stays exactly as it is. The geometry stops being a parser.

AND IT GETS WORSE WITH MORE AIRFIELDS, which is why it belongs before [ARCH-1]
rather than after: every airport multiplies the contacts on that string, and
range/radial are relative to ONE beacon today.

**Acceptance criteria**
1. `miles_between`, `radar_fix_by_track`, `_scope_geometry` and
   `aircraft_type_on_scope` read the structured contacts. No regex of the
   picture remains on the geometry path.
2. `identity.units_on` reads structure too, and `flatten_formation` is deleted
   rather than fixed -- it exists only to paper over the lossy string.
3. Every aircraft has a position, formation member or not, which closes the
   wingman gap without touching the prose.
4. `category` is carried from the streamer, where it is already known, so
   `count_contacts` can count aircraft -- closing the half of [INT-1] that is
   not a model swap.
5. The prose picture is byte-identical for a scope the agent already handles, so
   this cannot change what the controller says. Proved by a test, not by eye.
6. `docs/WIRING.md`'s radar section describes the contract as data plus a
   rendering of it.

Related: [#40] (identity reads it), [#2] (ARCH-1, which this should precede),
[#45] (INT-1's counting half), and themes 1 and 4 of the 29 July audit.

---

## [ENG-2] Engineering answers when nobody is watching a terminal — #28
labels: feature

**Status:** TODO

Engineering is turning into half the point of flying this, not a debugging
convenience — so it should not depend on a person having a log tail open.

**The split that already exists, and should be kept.** The CHANNEL is durable:
it records every note (`build/debug-notes.md` and the flight recorder) and always
answers with its own state, so a pilot is never talking into silence. The
RESPONDER is separate and may be absent — `tools/bench.py` is exactly that
boundary. What is missing is a responder that is a *program*.

`claude` is installed on the host, so a responder can be a headless session
given the note, the recent bridge log and the radar picture. That is the shape:
`tools/bench.py claude` claims the bench and answers from then on.

**Acceptance criteria**
1. With no human at a terminal, asking for engineering gets a real answer to the
   question asked — not just an acknowledgement.
2. The pilot can always tell WHAT he is talking to. A model answering must not
   sound like a person who is reading; the ack says which it is.
3. Immediate acknowledgement, answer when it arrives. A model takes seconds to
   tens of seconds and a silent radio reads as broken — the deterministic ack
   already solves this and must stay in front.
4. With no responder at all, behaviour is unchanged: *"not at the bench, keep
   talking, every word is recorded"*, and the note is still durable.
5. Notes survive a mission reload and a bridge restart, and can be read back by
   sortie afterwards.
6. Bounded cost: a rate limit and a per-sortie ceiling, so a chatty channel
   cannot run up a bill unattended.

### The line: engineering is out-of-world, the controller is in-world

This is the distinction that makes the whole thing coherent, and it is not about
who is allowed to talk.

The **controller** knows what a controller knows: the radar picture, what was
agreed on the radio, the plate. He is in the fiction, and he gives clearances.

**Engineering is outside it** and can see GROUND TRUTH — the `tracks` table, the
flight recorder, the bridge log, what the engine actually computed for a given
aeroplane, whether a spawn really produced what it claimed. That is precisely
what a pilot needs when the world and the fiction disagree:

> *"hey engineering, sentry says there is a tank down there, I don't see it. Can
> you confirm it's there and tell me where it is"*

No controller could answer that without breaking. Engineering can, because it is
querying the sim rather than reading a scope — and "the spawn reported success
but nothing is in `tracks`" is a real answer that has already happened once.

**Engineering never gives clearances**, vectors, altitudes or separation. Two
voices with one brain is the confusion this project has spent three sessions
removing, and the pilot must never be unsure which he is talking to.

### It MAY change things, with consent on the radio

Explicitly wanted: on-the-fly changes during a test flight are most of the cycle
time saved. Fixing something between two approaches is the loop that made
squadron night productive.

The residual risk is not the edit, it is the TIMING. Loading a bridge change
drops the radio for about twenty seconds, and doing that to a man at four miles
in cloud is unkind however good the fix is. So consent covers *when* as well as
*what* — "I will load it while you are climbing out" — and engineering says when
it is back, which is what a human engineer did by hand all of squadron night.

Depends on nothing. [ENG-1] (#4) should be flown first — there is no point
automating a channel whose basics are unverified.

---

## [ASR-2] On final, correct him RELATIVE to what he is flying — #37

labels: feature, needs-flight-test

**Status:** TODO — Hoover's, and it removes a whole class of error.

    "when in the final phases they say left 10 right 5 and don't bother with
     headings... once established, doing this would avoid all dg drift and mag
     compass problems"

    "vectors to the [FAF] should be with headings (rounded to the nearest 5) and
     once established, just corrections relative to current course"

This is how a real surveillance approach is flown, and it is also the only form
of guidance that cannot be broken by the pilot's instruments. An absolute
heading is only as good as the gyro he sets it on, and a directional gyro
DRIFTS — Hoover's read seven degrees off the compass on the runway, and the
compass in the same airframe read sixteen off the map. A relative correction
needs none of that: "turn left ten degrees" means the same thing whatever his
gyro says, because the controller is watching the track on radar and the pilot
only has to turn.

It also fixes a real asymmetry. We compute a heading in true, convert it to
magnetic, and speak it — and every one of those steps can be wrong. A relative
correction is computed from the SHAPE of his track and needs no frame at all.

**Two phases, two forms**

* **Vectoring to the final approach course**: absolute headings, rounded to the
  nearest 5. A pilot repositioning has time to set a gyro, and a round number is
  easier to hold and read back.
* **Once established**: relative only. "Turn left ten degrees." "Turn right
  five." No heading, no altitude repetition — the mile calls carry those.

**Acceptance criteria**
1. Outside the final approach fix, headings are absolute and end in 0 or 5.
2. Inside it, corrections are relative and no absolute heading is spoken.
3. The relative correction is derived from observed TRACK, not from a heading
   the controller believes he is flying.
4. A pilot with a deliberately mis-set gyro can still fly the approach to
   minimums — which is the whole point, and is a flight test nobody could have
   passed before.

Related: [#35] and the frame work in `route.py` — this is the belt to that
braces, because it makes the approach immune to the class of bug that cost a
night.

---

## [ID-4] A callsign is a POSITION, not a person — model identity properly — #38

labels: architecture, needs-design

**Status:** TODO — design first. Do not build the obvious fix.

**Needs a current-state design note before implementation (10 Aug).** #41
changed the event and slot assumptions this was written on, and it overlaps
#40 without duplicating it. Write down the actual keys, their lifetime and
cleanup, the known collision path, and the exact failing test or live scenario
to be solved — then work it. Starting from the narrative below would be
refactoring against a system that no longer exists.

    "Falcon 1-1 is not a person, it's a position in a flight. A person might
     participate in different flights in a night."

    "how do I reset it without engineering help? What happens in the future if a
     pilot changes slots and call signs?"

Both questions come from the same mistake: the system stores **one** binding
where there are **three** different things, and the one it stores is the least
stable of them.

**The three things**

| | what it is | how long it lasts | how we learn it |
|---|---|---|---|
| **person** | a human being | a night, or years | SRS transmitter name |
| **aircraft** | a track on radar | one slot | the sim's unit; labelled with the player's name while a human is in it |
| **position** | "Falcon 1-1" | ONE SORTIE, sometimes less | he says it on the radio |

Today `contacts` stores position → aircraft and nothing else, so a position that
outlives its sortie captures the next aeroplane. That is exactly what happened:
a tag reading `Hammer 1-1` from a Jug sortie twelve hours earlier sat on an F-16
whose pilot was calling himself Falcon 1-1, the geometry could not match him,
and the controller improvised two entire approaches without one deterministic
call. A two-hour expiry was added as a stopgap; it narrows the window and does
not fix the model.

**Why the obvious fix is wrong**

Matching the SRS name to the radar label is a good signal — they are the same
string, because both are the player — but binding *that* to the callsign
recreates the same error one level up. It says "this person IS Falcon 1-1",
which stops being true the moment he flies the second sortie of the night as
Pony 1-3, or hands the lead position over and becomes Falcon 1-2.

**What to think about instead.** The physical fact is person ↔ aircraft, and it
is knowable on every single transmission without anybody being asked: the voice
carries an SRS GUID, the GUID gives a name, and the name matches a track label.
The POSITION is then just what that person is answering to at this moment, taken
from the words he is currently speaking.

If that holds, the binding stops being state at all. It is COMPUTED per
transmission, nothing is persisted, and the answer to "how do I reset it" is
that there is nothing to reset — a wrong association cannot survive one call.
Some memory is still wanted for an aircraft that is not currently talking, so
the scope can label it; that is a cache with a short life, not a record.

**Cases the design has to answer**

1. Same person, second sortie, new callsign. Correct on his first transmission,
   with no engineering and no spoken ritual.
2. Same person, changes slot mid-night. Already works today, must keep working.
3. A position handed over — lead goes home and number two becomes lead.
4. Two people, one after the other, in the same position.
5. A pilot whose SRS name does NOT match his DCS name, or a visitor. This is the
   case the automatic path cannot serve.
6. AI flights, which have a callsign and no person at all.
7. Two people with the same SRS name. Ambiguous; ask rather than guess, the same
   rule as a formation that has broken up.

**For case 5, the period-correct answer is TURN IDENTIFICATION.** There is no
transponder in 1944 and none in DCS, so a controller identifies a track by
asking for a turn and watching which one turns: *"turn left thirty degrees for
identification"*. It needs nothing from the pilot but a heading, it is how it was
actually done, and it gives the pilot the reset he asked for without inventing a
command that does not exist in aviation.

**Acceptance criteria**
1. A person flying a second sortie under a different callsign is tagged
   correctly on his first transmission, with no operator action.
2. A tag from a previous sortie can never apply to a current aeroplane.
3. Changing slot keeps the identification.
4. A callsign handed from one pilot to another follows the words, not the
   history.
5. A pilot whose name does not match can be identified by a turn, and it works
   without engineering.
6. There is no "reset" command, because there is nothing durable to reset.

Related: [#12] (the first identity work), [#13] (ghost callsigns — the same
lesson, that a name is not an aeroplane), and the two-hour expiry now in
`identify.py`, which this should make unnecessary.

---

## [FT-1] Call the result on the radio; the card keeps the score — #31
labels: feature

**Status:** TODO

Flying the card produces results that currently live only in a pilot's memory
until he lands, and the ones that matter most — the failures — arrive with
detail that is lost by then.

Three ways were considered:

- **OpenKneeboard's doodle.** Ephemeral, and not machine-readable, so it can
  never become an attestation.
- **Checkboxes on the page.** Machine-readable, but it needs you to look at and
  touch the kneeboard at exactly the moment you are busiest.
- **Say it on the engineering channel.** Hands-free, uses a channel that already
  exists, already timestamps, already logs.

The third wins, and not only because it is hands-free: **a spoken result carries
context a checkbox cannot.** "B4 fail" is worth much less than "B4 fail, he
stepped on me at four miles", and the description is the part that gets fixed.

It also makes the second option free. Say it, and the page shows it — voice in,
card keeps the score, hands never leave the stick.

**Acceptance criteria**
1. *"B4 pass"* / *"B4 failed, he talked over my readback"* on the engineering
   channel is recognised, stored against the test ID, and **acknowledged on the
   air** so the pilot knows it landed.
2. Free text after the verdict is kept verbatim. It is the valuable half.
3. `/flighttest/` shows what has been called this sortie — a row already
   reported reads differently from one not yet flown.
4. Results carry the timestamp, the callsign and the COMMIT, so they can become
   an attestation without being retyped (`tools/attest.py`).
5. A result for an unknown ID is refused out loud rather than silently filed —
   "say again, I do not have a test D9".
6. Ordinary engineering talk is not mistaken for a verdict.

**A verdict should be ONE transmission, not three.** Today reporting a result
means summon, report, release — and forgetting the release leaves the controller
deaf to you, which is worst at exactly the moment you are most likely to forget.
Naming a station now releases the line automatically (a safety net, not the
answer). The answer is that *"B4 pass"* should be a one-shot report that never
takes the channel over at all.

**Watch for:** the transcriber. "B4" and "before", "C1" and "see one" are exactly
the kind of thing Whisper mangles, and a mis-parsed ID silently scores the wrong
row. The vocabulary priming already helps; the IDs should be in it, and an
unrecognised ID must fail loudly per criterion 5.

Depends on [ENG-1] #4 being flown — this is more traffic on a channel whose
basics are still unverified.

---

## [ID-7] Nobody may name himself — the label comes off the aeroplane, not the radio — #48

labels: architecture, needs-flight-test

**Status:** BUILT 30 July, unflown. Guards: `tests/test_identity.py`
(`TestNoOneMayNameHimself`), `tests/test_formations.py` rewritten whole.
**Tests:** card section N. **Code:** `atc/identity.py`, `atc/agent_atc.py`,
`atc/controller.py`, `director/prompts/rules.md`.

    "that self-designated callsign crap was the cause of a lot of problems.
     And we should just rip it out now"

WHAT A CALLSIGN WAS. The label a pilot spoke became the key the separation
engine held him under, which is the single root the last month of identity bugs
grew out of: ghost aeroplanes minted from read-back fragments; a board keyed on
strings Whisper guessed at; a pilot stuck as "Pony 1-1" for a whole approach
after he started flying as Falcon 1-1, radar tracking one aeroplane while the
engine sequenced another; and "Apex 1-2" — a member designation — becoming a
name the controller addressed a man by, which nobody does on the air.

WHAT IT IS NOW. A person is his HANDLE, out of the same chain the identity is:

    SRS GUID -> SRS client name -> sim unit -> track

A flight has a name. A member number is neither, and cannot become either. What
he SAYS is still used — matched against a filed strip or a track, to decide
WHICH identity he is — it just never decides what that identity is CALLED.
`Identity.plan` carries the strip he matched so the board and the flight-plans
table can still be joined.

FOUR DOORS WERE SHUT, and the last two were only visible once the first two
were:
  1. `_label` returned the spoken callsign. Now `_handle_for`.
  2. Rungs 2 and 3 matched a strip and then USED ITS NAME.
  3. The intent classifier's MEMBER callsign could overwrite the label.
  4. A radar BRACKET could key the engine. The bracket is only there because
     something correlated it from speech earlier, so that put "Pony 1-1" on the
     board by a longer route.

The handle is case-folded, because the sim says "362nd_sockeye" and SRS says
"Sockeye": without it a pilot acquired by radar after checking in on a strip
silently changed key, and everything stored against the old one was lost.

FORMATIONS CHANGED WITH IT, because the engine minted member names off the
flight key and that only ever worked while the key looked like a callsign:

    "if a flight wants to fly an approach in formation - they can. That's up to
     the flight lead. But only the lead's a/c is used for vectors."
    "if they want to fly individual approaches, they request/announce breakup -
     then each check in with an intention."
    "ATC should NEVER initiate a breakup."

So: a flight flies the approach as a flight if lead wants to; the three places
that broke one up unasked are gone; the break-up names nobody and asks each of
them to check in as himself; and vectors come off the lead's track whoever keys
the mic.

FOUR BUGS FOUND WHILE DOING IT, each invisible before:
  * a dissolved flight kept the LETDOWN, so all four members held and nobody was
    ever cleared — unreachable until a flight could be cleared before splitting
  * `seen_on_final` called `get()`, which CREATES, merely to read a phase; the
    stray single it left was then mistaken by `_enter` for an already-split
    flight. Two wrongs that cancelled until the minting went
  * `say_again_who` read out "I have ." with an empty list
  * the position-rejection check looked up range by a callsign the scope no
    longer prints, so it silently stopped rejecting anything

THE DIRECTOR'S PROMPTS WERE THE OTHER HALF and were contradicting the bridge.
`rules.md` said **"Callsigns are as spoken. Use whatever callsign the pilot
gives, exactly"**, and its formation section still described ATC-initiated
break-ups, the deleted visual-separation question, and assigning a ladder of
levels. The agent was doing all three from the prompt alone — the dry run caught
it inventing four altitudes for four aeroplanes, which is the invariant.

**Acceptance**
  * no board key, no recorder row and no transmission contains a member
    designation for a man who is not in a flight
  * a pilot who checks in as one callsign and flies as another is never
    challenged about it and never changes key
  * a formation is only ever broken up after the flight asks
  * with a flight together, every range and heading describes the LEAD
  * the agent never assigns altitudes inside a formation

**Open, and it is the reason this needs flying.** The agent still mostly
addresses him by the callsign he spoke rather than by the handle it was handed.
That is prompt adherence rather than architecture — the identity underneath is
correct either way — but it is the difference between "Sockeye, radar contact"
and "Pony one one, radar contact" on the air, and only a pilot can say whether
being called by his handle is right.

---



## [ARCH-6] `agent_atc.py` is the bridge, the loop, the monitor and the assembly — #55
labels: refactor

**Status:** PARTLY DONE — 5,802 lines down to 4,713 on 3 August and back up to
**7,516** by 18 August. Criteria 1 and 3 are met; 2 is not, and the line count
going the wrong way is the honest measure of why it matters: this is the file
every live fix lands in.

**One thing came out of it on 18 August and it was not the extraction.**
`agent_atc.main` — the `__main__` block as a function, so `marshall-atc` is a
real command (#147 criterion 3). That had been filed under THIS issue, beside
`marshall-radio`, on the reasoning that "the receive loop is `_run_srs` inside
`agent_atc.py`'s own `__main__`, so there is no function to name. Two
entrypoints wait on one extraction."

Half true, and the wrong half held both. `marshall-radio` is a separate PROCESS
and genuinely waits on separating the transport from the control — this issue.
`marshall-atc` IS this process and wanted nine lines of argument parsing lifted
out of an `if` block. **A blocker that applies to one of two things filed
together will hold both until somebody asks which.**

**Remaining scope (10 Aug).** `voice`, `talkdown`, `addressing` and `assembly`
are extracted and the dry-run and live paths share assembly. What is left is
criterion 2 alone: **separating loop-owned state from the guards that read it**,
so `_run_srs` and `asr_monitor` become callable by a test. This is a scoped
refactor, not evidence that the bridge is still a monolith.

It is the file every live fix lands in, which is exactly why it keeps growing
and exactly why that is dangerous: the receive loop, the radar injection, the
hook scheduler, the guards and the message assembly shared one namespace, so a
change to any of them could reach any other and nothing said so.

Four modules are out, chosen because each needs NOTHING from the loop — every
one takes what it uses as an argument, so the cut is provable rather than
hopeful:

    voice.py       what reaches the radio, and what must never leave the room
    talkdown.py    the ASR metronome: where he is, in words, every mile
    addressing.py  was this call for me, and did he read back what I gave him
    assembly.py    everything the controller is handed for one transmission

A PURE RE-EXPORT WOULD NOT HAVE BEEN SAFE HERE, unlike `route.py`. Tests
monkeypatch `A.fetch_radar` and `A.record`, and a caller in another module holds
its own reference — so the patch would silently stop biting and the test would
go on passing against the real network. The four blocks that moved have no patch
surface, which is part of why they went first.

**What it fixed on the way.** `atc_dryrun.py` assembled its own copy of the
message, with a comment admitting the hazard: every change had to be made twice
or the mirror drifts. It HAD drifted — "the radio calling itself {known}"
survived there for weeks after the label stopped coming off the radio, so the
tool whose whole purpose is showing what the bridge sends was showing the
opposite. It calls `compose_message` now.

Two tests in `test_manner.py` greped the bridge's SOURCE for `YOUR MANNER:` and
for the literal `me, "manner"`. Both broke on the move while the behaviour they
guarded had not changed — the signature of a test written against the wrong
thing. They call the composer now, and there is a third: a station with no
manner must get no fence.

**Acceptance criteria**
1. ~~The message assembly — what the agent is told, in what order — is a module
   that can be tested without a radio.~~ `assembly.compose_message`.
2. The guards are separable from the loop that runs them. **STILL OPEN** — the
   guards read and write loop state, so this needs the state to move first.
3. ~~`tools/atc_dryrun.py` and the live bridge drive the same assembly code.~~

**What is left, and why it is harder.** The remaining 4,713 lines are the
receive loop, the radar/scope readers, the guards and the director's HTTP
client. The client is the next clean cut but it carries the monkeypatch surface,
so it moves with its test doubles or not at all.

---

## [OPS-8] The director API is unauthenticated and published to the LAN — #74
labels: architecture

**Status:** OPEN. Raised by the Codex audit, 10 August; the database half is
fixed, this half is deferred deliberately.

`director/docker-compose.yml` publishes the agent on `8000:8000` — every
interface — and `docs/WIRING.md` confirms the HTTP surface has no
authentication. It owns prompts, sessions, flight state and mutating endpoints,
so anything on the LAN can rewrite the controller's brief.

**Why it is not simply bound to loopback like Postgres was.** The kneeboard is
a container in another compose project and reaches the director as
`host.docker.internal:8000` — across the docker bridge, not over 127.0.0.1.
Binding loopback is the obvious hardening and the one an audit recommends, and
it silently breaks every kneeboard page that reads live state. Verified before
changing anything, which is why only the database moved.

Two real fixes, either acceptable:

1. Put the kneeboard on the director's compose network and address the agent as
   `agent:8000`, then bind `127.0.0.1:8000:8000`. Cleanest; needs the kneeboard
   deploy to move.
2. Give the API a shared token and require it, so LAN reachability stops being
   equivalent to authority.

Deferred rather than half-done: a change that breaks the kneeboard mid-sortie is
worse than the exposure it removes on a LAN nobody else is on. Not a licence to
leave it — it becomes wrong the moment anybody else connects.

---

## [ARCH-11] Audit for a fix applied to one call site and not its siblings — #76
labels: architecture, tooling

**Status:** OPEN. Raised by [OPS-9], 10 August.

`tools/unwired.py` finds a correct thing nothing reaches. It cannot find the
other half of the same disease: **a correct thing reached from three places, two
of which still ask the old way.**

Three instances, all found by somebody else rather than by us:

| | |
|---|---|
| `Controller._me` | read in six places, assigned in none |
| `station_for` / `channels_for` / `"ABCD"[i]` / `field_origin` | four questions that had one answer until Kobuleti |
| `seen` vs `fix` vs airframe vs ground check | one moved to the track, three did not — [OPS-6] finding 1 |

The shape is always the same and always invisible to reading: several call sites
asking the same question by different routes, where the routes agreed until a
second field, a second map, or an untagged contact made them disagree. The wrong
answer is never absurd — it is a real controller, a real frequency, a real
distance, belonging to something else.

**Sketch.** For a given helper pair (`radar_fix` / `radar_fix_by_track`,
`station_for(role)` / `station_for(role, field)`), find call sites of the WEAKER
one that sit in the same function as a call to the stronger. That is exactly the
signature of a half-applied fix, and it is mechanical. Start with the pairs we
already know are hazardous rather than trying to discover them.

Not a lint rule — a repo-shaped check, like `unwired.py`, with a baseline so it
is not always red.


---

## [SEAM-1] A decided fact that is not spoken must not be silently lost — #79
labels: bug, architecture

**Status:** OPEN. Highest priority of the split-brain seam work.

**28 AUGUST: NOT FIXED, AND THE DIAGNOSIS CHANGED.** A pilot flew an ILS with
five vectors decided and none transmitted. I reported that as the engine
deciding and the air losing it, which was wrong. The vector monitor never saw
the aeroplane at all: nothing had assigned him an approach (#177), so
`_pro(ac)` was None, `may_vector(None)` was False, and every arrival mechanism
skipped him.

Four silent `continue`s on the path to the monitor now name themselves --
no bound track; the picture does not hold it; no procedure assigned versus a
letdown he flies himself; `may_be_vectored` refusing, which is six conditions
wearing one face. A refusal that does not name itself is what made a mute
approach a day-long mystery.

Whether vectors now TRANSMIT is unproven: the ghost harness cannot check in
with Approach the way a pilot does, so the last gate is untested. Card row H32.

`decision.py` already knows the answer and does nothing with it:

> *"It does not (yet) change the transmission; it MEASURES the seam."*

The engine decides an altitude, a heading, a runway, a frequency, a station. The
agent phrases it. `Decision.verify` compares the two and prints `NOT VOICED` when
a fact did not survive — and the transmission goes out anyway. **On one sortie
three of seventeen issued altitudes never reached the air**, which is the
observation that produced the module.

This is the half-built shape this repo keeps finding: a correct mechanism whose
output nothing acts on. A referee that watches and never blows the whistle.

`phrasebook.py` is the intended deterministic rendering and is imported by
`asr.py`, `controller.py` and `decision.py` — but **not by `agent_atc.py`**, so
it is not on the response path at all.

**Status:** BUILT 10 August, needs a pilot. Offline evidence and tests
are below; what it changes is what the RADIO says, so a sortie closes it.

**The evidence was already on disk** — no flight required. `NOT VOICED` has been
recorded to the flight recorder all along, and every sortie ever flown holds
exactly five, which split cleanly around the `Controller._me` fix at 19:43:52 on
9 August:

| when | miss | what it was |
|---|---|---|
| 19:31, 19:32, 19:34 | `taxi: one three` | **before** the fix — the ENGINE granting a taxi clearance from *Clearance Delivery's* frequency, because `_owns` returns True when `_me` is unset. The agent correctly refused to voice it. Already fixed |
| 19:41:54 | `cleared_takeoff: one three` | engine: *"runway one three, cleared for take-off, wind zero nine zero at six"*. Transmitted: **"Sockeye, roger."** |
| **20:52:33** | `refuse: one three three decimal zero, Kobuleti Tower` | **after** every fix that day. Engine: *"Take-off is Tower's, contact Kobuleti Tower one three three decimal zero."* Transmitted: **"sockeye, Kobuleti Ground, go ahead."** |

An aeroplane cleared for take-off and never told, and a pilot refused a
clearance and never redirected — #65's failure surviving as an agent-side
omission. Both from a controller who sounded fine.

**The verifier had to get stricter before it could be trusted to act.** While it
only printed, a false positive cost a misleading log line; now it costs a second
sentence on the radio restating what the pilot already has. The canonical
spelling alone flagged four innocent replies — a hyphen (`one-three`), digits
(`runway 13`), grouped digits (`2,000`), and a frequency to one decimal
(`133.0`). Numbers are now compared **by value**, not by string, and a spoken
match may not run into another number word — `one three` must not be satisfied
by `one three three decimal zero`, which is a different fact entirely.

**Appended, not substituted, and no retry.** Replacing the reply throws away the
agent's manner and its read of the conversation, which is the half it is good
at; a second model call costs a second or more on a frequency somebody is
waiting on. The missing clause is deterministic and we already have it.

**Digits, and the follow-up that should not have been one.**

    "im not sure i understand why we are using thirteen vs one three?"

There was no good reason. A reply in digits was made to PASS the verifier so
that enforcing this could not append a duplicate clearance to a transmission
that already carried one — a real hazard, solved in the wrong place, leaving
"thirteen" on the air.

The evidence settled it: across **886 recorded agent transmissions, nine
contain a digit and all nine are the "station calling … say your callsign"
template quoting the pilot back.** The agent has never written a clearance
number in digits. So `for_voice` — the last thing between the agent and the
air — now spells every aviation quantity, and no numeral can reach Polly:

    runway 13        -> runway one three          (not "thirteen")
    runway 07L       -> runway zero seven left
    heading 090      -> heading zero nine zero
    2,000 feet       -> two thousand feet
    133.0            -> one three three decimal zero
    250 knots / 4271 -> two five zero / four two seven one
    wind 090 at 6    -> wind zero nine zero at six

**Per quantity, not a blanket speller**, because they disagree: a runway is
spelled digit by digit and an altitude is not — "two zero zero zero feet" is
nobody's phraseology. Each is recognised by the word beside it and rendered by
the function in `core/say.py` that already knows its rules, which is the same
place the engine spells its own decisions. A bare number with no unit is left
alone; "Flight of 2" and "in 5 minutes" are not quantities with a convention.

This makes the failure impossible rather than unlikely, which is why it belongs
where every transmission passes. The verifier keeps its numeric comparison as
belt and braces.

`spoken_facts` was deleted: `accepted_forms` supersedes it and `unwired.py`
caught it the moment the last caller moved.

**Acceptance criteria**
1. A reply missing a required fact is not transmitted as-is. Either the agent is
   asked again under a constrained prompt, or the deterministic phrasebook
   rendering is transmitted instead.
2. The fallback is bounded — one retry, then phrasebook. A controller who goes
   quiet because a model would not co-operate is worse than one who sounds stiff.
3. `decision -> rendered text -> what was transmitted` is recorded for every
   turn, so the seam can be audited after a sortie rather than watched live.
4. A `refuse` decision is covered: it carries the redirect frequency and station,
   and losing those strands a pilot.
5. Offline tests, with a fake agent that omits a fact, prove 1 and 2.

---

**FLOWN 28 AUGUST AND FAILED, and this is the worst result of that sortie.**
Ten decided facts were not voiced, four were repaired, **six were lost** -- and
all six of the lost ones were the approach:

    vector: one two thousand, zero nine five
    vector: one two thousand, zero eight five
    vector: one two thousand, one zero zero
    vector: one two thousand, zero nine five
    vector: three thousand, one three zero
    vector: two thousand, one two five

The engine turned him and descended him from twelve thousand to two thousand
across five instructions and **the aeroplane heard none of them**. The pilot
flew the whole ILS on his own needles and said so at the time:

    "clearly there's an issue with a split brain on the approach. He thinks
     he's not supposed to say anything"

He is right about the cause. The ASR block handed to the agent reads *"The
turns and altitudes are transmitted automatically -- do NOT [repeat them]"*,
so the agent is correctly told to stay off them, and whatever transmits them
automatically did not. Both halves are behaving; the seam between them is
empty, and `not_voiced` recorded every one of the six without anything acting
on it.

This is the SEPARATION half of the two-brain invariant going out over nothing.
A vector that is decided and not transmitted is worse than one never decided:
the engine believes he is turning.

## [SEAM-2] `reconcile` arbitrates authority by searching prose for the word "hold" — #80
labels: bug, architecture

**Status:** BUILT 10 August, needs a pilot. Offline evidence and tests
are below; what it changes is what the RADIO says, so a sortie closes it.

**It found a regression I had just introduced, which is the real story.**
`reconcile` suppressed the holding *sentence*; #79 then repaired any decided
fact the agent had not voiced, reading `bridge.decided` — which still held the
hold. So the suppressed clearance came straight back on the air:

    reconcile:  directive -> ""   ("radar shows him established on the approach")
    #79 repair: appends "hold at present position, maintain five thousand"

A pilot established on final, told to climb and hold — **the exact bug
`reconcile` was written to prevent, re-entering through the door built to fix a
different one.** Caught before it flew by asking what the two changes do
together rather than what each does alone. A guard that edits prose while the
structured decision survives is not a guard.

So `reconcile` owns both halves now: it takes the decisions, and returns the
ones that still stand. `settle` writes those back to `bridge.decided`.

**And it reads kinds instead of words.** `HOLDING_KINDS = ("hold",
"continue_hold")`. Two cases the substring could not do:

* *"remain at present position, maintain five thousand"* — a hold with no
  "hold" in it. Suppressed correctly now, missed entirely before.
* *"taxi to runway one three, hold short of runway one three"* — a GROUND
  instruction the substring read as a holding clearance and would have
  suppressed.

The two holding paths in `controller.py` now carry `Decision`s; the
"no holding available" path deliberately does not, since there is no hold to
give and naming it one would suppress a vector to protect a clearance that does
not exist.

**Criterion 4 is NOT met and is deliberately deferred.** Six of thirty-two
`say()` calls carry a decision, so `reconcile` keeps a prose fallback for the
rest — removing it would silently stop suppressing holds on every path that has
not migrated, which is worse than the bug being fixed. The fallback is marked,
tested, and goes when the remaining paths carry theirs.

**How many is "the remaining paths"? Not all thirty-two — about eleven more.**

    "for criterion 4 - should we include a decision on all 32?"

The rule is *a `Decision` exists where there is a **fact a pilot must actually
receive*** — a level, a runway, a station, a frequency. That is what `verify`
checks and what `repair` restores, and it is the only thing either can act on.

Still owed one (~11):

| | |
|---|---|
| `cleared to land runway X` | `cleared_land` + runway |
| `cleared visual approach runway X` ×2 | `cleared_visual` + runway |
| `cleared <approach> runway X` ×3 | `cleared_approach` + runway |
| `descend and maintain X` ×2 | `climb` + altitude |
| `negative, you are assigned X` | altitude |
| `field in sight, contact <station>` | `handoff` + station |
| the missed-approach instruction | `missed` + its level |

Correctly carrying none (~15): *"roger"*, *"radar contact, say intentions"*,
*"no flight to break up"*, *"not radar identified, say your callsign"*,
*"heard a Mustang overhead"*, *"welcome, exit the runway when able"*, the
break-up announcements, *"no report"*. **There is nothing in them to verify and
nothing to repair**, and giving them a `Decision` would create a verifiable
object with no facts — plus a phrasebook rendering nobody needs.

**And over-applying is not free.** Every `Decision` is now both verified and
*repairable*, so one attached to a sentence the agent may legitimately
paraphrase produces a spurious second transmission. That is the cost this
sequencing exists to avoid: each new kind wants its phrasebook rendering and its
own test before it is trusted to speak.



    if directive and "hold" in directive.lower():

Twice, in the function whose whole job is deciding which authority owns an
aeroplane. `reconcile(directive: str, stack: str, vectoring: str)` takes three
strings that three different authorities have already rendered into English, and
picks a winner with a substring test.

It works today because `controller.py` writes those sentences and we control the
wording. It breaks the moment a phrasing changes, a synonym appears, or a
non-holding directive happens to contain the word — and the failure is silent
and safety-adjacent: a suppressed holding clearance, or one that should have been
suppressed and was not.

The reasoning inside `reconcile` is **correct and well argued** — the missed
approach owns him, the talk-down owns him on final, otherwise the engine owns
him. This issue is not about the policy. It is about the policy reading tea
leaves instead of being handed the facts.

**Acceptance criteria**
1. `reconcile` consumes typed `Decision`s, not rendered prose.
2. No authority decision in the bridge depends on a substring of another
   component's English.
3. Every precedence case — missed, established, holding-plus-vector — has a test
   that names the wrong answer it prevents.
4. The rendered strings are produced *after* reconciliation, not before it.

---

## [SEAM-5] Split `rules.md` into briefs, one at a time, and measure — #83
labels: architecture

**Status:** OPEN. Do **one**, measure, then decide about the rest.

`soul + plate + rules` is 24 KB assembled into the system prompt on **every**
`/atc` call, of which `rules.md` alone is 21.9 KB — sent whole regardless of
station, phase or request. `LAYERS.md` describes the state-triggered brief that
replaces it and it has never been built.

**Deliberately scoped to one migration.** The full design — briefs with
predicates, priorities, measured token costs, a logged manifest — is the right
destination and is a large correct system that nothing would use on the day it
landed. This repo has been bitten by exactly that three times (`phases.guide`,
`Controller._me`, `stations_at`). Clearance delivery is the candidate: its facts
are already deterministic and its rules are self-contained.

**Acceptance criteria**
1. One bounded brief is extracted with a deterministic inclusion predicate.
2. Prompt size, latency and answer quality are measured before and after, and
   recorded here — not asserted.
3. A controller who does not need the brief does not receive it.
4. The mechanism is general enough for the second brief without a rewrite, and
   the second brief is NOT built in this issue.

---

## [SEAM-6] Why did this call cost 8,000 tokens, and why did Approach know that? — #84
labels: architecture

**Status:** OPEN. **Blocked on [SEAM-5]** — do not start until one brief exists.

A per-turn `ContextPlan` that decides what the interaction layer sees: the
invariant brief, the role brief, the task brief, the live situation, the dialogue
window, the capabilities, and the retrieval policy for what was left out. Each
with a predicate, a priority, a measured cost, and a manifest logged with the
turn.

The manifest is the point. It makes *"why did Approach know that?"* and *"why did
this call cost 8,000 tokens?"* answerable without asking the model.

Deliberately last. The shape of the plan should be argued by the briefs that
exist, not designed before any of them do.

---

## [FP-7] A second theatre's plan made the board ambiguous again — #89
labels: bug, needs-flight-test

**Status:** OPEN. Found in the flight recorder, 10 August — the pilot marked
card row Q1 complete, and the transcript says otherwise.

Q1 asks for a clearance at Kobuleti and expects **Domino, without being asked
which**, because it is the only plan that departs Kobuleti. What happened:

    PILOT: Kobuleti Clearance, Viper 1-1, request clearance.
    ATC:   ... I have two plans on file — transit and radar recovery, filed as
           Domino, or transit and instrument recovery, filed as Silverstate.
           Say which one is yours.

The board:

| label | origin | destination | active |
|---|---|---|---|
| Domino | Kobuleti | Batumi | **true** |
| Silverstate | Nellis | Tonopah | false |

He was offered a plan from **another theatre, three thousand miles away, that
is not even active** — and made to choose. Two facts either of which should
have settled it on its own.

**This is #61 recurring, exactly as #61 predicted.** That issue trimmed the
board to one plan and recorded why the resolver's faults had been invisible:
*"there is always another plan to be ambiguous with, so a standing bonus to the
local one changes no outcome."* Adding `Silverstate` for Nevada (migration 022)
put a second plan back, and the ambiguity came with it.

**Not an argument for one plan on the board.** Multiple filed plans is the
point of the flight-planner work; the resolver simply has to use what it knows.
A plan whose origin is not the field he is calling from is not a candidate for
"which of these is yours" — it is not his at all.

**Acceptance criteria**
1. Asking for a clearance at Kobuleti with Domino and Silverstate on file gives
   Domino, unasked.
2. A plan whose origin is a different aerodrome is never offered as a choice.
3. An inactive plan is never offered as a choice.
4. Asking at Nellis with both on file gives Silverstate — the same rule, the
   other way round, so this is not a Kobuleti special case.
5. Two plans from the SAME field still produce a question (that is Q1b, and it
   must not regress into picking one confidently).

---

## [SEP-6] A refused phase transition welds an aeroplane into `departure` — #91
labels: bug, needs-flight-test

**Status:** DIAGNOSED, not fixed. The mechanism is proven and the log now
reports it; the trigger has not been reproduced offline.

An aircraft sat in `departure` from rotation to thirteen miles on the approach
— through Center, through the hand-off to Batumi Approach, through *"I'll take
the surveillance approach into one three"* — and the only trace was the
consequence, printed twenty times:

    .. ASR guidance suppressed: he is in the departure phase

**The mechanism is certain.** `derive("departure", on_ground=True,
was_airborne=False)` wants `taxi`; `departure` may only lead to `enroute` or
`arrival`; the transition is refused and the phase kept. Correct in itself —
*"landed while enroute"* is not a thing — but **refused silently**, so one bad
`on_ground` reading welds the phase in place for the rest of the sortie. Proven
by test, not by reading.

**What I could not reproduce** is the `on_ground=True` while airborne. Every
offline run of that path — real `Scope`, real contacts, `_me` on 124.425 —
flips `departure → arrival` correctly. The radar lines in the recorder show him
airborne throughout. So the trigger is real and I do not have it, and I am not
going to guess a fix into the separation path.

**What is fixed:** `derive` now reports a refusal, and the suppression names the
inputs rather than the verdict:

    .. phase REFUSED: departure cannot lead to taxi (worked by approach,
       airborne) — he stays in departure
    .. ASR guidance suppressed: phase departure does not fly the approach
       (worked by approach, airborne)

Same rule as `check.py`: **skipped is reported, never silent.** A phase that
will not move is otherwise indistinguishable from one nothing is trying to
move, and that difference is the whole diagnosis.

---

## [SEP-9] A vector was assigned below the minimum vectoring altitude — #95
labels: bug, needs-flight-test

**Status:** VISIBLE 11 August — the fact is verified now, and the underlying
duplication is [SEP-7]/#92.

    ASR: vectoring, 19 miles. Turn left. Fly heading 225, maintain 8000
    ATC: Sockeye, Batumi Approach, roger, level five thousand five hundred.

The MVA on the 056 radial at nineteen miles is **8,000 ft**. He was left at
**5,546**, two and a half thousand feet under it, and worked it out himself:

    "if I were to continue on heading 232, 5500 ... north east of Batumi,
     I would hit a mountain"

**The geometry was right.** Kobuleti's and Batumi's terrain were surveyed cell
by cell — every 5°, every half mile — precisely so a controller could not assign
an altitude into it. The number was correct when it was decided and gone by the
time it was spoken, because **a vector crossed the seam as prose** and only a
`Decision` is verified.

It carries one now, so a dropped vectoring altitude appears as `NOT VOICED`
instead of as a mountain.

**It is verified and deliberately NOT repaired.** The engine transmits vectors
itself, on its own schedule, from the same phrasebook — appending one to the
agent's reply would not restore a lost fact, it would say the same thing twice
from two transmissions. The same pilot reported exactly that on the same sortie:
*"I'm getting redundant instructions"*, *"he's stepping on me a couple of
times"*. `SPOKEN_BY_THE_ENGINE` names the exemption rather than hiding it.

**The duplication itself is #92**, and this sortie showed it doing real harm —
the two paths did not merely repeat each other, they **disagreed**:

    ATC[vec] ... turn right heading two four five, maintain three thousand
    ASR:     ... Fly heading 245, maintain 5500

Same aircraft, same moment, two altitudes.

---

## [PHR-5] "Kobuleti" is clunky, and one voice ignores the pronunciation table — #97
labels: bug

**Status:** OPEN. Reported live, 11 August. Two symptoms, possibly one cause.

    "Clearance says Kobuleti pretty clunkly, really slow"

    "for some reason, Batumi Tower says my name incorrectly ... I think Batumi
     Tower is not using the pronunciation table. Is that possible?"

It is possible and worth checking properly. `radio/tts.py` has `SAY_AS` — plain
respelling rather than SSML, deliberately — and it already carries
`"Sockeye": "sock eye"` for exactly this. It is applied in `frames`, which every
transmission passes.

So either the substitution is not reaching that path, or **a respelling tuned on
one Polly voice does not survive another**. Every controller has his own voice;
that would make the table correct for Matthew and wrong for whoever Batumi Tower
is, which is the sort of thing that looks like a bug in one seat only.

"Kobuleti" being slow and clunky is the same family: the spelling that stops it
being mangled may be costing it its rhythm.

**Acceptance criteria**
1. The callsign is pronounced the same by every controller voice.
2. Aerodrome names read at a normal pace.
3. Whatever is found is written down per VOICE if that is what it turns out to
   be — a table that is right for one speaker and silently wrong for eight is
   worse than no table.

---

## [OPS-16] Mission validation only knows the 1944 Caucasus sortie — #112
labels: bug, tooling

**Status:** OPEN.

`mission/validate.py` always opens `362nd-Blind-Flying.miz`, requires theatre
`Caucasus`, expects P-51/SCR-522 constraints and validates `route.FIXES`. It
cannot validate the Nevada mission at all, so the normal quality gate does not
prove that the mission a pilot is about to fly is structurally sound — on the
one map where the data is newest and least exercised.

**Acceptance criteria**
1. Validation takes a mission/theatre specification rather than a filename.
2. `tools/check.py` validates every mission the repo can build.
3. The Nevada mission has a build-and-validate test, not only data tests.

---

## [ARCH-14] There is no procedure model: no SIDs, no STARs, no transitions — #113
labels: architecture

**Status:** OPEN, and honestly stated in `core/nevada.py` already.

One ILS end is modelled at each Nevada field. There is no published departure,
arrival, or transition anywhere in the system — a flight plan carries a
comma-separated fix string and one approach key, and the controller vectors
everything in between.

That is a fair description of what Marshall does today and it should not be
described as anything else. It can provide vectors and one selected ILS
recovery. It cannot claim a Nellis SID, a range transit, a STAR, or coverage of
every procedure on a map.

**The shape of the answer**, from the audit and worth keeping: a procedure model
with typed legs and transitions — SID, enroute/range route, STAR, approach,
missed — with the flight plan choosing INSTANCES of those. Every later procedure
then becomes data rather than a branch in controller code, which is the same
move that made fields, stations and terrain minima portable.

Start with one Nellis SID, one range route, one Nellis STAR and the existing ILS.

---


## [ASR-6] The Nellis ILS dithers, and three approaches never arrive — #117
labels: bug, needs-flight-test

**Status:** HALF FIXED 13 August. **Arrivals: done.** Nellis went 1293/1296 to **1296/1296** and Tonopah 1291/1296 to **1296/1296** — the eight starts that never reached the missed approach point all do. **Dithering: not done.** Nellis was 103 flips and is now 67, helped by #19's angle fix; Batumi is 0. The geometry was tuned on a sea-level Georgian field and Nevada is a mile and a half up, which is the remaining half.

Both Nevada approaches now carry their OWN sweep baseline — until today they reported and were judged against nothing, because the only baseline was Batumi's and judging Nellis against Georgian figures is noise. So the 67 is recorded rather than accepted, and a regression against it is now visible.
approach other than Batumi's — which is #2 criterion 2, and the finding arrived
in the same minute the capability did.

    nellis-ils    1293/1296 arrived     103 flips on 22 approaches   745 turns
    tonopah-ils   1291/1296 arrived
    batumi-asr    1296/1296 arrived       0 flips                    576 turns

**103 rapid direction reversals.** Batumi's ASR has none, and #19 is the issue
that got it to none — so this is not a new class of fault, it is the old one on
terrain nobody had measured. A flip is a heading ordered one way and reversed on
the next call, and from the cockpit it reads as a controller who cannot make up
his mind.

**And eight starts never reach the missed approach point at all**, all of them
from 30 nm and all on radials that put the aeroplane behind the field:

    nellis-ils    180/150, 180/180, 260/270
    tonopah-ils   120/090, 120/120, 180/210, 200/180, 200/210

Both fields sit in high terrain — Nellis's minimum vectoring altitudes reach
10,500 ft and Tonopah's start at 6,500 — so the likeliest cause is the geometry
turning an aeroplane into a cell it may not descend through and then re-turning
it. That is a guess and is marked as one; the sweep prints every failing start,
which is where to begin.

**No baseline is recorded for either.** A baseline is per procedure — judging an
ILS in the Spring Mountains against a surveillance approach on the Georgian coast
measures nothing except that they are different approaches. Both report figures
and judge nothing until these are fixed and a defensible baseline exists.

**Acceptance criteria**
1. Zero dithering flips on `nellis-ils` and `tonopah-ils`, clean sweep.
2. Every start arrives, or the ones that cannot are explained by terrain and
   excluded deliberately rather than silently.
3. A recorded baseline for each, in `BASELINE_FOR`.

---


## [ARCH-18] Three sources, three magnetic variations, and only a pilot can settle it — #125
labels: bug

    "DKS also says batumi rwy course is 119 for rwy 13.. interesting"

Interesting is right. Batumi's runway is **131 true** — measured, and pydcs's
`heading=310` for the 31-13 strip agrees on the reciprocal. Three sources then
convert it to magnetic three different ways:

| source | variation | magnetic |
|---|---|---|
| DKS field data | **12°E** | **119** |
| `route.py` (`BATUMI_ASR.magvar_deg`) | **6°E** | **125** |
| Georgian AIP plate | **7°E** | **124** |

None is a typo. 12°E is roughly Batumi's *historical* variation; it has drifted
to about 7°E, which is precisely why the AIP renamed the runway 13 → 12 while
DCS still calls it 13.

**THIS IS THE WORSE HALF OF THE PLATE-VERSUS-SIM PROBLEM, and the reason it has
gone unnoticed.** A wrong frequency is a discrete failure: you tune it, you get
silence, you know within seconds. A wrong variation is CONTINUOUS. Every
absolute heading the controller issues is off by the difference, in the same
direction, for the whole approach — and from the cockpit that reads as the pilot
drifting rather than as the controller lying.

If DCS applies 12°E, then "fly heading one two five" flown on the HSI puts his
true track at 137 — **six degrees right of a localiser he is being vectored
onto**.

**Two things say this is live rather than theoretical.** `route.py` already
disagrees with itself — `Field_(Batumi).magvar_deg` is `0.0` while
`BATUMI_ASR.magvar_deg` is `6.0`. And `talkdown.relative_correction` exists
specifically because

    "every absolute heading we give is computed in true, converted to magnetic,
     and then flown against an instrument that is wrong by an unknown amount"

with a note about a DG reading 7° off the compass and the compass 16° off the
map. That is this fault, worked around rather than fixed — and the workaround
only covers the talkdown, not the vectors that precede it.

**Only a pilot can answer it**, and it takes ten seconds: line up on Batumi 13
and read the HSI.

    reads ~131   DCS applies no variation, and our 6° correction ADDS the error
    reads ~125   we are right and DKS is stale
    reads ~119   DKS is right and every absolute heading at Batumi is 6° out

Card row **Q9**. Deferred to the next sortie by the pilot, 11 August.

Unlike the navaid discrepancies this is **not** a NOTAM — a NOTAM tells the
pilot something; this is a number we owe him correctly on every single vector.
`magvar` becomes the fourth audited quantity, and the audit's answer here is a
correction rather than a broadcast.

**Status:** OPEN — no commit anywhere references it, and the disagreement
survived the #137 conversion intact rather than being settled by it:
`config/theatres/caucasus.toml` now gives the Batumi FIELD `magvar_deg = 0.0`
and the Batumi ILS `magvar_deg = 6.0`, in one file, six lines of table apart,
and `atc/asr.py` applies the profile's on every correction. Nor has a pilot been
asked: the Q9 this entry cites is struck through and is the range-datum row
(`[R#16]`), not the HSI reading — so this has no card row at all and the number
has never been taken.

---

## [SEAM-14] There is no enroute phase on a twenty-two mile sortie — #130
labels: architecture, needs-flight-test

    "Also kob departure didn't hand me off to center again"

Not a handoff bug. Kobuleti and Batumi are **22.6 nm apart**, so their derived
terminal areas are 11.3 nm each and they touch. The ladder's rule is

    Rule("departure", "center", "outbound_beyond", CENTER_NM)   # 25 nm

and a pilot going from one field to the other is **never 25 miles outbound from
where he started** — he turns for the destination first. Measured, from the
monitor's own log:

    Kobuleti Departure keeps him -- departure,  3 nm, outbound
                                                10 nm, outbound
                                                11 nm, inbound     <- turned
                                                10 nm, inbound
    DEBUG NOTE  "I've not been handed off to Georgia Center yet"
    DEBUG NOTE  "obviously, Kobuleti Departure can't handle that question.
                 I'm going to switch myself to center"

He reached Batumi Approach at 23 miles because the AGENT proposed it and the
bridge authorised it — not because any rule fired.

**Center is a fiction on this route**, and the comms card promising preset 5
makes it look like a fault. Three ways out, and the choice is a design one:

1. **Skip it.** Departure hands straight to the destination's Approach on a
   short hop. Real, and it is what happens between two fields this close.
2. **Scale the boundary to the field.** `DEPARTURE_NM`, `ARRIVAL_NM` and
   `CENTER_NM` are described in `handoff.py` as *"defaults until the airfield
   table exists"* — and the `sectors` table now holds each field's actual
   radius. The constant was standing in for exactly that.
3. **Fly further.** The Nevada sortie is 60+ nm and has a real enroute leg.

(1) and (2) are the same change from different ends: the boundary is the
aerodrome's terminal area, not a number.

**One thing the ladder cannot express either way.** `handoff.due` resolves
`rule.to` within `me.field`, so a departure at Kobuleti can only ever be handed
to a Kobuleti station — the DESTINATION's Approach is unreachable from the rule
table. That is why the airspace branch exists and why it is the only mechanism
that can move him between fields.

**Status:** FIXED 14 August, NEEDS A PILOT — card row V7. #139 landed, which
was the block, and the same change reverted on 13 August is now the right one.

`Rule.terminal_edge` marks the two rows whose distance IS the edge of the
terminal area — `center -> approach` and `departure -> center` — and `due`
resolves them through `handoff.reach_of`, which asks `core.airspace`. Procedure
reads geography; the reverse would put a rule table underneath a map. A circuit
distance stays a constant, because five miles is five miles at every aerodrome
on every map, and a test asserts that only those two rows are scaled.

    Center holds an arrival to 27.5 nm, then Approach   (was a flat 25)
    Kobuleti Departure holds an outbound to 28.8 nm     (was a flat 25)

The first number is the one that matters: Batumi's ILS holds at KOBULETI, 22.5
nm out, so an arrival is now with Approach BEFORE his procedure starts. Under
the 13 August attempt it was 11.3 and he would have been on Center inside the
final — #51 with the numbers changed, which is why nine tests refused it and
why the revert was right.

**THE HALF OF THIS ISSUE THAT IS NOT A BUG is written down rather than fixed.**
Kobuleti and Batumi are 22.6 nm apart and a pilot turns for his destination
long before he is 28.8 miles outbound, so `outbound_beyond` never fires and
Center never gets him on that hop. That is option (1) above — *"Departure hands
straight to the destination's Approach on a short hop. Real, and it is what
happens between two fields this close"* — and it is the comms card promising an
enroute leg that is wrong, not the ladder. Asserted in
`tests/test_the_ladder_uses_the_maps_boundary.py` so nobody "fixes" it.

Still true and still out of the rule table's reach: `due` resolves `rule.to`
within `me.field`, so a departure at Kobuleti can only be handed to a Kobuleti
station. The destination's Approach comes from the airspace branch, which is
the only mechanism that moves an aeroplane between fields.
---

## [SEAM-15] A controller can resolve a private fix but cannot say one — #133
labels: architecture

The other half of #129, and the half the pilot actually asked for:

    "But ATC should be able to get and referred to my private fixes when I open
     a plan with those fixes and the names in there."

#129 fixed the RESOLVING. A plan defines its own fixes in `legs`, `route_fixes`
falls back to them, and `check_live` accepts a route naming one, so **FOO, BAR,
SPAM** validate and clear without ever touching the shared table.

What still cannot happen is a controller USING one. "Report passing BAR",
"cleared direct SPAM", "say your distance to FOO" — every one of those needs the
plan's private fixes on the ATC side of the seam, positioned, at the moment the
transmission is built. They are copied into `assigned_plans` at clearance, so
the data has arrived; nothing reads it for language, and the fix table the
controller vectors against still holds only what is published.

**Why it is a seam and not a feature.** The two brains disagree about what a fix
IS. The director resolves names against a table; the bridge computes bearing and
range against `Fix` objects projected through the sim. A private fix exists in
the first world and not the second, so a controller asked for a range to one
falls through to "no fix for that" — which is the correct answer to the wrong
question, and reads to a pilot as ATC not knowing where his own route goes.

**What it wants:** the assigned plan's legs projected the same way the theatre's
catalogue is, scoped to the flight that filed them, so a private fix is
vectorable for exactly as long as that aeroplane is flying and invisible to
everybody else. Then `vector`, the arrival prompt and the enroute controller can
all name a point the pilot chose, which is the whole reason he named it.

Needs a flight test: whether a controller referring to your own steerpoint by
name lands as useful or as uncanny is a judgement only a pilot makes.

**Status:** OPEN — the rule was settled and no code has followed it. `bda3d1d`
says in its own body "No code in this commit. The rule had to be right before
the schema follows it", and no schema has: nothing reads an assigned plan's legs
for geometry, `push_fixes` still builds the controller's table from the
theatre's fixes and waypoints alone, no migration scopes `fixes` to a flight,
and `clearance.py` still asserts "THE PUBLISHED FIX TABLE IS THE WORLD". A
private fix is still resolvable and still unspeakable, which is the exact
asymmetry in the title.

---

## [ARCH-22] A new sortie inherited a dead one's state, because a flight row outlives the flight — #136
labels: architecture

    "why on earth is intent still ASR — where is that coming from. Something
     about that stinks"

Right, and it is not the classifier: asked that exact transmission it answers
`wants='ILS 13'`. What happened is worse.

At 04:52:00, on the transmission "Sakai is looking for the ILS runway 13 into
Batumi", three fields changed at once:

    intent       ''  ->  'asr approach'
    phase        ENROUTE -> CLEARED
    assigned_ft  None -> 4000

That triple is the signature of `Controller.restore()` (controller.py:530-554),
which hydrates an aircraft from its `flights` row. The row it found belonged to
the PREVIOUS sortie — the 03:00 flight that really was on the ASR — because
`flights` is keyed on `(mission, callsign)` and a mission instance outlives any
number of sorties flown inside it. He landed, parked, ended the flight, started
a new one, and got the dead one's state back the moment the engine engaged.

It also explains `in_letdown: true` at 35 nm and an assigned altitude of 4,000
he was never given.

`docs/STATE.md` asks three questions and this is the third with no answer:

    WHO OWNS IT     the controller
    WHERE IT LIVES  flights
    WHEN IT DIES    when the MISSION restarts  <- should be: when the SORTIE ends

**Half fixed, and the half that is done is a ceiling rather than the answer.**
`hydrate` now restores the RECENT past only: a row nobody has touched for
fifteen minutes is the last thing a finished flight said, not somebody
currently flying, and it is skipped — out loud, naming what was dropped, because
a board that silently discards an aeroplane reads exactly like a board with no
aeroplane on it. A bridge restarted mid-sortie still takes seconds and is still
invisible, which is the whole reason the cache exists.

**The root cause is still there: the row outlives the flight.** The clean fix is
procedural rather than temporal — *requesting an IFR clearance IS the start of a
sortie*, so the first call of a new flight should retire whatever that callsign
was doing before, instead of a timeout guessing at it. Fifteen minutes is a
number chosen to be longer than a restart and shorter than a coffee break, and
any number chosen that way is a number that will be wrong for somebody.

**Status:** PARTLY, and the split is exactly as the two paragraphs above
describe it. The ceiling is in and guarded: `Controller.hydrate` skips a row
untouched for `stale_after_sec = 900.0` and reports it in `skipped_stale`
instead of silently, with `tests/test_the_board_is_a_cache.py` asserting the
name that was dropped. The root cause is untouched — nothing retires a
callsign's previous row when he asks for a new IFR clearance, and `controller.py`
still carries the comment saying so in capitals: "A CEILING, NOT A FIX".

---

## [ARCH-23] Fixes are Python, published to the database as though they were data — #137
labels: architecture

    "There are fixes in core/fixes.py??? Shouldn't all fixes be data in the
     database?"
    "we deleted the domino flight plan that had feet wet… where on earth did
     that come from. It shouldn't be in the database from a flight plan as a
     private fix and it's definitely not a public fix."

Both right, and the second follows from the first. `FEET WET` is not a leftover
from the deleted plan and deleting that plan could never have removed it: it is
a module-level `Fix` in `core/fixes.py`, one of the 1944 strike sortie's own
turning points, and the bridge PUSHES the lot into the `fixes` table on every
start. So the database is a cache of a hard-coded list, and one mission's route
points are published to every controller in every sortie as though they were
navaids. When the pilot asked for a private steerpoint the controller could not
resolve (#133), it reached into that catalogue and offered him one.

The public/private distinction we settled for flight plans applies here one
level up and was never applied: **FEET WET, INGRESS, EGRESS and TSUTSNVATI are
that mission's private fixes.** They belong to the mission that flies them, not
to the theatre.

The other half is the one the pilot named first: forty aerodromes means forty
hand-edits of a Python module, and `route.py` being "the single source of truth"
is what makes that feel principled. It was true when there was one theatre and
one sortie.

**What it wants:** published fixes are rows, loaded from data, with a source
that can be cited (a plate, an AIP, the sim's own `Beacons.lua`); a mission's
route points live with the mission; and nothing invented gets published to
everybody. See also #133, which is the same distinction for flight plans.

**Status:** PARTLY — item 2 landed 14 August, and what is left of it is
named below rather than left as "partly".

`core/fixes.py` was 208 lines and is 151. FEET WET, INGRESS, TSUTSNVATI,
EGRESS and REHEARSAL, the route, its per-leg altitudes and the defended
batteries are all `[sortie]` in `config/theatres/caucasus.toml` now — a
SECTION of its own beside `[[fix]]`, because what is published is a fact about
the map and what is there goes home with the mission that flies it. Being in a
different Python module was the only thing that ever made them "private", and
that is not a property of a name; it is an accident of where somebody typed it.

`catalogue.SortiePoint` is the third kind of place, after `PublishedFix` (a
navaid an AIP would carry) and `OwnPoint` (geometry a procedure computes
against and no pilot ever says): a steerpoint that IS flown and IS named on the
radio and belongs to one mission. `route.py` keeps every old name — `R.SORTIE`,
`R.TARGET_AREA`, `R.DEFENDED` — as a reader over the file, so nothing
downstream moved. `core/fixes.py` keeps the `Fix` type and the two functions
that reason about a route, which is CONFIG.md's split exactly: numbers in the
data, rules in code.

**Still open, and each is its own piece:**

1. **The private points are still PUBLISHED at runtime.** `push_fixes` does
   `fixes.update(_th.waypoints)`, so they still reach the shared `fixes` table
   on every bridge start. Fixing it needs a scope on that table — the flat
   name→lat/lon map cannot express "this belongs to one mission" — and doing it
   carelessly breaks plan validation, which refuses a plan naming a fix the
   table does not hold. The DECLARATION is now separate; the PUBLICATION is not.
2. ~~`[[sortie.point]]` carries no lat/lon.~~ **Done, same day.** Seeded
   through `coord.LOtoLL` by `tools/seed_fixes.py` — re-runnable, additive,
   and a text edit rather than a TOML round trip so the `source` citations
   survive. **Every fix on the Caucasus map now carries a position**, so #139's
   question is answerable with no sim running for the first time. It answers
   badly: all four published approaches begin OUTSIDE the terminal area that
   owns them.

   The seeding also caught a wrong number in the data's own prose. TSUTSNVATI's
   note said *"11 nm east of Kutaisi"*; the grid metres and the sim's
   projection both say 18. They agree with each other and disagree with the
   sentence, which had been carried unchecked since the point was written —
   and its hand-given `N42 17.314 E42 51.676` matches the sim to six decimal
   places, which is what says the projection is right and the prose is not.
3. ~~The published fixes are declared twice.~~ **Done, same day.**
   `KOBULETI`, `BATUMI` and `KUTAISI` come off `[[fix]]`; `INITIAL` — which
   was a THIRD copy, since #143 had already moved it onto its approaches as an
   `iaf` — comes off the procedure that declares it, through the new
   `theatre.procedure_point`. The transit `FIXES`/`LEGS` are assembled from
   those readers rather than from constants, so the route cannot disagree with
   the catalogue it is drawn from. A test asserts IDENTITY rather than
   equality: two objects that happen to match are the thing being removed.
   `core/fixes.py` is now 140 lines and defines no places at all — the `Fix`
   type and the two functions that reason about a route.
4. `core/fields.py` still hard-codes `DEPARTURE_FIELD = "Kobuleti"` and
   `ARRIVAL_FIELD = "Batumi"`.

Tests: `tests/test_the_sortie_is_data.py`.
---

## The audit, 12 August

    "why dont you conduct an investigation, looking for smells, where we might
     be storing coordinates or pilot names or flight names or airport names or
     approach names in code"
    "this system should work on any map in any era with any pilot flying any
     flight plan"

Counted with comments and docstrings STRIPPED, so these are live code and not
narrative. Ordered by how badly each blocks that sentence.

### 1. Coordinates — and this is what blocks #139

`core/fixes.py` defines nine `Fix` objects carrying **DCS grid metres**:

    KOBULETI = Fix("KOBULETI", "MG", -317962, 635633, 124.000, ...)
    BATUMI   = Fix("BATUMI",   "OS", -355811, 617386, 132.000, ...)

There is no lat/lon on a fix anywhere. The only thing that can turn one into a
position is the sim, asked at bridge start through `coord.LOtoLL` -- which is
why `push_fixes` exists, why the fix table is a cache of a Python list, and why
"does this terminal area contain that approach fix" (#139) cannot be answered
offline at all. `core/fields.py` does carry lat/lon, for exactly two fields.

### 2. One sortie's route points, published as navaids

`fixes.py:130` -- `SORTIE = [BATUMI, FEET_WET, INGRESS, TARGET_AREA, HOMEBOUND,
BATUMI]`. FEET WET, INGRESS, EGRESS and TSUTSNVATI are the 1944 strike's own
turning points and go into the shared catalogue on every bridge start. This is
the original complaint and it is the same public/private confusion as #133, one
level up.

### 3. Aerodromes and their frequencies are Python constants

`core/stations.py` -- eight module-level `Station(...)` definitions:

    APPROACH      = Station("Batumi Approach",   124.425, "approach", ...)
    KOB_DEPARTURE = Station("Kobuleti Departure", 123.300, "departure", ...)

`core/fields.py` ends with `FIELDS = (BATUMI_FIELD, KOBULETI_FIELD)` and two
constants naming this sortie outright: `DEPARTURE_FIELD = "Kobuleti"`,
`ARRIVAL_FIELD = "Batumi"`. Adding an aerodrome means editing Python and
redeploying, which is the "forty aerodromes" problem stated as code.

### 4. Approach procedures are Python constants, and pages are bound to one

Six: `BATUMI_APPROACH`, `KOBULETI_ILS`, `BATUMI_ASR`, `BATUMI_ILS`,
`NELLIS_ILS`, `TONOPAH_ILS`. Worse, five kneeboard modules bind one at import:

    kneeboard/plate.py:28      P = R.BATUMI_APPROACH
    kneeboard/asr_plate.py:24  P = R.BATUMI_ASR
    kneeboard/routemap.py:23   P = R.BATUMI_ASR
    kneeboard/aip_plate.py:30  P = R.BATUMI_ASR
    kneeboard/brief.py:18      P = R.BATUMI_ASR

A page is a function of a Card (#71); five of them are functions of one
aerodrome's surveillance approach, chosen at import time.

### 5. A map is a Python function

    THEATRES = {"caucasus": caucasus, "nevada": nevada}
    want = os.environ.get("MARSHALL_THEATRE", "caucasus")

Plus `CAUCASUS_RECOVERIES` and `NEVADA_SORTIES` as literal dicts. Adding a map
means writing a function, not loading a file.

### 6. The pilot-facing language is tuned to one mission — the "any pilot" smell

The sharpest one, because it is already a live complaint.

`radio/tts.py` holds a **pronunciation table** as a Python dict: `"Sockeye":
"sock eye"`, `"Batumi": "bah-too-mee"`, and ten Georgian place names. A new
pilot with a new callsign is mispronounced on the air until somebody edits
Python and restarts the bridge. #97 is the symptom of this being code.

`radio/stt.py:21` hard-codes the **Whisper domain prompt**:

    "Radio calls to Batumi Approach. Mustang callsigns: Pony one one, Pony
     two, ... Terms: ... over the beacon, ... Oscar Sierra, Batumi, Kobuleti"

and `domain_prompt(..., field: str = "Batumi")`. So transcription accuracy is
biased toward a 1944 Mustang sortie at Batumi -- while the pilot flies an F-16
out of Kobuleti. Whatever the recogniser is primed for, it is not the sortie
being flown, and this is the layer every one of his words passes through first.

### 7. Flight plans arrive with the database schema

Migrations `011`, `012`, `017`, `022` and `024` `INSERT INTO flight_plans`:

    INSERT INTO flight_plans (name, label, ...) VALUES
      ('362nd-kobuleti-batumi', 'Domino', ..., 'batumi-asr', 'Kobuleti',
       'Batumi', 'KOBULETI, INITIAL, BATUMI', 5000, ...)

A flight plan is something a pilot files. Shipping one as schema means every
deployment of Marshall anywhere is born believing somebody is flying Kobuleti
to Batumi on the ASR -- and #131 was the bridge reading its approach out of
exactly this row.

### 8. Low, and listed so nobody re-finds them

`prompts/rules.md` names Sockeye, Pony and Batumi in worked EXAMPLES. Examples
are teaching material and belong in the brief; they are only a smell if a
controller starts treating them as facts about today. `prompts/plate.md` is
generated from `route.py`, so it inherits whatever the layers above fix.

### The doctrine that produced all eight, and the fix for it

The audit above is a list of symptoms. The cause is one sentence, and it is in
the front door:

    CLAUDE.md      core/route.py is the single source of truth
                   (fixes, wind, the ApproachProfile + its capability)

    docs/STATE.md  Postgres is the single source of truth for anything that
                   outlives a transmission

Same phrase, two documents, opposite answers — and `LAYERS.md` put
`core/route.py` in Layer 1, "World: what exists, where it is, what is
published", beside `tracks` and `events`. So the architecture did not merely
permit fixes and frequencies to live in Python; it declared them foundational,
and every agent reading CLAUDE.md went to code to change them.

`STATE.md` claimed Postgres for STATE and was right. Nothing ever claimed a home
for CONFIGURATION, so it defaulted to code and code had a document calling it
truth. That is the missing category.

    "all of that should be configuration stored in the database, not code ...
     You keep going to code to implement some fix ... I feel like we are still
     under-leveraging the database as a source of truth"

**Settled 12 August, and written into `docs/CONFIG.md`:**

    Would a different map, era, pilot or flight plan change this value?
    Then it is DATA, and it lives in the database.

    reference (navaids, fields, frequencies, procedures, magvar, airspace
               radii, pronunciation, recogniser vocabulary)   -> rows, seeded
               from a citable source
    sortie    (flight plans, steerpoints, callsigns)          -> rows, the
               pilot's
    behaviour (separation, the letdown, the phase machine,
               who owns which clearance, the geometry)        -> code, tested

**Numbers in the database, logic in code.** `sectors(field, role, radius_nm,
ceiling_ft)` and `handoff_rules(from_role, to_role, condition, threshold_nm)`
are rows, per theatre, seeded from the procedure they serve; `_inbound_within`,
the separation engine and the phase machine read them and decide nothing about
their values. A new map tunes rows; a new RULE is a commit with a test.

The alternative — the rule table itself as rows the engine interprets — was
considered and rejected: it makes the separation invariant into data, and *an
LLM never invents separation between aircraft* is the sentence this system
exists to keep true. A bad row must not be able to reach it.

`core/route.py` stays, as a typed READER over those tables rather than their
author. Its virtue was never that it held the numbers — it was that the mission
builder, the chart and the ATC all read one thing and so could not disagree.
That survives the move intact.

And a migration creates the SHAPE, never the CONTENTS: seeding belongs in a tool
that can be re-run, pointed at a theatre, and cited.

### Progress, 12 August

**Done, and the pattern is proved end to end:**

  * `config/speech.toml` — aviation English, true on every map
  * `config/theatres/<map>.toml` — the names on that map, and its published
    fixes with the SIM'S OWN lat/lon stored rather than asked for
  * `config/callsigns.toml` — the stopgap third scope, and it says so
  * `core/catalogue.py` — the loader, pydantic-validated with `extra="forbid"`
  * the pronunciation table, the Whisper prompt and the published fix catalogue
    all read through it

**What that bought, beyond the tidiness:**

`theatre.fixes` was built by scraping every module-level `Fix` out of
`route.py` — a fact about which Python file a name sits in, not about whether
anybody can look it up. The published catalogue is now four citable fixes
(three aerodromes and the fix on the letdown plate), each carrying its source,
and the 362nd's turning points are the sortie's.

And **geometry works with no sim.** Every published fix carries `coord.LOtoLL`'s
own answer, so "does this terminal area contain its own approach" is now a
question a test can ask — which is what #139 was blocked on. The assertion that
Batumi's terminal area is eleven miles and its ILS holds at twenty-two is in
`tests/test_configuration_is_not_code.py`, and it could not have been written
last week.

**One bug shipped and caught on the running bridge, not by the suite.**
`push_fixes` collected the configured coordinates and then the sim branch did
`out = {}` before adding its own — so the published table came back holding
FEET WET, INGRESS and EGRESS and not one aerodrome. Exactly the
replace-versus-merge that cost a catalogue in #129: two sources for one table,
the second silently winning. The gRPC call is now its own function so the merge
is testable without a server, and it has a test.

**Aerodromes and controllers moved next**, so `[[field]]` and `[[station]]`
tables now carry Batumi and Kobuleti, all nine seats, the runway designators,
the ATIS frequencies, and both fields' MSA sectors and 48 MVA cells apiece.
Adding an airfield is adding a table.

And the move is guarded rather than eyeballed: a test walks every attribute of
every field and station and asserts the file says exactly what the Python said.
It earned its place immediately — the first pass turned a double quote into an
apostrophe inside three controllers' `manner`, which is prose that goes
straight to the agent describing how a man sounds on the radio. Green suite, no
failure, and the brief had quietly changed. TOML multi-line literal strings fix
it; the test keeps it fixed.

**Approach procedures moved next**, and they were the interesting one because
they had to be TAKEN APART to move. `ApproachProfile` carries `stations`,
`msa_sectors` and `mva_cells` as well as the procedure, so every profile is the
theatre's reference data welded to one arrival — the unfinished half of #2, and
the reason the bridge cannot hold the first without defaulting the second.

The file holds only the procedure, and names its fixes rather than repeating
them: a beacon appearing in two approaches must be the SAME beacon, and copying
coordinates into both is how they come to differ by a decimal. The stations and
minimum altitudes are composed back in by `theatre.published_approaches`, from
the theatre's own list and the aerodrome the procedure names — one place, and
visible, which is where the welding will stop when #2 is finished.

Four procedures, byte-identical to the Python they replace, lat/lon excepted
because the file has them and the Python did not.

**And the guard found a real defect while doing it** — the 1944 letdown carries
no controllers at all, and it is selectable. Preserved exactly and filed as
#140, because a migration that quietly changes behaviour is worse than the
defect it fixes.

**The registry moved next.** `THEATRES = {"caucasus": caucasus, "nevada":
nevada}` made adding a map mean writing a function, and `CAUCASUS_RECOVERIES`
mapped an approach key to the NAME OF A PYTHON CONSTANT in a different module
from the map — so a theatre file could publish a procedure nothing was able to
select. A `[theatre]` table now carries the map's identity, the recovery keys
are the file's, and `catalogue.maps()` discovers what is on disk.

Two silent fallbacks became loud while doing it. `THEATRES.get(want, caucasus)`
swapped an unknown map for the Caucasus without a word, so
`MARSHALL_THEATRE=nevda` gave a bridge working Georgia while its operator
believed it was in the desert — every frequency, fix and field real and on the
wrong continent. Same for an unknown approach key, which is #131's fault one
level up.

**And the migrations stopped shipping flight plans.** Five of them INSERTed a
plan, so every deployment of Marshall anywhere was born believing somebody was
flying Kobuleti to Batumi. Removed: migrations are tracked by FILENAME with no
checksum, so applied databases are untouched and only a fresh install sees the
difference. All five verified against the real schema inside a rolled-back
transaction.

### The Python definitions are gone

`core/fields.py`, `core/stations.py` and `core/approach.py` no longer DEFINE
anything — `FIELDS`, `STATIONS`, `PRESET_LADDER`, the nine seats, the two
aerodromes and the four procedures are all deleted. There is one copy.

**Without touching the ~300 call sites**, which was the point of doing it this
way. A module `__getattr__` in `route.py` resolves those names against the
configured theatre, so `R.BATUMI_ASR` and `R.STATIONS` keep working and read
from the file. That is the same argument `route.py`'s own re-export block
already makes: keep the seam in one readable place rather than spread over
forty files. The names resolve LAZILY too, so a tool that only wants
`spell_alt` no longer needs a configured map to import.

THE CLASSES STAY IN PYTHON. `Fix`, `Field_`, `Station`, `ApproachProfile`,
`may_vector`, the descent geometry — shapes and behaviour are code; only the
INSTANCES were ever data. That sentence is the whole of `docs/CONFIG.md`.

**`PRESET_LADDER` is now derived rather than written.** It was a hand-kept list
of the same seats in the same order, so the card and the theatre could disagree
about which button a pilot presses — and the fix for that is not to write it
twice carefully but to write it once. The file says which seats are rungs
(`preset = false` on Sentry, who is a controller you may call and not a step
you are handed through).

**One subtlety worth keeping.** `R.KOB_CLEARANCE is profile.stations[0]` was
true when both were one module constant, and several tests assert exactly
that — identity is the cheapest way to say "the same controller, not a copy
that happens to match". The caches are keyed on a RESOLVED map name for this
reason: `stations_now("")` and `stations_now("caucasus")` were briefly two
entries holding two equal-but-distinct sets, and four handoff tests went red.

The migration guard is deleted, having done its job twice — a quote turned into
an apostrophe, and #140. Comparing the files to themselves proves nothing; what
replaced it asserts there is nothing left to drift FROM.

### What is still Python, and why

355 proper-noun references remain in live code, against 379 at the audit. The
number stays high because most of what is left is not configuration:

  * **`mission/build.py`** builds the 1944 `.miz`. A mission's own waypoints
    and units belong to the mission — the same distinction as #133.
  * **`intents.py`, `radio/pilot.py`, `radio/rehearsal.py`** are worked
    EXAMPLES — "Pony one one, checking in" teaching a classifier what a
    transmission sounds like. Teaching material, not facts about today.
  * **`core/fixes.py`** still holds the strike's turning points, which is
    correct: they are the sortie's, and publishing them was the original bug.
  * **`core/nevada.py`** was genuinely unconverted, blocked on #141. **BOTH CLEARED 13 August** — #141 turned out to have measured against the wrong VORTAC (see there), and `9275c81` moved Nevada's fields, stations, fixes and approaches into `config/theatres/nevada.toml` behind the same pydantic models. `nevada()` is a reader now, like `caucasus()`.

### Still to move

**Nevada**, blocked on #141 — a real coordinate discrepancy rather than effort.
Publishing a fix means writing down a coordinate AND a source, and its TONOPAH
sits ~34 km from the sim's own VORTAC on a different frequency. Its fields,
stations and procedures could move tomorrow; its fixes cannot until somebody
flies there.

**The "NDB 13" kneeboard page**, which is correctly bound to the NDB procedure
and wrongly bound to the Caucasus — it renders a Batumi plate on any map.

### The counter-example worth copying

`core/dtc.py` already does this correctly: it reads a cartridge the pilot
exported, derives origin, destination, route, altitudes and the comms ladder
from it, and hard-codes nothing about which map or which sortie. The whole file
works on Nevada and Caucasus without knowing either exists. Whatever shape the
fix takes, that is what the rest should look like.

---

## [ARCH-24] A terminal area does not contain the approach it serves — #139
labels: architecture, needs-flight-test

    "If the approach requires us maneuvering outside a 25nm ring then maybe we
     should extend that airspace so that the whole approach is covered by the
     airspace. If the approach doesn't require maneuvering in centers airspace
     but we accidentally cross into center because the pilot f d up, maybe his
     approach should be cancelled and he handed back to center. Trying to
     determine the direction of a ladder and assuming it always goes in one
     direction is brittle."

Right on all three counts, and the arithmetic is worse than the hypothesis.
`airspace.TERMINAL_NM` is 25 nm, but the reach actually published is

    reach = min(TERMINAL_NM, nearest_other_field_nm / 2)

and Kobuleti and Batumi are twenty-two miles apart — so **both terminal areas
are eleven-mile circles.** Batumi's ILS has its outer hold at KOBULETI, which is
those same twenty-two miles out. The procedure begins at double the radius of
the airspace that owns it.

So the 12 August bounce was not a stray: at 27 nm inbound, established, he was
GENUINELY in Center's airspace by the published map. The geometry answered
correctly and the answer was absurd, which is the signature of a volume that
does not describe what it is for.

The midpoint split exists so two adjacent fields do not overlap. That is the
wrong constraint. Real terminal areas overlap, and two fields twenty-two miles
apart whose approaches both reach thirty are one radar room with two names —
which `Station.also` already models for the CONTROLLER and nothing models for
the AIRSPACE.

**What it wants, in the pilot's own two parts:**

  * **The volume is derived from the procedure it serves.** A terminal area must
    contain every fix its own approaches use, plus the manoeuvring room they
    need. Then "he is outside my airspace" cannot fire on a man flying the
    approach as published, on any map, in any era, because the shape comes from
    the procedure rather than from a constant.
  * **Leaving it is an EVENT, not a handoff.** If he strays out of the terminal
    area, the approach is cancelled and he is handed back — said out loud, as a
    controller would. A silent bounce between two frequencies is the thing that
    has no procedural meaning; a cancelled approach has one, and a pilot knows
    what to do about it.

**Blocked on #137.** Computing "does this volume contain that fix" needs the
fixes to carry lat/lon, and in `core/fixes.py` they carry DCS grid metres and
are projected only by asking the sim at bridge start. That is the same root
cause as FEET WET: flight data living in Python.

**Interim, and it is a heuristic, so it is written down as one.**
`leaving_my_airspace` now declines to move an INBOUND aircraft — the trend, not
the range, computed the way `_handoff_state` computes it. It stops the four
Tower-to-Approach offers at one to four miles on final and the Center bounce at
27 nm, and it is exactly the brittle direction test the pilot objected to. It
comes out when the volumes are right.

**Status:** FIXED 14 August, NEEDS A PILOT — card row V6. Both halves of the
pilot's first bullet landed; the second bullet is split out below.

**The volume is derived from the procedure it serves.** `terminal_reach_nm`
takes the furthest fix any of that field's approaches uses and adds
`MANOEUVRE_NM` — five miles, which is not measured and says so — floored at
the conventional `TERMINAL_NM`. So `TERMINAL_NM` went from being the CAP to
being the FLOOR, which is the whole change in one sentence:

    Batumi     11.3 nm -> 27.5     furthest fix KOBULETI at 22.5
    Kobuleti   11.3 nm -> 28.8     furthest fix INITIAL  at 23.8

**The midpoint split is gone.** It existed so two aerodromes could not claim
the same sky, and that was the wrong constraint — real terminal areas overlap.
Where two now do, the nearer field's wins, and that tie is broken where two
volumes are compared rather than where they are drawn: migration 034 orders by
rank and then by the nearer centre.

THE HAZARD THE SPLIT WAS GUARDING IS REAL and is now handled somewhere it can
be. `tests/test_every_aerodrome_has_sky.py` recorded it exactly — *"what
happened on the first attempt at this, when both were given the full terminal
range and an aeroplane on Kobuleti's ramp resolved to Batumi Approach"* — so an
aeroplane on Kobuleti's ramp is inside both areas and is still Kobuleti's: by
rank, because the circuit outranks a terminal area, and by distance under that.

`tools/airspace_check.py` proves it against the live view, because the rule is
an `ORDER BY` and a unit test asserting the migration's TEXT proves the file
says something rather than that the database does it. It is a `check.py` row.
It also caught its own first failure honestly: a stale `flights` row from an
aborted run carried no track, the view's LEFT JOIN found none, and the
aeroplane fell through to the unbounded Center — reported as "overhead Batumi
-> georgia-center", which reads exactly like the bug it exists to find.

**Split out as #174:** the pilot's second bullet — *"leaving it is an EVENT,
not a handoff: the approach is cancelled and he is handed back, said out
loud"* — is controller behaviour rather than geometry and has its own issue
and its own criteria. A silent bounce between two frequencies still has no
procedural meaning; it is just no longer fired by a volume that was too small.

**What this unblocks:** #130. The ladder can now read the map without holding
an arrival on Center until eleven miles, which is why that alignment was
reverted on 13 August.
---

## [ASR-8] The 1944 letdown profile carries no controllers at all — #140
labels: bug, needs-flight-test

Found while moving the approaches into configuration (#137), by a test that
asserts the file says exactly what the Python said.

`BATUMI_APPROACH` -- the period beacon letdown -- is built with `stations=[]`,
where every other profile carries the theatre's nine. And it is SELECTABLE:

    CAUCASUS_RECOVERIES = {"batumi-ndb": "BATUMI_APPROACH", ...}
    MARSHALL_APPROACH=batumi-ndb

So a bridge started on the 1944 flavour has a controller who cannot name a
single frequency. `station_for` returns None for every role, which means no
handoff can be spoken, no departure frequency can be issued, and the refusals
that name a frequency -- "Take-off is Tower's, contact Kobuleti Tower one three
three decimal zero" -- lose the half that tells a pilot what to do.

Nobody has flown it, which is why nobody has noticed.

**Preserved deliberately for now.** The configuration file sets
`theatre_stations = false` on that one procedure and says why, because a data
migration that quietly changes behaviour is worse than the defect it fixes --
that is how you end up unable to tell a regression from a correction. The fix
belongs in its own commit.

**What it probably wants:** the station list is the THEATRE'S and not the
procedure's, which is the unfinished half of #2. An approach should not carry
stations at all; it should name the field it serves and let the theatre answer
"who works here". Then this profile has controllers because Batumi has
controllers, and the question cannot be answered differently by two procedures
at one aerodrome.

**Status:** FIXED 14 August, NEEDS A PILOT — card row V11. `theatre.beacon_seats`
supplies the controllers a period procedure actually has, and the answer was
already in the data:

    INITIAL   128.0   Batumi Approach     (arrival_fix — where he is worked)
    KOBULETI  124.0   Kobuleti Departure  (outer_hold)
    BATUMI    132.0   Batumi Tower        (navaid — the beacon he homes)

Each fix carries the seat that owns its frequency, because on this procedure
the frequency IS the navaid. `Station`'s own docstring has said so all along:
*"the controller had to sit on the beacon you were homing, because the ARA-8
tunes and homes on one frequency at a time."*

**Not the modern ladder, which is the other wrong answer and the worse one.**
Handing this profile `stations_now()` would tell a Mustang to contact Batumi
Tower on 118.6 while his set is homing 132.0 — a real controller on a frequency
the aeroplane cannot tune. A test asserts no seat of his carries a modern
frequency, and that every modern frequency resolves to nobody through his
procedure.

The issue proposed dropping the station list from the approach entirely and
letting the theatre answer. That is right for the MODERN procedures and is
already how they work; it is wrong here, because "who works this field" has a
different answer in 1944 and the era is exactly what this profile exists to
model. The period flavour stays in `AtcCapability` (no DME, procedural
separation, no vectors) and the SEATS are a fact about which radios exist.

**Two tests asserted the old emptiness and both argued against it in their own
docstrings** — *"its controllers live on the BEACONS"* and *"the man you talk
to IS the frequency you home"* — while asserting `None` and a push of nothing.
They assert the beacons now, and keep the guard that was always the real point:
a modern frequency must not resolve through this procedure.
---

## [ARCH-25] The 1944 beacons are fiction sitting where the real navaids go — #145
labels: architecture

    "importing a map's naviads should be dead simple ... We can get rid of
     those 1944 beacons for now.. I dont know how/if we'll use those again"

`tools/import_beacons.py` lands the easy half: 122 tunable navaids for the
Caucasus and 27 for Nevada, straight out of the sim's own `Beacons.lua` with
both frames of position, no projection and no transcription. A new map costs a
command.

**What it exposed** is that a published "fix" is still two things welded
together, exactly as `ApproachProfile` was:

    a position   real, from the sim, correct in every era
    a navaid     ident, frequency, type -- which is Beacons.lua for a modern
                 sortie and INVENTED for 1944

Ours against the sim's, for the same three fields:

    BATUMI    OS  132.0 ndb      vs   ILS ILU 110.3 · TACAN BTM · homer LU 0.430
    KOBULETI  MG  124.0 ndb      vs   ILS IKB 111.5 · TACAN KBL · homers KT/T
    KUTAISI   KT  --             vs   VOR KT 113.6 · TACAN KTS · ILS IKS
    INITIAL   SW  128.0 ndb      vs   nothing; we invented it

The POSITIONS agree to a tenth of a mile — both descend from the aerodrome
reference point. Every ident and frequency does not. A modern pilot tuning
"BATUMI 132.0" gets silence: the homer is 0.430 and the TACAN is BTM.

That matters because of the rule in `docs/CONFIG.md` — a pilot flies his
steerpoints and the navaids he can TUNE — and *tunable* means the frequency has
to be the one the aeroplane will actually receive in the era it is flying.

**INITIAL is out, 12 August**, and the interesting part is what it took two
failed attempts to find. The point itself moved exactly as planned: the four
approaches that name it carry it as `[approach.own_point]` — same position, same
ident SW, same 128.0 — and `theatre.published_approaches` resolves a fix role
against the published catalogue first and the procedure's own point second. The
published Caucasus catalogue is now the three aerodromes and nothing else, which
is `docs/CONFIG.md`'s rule stated as data: *a fix needs a NAME only if he can
fly to it.*

**What it broke was `check_in`, and the fault was not in the change.** Both
attempts died on the same four tests — a departing aircraft told to report an
approach fix, a man on the ramp given an arrival briefing, a radar controller
announcing "radar not available". `check_in` opened with this:

    fix = self._pro(ac).arrival_fix
    if fix is not None and tower_freq and tower_freq != here_freq:
        call = f"..., radar not available, report {fix.name}. ..."

From the SHAPE of the procedure's fix data it concluded two things nobody had
told it — that the controller has no radar, and that this aeroplane is arriving
— and it sat above every branch that asks those questions properly. It is #53
again: *a capability is declared, never inferred.*

Both halves were already wrong. `BATUMI_APPROACH` is the only profile carrying
an `arrival_fix`, and it sets `radar=True` **on purpose** — `SeeingHimAndSteering\
AreTwoCapabilities` asserts exactly that, "he can see him", because the
controller reads ranges off his own scope while the pilot flies the pattern on
the beacon. So the engine has been telling a pilot the radar is out while the
same profile tells the rest of the system it is up, and `agent_atc` string-
replaced the phrase back out on the way to the radio:

    if directive and ctl.profile.atc.radar:
        directive = directive.replace("radar not available, ", "")

A correction applied by the one component that cannot know whose aeroplane it
is. `ctl.profile` is the BRIDGE's arrival and two profiles are worked at once,
so a genuinely blind controller's warning was stripped whenever the bridge's own
procedure had radar — the failure it existed to prevent, wearing the other hat.

It survived because that profile carries no station list (#140): no Clearance
seat and no Departure seat to be wrong at. Publishing INITIAL was what kept any
LADDERED procedure from carrying an arrival fix, so retiring it made a two-week-
old bug reachable, which is this file's oldest shape — *correct by accident,
because a question with one possible answer cannot be answered wrongly.*

Fixed at the source: the arrival-fix greeting is nested inside the guard it
should always have shared with the greeting below it (`_arriving` and a seat
that works arrivals — they are one greeting spelled two ways), the phrase is
`atc.radar`'s and the capability is the AIRCRAFT's. The plaster in `agent_atc`
is deleted and replaced by `AnArrivalFixIsNotEVIDENCEOFANYTHING` in
`tests/test_two_fields.py`, which asserts both directions.

The third thing worth writing down: **an unused role is not an unresolvable
name.** Both attempts fell back to the procedure's own point on an empty string,
so the radar ASR — which names no `arrival_fix` at all — acquired one. That is
what actually turned a latent bug into four red tests.

**Still to do:**

  * the other three invented beacons. BATUMI, KOBULETI and KUTAISI are
    aerodromes and stay published; what is invented is their ident and
    frequency, which is the era question rather than the catalogue question.
  * the ILS, which is the half that needs interpretation: a localiser and a
    glideslope are two entries at two positions sharing one frequency, and
    turning that pair into a procedure needs a course and a threshold. It
    belongs with the approach, not in a mechanical import.
  * Nevada's #141 is unblocked by this — its navaids are now imported and
    citable, so the question is only whether the TONOPAH steerpoint was ever a
    navaid at all.

**Status:** PARTLY — the importer and the catalogue are real and in:
`tools/import_beacons.py`, 122 navaids on Caucasus and 27 on Nevada, and INITIAL
retired out of the published fixes into `[approach.own_point]` (`a9e8b34`,
`1e35bf9`), with `AnArrivalFixIsNotEVIDENCEOFANYTHING` in
`tests/test_two_fields.py` guarding the `check_in` bug that came out with it.
The "still to do" above is untouched: KOBULETI is still published as the
invented `MG` on 124.0 and KUTAISI as `KT`, and the localiser/glideslope pair is
not a procedure.

---

## [ARCH-26] A proposal half of the tree already obeys, and nobody could tell which half — #147
labels: architecture, documentation

    "I remember making this decision and I cannot find it."

He was right and I told him it probably was not written down. It is —
`docs/STRUCTURE.md`, 31 July, "Naming the parts, and the layout that follows" —
and a search for "rename" does not find it because the document never uses the
word. That is the smaller half of the problem. The larger half is that the
document was written in the present tense about a layout we did not have, and
by 12 August roughly half of it had quietly become true, so it read as a
mixture of description and intent with nothing marking which sentence was
which. Its own preamble warned about exactly this and the warning did not work:
**a document nobody can date is a document nobody can find.**

**Reconciled, 12 August.** Every claim in `STRUCTURE.md` is now marked APPLIED,
PARTLY APPLIED, STILL INTENT or SUPERSEDED, with the commit that landed it. The
reasoning is untouched, because the argument for why a name was wrong survives
whether or not the rename happened.

**What had landed:** `feed` out of the director and `srs` → `radio` (574906a);
the prompts into the domain that speaks them (ebea93a); `route.py` split into
six modules and a façade (df6ea5b); fields, stations and the four procedures
into `config/theatres/*.toml` (03edb35, 311028a, 118a9e6); `kneeboard` as one
module with `diag` as a page (e15c57c).

**What had not, and this is the finding worth keeping.** The parts of the
proposal about SHAPE landed; the parts about DELETION did not, and two went
backwards:

    director/app.py routes         24  (31 July)  ->  34
    the flights SQL module        326 lines       ->  377
    the /radar prose parsers      to be deleted   ->  replacement built
                                                     (c6afa12), old path
                                                     never switched off (#47)

A structure change is easy to celebrate, because afterwards somebody can point
at the new directory. A deletion nobody is accountable for does not happen.

**THE DEPLOYABLE NAMES: decided, and the decision is NO.** `STRUCTURE.md` argues
that "bridge" and "director" are accidents — the director was a separate repo
merged by subtree on 25 July and the folder is the seam — and names them
functionally instead: `marshall-radio`, `marshall-atc`, `marshall-feed`,
`marshall-kneeboard`. The argument is right and the rename is deferred, for
three costs the argument does not price:

1. **The database.** `director/docker-compose.yml` pins `name:
   marshall-director` because the Postgres volume is `marshall-director_pgdata`
   and compose otherwise derives the project from the DIRECTORY. A folder rename
   that forgets the pin brings the agent up on an empty volume — no contacts, no
   sessions, no approaches — looking entirely healthy. A rename that must
   preserve the old name in the one place a machine reads it is a rename of the
   documentation only.
2. **The subtree.** `git subtree add --prefix=director` (c5c5617), and
   `diff -r /tmp/fresh-stamp director/` is how upstream is pulled.
3. **`director/.env`**, which is this machine's credential file, git-ignored,
   read by `src/marshall/config.py` as the single door. A rename moves a file
   that is not in the repository, on a live box.

**And the naming argument turns out to be a proxy for a layering argument**,
which can be won without touching a directory name. Two of its premises have
already expired: the "two unrelated things sharing a container" complaint was
answered when `feed` left, and the prompts complaint when they left. What is
left inside the deployable is `director/tools/` — twelve modules of ATC domain
reasoning (`approaches`, `clearance`, `flights`, `identify`, `plans`,
`frequencies`, `capability`, `filing`, `hooks`, `context`, `ops`) findable only
by somebody who already knows to look in a container. That is the prompts
problem one layer down.

**THE WORD ITSELF COSTS COMPREHENSION, and that half needs no rename at all.**
13 August, reading an answer that explained a datum by saying "the bridge was
started on `batumi-asr`":

    "The bridge is not the term we should use, I think you mean radio and/or srs"

He is right about the referent — the thing that holds `APPROACH_NAME` and the
one `ApproachProfile` is the radio process, `python -m marshall.atc.agent_atc
--srs`, which `STRUCTURE.md` already proposes to call `marshall-radio`. And the
misreading it produced is not cosmetic: "the bridge has an approach loaded"
sounds like an implementation detail, where "**the radio** has an approach
loaded" is self-evidently absurd and is exactly why #162 exists. A name that
hides the wrongness of a design is doing damage while the rename is deferred.

So item 1 below is not the cheapest item, it is the one with a live cost:
`console_scripts` make the four names real, and then the documentation, the
issues and the answers can stop saying "bridge" without any directory, volume
or subtree moving.

**Remaining scope**, in order, none of which requires a rename:

1. `console_scripts` in `pyproject.toml` for what already exists —
   `marshall-kneeboard`, `marshall-radio`. Costs nothing and makes the four
   names real for the first time.
2. `_run_srs` out of `agent_atc.py` (#55). Until the bridge's entrypoint is an
   importable function, "a deployable is an entrypoint" has no referent.
3. `director/tools/` into `src/marshall/atc/`, the same move as ebea93a. This
   is where the value is.
4. The endpoint and `flights.py` deletions, which fall out of 3.
5. Only then is the directory name uninteresting enough to change safely.

**Acceptance criteria**
1. `docs/STRUCTURE.md` marks every claim with a status, and a reader can tell
   the target from the tree without opening the source. (Done.)
2. `CLAUDE.md` says that "bridge" and "director" are directory names rather
   than a design, and states the `marshall-director_pgdata` constraint at the
   point of temptation. (Done.)
3. The four entrypoint names exist as `console_scripts` and the documentation
   uses them.
4. `director/tools/` holds no ATC domain reasoning.
5. `director/app.py` has fewer routes than the 34 it has today, and the count
   is in the issue when it changes.

Code: `docs/STRUCTURE.md`, `CLAUDE.md`, `docs/START_HERE.md`, `pyproject.toml`,
`services/` (was `director/`).

**Status:** PARTLY — 18 August, and this line is a correction of the one I
wrote an hour earlier, which said "1, 2, 3 and 4 are met". Criterion 3 is not
met and saying it was is the exact failure #162 was filed about: **a criterion
is met or it is not, and a nearly-met one closes an issue that then never gets
finished.**

    1  met      the scoreboard dates every claim
    2  REWORDED it asked for the `marshall-director_pgdata` constraint to be
                stated at the point of temptation. That constraint is FALSE --
                there is no such volume -- so the criterion now asks for the
                pin and the reason it does not follow the folder
    3  NOT MET  two of four commands. `marshall-atc` and
                `marshall-kneeboard` exist; `marshall-radio` waits on #55 and
                `marshall-feed` is not a process
    4  met      no ATC domain reasoning under `services/tools/`
    5  NOT MET  36 routes against the 34 this was written about, and going
                the wrong way

**This issue does not close today.** The folder moved and the command exists,
which is most of the value; two criteria remain and one of them (5) is really
the CRUD-deletion work wearing this issue's number.

**Criterion 3 is met, and the reason it took a fortnight is the finding.**
`pyproject.toml` declared `marshall-kneeboard` alone, with a comment saying
`marshall-radio` AND `marshall-atc` both waited on `_run_srs` leaving
`agent_atc.py` (#55). Half of that was true:

    marshall-radio   a separate PROCESS. Genuinely #55. Still a comment.
    marshall-atc     THIS process. Wanted a function to point at, which is
                     nine lines of argument parsing lifted out of an `if`
                     block into `agent_atc.main`. Never needed #55 at all.

Two questions filed as one, and the wrong half's blocker held both. That is
the same shape as the folder and the vocabulary below, and as #162's `_seats`
switch — a pattern worth naming, because in each case the honest answer was
available the whole time behind a constraint that applied to something else.

**Criterion 4 is met and the folder moved: `director/` is `services/`.** The
three costs, measured rather than reasoned about:

1. **The database — gone, and it never existed.** There is no
   `marshall-director_pgdata`; `docker volume ls` shows no marshall volume and
   the data is a bind mount to `/srv/pgdata/data`. The compose pin
   `name: marshall-director` STAYS and does not follow the folder: it is the
   running deployable's identity, which is why `cd services && docker compose
   up -d` reached the same containers. Done live, with the stack up. Row
   counts either side: contacts 0, flights 2, approaches 6, flight_plans 3,
   stations 9 — identical.
2. **The subtree — a flag, not a blocker.** A prefix is an argument you pass,
   not a relationship stored in the repo. `git subtree pull --prefix=services`
   and `diff -r /tmp/fresh-stamp services/`.
3. **`director/.env` — evaporated on contact.** `git mv` on a DIRECTORY is a
   filesystem rename, so the git-ignored credential file travelled with
   everything else. Nothing was moved by hand. The cost was real to reason
   about and nil to pay, and finding that out took reading what `git mv` does.

**The correction that killed cost 1 landed in `CLAUDE.md` and stopped there.**
`0d60d07` fixed `CLAUDE.md` and this file on 17 August and did not touch
`docs/STRUCTURE.md` — which `START_HERE.md` names as *"read it before renaming
a directory"*. So the fix for a stale constraint left the stale constraint in
the document that decides the thing it was blocking, for another day. **A
correction is not landed until it reaches the document somebody will actually
consult.** That is the second-order lesson and it is worth more than the
rename.

**Criterion 5 is the only one open**, and it has gone backwards again:
`services/app.py` has 36 routes against the 34 this was written about. The
route count is not a rename problem and belongs with the CRUD deletion.

`marshall-director` survives as the compose PROJECT name. That is correct and
is not leftover: the deployable's identity is not its directory, which is the
whole argument this issue makes, arriving from the other side.

---

## [ARCH-27] The procedure a decision is made from is the bridge's, not the aeroplane's — #150
labels: architecture, needs-flight-test

`Controller._pro(ac)` is the owner of *"which approach is this aeroplane
flying"* and has been since two aircraft could recover to two fields. It is
consulted by the proactive monitor (`may_vector(_pro)`, `asr.guide(pos, _pro)`,
`is_the_intercept(g, _pro, pos)`) and by almost nothing else. The audit for
#146's siblings, 13 August, listed the sites that still read the bridge's:

    agent_atc.leaving_my_airspace:3380   getattr(profile, "guidance", "")
                                         -- the talkdown guard on the airspace rung
    handoff._inbound_within:201          getattr(profile, "guidance", "")
                                         -- "a talkdown makes LANDING the trigger"
    agent_atc.asr_context:1526           may_vector(profile)
    agent_atc.decide:2642                asr.guide(fix, ctl.profile, ...)
    agent_atc.settle:4322                _phases.guide(phase, fix, profile)

Each is a property of a PROCEDURE, and the failure is the one this project
keeps meeting: the wrong answer is a real answer. A Mustang on the 1944 letdown
beside a Viper on the ILS gets the Viper's rule about when Tower takes him,
because the bridge was started on the ILS.

`intents.dispatch` was the sixth and is fixed — it gated the reachability of a
station-passage report on the bridge's `kind` and `atc.radar` rather than his.
It is listed here because the fix is one line at each site and the risk is not:
`next_controller` uses `profile` for the STATION TABLE as well as the
procedure, and those are deliberately different things (see `_pro`'s docstring —
"who works ground at Kobuleti" is the theatre's and cannot differ per flight).
Threading `_pro` through it without separating the two would hand an aeroplane
another theatre's controllers.

This is the terminal half of #2 and #111 with the call sites enumerated, which
is the part that was missing. The same shape as #76: a fix applied to one call
site and not its siblings.

**Acceptance criteria**
1. Every site that asks a profile about the PROCEDURE (`kind`, `guidance`,
   `atc.*`, the geometry) reads the aircraft's, via one accessor.
2. Every site that asks a profile about the THEATRE (`station_for`,
   `station_on`, `stations`) reads one shared table, and a test asserts the two
   questions cannot be answered from the same argument by accident.
3. A test flies two aircraft on two procedures through one bridge and asserts
   each gets his own guidance rule.

Tests: beside `tests/test_two_fields.py`.
Code: `src/marshall/atc/agent_atc.py`, `src/marshall/atc/handoff.py`,
`src/marshall/atc/controller.py`.

**Status:** FIXED 13 August, NEEDS A PILOT — card row S15. The accessor is
`controller.procedure_of` (free function) and `Controller.procedure_for` (by
callsign); its docstring carries the line between the procedure question and
the theatre question, because a rule that lives only in a test is one the next
person breaks before the test tells them.

**RE-VERIFIED 18 August, and #162 made it unconditional.** This read FIXED
while the fallback it was about still existed: `procedure_of(ac, fallback)`
answered the AEROPLANE's procedure and fell back to the radio's, so every one
of the five call sites was right only because it had been individually
corrected. There is no bridge profile now -- `_pro` returns None rather than a
process-wide arrival -- so the fault this issue describes has no mechanism left
to occur through. The guard tests moved with it and got STRONGER: they assert
the parameter is ABSENT from the signature rather than that the body reads the
right variable.

SEVEN SITES, NOT FIVE. The five enumerated above are done. Sweeping for
`ctl.profile` rather than working the list found two more inside
`separation_context` that nobody had listed — whether a beacon is flown at all
(so a Mustang genuinely over the beacon was told he had not reached it), and
the DATUM a radar range is measured from (twenty-two miles of error between
Kobuleti and Batumi, quoted to a pilot as fact). An eighth, `his_station`, went
the same way. There are now no live reads of `ctl.profile` in `agent_atc.py`
and a test asserts it.

Criterion 2 held without changes and is now checked: `station_for` takes a
`procedure` and asks it ONE boolean about itself — `theatre_stations`, whether
it staffs the ladder — and never yields a Station. Seats come from the map for
everybody. That distinction is what would have made this fix worse than the
bug if it had been fumbled, so it is asserted rather than assumed.

NOT DONE, AND SPLIT OUT AS #173: `asr_monitor` picks its transmit channel once
at thread start from the bridge's procedure, then uses it for every aircraft's
mile calls. It is the same fault and not the same shape — a radio-path change
rather than a lookup — so it is its own issue with its own criteria rather than
a footnote here.

One correction to the entry above: the test file went in beside
`tests/test_two_fields.py` in argument but not in name — it is
`tests/test_two_procedures_one_bridge.py`, and it records that its first
version passed for the wrong reason. It compared an ILS against the map's
published letdown, which staffs no ladder at all, so `handoff.due` returned
None for reasons that had nothing to do with guidance and would have gone on
doing so if the talkdown rule were deleted outright.
---

## [SEAM-18] A read-back correction names what is missing in PROSE, so nothing checks it was said — #157
labels: bug, needs-flight-test

Found by `tools/ghost_flight.py --sortie` on 13 August — the first run in which
one aeroplane climbed the whole ladder under one callsign.

The engine decided this:

    CONTROLLER: Marlin three one, negative — say again one zero thousand,
                one two three decimal three.

and what reached the air was this:

    ATC[pilot/sonnet]: Marlin three one, negative — say again the altitude,
                       one zero thousand.

**One of the two missing items was dropped on the way to the radio, and nothing
noticed.** The frequency he had never read back is now a fact he has not been
asked for, so the exchange cannot terminate on the next transmission however
carefully he answers — which is the shape of #134, arriving through a door that
fix did not close.

**Why the repair mechanism could not help.** `Controller.clearance_read_back`
emits `Decision(kind="say_again", note=what)` and `note` is prose by
construction: `Decision.facts()` excludes it deliberately, so `decision.verify`
has nothing to check and `not_voiced`/`repaired` cannot fire. Every other
number the engine decides is verified against the transmission and put back if
it went missing. The one transmission whose entire purpose is to name numbers
is the one with no numbers in it.

`decision.verify` returns the missing items as SPOKEN FORMS -- strings -- which
is why they land in `note`. To carry them as facts the verifier has to say
which FIELDS were missed, not merely how they sound, and `_read_back_correct`
has the original `Decision` in hand to rebuild a typed one from.

**Acceptance criteria.**

- A correction that the engine decided names N missing items, and the
  transmission that goes out contains all N or is repaired to.
- `not_voiced` fires when one is dropped, naming which.
- A regression test drives the 13 August pair verbatim: two missing items in,
  one voiced, and the check goes red.

Tests: needs one; the sortie rehearsal counts corrections but cannot see which
items each named.
Code: `src/marshall/atc/controller.py` (`clearance_read_back`),
`src/marshall/atc/decision.py` (`verify`, `Decision`),
`src/marshall/atc/agent_atc.py` (`_read_back_correct`).

**Status:** FIXED 13 August, NEEDS A PILOT — card row G12.
`decision.accepted_forms` now returns a `Form` carrying the FIELD each fact
came from, not only how it sounds, and `decision.unspoken` returns those forms
for what went missing. `_read_back_correct` hands them up as
`{field: value}`, `Intent.missed_facts` carries them, and
`clearance_read_back` builds `Decision(kind="say_again", ..., **facts)` — so
the ordinary verify-and-repair path does the rest, exactly as it does for every
other decision. The phrasebook learned to render a correction from its fields,
because `repair` returns "" for a kind it cannot phrase and that silent no-op
meant `say_again` was recorded unvoiced and never put back.

`tests/test_a_correction_names_numbers.py` drives the 13 August pair verbatim
and keeps the OLD shape as an executable statement of the bug: a correction
carrying only prose verifies CLEAN against a transmission that dropped half of
it. Not "fails quietly" — reports success. That is why nothing ever noticed;
the check ran on every turn and had nothing to look for.
---

**FLOWN 28 AUGUST AND FAILED, card row G12.** The correction itself was right --
*"negative on two items -- departure frequency is one two three decimal three,
and squawk is zero zero five five. Read those back."* -- and both items were
named and voiced, which is what this issue is about. What went wrong is the
turn after: the pilot read back exactly those two and the engine came back with
*"say again five thousand"*, an item he had read back correctly first time.

Every engine utterance in that exchange is explained by each transmission being
judged ALONE, not cumulatively. Driven in isolation with a shared bridge the
carry-forward works, so the logic is right and something about its lifetime in
the live process is not. See #208, which is the other end of the same
accumulator.

## [ARCH-31] An approach is identified by its runway, and a navaid by its ident — #165

Two findings from reading one table out loud:

    "An airdrome is batumi, a navaid is a specific transmitter (vor, tcb, ndb)
     and batumi_ils … I don't know what that is. There could be multiple ils
     approaches into a field"

Both are right, and the second is live rather than theoretical.

### A key of `<field>-<kind>` cannot name two ILS approaches at one field

Every procedure is keyed `batumi-ils`, `kobuleti-ils`, `nellis-ils`. **Batumi's
runway is 13/31.** An ILS to 31 is an ordinary thing to add — it is the same
localiser from the other end — and the moment it exists:

    _approach_named("batumi-ils")   ->  two candidates, returns the FIRST

That is #131's bug exactly, one axis over. `startswith(f"{name}-")` matching
every approach at an aerodrome is what cleared a pilot for a "radar approach"
while his plate said ILS on 12 August; the comment recording that sortie sits
directly above the line that would now do it again on the runway axis instead of
the kind axis. The fix then was to match exactly first. The key simply cannot
express the distinction.

Real procedures are named for the runway they serve — ILS RWY 13, ILS Z RWY 13,
VOR RWY 31 — because the runway is what makes two approaches at one field
different things. The key must carry it:

    batumi-asr-13   batumi-ils-13   batumi-ndb-12   kobuleti-ils-07
    nellis-ils-21   tonopah-ils-32

And an ambiguous request must ASK rather than pick. That principle is already
built for flight plans — "which plan a spoken request means, and when to ASK
instead of picking one", #1 G3/G4 — and is exactly as true here.

### A navaid is a transmitter, not a place

The 1944 letdown's navaid resolves to:

    name='BATUMI'  ident='OS'  freq=132.0  kind='ndb'

A navaid is identified by its IDENT — `OS`, `LU`, `BTM`, `TPH`. `BATUMI` is an
aerodrome. #163 gave the datum its own slot and stopped the two sharing one
field, but the navaid it left behind is still *named for the airfield*, which is
the same conflation wearing its last disguise. The sim's own table has the real
transmitters at that field: `LU` (NDB 0.430) and `BTM` (TACAN 16X).

Note this one changes what is SPOKEN — "hold at BATUMI as published" becomes
"hold at the OS beacon" or similar — so it is a phraseology decision as well as
a data one, and wants a human's ear rather than a green suite.

**Acceptance criteria.**

- Two ILS approaches to opposite ends of one runway can both be published, and
  each resolves to itself. A test adds `batumi-ils-31` and proves it.
- An ambiguous approach request is refused with the candidates named, never
  resolved by list order.
- The navaid a procedure names is a transmitter with an ident, and no procedure
  names a navaid whose name is an aerodrome.
- Nothing a pilot hears changes for the runway-key work (it is an identifier);
  the navaid work DOES change phraseology and is flown before it is closed.

Tests: `tests/test_the_right_approach_by_name.py` is the home for the first;
the second wants `tests/test_a_beacon_is_not_an_airfield.py`.
Code: `config/theatres/*.toml`, `src/marshall/atc/agent_atc.py`
(`_approach_named`), `src/marshall/core/theatre.py`, and the stored
`flights.cleared_approach` / `assigned_plans.approach` values, which carry the
old keys and must migrate.

**Status:** PARTLY — the runway half is in and deployed, and the line that stood
here (waiting for `agent_atc.py` to be free) is stale. `_key_of` builds and
resolves `<field>-<kind>-<runway>` and refuses an ambiguous request by naming
the candidates (`55ee8b1`), the theatre files and the stored approaches were
migrated with it (`c4f530c`, migration 033, live keys now `batumi-ils-13` and
the rest), the sweep was pointed back at the real resolver rather than its own
copy (`51e3d0e`), and `tests/test_the_right_approach_by_name.py` publishes two
ILS approaches to opposite ends of one runway and tells them apart. The navaid
half is untouched: `config/theatres/caucasus.toml` still has the 1944 letdown
naming `navaid = "BATUMI"`, an aerodrome standing where a transmitter's ident
belongs — and that half changes what a controller SAYS, so it is flown before it
is closed.
Labels: needs-flight-test

---

## [ARCH-32] `enroute` is unreachable, and it takes the whole task half with it — #168
labels: bug, needs-flight-test

`phases._wanted` decides which phase an aeroplane should be in. Its complete set
of returns:

    "landed"  ·  current or ON_THE_GROUND[0]  ·  "landed"  ·  "departure"
    "missed"  ·  "approach"  ·  "holding"  ·  "arrival"  ·  current

**`"enroute"` is not among them.** The word appears in `phases.py` only inside
comments and `follows` tuples, so the phase is declared, is owned by Center, is
named in four other phases' `follows` — and nothing can ever put an aeroplane in
it. Swept from `departure`, the reachable set is `{arrival, departure}`.

**And `tasked` / `on_station` follow only from `enroute`**, so the entire
out-and-do-something half of a sortie is unreachable by construction. A strike,
a CAS check-in, a tanker join: the phase machine has vocabulary for none of it in
practice, however it reads on the page.

**Why nothing noticed.** Handoffs key on the controller's ROLE, not on the phase,
so the ladder still runs correctly — a departing aeroplane reaches Center and is
handed on properly while the board says `departure` the whole way. The phase was
wrong and nothing downstream of it was, which is why this survived #63 (which
fixed every other phase) and reads as fine on a recovery-only sortie.

It is not #91's welding: no refusals were logged on the sortie where this was
found. Nothing tried to move him and was blocked; nothing tried.

**Acceptance criteria.**

- A departing aircraft beyond the terminal area is `enroute`, and the board says
  so while Center works him.
- `tasked` and `on_station` are reachable from it, and a test walks the whole
  outbound half the way `test_a_sortie_is_flown_end_to_end` walks the recovery.
- The phase and the ladder agree: a test asserts that for every phase, the
  controller `handoff.due` would give him is the controller `phases.owner_of`
  names. Those two answering differently is what hid this.

Tests: `tests/test_phases_derive.py` is the home.
Code: `src/marshall/atc/phases.py` (`_wanted`).

**FIXED 13 August.** Being handed to Center is what "he is enroute" MEANS, which
is the argument the `arrival` rule one line above already makes about Approach —
so the fix is that rule's mirror, and it was simply never written. Not from
`rtb`, which Center also owns: a man coming home must not be re-derived into the
outbound leg every poll.

Safe against the inversion the neighbouring comment warns of. `enroute` aims at
a POINT rather than "none", so `handoff.due`'s phase-ownership branch never
fires for it and the rules table goes on deciding by role — the same reason the
`arrival` rule is safe.

**The test is the general form**, because a test that `enroute` is reachable
would pass for ever while the next phase went the same way. It sweeps every
phase in the table against every input the deriver can be handed, and **counts
only TRANSITIONS** — the first version counted `derive(x) -> x` and would have
passed on `enroute` the day before the fix, which is the exact thing it exists
to catch.

It flagged three more, and all three are honest: `rtb` is a stated intention and
deriving it from a turn towards home would be guessing at intent; `unknown` is
"heard on the radio and nothing more"; and `filed` is "a plan exists and there
is no aeroplane yet", which a deriver that runs for an aeroplane on radar can
never produce. Each is named in the test with the reason from its own
declaration, so the list is a claim somebody can argue with.

**Still missing, and not implied fixed:** `tasked` and `on_station` are now
reachable in PRINCIPLE — `enroute` was the prerequisite — and still have no
trigger. An overlord has to task him and there is no seat doing that. A test
asserts they remain underivable, so building the trigger will fail it and force
the claim to be updated.

**Status:** FIXED 14 August, NEEDS A PILOT — card row V9. The third criterion
landed and FOUND A LIVE BUG on its first run, which is the argument for having
written it rather than closing on the other two.

`tests/test_the_phase_and_the_ladder_agree.py` asserts that the controller a
phase names and the controller the ladder gives him are the same man: every
phase owner is a seat the map staffs, every rule role is one too, and for a
phase with no geometry `due` returns exactly `owner_of(phase)`.

**WHAT IT CAUGHT.** An aeroplane at eight thousand feet in the `clearance`
phase was handed to **Batumi Ground**. The guard in `due` asked
`owner_of(phase) in _GROUND_SEATS` against a hand-written
`("ground", "clearance")` — and `phases.clearance.owner` is spelled
**`"delivery"`**, which is in neither. `Station.also` carries both spellings so
every lookup worked and nothing ever looked broken.

The invariant it broke is the pilot's own: *"Yes, an airborne airplane is never
ground's. Just have tower take him back if he's flying."* It was enforced
everywhere except through the one seat whose role has two names — and the list
sat under a comment saying "named once ... two lists would drift". It drifted
through a third spelling nobody had counted.

`_GROUND_SEATS` is derived from the phase table now, so a rename in `phases.py`
carries by construction, with the two literals kept as a floor for a theatre
that staffs no delivery seat.

**Still open and still second criterion:** `tasked` and `on_station` have no
trigger. An overlord owns them, the map staffs one, and no rule reaches him.
That is asserted rather than forgotten — the test fails on the day somebody
builds it, with instructions to delete the class.
---

## [KB-6] The board's datum is the fallback whenever nobody has just spoken — #169
labels: bug, needs-flight-test

`field_origin` takes the SPEAKING controller's field, and only the transmission
path passes one: `agent_atc.py:5154` hands the seat's field in, while the
hook-tick publishes at `:5753` and `:5796` fetch radar with no `field=` at all.

So a board refreshed by the metronome — which is most refreshes — always renders
the fallback datum, whatever the seat working him would have measured from.

**Harmless today, and that is the trap.** Center is fieldless anyway, so the
fallback is what he would have used; the number and the "why" both happen to be
right. The moment #160 lands and a datum is chosen per aeroplane, this path will
go on printing the loaded approach's field while the controller measures from the
destination — and the page will be confidently wrong rather than honestly odd,
which is the exact regression the datum work was written to prevent.

**Acceptance criteria.** The datum a board row shows is the one the controller
working him would use, on a tick with no transmission in it — asserted, because
the failure is invisible while the two answers agree.

Code: `src/marshall/atc/agent_atc.py` (the hook-tick publishes).

**Status:** FIXED, NEEDS A PILOT — card row V10. The fix landed in `392f961`
and this entry went stale: `worked_from` has resolved the datum PER ROW since
then, from the seat working that aeroplane, re-measuring the range from the
contact's own position rather than relabelling it.

**RE-VERIFIED 18 August.** `worked_from` and `field_origin` both changed under
this issue when #162 removed their profile argument; the datum is resolved per
ROW from the speaking seat exactly as before, and `test_the_board_measures_from_his_seat`
was updated to the new signature with no assertion dropped. What DID change is
the fallback underneath: a row nobody has just spoken for now measures from the
sortie's arrival aerodrome rather than from whichever arrival the radio was
started on, so the "fallback nobody chose" this issue is about is now a stable,
named place. #160 carries that half.

**What was missing was the assertion**, which is the criterion this issue
states — *"asserted, because the failure is invisible while the two answers
agree"* — and a fix with no test is exactly the state that let this entry rot
without anybody noticing.
`tests/test_the_board_measures_from_his_seat.py` drives the metronome case: a
picture fetched with no field, a row whose seat is at the other aerodrome, and
a contact standing ON that aerodrome so the two answers cannot coincide. It
asserts the datum is his seat's field, that the NUMBER moved with the name
(zero miles, not twenty-two), and — separately — that the fallback would have
named a different field, so the test cannot pass by the two agreeing.

**The metronome still fetches with no `field=`, deliberately, and that is now
guarded.** It is nobody's picture and must stay so: passing a field there would
put one seat's answer under every row again. The hook callback in the same loop
DOES pass one and must, because that is one seat speaking (#166) — so the test
follows the variable the board is published from rather than sweeping the
function, which is what its first version got wrong.

The blind cases are asserted too: an unrecognised seat, no owner, a contact
with no position, and a seat at the same field all leave the picture's own
answer standing. A relabelled number would be worse than the fallback.
---

## [SEP-18] Nothing owns the runway, and nothing separates an aeroplane that is not on the approach — #170
labels: architecture

    "so, separation is only an apprach function? you saying the other phases of
     control have no separation engine? That seems like a flaw? What makes sure
     only one aircraft is on the runway at a time, or that two aircraft dont hit
     eachother en route?"

    "im pretty fearful that this separation thing is overly fit to ww2 ASR
     approaches"

**He is right, and the answer to both of his examples is "nothing".** Not
"something imperfect" — nothing. This is the honest statement of a scope that
has never been written down, filed so that it is a decision somebody made rather
than a gap nobody noticed.

**Separation is the arrival, and only the arrival.** `Phase` (`controller.py`)
has seven values — UNKNOWN, ENROUTE, HOLDING, CLEARED, MISSED, BANISHED, LANDED
— and every one of them is about the stack and the letdown. `Aircraft`'s own
comment says so, and the ground half of the same file states the boundary
outright:

    THESE MOVE `sortie_phase` AND NOTHING ELSE. There is no stack on the ramp,
    no levels and no sequence, so the separation engine has nothing to say here
    and must not pretend otherwise

That is correct as far as it goes — a holding stack is not what keeps a runway
clear — but nothing else was built to keep it clear either.

**Half one: nobody checks the runway.** `Controller.request_takeoff` asks
exactly one question before issuing the clearance, and it is `self._owns("tower")`
— whether the SEAT may speak (#65). It then reads the runway in use and says
"cleared for take-off". It does not ask whether anybody is on it.
`report_landed` issues a landing clearance the same way: field in sight, the
runway in use, the wind. Two aeroplanes at one aerodrome are serialised only by
the arrival stack, and an aeroplane enters that stack only through `check_in`
or `seed_from_radar` — both arrivals. **A departure and an arrival are never
sequenced against each other at all**, and two departures are not either.

There is a real reason it was not built, and it is already written down in
`report_down`'s docstring:

    an aerodrome row carries a position, an elevation and a landing heading,
    and no runway polygon

Confirmed against the data: a `fields` row is `name, x, z, elevation_ft,
runway, ends, atis_*, msa_sectors, mva_cells, magvar_deg, lat, lon,
grid_convergence_deg, note`. No length, no polygon, no thresholds as points. So
"is the strip occupied" cannot be answered geometrically today, which is why
nothing asks it.

**But the observable already exists on the ladder.** `phases.PHASES` defines
`landed` as "down and still on the runway" and `taxi_in` as "off the runway to
a stand", and Tower moves a man between them himself. One aeroplane in `landed`
at my field is a runway I must not clear anybody onto, and that check needs no
geometry, no radar and no new fact — only the discipline of asking.

**Half two: enroute, nobody is separating anybody, and that is by
construction.** There is no conflict detection, no proximity test and no
separation minimum anywhere in `src/marshall/atc/` outside the holding stack —
grep for `conflict`, `proximity`, `separation minim` returns only SQL `ON
CONFLICT` clauses and a formation's 0.3 nm formatting. And the invariant
forbids the other brain from filling the gap: *"An LLM never invents separation
between aircraft."* The deterministic half covers the arrival; the agent may
not; therefore between wheels-up and the arrival check-in the answer to "who is
separating these two aeroplanes" is **nobody, and no component is even
responsible for noticing.** It has never bitten because this route is 22.6 nm
(#130) and the sorties are single-ship, which is precisely the shape of thing
that bites first on a bigger map.

**The fear, adjudicated — half right, and the other half is worse.** The
engine's world model IS the single-beacon letdown: `controller.py`'s module
docstring opens *"The controller is BLIND: no telemetry, no radar, no connection
to DCS ... separation is by ASSIGNED ALTITUDE"*, and its four stack rules are
declared *"all forced by the letdown geometry"*. But it is NOT confined to the
1944 ASR — `BATUMI_ILS` carries the same hold, the same outer hold and the same
sequencing, and the identical machine runs it. So the accurate complaint is not
"it only works for the period approach". It is **one procedure's mechanism is
the only mechanism there is, and it is applied to procedures it was not derived
from** — the same shape as #53 (a radar capability on the profile whose whole
purpose is not having radar) and #113 (no procedure model at all).

**And the seam function's docstring says the opposite of what the code does**,
which is how a reader — or an answer written for the owner — gets this wrong.
`agent_atc.decide` still documents:

    directive/stack   the blind engine's next step and the holding stack,
                      and ONLY when it is engaged

`engaged` has gated nothing since the engine was hoisted out of that branch: the
parameter appears in the body only inside comments (`inspect.getsource(decide)`
confirms it), the caller still computes `engaged = SEP_ALWAYS or n_contacts >= 2
or len(ctl.aircraft) >= 2` and now uses it for the canned-reply path alone. The
one docstring anybody consults to find out what the deterministic half does
describes a gate that is gone.

**What it wants.** The runway half is small, buildable today and safety-critical;
the enroute half is a decision before it is code. Do not conflate them.

**Acceptance criteria.**

- A take-off clearance is refused, with a hold-short instruction, while another
  aeroplane at that field is `landed` — proven by a test with two aircraft at one
  aerodrome and no sim.
- A landing clearance is subject to the same check, and the man who is refused
  is told to go around or continue to expect it, not left with silence.
- Two aeroplanes at TWO fields do not interfere with each other — the check is
  per aerodrome, which is `tests/test_two_fields.py`'s whole subject.
- What separates two aeroplanes that are not in the arrival stack is decided and
  written into `docs/DESIGN.md`, even if the decision is "nothing, deliberately,
  until there is traffic to separate". A stated absence is checkable; this one
  was neither stated nor checkable.
- `decide`'s docstring describes its code: either `engaged` gates something
  again, or the parameter and the sentence both go.

Tests: `tests/test_controller.py` (two aircraft, one field, one runway);
`tests/test_two_fields.py` for the per-aerodrome half.
Code: `src/marshall/atc/controller.py` (`request_takeoff`, `report_landed`,
`Phase`, the ground-half comment), `src/marshall/atc/agent_atc.py` (`decide`).

**Status:** RUNWAY HALF FIXED, and this entry was stale — found by the same
grooming sweep. `Controller._on_the_runway` exists, `request_takeoff` refuses
over an occupied strip and says why, and
`tests/test_nobody_is_cleared_onto_an_occupied_runway.py` covers it including
the two-aerodrome case.

**The enroute half is still open and is still a decision to take first**, which
is what this issue said and remains true: nothing sequences two aircraft
against each other outside the arrival stack.
---

## [KB-7] Two columns on the board print the same word and mean different things — #171
labels: bug

    "in this case, wasnt the aircraft ENROUTE and with GA Center? Why would
     separation say UNKNOWN?"

He was reading one card with two rows on it:

    separation   UNKNOWN
    ladder       departure        <- `enroute` after #168

Both were correct, and the page gave him no way to know that. After #168 the
same card reads `separation UNKNOWN` beside `ladder enroute` — **the same word
present in one column and absent from the other, on one aeroplane, at the same
instant.**

The two columns answer different questions and the source says so at length
(`Aircraft`'s comment in `controller.py`): `separation` is `Aircraft.phase`,
where he sits in the ARRIVAL QUEUE, and `Phase.ENROUTE` has exactly one writer —
`check_in`, `controller.py:1653` — which is checking in with the arrival
controller, not being handed to a Center. `ladder` is `sortie_phase`, what he is
DOING across the whole sortie, and it is what `handoff.due` reads. The
distinction is right and must not be collapsed.

**But it is documented in the SOURCE, and this page exists so a pilot on the
knee does not have to read the source** (#155). `diag.py` renders
`kv('separation', ...)` and `kv('ladder', ...)` with no statement of what either
measures, and `UNKNOWN` — a real, correct engine state meaning "nothing has ever
put this man in the queue" — reads on a diagnostics page as "the system does not
know", which is exactly how it was read.

This is the consoling shape inverted: not a value that reassures, a value that
alarms. It cost a question from the owner and a page of answer, and it will cost
it again on every sortie until the aeroplane checks in with Approach.

**What it wants.** The label names the question the column answers — the arrival
queue, not "separation" in the abstract — and the value for "never admitted to
the queue" does not use the page's own word for ignorance. This is a rendering
change and nothing published needs to move.

**Acceptance criteria.**

- A reader who has never opened `controller.py` can say, from the page alone,
  why one aeroplane is `enroute` on one row and `UNKNOWN` on the other.
- The two columns cannot be read as two spellings of one fact, and a test in
  `tests/test_diag.py` asserts the page distinguishes them rather than asserting
  a string is present.
- No value on the card is rendered with a word the page also uses for "the
  snapshot does not contain this" — a missing fact still renders blank (#155
  criterion 2, which stays green).

Tests: `tests/test_diag.py`.
Code: `src/marshall/kneeboard/diag.py` (the `separation` / `ladder` rows).

**Status:** OPEN — found by the owner reading the board, 13 August; separate
from #155 so it cannot be closed by the parts of #155 that are already done.

---

## [ID-8] Whisper breaking his callsign is not him using the wrong one — #172
labels: bug, needs-flight-test

Caught on the board by the owner, 13 August, in a single transmission:

    heard    "Batumi Ground, Pan three twenty six, clear of runway one tree,
              request taxi to parking."
    who      panther26   radar   Panther26
    engine   "Panther two six, taxi to parking, your discretion."
    spoken   "Pan three, I DO NOT HAVE YOU ON THE BOARD, you are Panther two
              six, use that callsign. Panther two six, taxi to parking, your
              discretion."

**He is on the board.** The engine cleared him to taxi in the same breath, and
radar had named him before he keyed the microphone. The controller contradicted
himself inside one transmission, and the false half is the part the engine never
decided.

**Cause.** Polly said "Panther two six" and Whisper wrote "Pan three twenty
six". `_names_himself` looks for "panther" in the transcript, does not find it,
and `_plausible_callsign("Pan three")` is true — any English word in front of a
digit is a candidate. So a damaged spelling of his own callsign read as a man
calling himself something else.

**The identity ladder already forbids this**, and `misnamed` was the one place
not obeying it: *"RADAR, via the radio. No microphone in the chain at all. A
GARBLED CALLSIGN CANNOT TOUCH IT and neither can a confident wrong one."* A
correction sourced from the words is the microphone touching it.

**Why the obvious guard is wrong.** "Do not correct when radar named him" fails,
because radar names him in the case the correction EXISTS for too — Sockeye
calling himself Falcon 1-1 is still Sockeye on the scope, and telling him so is
the whole requirement: *"Sockeye screwed up by using Falcon1-1 on the radio and
needs to be corrected."*

The real question is whether the claim is a DAMAGED SPELLING of his own callsign
or a different callsign, and the two separate by a wide margin:

    Pan three    / Panther26   0.71        Falcon 1-1 / Sockeye     0.13
    Pan three 26 / Panther26   0.84        Hoover 1-1 / Sockeye     0.27
                                           Colt 2-1   / Panther26   0.27

**A designation is not a mangling, and it scores like one.** "Apex 1-2" against
the flight "Apex" is 0.80 — higher than the broken form — because it CONTAINS
the name rather than damaging it. That is a man naming a wingman, a different
aeroplane, and correcting him is correct. Whisper subtracts and substitutes; it
does not append a member number. So a claim holding the flight name whole is his
own words.

**Acceptance criteria.**

- The transmission above produces the engine's sentence and nothing else.
- Sockeye calling himself Falcon 1-1 is still corrected, and still told what to
  use instead.
- A member designation is still corrected.
- The threshold is not tuned to the example: mangled forms and different
  callsigns are separated by a gap, and a test asserts both sides of it.

Tests: `tests/test_identity.py::TestWhisperBreakingHisCallsignIsNotHimUsingTheWrongOne`.
Code: `src/marshall/atc/addressing.py` (`_mangled_form_of`, `misnamed`).

**Status:** FIXED 13 August, NEEDS A PILOT — card row S14. Closed and reopened twice in five minutes, and the second closure is the one worth recording. `552d4c7` carried a closing trailer, which this project's own rule forbids on a `needs-flight-test` issue. `1fb846a` was the commit APOLOGISING for that, and quoted the offending trailer in prose inside backticks to say what not to do — GitHub does not read markdown, saw the keyword, and shut the issue again thirty seconds after the reopen. There is now a `commit-msg` hook (`tools/commit_msg_check.py`) that refuses a closing keyword outside the trailer block, tested against the very message that did it. The fix and its tests stand; what has not happened is somebody hearing one sentence where there were two.

---

## [ARCH-33] The channel a talkdown goes out on is chosen once, from the bridge's procedure — #173
labels: architecture, bug, needs-flight-test

Found while closing #150's list of five, which is the argument for sweeping
rather than ticking items off: two more sites were inside `separation_context`
and are fixed, and this one is not, because it is not a one-line change.

`asr_monitor` computes its transmit channel ONCE, at thread start:

    _final = (_stations.role_at(_seats, "approach", _fld)
              if getattr(profile, "guidance", "") == "talkdown"
              else _stations.role_at(_seats, "tower", _fld))
    final_hz = (_final.freq_mhz * 1_000_000) if _final else freq_hz

`profile` there is the bridge's, and `_fld` is the loaded theatre's arrival
field. Both are then used inside a loop that runs PER AIRCRAFT — the mile
calls, the landing clearance relay, the goodbye, and every `channel_is_free`
check ahead of them.

So the question "which frequency does this man's final controller work on" is
answered once for everybody. Two aircraft on two procedures get one answer, and
the wrong one is a real frequency belonging to a real controller: a Viper on
the ILS at one field hears his mile calls on the other field's approach channel,
or hears nothing at all because the letdown the bridge was started on staffs no
ladder.

WHY IT WAS LEFT. The five sites #150 enumerated each pass a profile into a
function that already knows which aeroplane it is about. This one does not —
`final_hz` is a transmit channel, chosen before any aeroplane is in scope, and
moving it inside the loop means the pool, the free-channel check and the
goodbye all become per-aircraft. That is a change to the radio path rather than
to a lookup, and it wants its own test and its own flight.

**Acceptance criteria**
1. The final controller's frequency is resolved per aircraft, from his
   procedure and his field, at the moment something is said to him.
2. A test puts two aircraft on two procedures at two fields through one monitor
   and asserts the mile calls go out on two different channels.
3. `channel_is_free` is asked about the channel the transmission will actually
   use, not the one the thread started with.

Tests: beside `tests/test_two_procedures_one_bridge.py`.
Code: `src/marshall/atc/agent_atc.py` (`asr_monitor`).

**Status:** FIXED 14 August, NEEDS A PILOT — card row V8. `final_channel`
answers it per aeroplane, from two facts that are both his: whether HIS
procedure is a talkdown (Approach's channel) or not (Tower's), and which field
is HIS, off the frequency he checked in on. Resolved at the top of the
per-aircraft loop, so everything that iteration says to him — the mile calls,
the landing relay, the goodbye, and every free-channel check ahead of them —
goes out on one channel that is his.

**RE-VERIFIED 18 August.** `final_channel` lost its `profile` parameter to
#162 and resolves the aeroplane's procedure through `ctl.procedure_for` inside
instead. That is the same answer by a shorter route -- the caller can no longer
pass the wrong one, which is what this issue was about. The source-inspection
guard was updated to the new call shape rather than removed.

The thread-level constant is gone rather than shadowed. `_his_picture` used it
as the fallback for an aeroplane who has checked in nowhere and now uses the
channel THIS THREAD listens on, which is what that fallback actually means.

**The blind cases answer honestly.** A man on a frequency nobody works, or on a
procedure that staffs no ladder at all — the 1944 letdown — gets back the
channel he called on rather than a seat from somebody else's aerodrome. A guess
that names a real controller at the wrong airport is the #147 fault and is
worse than the frequency in front of him.

Criterion 3 is met by construction rather than separately: `channel_is_free` is
asked about `_final_hz`, which IS the channel the transmission then uses.

Tests: `tests/test_the_final_goes_out_on_his_channel.py`. The two-field case
is the one a single-aerodrome map cannot show, so it skips there and says so.
---

## [SEP-19] Leaving the terminal area is a cancelled approach, not a silent bounce — #174
labels: bug

    "If the approach doesn't require maneuvering in centers airspace but we
     accidentally cross into center because the pilot f d up, maybe his
     approach should be cancelled and he handed back to center. Trying to
     determine the direction of a ladder and assuming it always goes in one
     direction is brittle."

The second half of #139, split out on 14 August rather than folded in, because
it is controller BEHAVIOUR and #139 was geometry.

#139 fixed the reason this fired when it should not have: terminal areas were
eleven-mile circles around approaches that begin at twenty-two, so a man flying
the published procedure was genuinely outside the airspace working him and the
system was right to say so. Areas hold their own procedures now, so a departure
from one is a real event rather than an artefact.

**AND A REAL EVENT STILL HAS NO WORDS.** `leaving_my_airspace` returns the next
station and the ladder hands him over, silently, as though it were an ordinary
progression. It is not. A pilot who has strayed out of the terminal area while
being vectored for an approach has had something happen TO him, and a
frequency change with no explanation is the thing that has no procedural
meaning:

    what he gets      "contact Georgia Center one three niner decimal zero"
    what it means     his approach clearance is void and nobody said so

A cancelled approach has a meaning he can act on. It is also the honest
description of the state: `Controller` still holds him as CLEARED, the letdown
slot is still his, and the stack behind him is still sequenced against an
aeroplane that is no longer flying the procedure.

**Acceptance criteria**
1. An aircraft that leaves the terminal area while CLEARED for an approach has
   that clearance cancelled in the engine — the letdown slot is released and
   the stack resequences.
2. The engine decides it, so it is a `Decision` and `verify` can check it
   reached the air. Not prose the agent composes.
3. He is told, in one transmission: the approach is cancelled, and who has him
   now.
4. A test flies an aircraft out of the area mid-approach and asserts all three,
   and asserts the ordinary inbound case is untouched.

Tests: beside `tests/test_the_ladder_uses_the_maps_boundary.py`.
Code: `src/marshall/atc/agent_atc.py` (`leaving_my_airspace`),
`src/marshall/atc/controller.py`, `src/marshall/atc/phrasebook.py`.

**Status:** OPEN — split out of #139 on 14 August, not started. The geometry
that made it fire spuriously is fixed; the words it should say do not exist.

---

## [SEP-20] The controller asks for position reports the aeroplane cannot make — #175
labels: bug

    "The report beacon or report over holding fix has always been impossible in
     a ww2 aircraft. In modern we can instruct an aircraft to hold at a navaid
     or a fix on his flight plan. Telling a p51 to hold at the beacon or report
     established has always been impossible and a defect."

Named by the owner on 14 August while dropping WW2 homing, and it predates that
work by months. It is not a consequence of the removal; the removal is what
made it visible.

**HALF OF IT IS ALREADY RIGHT, which is what makes the other half easy to
miss.** `Controller._hold_phrase` asks `equipment.can_hold_at(kit, kind)` before
it offers a published hold, and falls through to a racetrack — a heading, a
turn and a clock — when the aeroplane cannot find the fix:

    "When ATC asks an airplane with no navaids to hold, it's going to need to
     help him... 'turn 180 heading fly 2 mins, then right turn to 360 and fly 2
     minutes'. Right now he just says to hold."

So the INSTRUCTION is gated on what he can fly. The REPORT is not.

**What is still wrong.** `report_beacon` is the letdown's entry point and asks
nothing about the aeroplane: a P-51 whose ADF does not work reports itself over
a beacon it cannot detect, and the engine believes it and sequences on it. The
same shape reaches the air the other way round — *"report established"*,
*"report over the beacon"* — instructions the pilot has no instrument to obey.

    a P-51D-30    the only WW2 airframe with a homing receiver at all, and it
                  works badly enough to be unusable
    everything    no ADF, no DME, nothing that says WHERE HE IS relative to a
    else in 1944  point on the ground

**And a radar controller should not be asking.** An ASR exists precisely so the
controller reads the range off a scope and TELLS him — *"eight miles from
touchdown"*. Asking a man to report a position the controller can already see is
the procedure inverted, and asking one he cannot determine is worse than
useless: he either guesses or stays silent, and both look like a pilot who is
not following instructions.

**WHAT A P-51 HOLD ACTUALLY IS**, from the owner, and it is the whole of it:

    "A controller can tell a p51 to hold at an altitude and fly an inbound
     outbound heading and timed legs, but that's it"

Which the engine already does. `_hold_phrase`'s fallback is a level, a turn
direction, an outbound heading, a leg time and an inbound heading — everything
he needs in one transmission and in the order he flies it. So this issue is NOT
about the hold. The hold is right and has been since #163.

It is about everything that asks him where he IS:

    the hold        gated on `equipment.can_hold_at`      correct
    the report      gated on nothing                      the defect

**AND AN INS IS NOT ENOUGH ON ITS OWN**, which `equipment.can_hold_at` claimed
and which is the second correction from the owner:

    "F16 needs a navaid or a fix on his plan for a hold."

An inertial platform tells him where HE is; it says nothing about where an
arbitrary point on the ground is. That comes from tuning the station or from
having FILED the fix. So the rule is two ways to say yes — he can receive it,
or it is on his plan — and `"ins" in kit` was a third that does not exist.

Corrected 14 August, with `on_his_plan` added. **No caller passes it**, so
today both `_hold_phrase` and `_report_phrase` answer "he cannot" for an F-16
at an NDB field, which is right for a fix he has not filed and wrong for one he
has. Threading the filed legs to those two call sites is the remaining half of
this issue.

**THE BETTER ANSWER IS TO ASK HIM**, and it came from the owner while this was
being written:

    "We could always make at a question the controller asks rather than a per
     airframe rule"

Which is what a real controller does — *"advise able direct BATUMI"* — and it is
better than a table for reasons this project has already learned once:

  * **A table is a guess about somebody else's aeroplane.** `equipment.receivers`
    maps an airframe name to a set of receivers, so it is wrong for a variant it
    has not heard of, wrong for a failed radio, wrong for a loadout that
    replaced a set, and wrong the day DCS changes a module. Every one of those
    is invisible: the aeroplane answers a question nobody asked it.
  * **The pilot is the authority and is on the frequency.** This is the identity
    ladder's shape exactly — RADAR over roster over not-admitted — where the
    best evidence wins and the fallback is honest. Ask, and believe the answer.
  * **It removes the flight-plan problem entirely.** "Able BATUMI?" needs no
    knowledge of what he filed, which is the half of this issue that has no
    caller today.

So the table becomes a PRIOR, not a verdict: it decides what the controller
offers first and what he assumes when nobody has answered, and a pilot's "unable"
overrides it for the rest of the sortie. That also gives the exchange somewhere
to live — an `unable` is a fact about a flight, like a clearance, and belongs on
the board beside one.

**Not built.** It changes what the engine ASKS as well as what it believes, so
it wants its own pass and probably its own issue once the shape is agreed. The
equipment gate below is worth having in the meantime: it stops the controller
saying something impossible, which is the defect, and asking is how he stops
having to guess at all.

**Acceptance criteria**
1. Nothing asks for a position report the aeroplane's equipment cannot
   produce — the same `equipment` question the hold already asks, on the report
   side.
2. A controller with radar reads the position out rather than requesting it.
3. `report_beacon` from an aeroplane that cannot find the beacon does not
   silently become a sequencing fact.
4. A modern aeroplane is untouched: hold at a navaid, hold at a fix on the
   filed plan, report established — all of which he has the instruments for.

Tests: beside `tests/test_equipment.py` and `tests/test_controller.py`.
Code: `src/marshall/atc/controller.py` (`report_beacon`, the approach
clearance), `src/marshall/atc/equipment.py`.

**Status:** PARTLY, 14 August. The report side now asks the same equipment
question the hold side has asked since #163, so a P-51 is asked for the field
in sight rather than for a beacon it cannot detect, and the two halves of one
exchange can no longer contradict each other. `equipment.can_hold_at` has had
its INS-alone rule corrected.

STILL OPEN: `on_his_plan` has no caller, so a modern aeroplane is refused a
hold at a fix he filed. And criterion 2 — a radar controller reading the
position out rather than requesting it — is untouched.
---

## [ARCH-34] Two knobs survive the per-flight profile, and one of them is the plate — #176
labels: architecture, needs-flight-test

The remainder of #2, lifted out of a closed issue so that it is readable. #2
was closed on 11 August reading "all four criteria met"; #162 found that the
mechanism had landed in 2 call sites out of 28 and finished the replacement on
18 August. Two of #2's four criteria are still genuinely unmet, and leaving
them inside a closed entry is the same mistake one level down.

### `MARSHALL_SORTIE` still exists

#2 criterion 3 asked for it to disappear: *"the flight's assigned plan chooses
its procedure."* #162 took the PROCEDURE out of `NEVADA_SORTIES` — a sortie
says where you depart and where you recover, and Approach issues the approach —
so the knob is smaller than it was. It still picks the arrival FIELD and the
filed plan for a Nevada start.

That is defensible in a way the approach never was: which of two filed sorties
is being flown is a fact about the mission. It is still a process-wide choice
made by an environment variable, and #111's answer (per-flight) is the right
one. Low priority, and named so it is not rediscovered.

### The plate is the map's, not the aeroplane's

#2 criterion 4 asked that *"the plate the agent is given is the plate for the
aircraft being spoken to."* What #162 built is a plate describing EVERY
published procedure, pushed once at startup. That is the radio being able to
work any approach, and it is not the same sentence:

    what #162 delivered   the controller is briefed on all four procedures,
                          so no aeroplane can be worked against the wrong one
    what #2 asked for     the controller is handed HIS procedure, and not the
                          other three

The first is correct and was the blocker. The second is a per-turn brief, which
is `docs/LAYERS.md`'s brief mechanism — *"what a controller is handed when it
becomes relevant, and not before"* — and is design intent with nothing built.
The measured cost of not having it: the Caucasus plate is ~10,200 characters
against ~5,300 for one procedure, so about half of what the model reads on
every push-to-talk is three approaches nobody on the frequency is flying.

**Acceptance criteria**
1. `MARSHALL_SORTIE` disappears, or its remaining job (arrival field, filed
   plan) is a property of a flight rather than of the process.
2. The plate part a controller is handed on a given turn describes the
   procedure that aeroplane is cleared for, and the others are not in it.
3. What was loaded is RECORDED, because once the prompt varies per call "what
   did the controller actually know when he said that" is a question only the
   recorder can answer. `LAYERS.md` names this as the real cost of the design.
4. An aeroplane with no clearance gets no procedure section rather than a
   default one — the same rule `_pro` already follows.

Tests: `tests/test_a_profile_per_flight.py`, `tests/test_two_procedures_one_bridge.py`.
Code: `src/marshall/atc/briefing.py` (`plates`, `_procedure_lines`),
`src/marshall/atc/agent_atc.py` (`load_and_push_plates`),
`src/marshall/core/theatre.py` (`NEVADA_SORTIES`).

**Status:** PARTLY — 18 August, same day. Criterion 2 is built; 1, 3 and 4 are
not.

**The plate split, and the tool.** The static `plate` part is now the theatre's
facts plus an OFFER — every key, kind, runway and field, 154 characters — and
the detail of the approach an aeroplane is CLEARED for rides on his own
transmission through `compose_message`. Caucasus: **10,601 characters down to
4,694**, and the ~1,700 that describes a procedure now reaches only the
controller working the aeroplane flying it.

    "Can we give the agent a tool to lookup procedures on demand as he needs
     them? Or does that cost too much latency if we know the agent is going to
     need a procedure?"

Both, split by whether we know in advance:

    HIS approach       injected. `procedure_for` resolves it off the board
                       BEFORE the model is called, so a tool would pay a round
                       trip for something in hand -- and a round trip roughly
                       doubles a call whose median is 3.3 s. The bigger reason
                       is that a tool call can FAIL or simply not happen, and
                       this is the procedure he is being talked down.
    every OTHER one    `look_up_approach`, universal like `look_up_frequency`.
                       Unpredictable, occasional, and landing on a
                       CONVERSATIONAL turn -- so the ~3.3 s is paid where
                       nobody is waiting on a heading.

`frequencies.py` had already argued this axis for the station table: *"the
field a man is sitting at is cheap and constant, and the rest of the map is
neither."* Substitute the approach he is flying and it is unchanged.

**TWO DEFECTS FELL OUT, both found by running it rather than by reading.**

1. **The approaches table accumulated across maps.** `load_and_push_plates`
   upserted each row and dropped none, so the live table held six rows across
   two continents and `look_up_approach` offered a Caucasus controller Nellis
   and Tonopah. That is exactly what `frequencies.py` records finding in
   `stations`, and the fix is the one `set_stations` already makes: the push
   REPLACES. `PUT /approaches` is the bulk route; the per-key one stays for
   tools and tests. Verified live — six rows in, four out.
2. **`profile_to_dict` is lossy and reasoning over the row cannot be made
   correct.** `vectored` is a computed property (`kind == "asr"`) and
   `asdict` keeps fields and drops properties, so the stored JSON has no
   `vectored` at all. Describing an approach from the dict called the
   surveillance approach unvectored AND, before that, called the 1944 letdown a
   headings talkdown — which is the one instruction that would break it, since
   a heading destroys the pilot's only reference. The row is rebuilt with
   `profile_from_dict` and `may_vector` is asked. That function's docstring
   already named the trap: *"ONE QUESTION, ONE ANSWER, and it was being asked
   three different ways ... which disagreed."* This was a fourth.

**And the image would not have built.** `services/Dockerfile` and the compose
`dockerfile:` key still carried `director/` paths after the rename. Nothing in
the suite builds the image, so check.py was green and the next deploy would
have failed. Found by rebuilding.

**Remaining:** criterion 1 (`MARSHALL_SORTIE`), 3 (recording what was loaded,
which `LAYERS.md` names as the real cost of a per-call prompt) and 4 as a
guarded assertion rather than a consequence.
Labels: needs-flight-test
---

## [ARCH-35] Approach never asks which approach, so a VFR arrival gets silence — #177
labels: bug, architecture, needs-flight-test

    "A field has a set of approaches available to it. When a pilot approaches
     the field - on a flight plan or not (just coming into the airspace vfr)
     the approach should ask which approach he would like and assign it to him,
     and support him in that approach"

#162 established the shape -- a field OFFERS a set, Approach ISSUES one to one
aeroplane -- and wired the ISSUING to a filed plan only. `assign_approach` had
exactly one caller and it read `assigned_plans.approach`, so a pilot who asked
on the radio was never given one.

**And the failure was silent, which is worse than the wrong answer it
replaced.** Everything followed correctly from `_pro(ac)` being None:

    stack_ft          empty, so `_free_slot` returned None
    request_approach  fell through without entering the stack
    the engine        said NOTHING AT ALL

Measured: radar-identified, asking plainly, phase stayed UNKNOWN and the outbox
was empty. The agent then answered with no directive behind it, improvising a
clearance the separation engine had no record of. Before #162 he was given the
radio's loaded arrival instead -- a real procedure, possibly at the wrong
field, which is the defect that issue deleted. **Removing a wrong answer
without supplying the right one turns a defect into a quieter defect.**

**Who it happens to.** Anyone not taking an IFR clearance from Delivery first:
a VFR join, an air start, a mid-sortie test, or the owner jumping in to try
something. `_cleared_plan_now` returns `{}` without a `cruise_ft` or a
`squawk`, so no clearance means no plan means no approach.

**What was built.**

    core/approach.match_spoken     a pilot's WORDS to a published procedure.
                                   Returns `(profile, candidates)` -- an
                                   ambiguous request is asked BACK with the
                                   candidates named, never resolved by list
                                   order, which is #165's rule
    Controller.offer_approaches    names what this FIELD publishes and asks
                                   which. One on offer is told, not asked
    Controller.request_approach    takes `wants`, resolves it, and ISSUES --
                                   `assign_approach` from the radio at last
    intents.dispatch               passes `intent.wants`, which the classifier
                                   already extracted verbatim ("an approach he
                                   wants, a runway") and which reached the
                                   board and nothing else

**The assignment is the ENGINE's and that is not bureaucracy.** An approach
clearance puts an aeroplane into a letdown that holds ONE, so which procedure
each aeroplane is on decides who contends with whom. It may never be a thing
the language half remembers having said.

**Acceptance criteria**
1. A radar-identified pilot with nothing filed who asks for the approach is
   ASKED which, with the field's set named — never met with silence.
2. Naming one issues it, and the stack, the levels and the letdown all work
   from it afterwards.
3. An ambiguous request names the candidates and assigns nothing.
4. A pilot already cleared is not asked again.
5. Three aircraft choosing different procedures still hold distinct levels
   with one in the letdown and no anomalies.
6. A procedure the map does not publish resolves to nothing, and the controller
   says so rather than offering the nearest thing.

Tests: `tests/test_approach_asks_which_one.py`. All six are green.
Code: `src/marshall/core/approach.py` (`match_spoken`),
`src/marshall/atc/controller.py` (`offer_approaches`, `published_approaches`,
`request_approach`), `src/marshall/atc/intents.py` (dispatch).

**Status:** BUILT 18 August, needs a pilot. The engine half is guarded by the
six criteria above; what no suite can score is whether ASKING sounds right on
the air — whether the offer is too long a transmission, whether "say which you
want" is the phrase, and whether a pilot who has already said what he wants in
his check-in gets asked anyway because the classifier put it in `wants` and
nothing else did.
Labels: needs-flight-test
---

**FIXED 28 AUGUST.** The classifier extracts `wants` from a CHECK_IN -- a
pilot's first call is one breath, position, altitude, ATIS and the approach he
wants -- and only the REQUEST_APPROACH branch read it. So the engine asked a
man to say the request it was holding:

    PILOT   ...information alpha, request the ILS runway 1 tree.
    ENGINE  report the field in sight. Say your request.

Hoisted exactly as the ATIS letter was for #180. `note_wants_approach` assigns
the procedure and does NOT sequence him -- a check-in is not the moment to be
entered in a stack. Guarded by `tests/test_a_check_in_can_name_an_approach.py`.
Still needs a pilot: card rows G18 and H32.

## [ARCH-40] Plan resolution is hand-weighted string scoring where a similarity query belongs — #183
labels: architecture

**Status:** BUILT 18 August, NEEDS A PILOT — card rows G3–G7. `plans.score`, `pick`, `ask_which`, `_squash`, `_spoken`, `_addressed_field` and `_words` are gone; `request_clearance(callsign, plan)` takes a label the controller has chosen, and `plans.named` is an exact lookup. **No similarity search was needed in the end** — the answer was not a better matcher but deleting the matcher, because the controller already had the labels, the words and the conversation and was passing a bare string to something that had none of them. `tools/plan_sweep.py` now scores the MODEL on the same phrasings and is baselined at 14/16; it moved to the `--live` group because it costs model calls, and `check.py` names it as unguarded rather than dropping it. **Only a pilot can score G5/G6** — whether the question a controller asks when two plans really are alike sounds like a controller rather than a menu.

    "that's weak ... this kind of string matching is lame"

**Not a request for a particular tool** — the complaint is the approach, and it
is correct. What is in the database today, for whoever picks this up: pgvector
is installed and carries exactly one column, `memories.embedding`, so flight
plans have no embedding at all; `pg_trgm` is installed and unused here.

`plans.score` is a bespoke point system in Python over rows fetched from
Postgres:

    named the label     100
    task word           10 each
    route word          6 each
    destination         1

Nobody can tune those numbers, nothing tests the ratios, and #182 was one
`in` operator inside it deciding a whole sortie. Logic where a query belongs —
the same split `docs/CONFIG.md` already states.

**Two dimensions, and conflating them is the trap** — whatever the mechanism
turns out to be.

    a NAME      an identifier. Wants trigram or phonetic similarity with an
                explicit ambiguity MARGIN. Embeddings place `Domino`,
                `Domingo` and `Dominoes` close together and would return a
                confident wrong sortie, which is the one failure this domain
                cannot absorb
    a TASK      "the CAS over Tsutsnvati", "the weather run out to Ingress".
                Genuinely semantic, today crude word overlap, and where an
                embedding earns its keep

**The margin is the part that must survive.** #165's rule is that an ambiguous
request is asked back rather than resolved by list order, and a similarity
score makes that expressible properly for the first time — two candidates
within a threshold of each other is ambiguity, stated as a number rather than
as an integer tie nobody chose.

**The open design question is who resolves it at all.** Matching what a pilot
said to a set of named plans is a language problem, and the language brain is
already handed `plans.pick` as a tool — it could instead be handed the
candidates and asked. What must stay the engine's is the ASSIGNMENT and the
ambiguity margin: which plan an aeroplane is on decides what it is cleared for,
and that may not be a thing the language half remembers having said. That is
the same line #177 drew for approaches.

**And it subsumes a live gap.** `_LABEL_OK` bans spaces and digits but not the
hazard it was written for: `SamovarOne` passes, and now that #182 matches on
letters, a pilot saying *"Samovar One"* resolves to it. The rule enforces its
letter, not its reason, and CamelCase is the loophole. A confusability check
belongs with the scoring, not in a second regex.

**Acceptance criteria**
1. Label matching survives spelling and spacing without a bespoke squash.
2. Two plans whose names are confusable are reported as ambiguous, not ranked.
3. A task described in the pilot's own words resolves without naming a plan.
4. The weights live somewhere they can be changed and tested.

---

**FLOWN 28 AUGUST AND FAILED, card row G4**, for a reason the row did not
anticipate. The pilot asked by what he was DOING and named the destination:

    PILOT  Kobuleti Clearance, Sockeye, request clearance for the transit
           and recovery to Batumi.
    ATC    Sockeye, no plan filed under that name. I have BatumiTest and
           NellisTest on file. Which do you want.

The card's premise was that nothing here is ambiguous, "one ending at Batumi,
one three thousand miles away". By TASK they are identical -- `flight_plans`
holds "Transit and Recovery" for BatumiTest and "Transit and recovery" for
NellisTest -- so asking which is defensible on the task alone. **The
destination he named was never used**, and it is the thing that separates them.
The pilot's own note: *"I cannot specify what I'm doing, I have to use the
name."*

## [ARCH-41] Everybody joins the arrival queue on their first transmission — #184
labels: bug, needs-flight-test

**Status:** FIXED 18 August, NEEDS A PILOT — card row Q15. Guarded by `tests/test_a_departure_is_not_in_the_arrival_queue.py`, including a check that walks `controller.py` and fails if any reader starts telling `UNKNOWN` from `ENROUTE` — the day that happens this stops being a display fault. **A pilot is needed for criterion 1** because what is being tested is whether a man on the ramp, reading his own board, is told something true about himself; the engine can only prove the value changed.

    "sitting on the ground here, getting ready to taxi, I look at the board,
     the arrival cue says, check in with the arrival cue"

    "the board says, arrival queue is checked in with the arrival controller.
     His place in the let down and nothing else. My issue with this is that I
     obviously have not checked in with the arrival controller yet. What is
     this status actually?"

He was right, and the board was faithfully reporting what the engine held.
`phase` read `ENROUTE` on **every board snapshot of the sortie** — all eighteen,
from his first word on a cold ramp to thirteen miles out:

    15:12:51   phase ENROUTE   sortie_phase clearance      (cold, on the ramp)
    15:16:34   phase ENROUTE   sortie_phase taxi
    15:20:01   phase ENROUTE   sortie_phase holding_short
    15:20:14   phase ENROUTE   sortie_phase departure

It never changed, because there was nothing left for it to change to.

**One line in `check_in`, guarded against the wrong end of the sortie.** It
refused to demote a `CLEARED` or a `LANDED` aeroplane — both learned from #51,
where a check-in on a new frequency knocked a man out of the letdown he was
already in and he held at 44 nm and declared an emergency — and said nothing
about a man who has not started his engine. The FIRST transmission of any
sortie is a check-in, so every aeroplane joined the arrival queue before it
moved.

**`UNKNOWN` means "never admitted" and no departure could ever be shown it.**
#171 published exactly those words in the legend so the page could tell a real
answer from a missing one; this line overwrote the answer on his first word.

**IT IS NOT A SEPARATION BUG, and that is asserted rather than hoped.** All
three readers of the field pair `UNKNOWN` with `ENROUTE` — stack admission in
`report_beacon` and `_try_clear`, the channel choice in `_channel` — so nobody
was sequenced differently and no aeroplane held a slot it should not have. A
test walks the source and fails if a reader ever starts telling them apart,
because on that day this stops being a display fault.

**My first write-up of this was wrong** and is corrected in the flight record.
It read *"a field with no value rendering its caption instead of nothing"*,
the same shape as #155. A missing value would have rendered `UNKNOWN` →
*"never admitted"*, which is exactly right for a man on the ramp and is the
case #171 built. He got the other value, which meant something had genuinely
admitted him.

**Fixed** with #178's latch: `has_been_airborne`, set only on positive radar
(#164's scar — `not on_ground` is not `airborne`) and carried across a restart
in `flights`. An aeroplane radar has not yet placed stays `UNKNOWN`, which is
honest and costs nothing.

**Acceptance criteria**
1. A cold aeroplane's first transmission does not put it in the arrival queue,
   and the board reads *"never admitted"* the whole way down the ground ladder.
2. A genuine arrival checking in still becomes `ENROUTE`.
3. A cleared aeroplane is still not demoted by a check-in on a new frequency.
4. No aeroplane's place in the letdown changes.

---

## [ARCH-44] The mission key drifts, so a sortie's own rows become unreachable — #187
labels: bug, architecture, needs-flight-test

**Status:** FIXED 18 August, NEEDS A PILOT — card row Q16. Verified against the live sim: the resolver now returns `...@1786509383`, the key the board's existing rows were already under, instead of the drifted `...@1786509377` — so rows orphaned before today are reachable again. **A pilot is needed because the fix is about what survives a PAUSE**, and pausing a running server is the one thing no unit test can do.

    "We agreed weeks ago that a flight plan does not need to have a
     pilot/aircraft on it. That any pilot can be assigned any plan - many to
     many. Why would the agent respond like this?"

It was never about the plan. The plan was found; the **aeroplane** was in
another bucket.

Every flight, contact and assigned plan is scoped to a `mission` key, which was
DERIVED on each process start:

    started = int(wall_clock_now - timer.getTime())

`timer.getTime()` is DCS **model time**. It stops while the mission is paused
and wall clock does not, so the difference is not a constant — it grows by
every pause the server takes. Measured 18 August on a mission up 6.7 days:

    rows on the board were written under   ...@1786509383
    a process starting now computed        ...@1786509377

Six seconds apart, so `board.find(mission=...)` matched nothing. **The rows
were not deleted, they were unreachable** — which is worse, because the table
reads as empty rather than as wrong. A pilot on the radio was refused his
clearance with *"nobody is listed under that callsign"* while his own row sat
in `flights` under a key nobody would compute again.

**A tolerance would not have fixed it.** Rounding the derived value only widens
the window in which two processes agree and calls that a fix — the same trade
`_squash` made in #182 and which was deleted for it. The key is now WRITTEN
DOWN the first time a mission is seen and read back afterwards.

**A genuine reload is still a different world**, detected by the one signal
that cannot be faked: model time RESTARTS. Elapsed is monotonic within a
mission, so going backwards means the sim loaded something new. A pause moves
the derived start; it can never move elapsed backwards. That asymmetry is the
whole design, and it is why the reload check needs no fuzzy matching.

Migration 036 adopts every `mission` value already in `flights`, so this does
not orphan the rows it exists to stop orphaning.

**Its test talks to Postgres and SKIPS LOUDLY without it**, because a stubbed
pool here would reproduce the very failure being fixed — see #120.

**Acceptance criteria**
1. Pausing the server mid-sortie does not change which rows the board can see.
2. A radio restart mid-sortie finds the flights it wrote before the restart.
3. Loading a different mission does start a fresh bucket.
4. The previous instance's rows still exist and are still reachable by key.

---

## [ARCH-45] The theatre file declared one mission, and every controller read it out — #188
labels: bug, architecture, needs-flight-test

**Status:** BUILT 18 August, NEEDS A PILOT — card row G15. **The data went first and that was not the fix.** Removing the Caucasus route left the mechanism, and Nevada turned out to declare its own route in PYTHON (`NEVADA_ROUTE`) — the same fault one file further out.

    "If a route like that exists in code and of being handed to an llm,
     something is fundamentally wrong. Fix the core not the system"

So the route-shaped hole is gone, not just what was in it: `Theatre.waypoints`, `Theatre.legs`, `sortie_route`, `_sortie_wp`, `_sortie_legs`, `sortie_alt_ft`, `NEVADA_ROUTE`, the `R.SORTIE*` aliases, the fix-push that folded route points into the published table, the `steerpoint N` aliases, and `Sortie.route`/`alt_ft` from the model — so a theatre file that declares a route now RAISES instead of being quietly obeyed. `briefing._sortie()` is a stub returning nothing. **Only a pilot can score criterion 1**: what has to be true is that asked about his own route he hears HIS route, and a confidently wrong answer sounds exactly like a right one.

    "The theatre file, whatever that is, should handle hundreds of different
     flights all with different flight plans? There is some plan stuck in
     there? Get rid of it"

`config/theatres/caucasus.toml` carried a `[sortie]` block — the 1944 strike —
as **the** mission this map flies:

    route  = ["BATUMI", "FEET WET", "INGRESS", "TSUTSNVATI", "EGRESS", "BATUMI"]
    alt_ft = [2000, 500, 3000, 9000, 11000]

`briefing._sortie()` read it and put it in front of every controller on every
transmission as *"Today's filed route"*, numbered by steerpoint with leg
headings. On 18 August an F-16 on a filed `BatumiTest` clearance asked what his
second steerpoint was:

    21:38:00  PILOT  can you tell me what my second waypoint is
    21:38:06  ATC    steerpoint two is feet wet, heading two seven zero for one
                     two miles off steerpoint one
    21:38:34  NOTE   that's a serious issue ... The waypoint two for my flight
                     plan is bar. I'm ending this mission

Read straight off the block — waypoint 2 was FEET WET and leg 1→2 was 270 at
12 nm. His actual route, `FOO BAR SPAM INITIAL`, was in the same message two
lines away on his own flight strip.

**THE AUTHORITY ARGUMENT IS THE ONE THAT MATTERS, and it is stronger than the
provenance argument.** He was cleared to BatumiTest — issued, read back,
stamped in `assigned_plans` at 21:30:46. Even if the theatre's route had been a
current, correctly-filed plan, quoting it to a man cleared on another is wrong.
A cleared aeroplane's route has exactly one source.

**Third escape for the same four names.** `catalogue.py` records the previous
two — published as navaids, then scraped out of `route.py` into
`theatre.fixes` — and both fixes addressed the FIXES. Nobody touched the
route, so it kept broadcasting.

**What was removed.** `[sortie].route`, `alt_ft` and the four turning points
from the theatre file; the dead `R.FEET_WET`, `R.INGRESS`, `R.HOMEBOUND` and
`R.TARGET_AREA` aliases. `REHEARSAL` stays — an air-start point is a fact about
the map, not about a mission — and so do the defended areas. Nevada already
declared no `[sortie]`, so the no-route path existed and was already correct.
`tools/draw.py` no longer assumes a target exists.

**Zero live code references to the name remain.** What is left in `src/` is
incident history in comments, which this repository keeps on purpose.

**Still over-fitted, and filed here rather than fixed:** `tools/plan_sweep.py`
and `tools/plan_assign_check.py` bake the 1944 route into their fixtures, and
34 references remain across `tests/`. A harness that only ever resolves the
retired route is one that passes while a pilot is told the wrong waypoint.

**Acceptance criteria**
1. Asked about his own route, a cleared aeroplane is answered from
   `assigned_plans` and nothing else.
2. No controller volunteers a route the pilot was not cleared on.
3. A map with no `[sortie]` briefs correctly (Nevada already does).
4. `[sortie]` is renamed to what it now holds, or its remaining contents move.

---

## [ARCH-46] The model is briefed on the aeroplane as it was before the turn decided anything — #190
labels: bug, architecture, needs-flight-test

**Status:** FIXED 18 August, NEEDS A PILOT — card row Q18. Guarded by `tests/test_the_picture_is_frozen_after_the_engine.py`, which asserts the ORDER (bind → decide → settle → freeze → describe) and fails by line number if the read moves back above `settle`. **Only a pilot can score criterion 1**: both the right and the wrong behaviour are a controller answering confidently on the correct frequency.

    21:36:11  PILOT   Kobuleti Departure, sockeye with you        (on 123.3)
    21:36:13  ENGINE  Sockeye, Kobuleti Departure, radar contact
    21:36:14  handoff Kobuleti Departure keeps him -- departure, 3 nm, outbound
    21:36:18  ATC     you should be with Tower, one three three decimal zero —
                      you're still with me

He was on the right frequency, sent there four seconds earlier. The seat
answering was Departure and the engine agreed **in the same turn**. What
disagreed was the FLIGHT STRIP in the message, which still said Tower owned
him — so the controller reconciled a contradiction it had been handed, the only
way it could.

**The row was read at the top of the turn** and carried three hundred lines
down into `compose_message`, across `next_controller` (which settles the
handoff and records it) and `settle` (which advances the engine):

    _bound = flight_bind(...)           <- picture taken
    nxt    = next_controller(...)       <- handoff decided and written
    settle(...)                         <- engine advanced
    compose_message(..., _flight, ...)  <- briefed from the OLD picture

**IT HAD BITTEN BEFORE, ON A DIFFERENT FIELD**, and `phase_now`'s docstring
records it: *"This lived inside `settle`, which runs AFTER
`separation_context`, so the half of the turn that MUTATES the engine ran
before anything had worked out what the aeroplane was doing."* That fix hoisted
**one field** to the top of the turn. The shape was never addressed, so it came
back on `owner`.

**So the turn has a boundary now:** everything before the freeze DECIDES,
everything after DESCRIBES. `flight_now(fid)` re-reads the row once, after the
deciding is done, immediately before the message is built.

**A read and not a write.** `flight_bind` would return the same row and also
upsert, so a picture-taking call would quietly change what it was
photographing — the boundary crossed by the line drawing it.

**Re-read rather than patched.** Mending a stale copy from whatever the engine
happens to hold is the trade that put the board and `flights` out of step in
the first place (#120).

**The guard is an ORDER, not a line of code.** `flight_now` may move, be
renamed or be inlined; what may not change is that the row the message is built
from is obtained after the engine stops changing things. Moving the read back
above `settle` fails two assertions by line number.

**Acceptance criteria**
1. A controller never tells a pilot to go back to a frequency the same turn
   handed him away from.
2. The strip names the controller who has him NOW.
3. The store being unreachable degrades to the stale row, never to a lost
   transmission.

---

## [ARCH-47] The board and the strip carry the facts and do not say what they are — #191
labels: bug, needs-flight-test

**Status:** FIXED 18 August, NEEDS A PILOT — card row G16. **Only a pilot can score it**: what is being tested is whether a man reading his own board can tell a real clearance from an absent one, which is a question about legibility and not about a value.

Two findings from the 18 August evening sortie with one cause: the clearance
was recorded correctly and every surface that showed it was unreadable.

**THE BOARD.** *"cleared for"* renders `assigned_plans.approach` — the
**approach**, not the plan. He had no approach yet, so it was correctly blank
and read as a missing clearance:

    21:31:11  NOTE  I finally got the read back correct ... but cleared for,
                    is still showing blank on my board
    21:33:30  NOTE  I wonder if Kobuleti Clearance actually put me on the
                    clearance ... I'm guessing he just remembers that from the
                    conversation history, not actually putting it in the
                    database

The guess was reasonable and wrong — `assigned_plans` held BatumiTest, origin
Kobuleti, squawk 7457, acknowledged. **A board that cannot show a clearance
that exists is indistinguishable from one reporting a clearance that does
not**, and it cost him a taxi back to Clearance to find out which he had.

The plan appeared on the board nowhere at all. The one join that existed went
through a spoken plan NAME in the identity registry, so it was blank for anyone
who had not happened to say one — while the row sat in `flights`.

**THE STRIP.** The model's copy read:

    STRIP: sockeye, on BatumiTest, via FOO-BAR-SPAM-INITIAL, cruise 10,000 ft

    "my guess is that the llm doesnt know what \"on BatumiTest\" means..
     Should it say \"FlightPlan: BatumiTest, Route: FOO>BAR>...\""

Neither half says what it IS, in a line of comma-separated phrases where a
route reads as more phrases. A controller holding exactly this was asked which
plan the pilot was on and sent him back to Clearance (#4), and another asked
for his second steerpoint answered off the theatre's route (#188) rather than
the four names in its own message. **Neither was a knowledge gap.**

**Fixed.** The board reads the authoritative `flights` row and shows
`flight plan` + `route` + whether it was read back; *"cleared for"* is renamed
`cleared approach`, which is the question it was always answering. The strip
names its fields — `FLIGHT PLAN:`, `ROUTE:`, `CRUISE:` — and the route is
`>`-separated because it is ordered.

**Acceptance criteria**
1. The board shows which flight plan an aeroplane is cleared on.
2. A blank approach field cannot be read as a missing clearance.
3. Asked which plan he is on, any controller answers from the strip.

---

## [ARCH-50] "Go ahead" is said to calls that have already been made — #195
labels: bug, needs-flight-test

**Status:** FIXED 18 August, NEEDS A PILOT — card row S16. The rule is in `rules.md` and names the phrase, what it is for, and the incident. **Only a pilot can score it**: "go ahead" is perfectly good phraseology in the wrong place, so nothing in a transcript looks wrong — you have to be the man who just spoke.

    "I just gave Kobuleti Tower a read back, and he said, go ahead afterwards.
     Don't know what that's all about."

Heard three times now, from three different causes, and it is the same sentence
to a pilot every time. The third, 18 August, on a garbled read-back the engine
had already judged:

    21:30:12  ENGINE  Sockeye, negative — say again one two three decimal
                      three, seven four five seven.
    21:30:15  ATC     Sockeye, Kobuleti Clearance, go ahead. Say again one two
                      three decimal three, squawk seven four five seven.

The recorder shows `REPAIRED say_again`, so the model's own words were
*"Sockeye, Kobuleti Clearance, go ahead."* and the engine's correction was
**appended** by `decision.repair`. The controller line was in front of it and it
opened by inviting a call that had just been made.

**We had never told it.** Unlike #179, "go ahead" appears in no prompt — the
model reaches for it as stock phraseology when it has nothing else to open
with. So there was no rule to break and none to find; the fault is an absence.

**The rule now names the phrase and what it is for.** *"Go ahead" means I am
listening, transmit* — it belongs only to a call with nothing in it. Said to a
read-back, a report or a request, it tells a man who has just spoken to speak,
and he cannot tell whether he was heard. **If a controller line is present, the
answer is that line** — there is nothing left to invite.

**Not a filter.** #179 settled that: the fix for a model saying the wrong thing
is the sentence we did or did not write, and this one was missing.

**Acceptance criteria**
1. A read-back is answered, never invited.
2. "Say again" is used when a transmission genuinely was not received, and
   names what was missed.
3. "Go ahead" still answers a bare call — "Kobuleti Clearance, Sockeye".

---

**FLOWN 28 AUGUST AND FAILED.** Twice on the approach, to calls with content
in them:

    20:12:24  PILOT  Batumi Approach, Sockeye is established, ILS one three.
    20:12:37  ATC    Sockeye, Batumi Approach, go ahead.
    20:14:03  PILOT  established on the ILS one three. What do you show as my
                     final destination for my flight plan?
    20:14:14  ATC    Sockeye, Batumi Approach, go ahead.

Both are reports, one carries a question, and "go ahead" was the answer to
each. Both turns also had a decided vector that was never voiced (#79) -- so
"go ahead" was what went out INSTEAD of a turn and a descent.

## [SEP-24] The engine threw on every arrival turn, and the failure was a log line — #197
labels: bug, architecture, needs-flight-test

**Status:** FIXED 19 August, NEEDS A PILOT — card row H29. Guarded by `tests/test_no_procedure_is_not_a_beacon.py`, which drives real intents through `dispatch` for an aeroplane the engine cannot place and asserts the whole turn survives. **Only a pilot can score criteria 1 and 3**: an engine that is not running sounds exactly like one that is — the model answers pleasantly either way, which is how this survived a full sortie.

    "why oh why would it be treated as a vector approach? first, I was assigned
     the ILS ... there hsould be no default appaorch"

There is no default — `Controller()` has carried `profile=None` since #162 —
and that is exactly the case three separate places mishandled. **One absence,
three faults, one sortie flown with the deterministic half switched off.**

**1. The engine was not running.** `asr.guide(fix, None)` reads
`profile.final_crs_true`. `separation_context` catches everything, because a
classifier failure must cost a label and never a transmission — so the
exception was total and silent:

    !! controller classify failed: 'NoneType' object has no attribute
       'final_crs_true'                                    ... eleven times

No directive, no engine line, no approach issued, and a model answering alone
with nothing to voice. **The engine was not wrong about the arrival; it was not
running.**

**2. Unknown was inverted into a beacon.**

    beacon_flown = not may_vector(procedure_for(callsign))

`may_vector` answers *"may this controller give headings?"*, for which "I do not
know what he is flying" is correctly **no**. Inverting it turns an absence into
a positive claim. Ten position reports refused with *"you have not reached the
fix, continue inbound"* — to a departure, outbound, at nineteen miles. *"I'm
not inbound at all."*

**3. And "inbound" was assumed.** That instruction is only sound for an
arrival; it is now only given to one.

**4. `reachable` refused his position reports too**, on the reasoning that
*"there is no station to pass"* — which we cannot know without a procedure. A
controller with radar can always answer where a man is; it is the one thing he
never needs a procedure for.

**AND THE APPROACH CLEARANCE WAS NARRATED, WHICH IS WHY HE HAD NO PROCEDURE.**

    01:51:34  PILOT  Sakai would request the ILS-13 approach.
    01:51:48  ATC    Sockeye, cleared ILS runway one three approach ...

No engine line between them. `unbacked_claims` — written for exactly this in
#185 — watched *"cleared to"* and *"readback correct"* and not a single
approach phrase. It does now.

**The engine path itself is sound and always was**: the classifier returns
`REQUEST_APPROACH` with `wants='ILS 13'`, `dispatch` reaches
`request_approach`, and it issues. It never ran because fault 1 threw three
lines earlier.

**AND THE LOG COULD NOT SHOW IT.** #186 moved 22 exception paths onto module
loggers and nothing anywhere calls `basicConfig`, so all of them fell to
Python's `lastResort` handler — no timestamp, no level, no logger name, in a
file that also carries the whole sortie transcript. A diagnostic nobody can
pick out of the noise is the failure #186 was written about, relocated rather
than fixed. Configured now, with `MARSHALL_LOG_LEVEL`.

**Acceptance criteria**
1. An aeroplane with no assigned approach produces no exception on any turn.
2. His position reports are answered from radar, not refused.
3. Asking for an approach by name gets one ISSUED — `assigned_plans.approach`
   is written and the strip shows it.
4. A spoken approach clearance with no record reaches the recorder as
   `unbacked`.
5. Nothing tells an outbound aeroplane to continue inbound.

---

## [ARCH-52] We can say his name and cannot hear it — #198
labels: bug, needs-flight-test

**Status:** FIXED 19 August, NEEDS A PILOT — card row S17. Offline test asserts every configured name reaches the prompt; the 0/7 -> 6/7 measurement is in the commit rather than the suite, because scoring the recogniser costs a model and eight seconds of synthesis per voice.

    "Sakai would request the ILS-13 approach."
    "Batumi Ground, Sakai, is clear of active runway 07"

All night, in every transcript. `Sockeye` is a word the recogniser has no
reason to expect and every reason to hear as a commoner name, and priming is
the lever — `whisper_vocabulary` already carries stations, fixes and plan
labels, and its own comment has said so since it was written.

**It seeded the wrong table.** `route.SQUADRON_CALLSIGNS` is
`("Pony", "Hammer", "Spit", "Whistler")` — the flight names the mission builder
gives AI aircraft. The man flying was Sockeye, and `config/callsigns.toml` had
held his respelling all along, because the TTS half needed it to **say** his
name. The STT half needed the same word to **hear** it and was reading a
different table.

**One fact, two tables**, and the wrong one decides what the transcript says —
which is then what the callsign-correction guard fires on (#196's other half)
and what a controller reads back at him.

**Measured**, by rendering the name in seven Polly voices and transcribing each
back through the real recogniser:

    unprimed          0/7 correct   ("Sakai" x6, "Suck I" x1)
    live vocabulary   6/7 correct

**And the seventh is Joey**, which gives "Socke" where the other six give
"Sockeye" exactly. That is independent corroboration of the one thing I could
not test directly — *"only batumi tower says sakai"* — since Batumi Tower is
the Joey seat. The pronunciation question stays open, but it is no longer my
guess against yours: two different measurements now single out the same voice.

**`default_prompt` still names nobody, deliberately.** Priming for another
sortie's callsigns is worse than not priming, which is why the fix feeds the
LIVE vocabulary and not the fallback.

**Acceptance criteria**
1. His callsign appears correctly in the transcript.
2. The callsign-correction guard does not fire on his own name.
3. A name with a respelling always has priming — asserted, not hoped.

---

## [ARCH-53] Nobody knew where he was on his own flight plan — #199
labels: architecture, needs-flight-test

**Status:** BUILT 19 August, NEEDS A PILOT — card row H30. Twelve tests over HIS route with the real coordinates, including the two algorithms that failed on it. **Only a pilot can score criterion 1**, because a confident wrong fix name sounds exactly like a right one — which is how #188 survived a whole sortie.

**28 AUGUST: THE CONTROLLER HAD THE NAMES AND NOT THE PLACES.** Airborne, asked
for vectors to his next steerpoint, Departure said "I don't have your
steerpoints" -- and was telling the truth three times over:

  * `assign` copies a plan onto a flight and `assigned_plans` has no `legs`
    column, so the coordinates were left behind in `flight_plans`. The legs
    come back with the row now, read through `filed`.
  * `route_fixes` dropped `alt_ft`, so "do you know the altitude of my
    steerpoints" got no.
  * `flight_plan_help` rode inside `clearance_tools`, handed out only to seats
    with the CLEARANCE capability -- Clearance and Delivery. Every seat that
    works an aeroplane in the air had no way to read its plan at all. Reading a
    plan is universal now; issuing one is still Delivery's.

    FOO (5,000 ft, 064M 16.8 nm from Kobuleti) -> BAR (10,000 ft, 028M 18.5 nm)

Needs a pilot: ask any seat for vectors to a steerpoint.

    "obviously she doesn't know where those waypoints are and where I'm at on
     my flight plan"

    "I would expect that since my flight plan steerpoints have coordinates, the
     system can figure out where I am relative to my steer point and which leg
     im on"

The engine measured one thing — range from the FIELD. The pilot navigates by
his steerpoints. The two were never joined, so a controller asked for his next
fix answered off the theatre file (#188), and asked again after landing named
the first fix of the plan he had just flown.

Every leg carries `lat`/`lon` and radar carries his position. `progress.where`
is the join.

**THE ROUTE IS WHY THIS TOOK THREE ALGORITHMS.** `FOO -> BAR -> SPAM -> INITIAL
-> BATUMI` turns through nearly 180 degrees at BAR. Every simple rule works on
a straight line, and this plan is not one:

    each fix tested independently,   standing exactly ON FOO read as "past
    abeam by projection              INITIAL, next fix BATUMI" — the
                                     perpendicular through a fix four legs
                                     later, pointing elsewhere, was already
                                     behind him. An abeam test is a statement
                                     about ONE leg

    sequential walk, abeam by        the BAR-SPAM midpoint read as "past FOO,
    "closer to the next than         next fix BAR". "Closer to the next" only
     to this one"                    becomes true past the leg's MIDPOINT — it
                                     lagged half a leg, every leg

Both were proxies. The question is which leg he is nearest, and only distance
to the **segment** survives a route that turns.

**And the case neither had:** on the ramp at Kobuleti, seventeen miles from the
first fix and near no leg at all, nearest-leg picked whichever was least far
and answered *"past BAR, next fix SPAM"* before the engine was running. Off the
route, only the nearest FIX means anything — `OFF_ROUTE_NM` draws that line,
and it is not an accuracy tolerance.

**Hybrid, as chosen.** `REACHED_NM` is the explainable normal case — *"you are
inside two miles of BAR"* — and the segment geometry is the backstop that stops
him welding to one leg when he flies a fix wide.

**Stateless, and that is a requirement.** A pure function of (legs, position),
so a restart, a dropped radar frame or a reconnect cannot lose his place.

**It answers; it does not decide.** Nothing issues a clearance, moves a phase
or contradicts a pilot. It reaches the controller on the strip:

    ON ROUTE: past BAR, next fix SPAM, 19 miles on 265

**Acceptance criteria**
1. Asked for his next steerpoint, he is told his own — by name and range.
2. On the ramp the answer is the first fix, not a leg he has not flown.
3. After landing the route reads complete, not "next fix FOO".
4. A fix flown wide still counts as passed.

---

## [SEP-25] Three mechanisms decide a handoff, and I fixed the wrong one first — #200
labels: bug, needs-flight-test

**Status:** FIXED 19 August, NEEDS A PILOT — card rows Q17 and H31. **The first fix was still three mechanisms**: it taught the events branch the phase so it could tell a departure from a roll-out from a go-around. *"I don't see why the handoff to departure is any different on a go around. Still use the 5nm airspace rule right?"* — right, so the go-around is a table row now, `Rule("tower", "approach", "going_around_beyond", DEPARTURE_NM)`, at the same range as a departure and with a different destination. The events branch answers only what the table CANNOT: airborne with no radar picture, where there is no range to ask about and a blind controller would otherwise never let anybody go. `test_the_ladder_has_a_direction` had asserted the two-mile handoff as "the case the branch exists for"; it is inverted, which completes that file's own thesis that airborne is not an event.

`next_controller` asks in order: the sim's **events**, the **rule table**, then
the **airspace volumes**. #189 gave the rule table the last word over the
volumes — and the events branch runs before both.

**"Getting airborne ends Tower's business."** That is the events branch's own
docstring, written for a go-around, and it is true of an aeroplane that has
just flown an approach and false of every other way to be airborne with Tower:

    departure    handed on at ROTATION, twice in two sorties —
                 "he sent me to departure before I even hit the end of the
                  runway". The table says DEPARTURE_NM and never got a word
    roll-out     fifteen seconds after touchdown, still reading as airborne to
                 radar, Tower offered him to Approach —
                 "I have touched down for about 15 seconds, and then he sent
                  me to approach or departure"
    go-around    genuinely this branch's, and the only one of the three it was
                 written for

All three are *"airborne, with Tower"*. Only the **phase** tells them apart,
and the branch could not see it.

**AND THE AIRSPACE TOOK A MAN OFF AN APPROACH.** `under_our_vectors` guards
that, and it is only true while a vector is actually in flight — so an
aeroplane established on the ILS and flying it himself fell through, and was
offered to Georgia Center mid-approach. Being **cleared** for an approach is
the durable version of the same fact; geography does not get a vote on a
procedure it cannot see.

**Both are the same sentence as #189**, one mechanism over: a decision made
somewhere upstream must not be silently overruled by whoever is asked next.

**Acceptance criteria**
1. Tower keeps a departure to about five miles.
2. Nothing hands a rolling-out aeroplane to Approach.
3. A go-around still goes back to Approach.
4. An aeroplane cleared for an approach is never offered to Center.

---
