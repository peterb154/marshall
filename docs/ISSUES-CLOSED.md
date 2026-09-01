# Closed issues — the record

    Type: WORK RECORD

**Every issue here is CLOSED on GitHub and attested.** They were in
`docs/ISSUES.md` until 19 August, where they made up 129 of 198 entries and
7,231 of 12,241 lines — 59% of the file somebody opens to find out what is
still wrong.

    "Let's shore up the backlog and issues.md and the flight test card -
     consolidating and simplifying."

**NOTHING IS SUMMARISED OR TRIMMED.** Each entry is exactly as it was written,
because the value of this file is the account: what the symptom was, what the
cause turned out to be, and which of the two the first fix addressed. That is
the thing this project keeps needing and cannot reconstruct later — most of a
month's work has started by reading one of these and recognising the shape.

`tools/issue_sync.py` and `tools/file_issues.py` read this file as well as
`ISSUES.md`, so a closed issue is still compared against GitHub and still
cannot drift. The split is about which file a person opens, not about which
issues exist.

**Nothing is added here by hand.** An issue moves when it closes.

---

## [FP-1] Flight plans: many on file, assigned per flight — #1
labels: feature, needs-flight-test

**Status:** CLOSED — built, script-checked, never said to a human.
Card section **G**.

**What is in.** `flight_plans` are filed templates with routes, cruise levels,
tasks and a spoken label; `assigned_plans` is the per-flight copy, one row per
flight by unique index. A spoken request resolves against task, route places,
label and destination-last (`plans.pick`), and where two plans fit the controller
ASKS. The clearance comes back finished in CRAFT — clearance limit, route,
altitude, departure frequency, squawk — and the brief says to voice it whole.
Route fixes resolve through the `fixes` table rather than being stored on the
plan, so a plan and a chart cannot disagree about where INGRESS is, and a route
naming a fix nobody holds is refused at delivery instead of discovered on the
third leg. How much navigation help a pilot gets is keyed on the aircraft type
radar already reports.

**What the scripts cover.** `tools/plan_sweep.py` (eleven phrasings: match, ask,
and nothing-on-file, offline or `--live`), `tools/plan_assign_check.py`
(criteria 1, 2, 5, 7 against a running director on a scratch mission), and
`tools/atc_dryrun.py --script clearance` for the seam that matters — whether the
agent voices the tool's numbers or improvises. The dry run is what found the
departure frequency going missing, twice.

**What is left for a human:** whether the clearance is COPYABLE at speaking
pace, which no script can judge. G1–G5.

**Found on the way**, both fixed here: a plan's spoken name is a callsign by
shape, so "request clearance, Samovar Three" bound the pilot's radio to his own
flight plan — see [#13]; and "clearance for the CAS" produced an aeroplane
called Clearance 4, since "for" is a homophone of "four", in the one exchange
where every pilot says those exact words.

**28 July: a clearance that never happened**, three faults in one exchange and
the plan lookup innocent of all of them. The pilot called himself Falcon 1-1;
nothing called Falcon existed, and the identity ladder refused it — correctly,
because a callsign is a pilot's own handle or a flight somebody created and
never a name chosen in the air ([#42]). Then:

  * `request_clearance` missed on the board and said "No flight on the board
    for Falcon 1-1", a true statement about the PILOT, which the controller
    relayed as "no flight plan on file for that callsign" — false, and about
    the FILE. He spent two minutes hunting a plan that was on file the whole
    time. The miss now names the closed set (`clearance.not_on_the_board`), so
    a controller who cannot find him can say who he *does* have.
  * "we'd like to open the flight plan" resolved to nothing, because `open` was
    not in `_NOISE` and one surviving word made the request read as *naming*
    somewhere nobody had filed for. What he wants DONE with a plan is never
    WHICH plan.
  * and the third was ours from the start: two of the six templates carried a
    callsign, and `pick` handed a plan over as "the one on file for you" when
    it matched. That is the pre-assignment this issue says must not exist. The
    column is now dropped at the query (`_TEMPLATE_COLS`) and the branch is
    gone — a plan on file belongs to nobody until a clearance copies it into
    `assigned_plans` against a flight_id.

Guarded by `tests/test_board_miss.py` and two new classes in
`tests/test_plans.py`. Note the first fault was a wrong EXPLANATION of correct
behaviour, which is the kind that costs a sortie and leaves no red test.

Today there is exactly one flight plan and it is mission-wide — `flight_plans`
carries `active`, and every insert does `UPDATE flight_plans SET active=false`
first. The bridge loads that one plan at startup to build the plate. Two flights
cannot be going to two different places, and a plan cannot be reused.

A plan should be a **filed template with no callsign**. When a flight asks for
clearance and references one, it is **copied** to an active instance bound to
that flight. Two flights can then fly the same plan at once, and the same plan
can be flown night after night. The copy also means a controller amending one
flight's routing never edits the filed original — the same rule as everywhere
else here: the template is what was *filed*, the instance is what was *agreed*.

**Acceptance criteria**
1. Two flights hold different assigned plans at the same time, and each ATC
   response reflects that flight's own destination and route.
2. The same template can be assigned to two flights concurrently; amending one
   instance leaves the other and the template untouched.
3. A template survives a mission reload and can be assigned again with no edit.
4. A plan can be referenced **by callsign** (it is filed against nobody, so the
   controller offers what is on file) or **by name** when there is more than one.
5. Assigning stamps `flights.flight_plan`, `destination`, `route`, `cruise_ft`
   and `clearance_ack`.
6. Once assigned, the controller can answer "where am I going" and "what am I
   doing" without the pilot repeating himself.
7. Nothing regresses when a flight has NO plan — that is still the normal case.

**Out of scope**, deliberately, and tracked as [ARCH-1]: two flights recovering
to *different fields*. The bridge holds one `ApproachProfile` and the geometry,
the controller and the plate all read it. The schema here will carry
`destination` and `approach` from the start so that work needs no migration.

Code: `src/marshall/atc/approaches.py`, `director/migrations/`, `flights` table
(columns already exist and nothing writes them).

---

## [ARCH-1] One approach profile per flight, not per bridge — #2
labels: architecture

**Status:** CLOSED 11 August, and this entry is the correction rather than a
reopening — GitHub owns open/closed state because closing is a human act, and
what a human closed does not get reopened by a tool or by me. What it read was
*"FIXED 11 August. All four criteria met"*, and #162 measured what that was
worth: the mechanism had
landed in 2 call sites out of 28, beside the singleton it was meant to replace.
Every criterion below is about a flight GETTING its own profile, and none of
them asks what fraction of the code reads it — so a parallel implementation
satisfied all four.

#162 finished the replacement on 18 August: `Theatre.approach` is deleted, the
loop holds no `profile`, and `_pro` answers None for an aeroplane nobody has
cleared. Two of the four criteria are now genuinely met, and the other two are
still open and are named rather than assumed:

    1  met      two aircraft, two fields, two approaches, no shared numbers
    2  met      `asr_sweep.py --profile`, Batumi byte-identical
    3  NOT MET  `MARSHALL_SORTIE` still exists (`core/theatre.py`). It no
                longer picks a PROCEDURE -- #162 took that out of
                `NEVADA_SORTIES` -- but it still picks the arrival field and
                the filed plan, so the knob is smaller and present
    4  NOT MET  the plate is pushed ONCE at startup and describes every
                published procedure. That is the radio being able to work any
                approach; it is not "the plate for the aircraft being spoken
                to", which is a per-turn brief and is `LAYERS.md`'s brief
                mechanism, still design intent

**The criterion that was missing is now written down**, and it is #162's real
contribution to this issue: *the old path is gone*. That one is met.

**The two unmet criteria are re-homed rather than left inside a closed issue**,
which is the whole failure mode this entry is a monument to: a remainder parked
under a green tick is a remainder nobody reads. See [ARCH-34] / #176.

Criterion 2 landed with the rest: `asr_sweep.py --profile nellis-ils`. Batumi's
figures are byte-identical (1296/1296, 0 flips, 576 turns), and pointing it at an
approach it had never swept found a real defect in the same minute — see #116.
A baseline is now per procedure, because judging an ILS in the Spring Mountains
against a surveillance approach on the Georgian coast measures nothing.

**THREE things were per-bridge, not one**, and fixing only the first would have
looked right and behaved worse:

* **The numbers.** `Aircraft.profile` and `Controller._pro(ac)` — the beacon he
  homes, his stack levels, his runway, his minima, his missed approach, the name
  of the controller working him. The facility's station table deliberately stays
  on the Controller: `station_for` answers "who works ground at Kobuleti", which
  is a property of the theatre and cannot differ per flight.
* **The stack.** Two aerodromes are two stacks. A hold over Nellis and one over
  Tonopah are 120 nm apart and share no airspace, so an aeroplane waiting for one
  was reserving a level in the other. Scoped by the procedure's beacon.
* **The letdown.** One string meant an aircraft on the Nellis ILS blocked the
  approach at Tonopah for a reason nobody could explain on the radio.

**The bug the test found**, and it is the one worth remembering: `_try_clear()`
with no reference checked the BRIDGE's letdown while `_next_up` picked an
aeroplane out of a different stack and cleared him — so both arrivals at Nellis
were cleared for the same approach at once. "Is the letdown free" cannot be
asked without saying which.

**Migration 025** exposes `assigned_plans.approach` on `flight_state`. The column
has existed since the plans table and the view did not carry it, so the bridge —
which joins the view and nothing else — could not find out which procedure an
aeroplane was recovering on. Exactly the gap migration 023 closed for the squawk,
one column along, eleven days later.

Originally: **THIS IS THE WALL IN FRONT OF MULTIPLE AIRPORTS.** Everything else on this list makes one
field work better; nothing else lets there be a second one. It has sat
unprioritised since the beginning while three days went on ghosts

`_run_srs` holds a single `profile`, and `asr.guide`, `controller.py`, the
metronome and the plate all read it. Two aircraft recovering to different fields
need a profile each. This is the wall in front of [FP-1] point 8 and in front of
the Kobuleti test [TEST-1].

**What Nevada added, 11 August.** Filed again as [ARCH-13]/#111 before anybody
noticed this had described it since the beginning — which is its own evidence
that the backlog needs reading, not just adding to. That entry is retired into
this one.

    "a flight that departs Nellis, works the range, and returns to Nellis needs
     that profile and its arrival state during the same sortie. It cannot be
     selected concurrently with the Tonopah recovery."
                                               -- CODEX_NTTR_AUDIT.md

`Theatre.nevada()` selects ONE approach and `load_and_push_plate` pushes ONE
`plate` prompt at startup. A Nevada bridge loaded the Tonopah ILS, so a pilot
going home to Nellis would have been worked against a profile for a field 124
miles away. `MARSHALL_SORTIE` now picks which — **a knob, not a fix**, and it is
stated as one.

It is the two-aerodrome lesson one level up: **a procedure is only unique within
a flight**, and the wrong answer is always plausible because it is a real
approach to a real runway.

**Acceptance criteria**
1. Two aircraft, two fields, two approaches flown concurrently without either
   controller using the other's numbers.
2. `asr_sweep.py` runs against a named profile and still reports the same
   figures for Batumi.
3. `MARSHALL_SORTIE` disappears — the flight's assigned plan chooses its
   procedure.
4. The plate the agent is given is the plate for the aircraft being spoken to.

---

## [ENG-1] Engineering channel: getting a human on the line — #4
labels: needs-flight-test

**Status:** CLOSED — commit `cffad1a`

"Get engineering on the line" from any frequency, answered instantly without a
model. Replaces a hand-launched transmit-only process that was not there when
the pilot changed channels.

**Acceptance criteria**
1. Summoning on 124 and on 118 both answer, in engineering's voice, within a
   second or two.
2. With nobody at the bench the answer is *"not at the bench right now, keep
   talking, every word is recorded"* — **never silence**.
3. After summoning, ordinary speech is logged and acknowledged, and **Approach
   does not answer it**.
4. "Thanks engineering" releases; the next call reaches ATC normally.
5. Every note lands in `build/debug-notes.md` with a timestamp and a callsign.

Tests: A1, A2, A3, A4
Code: `agent_atc.engineering_ack`, `_ENG_CALL`, `_ENG_DONE`

---

## [RAD-1] Do not talk over the pilot; leave room to read back — #5
labels: needs-flight-test

**Status:** CLOSED — commits `8464b4b`, `c0c5d29`

The radio lock only ever stopped the bridge's own threads colliding with each
other; it knew nothing about the humans. Three guards now: while a pilot is
transmitting, while his answer is being composed, and for seven seconds after a
clearance.

**Acceptance criteria**
1. Talking for ~15 seconds on final does not get a mile call on top of you.
2. The held call is **made afterwards, not lost**.
3. After a clearance there is a gap long enough to read it back.
4. **Two pilots:** a mile call for one never lands where the other's answer
   should have been.

Tests: B4, B5, F2, F3
Code: `agent_atc.channel_is_free`, `SRSClient.someone_is_talking`

**Least evidence of anything on this list.** Synthetic pilots take turns
politely, so F2/F3 have never been properly contested.

---

## [RAD-2] Wait for the check-in before working him — #6
labels: needs-flight-test

**Status:** CLOSED — commit `c0c5d29`

> "when we got a handoff from center to approach, by the time I switched over,
> approach was already half done with the first instruction"

The metronome worked anyone the controller knew, and it knew him from *Center's*
frequency.

**Acceptance criteria**
1. After a handoff, the new controller says **nothing** until you check in.
2. On check-in he begins normally, from the start of the instruction.
3. A man who never checks in is never vectored.

Tests: B1a (new)
Code: `agent_atc._heard_on`, `may_be_vectored(freq_hz=)`

---

## [RAD-3] One controller, one frequency, for the whole approach — #7
labels: needs-flight-test

**Status:** CLOSED — commit `296b33d`

The talkdown used to transmit on Tower's frequency while the model answered on
Approach's — one controller arriving as two voices on two channels.

**Acceptance criteria**
1. Vectors, mile calls and landing clearance all arrive on 124.
2. One voice throughout.
3. No instruction to change frequency before the missed approach point.

Tests: B1, B2, B6
Code: `agent_atc` `final_hz`, `route.hands_to_tower_nm`

---

## [APP-1] The talkdown keeps him to the missed approach point — #8
labels: needs-flight-test

**Status:** CLOSED — commit `faac653`

On an ILS the aeroplane has its own aid and Tower takes him at the intercept. On
a talkdown the controller IS the approach aid, so he keeps him and relays the
landing clearance.

**Acceptance criteria**
1. No handoff to Tower inside the final.
2. Landing clearance with the wind arrives from the controller flying the
   approach.
3. A profile with `guidance: "intercept"` still hands over at the intercept.

Tests: B6
Code: `route.hands_to_tower_nm`

---

## [APP-2] The approach ends when the wheels are down — #9
labels: needs-flight-test

**Status:** CLOSED — commit `faac653`

> "I'm sitting on the ground at Batumi, in Batumi Tower thinks I'm on the missed
> approach"

**Acceptance criteria**
1. Landed and stopped, the controller stops working you within a sweep or two.
2. It does **not** fire early — at 200 ft a mile and a half out you are still
   being talked down.

Tests: B7
Code: `asr.on_the_ground`

---

## [APP-4] Going around: no vector back towards the field — #11
labels: needs-flight-test

**Status:** CLOSED — commit `36ea1a4`

> "pny flight is outbound after the missed and the atc is saying that he is left
> of course (thinking he is inbound)"

Open for three sessions and four failed attempts. Fixed by giving the caller the
one fact geometry cannot recover: whether he is flying the procedure.

**Acceptance criteria**
1. Going around and climbing out on the published missed, **every** instruction
   is about the missed approach — climb, the published heading, re-sequencing.
2. No turn back towards the field while below the missed approach altitude.
3. Never told he is "left of course" while flying it.
4. At the missed approach altitude he is re-sequenced normally.
5. `asr_sweep.py` clean and `--sloppy` both unchanged from baseline.

Tests: B8 (new)
Code: `asr.guide(on_missed=)`, `agent_atc.flying_the_missed`

---

## [ID-1] Telling a flight's aircraft apart after they split — #12
labels: needs-flight-test

**Status:** CLOSED — commits `50cebe7`, `ed18e97`

> "last night shooter was being called pony1"

`Pony 1` is a *formation*. Naming yourself more precisely now wins immediately,
and the controller asks each aircraft to check in by name at the break-up.

**Acceptance criteria**
1. At break-up each aircraft is named, in order, and asked to check in.
2. A lead who checked in as the flight is addressed by his own callsign from the
   moment he uses it — **one call, not a majority**.
3. Two pilots are never addressed by the same name.
4. A flight name is never bound to a radar track that has a wingman on it.
5. A single ship whose callsign looks like a flight ("Hoover 1") is still
   radar-identifiable and still gets talked down.

Tests: C4, C4a, C4b, F5
Code: `agent_atc.transmitter_callsign`, `controller._identify_phrase`,
`src/marshall/atc/identify.py`

---

## [ID-2] Noise must not become an aeroplane — #13
labels: needs-flight-test

**Status:** CLOSED — commits `631173a`, `50cebe7`

**Needs re-triage before anybody works it (10 Aug).** Its closure condition —
"no new ghost from a live sortie" — does not match its `needs-synthetic-check`
label, and the identity work since (#40, #41, #48, #52) moved the safety
boundary this was written against. Do not start from the text below. Decide
first whether the present corpus IS the contract (then close it with an
attestation) or restate it as a bounded admission-rule regression.

A garbled call put an aircraft called `Waypoint 3` in the holding stack; another
produced `21-2`; "I have two aircraft" became `Have 2`.

**Acceptance criteria**
1. A sentence with a number but no callsign never creates an aircraft.
2. "Sentry" and "ingress" transcribe correctly (were "Century", "in-grass").
3. "Pony one **too**" is understood as Pony 1-2.
4. Your first transmission is primed — a callsign on the roster, or passed via
   `MARSHALL_CALLSIGNS`, is known before you speak.

Tests: C4c, D1, D2
Code: `stt.domain_prompt`, `callsign._NOT_A_NAME`, `agent_atc._plausible_callsign`

---

## [ID-3] Answer the man who actually spoke — #14
labels: needs-flight-test

**Status:** CLOSED — commit `c0c5d29`

The bridge had the identity right on every transmission and never told the
model, which inferred the caller from the transcript and the radar — and
answered a wingman's check-in as his leader.

**Acceptance criteria**
1. Every reply names the pilot who transmitted.
2. Holds when the transcript mangles the callsign.
3. Holds with two pilots alternating.

Tests: F1
Code: `agent_atc` `THIS TRANSMISSION IS FROM`

---

## [SEQ-1] One in the letdown, and nobody vectored until cleared — #15
labels: needs-flight-test

**Status:** CLOSED — commit `296b33d`

The guard asked the blind engine how many aircraft existed; a restart emptied
it, and both aircraft were vectored at once — different headings, different
altitudes, one frequency.

**Acceptance criteria**
1. Two contacts on the scope and nobody cleared: **nobody** is vectored.
2. The man holding hears the hold and nothing else.
3. It survives a bridge restart mid-sortie.
4. A single ship is worked normally.

Tests: D4, F4
Code: `agent_atc.may_be_vectored`

**Safety-relevant.** Two aircraft on one intercept is the thing this whole
design exists to prevent.

---

## [HO-1] Handoffs follow airspace, not range — #16
labels: needs-flight-test

**Status:** CLOSED — commit `8a4ce0f`

> "georgia center handed us off the approach oftly early... should have kept us
> with him until we left his airspace"

**Acceptance criteria**
1. Departing, Center keeps you until you leave his airspace.
2. Returning, Center hands you to Approach normally.
3. A talkdown is **never** handed over mid-approach, whatever the airspace says.
4. An unreachable director means no opinion, not a wrong one.

Tests: C5, C6
Code: `agent_atc.leaving_my_airspace`, `migrations/008`

**Least certain of the shipped fixes.** It fires on live geometry that could not
be reproduced solo.

---

## [OVL-1] Sentry computes, and admits what she cannot — #17
labels: needs-flight-test

**Status:** CLOSED — commits `0b08330`, `296b33d`

She gave three different ranges to the field inside a minute, all invented, with
the tool in her list. Steerpoints were not in her table at all.

**Acceptance criteria**
1. Range and bearing to any steerpoint, by name or number, computed not guessed.
2. Asked twice, the same answer.
3. No fix for it → says so, never a made-up mile count.
4. Asked for a target, she places one and tasks you onto it.
5. Reports what the sim actually created, and refuses to send anyone if it does
   not match.

Tests: C7, C8, C9
Code: `agent_atc.push_fixes`, `feed/tracks.py`, `spawn_ground`

---

## [OPS-1] One bridge at a time — #18
labels: needs-flight-test

**Status:** CLOSED (ground) — commit `296b33d`

The most-repeated cause of "duplicate controllers". Killing the launcher does not
kill the python child.

**Acceptance criteria**
1. A second bridge refuses to start and names the PID holding the lock.
2. A crashed bridge (`kill -9`) leaves no stale lock.

Tests: D5
Code: `agent_atc.claim_the_frequency`

---

## [BUG-1] Outbound vector at ~14 nm while inbound — #19
labels: bug

**Status:** FIXED 13 August — commit `b09595f`. `in_position`'s angle test was `min(TURN_IN_NM, along * tan(30°))`, which is 2.0 nm at every range past three and a half miles: a fixed distance wearing an angle's clothes, under a docstring describing what it should have done. A real 17° cone now. Both realistic sweeps improved (clean 576→555 turns with establishment unchanged; sloppy 35→20 flips, 1535→944 turns); the deaf sweep went 94→100 and the trade is recorded in the baseline rather than hidden.

**The remaining bug is the `in_position` room test, not the vectoring.** Inbound
on the course, a heading that would fix it in thirty seconds, and instead he is
sent outbound to reposition:

```
        1.5 nm off   2.5 nm off   3.5 nm off
11 nm      in          AWAY         AWAY
14 nm      in          AWAY         AWAY
16 nm      in          in           AWAY
18 nm      in          in           in
```

At 14 nm and 2.5 nm off that is a ten degree offset. Real ATC gives a heading.

The frame fix (grid convergence, see [#35]) killed the 144-degree REVERSAL on
Hoover's trace and took the deaf sweep from 23 reversals to 17 — but it did not
touch this, and saying it had was my error.

Inbound, more than 2 nm off course, and the engine turns him away. Four attempts
across two sessions, all of which regressed the sweep and none of which ever
reproduced it.

**Why it hid for so long.** The sweep flies a pilot who OBEYS. `--sloppy` lags,
overshoots and drifts, and still complies. This bug needs the geometry to keep
getting WORSE while the controller keeps talking, and an obedient aeroplane
never allows that — it turns, the error shrinks, and the engine looks fine.

Hoover produced it by accident: outbound at 320, five to eight miles northwest,
reading a bug report to engineering and not turning.

    "when I'm in this range between the inner, basically near the runway, going
     the opposite direction. This is where he gets very, very confused."

His radar trace, replayed offline and deterministic:

        4.9 nm  r305  hdg 318   ->  turn to 126   xtk -0.09
        6.1 nm  r310  hdg 320   ->  turn to 142   xtk -0.64
        6.7 nm  r312  hdg 322   ->  turn to 149   xtk -0.93
        7.7 nm  r315  hdg 324   ->  turn to 160   xtk -1.47
        8.5 nm  r316  hdg 324   ->  turn to 165   xtk -1.77
       10.0 nm  r318  hdg 324   ->  turn to 309   xtk -2.42     <-- 144 degrees

**Two faults, one trace.** The engine hands an aircraft flying AWAY from the
field the intercept heading it would give one flying towards it — 126 to a man
on 318 is an instant one-eighty at five miles, not a vector — and then, past
about two miles of cross-track, it gives up and sends him outbound instead, in a
single 144-degree reversal with no downwind and no base leg.

**Scale.** A pilot who does not turn produces a >90-degree reversal in **237 of
1,080** starts. The same starts with an obedient pilot produce **none**.

**Now guarded.** `asr_sweep.py --deaf` flies a pilot who never turns, from three
miles out as well (the ordinary grid has never STARTED inside eight), with its
own baseline — arrivals are not a measure of a man who is not flying the
approach, so it scores the arguing instead. In `tools/check.py`. The trace above
is `TestTheReversalHooverFlew`, which holds the current behaviour and carries the
assertion it should pass, marked expected-failure so the day it is fixed the
suite says so.

**Acceptance criteria**
1. Inbound and off course at 20–11 nm, corrections converge — no turn away.
2. `asr_sweep.py` and `--sloppy` no worse than baseline
   (1293/1296 · 1 flip · 582 turns; sloppy 1296/1296 · 26 flips).
3. ~~A repro exists as a test before any fix is written.~~ **Done.**
4. An aircraft flying AWAY from the field is sequenced — downwind, base, final —
   rather than handed the inbound intercept heading as though it could turn onto
   the course from where it is.
5. No instruction reverses by more than 90 degrees between consecutive calls
   while the pilot's own heading is unchanged. Turning him around is a decision
   to re-sequence, and that is a pattern, not one word.
6. `--deaf` no worse than its baseline (23 flips, 576 turns).

---

## [BUG-2] Three approaches orbit instead of arriving — #20
labels: bug

**Status:** CLOSED 13 August — verified mechanically, not flown. #20's exact geometry reproduced: 8 and 12 nm on radial 305±60°, the reciprocal of Batumi's 125 final course, across all twelve headings — 144 starts, 144 arrivals, no orbits. Both criteria bettered: 1296/1296 on the clean sweep, 0 dithering against a ceiling of 1, 555 turns against ~582. It had been fixed by other work and nobody went back to look.

Starts 8–12 nm behind the field on the departure side. The bearing to the entry
gate rotates the same way the aircraft turns, so it chases it round — a stable
orbit that, sampled once a revolution, looks like an aeroplane frozen in the sky.

**Acceptance criteria**
1. 1296/1296 arrive on the clean sweep.
2. Dithering stays at 1 and turns at ~582 — the two attempts that "fixed" this
   took dithering to 2,696 and 4,159.

---

## [BUG-3] The model invents fields, frequencies and procedures — #21
labels: bug

**Status:** CLOSED

Observed on a go-around rehearsal:

    "climb one zero thousand, proceed KOBULETI, contact Kobuleti Departure
     one two four, hold, expect re-sequence"

None of that exists in the plan. Same class as the invented ranges fixed in
[OVL-1]: a model asked a question answers it whether or not it knows.

**Acceptance criteria**
1. The controller never names a field, frequency or fix that is not in the
   profile or the fix table.
2. When it has nothing, it says so.
3. A rehearsal transcript can be checked against the profile automatically.

---

## [HOOK-1] Hooks keep their promises — #25
labels: bug

**Status:** CLOSED

"I will call you in five miles" has to actually happen, and a conditional hook
must stay conditional.

**Acceptance criteria**
1. Every promise on the air is either kept or explicitly withdrawn.
2. A hook whose condition has passed does not fire anyway.

---

## [CTX-1] The controller is handed state; he remembers only the conversation — #43
labels: feature, needs-flight-test

**Status:** CLOSED — `bd2db1b`..`d6d5b11`. Window
24, situation stripped from history. Unflown. Card section F.

Measured on two real sessions in `session_messages`: the average user message
sent to Sonnet is **2,522 characters, of which 74 are the pilot's actual words**.
The other 2,448 are the injected block — RADAR, TRANSMITTER, STRIP, YOU ARE,
VISUAL APPROACHES — re-sent on every call and then kept in history afterwards.

Two costs, and the second is worse than the money.

`SlidingWindowConversationManager(window_size=16)` counts MESSAGES, not turns,
and a call averages 2.56 messages (2 for a plain exchange, 4 with one tool call,
6 with two). So the window holds **6.3 transmissions** — and fewer exactly when
the controller is busy, because that is when it reaches for `identify`, `vector`
and `set_hook`. The memory shortens under load.

And the history carries STALE SITUATION. An evicted-but-not-yet-evicted message
holds the radar picture as it stood five minutes ago, so the model can see
`RADAR: no contacts` sitting beside a current scope with four aircraft on it.
That is not merely wasteful, it is contradictory state in the context, and it is
being paid for at roughly 10k tokens a call to be there.

**The rule this issue exists to establish:** everything that is STATE is
injected fresh on every call and never stored; only DIALOGUE is remembered.

    SITUATION      radar, strip, phase, who you are    re-derived, never stored
    PENDING        the commitments not yet discharged  re-derived, never stored
    CONVERSATION   the pilot's words and the reply     stored, and only this

The same pattern the bridge already uses for RADAR and CONTROLLER, extended one
step. Stripping the injected block from history turns 16 messages into about 16
real exchanges instead of 6.3, at a few percent of the tokens — longer memory,
cheaper, and no stale picture to reason from.

THE SCENARIO THIS HAS TO PASS, from the pilot who found it:

    "approach, sockeye, i have a question"
    "sockeye, approach, standby"
    "andre, approach, turn left 120 descend 2000"
    "descend 2000 turn 120"                              (andre)
    "sockeye, approach, go ahead with questions"

Five transmissions, interleaved between two pilots, with a promise made in the
second that must still be true in the fifth. At today's 2.56 messages per call
that is ~13 messages, inside 16 — until one of those calls uses a tool, and the
vectoring call almost certainly does. It is sitting on the edge of failing and
nothing would report it if it did.

**Acceptance criteria**
1. A historical turn in the context contains the pilot's words and the
   controller's reply, and no radar picture. A stale scope cannot appear.
2. SITUATION and PENDING are assembled fresh per call and are never written to
   `session_messages`.
3. Average input tokens per transmission are recorded before and after, in the
   commit, and go down.
4. The five-transmission scenario above completes with the promise kept, with a
   tool call in the middle of it, and is covered by a script rather than a
   memory of having tried it once.
5. The window is sized against that scenario deliberately, and the reasoning is
   written down where the number is set.
6. Postgres still holds the full transcript. Trimming what is SENT must not
   trim what is replayable.
7. `docs/WIRING.md` is updated in the same commit -- the life-of-a-transmission
   section, the two-brain section and the vocabulary all describe the message
   that is sent today, and would be wrong the moment this lands. A wiring
   document that lies is worse than none, because it is trusted.

Related: [#25] (hooks), [HOOK-2] (which fills the PENDING slot), and finding 6.2
of the 29 July audit, which reached the same boilerplate from the cost side.

---

## [CHART-1] Chart the enroute fixes, not just the letdown — #26
labels: feature

**Status:** CLOSED MOOT 13 August — the kneeboard's plate and route map were deleted in `69ce4dc`. A pilot gets his chart from the DTC in the aeroplane; there is no page left for enroute fixes to be missing from. Refile against whatever replaces it, if anything does.

The kneeboard has the plate and the route map; the enroute fixes are not drawn
to scale anywhere.

---

## [KB-1] Kneeboards render live, and one of them is the test card — #29
labels: feature

**Status:** VALIDATED — Hoover, read in the cockpit and used to brief and
correct A1, A2, B3 and B7 in one sitting. Closed.

Two things that were one problem. Pages were generated once at container start,
so editing a chart changed nothing until somebody restarted the server — which is
how the kneeboard came to be showing beacon frequencies for a field that had
moved to a radar approach. And there was nowhere to read the test card in the
cockpit.

**Acceptance criteria**
1. Editing a chart or a doc on the host shows up on the next page turn, with no
   restart. (Changing `serve.py` itself still needs one — it defines the app.)
2. `/flighttest/` carries the test card, one tab per section, plus the live
   issues, so a failure can be reported by number from the aeroplane.
3. Both survive an OpenKneeboard reconnect without "No Pages".
4. The card is PARSED from the markdown, never re-authored, so the copy read in
   the cockpit cannot drift from the copy reviewed in a diff.

Flown by: reading the card in the aeroplane and reporting a failure by its
number — which is every other test on this list.

---

## [KB-2] Doodle on the kneeboard pages — #34

labels: feature, needs-flight-test

**Status:** CLOSED — the pilot was right, it is a setting, and it is
now set. Card **A7**.

OpenKneeboard's ink layer IS available to a web dashboard; the page just has to
ask. By default the tab runs in `MouseEmulation` and every pen stroke is
delivered to the document as a mouse drag, which draws nothing. Requesting the
`DoodlesOnly` and `SetCursorEventsMode` experimental features (v1.9+) and calling
`SetCursorEventsMode("DoodlesOnly")` hands the cursor to the ink instead. No
canvas, no persistence layer, no rendering to files.

Two things it has to get right, and both are about not making something worse:

* **The mode follows the PAGE.** The E6B is a working wind-triangle calculator
  with plus and minus buttons on it, and DoodlesOnly takes its clicks away. A
  chart, a plate and a test card are things to write ON; a calculator is a thing
  to PRESS. Switched on every page turn, and only when it actually changes.
* **Doodling is requested only after page navigation is working.** An older
  OpenKneeboard rejects the whole `EnableExperimentalFeatures` call if it does
  not know one of the names, and losing page turns to gain ink is a bad trade.
  If the page API failed we are navigating by the on-screen buttons, and taking
  clicks away there would leave a pilot on page one of a document he cannot
  turn.

    "I want to doodle on the OpenKneeboard pages."

A kneeboard you cannot write on is a poster. The whole reason a pilot straps one
to his leg is to copy a clearance onto it, tick a test row as he flies it, circle
the fix he is worried about, and scribble the number the controller just gave
him. Section G exists to find out whether a CRAFT clearance is copyable at
speaking pace, and right now the answer has to be copied onto something else.

**The thing to establish first**, before any design: OpenKneeboard's ink layer
works on its own page-based tabs (files, images, its own doodle tab). Our pages
are a **Web Dashboard** tab, which is a browser view, and whether OKB will ink
over it — or pass pen and mouse input through to the page — is not something to
assume. That answer decides which of these this becomes, so it is step one and it
is twenty minutes with a stylus, not a design meeting.

**Three shapes, in the order they are worth trying**

1. **OKB inks it natively.** If the web tab accepts ink, there is nothing to
   build but a note in the docs saying which pen mode to use. Best outcome and
   costs nothing; find out first.
2. **We draw it ourselves.** If OKB passes pointer events to the page, an
   overlay canvas on the pages we already own — with the strokes saved per page
   so they survive a page turn, a reconnect and a server restart. This is the
   one that composes with everything else: strokes are just another thing the
   page can persist, so a ticked test row and a circled fix are the same
   mechanism, and a doodle can be read back off the server after the sortie
   instead of being a photograph of a screen.
3. **Render to a file tab.** Generate the pages as PNG or PDF and serve them as
   an OKB file tab, which inks natively today. Costs the live rendering that
   [KB-1] was built for — the card and the charts would go back to being
   generated rather than read — so this is the fallback, not the plan.

**Acceptance criteria**
1. A pilot can draw on the flight-test pages and the charts with a stylus or
   mouse, in the aeroplane, without alt-tabbing out of the sim.
2. Strokes survive a page turn and come back when he returns to that page.
3. They survive an OpenKneeboard reconnect and a kneeboard server restart —
   a clearance copied onto the page is *the* copy, and losing it is worse than
   never having offered.
4. Clearing is deliberate and per page. A pilot must never lose a page of notes
   by tapping the wrong thing.
5. Whatever he drew is retrievable on the ground, so a debrief can look at the
   page he was actually reading.
6. The live rendering from [KB-1] still works — editing a doc still shows up on
   the next page turn.

**Not in scope**: shared or synchronised doodles between two pilots. One pilot,
one kneeboard, same as the real thing.

Depends on nothing. Related: [KB-1] for the rendering, [FT-1] for reporting a
result by radio — doodling is the other half of that, since some findings are a
shape rather than a sentence.

---

## [BUG-4] Which side of course he is on — #35

labels: bug, needs-flight-test

**Status:** CLOSED — cause found and confirmed against the pilot's own
calls twice. Needs one approach flown to close.

**It was GRID CONVERGENCE.** DCS's x/z grid is a transverse Mercator and its
north is not true north; at Batumi the difference is 5.74 degrees. Our radials
come from `ST_Azimuth` on lat/lon and are TRUE. The final approach course was
taken from the F10 ruler, the aircraft compass and `getRunways().course` — all
of which are in the GRID frame. So every centreline this system drew was six
degrees off, and it sat SOUTH of the runway, which is exactly what he said:
"flying me in south of the field".

Confirmed twice from his own radio calls. On final he reported himself right of
course while the controller said left; at the corrected course he was 683 ft and
729 ft RIGHT at those two fixes.

**It also closed [#19].** The outbound trace that reversed 144 degrees now walks
round smoothly — that trace sat exactly where the six-degree error changed which
side of the course he was on, so the engine kept changing its mind.

**Still to do**, and it is Hoover's: the approach is anchored on the runway
CENTRE, half a mile past the 13 threshold, so range calls and the missed
approach point are 0.56 nm late. Separate from the frame error and worth fixing
next.

    "Only major complaint is that he thinks I'm left of course when right of
     course." ... "It shows up as him always vectoring me about .25 miles south."

One cause is found and fixed: the geometry computed in TRUE and the controller
spoke MAGNETIC without converting, so every vector was six degrees right of what
the engine intended. See the frame split in `route.py` and `asr.py`.

**That does not close this.** At seven miles Hoover was told "left of course"
while he believed he was right, and the corrected centreline moves that call by
under two degrees without flipping its sign. Either something else is wrong, or
his sense of which side he was on came from instruments we now know were lying —
the P-51's wet compass read 139 where the F10 map said 123 magnetic, and the DG
beside it had drifted seven degrees the other way.

**How to settle it, and it needs an aeroplane**: fly it in something with an
inertial platform and an HSI — an F-16 — where "which side of the centreline am
I on" is an instrument reading rather than a judgement. If the F-16 agrees with
the controller, the P-51's instruments were the story and this closes. If it
does not, the residual is real and we have a clean measurement of it.

**Acceptance criteria**
1. In an aircraft with an HSI, the side called matches the needle, inbound,
   from 20 nm to the threshold.
2. The distance called matches within 0.2 nm at 10 nm.
3. A P-51 flying the same track gets the same calls — the answer must not
   depend on what the pilot can see.

---

## [PHR-2] Two altitudes for one missed approach — #36

labels: bug, needs-flight-test

**Status:** CLOSED — seen once, live, 27 July.

On the go-around the controller said **"fly heading three three zero, climb and
maintain three thousand"**. Hoover read it back and started up. Thirty seconds
later, checking in after the frequency change, he was told **"turn right heading
three one one, maintain two thousand, vectoring for another approach"**.

Two altitudes for one missed approach, a half-minute apart, with a read-back in
between. A pilot climbing away from a runway with the throttle up is the worst
possible audience for a contradiction, and there is no way for him to tell which
one is the mistake.

Same shape as the departure-frequency contradiction fixed the same night: a
number the controller INVENTS on one transmission and INVENTS AGAIN on the next,
where it should have come from one place. The missed approach altitude is
published — it is on the plate — so it should be quoted, not remembered.

**Acceptance criteria**
1. The altitude in the go-around instruction is the plate's missed approach
   altitude, and the same number is used on the check-in that follows.
2. If the controller means to change it, he says so — "amend your altitude,
   maintain two thousand" — rather than issuing a different number as though it
   were the first one.
3. A regression check drives a go-around and compares the two transmissions.

---

## [ASR-4] Vector him onto a BASE LEG, not at a point — #39

labels: bug, needs-flight-test

**Status:** CLOSED for the pattern; **criterion 2 still open**.

**Remaining scope (10 Aug).** The base-leg pattern is BUILT and flown by the
sweeps; the original point-vs-pattern design question is settled. What is left
is narrower and worth stating so nobody re-opens the design: **speed-scaled
turn-in and intercept geometry**, plus the non-turning case (`--deaf`). Read the
diagnosis below as history, not as a plan.

Built 27 July. The reposition is now three legs — downwind, base, final — each a
TRACK with a heading he can hold, joined by intercepting a line rather than
chasing a dot. The clean sweep is the best it has ever been: 1296 of 1296
arrived, **zero** rapid reversals, and fewer direction changes than the old
point-chasing gate.

The pilot's own second idea went in with it: the legs are **bands**, not lines.

    "you could also make the IF a circle that is like 5 miles rather than a
     point"

Holding a pilot to an exact track means correcting him for a tenth of a mile,
and a pilot who lags oscillates across it — the sloppy sweep's direction changes
nearly doubled before a 1.5 nm tolerance was added.

**What is NOT fixed, and it is criterion 2.** A fast aircraft still overshoots
the centreline on the turn from base to final — at 450 knots a 45-degree
intercept from five miles is not enough, he crosses to eight miles the other
side, and the engine correctly but expensively sends him round again. The
circling he reported is gone; the overshoot that can cause a second circuit is
not. The intercept angle and the turn-in distance need to scale with
groundspeed, which the engine now has (see descent.py).

**Also recorded rather than smoothed:** the `--deaf` sweep's reversals went from
20 to 72. A pilot who never turns is flown through all three legs and the engine
keeps re-deciding which one he is on. Same root as the overshoot.

    "He has a very hard time getting me to the IF, then it works well... right
     now, if I'm going fast, he basically flies me around in circles. If I'm
     going slow enough, he aims me right at the IF -- even if I'm 180 out of
     phase, then turns me hard 180. It would be way better if he had a right
     base and a left base that he could put me on. Again, once established it
     was really good."

**The engine steers at a POINT.** `entry_gate` returns one place on the ground,
just outside the intercept wedge, and an aircraft that is not in position is
vectored straight at it. That is why both failures look the way they do:

* **Fast** — the gate is recomputed as he moves, the bearing to it rotates as
  fast as he turns, and he chases it round. Twelve vector calls in twenty-degree
  steps, which is the circle he describes.
* **Slow** — he reaches the point pointing the wrong way and has to be turned
  through 180 degrees, because arriving at a place says nothing about arriving
  on a heading.

Neither is how anybody vectors an aeroplane. A real controller flies him a
PATTERN: downwind, base, final — three legs at known angles, each one a heading
he can hold, and the turn onto final is a 30-45 degree intercept rather than a
reversal.

**What to design.** A base leg is a TRACK, not a point: perpendicular to the
final approach course, on the side he is already on, crossing the centreline far
enough out that the turn onto final fits. The vectoring question stops being
"what heading points at the gate" and becomes "which leg is he on, and what
heading holds it":

    downwind   parallel to the course, opposite direction, offset to one side
    base       90 degrees to the course, turning toward the centreline
    final      the 30-45 degree intercept that already works

The engine is deliberately stateless -- `guide` computes from position alone --
so the design has to decide a leg from geometry rather than remembering one.
That is the interesting part, and it is worth doing carefully: which leg a
position belongs to is a function of along-track, cross-track and heading, and
getting it wrong produces exactly the dithering the sweep measures.

**Right base and left base**, as he says: pick the side he is already on and
never cross him through the centreline to reach the other one.

**Acceptance criteria**
1. An aircraft arriving from any direction is established on final having flown
   recognisable legs, with no turn greater than 90 degrees between consecutive
   instructions.
2. A fast aircraft is not turned in a circle: the number of direction changes
   before established does not grow with speed.
3. An aircraft 180 degrees out of phase is taken downwind and turned base,
   never pointed at a fix and reversed on arrival.
4. The side is chosen once and not swapped.
5. `asr_sweep.py`, `--sloppy` and `--deaf` no worse than baseline, and the
   established range improves.

This is the last big piece of the approach: he reports that once established the
talkdown is "really good", and every complaint left is about how he gets there.

---

## [ARCH-4] A person is his handle; a flight has a name; members have neither — #42

labels: architecture, needs-flight-test

**Status:** CLOSED — designed with the pilot 29 July and built the
same night, `e0d03a2`..`a17998f`. Create, join, the one-mile rule, break-out,
lead-loss and the voiced verdicts all work over real SRS against synthetic
pilots; the manned path and two humans are unflown. Card section D.

Every identity failure this week came from one place: deriving a member's radio
identity from a flight number. "Falcon 1-1" and "Falcon 1-2" share a flight, so
a lookup on the flight handed two pilots each other's position; a lead refused
for want of a radar track let his wingman's radio take the FLIGHT's name; and a
callsign a man had used an hour earlier separated him from himself.

The pilot's model removes the thing that breaks rather than guarding it:

    A PERSON IS HIS HANDLE.        Sockeye is Sockeye as a single, whatever he
                                   is flying, on every sortie.
    A FLIGHT HAS ITS OWN NAME.     "Apex", not "Sockeye's flight" and not a
                                   number derived from anybody.
    MEMBERS HAVE NO RADIO IDENTITY WHILE THE FLIGHT IS TOGETHER. There is no
                                   "Apex 1-2" on the ATC frequency. Only the
                                   flight speaks.
    ANY MEMBER MAY SPEAK FOR IT.   The flight is not bound to one radio -- if
                                   lead goes down, another member carries on.
    A PILOT IS IN ZERO OR ONE.     Membership is exclusive and registered.

    "Maybe apex1-1 is intra flight speak and never lands in atc"

Which turns the hardest case into the easiest. A member callsign is not
something the controller has to resolve -- it is EVIDENCE THE TRANSMISSION IS
NOT ADDRESSED TO HIM. We already classify ship-to-ship; a member number becomes
its strongest indicator. Everything ATC hears is then either a HANDLE or a
FLIGHT NAME, and both are closed sets.

**HOW MEMBERS ATTACH, which is the question that needed answering.** By
declaration, naming handles:

    "Georgia Center, Sockeye -- forming Apex flight of three with Shooter and
     Andre"

That is speech, and it is safe for the same reason the identity ladder is safe:
the names are matched against a CLOSED, KNOWN SET. We know exactly who is
connected (the SRS roster) and who is flying (the manned tracks) -- so "Shooter
and Andre" is two words checked against maybe four people demonstrably online,
not open-ended parsing. A claim matched against an authority, never believed on
its own.

Two creation paths, and both already have somewhere to live:

    ON THE GROUND   opening a plan at clearance delivery, where the flight and
                    its members are typed rather than spoken.
    IN THE AIR      the declaration above.

**THE SECOND HALF, designed 29 July and NOT yet built.** An approach is flown
as a flight or as individuals, and which one is the FLIGHT'S choice:

    "It's the flights choice if they want to break up. Not atc problem. So if
     apex asks for the approach, atc routes them like one. If the flight
     reports a breakup then 4 pilots check in, they all need to ask for the
     approach. Atc will treat like 4 airplanes."

Which deletes two things outright. "Can you maintain visual separation between
your aircraft?" goes, because separation WITHIN a formation is the flight
lead's and never the controller's -- the real rule as well -- so there was
never anything to negotiate. And the break-up stops assigning levels: it does
one thing, the flight stops existing, and each aeroplane then checks in as an
ordinary arrival through the same path as a single. That removes the capacity
problem entirely, since there is nothing to fit.

    THE LEAD IS THE DECLARER, and ATC needs him for exactly ONE thing: the
    track the geometry uses. Not for identifying who is talking (any member may
    speak) and not for separation (the flight is one entity). When the lead
    drops out the roster promotes the next member, so the position source
    follows without anybody saying anything.

    WHEN A FLIGHT FALLS APART IMPLICITLY -- they cannot hold formation -- ATC
    does NOT force the split, because breaking up is the flight's choice. But
    it must not pretend either: `tracks.in_formation` already knows, so the
    honest response is to say what radar shows and decline to keep working them
    as one thing. The choice stays theirs; the consequence is stated.

ATTEMPTED AND REVERTED, 29 July. The break-up change ripples through
twenty-two formation tests -- levels, capacity, sequencing after the split, and
the "ask, do not infer" path all encode the old two-step. Half-done semantics
left in the tree overnight is worse than none, so it went back to a green
tree. It wants a clean pass, not the end of a long session.

**Acceptance criteria**
1. `handle()` identifies the person; the ATC-facing name is a handle or a
   flight name, never a member number.
2. A flight record carries a NAME, a lead and a member list of handles, and a
   pilot may appear in at most one.
3. Any member's radio resolves to the flight while the flight exists.
4. A transmission whose callsign is a member number is treated as intra-flight
   and does not move ATC state.
5. Forming a flight in the air matches spoken handles against connected
   players, and refuses a name it cannot match rather than inventing a member.
6. On dissolution every member reverts to his handle, and the flight name
   refers to nobody -- which is what real procedure does and what
   `Controller.ambiguous_after_breakup` already assumes.
7. The visual-separation question is gone.
8. A break-up assigns nothing; each aeroplane checks in and requests the
   approach as a single.
9. A flight that is no longer in formation on radar is TOLD SO, and the
   controller declines to work it as one aeroplane -- without forcing a split.
10. A PILOT CAN ONLY JOIN HIMSELF, and only from inside one mile. The lead
    declares a NAME and nothing else -- no members, no count -- so there is
    nothing in the request for Whisper to get wrong. Joining is the moment the
    controller stops separating him, so the radio call and the physical fact
    have to agree; a distance nobody can measure is a refusal, not a pass.
11. When the LEAD is lost, THE FLIGHT DISSOLVES and the survivors revert to
    individuals. Simpler than promoting somebody and more honest: the flight's
    geometry IS the lead's track, so once he is gone the flight has no
    position. It is also the conservative failure -- the controller starts
    separating the survivors, which is what two men whose lead just went down
    need -- and they re-form through the one path there is.
12. A member must be able to break HIMSELF out. A lost wingman who transmits
    is otherwise answered as the flight, so the controller vectors the lead --
    the man who needs help gets none and somebody who did not ask gets turned.

**29 July: forming up made both aeroplanes invisible.** The first rehearsal
scored one record out of seven and looked like a parser fault in
`parse_create`. It was not — the regex reads every phrasing correctly. The
radar picture collapses a formation onto ONE line for the controller, and the
collapse dropped everything but the lead's name:

    362nd_Sockeye-1 (P-51D-30-NA) IN FORMATION with 362nd_Andre-1 — 2 ships,
    lead 13.5 nm on the 307 radial, 5,952 ft, heading 062, 281 knots

Every scope regex wanted a colon after the type and a formation line has none,
so the lead did not parse; the wingman is named only inside the prose, so he
did not either. `units_on` returned neither, `_ident.track` was empty, `_who`
was empty — and the bridge's whole flight block is gated on `_who`. Create,
join and break-out were all unreachable.

Backwards in the way that matters: **forming up is what a pilot does
immediately before asking to join a flight**, so the act made him
unidentifiable. In the rehearsal Sockeye and Andre were placed a few hundred
yards apart precisely to exercise the one-mile rule and thereby vanished, while
Shooter — ten miles out, alone, and written as the REFUSAL — was the only one
the ladder could see. The single negative case passed and every positive case
died, which is what made it read as a parser bug.

Fixed on both sides of the seam. `tracks._render` gives each wingman his own
airframe, manned flag and **distance off the lead**; `identity.units_on` reads
the formation line; and `identity.flatten_formation` rewrites the line into the
ordinary shape the four position regexes already parse, so they did not each
need teaching about formations — and could not each be taught differently.

The offset is not decoration. `FORM_NM` is 2.0 and `JOIN_NM` is 1.0, so "radar
shows them as a formation" is NOT evidence they are within a mile, and using it
as evidence would have doubled the join radius silently. An offset the picture
does not carry reads as **unknown, never zero** — the bridge and the director
are separate deployables and an older picture is a real thing to be handed.
Guarded by `tests/test_formation_scope.py`, which lifts `_other_ship` out of
the director's source and round-trips it through the bridge's parser, because
the two processes do not import each other and a hand-written fixture would
only prove the parser can read the test's idea of the line.

**And the crash the repair uncovered.** With formations parsing, the rehearsal
got as far as `Apex: created, lead Sockeye` — the exact line that was
impossible before — and the bridge then died on the next transmission:

    AttributeError: module 'marshall.atc.flights' has no attribute
    'parse_adopting'. Did you mean: 'parse_joining'?

Adoption was designed and then dropped: a pilot joins HIMSELF, on his own
radio, because that is the transmission radar can corroborate, and rejoining
after a break-out is joining rather than a case of its own. `parse_adopting`
went with the simplification and its call site stayed.

It had never fired because it needs `_who`, `_who` needs a resolved TRACK, and
both routes to one were blocked — a pilot identified from a filed strip has a
callsign and no track, and every aeroplane in a formation resolved to nothing.
So it was unreachable in practice and reachable the instant identity worked.
An AttributeError in the SRS thread is not an ordinary bug: the bridge IS the
radio, so it takes the frequency down and the only symptom a pilot sees is that
ATC stopped existing.

Guarded by `tests/test_bridge_calls.py`, which walks the bridge's AST and
checks every `fl.*` and `identity.*` against what those modules actually
define. Importing the module proves nothing here and the unit suite never runs
the SRS loop, so the source is the only place this is visible before a sortie.
`connected_handles` went too — it existed only to supply the closed set of
handles that a declaration could name, and nobody names handles any more.

Related: [#40] (identity), [#38] (a callsign is a position), [#12] (break-up).

---

## [ARCH-3] The sim already tells us; we are inferring it instead — #41

labels: architecture, needs-flight-test

**Status:** CLOSED — `7c9ca15`..`91a9d3f`. `land`,
`takeoff` and `player_leave_unit` are consumed and drive the Tower handoff and
the slot release. Unflown. Card section E.

    "for landing - isn't there a dcs event that we can use to determine if the
     pilot landed or not?"

There is, and asking the question turned up a whole stream nobody is using.
`mission.StreamEvents` carries, among others:

    land, runway_touch, takeoff, runway_takeoff, landing_quality_mark
    birth, crash, ejection, unit_lost, pilot_dead
    player_enter_unit, player_leave_unit, player_change_slot
    engine_startup, engine_shutdown
    connect, disconnect, srs_connect, srs_disconnect

Only `StreamUnits` is subscribed to. Everything else in this system that wants
to know a STATE CHANGE infers it from a position sample, which is guessing at
something the sim would simply state.

**What is currently inferred and should not be:**

  LANDED        inferred from altitude under 200 ft and speed under 60 kt.
                Reasonable, tested, and still a heuristic -- it exists because
                a taxiing aeroplane read as a go-around and a parked one was
                told to climb to three thousand. `land` says it outright.

  AIRBORNE      the same test in reverse, with the same objection.

  A NEW SLOT    [#38] asks how a pilot changes aircraft without an engineer
                resetting his binding by hand. `player_change_slot` and
                `player_leave_unit` answer it exactly, and they are the sim
                telling us rather than us noticing afterwards.

  A NEW CONTACT the radar picture is polled; `birth` is an announcement.

**And the one worth its own line: `srs_connect` / `srs_disconnect`.** The sim
reports the RADIO joining and leaving. That is the third leg of the identity
triangle -- person, aeroplane, radio -- arriving as an event rather than being
correlated from a name match, which is what [ARCH-2] spent two days building
around.

**Why this is architectural rather than a tidy-up.** Every inference above is a
sample of a continuous quantity used to detect a discrete change, and that is
the shape of bug this project keeps producing: the position is right and the
CONCLUSION drawn from it is wrong at the boundary. An event has no boundary.

**Deliberately not built the afternoon a guest was flying.** The heuristics
work and are tested; a new streaming subscription, its reconnection behaviour
and its state are not something to land an hour before somebody arrives. The
right sequence is a consumer alongside the track streamer, events written where
`tracks` already is, and the inferences retired one at a time as each event
proves itself -- with the heuristic kept as the fallback for a stream that
drops, because the sim pausing is a normal event here and a dead subscription
must not read as "nobody ever lands".

**THE HANDOFF IS THE BEST EXAMPLE, and the pilot named it:**

    "Landing / takeoff event should be triggers to switch to/from tower"

Which is what the real thing does. Right now Approach gives him up at a RANGE
(`hands_to_tower_nm`), and that number has already had to be special-cased once
because handing a man over mid-talkdown abandons him at the exact moment the
procedure starts -- "contact Batumi Tower now" while the same controller was
still reading his range every mile. The range is standing in for an event that
exists.

    landing:    Approach keeps him through the talkdown. `land` -- or
                `runway_touch` -- is what moves him to Tower, because touching
                down is precisely when the approach is over. Nothing about
                distance can express that; a go-around at half a mile is closer
                than a landing at one.
    departure:  `takeoff` / `runway_takeoff` moves him OFF Tower. Today nothing
                does, which is why a departing flight was given to Approach at
                25 miles and never handed back.

Both are the same mistake as the landing guess: a threshold on a continuous
quantity standing in for a discrete fact the sim publishes.

**Acceptance criteria**
1. A `StreamEvents` consumer runs beside the track streamer and survives the
   sim pausing, a director restart, and a mission reload.
2. `land` retires the altitude/speed guess in `asr_context`, which stays as the
   fallback when no event has been seen for that aircraft.
3. `land` / `runway_touch` triggers the handoff to Tower; `takeoff` triggers
   the handoff away from it. The range rule stays as the fallback.
4. `player_leave_unit` / `player_change_slot` clears the slot-to-callsign
   association -- [#38].

       "Player leaving slot event can clear database for slot association to
        callsign"

   This is the answer to the question he asked days ago and nobody had one for:

       "how do I reset it without engineering help? What happens in the future
        if a pilot changes slots and call signs?"

   The stand-in today is a TWO HOUR TTL on the binding (`identify.py`,
   `BINDING_TTL_SEC`), which is the same mistake as the landing guess wearing
   different clothes -- a timer approximating an event. Two hours is far too
   long for a man who swapped aeroplanes between sorties and far too short for
   one flying a long mission, and it can never be right because the quantity it
   measures is not the one that matters. Leaving the slot IS the moment the
   association stops being true, and the sim says so.

   It also completes [#38]'s thesis rather than merely serving it: a callsign
   is a POSITION, and a position is vacated. The event is the vacating.
5. Events are recorded where a sortie can be replayed against them.
6. `BINDING_TTL_SEC` is retired, or demoted to the fallback for a session where
   no event stream was available.

Related: [#38] (a callsign is a position), [#40] (identity).

---

## [ARCH-2] The board is keyed on a mis-transcribable string — #40

labels: architecture, needs-flight-test

**Status:** CLOSED — `ffb6bab`..`a17998f`. The
ladder is built and running; no pilot has flown it. Card section B.

**Documentation conflict, resolve before working it (10 Aug).** This reads as
shipped here while `docs/WIRING.md` still describes the separation engine as
keyed on a Whisper-derived string. One of the two is wrong and it decides
whether there is any work left at all. Settle that first; sequence #38 before
this if the model itself is still in question.

**Was:** TODO — design first, and MEASURE before building.

    "the fact that this can happen -- that there is some dictionary with ghost
     aircraft -- makes me concerned about the foundational architecture of what
     we've built. My concern is that it's been working well for one human
     aircraft as long as whisper transcriptions are perfect.. But wait till
     there are 10 guys on."

The concern is correct and the flaw is one line: `Controller.aircraft` is a
`dict[callsign -> Aircraft]`, and the callsign arrives through Whisper.

**The primary key of the separation engine is a string a machine guessed at from
audio.** Everything else follows. A garbled callsign can mint an entry, which is
the ghost problem — three of them in one evening. But with more than one
aeroplane the worse failure is not a ghost, it is a COLLISION: a transmission
from one pilot filed against another's key moves the wrong aircraft's altitude,
phase and place in the queue. That is a separation error, not noise, and nothing
in the system would report it.

**What the key should be.** Two identifiers exist that are not spoken and cannot
be mis-heard: the sim's unit name for a track, and the SRS GUID of a radio. The
callsign is the wrong thing to key on for exactly the reason [#38] gives — it is
a POSITION, not an identity. It changes between sorties, it is handed between
pilots, and it is the only one of the three that arrives as sound.

So the aircraft record should be keyed on the TRACK, with the callsign demoted
to a label used for addressing him on the radio. Resolution then runs GUID ->
person -> track, none of which involves parsing words, and a transmission that
cannot be resolved touches nothing.

**What today's guards do, and what they do not.** Three landed on 27 July: our
own phraseology cannot become a callsign; only a bound radio or a tagged track
may become an aeroplane; and nothing unidentified may be sequenced. Together
they make the single-aircraft case sound and they remove the ghost class. They
do NOT change the key, so the collision case is untested and unguarded.

**MEASURE FIRST.** `radio/rehearsal.py` already drives synthetic pilots over real
SRS with real Whisper and Polly. A multi-aircraft rehearsal -- four or six
radios, overlapping calls, deliberately similar callsigns -- would say what
actually breaks and how often, and turn this from an architectural worry into a
number. Refactoring the key before that is guessing at scale, and the last time
this project guessed at a fix rather than measuring it, three ghosts survived
four attempts.

**MEASURED, 27 July.** `srs/crowd.py` replays every flight recording on disk.
846 real transmissions; the extractor would bind a radio to **37 distinct
names, of which 10 were aeroplanes**. The corpus is now `tests/test_ghosts.py`.

Three classes, and only the first is closed:

  OUR OWN WORDS       "Maintained 2", "Left 3-0", "Busy 4". Closed by the
                      27 July phraseology guard -- none survive the replay.

  ORDINARY ENGLISH    "You 4" (from "with you 4,100 level"), "Bound 4",
                      "Here 4", "The 2", "Paired 4", "Nearest 5". This class
                      REPLACED the first one and cannot be blacklisted: the
                      supply of English content words is unbounded.

  A REAL CALLSIGN,    "Tony 1-1" for Pony 1-1. "Hammer 1-3" and "Pony 1-4"
  MISHEARD            for Hammer 1-1 and Pony 1-1. THE DANGEROUS CLASS: these
                      have the exact shape of aeroplanes, and on a frequency
                      with a four-ship up they ARE aeroplanes -- so the same
                      transcript that makes a harmless ghost with one pilot
                      makes a MIS-ATTRIBUTION with four, and moves somebody
                      else's altitude.

**Corroboration is the only filter that can work, and the obvious version of it
is circular.** Requiring the spoken name to appear on the radar picture kills
43% of legitimate bindings, because the scope is tagged with the callsign the
binding produced -- an aeroplane cannot be corroborated until it has already
been believed. The corroborating authority has to be something nobody spoke:
the sim's unit names, or a FILED FLIGHT PLAN. Which is the same conclusion
[#38] reached from the other direction.

**Acceptance criteria**
1. A multi-aircraft rehearsal exists and reports mis-attributions per hundred
   transmissions.  DONE -- `srs/crowd.py`, both synthetic and retrospective.
2. The engine can be asked what it believes exists.  DONE -- `Controller.board()`,
   written to the flight recorder on every transmission, so a ghost is
   timestamped against the words that minted it.
3. A transmission that cannot be resolved to a track changes no aircraft state.
4. Two aircraft with similar callsigns ("Pony one two" / "Pony one one") cannot
   have one's report applied to the other.
5. The state a controller holds survives a callsign being re-heard differently.
6. `tests/test_ghosts.py` baseline goes DOWN and never up.

Related: [#38] (a callsign is a position), [#13] (ghosts), [#15] (sequencing).

---

## [PHR-1] Phraseology a real controller would actually use — #30
labels: bug

**Status:** CLOSED — two found so far, both by a pilot

Invented phraseology reaches the air and nothing here catches it, because a test
can check that a call was MADE, not that it is something a controller would ever
say.

Found so far:
- clearing a Mustang with no ADF for a *beacon* approach, and asking him to
  report a fix he had no receiver for
- *"landing assured"* — the pilot's determination, not a controller's, put in
  his mouth as a verdict (fixed: he now gives the clearance and the wind)
- inventing a field, a frequency and a handoff that exist nowhere in the plan
  ([BUG-3] #21)

**This is a script's job, not a sortie's.** You cannot fly enough approaches to
tickle every phrase, and a pilot who does hear a bad one has spent an approach to
find a single instance. A harness can drive hundreds of exchanges through the
real bridge and check every transcript, which is both faster and more complete —
so it carries `needs-synthetic-check`. What still needs a pilot is the judgement
call on a phrase that is *real but wrong*, like "landing assured".

**Acceptance criteria**
1. A harness drives scripted exchanges through the bridge and checks every
   transcript against the LOADED profile: any fix, frequency, field or procedure
   named that is not in the data is a failure.
2. A list of phrases that are the PILOT's to say and the controller never does,
   kept out by test.
3. It runs over the existing rehearsal scripts, so adding a script adds coverage.
4. New procedures have their phraseology read by a pilot before they are flown —
   the one part of this that cannot be automated, because "real phrase, wrong
   speaker" is a judgement and not a lookup.

---

## [ENG-3] Naming a controller releases the engineering line — #32
labels: needs-synthetic-check

**Status:** CLOSED — commit `72b79cc`

Everything a pilot says goes to engineering until he releases the line. Forget
the goodbye and the controller has gone deaf to him — and the moment he is most
likely to forget is four miles out, with other things to think about, which is
also the moment it costs most.

Addressing a station by name is an unambiguous statement about who he is talking
to, and the system should not need it said twice.

Found by briefing the workflow aloud rather than by any test: *"first get
engineering on the line, then say b4 passed, then goodbye engineering?"* — three
steps, and the third is the one you drop.

**Acceptance criteria**
1. On the engineering line, a transmission naming a station ("Batumi Approach,
   ...") reaches ATC and gets a controller's answer.
2. The line is released silently — a "clear" call here would be engineering
   talking over the transmission it just got out of the way of.
3. Engineering traffic that happens to be about ATC is NOT released: "the
   vectors turned me at four miles" stays a note.
4. Explicitly saying goodbye still works and still gets its acknowledgement.

A safety net, not the fix. A verdict should be one transmission and never take
the channel over at all — [FT-1] #31.

---

## [RAD-4] Ship-to-ship on frequency, and the callsign discipline we skip — #33
labels: feature

**Status:** CLOSED

Two related things about who a transmission is FOR.

### Ignoring what is not addressed to him

Real ATC assumes a pilot is talking to it, which is why nobody says "Omaha
Approach" on every transmission — and ours does the same, correctly. But
occasionally two aircraft talk to each other on the same frequency:

> *"Pony one two, Pony one one, join up"*

That is addressed to the wingman. A controller hears it, understands it is not
his, and says nothing. Ours answers it, because everything on its frequency is
treated as a call to it.

The giveaway is the ADDRESSEE, and we can read it: a transmission that opens
with an aircraft callsign which is **not the speaker's own** is ship-to-ship.
"Batumi Approach, Pony one one, ..." opens with a station. "Pony one one, level
five thousand" opens with his own name. "Pony one two, Pony one one, join up"
opens with somebody else's.

**Acceptance criteria**
1. A transmission opening with another aircraft's callsign is logged and **not
   answered**.
2. Opening with his own callsign, a station name, or nothing at all is answered
   as now.
3. It is never applied when the speaker is unidentified — guessing that a call
   is not for us is worse than answering one that was not, because the pilot
   gets silence and no way to tell why.
4. The separation engine does not act on it either: a join-up is not a position
   report.

### The callsign discipline we quietly do not need

Ours has an advantage a real controller does not: the SRS GUID tells it who
transmitted, so a pilot can omit his callsign entirely and still be understood.
That is unrealistic, and it removes the one piece of radio discipline a pilot
genuinely owes — **every transmission starts with who you are**.

Worth keeping the GUID as the ANCHOR. It is what stops a mangled callsign
inventing an aeroplane, and giving that up to chase realism would trade a real
bug for a fictional one. What is missing is the manner: a controller who gets an
unprompted transmission with no callsign in it asks for one, rather than
silently knowing.

**Acceptance criteria**
5. An unprompted call with no callsign draws *"station calling, say your
   callsign"* — even though we know perfectly well who it is.
6. A reply inside a conversation already under way does not (a readback is not
   an unprompted call, and demanding a callsign on every "roger" is its own kind
   of unrealistic).
7. Identity itself still comes from the GUID. This changes what he SAYS, never
   what he knows.

---

## [OPS-2] Backlog and issues stay in step — #27
labels: chore

**Status:** CLOSED

**Acceptance criteria**
1. Every row on the flight test card names an issue.
2. Every SHIPPED/UNVERIFIED issue is closed by a human flight, not by a green
   unit test.
3. `docs/BACKLOG.md` keeps the debriefs and the reasoning; this file keeps the
   work.

---

## [SEQ-2] Nobody is number two behind himself — #50
labels: needs-flight-test

**Status:** FIXED — commit pending. Found live, 31 July, on Fred's first sortie.

**Remaining scope (10 Aug).** The cause is no longer unknown and this issue
should not read as an investigation: `Controller.check_in` reset the phase
unconditionally on a frequency change, which is what returned a CLEARED
aircraft to HOLDING. What is left is **flying card rows H18/H19** to prove it in
the air.

Sockeye was cleared for the approach, which put him in the letdown. Something
then returned him to `HOLDING` while he still held the slot, so he was at once
the aircraft **on** the approach and an aircraft **waiting** for it.

Every request after that reached the "letdown occupied" branch in `_try_clear`,
found it occupied, and told him he was number two behind the only other
aeroplane in the sky — which was him. `_next_up()` would have returned him
immediately; on that branch it is never asked.

He held for four transmissions at 44 nm and then declared an emergency to get
out of it. From the cockpit it is indistinguishable from having been forgotten.

**Fixed by** not queueing the man in the letdown behind the letdown: if the
requester *is* the occupant he is told he is cleared, and his phase is put back
in step with the clearance he already holds. The slot is not released — that
would let a second aircraft in behind him.

**Acceptance criteria**
1. An aircraft that holds the letdown and asks again is told he is cleared,
   never "number two". Guarded by `TestNobodyIsNumberTwoBehindHimself`.
2. A genuine second aircraft is still told "number two". Same class.
3. The letdown is not released by the re-affirmation.
4. ~~**Still open:** what returned him to `HOLDING` while cleared.~~ **FOUND
   2 August.** `Controller.check_in` reset `ac.phase = Phase.ENROUTE`
   unconditionally, so *any* frequency change put a cleared aircraft back in the
   queue — and the eight-rung ladder changes frequency seven times, which is why
   this surfaced the moment there were two aerodromes. One unguarded line, two
   hundred lines from the symptom, with `seed_from_radar` directly above it
   already carrying the guard. It is a cure now rather than a guard.

**Flown by:** card rows **H18** (ask again while cleared) and **H19** (check in
on a new frequency while cleared) — the second is the root cause, and it needs
the ladder to provoke it.

---

## [HO-2] Georgia Center has no proactive handoff at all — #51
labels: bug

**Status:** CLOSED — one cascade, `agent_atc.next_controller`. Found live, 31 July.

`handoff.RULES` contains no rule whose `frm` is `center`. The proactive monitor
therefore can never hand anybody off Center — only the receive path can, via
`profile.handoff_from`, and only when the pilot transmits inside
`approach_hands_over_nm` (25 nm).

On the sortie this compounded [SEQ-1]: he was held by Center at 44 nm, nineteen
miles outside the airspace Approach would have taken him in, with no mechanism
that could ever have moved him on.

**There were THREE mechanisms, not two.** The receive path ran a cascade
inline — the sim's events, then a rule table, then the airspace volumes — and
nothing else could ask the question the same way. The monitor asked only the
rules; `tools/handoff_check.py` asked only the volumes and reported "all cases
behaved" while Center could not hand anybody over at all.

**Acceptance criteria**
1. ✅ `center -> approach` exists, conditioned on inbound range, and fires
   unprompted.
2. ✅ One function answers "who has him next" — `next_controller` — and the
   bridge, the monitor and the live check all call it.
3. ✅ `route.handoff_from` is deleted. It also belonged in `atc/` on the
   layering: a handoff is procedure and `core` may not depend on `atc`.
4. ✅ A live case guards the fix. There was none: every existing case passed
   with a Center that never lets go.

**Found while fixing it**, both by printing the ladder rather than by flying it:
- Nothing handed a *departure* to Center either, so preset 4 was unreachable
  outbound. Mirror of the same gap.
- `airborne_beyond` ignored the direction, breaking the rule the module's own
  docstring opens with. It survived because its only rule was
  `tower -> departure`, where an arrival is rarely still on Tower at six miles;
  adding `departure -> center` made it reachable at once, and an aircraft 25 nm
  out **inbound** was handed away from the field it was arriving at. It is
  `outbound_beyond` now, and a structural test asserts every distance rule reads
  the trend.

**Still dead ends** (a preset nothing can hand you off, which in the air is
indistinguishable from being forgotten):
- `Kobuleti Clearance` — deliberate; "he has his clearance and is ready to push"
  is not a fact the sim reports.
- `Batumi Ground` — not deliberate, and **it is now its own issue rather than a
  loose end hanging off this one.** An issue whose own criteria are all met but
  which stays open as a container for a different defect is how work gets lost:
  close it and the defect goes with it, leave it open and nobody can tell what
  it is waiting for. See [HO-3] / #77.

---

## [ID-6] Frequency read-backs are parsed as callsigns — #52
labels: bug

**Status:** CLOSED 9 August. Confirmed live first — five corrections in one
sortie, every one a fragment of a read-back:

    "Write 305 to send 6,500 sockeye"   -> "Send six, I do not have you on the board"
    "Clear to land one tree, sockeye"   -> "Land one three, ..."
    "305, 2000, slow into 250, sockeye" -> "Into two zero, ..."
    "Go on to approach 124 decimal 425, sockeye"  -> "Decimal four five, ..."
    "Batumi Approach, sockeye, with you 12,000"   -> "You one two, ..."

The last arrived directly after a landing clearance.

**Not fixed by a better parser, because that question does not converge.**
`_plausible_callsign` says so in its own docstring: any English word in front of
a digit is a candidate, and a read-back is made of our own words and numbers.
Six ghosts were fixed one denylisted word at a time and one of those fixes
created the next ghost.

**IDENTITY NEVER DEPENDED ON IT.** The SRS GUID and the radar track say who is
talking, so a wrong callsign cannot misroute a clearance or put a ghost in the
stack. The correction is a COURTESY — and a courtesy must fail silent. It was
failing loud.

So the question was narrowed instead of the parser widened. A wrong callsign
matters exactly when it is what everyone else on the frequency heard him call
himself, which is the **check-in** — not the ninth read-back. Real controllers
work that way. And a read-back is structurally mid-conversation, so the entire
class disappears rather than being filtered word by word.

Gated on `heard_on`, which still holds the previous frequency at that point, so
a different channel means a controller who has not heard from him yet. No new
state. A second, free guard: a man does not give himself two callsigns in one
transmission, so a claim is ignored when the transmission also contains the name
his radio answers to.

**Also out:** `heard 'X', but this radio is Y` compared raw strings and fired 23
times in that sortie — 19 of them `Sockeye` against `sockeye`, pure case, burying
the four real mishearings (Sakai, Sucka, Sucker, "Write 2-5-5"). It uses
`_matches_name` now, which is what the rest of the identity path uses.

**Acceptance criteria**
1. ~~A read-back is never mistaken for a callsign.~~ All five from the sortie,
   guarded in `tests/test_identity.py`.
2. ~~A pilot who checks in under a name nobody answers to is still corrected.~~
3. ~~The log notes an identity mismatch only when there is one.~~
---

## [APP-5] The NDB letdown profile claims radar — #53
labels: bug

**Status:** FIXED 11 August — and the flag was not the fault.

`radar=True` on the beacon letdown is **deliberate**: "Radar ON (you wanted
eyes)". The controller reads ranges off his own scope while the pilot, with no
DME, flies the published pattern himself. What was wrong is that ONE FLAG WAS
ANSWERING TWO QUESTIONS — seeing an aeroplane and steering it are different
capabilities, and keying "does he vector?" on `radar` would have given a period
letdown radar phraseology.

`AtcCapability.vectors` separates them. `None` means "ask the procedure", which
is what `_vectored` did all along by naming the procedure KINDS — the workaround
this issue was filed to record. `BATUMI_APPROACH` now says `vectors=False` out
loud instead of relying on its name.

Originally found 2 August while making the ILS a vectored procedure.

`BATUMI_APPROACH` — the 1944 beacon letdown, whose entire purpose is the
non-radar handicap — carries `AtcCapability(radar=True)`.

Nothing reads it today in a way that bites, which is why it has survived. It was
found because `Controller._vectored` was about to be keyed on `atc.radar`, which
is the obvious and correct-looking thing to do: a controller with radar vectors.
Doing so would have given a period letdown radar phraseology — turning an
aeroplane the controller cannot see.

`_vectored` names the procedures instead (`asr`, `ils`) with a comment saying
why, so the workaround is visible rather than quiet.

**Acceptance criteria**
1. The letdown profile's capability says what it is: no radar, procedural
   separation.
2. `Controller._vectored` reads the capability rather than a list of procedure
   names, and the comment explaining why it could not comes out.
3. The approach sweep is unmoved — this changes what the letdown is ALLOWED to
   do, and if that changes how it flies, the capability was load-bearing
   somewhere nobody documented.

---

## [ARCH-5] `route.py` is six subjects in one file — #54
labels: refactor

**Status:** DONE 3 August. Split; the façade keeps the contract.

2,057 lines holding conversions, places, airspace, aerodromes, controllers and
procedures. The size was never the complaint — the COUPLING was. Adding the
second aerodrome meant editing a station four hundred lines away from the field
it belongs to, and four of the bugs that shook out of the two-field work were
that shape: something reaching sideways for a fact nobody had handed it.

Split into `units` / `airspace` / `fixes` / `fields` / `stations` / `approach`,
depending strictly downward in that order, with `route.py` re-exporting all of
it. The re-export is deliberate and not laziness: some three hundred call sites
read `R.BATUMI_ASR`, and the contract they rely on — one place that cannot
disagree with itself — is unchanged. New code imports the narrow module.

Two things moved rather than merely relocating. `field_named` was in the station
block with a docstring explaining the circularity it was working around; it is
the join over `FIELDS` and it lives with them now, and the cycle is gone rather
than commented. `ias_mph` was inside the fix list because that is where it was
written, and it is atmosphere.

**Acceptance criteria**
1. No cycles: each module imports only from those below it.
2. `from marshall.core import route as R` reaches every name it did before.
3. The suite, the sweeps and the three kneeboards are unmoved.

---

## [FP-3] The sortie being flown was not on the board — #56
labels: bug

**Status:** FIXED 7 August; awaiting the flight. The row is on the board and
resolves in the live director, but the acceptance criterion is that a pilot gets
his clearance on the radio — card **Q1** — so this is `needs-flight-test` and a
green sweep does not close it.

Every filed plan departed Batumi. Correct while Batumi was the only aerodrome
with controllers, and it stopped being correct the day Kobuleti got a full
station set and the F-16s moved to its ramp — silently, because nothing fails.

A pilot on the Kobuleti ramp asks for his clearance and is told, in perfect
phraseology, that there is nothing on file for him. That is the first
transmission of the night and it is indistinguishable from having mistyped your
own callsign.

Filed as **Domino** (migration 017), Kobuleti → Batumi, KOBULETI/INITIAL/BATUMI,
five thousand, recovering on the Batumi radar approach.

**Three more things fell out of filing it.**

1. **The plans board had no kneeboard tab.** `kneeboard/plans.py` was written so
   a pilot can read what is on file — its own docstring says he cannot ask for
   "Marlin" if he cannot remember the board — and it was never wired into
   `site.py`. The board existed in the database and on the controller's side of
   the radio, and nowhere the pilot could see it. It is now a PLANS tab.

2. **A row with nothing in it** (`362nd-batumi-asr-2`: a callsign, an approach,
   and no label, route, origin or task) had been on the board since the second
   ship was wired up. Invisible until something rendered it. Removed in 018.

3. **`origin` was never scored** — see #57.

---

## [FP-4] A task that repeats the destination outscores the board — #57
labels: bug

**Status:** CLOSED 7 August.

Domino was filed with the task "transit from Kobuleti to Batumi, radar
recovery", which reads well and is scored at ten points a word. The route and
the destination already carry BATUMI, so one plan collected credit for the same
fact three times — and `"IFR to Batumi, ready to copy"`, a request every plan
answers equally and which the sweep exists to keep AMBIGUOUS, resolved
confidently onto the Kobuleti departure.

Migration 012's warning exactly: not an error, a plausible answer to a question
nobody asked. A pilot at Batumi would have been cleared onto a sortie starting
at another aerodrome.

**The real fix was that `origin` was not scored at all.** It never carried
information — every plan left Batumi, so scoring it would have added one point
to all of them — and `plans.py` says so at the top. Domino makes it the most
discriminating field on the board: one row, one origin that is not Batumi. So
the endpoints are read from their own fields, and the task went back to saying
what he is DOING (019), which is what the other five already did.

**Left open deliberately.** "Clearance for the transit FROM Kobuleti TO Batumi"
asks rather than resolving, because Anvil's task legitimately owns the word
Kobuleti — going there is its job. Telling them apart needs the DIRECTION, which
nothing parses. Recorded as ASK in the sweep rather than tuned away: moving a
weight until one case flips is fitting the scorer to the test, the cost of being
wrong is a clearance onto somebody else's sortie, and the cost of asking is the
pilot saying one more word.

---

## [BUG-5] The controller invented every frequency except Departure's — #58
labels: bug

**Status:** FIXED 7 August; awaiting the flight. Found in the dry run, not in
the air — and the air is where it is confirmed, because what is being checked is
a number a controller says out loud. Card row **Q13** asks him for his own
field's ground and tower frequencies. `needs-flight-test`.

Kobuleti Clearance told a pilot **"Ground is one three three decimal zero"** —
that is Kobuleti TOWER; Ground is 121.800 — and **"Tower is one one eight
decimal zero"**, which is Batumi Tower's second channel, at the field he had not
taken off for yet. Both in correct phraseology, confidently, and a pilot has no
way to tell.

It was inventing them because it had never been given any. The only frequency in
the brief was DEPARTURE FREQUENCY, added after a clearance and a taxi
instruction disagreed about it — so Departure came out right and everything else
was guessed.

**And the brief was teaching one of the wrong ones.** The YOU ARE block carried a
worked example of correcting a pilot on the wrong button, and the example
contained a literal `"Tower is one one eight decimal zero"`. The model lifted it
verbatim as fact. An example in a prompt is data to a model; it may not contain
a number that could be mistaken for this field's.

Fixed by handing the controller **his own aerodrome's station list** — the same
one the comms card prints and the aeroplane's presets are built from, so the
card, the radio and the man cannot disagree. A real controller knows his own
field's frequencies; supplying them corrects an omission rather than adding a
hint.

**And the departure lookup was the two-field bug again**, walking
`profile.stations` for the first role match. `station_for` was rewritten to stop
doing that; this one kept doing it. Kobuleti Departure is listed first, so
Kobuleti was right by accident and a BATUMI clearance was about to name a
controller forty miles up the coast.

Guarded in `tests/test_two_fields.py`, including channels — the frequency that
actually leaked was a `channels` entry and not a `freq_mhz`, so a check walking
only `freq_mhz` passed against the broken brief and guarded nothing.

---

## [OPS-3] Three tools that lied about what they had done — #59
labels: bug

**Status:** CLOSED 7 August.

Not one bug; one shape, found three times in an afternoon of pre-flight checks.
Each of these reported something other than what it did, and each was believed.

1. **`atc_dryrun` printed replies the radio would never carry.** It called
   `for_voice(reply)` without `agent=True`, so a reply with no `RADIO:` marker
   printed in full — and is SILENCE on the live radio. It showed four turns of
   the controller narrating his own reasoning that a pilot would never have
   heard, and hid the failure that actually matters: that he said nothing.

2. **The mission builder's summary was a fixed string.** `"4 x P-51D-30 + 2 x
   P-47D-30, airborne over REHEARSAL"` no matter what was built. Under
   `--session` it reported four Mustangs and two Thunderbolts airborne; there
   were eight client slots, half of them F-16s on the Kobuleti ramp, and no
   P-47 at all. It cost an hour hunting for aircraft that were in the file the
   whole time. It reads the mission now.

3. **`write_presets` was handed the units `--session` had just deleted.** So a
   session mission wrote SCR-522 preset files for four Mustangs and two
   Thunderbolts that were no longer in the .miz, and wrote none at all for the
   eight aeroplanes somebody was about to fly. It has never bitten because the
   F-16 takes its presets from the mission table and the F-16 is what gets
   flown — a session Mustang has been mute since session missions were added.

The lesson is the one already in `atc_dryrun`'s own comment about the message it
used to assemble by hand: **a tool that shows you something other than what the
system does is worse than no tool, because you believe it.**

---

## [OPS-4] The card check was blind to a quarter of the card — #60
labels: bug

**Status:** CLOSED 10 August. All three criteria met and `check.py` is green
on this check for the first time.

**What the row's `[#n]` means is now written down and enforced.** `[#n]` says
the row is CHASING finding n and retires when n closes; `[R#n]` says the row
EXERCISES the fix in n and is the regression that tells us if it rots — closing
n is when it starts earning its keep. The seventeen rows are `[R#n]` now, so
Q6/Q8/Q9 — the only rows that test handoffs between two aerodromes — stay on the
card instead of being struck for citing a single-aerodrome fix. The convention is
documented on the card itself, not just here.

Criterion 3 was fixed alongside the Codex audit: `issue_sync` exits **2** when it
cannot reach GitHub, which `check.py` reads as SKIP and reports by name, rather
than failing on `gh auth` and masking the real drift.

**Two more faults found while closing it, neither in the acceptance criteria.**
Q5 — the take-off-refusal row, the one the card calls the most serious finding it
can record — cited **#41** while #65 was filed saying "card row Q5 is the check".
So the row and its issue each thought the other was covered. And #66 had no row
at all. Both fixed: Q5 recites #65, and Q9b is the departure-greeting check.

**And the check gained a rule it should always have had.** Nothing verified that
a slug is unique, and I filed three collisions in two days — [OPS-4], [OPS-5] and
[OPS-6] each named two different issues — by appending to this file without
reading up. The number is unique because GitHub assigns it; the slug is chosen by
hand and is what anybody says out loud. Renamed to OPS-7/8/9, plus two older
collisions ([ID-3] on #14 and #48, [SEQ-1] on #15 and #50), and the check now
refuses a duplicate.

`issue_sync` matches a cockpit row as `| H7 | P2 | ... [#19]`. Sections **Q, R,
S and T** — added 2 August, the two-field ladder, ATIS, phraseology and the
Kobuleti ILS — write their IDs in bold, and Q has a lettered row: `| **Q1b** |`.
The pattern matched none of them. Fourteen rows in Q alone were invisible, and
the check reported "labelled `needs-flight-test` and no row cites it" for issues
whose rows were sitting on the card in the section written for them.

**A check that silently ignores a quarter of the document is worse than none,
because its silence reads as agreement.** Same fault as the three tools in #59,
in the thing that is supposed to catch faults — and it survived because it was
un-runnable: it needs `GH_TOKEN`, and the token was exported from a branch of
`.bashrc` that returns early for non-interactive shells, so every automated run
failed on `gh auth` before reaching this.

**What it now reports, and why that is also wrong.** Seventeen rows cite closed
issues, and the tool's advice is to strike them through and keep the script as
the regression. That advice is right for a row that has been FLOWN. Every one of
these is in a section that has never been flown: they cite the issue whose fix
they exercise, and those fixes were closed on earlier sorties at a single
aerodrome — which is exactly the condition under which four of them were
*correct by accident*.

So the card conflates two things behind one `[#n]`:

* **the finding this row is chasing** — open, and the row retires when it closes
* **the fix this row exercises** — closed, and the row is the regression check
  that tells us if it rots

They want different columns and different handling. Striking Q6, Q8 and Q9
because #16 is closed would delete the only rows that test handoffs between two
aerodromes.

**Acceptance criteria**
1. A row can name a closed fix as its subject without being reported as stale.
2. A row chasing an open finding still retires when that finding closes.
3. The check runs in a non-interactive shell — if it cannot reach GitHub it says
   SKIPPED and names what is unguarded, rather than failing on `gh auth`.

---

## [FP-5] The board is the sortie, and the address is not a request — #61
labels: bug

**Status:** CLOSED 7 August.

    "lets clean up the flight plan database - leave only the one kobuleti to
     batumi ifr"

Five of the six rows were the single-aerodrome TEST board from migration 012 —
built so the wrong answer would be available. That is the right board for
testing clearance delivery and the wrong one for flying, because every row is an
answer a pilot might be handed by mistake. Migration 020 leaves Domino.

**A migration alone would have been self-reversing.**
`agent_atc.load_and_push_plate` upserted `362nd-batumi-asr` with `active=true`
on every start, so the deleted row — and the active flag with it — came back on
the next bridge restart. The board would have looked clean until nobody was
watching. The bridge seeds `BOOTSTRAP_PLAN` now, named once so a migration and
the bootstrap cannot disagree, and it no longer writes a Mustang's callsign onto
a plan an F-16 flies.

**Trimming the board then exposed two faults in the resolver**, neither of which
can appear on a five-plan board — there is always another plan to be ambiguous
with, so a standing bonus to the local one changes no outcome:

1. **"Request clearance to Vaziani" was answered with a clearance to Batumi.**
   Reading the ORIGIN off the station he addressed (#57) gave every plan at his
   field four points on *every* transmission, because every transmission opens
   by naming a station. With one plan on the board that floor was enough to win.
   The address is banked separately now: it breaks ties between plans his own
   words already point at, and can never be the match on its own.
2. **"Kobuleti Clearance, Viper one one, request clearance" was answered with
   "nothing on file".** The plainest request in aviation. The station name
   survived into the test for *did he name something specific*, so addressing a
   controller read as asking for a sortie nobody had filed.

Both are the same mistake in two places, and it is the one this whole file keeps
finding: **something reaching sideways for a fact it should have been handed.**

**What this costs, stated plainly.** `plan_assign_check` needs two filed plans
and now SKIPS, naming #1 as unguarded — which is the suite working as intended.
`plan_sweep --live` skips eleven of its sixteen cases and names each one; the
inline fixture still exercises all sixteen with no database, so tier-1 coverage
is unchanged. Re-running migration 012 restores the test board.

---

## [ARCH-7] The router had no idea what was possible — #62
labels: architecture

**Status:** DONE 9 August. Found by a pilot, from the cockpit, not by a test.

    "why would one of the brains (the one doing the wrong thing) be invoked at
     all when that phase of flight isn't happening. I feel like there is a
     fundamental flaw in the state machinery"

There was, and it is smaller and dumber than "split brain" suggests.

**What happened.** On a RADAR approach, a pilot read back a heading twelve
times — *"Left one four zero, two thousand five hundred, sockeye"*. The intent
classifier's own written instruction for `report_beacon` says *"ANY position,
altitude or progress report ... if he is telling you where he is or what he is
doing, it is this one"*, so a heading-and-altitude read-back matched. `dispatch`
was a flat `match intent.kind` — label straight to method — so it ran
`report_beacon`, which means *"reported over the approach beacon"*. That saw him
cleared, started the station-passage clock, and said:

> *"roger, station passage two plus three two, report field in sight or missed
> approach"*

Twelve times, on a procedure with no beacon, to a pilot with no receiver for one.

**The flaw is not the classifier.** Even a perfect one cannot help: nothing
between "what I think he said" and "act on it" asked whether the action EXISTS
in this procedure, at this phase, at this field. The engine's state was consulted
only inside the method, after it had been chosen and was committed to answering.

**The fix is one rule, not a table of special cases.** An action is reachable
when the procedure contains it and the aeroplane is somewhere it could be
performed. A beacon report is station passage: that exists on a letdown the
PILOT navigates, or for a controller with NO RADAR who has no other way of
learning where anybody is. On a vectored procedure with radar there is no
station to pass and his altitude is on the scope already.

**Unreachable is not an error and never a "say again"** — a read-back needs no
engine action and the agent answers it with "roger". It is logged, because the
last unlogged suppression repeated twelve times before anyone noticed.

**Why the talkdown has always been the good part**, and this is the general
lesson: it is pure geometry on a four-second clock and never asks what anybody
said, so a mis-heard sentence cannot tell it the wrong thing. The deterministic
engine should be driven by FACTS, not sentences. Radar gives it facts; a
classifier gives it a guess about words.

**What the mutation test showed** when the gate is removed: that same read-back
produces *"hold at five thousand, right turns"* — a HOLD — and an airborne taxi
request produces *"taxi to runway one three"*. Both were reachable before.

**Acceptance criteria**
1. ~~`report_beacon` never runs on a radar approach or an ILS.~~
2. ~~It still runs on the beacon letdown, and for any non-radar controller.~~
3. ~~Airborne-only actions cannot fire on the ground, and ground-only actions
   cannot fire airborne.~~
4. ~~Not knowing where he is never blocks anything.~~
5. ~~An aeroplane still reaches the board: `check_in` and `request_approach`
   are reachable airborne on every procedure.~~

---

## [ARCH-8] The state machine was written, complete, and unwired — #63
labels: architecture

**Status:** DONE 9 August. The foundation, not a fix.

    "think about ARCHITECTURE not quick fixes. Blocks are usually smells. This
     system is going to get much more complicated once we have this basic
     behavior addressed. We need solid foundation"

`phases.py` has held a complete and correct table since it was written: fifteen
phases, each declaring **who works him**, **what the geometry aims at**, and
**what may legally follow**. Its own docstring says it exists so that "nobody
has to remember which" and to stop "three different ideas of what is happening
getting loose".

**Two modules read it** — the comms kneeboard page and `handoff.py`. Not the
controller, not the geometry, not the reply composition.

**Five of the fifteen phases were ever set**, all by ground intents. Nothing
ever set `enroute`, `arrival`, `holding`, `approach`, `missed` or `landed`, so
an aeroplane's phase froze on `"departure"` the moment it rotated.

**And `phases.guide` — a dispatcher written to fly the phase he is in and return
None for the ones we do not fly — had never been called by anything.**
`settle` called the arrival's geometry directly, for every aeroplane, in every
phase. So an F-16 one mile off Kobuleti at 950 ft and 403 knots, climbing away
on runway heading, was told *"he has gone around, one miles. Missed approach:
fly heading 330, climb 3000."* The arithmetic was right; the question was wrong,
and nothing in the code was able to notice.

That is why the guards exist. Every one of them — `strip_unauthorised_handoff`,
`hush_a_second_talkdown`, the vector holds, `reconcile`'s suppressions — is a
referee deleting output that should never have been produced, because nothing
asked whose turn it was first.

**What was added is the missing half:** `phases.derive` computes the phase from
FACTS — the sim's on-ground flag, the arrival engine's own clearance state
(authoritative because it is what issued the clearance), and who is working him.
Illegal transitions are refused against `follows` and the current phase kept.
`settle` now asks the dispatcher instead of the arrival geometry.

**Two corrections to the table**, both making it tell the truth about code that
already existed:

* `arrival` was declared with no handler while `asr.guide` had been flying it
  all along — the "vectoring, twenty three miles, turn right" calls are that
  phase, and they happen long before anybody is cleared.
* `departure` followed only `enroute`. The sortie this system flies is
  twenty-four miles; on a hop that short Departure hands straight to Approach
  and there is no enroute segment at all, so the transition was being refused
  as illegal.

**Acceptance criteria**
1. ~~A departing aircraft is never given the arrival's geometry.~~
2. ~~An aircraft being vectored towards the final still gets guidance, before
   any clearance.~~
3. ~~The phase advances from facts rather than from what anybody said.~~
4. ~~An illegal transition is refused and the current phase kept.~~
5. Every producer consults the phase. **PARTLY** — the geometry does; the reply
   composition and the authority to issue a clearance do not yet (#64).

---

## [PHR-3] The canned replies were from a prior generation — #64
labels: bug

**Status:** DONE 9 August.

    "Batumi ground seems to be from a prior generation.. Not using callsigns,
     mispronouncing my callsign"

It was. `simple_response` — the zero-latency path for radio checks and closing
calls — predates GUID identity and never learned about it. It dug a callsign out
of the WORDS with a regex, which is the mistake the rest of the system spent a
fortnight removing:

    "Batumi Ground, sockeye just off runway one three, request taxi"
        -> "Runway one three, roger, welcome, taxi to parking..."
    "...will exit the runway when able, and I will contact ground"
        -> "The one, roger, welcome, taxi to parking..."

Closing calls are exactly what lands in this path, so Ground and Tower are where
it showed — which is why one seat sounded a generation behind the others.

It is handed `known` now. The regex stays only for a radio the bridge has not
identified at all, which is the one case where the words are all there is.

**Still open, and the reason this is a bypass rather than a feature:** the canned
path skips the agent, the engine, the phase and the role entirely. It is a block
around the whole system, and blocks are smells. It survives for now because a
radio check genuinely needs no model — but anything with substance must not come
back through it.

---

## [SEP-2] Ground cleared an aircraft for take-off, and argued about it — #65
labels: bug, needs-flight-test

**Status:** CLOSED 9 August; awaiting the flight. Card row **Q5** is the check.

    ATC:   Sockeye, Kobuleti Ground, cleared for takeoff runway zero seven.
    PILOT: you are not authorized to clear for departure
    ATC:   negative ... there is no separate tower here, I am also your tower,
           cleared for takeoff runway zero seven
    ATC:   negative, Kobuleti has no separate tower, I am Ground and Tower both
           on one two one decimal eight

The card says this is the most serious finding it can record: *"Ground owning the
runway is the one thing on an aerodrome that must not be shared."* Two separate
faults produced it.

**The brief never said what a seat does NOT own.** Kobuleti Ground's `also` is
empty and the `YOUR FIELD` block lists Kobuleti Tower on 133.000, so both facts
were in front of the model. Every block told it what it IS; none told it what it
is NOT, and it reasoned its way into the gap and then defended the position.
There is a `NOT YOURS: THE RUNWAY` block now, read off the station table so a
field that genuinely folds Tower onto Ground says the opposite from the same
code. Scoped to the ground seats: on a GCA the radar controller relays Tower's
landing clearance rather than sending a man in cloud to another radio, and that
procedure must survive.

**And the engine got it right and a guard deleted it — three times.**

    CONTROLLER: Sockeye, Take-off is Tower's, contact Kobuleti Tower one three
                three decimal zero.
    .. refused an unauthorised handoff: <that sentence>
    .. NOT VOICED [refuse] one three three decimal zero, Kobuleti Tower

`strip_unauthorised_handoff` removes any "contact somebody" the bridge did not
authorise — correct for a handoff the MODEL invented, exactly wrong for one the
ENGINE decided. A refusal IS a redirect and is authorised by definition, and
`_not_mine` already emits a `refuse` Decision carrying the station and the
frequency, so the authorisation was sitting unused in the decision the whole
time. It is read now.

That is the shape of every guard in this file: a referee deleting output rather
than a rule preventing it — see #63.

**Acceptance criteria**
1. Ground refuses a take-off request and names Tower's frequency.
2. The refusal actually reaches the air.
3. Ground does not agree it is also Tower when challenged.
4. A field whose Ground genuinely also works Tower still clears take-offs.
5. The GCA relay is unaffected: Approach still passes the landing clearance on
   its own frequency.

---

## [PHR-4] The check-in greeting was one sentence for every seat — #66
labels: bug, needs-flight-test

**Status:** CLOSED 9 August; awaiting the flight.

    "why would it ask for the field in sight, and why would it be asking for
     information alpha at this field"

He had lifted off Kobuleti ninety seconds earlier. Kobuleti Departure answered
with the ARRIVAL greeting — report the field in sight, advise you have
information Alpha, say your request — five times across the sortie, including
from Georgia Center thirty miles out.

**The seat is not what tells the two jobs apart.** Kobuleti Departure carries
`also=("approach",)`, correctly, because it works Kobuleti's arrivals too — so
`_owns("approach")` was true for a climbing aircraft. One controller frequently
works both ends: Batumi Approach also works its departures.

The PHASE tells them apart, and `phases.py` has said so since it was written —
`owner_of("arrival")` is approach, `owner_of("departure")` is departure. It
could not be asked until #63 made the phase real.

Also out: the ATIS question. A pilot climbing out on a clearance he read back
four minutes ago has already said what he wants, and the information he needs is
the one at the field he is going TO. Approach and Clearance ask; Departure and
Center do not.

**Acceptance criteria**
1. A departing aircraft is greeted with "radar contact" and nothing about the
   field or the letter.
2. The same seat working an ARRIVAL still asks — that half must not be lost.
3. Center does not ask a man thirty miles out to report the field in sight.
4. A voice out of nowhere with no phase is still treated as arriving, which is
   what every sortie looked like before the ladder grew a ground half.

---

## [OPS-5] Frequencies are looked up, not carried — #67
labels: architecture

**Status:** DONE 9 August.

    "giving the agent a tool to look up ANY frequency on demand is more
     scalable and we dont need to waste tokens on every call"

`look_up_frequency(place, position)` on the director. The axis is not "prompt
versus tool" in general: a controller works ONE aerodrome, so his own field's
handful of lines is cheap and constant and stays in the brief — he knows his own
tower the way he knows his own name, and a round trip for the commonest question
there is would be latency for nothing. Everywhere ELSE is unbounded: thirty
fields at four to eight seats each is two hundred lines carried on every
transmission of every sortie to answer a question a pilot asks twice a night.

It removes a failure as well as tokens. Asked for a frequency it had not been
given, the controller invented one — confidently, in correct phraseology, with a
plausible number. The tool answers from the station list the bridge already
publishes into `approaches`, so it cannot drift from `route.py`, and it says
outright when a position does not exist: *"There is no Vaziani position on the
published list... do not offer a number."* An empty result would invite the
model to fill the silence itself, which is the failure being removed.

Same bargain as `vector`: an exact answer is available, so an estimate is never
acceptable.

---

## [FP-6] The clearance was assigned and no later controller was told — #68
labels: bug

**Status:** DONE 9 August.

    "is the flight plan assignment working? I ask clearance for off to batumi
     but I don't think anything is happening with that"

**It was working, completely.** A pilot asks Clearance for "Domino"; the plan is
matched from his own words, COPIED into `assigned_plans` against his flight,
denormalised onto `flights`, joined into `flight_state`, and stamped when he
reads it back. The 9 August sortie has the row: flight 780, Domino, Kobuleti to
Batumi, 5,000 ft, acknowledged at 20:48:52. Every field populated and correct.

And `flight_strip` — the one thing that tells the next controller what he has
inherited — read **none** of them. Not the plan, not the route, not the cruise
level, not whether it had been acknowledged. So Departure, Center and Approach
each met a man with a filed route and a cleared altitude and asked him what he
wanted:

> *"I had an IFR flight plan open and now they're asking for my intent."*

Which is the same shape as everything else this week — #63, #58, #52 — the data
exists, is correct, and nothing reads it.

**Two things went with it.** `flights` kept the plan's KEY and not its LABEL, so
a strip could either read `362nd-kobuleti-batumi` aloud or say nothing; the
spoken label is denormalised now beside the route and the level, for the same
reason those are — relabelling a template later must not retrospectively change
what somebody was cleared on.

And a latent crash: `f.get("claimed_size", 1) and f["claimed_size"]` made the
guard truthy from the default and then subscripted a missing key. The strip is
composed on every transmission, so that took the whole turn down for any row
without a size.

**Acceptance criteria**
1. ~~The strip names the plan by the label the pilot said.~~
2. ~~It carries the route and the cruise level.~~
3. ~~It distinguishes a clearance read back from one that was not.~~
4. ~~A flight with no plan reads as it always did.~~

---

## [OPS-6] Audit for the thing that exists and nothing uses — #69
labels: architecture

**Status:** DONE 9 August. `tools/unwired.py`, in `check.py`.

    "So that problem -- where we have a system and nothing is using it... that's
     happened several times. Is this something you can audit for?"

It has happened at least six times and it is the dominant failure mode of this
project. Not bugs in what was written — the written thing is usually correct —
but a correct thing no path reaches:

| what | what it cost |
|---|---|
| `phases.guide` | a dispatcher written to fly the phase he is in; the arrival's geometry was called directly instead, and a departing F-16 was told he had gone around (#63) |
| `Controller._me` | read in six places, assigned in none — so Kobuleti Tower cleared a take-off on Batumi's runway (#58) |
| `flight_strip` | the plan, route and level were assigned, stored and joined; the strip read none of them (#68) |
| `phrasebook.render` | built, tested, never wired — and the tests made it look alive |
| `kneeboard/plans.py` | a page a pilot needs, with no tab (#56) |
| `AtcCapability.era` | declared, never consulted, and the code says so in a comment |

**Four shapes, all detectable:** a function nothing calls; an attribute read but
never assigned; something only its own TESTS call; a module nothing imports.

**What it cannot do, stated plainly.** It cannot tell whether a thing is called
on the path that MATTERS. `asr.guide` was called constantly, by the wrong
caller — no static pass finds that, only a sortie does. And a METHOD cannot be
qualified (`ctl.get()` — `ctl` is an object, not a module), so methods are judged
on their bare name and get false negatives. Module-level functions get the strong
answer.

**Proved against the real bugs rather than asserted.** Reintroduce the two
historical faults into a copy of the tree and it names both:

    DEFINED AND NOTHING CALLS IT
      phases:guide          function  src/marshall/atc/phases.py:185
    READ BUT NEVER ASSIGNED
      _me                   attribute

**Keyed on `module:name`, always.** Bare names cannot answer this: `guide` is
defined in both `asr.py` and `phases.py`, and keyed on the bare name whichever
file sorted first owned the answer while the other was invisible.

**Baselined**, like the approach sweep, because a public helper and a framework
entry point look unused and are not — 75 known today. It fails only on something
NEW, since a check that is always red is a check nobody reads.

---

## [ARCH-9] A second map: Nellis and Tonopah — #70
labels: architecture

**Status:** CLOSED AND MISSION DONE 9 August. Not yet flown; two surveys
outstanding.

    "How well do you think this system is going to transport to a totally
     different map and field? ... There had not been anything in code that locks
     it into caucuses"

**Measured rather than assumed.** Stripping comments and docstrings, twenty-nine
CODE references to a Caucasus place survive outside the data modules — and
twenty-four are kneeboard PROSE, page titles and briefing text with "Batumi"
written into them. The architecture is already field-parameterised because
adding Kobuleti forced it to be; what is genuinely map-bound is data.

**NTTR installed** on the server (`NEVADA_terrain`), and `core/nevada.py` holds
Nellis (KLSV) and Tonopah Test Range (KTNX) — fields, stations, fixes and an ILS
to each. **Every number comes from the sim's own `Beacons.lua` and `Radio.lua`,
cross-checked against the published plate, and the two agree:** DCS models
Nellis Tower on 132.550 and that is the real Tower frequency; the localiser
antenna bearings reproduce the published courses once you remember the antenna
points back up the approach.

**Three things the second map found that the first could not.**

1. **Magnetic variation is per FIELD, not per theatre.** Nellis 12E, Tonopah
   16E — four degrees apart on one map. `units.MAGVAR` was one constant and
   `geo.GRID_CONVERGENCE_DEG` carried a comment saying it "belongs to the FIELD
   ... here as a default until the airfield table exists". The table has existed
   since Kobuleti. It lives on `Field_` now, defaulting to the theatre so
   nothing that exists today moves.
2. **`PRESET_LADDER` names Caucasus stations**, so every Nellis controller fell
   into the leftovers and the comms card came out in list order — the same
   inaudibility as a dropped rung, reached from the other side. A theatre's
   station list is already written in the order the buttons are pressed, so it
   IS the ladder when none of the Caucasus rungs apply.
3. **`ends[0]` must be the end whose heading is `runway`.** Written the other
   way round, Nellis named runway 03 with the wind from 210 — the downwind end
   of its own ILS runway, which is precisely the fault that put a Kobuleti
   departure on 25 in a 090 wind. Now guarded across all four fields.

And the runway designators prove `Field_.ends`'s original point on a second map:
Tonopah is painted **15/33** and its heading is **141**, which rounds to 14. A
first draft of the test asserted the designator could be derived from the
heading — the exact derivation this codebase exists to warn against.

**Mission:** `marshall.mission.nevada` — F-16s **hot in parking** at Nellis,
comms ladder on the VHF box, DTC steerpoints to TPH and Tonopah, wind 210 so
both ILS ends are in use. A separate builder from the 362nd's 1944 sortie on
purpose; they share `channels_for`, `set_channels` and `write_presets` and
nothing else.

**Both surveys DONE 10 August**, and the numbers are the argument for having
run them rather than borrowing:

* **MVA**, from `land.getHeight` over a polar grid — the same heightmap the
  aeroplane hits. Nellis: 48 cells, 3,000–10,500 ft, with 2,000 ft under the
  approach and 9,416 ft twenty-five miles north-west. Tonopah: 48 cells and
  **nothing below 6,500 ft anywhere** — a controller there manoeuvres above
  Batumi's highest terrain all the time. Batumi's cells here would not have been
  conservative, they would have been fiction: its high ground is south-east and
  its low ground is the sea.
* **Grid convergence**, from the sim's own `coord.LOtoLL`: Nellis +1.16,
  Tonopah +0.13. **Cross-checked**, which is what makes them trustworthy rather
  than merely produced — convergence is `(λ − λ₀)·sin φ`, so each field implies
  a central meridian, and two fields 120 nm apart both give **−117.0**. Batumi's
  single recorded value never had that check available.

`tools/survey_terrain.py` had `field = R.BATUMI` hardcoded, so the one tool that
turns terrain into a vectoring minimum could only ever answer for the field it
was written at — the same shape as every other bug since this grew a second
aerodrome. It takes `--field` now, resolved across both maps.

**Also open:** SIDs, STARs and the remaining instrument procedures are not
modelled — only the ILS to one end of each field. Nellis has parallel runways
(03L/21R, 03R/21L) and `Field_` models one pair; the ILS is on 21L, so that is
the pair described. A parallel-runway field wants an L/R designator on the end.

---

## [KB-3] A kneeboard page is a function of a Card — #71
labels: architecture

**Status:** CLOSED MOOT 13 August — answered by deletion rather than migration. Five of the six pages named in its remaining scope are gone (`69ce4dc`); `site` survives as the renderer this issue put out of scope. The complaint that opened it — "hard coding batumi stuff isn't cool" — is answered, because there are no theatre-specific pages left to hard-code into. A real resolution of the concern, and not the one this issue proposed, so MOOT rather than FIXED.
same pattern.

**Remaining scope (10 Aug).** The Card, theatre-aware `comms` and the Nevada
hold behaviour are done. What is left is exactly six page migrations:
`navlog`, `asr_plate`, `aip_plate`, `e6b`, `brief`, `site`. The diag and
flight-test pages are deliberately out of scope — they are good as they are.

    "1) Ww2 is a feature, not the purpose. 2) There are aspects of the kneeboard
     eventually that will be pilot specific... 3) we're going to need a dynamic
     kb system eventually... but hard coding batumi stuff isn't cool"

**The problem, measured.** Seven of the nine pages take a `profile` argument and
then read the theatre out of module constants anyway — so the parameter chooses
the approach and the module chooses the map. `navlog.py` reaches ten and takes
no profile at all. That is why **24 of the 29 surviving Caucasus code references
in this system are kneeboard prose**: a page cannot be pointed at another field,
it has to be rewritten.

**`kneeboard/card.py`** holds everything a page may read — theatre, fields,
departure and arrival, stations, profile, wind — and pages take it as an
argument. Nothing they read is a module constant.

The deferred half is **declared rather than left to be discovered**: `pilot` and
`plan` are on the Card and empty. A per-pilot page is that field being filled
in, not a new mechanism; a planned-flight dashboard is `plan`, which
`flight_state` already joins and `assembly.flight_strip` already reads.

**WW2 stays a feature, not the frame.** Some pages genuinely ARE the 1944 sortie
— the beacon plate, the strike route map, the squadron brief — and those remain
Caucasus on purpose and say so. What must not happen is a page that means to be
general and is accidentally specific.

**Two real bugs fell out of converting the first page.**

1. The comms ladder intersected `route.PRESET_LADDER`, which names Caucasus
   stations — so a Nevada card came out **empty**. A comms page with no
   frequencies is the inaudibility failure that file's docstring is about,
   reached from a third direction.
2. **`hold_top_ft` defaults to 10,000 ft** — *"P-51: oxygen, not airspace"*.
   Tonopah's stack starts at 12,000, and `stack_ft` is `range(base, top + 1)`,
   so it was an **empty list**: a controller with no level to give and
   `_free_slot` returning None to the first arrival. Nellis's own survey reaches
   10,500 ft, above the default ceiling — a holding level below the terrain.

**Acceptance criteria**
1. ~~A page renders correctly for a theatre it was not written for.~~
2. ~~Its prose follows the theatre, not just its data.~~ Correct frequencies
   under the wrong airport's title is worse than a failure.
3. ~~Every approach can actually hold somebody.~~
4. The remaining pages take a Card. **OPEN** — `navlog`, `asr_plate`,
   `aip_plate`, `e6b`, `brief`, `site`.

---

## [ARCH-10] The bridge is started with a map, and the sim confirms it — #72
labels: architecture

**Status:** DONE 10 August. Live on Nevada.

    "Tell me what you mean that the bridge runs Caucasus profile."

One line: `profile = load_and_push_plate(R.BATUMI_ASR)`. That object is not
merely an arrival — it carries the STATION LIST, so it decides which frequencies
the ear opens and who `station_on` says is speaking. Beside it the ATIS served
`R.FIELDS` and the bootstrap wrote a Kobuleti-to-Batumi plan.

So on the Nevada mission the bridge was deaf, and in one place wrong:

| | |
|---|---|
| Nellis Clearance 120.900 | nobody listening on it |
| **121.800** | reaches **Kobuleti Ground** — the one frequency the two maps share |
| ATIS | Batumi and Kobuleti weather on 127.100/127.400 |

The middle one is the shape this project keeps meeting: not silence, but a real
controller at a real field answering confidently for the wrong airport.

`core/theatre.py` is the selection, made once. The bridge takes its approach,
fields, stations and bootstrap plan from it; the kneeboard Card builds from it.
Started with `--theatre nevada`, never inherited.

**Should it come from the sim?** In principle yes — it is this project's own
rule. In practice `env.mission.theatre` is not exposed to the mission scripting
environment, and `GetMissionName` is a filename convention rather than a fact
about the terrain. So **the flag chooses and the sim confirms**: a field the
theatre claims to own is converted through `coord.LOtoLL` and checked against
where that field really is. A wrong theatre is not subtle — Batumi's metres on
the Nevada map return 36.29 N, 107.98 W, about 150° from Batumi.

**Two things I got wrong on the way, both left written down.** I recorded that
`coord.LOtoLL` HANGS on off-map coordinates and built the check around treating
a timeout as proof. It does not hang; it answers instantly and wrongly, which is
far more useful. The hangs were the sim's Eval service being unreachable at all —
`return "hello"` timed out identically — because a freshly restarted server has
not started its scripting environment. **A conclusion drawn while one component
was down and attributed to the component being measured.** So a timeout is now
"could not check" and only a real answer in the wrong place is a refusal.

Nevada plan filed as **Silverstate** (migration 022), cruise 24,000 — chosen
against the surveyed minima, not for roundness: Tonopah's vectoring cells reach
10,500 and its stack starts at 12,000, so the Caucasus levels of three to eleven
thousand would be inside the terrain.

---

## [OPS-7] A paused sim is the quietest failure we have, and nothing could unpause it — #73
labels: architecture, tooling

**Status:** DONE 10 August. Verified against the live server, paused and running.

    "Joining the server doesn't unpause it. We've experienced this before."

Correct on both counts, and the repo knew and could not act. `deploy_mission.sh`
ended by PRINTING `now unpause: it boots paused (pause_on_load), and AI tasking
is frozen until you do` — a true fact, addressed to a human, with no command
beside it. `SetPaused` had been in the vendored proto the entire time. The same
shape as every other unwired system here: a correct thing nothing reaches.

**Why joining does not help.** `serverSettings.lua` has `pause_on_load = true`
and `pause_without_clients = false`. So it boots paused, it does *not* pause
when empty, and a client arriving clears nothing. Only `SetPaused(false)` does.

**Why it is so hard to see.** There are two Eval services and only one stops:

| service | Lua state | paused |
|---|---|---|
| `HookService.Eval` | `DCS`, `net`, `Export` | **answers** |
| `CustomService.Eval` | `coord`, `timer`, `world` | **hangs to the deadline** |

Measured both ways on the live server. So a paused server answers
`GetMissionName`, answers `GetPaused`, logs healthy — and silently fails every
question Marshall actually asks, because `theatre.verify` and the ATIS weather
observation both run mission Lua.

**I misdiagnosed this twice**, and the second one shipped in #72's commit
message. First as `coord.LOtoLL` hanging on off-map coordinates. Then as "a
freshly restarted server has not started its scripting environment yet" — vague,
unactionable, and wrong. It had started. It was paused, which has a fix.

**What landed**

- `feed/dcs.py` — `is_paused`, `set_paused`, `mission_lua_ready`, `unpause_sim`.
- `tools/sim.py` — `status` / `unpause` / `pause`. `status` exits non-zero when
  mission Lua is silent and says *why*, distinguishing paused from unreachable.
- `deploy_mission.sh` unpauses instead of advising it.
- `theatre.verify` takes an injected `is_paused` (it is `core`; `feed` is above
  it) and its timeout message now names the cause and the command.
- The bridge prints a loud banner if it comes up against a paused sim.

**Two real bugs found while building it, both by the new tests:**

1. **`SetPaused` returns before the state changes.** The first `set_paused` read
   `GetPaused` in the next breath and reported *"sim is now PAUSED"* having just
   successfully unpaused the server. A verify that runs before the thing it
   verifies reports failure on success, which teaches the next reader to
   distrust the check instead of the state. It polls to a deadline now.
2. **`theatre.verify` did not honour its own timeout.** It used a
   `ThreadPoolExecutor` in a `with` block, and the block's exit calls
   `shutdown(wait=True)` — so having given up at 8 s it then blocked until the
   abandoned call hit the 25 s gRPC deadline. A 25 s stall on every bridge start
   against a paused sim. Now a daemon thread that is abandoned, not awaited:
   8.0 s measured. The test suite caught it by PASSING and taking two minutes.

**And one latent bug in shared machinery.** `feed/stubs.bind()` rebound `dcs`
to the vendored stubs but left pydcs's already-imported CHILDREN cached, so
`import dcs.coalition.v0` found a module where a package was wanted. Invisible
in production — the mission builder and the bridge are different programs — and
fatal in the test suite, where both run in one interpreter. It surfaced because
this is the first test to cover `feed/dcs.py` at all: passing alone, failing in
the full run. `bind()` now evicts the submodules too.

**Regression:** `tests/test_paused.py`, 12 cases, no sim or network. It pins the
*reasoning* — that a timeout is blamed on a pause when the sim says paused and
explicitly not on the map — plus the wall clock, which is the only thing that
catches fault 2.

---

## [OPS-9] Codex audit, 10 August — an outside reading of the tree — #75
labels: architecture

**Status:** DONE 10 August, except the deferred half of [OPS-8].

An external audit (`CODEX_FINDINGS.md`) reviewed the docs against the tree. Five
findings; **all five verified against the code, none spurious**. The one that
mattered had escaped every one of our own checks.

**1. HIGH, and correct — a fix that went to one call site and not its siblings.**
On 1 August `seen` was switched from asking the scope by callsign to asking by
TRACK, because `radar_fix` needs a bracketed tag and a manned contact is labelled
by player name. Its three siblings were left asking by callsign: the `fix` that
seeds the engine, the airframe lookup, and the ground check. So an identified but
untagged contact came out in the state worse than either half —

    seen = True     `may_be_sequenced` treats him as a radar arrival
    fix  = None     and the seed saying "he is already on final" never runs

— and an aeroplane established on the approach is filed as a new arrival and
**stacked**, which is exactly what the radar seed exists to prevent. Equipment
failed in the same case, and an unknown airframe falls back to "assume modern".

Fixed: one lookup, track first, and everything downstream reads it.
`tests/test_untagged_final.py` — verified to FAIL on the pre-fix code. No
existing test caught it because every scope fixture in the suite carries a
*tagged* contact, and untagged-but-tracked is the state every pilot is in for
the first seconds of every sortie.

**2. HIGH, partly — Postgres and the agent published on all interfaces.** True.
`"5432:5432"` binds 0.0.0.0 while the comment beside it claimed "bound to the
LAN" — the prose was the thing that was wrong, and nothing enforced it. Postgres
is now `127.0.0.1:5432:5432`; the only host process needing it is the bridge,
which already dials `localhost`, and the director container uses `db:5432` on
the compose network. Verified refused from the LAN and still readable by the
bridge. The agent port is [OPS-8].

*That change broke the radio for about a minute*, which is the lesson worth
keeping: `bridge.py::_compose_dsn` matched `"(\d+):5432"`, a bind address made it
stop matching, and the bridge would have come up with **no Postgres at all** — no
ATIS letter, no runway in use, no board, and no symptom but `PUBLISH FAILED` on
every recording. Pattern widened, and pinned by a test that reads the real
compose file.

**3. MEDIUM, and fair — the local gate was network-dependent.** `issue_sync`
called `sys.exit` on a `gh` failure, so no token meant a red check. Worse, it
*masked* the real result: this check is genuinely failing on card/issue drift
(#60), and an auth error in the same red was indistinguishable from a firewall.
It exits **2** now, which `check.py` already reads as SKIP and reports by name.
Verified both ways: without a token it SKIPs and says why; with one it still
FAILs on the real drift.

The broader ask — `--unit` vs `--release` modes — is **declined for now**.
`check.py` already prints every skip with what it leaves unguarded and says
"Skipped is not passed"; a second mode would add a way to run the gate that
looks stricter without changing what is actually verified. Revisit when there is
CI, which is the only place the distinction earns its keep.

**4. MEDIUM, already tracked** — `agent_atc.py` at ~4,950 lines with untestable
nested loop functions. Accurate, and it is #55.

**5. MEDIUM, and all four examples correct** — doc drift. `/chat` vs `/atc` in
DESIGN and the module docstring (the bridge has used `/atc` since the two-tier
router); README calling the voice stack "next" when it has been flying for
weeks; `SCHEMA.md` presenting an unapplied proposal with no marker; WIRING
describing the prompt-cache scar that `app.py` closed on 29 July. All four
corrected, with SCHEMA.md given a prominent SUPERSEDED banner rather than being
deleted — the argument in it is still the reason the second and third airfields
were cheap.

**What this says about our own checks.** `tools/unwired.py` looks for things
nothing reaches; nothing looks for a fix applied to one of several call sites
that should have moved together. That is the shape of finding 1, of the `_me`
bug, and of the two-fields lesson. Worth a check of its own — filed as #76.

---

## [HO-3] Nothing hands a landed aircraft to Batumi Ground — #77
labels: bug, needs-flight-test

**Status:** FIXED 13 August, needs the next sortie. Half of it went with
[SEP-5] / #88 on 10 August — the phase branch that hands a parked aeroplane over
could not run while he was on the ground — and that left the rung reachable but
still entered by the PILOT asking for a stand, which is criterion 1 unmet: he
had to speak to advance the last rung of his own sortie.

**What closed it is a sentence, not a mechanism.**

    "We can just have tower say something like -- 'sockeye, batumi tower,
     welcome, exit runway and contact ground' once it's on the ground"

`Controller.report_down` already fires off the radar poll with no pilot in it,
already says *"welcome, exit the runway when able"*, and now names Ground and
his frequency in the same breath and moves the phase to `taxi_in` with it. The
words and the rung are decided in one place from one lookup, because a handoff
spoken by one authority and booked by another is two answers to one question
(#115).

**The design that was NOT built, and why it is worth writing down.** The
obvious reading of criterion 1 is to watch him VACATE and hand him over
afterwards, and there is no honest observable for it. An aerodrome row carries a
position, an elevation, a landing heading and the runway designators — no
threshold coordinates and no length — so "clear of the strip" reduces to a
threshold over a cross-track measured from a reference point that is only
approximately on the centreline. Tuned generously it is a handoff that never
comes for a man who parks near the runway line; tuned tightly it is Tower
releasing an aeroplane still rolling on the active, which is the invariant this
engine exists to hold. A real tower does not wait for any of that: the frequency
change goes out during the roll-out. Deleting the question beat answering it.

    F5. After landing and clearing the runway, wait. Say nothing.
        Nothing hands you to Batumi Ground.

The seat works: taxi in on 121.900 and a real controller answers as Batumi
Ground. What is missing is the rule that SENDS you there. `phases.py` gives
`landed` to Tower, so preset 8 has a live controller on it that nothing ever
hands you to — and in the air a preset nobody hands you to is indistinguishable
from having been forgotten.

**Why it is not merely cosmetic.** The whole point of the eight-rung ladder is
that every rung can be both left and reached; #51 closed the two Center gaps on
exactly that argument. This is the last one, and it is at the end of the sortie
where a pilot is least able to tell "the system dropped me" from "I missed a
call".

**Ground transitions are not geometry**, which is what makes this cheap: a phase
with no volume is owned outright by the controller `phases.py` names, so moving
into it IS the handoff. It needed no new rule row in the end — `taxi_in` is
already Ground's phase and already has no successor, so the landing simply moves
him onto it.

**Acceptance criteria**
1. After landing and clearing, the pilot is handed to Batumi Ground with the
   frequency, unprompted, with no request. **MET, and by a test rather than a
   claim** — `TowerGivesHimGroundOnTheRollOut` in
   `tests/test_ground_procedure.py` lands an aeroplane, dispatches no intent at
   all, and asserts the name, the spoken frequency and the rung.
2. It is the ARRIVAL field's Ground — not Kobuleti's, which is the failure mode
   two aerodromes made reachable. **MET**: `test_it_is_the_ARRIVAL_fields_ground`
   lands under each Tower in turn, and the other field's ground frequency is
   asserted absent as well as the right one present.
3. ~~`tests/test_handoff_rules.py` covers it~~ — it does not, and that is
   correct rather than a shortfall. The transition is phase ownership and not a
   rule row, so the coverage lives beside the other ground transitions in
   `test_ground_procedure.py`; the structural test that every rule reads the
   trend is untouched and still passes.
4. Card row F5 stops describing a known gap and becomes an ordinary check.
   **MET** — F5 and F5b are rewritten, and the preamble note warning that the
   card and the design disagreed is gone.
5. **AND #100 IS NOT REVERTED.** Its three criteria are asserted from the far
   side of the new trigger: nothing hands him on once he is with Ground, Ground
   still owns the parking instruction when he arrives already on `taxi_in`, and
   `taxi_in` still has no successor.

---

## [OPS-10] The documentation was deep, and unsafe to onboard from — #78
labels: architecture, tooling

**Status:** DONE 10 August.

    "it is not yet safe as a new-agent onboarding system ... it will spend too
     long deciding which document describes today versus history."

Correct, and the sharpest instance is the worst possible one. **`README.md` —
the first thing anybody reads — described the inverse of the architecture:**

> The controller is blind. No radar, no telemetry, no connection to the sim.
> The AI is ears and mouth, never the brain.

against `CLAUDE.md`'s opening line, *"Real ATC by default. A capable,
radar-equipped agent is the controller's brain."* Both true once; one left
standing for weeks after it stopped being. A new reader could form the wrong
model of the whole system and start changing things before reaching any document
that would correct them.

**What landed**

- **`docs/START_HERE.md`** — two pages, linked first from README and CLAUDE.md:
  what runs today, the invariant, where state lives, the deployables, the test
  tiers, the known limits, and **which document wins when two disagree** (code
  and executable config, then tests, then WIRING, then ISSUES' *Remaining
  scope*, then history).
- **`docs/RECIPES.md`** — the five cross-cutting changes: add a field, add an
  approach, add a kneeboard page, change a handoff or a controller decision,
  change a prompt. Each names the file that OWNS the fact, the trap that has
  already bitten there, what to run, and whether it puts a row on the card.
- **README's architecture section rewritten**, with the old text kept visible as
  a quote rather than quietly overwritten — a README that lies is the most
  expensive kind of stale document, and hiding the correction loses the lesson.
- **Every document under `docs/` declares a `Type:`** — current reference, work
  record, proposal, or historical debrief — plus what it was validated against.
  `STRUCTURE.md` is fenced as a proposal describing a layout we do not have.
- **`tools/docs_check.py`**, in `check.py`: every doc typed, every HTTP path in
  prose present in the source, every `python -m` and `tools/x.py` runnable,
  every relative link resolving.

**It found three real stale references immediately** — `WIRING.md` pointed at
`director/tools/{tracks,dcs,events}.py`, which moved into `src/marshall/feed/`
during the merge. Nine citations in the deepest reference document, resolving
nowhere.

**What it deliberately does not check is prose for truth.** "The controller is
blind" is four correct words about a system that changed underneath them, and no
checker was ever going to know. The typing rule is the answer instead: a
document that says what it is and when it was validated can be wrong, but it
cannot be *mistaken for current*.

**The two-copy rule for issues is now written down** (`START_HERE.md`), since it
was agreed and nowhere recorded: `ISSUES.md` is the source, GitHub is a
projection, never edit a body there, `--sync` publishes, and GitHub owns only
open/closed state.

---

## [SEAM-3] Every controller is handed every tool, and prose says who may use them — #81
labels: architecture

**Status:** DONE 10 August, verified against the running director.

`src/marshall/atc/agent/capability.py` maps a seat to what it may reach for, and
`build_agent` constructs the tool list from it. **What is absent cannot be
called** — the same argument that keeps an LLM out of separation: authority is
structural, not advisory.

| seat | gets |
|---|---|
| every controller | identify, vector, hooks, frequency, memory |
| clearance / delivery, or a seat that `also` works them | + clearance |
| **overlord (Sentry) only** | + spawn |

**A role is not one string.** Batumi Ground carries `also=("delivery",
"clearance")` and Kobuleti Departure `also=("approach",)` — a field this size
folds seats together, so a capability is granted if the primary role *or*
anything it also works qualifies. Reading the primary alone would disarm a
controller who genuinely does the job.

**Three things worth recording.**

*The seat comes from the FREQUENCY*, which is the one fact about a transmission
no pilot can influence — the same reason `station_on` decides who is speaking
rather than anything in the transcript. The bridge resolves it and sends it;
nothing in the message can change it.

*The agent cache had to be re-keyed.* One bridge monitors every frequency in the
theatre under **one** session id, so the role varies within a session. Caching
on the session alone would have handed Batumi Approach whatever tool set Sentry
was built with — reopening the leak through the cache. It is keyed on
`(session_id, role, also)` now; the session is still the session, so a shared
channel's conversation is unchanged.

*An unknown seat is not disarmed.* Empty role returns the full set, because a
capability system that silently took a tool away from a controller after a
lookup missed would be worse than none. Older bridges and direct calls behave
exactly as before.

**Verified live**, not only in tests — three POSTs to the running `/atc`:

    agent for captest-approach [approach: frequency, hooks, identify, memory, vector]
    agent for captest-overlord [overlord: frequency, hooks, identify, memory, spawn, vector]
    agent for captest-ground   [ground+clearance: clearance, frequency, hooks, identify, memory, vector]



`build_agent` gives one tool list to every session, `spawn_ground` included, and
the Overlord brief is what tells an approach controller not to put armour in a
valley. **Prose is not a permission system.** It costs tokens on every call to
describe capabilities the station may not use, and it relies on the model
obeying an instruction rather than on the capability being absent.

The station is known deterministically — the bridge resolves who is speaking
from the frequency before the call is made. That is the natural key for a tool
set.

**Acceptance criteria**
1. The tool list is constructed from the station's role, not shared.
2. An approach controller is not *given* `spawn_ground`; it is absent, not
   forbidden.
3. The role comes from the trusted side (the bridge), and cannot change within
   a session — or the session key includes it, so histories cannot cross roles.
4. A test asserts the tool set for each role.

---

## [SEAM-4] The board is advanced before anything asks whether the call was real — #82
labels: bug

**Status:** CLOSED.

`decide()` — which classifies and can advance the separation board — runs at
`agent_atc.py` line ~4694. The check for whether the transmission was a **debug
note to the project rather than a call to the controller** runs ~165 lines later
and then `continue`s.

**I could not make the board actually move**, and that is the finding rather
than a reassurance: two unrelated gates catch it first — the callsign must be
plausible against the transcript, and the action must be reachable in the
current procedure. Nothing about the debug check is what protects us. It is
protected by accident, which is precisely the shape of the four faults the
second aerodrome exposed.

The general rule the audit states is the right one: **a call that will be
rejected must be rejected before it can mutate state.**

**Acceptance criteria**
1. Debug notes, and any other transmission the loop will not answer, are
   recognised before `decide` runs.
2. A test proves a debug note cannot reach `intents.dispatch`, independent of
   the callsign and reachability gates — i.e. it still passes if those are
   disabled.
3. No other "reject after mutating" ordering remains in the receive loop.

---

## [KB-4] Two thirds of the flight test card never reached the cockpit — #85
labels: bug

**Status:** DONE 10 August.

    "Where will I find Q1–Q9 plus S10–S12 and H20–H21 -- they arent on the
     flighttest kneeboard"

They were not there, and neither was most of the rest. **Six pages of fifteen
and 47 rows of 120** were reaching the aeroplane. Two independent faults.

**1. The row pattern could not see a bold ID.** `_ROW` matched only a bare
`| H4 |`, so every section written since 2 August rendered **zero rows** — Q
(the two-aerodrome ladder, fifteen rows), R (ATIS), S (phraseology) and T (the
Kobuleti ILS). The card opens by telling a pilot to *fly Q first*.

This is **#60 exactly, in a second tool.** That issue fixed the identical
blindness in `tools/issue_sync.py`, which *reports* on the card — and nobody
looked at the page a pilot actually reads. One document, two tools, two
different ideas of what a row is.

**2. Eleven sections had no GUID**, and a section with no GUID is not published
at all: D, F, K, L, M, N, P, Q, R, S, T. The builder said so on every single
run — *"section Q has no GUID and will NOT appear on the kneeboard"* — into a
container start-up log that nobody reads. **A loud warning in a place nobody
looks is a silent one**, which is the same lesson as the frequency table and the
runway in use: being right in a log is not being reachable.

GUIDs are derived `uuid5` from a fixed namespace and the section letter rather
than rolled at random, so regenerating the table cannot hand a pilot a different
identifier for the same page and drop him somewhere he did not choose.

**A third thing, found on the way.** Section E's slice ran to end of file,
because it is the last *lettered* section and "Already flown, and kept as the
regression record" is not one — so twelve retired rows appeared on the page
whose whole job is telling a pilot what **not** to report. Sections stop at the
next heading of any kind now, and a struck row is skipped everywhere: striking
through is what retires a row from the cockpit list.

**Regression:** `tests/test_diag.py` — every section renders rows, every section
has a GUID and a tab label, no two share a GUID, row IDs carry no markup, and E
holds exactly its two rows.

---

## [SEP-3] A whole departure was flown on approach vectors — #86
labels: bug, needs-flight-test

**Status:** FIXED 10 August, needs the next sortie.

Ninety seconds after rotating off Kobuleti, climbing out for Batumi:

    ASR: he has gone around, two miles. Missed approach: fly heading 125,
         climb 3000.
    ASR: vectoring, nine miles. Turn left. Fly heading 250, maintain 3000.
    ATC: Sockeye, Kobuleti Departure, radar contact, turn left heading three
         zero five, maintain three thousand.

He was turned through six headings and **descended to two thousand while
climbing out to five**, thirty miles from either aerodrome, and he flew it —
the instructions were confident, in correct phraseology, and about the wrong
procedure at the wrong field. This is what the pilot reported as *"conflicting
instructions on the ASR approach"*.

**Two paths to one geometry, and only one of them gated.** `settle` asks
`flies_geometry(phase)` before calling `phases.guide`, and `departure` answers
False — so the structured guide was correctly `None`, exactly as designed. But
`decide` had already built the *prose* from `asr_context`, which calls
`asr.guide` directly and checks only three things: is the approach vectored, is
there a fix, is he on the ground. **No phase.** The prose is what goes into the
agent's prompt, so the gate that worked protected the half nobody hears.

And `reconcile` could not save it: it arbitrates only when there *is* a guide,
so `g is None` returned everything untouched — the ungated vectoring included.

The same shape as #76, a fix applied to one call site and not its sibling,
found by flying it rather than by reading it. Gated in `settle`, where the phase
is derived; asking `asr_context` to derive its own would be a second answer to
the question `settle` exists to settle.

---

## [SEP-4] Seven agents, one session, and a landing clearance lost — #87
labels: bug

**Status:** FIXED 10 August.

On short final at Batumi:

    CONTROLLER: Sockeye, roger, cleared to land runway one three, wind zero
                nine zero at six.
    !! agent error: HTTP Error 500: Internal Server Error
    ATC[pilot/sonnet] (0.0s): (no call)

The engine issued the landing clearance and **the pilot heard nothing.**

    psycopg.errors.UniqueViolation: duplicate key value violates unique
    constraint "session_messages_pkey"
    DETAIL: Key (session_id, agent_id, message_id)=(hooks, default, 38)
            already exists.

**Introduced by #81, hours earlier.** Keying the agent cache on the seat was
right — one bridge works every frequency under one session id, so the role
varies within a session. What I missed is that each of those agents then
constructed its own `PgSessionManager(session_id="hooks")` with its own message
counter. Seven agents were built for this sortie; sooner or later two of them
wrote message 38.

The conversation store is per seat now, which is also the more honest model:
Kobuleti Ground and Batumi Approach are different people, and a pilot's
conversation with one is not the other's to remember.

**Worth noting for #79:** the repair could not help here. A decided fact is
restored when the agent's reply omits it — but there was no reply at all, so
nothing was appended to. A total agent failure still loses the clearance, and
that is a different mechanism from the one built today.

---

## [SEP-5] Every ground handoff failed, and one `elif` did it — #88
labels: bug, needs-flight-test

**Status:** FIXED 10 August, needs the next sortie.

Three failures in one sortie, and in each the **agent proposed the right handoff
and the authorisation deleted it**:

    .. refused an unauthorised handoff: Sockeye, roger, holding short runway
       zero seven, contact Tower one three three decimal zero when ready.
    ATC: sockeye, Kobuleti Ground, go ahead.

| card | should have | did |
|---|---|---|
| Q3 | correct read-back hands Clearance → Ground | *"Readback correct."* and nothing |
| Q6 | holding short hands Ground → Tower | *"go ahead"* |
| F5 | landing hands Approach/Tower → Batumi Ground (#77) | *"go ahead"* |

**`next_controller` reads three kinds of evidence in order** — the sim's
events, the rule table, then the airspace volumes. The rule-table step holds the
PHASE branch, written specifically for the ground half of a sortie, whose own
comment reads:

> A parked aeroplane has no geometry to argue from, so without it Clearance,
> Ground and Tower can never let go of anybody.

It sat behind `elif`, on the far side of `if down: nxt = None`. **So the branch
written for aeroplanes that are parked ran only for aeroplanes that were
flying**, and the comment named precisely the aircraft that could never reach
it. The event guard is right — being down outranks an event — but it was
suppressing the one mechanism that works on the ground.

**Everything else was already correct.** `phases.py` has described
`clearance → taxi`, `taxi → holding_short` and `landed → taxi` since it was
written; `clearance_read_back`, `request_taxi`, `report_holding_short` and
`request_takeoff` all set the phase. Nothing could read it from the ground.

**Two more, found in the same place.** `report_down` set the separation enum
`Phase.LANDED` but not `sortie_phase`, so even with the branch reachable a
landed aeroplane had no phase to hand over on. And Tower's last transmission
ended *"taxi to parking"* —

    "Batumi Tower ... just gave me clearance to taxi to parking when that's
     ground's job"

Right, and it is the same fault as Ground clearing an aircraft for take-off, in
the other direction. Tower owns the runway; the taxiways are Ground's. He says
*"exit the runway when able"* and the phase hands him over.

**And the canned close-out was swallowing the call entirely.** *"Clear of the
active, request taxi to parking"* matched the closing-acknowledgement
short-circuit and got a canned *"taxi to parking when ready"* from whatever seat
was speaking — so the engine never saw it, the phase never moved, and nothing
ever handed him to Ground. A closing acknowledgement **asks for nothing**; a
request belongs to the engine, where `request_taxi` refuses it from Tower and
names Ground with the frequency.

---

## [SEAM-7] The engine could not hear a read-back, and could not check its own directive — #90
labels: bug, needs-flight-test

**Status:** FIXED 10 August, needs the next sortie.

**One more turn of the crank, 11 August.** Every piece worked in isolation --
the classifier returned `read_back`, the squawk was on the board, the verifier
judged the real wrong read-back correctly -- and the handoff still did not
happen, because they were **one turn out of step**. The clearance facts were
cached from the flight row *after* `decide` had run, and the clearance is
assigned by the agent's tool later still; so on the turn the clearance goes out
the row has no level and no squawk yet, the cache stays empty, and the read-back
on the very next transmission found nothing, returned `None`, and left the phase
alone.

    "after getting clearance, I did not get switched over to ground"

It reads the board directly now. One read on a path that already does several,
and the only version that cannot be a turn behind.

Two findings from one clearance-delivery exchange, and they are the same fault
seen from both ends of the seam.

**1. There is no `read_back` intent.** `Controller.clearance_read_back` has
existed since the ground procedure was written — its docstring calls a correct
read-back *"the transition, not the words"* — and **nothing on the radio path
could ever call it.** Only the tests did. `intents.py` names four ground intents
and says outright why they must exist: *"the CONVERSATION is the only thing that
can report them."* The read-back is the fifth and it was missing.

So a read-back was filed as a check-in. The controller answered *"advise you
have information Alpha"* to a man reciting a squawk, three times, and Delivery
could never finish with him:

    "Clearance did not hand me off to ground"

That is precisely the failure the same file already documents for holding short
— *"classified as check_in or unknown, so the controller heard 'somebody said
something' and the phase never moved"* — in the one transmission that happens on
every IFR flight.

**2. The ATIS advisory carried no `Decision`, so it could vanish.** The engine
asked for the information letter on three consecutive transmissions and the
agent dropped it every time, silently:

    "he never once said 'advise you have information alpha'"

#79 built the mechanism that catches exactly this, and the check-in path did not
use it: it composes prose, and only a `Decision` is verified. A directive the
engine issued can still disappear as long as it carries no decision.

**Judged by the same verifier, both directions.** `decision.verify` asks whether
every fact of a decision survived being spoken. A read-back is that question
with the speakers swapped, so it is the same function — not a model asked *"was
that correct?"*, which would answer confidently either way and decide whether an
aircraft changes controller.

**Which needed the clearance to be fully recorded.** `assigned_plans` held the
limit, route, level and approach — everything a pilot writes down except the
**squawk**, which was computed from the flight id when the words were composed
and then thrown away. Migration 023 stores it and puts it on `flight_state`,
because a fact that lives only in the copy is a fact nothing can reach. It
matters: on the sortie the level and the frequency were both read back right and
only the squawk was wrong, so **anything short of the whole clearance would have
called that read-back correct** and handed him on mid-correction.

`None` is not `False`. No clearance on the board means no judgement, and an
unjudged read-back leaves the phase exactly where it is.

---

## [SEP-7] A third path to the approach geometry, ungated — #92
labels: bug

**Status:** CLOSED 11 August.

**They did not merely repeat each other — they disagreed.** Same aircraft, same
moment, two altitudes:

    ATC[vec] ... turn right heading two four five, maintain three thousand
    ASR:     ... Fly heading 245, maintain 5500

Neither computation was wrong about its own instant. The monitor's came from its
radar poll and `asr_context`'s from the fix on the transmission, seconds and a
few hundred yards apart — and the vectoring altitude is range-dependent, so it
steps between them. **Asking the question twice was the fault**, not either
answer.

The engine owns the vector now, for the same reason it already owns the mile
calls: it can see, it is on a metronome, and it does not paraphrase. The agent
is told what is being transmitted rather than handed the turn to say —
the identical rule the `final` branch has stated since it was written, applied
one branch up.

Reported from the cockpit as *"I'm getting redundant instructions"*, *"he's
stepping on me a couple of times"* and *"we're in the 180 degree flipping
again"*.

#86 gated the ASR geometry on the phase in `settle`, because `asr_context`
reached `asr.guide` with no phase check and flew a departure on approach
vectors. **There is a third caller.** The proactive monitor calls
`asr.guide(pos, profile, ...)` directly, gated only on `may_be_vectored` —
nothing about the phase.

So on 10 August the pilot-path guidance was suppressed on every transmission
while the monitor went on transmitting vectors:

    .. ASR guidance suppressed: he is in the departure phase
    ATC[vec] Sockeye, turn right heading three zero five, maintain two thousand.
    ATC[pilot/sonnet]: Sockeye, negative, amend — turn left heading one six zero

A controller whose turn-by-turn guidance is switched off, still vectoring, with
nothing reconciling the two. The pilot reported the result: *"approach flipped
the heading almost 180 degrees a couple times."*

**Not fixed yet, deliberately.** Gating the monitor is the consistent answer —
one question asked the same way everywhere — but with [SEP-6] unresolved it
would make the controller go **silent** on an approach instead of erratic, which
is worse. The phase has to be trustworthy first.

`asr.guide` now has three callers and two of them have a phase gate. That is the
shape [ARCH-11]/#76 exists to find, three times over.

---

## [SEP-8] Cleared for an approach six seconds after take-off — #93
labels: bug, needs-flight-test

**Status:** FIXED 11 August. This is the cause of [SEP-6]; the diagnostic added
there found it on the first flight.

    .. sockeye is already on final per radar; not stacking him
    .. phase REFUSED: departure cannot lead to approach — he stays in departure

`separation_context` asked the **approach** geometry about an aeroplane at
**0.6 nm and 472 feet climbing off Kobuleti**. It answered about the numbers it
was handed, obligingly, and `seen_on_final` did the rest — that sets
`Phase.CLEARED` and hands him the letdown. `derive` then wanted `approach`;
`departure` cannot lead there; the transition was refused; and the phase stayed
welded to `departure` for the whole flight.

Everything the pilot reported downstream came from that one seeding: the
guidance suppressed on every transmission, and the vectors that reversed 140°
because only the ungated monitor was still talking ([SEP-7]).

**The fourth caller of `asr.guide`, and the only one that MUTATES.** #86 gated
two. This is the one that changes the engine, so an ungated question costs most
here.

**The real fault was ordering.** The phase was derived in `settle`, which runs
*after* `separation_context` — so the half of the turn that mutates ran before
anything had worked out what the aeroplane was doing. `phase_now` derives it
once, before anything acts, and `settle` reads the same answer instead of
recomputing it. One function, one answer, the same rule as `is_on_the_ground`.

**Not knowing is not the same as knowing he is departing.** An empty phase is
the case this seed was *built* for — a flight established on the final at ten
miles the engine has never heard of — so the gate refuses only a phase we
positively know does not fly the approach. Blocking on "no phase" would have
fixed this by reopening the original.

---

## [ATIS-2] The broadcast was stamped midnight, every time — #94
labels: bug

**Status:** FIXED 11 August.

    "ATIS always says 0,0,0,0,0 julium, and is always on alpha"

Which is *"time zero zero zero zero Zulu"* heard through Whisper, and a fair
transcription. The bridge passed `mission_clock=None` — it is **the only caller**
of a parameter written for exactly this — so `zulu(0)` stamped every recording
midnight.

The sim's own clock is the right source rather than this machine's: a mission
set at dawn on a server running at teatime is what makes the difference visible.
`timer.getAbsTime` answers in the mission's day. Zero on any failure, so a sim
that will not answer costs the timestamp and never the broadcast.

**Rotation was not broken; the letter never got old enough.**

    "its only ever been alpha and the mission has run for MANY hours. so
     rotation isnt working."

I had written that "always on alpha is correct, a static mission gives no
reason to turn" — **wrong**, and the pilot was right to push back. An hour of
age never accumulated because the BRIDGE kept being restarted, and every
restart built a fresh in-memory `Airwave`: no letter, no recorded-at, first
letter again, clock back to zero.

The durable half was in Postgres the whole time. The `atis` table has carried
`letter` and `recorded_at` since the ATIS was built — controllers read them so a
taxi clearance and the broadcast cannot name different runways — and **the
writer never read them back.** The same shape as every other unwired system
here, in the one place where the state is deliberately persisted.

`serve` seeds from the table on the way in now, converting the stored wall-clock
age into its injected clock frame so the rotation still measures elapsed time
and stays testable with a clock you turn by hand:

    atis: Batumi was on information Alpha, 25 min ago

A letter with no audio is a **restart, not a rotation** — the letter comes off
the table, the frames do not, because Polly renders those and nothing stores
them. It re-records the same letter rather than advancing: a pilot who copied it
two minutes ago has not been overtaken by an hour.

**And the letter no longer starts at Alpha.**

    "the atis information xxx should rotate at least every hour and start
     randomly - so that it's not always alpha"

Hourly rotation already worked (`ROTATE_AFTER_SEC`); the FIRST letter was the
problem, because Alpha says the aerodrome switched its transmitter on the moment
the mission loaded. `broadcast.first_letter` derives it from the field and the
mission's hour instead.

**Derived, not random, and the difference is the point.** `random.choice` would
hand out a new letter on every bridge restart — a pilot who copied Bravo on the
ramp and heard Delta ten minutes later would be right to report it. This is not
Alpha, is different at every aerodrome, is stable across a restart, and advances
through the day exactly as the hourly rotation would have taken it:

    midnight   Batumi=Sierra   Kobuleti=Foxtrot   Nellis=Xray
    1300Z      Batumi=Foxtrot  Kobuleti=Sierra    Nellis=Kilo
    1400Z      Batumi=Golf     Kobuleti=Tango     Nellis=Lima

---

## [ATIS-3] Clearance never asks whether you have the information — #96
labels: bug

**Status:** FIXED 11 August, confirmed live by `tools/ladder_rehearsal.py`
row Q3b. Reported live the same day.

    "Clearance ... never did ask that I had information [alpha]"

Correct. The ATIS advisory is attached in `Controller.check_in`, which is the
only path that composes it — and `request_clearance` says nothing at all:

    def request_clearance(self, cs):
        ac.sortie_phase, ac.last_report_t = "clearance", self.t

So the first controller of the sortie, the one whose entire job is handing over
the numbers a pilot writes down, is the one seat that never confirms he has the
weather. Every later seat does.

Real delivery asks on the first call, before the clearance, because the letter
tells him which runway and which approach to expect. It should be part of the
clearance exchange rather than of the check-in that never happens on the ramp.

**Acceptance criteria**
1. Asking Clearance for an IFR clearance draws *"advise you have information X"*
   (or the correction, if the letter he named is stale).
2. It carries an `advise_atis` decision, like the check-in does, so a dropped
   letter is caught by the verifier rather than by a pilot.
3. A field with no broadcast is not asked about — the existing rule.

---

## [SEP-11] Cleared to five thousand, told to climb to five thousand five hundred — #98
labels: bug, needs-flight-test

**Status:** FIXED 11 August, needs the next sortie. Both halves -- the missing
field and the invented number -- because either alone leaves it open.

    PILOT:  Georgia Center, sockeye level 5000.
    ATC:    Sockeye, Georgia Center. Assigned altitude is five thousand five
            hundred, not five thousand — climb...
    PILOT:  "I was clearly assigned to 5,000. Don't know why you said that"

He was. The clearance he read back, from the plan on file, is `cruise_ft = 5000`
— and something else believes his assigned altitude is 5,500 and corrected him
onto it.

**Two ideas of one number.** The IFR clearance's cruise level comes from the
flight plan; `Aircraft.assigned_ft` is the separation engine's, set when it
issues a level. They are different fields with different owners and nothing
reconciles them, so whichever is nearer to hand wins the sentence.

This is the shape the project keeps meeting, in the one place a pilot cannot
argue: he read the number back, and was told he had it wrong.

**Acceptance criteria**
1. En route, the altitude a controller asserts is the one on the strip.
2. If the engine has a different level it is because it ISSUED one, and the
   issuing is what changes the strip.
3. A pilot level at his cleared altitude is never corrected onto another.


**What was actually wrong, and it was two things.**

**The engine had nowhere to put the clearance.** `assigned_ft` is the separation
engine's -- a stack slot, a vectoring altitude, a missed-approach level -- and
`clearance_read_back` moved the phase and touched no altitude, so en route there
was nothing authoritative to point at. The strip carried `cruise 5,000 ft` from
the plan beside `assigned N ft` from the engine with no rule about which
governed, and the correction in `report_beacon` was gated on `assigned_ft`
alone: a pilot reporting his level in the cruise fell through to a bare `roger`
and nothing in the engine had an opinion about his altitude at all.

Collapsing the two fields was not available. `_free_slot` reads `assigned_ft`
and `None` genuinely means "not in the stack", so a cruise level written there
becomes a holding slot the first time somebody enters the pattern -- a
separation bug, which is the one class an LLM must never be near. So:
`cleared_ft` beside it, and one `Aircraft.governing_ft` that everything
asserting an altitude reads. The engine's assignment outranks the clearance
because it was issued to keep him away from somebody; the clearance stands when
the engine has issued nothing.

**And 5,500 is in no table anywhere.** Not in the plan (5,000), not in the plate
(*"Assignable altitudes: 2000 vectoring, 732 MDA, 3000 missed. Nothing else."*),
not in the rules. It is the same figure the agent produced in #95, where the
engine had said **8,000**. Two incidents, two different correct answers, one
invented number -- so fixing where the number comes from would not have caught
either, because the engine was right both times and the agent said something
else.

That is what `decision.verify` is for, and altitudes were the one assertion it
could not police, because presence is not enough for them. The transmission
above CONTAINS "five thousand", inside "not five thousand", so a
did-he-say-it check passes while the pilot is corrected off his cleared level.
A `level` decision therefore also fails on a CONTRADICTING altitude: a second
level in a sentence about his level is not a richer way of saying the first.
Narrow to `level` on purpose -- an approach clearance legitimately carries the
vectoring altitude and the MDA together.

Verified against the recorded transmission:

    bad  -> ['five thousand (he said five thousand five hundred)']
    good -> []
    repair: five thousand

---

## [PHR-6] An ASR approach should say once that no read-back is wanted — #99
labels: enhancement

**Status:** FIXED 11 August. Attached to the approach clearance, once, and only
on a TALKDOWN — not on an ILS, where the controller says almost nothing after the
clearance and the pilot does report established. Telling him not to acknowledge
there would suppress the one call the procedure needs.

Suggested from the cockpit, 11 August.

    "on an ASR approach, you should tell me at the beginning of the approach
     not to read back"

Right, and it is real procedure rather than a nicety: on a surveillance approach
the controller talks continuously and a read-back of every mile call would put
the pilot on the air over the next instruction. The phrase belongs once, with
the approach clearance — *"do not acknowledge further transmissions"* — and then
never again.

The engine already knows the moment: `cleared_approach` on a vectored profile.

**Acceptance criteria**
1. The approach clearance on a vectored profile carries it, once.
2. It is not repeated on later transmissions.
3. A beacon approach, where he DOES report, is unaffected.

---

## [HO-5] After landing, Ground sends him back to Tower and disowns parking — #100
labels: bug, needs-flight-test

**Status:** FIXED 11 August, needs the next sortie.

**Two faults, and they compound.** `landed` is TOWER's phase — correctly, the
roll is over and he is still on the strip — and **nothing moved him off it**. So
Ground looked at a landed aeroplane, read Tower's phase, and handed him back to a
controller who had finished with him. And parking was owned by nobody: Tower
stopped saying it (correctly — the taxiways are not his, see #88) and Ground
never started, so the last instruction of the sortie fell down the gap between
two seats.

**`taxi_in` is Ground's, and nothing follows it.** `taxi` could not be reused: it
means "to the holding point AND NO FURTHER", it leads to a runway, and
`holding_short` follows it. Two journeys across the same tarmac in opposite
directions, and giving them one name is what made the ladder circular.

The classifier needs no new intent. "Ready to taxi" and "taxi to parking" are the
same request in its taxonomy and opposite journeys on the aerodrome — and the
ENGINE knows which rung he is on, so a taxi request from an aeroplane that has
landed is a taxi IN.

The ladder now closes: Tower keeps him while he is on the runway, the taxi
request is what gives him to Ground, and Ground parks him with nobody after.

**AMENDED 13 August — one sentence of that was wrong, and only one.** "The taxi
request is what gives him to Ground" was a convenient trigger, not a designed
one: it made the PILOT responsible for advancing the last rung of his own
sortie, which is exactly what #77's criterion 1 refuses. The right principle is
two paragraphs above and this issue applied it only to telling the two journeys
apart — **the ENGINE knows which rung he is on**. It knows he has landed, too.
So the trigger moved from his mouth to the sim: `report_down` fires off the
radar poll and gives him Ground on the roll-out. Everything else here stands,
including all three criteria below, and the request path is untouched — a pilot
who asks anyway gets what he got yesterday.

Reported live, 11 August — the last exchange of the sortie.

    PILOT: Taxi to parking my discretion, sockeye.
    ATC:   Sockeye, contact Batumi Tower one one eight decimal six.
    PILOT: Batumi Ground, don't you own parking instructions?
    ATC:   Sockeye, negative, taxi to parking your discretion is all I've got,
           contact Batumi Tower one one eight decimal six.
    PILOT: "obviously he doesn't know his responsibilities"

Two faults in one transmission. **Ground is the end of the ladder** — after
landing he is the last controller, and there is nothing to hand back to Tower
for; the sortie ends with him. And **parking is Ground's**, which is the whole
reason #88 stopped Tower from issuing it.

The handoff is the more serious half: a rung that hands BACKWARDS puts a pilot
on a frequency whose controller has already finished with him, which is how a
man ends up talking to nobody at the end of a flight.

**Acceptance criteria**
1. After landing, Ground does not hand him to Tower, or anywhere.
2. Ground gives a parking instruction rather than declining to own one.
3. `taxi` is a terminal phase at the arrival field — nothing follows it.

---

## [OPS-11] The ladder is rehearsed by a synthetic pilot, and checked — #101
labels: tooling

**Status:** SHIPPED 11 August. Runs unattended, spawns its own fixture, and
goes six of eight against the live bridge; the two that fail are #105 and fail
for that reason. Originally BUILT, needing an aeroplane to judge the
engine-side rows.

    "Can you test some of this using ai aircraft. It's getting tedious to test
     the same things over and over."

It is, and a pilot is the wrong instrument for the parts that do not need ears.
Seven of the last eight sorties re-flew the same eight rungs to find out whether
a handoff fired — which is a structural fact, recorded, and checkable.

`tools/ladder_rehearsal.py` speaks the ladder over real SRS with a Polly voice
and **asserts** on the flight recorder. `flight_rehearsal.py` already spoke;
what it did not do was judge. Every step names its card row and a predicate over
the recorded events — the engine's directive, the authorised handoff, the board
with each aircraft's phase and owner, `not_voiced` when a decided fact went
missing — so the answer is PASS/FAIL and the exit code means something.

**It found two things on its first run**, which is the argument for it:

* **A session collision, live** — `UniqueViolation ... (hooks:ground, default,
  28)`. My own per-seat fix keyed the conversation store on the ROLE, so
  *Kobuleti* Ground and *Batumi* Ground both wrote to `hooks:ground`: two
  controllers, one conversation, the same next message id, and one losing. The
  same lesson as everything else here — **a role is only unique within an
  aerodrome** — and I still keyed on the role. It is the station now.
* **The harness measuring itself** — it waited for the recorder to go quiet, and
  the pilot's own transmission lands immediately while the reply is a model call
  six seconds behind. Every step ended before the controller spoke and reported
  him silent. It waits for the controller now.

**What it cannot do yet.** The engine hears from RADIOS, and a radio is bound to
an aircraft by RADAR — so a synthetic pilot with nothing on the scope is a voice
the engine correctly declines to act on. Those rows **SKIP**, naming why, rather
than going red against a controller behaving perfectly. The first run reported
six red rows for exactly that reason, which is how a harness teaches people to
ignore it.

Spawning an aeroplane at Kobuleti under a matching name is the missing half —
`flight_rehearsal.py` already does this for the formation scenario and the
identity chain cannot tell a spawned unit from a human.

**And it will never cover the ears.** Whether a repaired transmission sounds
like one controller finishing his sentence is card row S11, and no machine
answers it.

---

## [OPS-12] `--ground KOBULETI` parked the aeroplane at Batumi — #102
labels: bug

**Status:** FIXED 11 August. Found while wiring an aeroplane into the ladder
rehearsal.

    lat, lon = _at("BATUMI")
    where = args.ground

`spawn.py --ground KOBULETI` resolved to **Batumi**, forty miles away, and
printed the answer beside the question it had ignored:

    at KOBULETI  ->  41.61030, 41.59970

Correct by accident while the theatre had one aerodrome; wrong the moment it had
two. The same fault as `station_for`, `channels_for`, `"ABCD"[i]` and
`field_origin` — **a question with one possible answer cannot be answered
wrongly**, so nothing found it until a second field existed.

**Two more in the same file.**

The anchor table was two hardcoded Caucasus pairs, so a Nellis spawn would have
resolved to a Georgian coastline. It reads `core/fields.py` through the loaded
theatre now — the published positions have been there since `theatre.verify`
needed them, and two tables of one fact is how they come to disagree.

And **an unknown type was passed through to DCS rather than refused**: `--type
viper` fell past the aircraft table, past the ground table, and spawned a
**Leopard-2** — reported as success. A harness asking for a jet on the scope got
a tank parked on a runway and nothing said so. Unknown types are now an error
naming what is known, with `--force` for a raw DCS type name, and the F-16,
Hornet, Warthog and Eagle are in the table.

---


## [SEP-12] A parked aeroplane was derived as `taxi`, so the sortie began on Ground's rung — #103
labels: bug

**Status:** FIXED 11 August. Found by the ladder rehearsal, which is the whole
argument for having one — it is the third distinct cause of the same symptom and
the first two were each found by a pilot flying the card.

    return current if current in ON_THE_GROUND else "taxi"

`phases._wanted`, for anything the sim says is stopped on the ground and has not
flown. So an aeroplane that had spoken to nobody yet, at the first radar sample,
was **taxiing** — and the clearance rung was skipped before the first word:

    PILOT: Kobuleti Clearance, Sockeye, request clearance.
      .. phase: (none) -> taxi

Everything downstream is then correct and useless. `handoff.due` reads the phase,
sees `taxi`, and says Ground owns him — from the moment he appears, while he is
sitting on Delivery's frequency asking for a clearance he has not got.
`clearance_read_back` setting `taxi` on a correct read-back moves him nowhere,
because he has been there since he spawned, so there is no transition and **no
handoff**:

    PILOT: Cleared to Batumi as filed, maintain five thousand, departure
           one two three decimal three, squawk six five two one, Sockeye.
    ATC:   Readback correct.

and nothing else. That is #90's symptom exactly, twice fixed and still failing,
because the two earlier fixes were both real and neither was this.

It also produced a nonsense refusal on every ground transmission after take-off
clearance — `departure cannot lead to taxi` — which is the deriver being told
off for a transition nothing should have proposed.

**Radar cannot see which ground rung he is on.** Clearance, taxi and holding
short are the same range, the same direction and the same zero knots; two
aircraft parked side by side, one waiting for a clearance and one waiting for the
runway, are geometrically identical and belong to different controllers.
`handoff.State` says so about the rules and was right about the deriver too. What
separates them is what was SAID, and every one of those transitions has an intent
behind it.

So a fresh aeroplane is seeded at the FIRST rung and geometry never overrules the
conversation afterwards. `on_ground is False` still catches him leaving the
ground, which is the one ground transition radar can genuinely see.

**And the board did not publish the rung**, which is why this survived three
sorties of looking at logs: `board_rows` carried the separation enum alone, so
every reader outside the engine saw a parked aeroplane described as ENROUTE and
had no way to ask what it actually thought he was doing. Published now — see #96.

---


## [OPS-13] Fourteen files each decided where the sim was, and three leaked a LAN address — #104
labels: bug, tooling

**Status:** FIXED 11 August.

`DCS_GRPC_ADDR` lives in `director/.env`, which compose reads for the container
and **no shell reads** for a tool run by hand. So every tool rolled its own:

    tools/spawn.py, defend, draw, asr_autopilot, survey_terrain,
    say, check, ladder_rehearsal, radio/pilot.py, atc/agent_atc.py
                                   127.0.0.1:50051
    tools/ai_traffic.py, flight_rehearsal.py, whats_out_there.py
                                   a private LAN address, hardcoded
    tools/sim.py                   reads director/.env -- correctly, privately

Fourteen implementations of one fact, three answers, and the correct one was a
module-private helper behind a comment naming this exact failure: *"anything run
by hand quietly defaults to localhost and fails against a sim on another
machine."*

**What it cost.** The ladder rehearsal asked `sim.py` where the sim was, got the
truth, then asked `spawn.py` to park its fixture aeroplane there and got
`Connection refused` from **localhost** — two lines under a healthy status
report. Every row needing an aeroplane reported SKIP: honest, and useless. It
is the `asr.guide` shape again — two paths to one fact, one of them gated —
except here it was fourteen.

**And it is a leak.** This repo is PUBLIC. Seven files carried a private LAN
address, `SRS_HOST` in four more of them, all in `tools/`, where nobody looks.

`marshall/config.py` resolves both, once — environment, else `director/.env`,
else loopback — and writes the answer back into the environment so a subprocess
cannot get a second opinion. `feed/dcs.py` re-exports `DCS_GRPC_ADDR` under the
name its callers already import; `tools/sim.py` and `tools/bridge.py` lost their
private copies.

`tests/test_one_place_says_where.py` is what stops the fourteen growing back one
convenient default at a time: no committed RFC1918 address, and nothing but
`config.py` may supply a default for a host variable. Both halves were proved
to go red before being left green.

---


## [SEAM-8] A plan on file is reported as a clearance already issued and read back — #105
labels: bug, needs-flight-test

**Status:** FIXED 11 August, needs the next sortie.

**Two judges of one question, and the wrong one was writing it down.** The bridge
verifies a read-back against the clearance on the board — `decision.verify`, the
same function that checks the controller said what the engine decided — and the
director's tool ALSO took `correct: bool = True` from the model and stamped
`clearance_ack` from it. So the one durable fact distinguishing "we read him a
clearance" from "he has it" came from a guess that defaults to yes, and the
`rules.md` prompt explicitly told the agent to form that guess.

The verifier decides, the bridge records, the agent phrases:

* `_read_back_correct` returns the verdict **and the elements he missed** —
  `verify` had always returned that list and the bridge discarded it, so the only
  thing that knew WHAT was wrong was the agent, inventing it. It once said
  "negative, you missed altitude" to a pilot who had read the altitude back
  perfectly and dropped the squawk.
* The engine names them: *"negative — say again four six two zero."*
* The bridge POSTs `/flights/{id}/clearance-ack`, which existed and which nothing
  had ever called.
* `clearance_read_back(callsign, correct)` is **gone** from the agent's tools.
  `clearance_state(callsign)` replaces it and can only REPORT: `NOT ISSUED`,
  `ISSUED, NOT ACKNOWLEDGED`, or `ACKNOWLEDGED`.

Verified live: `clearance_ack` moves from `None` to a timestamp when the bridge
records it, and the controller now answers a mangled read-back with *"altitude is
two four thousand, not four thousand"* — the element, named, from the verifier.

Originally found by `tools/ladder_rehearsal.py` on a deliberately clean
board, 11 August.

The director's flights were cleared and the bridge restarted, so nothing had
been said to anybody. The first transmission of the sortie:

    PILOT: Kobuleti Clearance, Sockeye, request clearance.
      .. phase: (none) -> clearance
    ATC:   Sockeye, Kobuleti Clearance, you are already cleared as filed and
           your read-back was correct — cleared to Batumi, as filed, maintain
           five thousand, departure frequency one two three decimal three,
           squawk six five two one.

Nobody had cleared him. Nobody had read anything back. He had said six words.

**A FILED PLAN IS NOT AN ISSUED CLEARANCE**, and this is the `flight_strip`
fault seen from the other side: that one had the plan, the route and the cruise
level assigned and stored while the strip read none of them, so every controller
asked a cleared pilot what he wanted. This is the same seam failing the other
way — the plan on file is read as a clearance the pilot has already accepted.

Three things are being conflated where there are three distinct states, and the
schema already distinguishes them:

    FILED       a plan exists for this callsign          `flight_plans`
    ISSUED      a controller has read it to him          `assigned_plans`
    ACKNOWLEDGED  he has read it back correctly          the read-back verdict

Claiming the third is the worst of the three. "Your read-back was correct" is
the phrase that ENDS Delivery's business (#90) and hands him to Ground, so
asserting it unprompted skips the rung it exists to close — and tells a pilot he
has an altitude and a squawk he has never heard.

It also explains why the read-back row could not pass: by the time the real
read-back arrived, the agent had already said the words, so the exchange it was
supposed to complete had nothing left to complete.

**Acceptance criteria**
1. On a clean board, the first `request clearance` gets a clearance ISSUED, not
   a claim that one already was.
2. "Read-back correct" is only ever said in response to a read-back.
3. The three states are distinguishable in what the agent is handed — a brief
   that says "filed" must not read as "issued".
4. `tools/ladder_rehearsal.py` Q1/Q1a/Q3 pass on two consecutive runs, which is
   what makes it a gate rather than a first-run demo.

---

## [SEP-13] "Holding short" on Ground does not move the phase — #106
labels: bug

**Status:** CLOSED 11 August. NOT A BUG in the engine -- **the record was stale**. Closed by #107,
11 August, and the diagnosis below was wrong.

`report_holding_short` did run, and the phase did move. The board was RECORDED
before `decide()` let the engine hear the transmission, so the snapshot showed
the rung he had been on when he keyed the microphone. The classifier was also
verified correct on the exact Whisper output, including "Holding Short of
Runways 07":

    report_holding_short  <- Kobuleti Ground, Sockeye, Holding Short of Runways 07.

Kept rather than deleted because the shape is worth remembering: every symptom
below was real and every cause named was wrong, because the instrument was
reading a turn late. See #107.

**The original report, 11 August.**

    PILOT: Kobuleti Ground, Sockeye, Holding Short of Runways 07.
    ATC:   Sockeye, contact Kobuleti Tower one three three decimal zero, good day.
    board: sortie_phase = taxi

The right words, and the rung did not move. The engine's `report_holding_short`
did not run, so the transmission that MEANS "Ground is finished with me" left him
in `taxi` — and the handoff that followed came from the agent rather than from
the ladder.

It is the same shape as #103 one rung further on: the ground half of the sortie
is driven entirely by what is said, so an intent that fails to classify is a rung
that cannot be climbed. Note what did work in the same run — `request_taxi` and
`request_takeoff` both fired, and `request_takeoff` fired on the very similar
"Holding Short Runway 07, ready for departure" — which points at the classifier
rather than at the engine.

**Acceptance criteria**
1. "Holding short of runway zero seven" on Ground sets `sortie_phase` to
   `holding_short`, whether or not "ready for departure" follows.
2. The Tower handoff that follows is the ladder's, recorded as `atc/handoff`.
3. Whisper's "Runways 07" for "runway zero seven" does not change the answer —
   the transcript is what it is and the classifier reads transcripts.

---


## [OPS-14] The flight recorder was a turn stale, and half the handoffs left no trace — #107
labels: bug, tooling

**Status:** FIXED 11 August. Both halves found by `tools/ladder_rehearsal.py`
reporting failures against a controller that was behaving correctly.

**The board was written before the engine heard him.** `record(kind="board")`
ran at the top of the turn and `decide()` — which is where the engine acts on
the transmission — ran sixty lines later. So the recorded board is the state as
of the moment the pilot keyed the microphone, not the state his words produced.

`Controller.board()` says in its own docstring that the point is that "a ghost
is created by a transmission, so the transmission and the board have to be
adjacent in the record or the pairing is guesswork after the fact". A ghost
minted by one transmission appeared attached to the *next* one.

Measured: a pilot reported holding short, the engine moved him to
`holding_short` correctly, and the record said `taxi` — the rung he had been on
when he started speaking. The check written to catch that transition failing
believed the record and reported the engine broken. It was not.

The live `publish_state` stays where it is: the map must not wait on a model
call, and it is a snapshot for a human watching rather than the record anything
is judged against.

**And `atc/handoff` was only ever written by the proactive monitor.** A handoff
the ladder decided and the AGENT then voiced — which is most of them, and all of
the ground ones — left no trace. The bridge authorised it, which is why
`strip_unauthorised_handoff` let it through, and then forgot.

So "which handoffs actually happened" was unanswerable from the record for the
entire receive path. That is the exact question the two mechanisms in #51
disagreed about for a fortnight, and a voiced handoff and an authorised one are
different events whose difference is the bug worth catching.

Both are the same shape as #103: not a wrong answer, a **right answer recorded
at the wrong moment or not at all**, believed by everything downstream. The
harness is the first reader that ever compared the record against what the
engine actually did, which is why two years of logs looked fine.

---


## [SEP-14] The vacated stack level is reassigned before it is vacated — #108
labels: bug, needs-flight-test

**Status:** FIXED 11 August, needs the next sortie. **Hold the level empty** was
the call: on a radar approach the level IS the separation, so the aircraft
cleared for the approach keeps his until he is out of it. Found on the FIRST
run of `tools/stack_rehearsal.py`, 11 August — the first time three arrivals have
ever been sequenced at once.

Three lines, no radio, no sim, no model:

    ctl = Controller(profile)                 # stack_ft [5000, 6000, ...]
    for cs in ("Alpha 1", "Bravo 1", "Charlie 1"):
        ctl.report_beacon(cs, 9000)

    Alpha 1      CLEARED   assigned=5000   <- letdown
    Bravo 1      HOLDING   assigned=5000
    Charlie 1    HOLDING   assigned=6000

**Alpha is flying the letdown at five thousand and Bravo is holding at five
thousand over the same beacon.** Not laterally separated — the hold is over the
beacon and so is the start of the procedure. This is the accident the entire
deterministic half of the system exists to make impossible, and it is the
default outcome of three aeroplanes arriving together.

**How it happens.** `_try_clear` promotes the bottom holder to `CLEARED` and
leaves `assigned_ft` alone, which is right — that IS the altitude he flies the
letdown at. `_free_slot` then counts only `_holders()`, and he is no longer one,
so his level reads as free and the next arrival is put on it. Each half is
defensible; together they hand out an occupied altitude.

**Why nothing caught it.** Both existing tests ASSERT this behaviour —
`test_arrivals_fill_bottom_up` expects B at the base while A is cleared at the
base — so the suite encodes it as intended. Whether it was ever decided or
merely observed and written down is not recoverable from the history. It has
never been flown: sixteen turns of two-or-more holding in this project's whole
recorded life, all synthetic, none of them three-deep.

**The design call, which is the reason this is filed rather than fixed.**

*If the level is his until he leaves it* — the real-procedure answer, and mine —
then `_free_slot` must reserve the letdown aircraft's level, and `_step_down`
must not move a holder into it. That costs one stack level while somebody is on
the approach, which is correct rather than a loss: a level with an aeroplane
descending through it is not free.

*If lateral separation on the procedure is deemed enough*, the engine is right
and what needs fixing is the BOARD, which currently reports two aircraft at one
altitude to every reader outside the engine — and the rehearsal, reasonably,
called it a violation.

The first attempt at fixing it broke seven tests, which is how the second reading
surfaced. Recorded here so the next person does not have to rediscover that the
tests disagree with the fix.

**Acceptance criteria**
1. Three arrivals produce three distinct altitudes, or a stated reason why two
   may share one.
2. `tools/stack_rehearsal.py --ships 3` reports no violation.
3. Whatever is decided, the board says the same thing the engine believes.

**Decided, and done.**

    "Yes, hold it empty"

`_spoken_for` is the level reservation: any aircraft that is not a holder and is
not gone -- the letdown, a missed approach, one under vectors -- keeps the
altitude he is at. `_free_slot` and `_step_down` both read it, because the
collision arrives from both directions: a new arrival can be put on the cleared
aircraft's level, and the step-down can walk the bottom holder into it.

It costs one holding level while somebody is on the approach, which is not a
loss -- a level with an aeroplane in it was never free. Three arrivals now
produce 5,000 / 6,000 / 7,000 instead of 5,000 / 5,000 / 6,000.

Eight tests asserted the old numbers and were updated with the reason. They were
all asserting CONSEQUENCES -- "B is at five thousand" -- and the invariant itself
was never written down, which is why the numbers still matched while two
aeroplanes shared an altitude. `NoTwoAircraftAtOneAltitude` asserts the rule:
three arrivals, a full stack, through a landing and a step-down, and after a
missed approach. Confirmed to fail against the old engine and pass against the
new one before being left green.

Live, three synthetic arrivals over real SRS:

    Hoover           CLEARED      5000 ft  <- letdown
    Sockeye          HOLDING      6000 ft

    no aircraft shared a level, one letdown at a time, the stack
    filled from the bottom, and nobody was forgotten.

---


## [ARCH-12] A radar picture with no origin should say nothing, not guess — #109
labels: architecture

**Status:** FIXED 11 August.

    "A fallback must be conservatively unavailable, not confidently wrong on
     another map."                                  -- CODEX_NTTR_AUDIT.md

`feed/dcs.py` and `feed/tracks.py` measured every bearing and range from a
hardcoded Batumi, with a `_MAGVAR = 6.0` described as "Caucasus magnetic
variation". Both are now derived from the loaded theatre's home field, so a
Nevada picture is measured from Nevada and uses the field's own surveyed
variation (12 East at Nellis, 16 at Tonopah).

**What is still wrong is the shape of the failure.** `home_field()` raises if
the theatre publishes no field, and every caller renders unconditionally — so
there is no path that returns structured contacts *without* a
controller-relative rendering. A controller who cannot measure should say he
cannot, exactly as `vector` already does for an unpublished fix:

    "negative DME to ingress, you'll have to call it off your own nav"

which was the correct failure and is the model for this one.

**Acceptance criteria**
1. With no usable origin, radar answers with contacts and no bearing/range.
2. Range-dependent guidance is suppressed rather than computed from a default.
3. Nothing anywhere carries a map's coordinates as a module constant.

**Done.** `fetch_radar` fell back to the DIRECTOR's prose whenever it had no
projected origin of its own, and the comment justified it: *"drawing from a stale
constant beats drawing nothing"*. It does not. That prose is measured from the
director's origin, which the bridge does not choose and cannot see, and a Nevada
controller reading distances from Georgia gets plausible numbers that are wrong
in every one.

`picture.unranged` renders what needs no origin — who, what, how high, which way
— and says plainly that bearing and distance are unavailable. That is enough to
answer "do you have me", to correlate a radio with an aeroplane, and to see that
four contacts exist; `vector` already models the right failure for the rest.

**And "no contacts" was itself a lie.** The old no-origin path returned exactly
that, to a controller with four aeroplanes in front of him. Not seeing and not
being able to measure are different failures with different answers, and
reporting the second as the first is how a pilot four miles out gets told he is
not on the scope. They are distinct now.

The director's prose is still used for the case that genuinely justifies a
fallback: no contacts of our own — "I cannot see", rather than "I cannot
measure".

---

## [OPS-15] Nevada has no Center, so the ladder stops at Departure — #110
labels: bug, needs-flight-test

**Status:** FIXED 11 August, needs the next sortie.

`handoff.RULES` routes an outbound Departure aircraft to `center` at 25 nm.
`NEVADA_STATIONS` held Nellis and Tonopah positions only, so
`station_for("center")` returned nothing, `handoff.due()` produced no verdict,
and a Nellis departure worked cleanly through Clearance, Ground, Tower and
Departure and then **stayed with Departure for the rest of the flight**.

Nothing fails in that sequence. A rung is missing and the ladder quietly stops,
which is #51 on the Caucasus — the one a pilot found at 44 nm by declaring an
emergency.

Los Angeles Center (ZLA) owns the enroute airspace over southern Nevada, and a
transit between two airfields is enroute work. 133.400 is one of its sector
frequencies; like Georgia Center's it is **chosen rather than surveyed** and is
marked as such.

**Not the range.** Real NTTR range control is Nellis Control — "Blackjack" — a
different service with its own airspace and phraseology, and none of it is
modelled. Naming a there-and-back transit a range mission would be exactly the
plausible-wrong-answer failure the two-aerodrome work was about.

---

## [ARCH-13] One arrival profile per bridge, and a sortie has two ends — #111
labels: architecture

**Status:** CLOSED as a duplicate of [ARCH-1]/#2, which has described this since
the beginning: "One approach profile per flight, not per bridge -- THIS IS THE
WALL IN FRONT OF MULTIPLE AIRPORTS."

Filed on 11 August by somebody (me) who had read the Nevada audit and not the
backlog. The evidence it carried -- a Nevada bridge loading the Tonopah recovery
for a flight going home to Nellis -- is folded into #2, where the acceptance
criteria now include it.

Worth leaving rather than deleting: a 115-issue backlog that grows a duplicate of
its oldest architectural entry is telling you something about itself.

---

## [SEP-15] "On the ground" was measured from sea level — #114
labels: bug, needs-flight-test

**Status:** FIXED 11 August, needs the next sortie. Found on the first Nevada
ladder run.

    GROUND_ALT_FT = 200
    return bool(pos.alt_ft < GROUND_ALT_FT and pos.speed_kt < GROUND_SPEED_KT)

`pos.alt_ft` is **above sea level**. That works at Batumi, thirty-two feet up,
and is nonsense anywhere with terrain under it: the **ramp** at Nellis is 1,849
feet and Tonopah's is 5,550, so every parked aeroplane on the map read as
airborne.

Everything gated on "is he down" was wrong with it — the ramp guard, the phase
branch of `handoff.due`, the silence that keeps approach guidance off a taxiing
aircraft. What it actually produced, to a stationary F-16 that had asked for a
clearance:

    ATC: "Sockeye, radar shows you a mile out, past my boundary — contact
          Los Angeles Center, one three three decimal four."

The airspace branch is correctly gated on `not down` and its own comment says
why — *"a parked jet is not 'leaving my airspace'"*. It was right. The fact
underneath it was wrong, so Clearance sent a man who had not moved to an enroute
controller a hundred miles up.

**The height is above the FIELD now**, taking the highest aerodrome in the
theatre — one number for a test that has no per-aircraft field to consult, and
generous on purpose: the sim's own land/takeoff event is checked first and is
authoritative, so this fallback only ever decides for aircraft no event covered.

The Caucasus is unchanged, which is the point — 59 feet against 32 changes
nothing there, and that is exactly why this survived. A constant that is right
on one map is invisible until there are two.

---


## [SEAM-9] Handed to Center and told to hold, in one transmission — #115
labels: bug, needs-flight-test

**Status:** FIXED 11 August, needs the next sortie.

**`reconcile` was arbitrating three authorities out of four.** Its whole job is
deciding which one owns an aeroplane, and the handoff — the strongest answer
there is, because it says somebody else does — was decided two hundred lines
further down and merged into the reply afterwards. So a turn that produced both
produced both.

`next_controller` now runs BEFORE `settle`, and `reconcile` takes it as its
first branch: a binding instruction is dropped along with its decision, because
suppressing only the words leaves #79's repair to put it straight back on the
air. A **refusal survives** — "take-off is Tower's, contact Kobuleti Tower one
three three decimal zero" IS the handoff with its reason attached, and card row
Q5 turns on it.

Arbitrated on the DECISION, never on the prose: reading a directive for a
keyword is what this function was rewritten to stop doing. A directive whose
engine attached no decision cannot be arbitrated and is kept, which is the safe
answer and makes #80's criterion 4 visible rather than guessed at.

Live, the same exchange that filed this:

    "Bandit, you're outside my airspace, contact Los Angeles Center,
     one three three decimal four. Good day."

and nothing after it. `tools/stack_rehearsal.py` checks every transmission for
the pair from the outside, reading what went on the air rather than what
produced it.

Originally seen on the first Nevada stack run, 11 August.

    ATC: "Bandit, contact Los Angeles Center, one three three decimal four.
          Good day. Hold at present position, maintain one zero thousand..."

Two authorities in one breath, which is the exact thing `reconcile` exists to
prevent — and the pilot cannot obey both: he has been sent away and given an
instruction by the man who sent him.

Each half is defensible on its own. The arrivals were spawned 32 to 50 nm out,
outside Approach's twenty-five miles, so the ladder is right that Center owns
them; and the separation engine is right that an aircraft asking for the
approach with two ahead of him gets a level. The fault is that both reached the
radio.

`reconcile` already decides between the engine's directive and the agent's
proposal. A HANDOFF is a third authority and it is not in that decision: it is
authorised separately, by `next_controller`, and merged into the reply
afterwards. So a turn that produces both produces both.

**A handoff should win.** Once he is somebody else's, an instruction from this
controller is not ours to give — the same rule as #65 and #88 one level up: a
controller answers for what he owns, and he has just said he does not own this
aeroplane.

**Acceptance criteria**
1. A turn that authorises a handoff issues no separation instruction with it.
2. The engine's directive is dropped rather than the handoff, and the drop is
   logged the way `reconcile` logs the others.
3. `tools/stack_rehearsal.py` sees no transmission containing both.

---


## [OPS-17] `--sync` overwrote an issue it had no business touching — #118
labels: bug, tooling

**Status:** FIXED 11 August. Caused by me, on somebody else's issue.

    renamed  "investigate DCS-SMS"
          -> "[ASR-6] The Nellis ILS dithers, and three approaches never arrive"

`[ASR-6]` was appended to `ISSUES.md` with a **hand-written** `— #116`, chosen as
"the next number". #116 was already **"investigate DCS-SMS"**, opened by the repo
owner twenty-five minutes earlier and deliberately closed. `file_issues.py
--sync` edits by NUMBER, took the claim at face value, renamed the issue and
replaced its body.

**The body is not recoverable.** GitHub's `userContentEdits` keeps the
replacement, not what was there before. The title and the closed state are
restored and the investigation comment survived — which is the substance — but
the original text is gone. Recorded here rather than quietly patched.

**Three faults, and only the first is mine alone.**

1. A number was hand-written instead of being assigned. Every other entry this
   week was appended without one and renumbered by the tool, which is the
   mechanism that makes collisions impossible.
2. `--sync` had no idea what it was editing. It matched on number and never
   asked whether the issue on the other end was the one the entry describes. It
   now **refuses** any edit where the existing title does not carry the entry's
   slug, and exits non-zero.
3. `issue_sync.py` reported "in step" while GitHub held an issue `ISSUES.md` has
   never heard of. It compared every entry against GitHub and never the other
   way, so an issue filed straight on GitHub — legitimate, and normal — was
   invisible, and its number looked free. It lists them now.

The third is the one that made the first possible, and it is the same
one-directional blindness as the `DONE`-word gap fixed the same day: a check
that only looks one way will call two things equal while one of them holds
something the other has never seen.

---


## [ARCH-15] The board cannot remember who is flying — #119
labels: architecture, needs-flight-test

**Status:** FIXED 11 August, needs the next sortie. All six criteria met and
proved against the live director:

    1. three binds on srs_name alone -> 1 row
    2. intent recorded -> 'VFR to Batumi, visual 13'
    3. another instance sees 0 rows
    4. after leaving the slot -> 0 rows
    5. expiry removed 1, 0 left

**The sortie key is `name@started`**, where `started` is `now - model_time` —
the sim's model clock resets on every load, so that difference is constant
within one instance and different across two. Any process computes it without
coordinating, and a bridge restarted mid-sortie computes the SAME key and keeps
the board, which a random id per process would not. **Nothing is deleted to make
this work**: a row from a previous instance is not stale data to be cleaned up,
it is a different world, and it is never found.

**`srs_name` is now the weakest binding key**, after guid and track. A name can
be changed and two people can pick the same one — and it is enormously better
than the alternative, which was to match nothing and INSERT.

**`player_leave_unit` ends the row**, in the same breath as the board entry, and
takes `assigned_plans` and `flight_member` with it. **Silence expires it** on the
tick that already reconciles the board — wired at the moment it was written,
because an endpoint nothing calls is the shape this project keeps finding.

**Intent is captured above the reachability gate.** An action the procedure does
not contain is a reason not to act on a transmission; it is not a reason to
forget what the man said he wanted.

Originally: **read `docs/STATE.md` before working this.**

    "if the whole system requires claude code to keep the database clean, this
     isnt going to work."

Correct. Nothing ever deletes a flight row. `clear_mission` exists and is called
by exactly one thing — a human hitting `DELETE /flights`. Every row is
`mission = 'default'`, so there is no notion of a sortie; `player_leave_unit`
frees the in-memory board and not the row; a mission load wipes nothing.

`tracks` already does this correctly — every radar sweep deletes whatever the sim
no longer has, nobody cleans it by hand, and it has never carried a ghost. Same
kind of fact, opposite treatment.

**What it cost, 11 August.** One sortie, three complaints, one cause. His flight
produced three rows in thirty seconds, none bound to him, because `bind()`
matches on `srs_guid`, `track_name` and `callsign` and **not `srs_name`** — so a
transmission carrying only an SRS name matched nothing and inserted. Every
`flight_agree` wrote into a row identifying nobody and the next transmission
abandoned it. Every controller met him for the first time.

And **nothing on the bridge ever writes `intent`.** He said "VFR to Batumi,
visual 13" on his first call and at every handoff; the field is read in four
places and written by none.

**Acceptance criteria**
1. A row belongs to a mission INSTANCE. A row from a previous one is never found.
2. `player_leave_unit` ends the row, not only the board entry.
3. A flight with no radar contact and no transmission expires, reconciled the way
   `tracks` is.
4. `srs_name` is a binding key.
5. A pilot's stated intent is written down and inherited at every handoff.
6. `DELETE /flights` is a debugging convenience, not load-bearing. Fly two
   sorties back to back without touching it and the second is clean.

---

## [ARCH-16] The board is in memory; the database is the source of truth — #120
labels: architecture, needs-flight-test

**Status:** FIXED 11 August, needs the next sortie. **See `docs/STATE.md`.**

**The board is a write-through cache now**, hydrated from `flight_state` at
bridge start and written through on every turn. Live: `board: 1 aircraft restored
from the table`, and the ladder continued from the restored rung — Q6 needs the
phase to have been `taxi` before it, which only the table knew.

**Migration 026** gave four facts a column. `sortie_phase` is the important one:
`flights.cleared` already carried the SEPARATION enum and `sortie_phase` answers
a different question — what he is DOING — and is what `handoff.due` reads to
decide who owns him. Losing it on a restart lost the entire ground half of a
sortie. The others are `on_visual`, `approaches_flown` and `atis_letter`.

**No position is restored.** That is radar's, it lives in `tracks`, and it is
reconciled every sweep; a board that remembered a position across a restart would
assert where an aeroplane was minutes ago.

**The letdown comes back with him.** An aircraft restored as `CLEARED` is
restored as the man ON the approach — otherwise the next arrival is cleared
straight into him, which is the accident the engine exists to prevent, caused by
the recovery from a restart.

**And the scratch is named.** `Bridge.__init__` grew sixteen dictionaries without
anybody deciding which were durable. They are now in two labelled groups with the
test written down: *if a bridge restarted mid-sortie would say something WRONG
without it, it is remembered and needs a column; if it would merely recompute it,
it is scratch.*

**Two faults found on the way**, both mine and both caught by existing tests:

* The #115 handoff branch dropped the ASR talkdown along with the instruction. A
  talkdown is not an order we may no longer give, it is the procedure the
  controller is flying, and going silent on final because a handoff was due is a
  far worse failure than the one being prevented. It now goes only when a
  **heading** is among the suppressed instructions.
* A unit test inherited the LIVE board, because startup hydration asked the sim
  which mission was loaded and got the real key. A test is a different world from
  a live server and must never share a bucket with one — the mission instance
  doing its job in the other direction.

Originally: OPEN, and deliberately after #119.

    "there really shouldn't be much in memory data structures - we addressed
     this - database is fast and should be the single source of truth"

`Controller` holds the entire board — phase, altitude, approach, clearance, the
letdown, the formations. `Bridge` holds sixteen more dictionaries. The same facts
exist in `flights`, `identities`, `assigned_plans` and `flight_member`, are
written, and are never read back as authoritative. A restart forgets every one of
them while the aeroplanes go on flying.

Some of it genuinely belongs in memory — `decided`, `handoff_due`, `last_said`
live and die inside one transmission. The rest is the controller's MEMORY.

**Not worth starting before #119.** There is no point caching a table that
cannot be trusted to hold what it is given.

**Acceptance criteria**
1. `Controller.aircraft` is a cache of the tables, not the original.
2. A bridge restart mid-sortie loses nothing a pilot can hear.
3. Per-turn scratch is separated from remembered state, named as such.

---


## [SEAM-10] A read-back is heard as a report, and a debug note moves the board — #121
labels: bug, needs-flight-test

**Status:** FIXED 11 August, needs the next sortie. Unit-proven against the exact
transmissions; NOT yet proved live, because reproducing it needs a spawned
fixture and a two-turn sequence the harness does not yet script.

    PILOT: Kobuleti Ground, sockeye, taxi to runway 07, holding short of
           runway 07.
    ATC:   Sockeye, contact Kobuleti Tower one three three decimal zero.

He read the taxi clearance back and it was heard as "I am holding short", so the
phase moved and the ladder handed him to Tower before he had moved an inch. His
own note:

    "clearly, Kobuleti Ground thinks that I'm telling her that I'm holding short
     of runway 07 when actually I'm just doing a read back"

**TIME IS THE DISCRIMINATOR, the echo is the guard.** Word overlap cannot
separate them and that is the whole difficulty: a genuine *"holding short of
runway zero seven"* is a SUBSET of *"taxi to runway zero seven, hold short of
runway zero seven"*. A read-back FOLLOWS its instruction inside one exchange; the
report of complying comes minutes later, after he has taxied there. The echo is
still required so an unrelated transmission in the window is not swallowed.

`reads_back_what_we_said` has existed for weeks and only ever decorated the
AGENT's prompt — it could tell a model not to say "negative" and could not stop
the engine acting. The check is in the dispatch now, where it can.

**AND THE DEBUG NOTE.** #82 said "I could not make the board actually move" and
was left alone. It moves:

    PILOT: Debug log, that's not correct. You should be sending me to tower now
           on a visual approach.
      .. phase: approach -> landed
      .. ASR guidance suppressed: phase landed does not fly the approach

A note to the project, at 1,900 ft on final, classified as "I have landed" — so
the engine believed he was down, suppressed the approach for the rest of the
sortie, and the controller improvised from there. The gate ran two hundred and
forty lines AFTER `decide`. It is the first thing in the turn now, before
identity, before the classifier, before anything.

**What was NOT wrong**, and I said it was: there is no missing `REQUEST_LANDING`
rung. A clean call to Tower already gets *"cleared to land runway one three, wind
zero nine zero at six."* The landing clearance never arrived because the phase
had been corrupted by a debug note, not because nothing could issue it.

---

## [SEAM-11] The proactive thread decides nothing and does not say so — #122
labels: bug

    "had to end that flight early. left several debug logs. Never got handed to
     center.."

Kobuleti to Batumi, 11 August. He checked in with Kobuleti Departure at four
miles and then flew to thirty with nothing on the radio at all:

    DEBUG NOTE  on 15 miles away from the airport, still no transition to center
    DEBUG NOTE  I'm passing 20 nautical miles from the airport, still no transition
    DEBUG NOTE  I met 30 miles outside the airport, I have to stop flying

`Rule("departure", "center", "outbound_beyond", 25)` exists and is correct —
asked directly with his exact state it returns Georgia Center. So the rule was
never asked, and **the record cannot say why, because the monitor writes a line
when it acts and nothing when it does not.** Three minutes of a pilot leaving
the terminal area produced zero lines and no exception. A thread that goes
silent when it decides nothing is indistinguishable from one that has died —
which is the same complaint a pilot makes about a controller who stops talking.

Two fixes, and only the second is about a rule:

  * **It kept no record of deciding nothing.** `watching_him` returns
    `(station, why)`, and the monitor prints the reason when it CHANGES —
    which controller is holding him, his phase, his range, and whether he is
    inbound or outbound. Recorded as `handoff/none`, so it is on the
    diagnostics page too.
  * **It asked the wrong question.** `next_controller` is the one function that
    owns "who has him next" — the sim's events, then the ladder, then the
    airspace volumes, in that order — and this thread asked only the middle
    one. Its own docstring warns about exactly that and names the sortie it
    cost (#51). It is a caller now, so the volume branch gets a vote as well:
    a jet that has left the terminal area is caught even if the ladder is
    somehow starved.

**And it became testable by being a function at all.** The departure → Center
rung has never had a check: `ladder_rehearsal.py` cannot cover it, because a
synthetic pilot has no aeroplane on radar and this rung is pure geometry. See
`tests/test_the_monitor_says_why.py`.

## THE CAUSE, found by `tools/ghost_flight.py`

Not guessed at. `tracks` is the radar picture and everything downstream of it is
ours, so a row written by hand and marched along a heading flies the whole chain
— radar, board, decision, radio — with no sim at all. That tool is new and this
is what its first three runs turned up. **Three faults, in the order they
surfaced, each hiding the next.**

**1. Kobuleti had no airspace.** `sectors` held three rows — batumi-approach,
batumi-tower, georgia-center — and 005's own comment predicted it: *"the moment a
second aerodrome exists, and a second aerodrome is the next test."* 008 COALESCEs
onto the unbounded sector, so an aeroplane inside no described volume becomes the
Center's, and a jet 3 nm off Kobuleti's runway at 2,000 ft was offered Georgia
Center while still in the circuit. Absence read as an answer. Migration 027 gives
both fields circular volumes that meet near the midpoint; `leaving_my_airspace`
now also abstains inside the ladder's own terminal distance, because the next
theatre has the identical hole and Nevada is next.

**2. The monitor measured every range from Batumi.** `fetch_radar` takes the
speaking controller's field and the receive path has passed it since #109; this
thread passed nothing. So a jet three miles off Kobuleti read as twenty-five
miles out and `departure → center` fired on the first poll — the rule right, the
input wrong, every number real and belonging to another airport. It draws one
picture per aerodrome now, through `radar_fixes(picture=...)`.

**3. And underneath both, the actual cause of the sortie.** The thread remembered
who it had already handed over as a SET OF CALLSIGNS:

    if _nxt is not None and cs not in handed_off:

which cannot tell *already sent to Departure* from *already sent to Center*.
Tower gave him to Kobuleti Departure at half a mile; from that moment the monitor
believed it had finished with him, and the entry is only cleared on a poll where
NOTHING is due — which never comes once an aeroplane is airborne. **Every later
rung of the ladder was suppressed by the first one, for the rest of the flight.**
A handoff is not a state an aeroplane is in; it is a thing said to a particular
man about a particular controller, so the record has to name the controller. See
`a_fresh_offer`.

It took a ghost that checks in with TOWER first to reproduce — `--from-tower` —
because a flight that starts on Departure never has a first handoff to be
suppressed by. The rung now passes end to end: Tower → Departure → Center at
exactly twenty-five miles, with the monitor accounting for itself every five.

**Status:** FIXED 13 August — `0ff0467`, `dee3600`, `124ff1c`. All four hold at
HEAD: `watching_him` returns `(station, why)` and asks `next_controller` in
every branch, the thread records `handoff/none` and `/diag` has a row for it,
`a_fresh_offer` keys the memory on the CONTROLLER rather than the callsign, and
the picture is drawn per aerodrome. `tests/test_the_monitor_says_why.py` is
green. Not `needs-flight-test`: every claim is structural. One sentence above is
now stale and is left standing as the record — `leaving_my_airspace` no longer
abstains inside terminal distance, that guard having been deliberately replaced
by the `coming_towards_us` trend test under #138.

---

## [ASR-7] An ILS is not a talkdown, and nothing had ever flown one — #123
labels: bug

    "ive never flown an ILS with marshall yet - just the ASR and Visual"

Which is why this was never seen. `profile.vectored` is False for an ILS —
correctly, because it asks who owns navigation ALL THE WAY DOWN and on an ILS
that is the pilot — and both the guidance context and the whole radar monitor
were gated on it. An ILS recovery got no vectors, no descent, no clearance and
no geometry whatever; the controller had to improvise the entire arrival, which
is precisely what `asr_context` exists to prevent.

The same gate killed the monitor outright on the 1944 beacon letdown, handoffs
and all, because that profile is not vectored either. Two procedures, opposite
reasons, one flag answering for both.

**`may_vector` is the question actually being asked** — may this controller
issue a heading at all — and it is now asked in one place by both callers. The
capability wins where it is stated (#53 added it for the letdown, whose homing
adapter points the nose at the beacon), and the procedure decides where it is
not.

**The two procedures divide the work in opposite places**, and that is the whole
of the new behaviour:

    ASR    the controller IS the approach aid. A range every mile, a heading
           and an altitude, all the way to the missed approach point.
    ILS    the controller owns the INTERCEPT only. He vectors, he clears, and
           at established he STOPS — the pilot has a localiser and a glidepath
           and is flying both. Reading him ranges is chatter over a busy man,
           and reading him a descent table beside his own glideslope is two
           instruments disagreeing once a mile all the way down.

The approach clearance rides on the last vector rather than waiting to be
prompted, for the same reason `vector_call` exists: the agent only speaks when
the pilot does, and an aeroplane being turned onto the localiser has no reason
to transmit. A clearance that waits arrives after he has flown through the
centreline, or never.

Still to fly: the Kobuleti ILS 07 recovery end to end. See
`tests/test_the_ils_is_not_a_talkdown.py`.

**Status:** CLOSED UNVERIFIED 13 August — flight-test bankruptcy, not a pilot's word. `may_vector` is one question in
`core/approach.py`, asked by both the guidance context and the radar monitor: an
ILS controller vectors to the intercept and goes quiet at established, the ASR
still talks him all the way down, the beacon letdown never vectors at all, and
the approach clearance rides on the last vector. All four are in
`tests/test_the_ils_is_not_a_talkdown.py` and green, and a ghost flew the BATUMI
ILS arrival end to end (`655bf90`). The line above is the reason this is not
FIXED: nobody has flown the Kobuleti ILS 07 recovery.

---

## [ARCH-17] Airspace was hand-written, and the next map has forty aerodromes — #124
labels: architecture

**Status:** CLOSED 11 August. Attested by claude at 4c88b7c —
`tools/ghost_flight.py --from-tower` against the live bridge: five derived
volumes pushed at startup, Kobuleti Departure → Georgia Center at exactly 25 nm
measured from Kobuleti; `tests/test_every_aerodrome_has_sky.py` asks every
loadable theatre for gaps. Not `needs-flight-test`: every claim here is
structural — a volume exists, a boundary falls between two fields, a handoff
fires at a range — and a machine can answer all of them.

    "So how do we prevent missing airspace bug going forward. We're going to add
     dozens of airfields"

You cannot, by hand, and the reason is not effort.

`sectors` held three rows written into migration 005 — batumi-approach,
batumi-tower, georgia-center — and 005's own comment named the day it would
break: *"the moment a second aerodrome exists, and a second aerodrome is the
next test."* It arrived without one. 008 COALESCEs onto the unbounded sector, so
an aeroplane inside no described volume is the Center's, and a jet three miles
off Kobuleti's runway at two thousand feet was handed to Georgia Center while
still in the circuit.

**The row was not wrong. It was ABSENT, and absence read as an answer.** That is
the failure mode a hand-maintained table has and a derived one cannot have:
`sectors` was a SECOND COPY of a fact the theatre already holds — where the
aerodromes are and who works them — maintained independently of its source. It
drifts, and the drift is invisible until somebody flies it. docs/STATE.md, one
table further along.

**So the volumes are derived and pushed**, exactly as the fix catalogue is and
for the identical reason the `/atis` endpoint gives: the bridge knows which map
is loaded and the director does not.

    core.airspace.sectors_for   what a volume is, from fields + stations
    push_sectors                at startup, beside push_fixes
    feed.tracks.set_sectors     the pushed set REPLACES the table

An aerodrome now gets airspace **by existing**. Give it a lat/lon and a Tower and
it has a volume; give it neither and it has none, which is honest. Forty of them
cost nothing.

**Where the boundary goes, with nobody drawing a polygon:** half way to the
nearest neighbour, capped at the terminal range. Kobuleti and Batumi are
twenty-two miles apart so they meet at eleven and neither swallows the other —
which is what went wrong on the first attempt, when both were given twenty-five
and an aeroplane on Kobuleti's ramp resolved to Batumi Approach. It is also how
it is actually done: a boundary between two terminal areas twenty miles apart is
not at either field's twenty-five mile ring.

**Three smaller faults fell out of it:**

  * The sector is named for the VOLUME's role, not the station's. Kobuleti's
    terminal controller answers as Departure, and `leaving_my_airspace` reads the
    role off the end of the sector name — so `kobuleti-departure` would have
    silently switched airspace off for that field.
  * `departure` was missing from that function's ladder-order map, so it
    defaulted to 9, BELOW everything, and "never hand him UP the ladder" could
    not fire for a departing aircraft at all. An outbound jet was eligible to be
    handed to Tower, the one direction the guard exists to forbid.
  * `handoff.CENTER_NM` and the edge of Approach's volume are two statements of
    one boundary and were two numbers. `CENTER_NM` is imported from
    `airspace.TERMINAL_NM` now — procedure may read geography, not the reverse.

`tests/test_every_aerodrome_has_sky.py` asks the general question of **every
theatre this project can load**, not of the field somebody remembered to add:
every field with a terminal controller has a volume, every theatre has an
unbounded fallback, and neighbours do not overlap. Nevada had the same hole,
unflown and unnoticed, until that file ran.

---

## [ARCH-19] The filed route repeats the aerodromes, and the "two fixes" rule depends on it — #127
labels: architecture

**Status:** CLOSED 11 August. Attested by claude at 28947f8. `clearance_tools`
takes the seat and `field_of` establishes the origin at issue into
`assigned_plans`; `check_live`'s two-fix rule is replaced by "every fix named
exists" with a warning on a repeated aerodrome; migration 029 normalised all
three filed rows. Live: an empty route is accepted, a repeated aerodrome is
warned about, and the DTC refiles Domino as `FOO, BAR, SPAM`.

Not `needs-flight-test`: every claim is structural — a validator verdict, a
column written, three rows rewritten — and a machine answers all of them. What a
pilot would add is whether the CLEARANCE still reads correctly aloud, which is
card row Q2 and unchanged by this.

    "So ORIGIN and DESTINATION - should these be on the flightplan as fixes?"

No. ICAO keeps them apart on purpose — **field 13** departure, **field 15** the
enroute portion, **field 16** destination — and `flight_plans` already has all
three columns. Repeating the aerodromes inside `route` is duplication, and it
has quietly become load-bearing: `filing.check_live` refuses anything with
**fewer than two fixes**, and that rule only passes because the aerodromes are
padding the list.

So a genuine direct flight — Kobuleti to Batumi with nothing published in
between, which is most of what gets flown here — has **zero** enroute fixes and
cannot be filed at all without writing its endpoints in twice.

`dtc.plan_from` now returns `enroute` beside `route` so the honest list already
exists; the route keeps its endpoints only because the rule exists TODAY and
refusing a plan is worse than repeating a name.

## The shape, decided 11 August

    "I think the destination will typically be in the steerpoints but the
     departure airfield will not. Maybe that's determined from whatever
     clearance opens the plan?"

Right on both halves, and the second is the better idea. Three facts, three
authorities — which is the same split #105 drew between FILED and ISSUED, one
field along.

| | authority | when it is known |
|---|---|---|
| **destination** | the cartridge | at filing. It is a steerpoint: DKS writes the field's own name on it |
| **route** | the cartridge | at filing. The ENROUTE portion, and empty is legal |
| **origin** | the seat that opens the clearance | at ISSUE, not at filing |

**Why the origin is not filed.** A DTC has none — steerpoint one is already
airborne and some miles out, so where he took off from is genuinely not in the
file. Every attempt to derive it has been a guess dressed as a fact:
`theatre.departure` was a per-theatre constant; nearest-aerodrome-to-steerpoint-
one needed a field table; the comms ladder is a good heuristic and is still a
heuristic.

The clearance frequency is not a heuristic. A pilot calling **Kobuleti
Clearance** is on Kobuleti's ramp — he cannot be anywhere else and be talking to
that seat. `bridge.heard_on` already resolves the frequency to a station and
`his_field()` already turns a station into an aerodrome, so the fact is in hand
at the moment it matters and needs no inference at all.

And it belongs on the per-flight copy rather than the template: `assigned_plans`
already has its own `origin` column. A filed plan is a route anybody may
request; a clearance is issued to one aeroplane departing one field. Two
aeroplanes may fly `Domino` out of different fields on the same night, and
today's schema says they have the same origin.

## The order

1. **Establish the origin at issue.** `clearance_tools` learns its own field
   from the station the agent was built with, and `assign` writes it to
   `assigned_plans.origin`. Additive: nothing that reads the template changes.
2. **Let the route be enroute-only.** `check_live` stops demanding "at least two
   fixes" — the rule it actually wants is *every fix named is one the sim
   holds*, which is what its own docstring says it is for. Empty becomes legal,
   which is what "direct" means.
3. **Normalise the filed rows**, once 2 is in: strip the endpoints from `route`
   on the plans already on the board.

Not to be done while somebody is flying: 2 touches the validator, every filed
row, and the clearance a controller reads aloud.

---

## [SEAM-13] The flight row's callsign is the unit name, so a pilot cannot be found by what he says — #128
labels: identity

**Status:** CLOSED 11 August. `names.handle` dropped ANY chunk with a digit, so
`Nomad29` went with the squadron tag and the slot number and the fallback
returned the whole raw unit name. It now drops only what is structurally a slot
(all digits) or an ordinal squadron tag; everything else is a person.

Attested by claude at bafcf01 — `ladder_rehearsal --only Q1a` PASSES against the
live bridge through real SRS, Whisper and Polly: *"Kestrel seven one, Kobuleti
Clearance, cleared to Batumi, as filed, maintain one zero thousand, departure
frequency one two three..."*. Not `needs-flight-test`: the claim is that a
callsign resolves and a clearance is issued, and a synthetic pilot flying the
card row answers both.

Found #129 on the way — the plan it was clearing named steerpoints that a bridge
restart had already deleted.

Found by `tools/ladder_rehearsal.py --only Q1a` while proving #126 — the first
rehearsal of clearance delivery since the mission wiring was fixed.

    PILOT: Kobuleti Clearance, Nomad29, Domino please.
    ATC:   Nomad two nine, I do not have you on the board.
           You are three six two nd nomad two nine one — use that callsign.

**The board is being read correctly now** (that is #126 working: before it, the
tool could not see the board at all and said so flatly). What it holds is wrong:

    callsign   362nd_nomad29-1     <- the UNIT name, lower-cased
    track      362nd_Nomad29-1
    authority  (none)
    confirmed  (none)

`park_an_aeroplane`'s own docstring says the chain should derive the handle:
*"`362nd_Sockeye-1` derives to the handle `Sockeye`, which is exactly what the
synthetic pilot calls himself."* It did not. The raw track name went into the
`callsign` column instead, so `_flight("Nomad29")` misses and every
callsign-keyed tool misses with it.

**And the refusal then tells him to rename himself after a sim unit.**
`not_on_the_board` names the closed set, which is right and is what makes this
diagnosable at all — but the set it names is track names, so the advice is *"use
callsign 362nd_nomad29-1"*, which no pilot would ever say and no transcriber
would ever hear.

Isolated from the identity fault, the clearance path is correct — bound a flight
by hand under the right mission and it issues:

    cleared to Batumi, as filed, maintain one zero thousand,
    departure frequency one two three decimal three, squawk one four two one
    (matched on destination, origin (from who he called); plan Domino)

so this is the LAST thing between a pilot and his clearance, and it is on the
identity side rather than the clearance side.

Two things to establish: whether the handle derivation runs at all on this path,
and whether `authority`/`confirmed` being empty is the same cause or a second
one. Suspect the row is minted by the transmission before radar correlates it,
and never revised — which would be #119's lifecycle question one column along.

---

## [ARCH-20] A filed plan outlives the steerpoints it names — #129
labels: bug

**Status:** CLOSED 12 August. Attested by claude at 8587385.

    "wait.. why are those fixes coming from the flight plan????"
    "Private fixes should only live in a flight plan"

The second sentence is the whole answer and it was settled days before I broke
it. There are two kinds of fix and they have different owners:

    PUBLIC   on a plate, known to everybody, in the theatre catalogue.
             DIOMI, UMROS, INITIAL. A plan may name one; it may not define one.
    PRIVATE  named by the pilot, defined BY THE PLAN THAT NAMES IT.
             FOO, BAR, SPAM. Resolvable to anybody holding that plan and to
             nobody else, which is what "private" means.

I put the private ones in the PUBLIC table. That table is owned by the bridge
and REPLACED on every start -- correctly, so a Nevada run cannot keep Caucasus
fixes -- so a pilot's own steerpoints were deleted by a restart and his filed
route stopped resolving:

    ATC: Your BatumiTest routing is via fix points not held at this station —
         unable that plan as filed.

Technically true and it reads as the plan being wrong. It happened twice: once
the night it was built, and again after four restarts spent fixing something
else.

**Fixed.** `flight_plans.legs` already carried `{fix, alt_ft}` (migration 030);
it carries `lat`/`lon` too, so a plan is self-contained. `plans.route_fixes`
resolves a name against the public catalogue first and then against the plan's
own legs; `filing.check_live` accepts a route naming a fix the plan defines.
Nothing is written to the shared table, so nothing can delete it.

Proved by doing the thing that used to break it: filed BatumiTest via FOO, BAR,
SPAM and INITIAL, restarted the bridge so the catalogue was republished without
them, and the plan still validated clean and still cleared —

    cleared to Batumi, as filed, maintain five thousand, expect one zero
    thousand one zero minutes after departure, departure frequency one two
    three decimal three, squawk six four six seven

**What is still not built** is the half the pilot actually asked for: a
controller SAYING one. "Report passing BAR" needs the private fixes reaching
the ATC side, which they now can — the plan holds them and `assigned_plans`
copies the plan at clearance. Tracked as #133.

---

## [ARCH-21] A flight plan is a route somebody filed, and nothing else — #131
labels: architecture

**Status:** CLOSED 12 August. Attested by claude at 5be4dcb — the bridge reads
`theatre.approach_key` directly with no round trip; `departure_freq(field)`
comes off `sectors` (Kobuleti 123.3, Batumi 124.425, previously the same number
to that code); the `unfile` guard is gone and the finished plan was deleted and
stayed deleted across a restart. Not `needs-flight-test`: every claim is
structural and a machine answers all of them.

    "i dont understand this active business. sounds like mis-alignment between
     you and me"
    "whyt would the bridge load a default approach column?? doesnt make sense"

Both right. `flight_plans` was doing two unrelated jobs, and the second one was
not about flight plans at all:

    a route a pilot filed and may request        <- what it is for
    where the bridge parks "which arrival am     <- `active` + a round trip
    I running tonight"

**The round trip.** The bridge wrote `theatre.approach_key` onto a flight-plan
row with `active=true`, read the row straight back, and rebuilt the approach
profile from it — a journey with itself, for a value it was holding the whole
time. The only thing it added was a chance to come back different, which is
exactly what happened: `_approach_named` matched on a prefix and returned the
surveillance approach for a plan filed as `batumi-ils`, and a whole sortie was
flown as a talkdown (see the commit that fixed it).

**What it cost a pilot.** Finishing with a route and trying to remove it:

    "362nd-kobuleti-batumi is the ACTIVE plan — the bridge reads the approach it
     runs from this row. Make another plan active first."

There was no way to make another plan active — no endpoint, no button — and
anything set by hand was overwritten at the next bridge start. The refusal named
an action that could not be taken and would not have held.

**Fixed:**

  * the bridge reads its own theatre and never asks the director back
  * `departure_freq` reads `sectors`, which carries the FIELD on every row —
    it took "the first departure station in the active plan's profile" before,
    which is field-blind, so a pilot cleared out of one aerodrome could be given
    the other's departure frequency. Kobuleti 123.3, Batumi 124.425, and they
    were the same number to that code.
  * `unfile` has nothing left to guard
  * the start-up line says `approach: batumi-ils (from the theatre)` rather than
    naming a flight plan it does not load — it was printing the name of a row
    that had just been deleted

**Still open, and it is the rest of #2.** `ApproachProfile` carries the theatre's
reference data (stations, fields, minimum altitudes) AND one arrival procedure,
so the bridge cannot have the first without defaulting the second. It should not
have a default: which approach you are flying is a fact about your clearance,
and until you have asked for one the honest answer is that the controller has
none for you. `MARSHALL_APPROACH` is a symptom of the same thing — an
environment variable pre-selecting an arrival the bridge should not be choosing.

---

## [SEAM-16] The read-back correction had no exit, and ran for the whole sortie — #134
labels: bug

**Status:** CLOSED 12 August. Not `needs-flight-test`: every claim is
structural and the evidence is the recorded transcripts, replayed verbatim.

    "If the partial readback isn't issuing me a clearance, it should say so."
    "how can a clearance not be issued due to a readback problem then every
     body just continues as though nothing is wrong?"

On 12 August this went out **eight times**, the last two on short final and
after landing at the other aerodrome:

    Sockeye, negative — say again one zero thousand,
    one two three decimal three, three three five zero.

The pilot logged it as three separate faults — a squawk being re-issued, the
wrong field's departure frequency, and a controller who had lost the flight. It
was one function reciting his departure clearance at him for twenty-six minutes.

**Three faults, stacked, and the first one is the interesting one.**

*A correct read-back was judged wrong.* `decision._said_words` refuses a match
whose next word is another number word, so that "one three" cannot match inside
"one three three decimal zero". Correct for a runway; fatal for everything else,
because a number ending in a magnitude is FINISHED and what follows it is the
next fact:

    maintain one zero thousand, one two three decimal three
                                ^ the altitude was reported missing

*And a read-back through Whisper is not spelled the way `say.py` spells it.*
The controller SYNTHESISES "one zero thousand"; the pilot is HEARD, and what
came off the radio was `expect 1,000, 1, 0 minutes`, `frequency is 1, 2, 3
decimal, 3`, `squawk 3, 3, 5, 0`, `1-0,000`. Every one is the right number,
correctly read back, and none matched either spelling — the words are not
present and no single digit token equals the value.

*So the exchange became unwinnable.* Told two elements were missing, he read
back exactly those two — and was judged against the WHOLE clearance again, so
the frequency he had got right the first time became a miss:

    ATC:   negative — say again one zero thousand, three three five zero
    PILOT: we expect one zero thousand, one zero minutes after departure,
           and we're going to squawk three three five zero
    ATC:   negative — say again one zero thousand, one two three decimal
           three, three three five zero

There is no transmission that ends that. `clearance_ack` is only written when
the read-back is judged fully correct, so it was never written — and the guard
that stops the check running (`if plan.get("acknowledged")`) never fired. Every
later read-back of every OTHER instruction was then judged against the departure
clearance: his taxi read-back on the ramp, his ILS clearance read-back at thirty
miles, and "clear of the active" after he had landed.

**Fixed.** A number ending in a magnitude, or carrying a decimal, is finished.
Split digit tokens are rejoined and every contiguous slice of a run is a
candidate, so `1 0000 1 0` yields the ten thousand he said and not the
1,000,010 a greedy join produces. The read-back is cumulative — what he has
already said correctly stays said. And a read-back belongs to the man who
ISSUED it: the IFR clearance is Clearance Delivery's, and once he has let go
nobody else judges a read-back of it.

Proved against the recorded transcripts rather than a tidied version of them —
see `tests/test_read_back.py`, which replays both transmissions verbatim.

**Flown on 13 August, and two more of it came out.** `tools/ghost_flight.py
--sortie` put a synthetic pilot on the ramp at Kobuleti and made him read a
clearance back badly on purpose. The exchange still could not terminate, for two
reasons neither of which the 12 August transcripts contained:

*A radio says "tree" for three, and Whisper writes down what it hears.* The
read-back came back as `1-2-3 decimal tree`, and on the next sortie as `123
decimal tree` — every character of the right number, in three notations at
once. The word form was not present (`tree` is not `three`, and `1 2 3` is not
`one two three`) and the digit rejoin stopped at the `decimal`, because what
followed it was a word, leaving a trailing point that was discarded. He was
asked to say again a frequency he had just said. `_normalise` folds the four
ICAO spellings onto the ordinary ones now, and a spoken digit may finish a run
of written ones — ONLY a mixed run, because rejoining a run of pure words
would satisfy a runway with a frequency, which `_said_words` exists to refuse.

*And `clearance_ack` was never written, on any sortie, ever.* `_flight_id_of`
asked `/flights` with no mission, so it walked the rows of a mission called
"default" — which no real sortie is — found nobody, returned 0, and
`_ack_the_clearance` gave up silently every time. Nothing had noticed because
nothing downstream read the column: the engine's own `clearance_agreed` was set
in memory by `clearance_read_back`. The moment #135 started reading the board,
it mattered:

    ATC  Marlin four two, readback correct, contact Kobuleti Ground
    ATC  Marlin four two, your IFR clearance has STILL not been read back

Both fixed and both flown. The next sortie read its clearance back sloppily, was
corrected once, was agreed, and had `clearance_ack` on the row before it moved.

**Still open, and it is the pilot's second sentence.** A clearance that was
never agreed did not stop anything: Ground issued taxi to an aircraft with no
IFR clearance and nobody said a word. That is #135.

---

## [SEAM-17] Ground taxied an aircraft whose clearance was never agreed — #135
labels: bug

    "And when I ask ground to taxi with no clearance — why does he let me go.
     Talk about swallowing an error."

The read-back loop of #134 meant `clearance_ack` was never written. Nothing
downstream cared. He asked Kobuleti Ground for taxi and was given it, was handed
to Tower, was cleared for take-off, and flew a full sortie to Batumi — the whole
ladder, on a clearance the board still recorded as ISSUED and never AGREED.

#105 made FILED, ISSUED and ACKNOWLEDGED three real states precisely so this
question could be asked. It is asked in exactly one place — the read-back check
itself — and by nothing that acts.

**What it wants.** A rung that requires a clearance must refuse without one, and
say which state he is actually in: "your IFR clearance has not been read back,
contact Clearance on one two five decimal one" is a controller doing his job.
Silence is the failure mode this codebase keeps producing — an error that
changes nothing and is therefore indistinguishable from success.

**Built, and it was dead code until 13 August.** `Controller.request_taxi`
refuses on `clearance_agreed is False`, and that field was written in exactly
two places: `hydrate`, which runs once when the bridge starts, and
`clearance_read_back`, which only ever sets it TRUE. Nothing in a live sortie
could set it False, so the guard could not fire — and the unit tests kept it
green by assigning the field themselves. A ghost flown down the ladder asked
Ground for taxi on a clearance he had never read back, and was cleared to the
runway.

`note_clearance_agreed` is the writer that was missing: beside
`note_cleared_level`, off the same board read, on every turn. The engine did not
issue the clearance and cannot know one exists unless it is told.

**And the refusal moved him on anyway.** `request_taxi` writes `sortie_phase =
"taxi"` before it decides anything, which is right for a man on the wrong
frequency and wrong for one who has just been refused: THE PHASE IS THE HANDOFF,
so `taxi` means Ground has him. In consecutive transmissions:

    ATC  your IFR clearance has not been read back, contact Kobuleti Clearance
    ATC  readback correct, contact Kobuleti Ground one two one decimal eight

which is this issue's own complaint back again, with the refusal audible and
changing nothing. He stays on Clearance's rung now until Clearance is finished
with him — #82's shape, one method over.

Tests: `GroundCanActuallyRefuse` and `ARefusalDoesNotMoveHimOn` in
`tests/test_a_sortie_is_flown_end_to_end.py`; the refusal itself is held by
`GroundDoesNotMoveAnAircraftOnAnUnagreedClearance` in
`tests/test_ground_procedure.py`.
Code: `src/marshall/atc/controller.py`, `src/marshall/atc/agent_atc.py`.

**Status:** CLOSED UNVERIFIED 13 August — flight-test bankruptcy, not a pilot's word. Flown by a synthetic pilot end to end: refused
with the frequency at 01:17, agreed at 02:36, taxied. Whether it SOUNDS like one
controller is still a pilot's. Card row Q3c is the one that asks it, and it is
struck through — flown, so what remains is the ear, not the structure.

---

## [HO-6] Center issued an approach clearance, and the ladder ran backwards — #138
labels: bug

Batumi Approach never cleared him for the approach. Georgia Center did — twice:

    04:52:00  Sockeye, cleared I-L-S approach runway 13, report established
              on the final approach course.
    04:56:33  Sockeye, cleared I-L-S approach runway 13, continue.

    "approach, never actually cleared me for the approach, and never asked if
     I have information alpha"

An approach clearance is Approach's. A Center controller who issues one has
issued a clearance he does not own, which is the aerodrome half of the invariant
in `CLAUDE.md` — the same shape as a Ground controller putting an aeroplane on
the runway.

**And the handoff has no direction.** Having checked in with Batumi Approach at
04:53:02, he was handed BACK to Center at 04:54:45, 27 nm inbound. Then Tower
tried to hand him to Approach four times — 05:03:42, 05:04:16, 05:04:20,
05:04:47 — at four, two and one miles on final:

    "he just tried to transfer me back to approach when I was within five
     miles on the final"

Nothing in the rule table says a rung already passed cannot be offered again, so
distance alone decides and an aircraft on final is geometrically "in Approach's
airspace" for ever.

Related and probably the same absent rule: no landing clearance was ever issued
(Tower's whole transmission at 05:03:36 was "Sockeye, Batumi Tower"), and after
he parked, Ground sent him back to Tower "for landing" — which is #100.

**Status:** CLOSED UNVERIFIED 13 August — flight-test bankruptcy, not a pilot's word. Both halves are in code and guarded, and no
commit closes it. `Controller.request_approach` refuses a clearance the speaker
does not own and names who does (`_owns("approach")` / `_not_mine`, `88bbc6e`),
and the direction test is now ONE function — `agent_atc.coming_towards_us`,
read by all three rungs (`655bf90`) — with
`NobodyIssuesAClearanceThatIsNotHis` and `AnInboundAircraftIsNotLeaving` in
`tests/test_the_ladder_has_a_direction.py` green. The airspace half still rests
on that heuristic until #139 lands, and no pilot has flown an arrival since.

---

## [OPS-18] Nevada's TONOPAH fix is thirty kilometres from the sim's own VORTAC — #141
labels: bug

Found while moving Nevada's catalogue into configuration (#137), by looking for
a citable source for its coordinates. The vendored `nevada-Beacons.lua` is the
sim's own data and carries both frames for every beacon:

    Silverbow  TQQ  BEACON_TYPE_VORTAC  113.000
      position    = (-227436.9, ..., -174559.0)
      positionGeo = (37.790475, -116.779233)

`core/nevada.py` says:

    TONOPAH  x = -200809  z = -196936  freq_mhz = 117.2

That is **~34 km away, on a different frequency**, and the Tonopah FIELD sits
at (-226613, -174653) — within a kilometre of the VORTAC and nowhere near the
fix named after it. So either the fix is wrong, or it is deliberately some
other point and badly named.

It matters because the fix is the beacon of `tonopah-ils`: every range and
radial that approach speaks is measured from it, and each one is a plausible
number. This is the [ARCH-18] shape again — three sources, and only somebody
who has flown it can say which is right.

**Not guessed at, and Nevada is therefore NOT converted.** Its fields, stations
and procedures could move today; its published fixes cannot, because publishing
one means writing down a coordinate and a source, and I have two candidates and
no way to choose. Picking the prettier one would put a real-looking number in a
file with a citation next to it, which is worse than leaving it in Python where
its provenance is at least visibly absent.

**What it needs:** a Nevada sortie, or `coord.LOtoLL` asked with that map
loaded. `vendor/dcs/nevada-Beacons.lua` pairs `position` with `positionGeo` for
all 45 beacons, so once the right point is known the seeding is mechanical --
and the same file makes Caucasus verifiable without a running server too, which
is worth doing whichever way this goes.

---

**RESOLVED 13 August, without a sortie. This issue compared the fix against the
wrong VORTAC.**

`nevada-Beacons.lua` carries TWO Tonopah-area VORTACs, and only one of them is
in the text above:

    Silverbow   TQQ   113.000   (-227436.9, -174559.0)   <- what #141 measured
    Tonopah     TPH   117.200   (-200809.97, -196936.80)  channel 119

`core/nevada.py`'s fix is `x = -200809  z = -196936  freq_mhz = 117.2`. That is
**1.3 m from TPH and on TPH's exact frequency**; the geo positions agree to
zero. There were never two candidates. Position and frequency each identify TPH
on their own, and together they leave nothing to choose between.

**What made it look wrong is #163.** The reasoning was "a fix named TONOPAH is
34 km from Tonopah airfield, so one of them is wrong" — and that is exactly the
conflation #163 is about. TPH is an ENROUTE VORTAC that carries the town's name.
It is not the airfield's beacon and was never meant to be near it. A beacon is
not an airfield; #141 is the same defect wearing a coordinate.

So Nevada's fixes were never blocked, and the block was the only reason #137
listed Nevada as unconverted. Both are cleared: `9275c81` publishes them with
`nevada-Beacons.lua` cited as the source.

**Status:** CLOSED 13 August — commit `dfbdffa`. Resolved from the sim's own
vendored data, not from a flight. The remaining Nevada caution is in #163: the NELLIS fix wears the
LSV TACAN's ident while sitting at the aerodrome reference point, which is the
same conflation in the other direction and is that issue's to fix.

---

## [FP-8] A flight plan was a bag of columns, half of them the clearance's — #142
labels: architecture

**Status:** CLOSED 12 August. Structural throughout; the suite and the live
board both check it.

    "the origin should be determined at request time, the destination is the
     last point. We should not define an approach in the flight plan. there
     should be no cruise alt in flight plan."

`flight_plans` carried thirteen columns and only three of them described a
flight plan.

**Two copies of the route, and they had already drifted.** On the live board:

    route : FOO, BAR, SPAM, INITIAL
    legs  : FOO, BAR, SPAM, BATUMI

`route` was a string validation read; `legs` was the structured list with
positions that the map and the clearance read. Nothing kept them in step.

**And four columns that belong to the CLEARANCE, not the plan** — which the
schema had already half-admitted, because `assigned_plans` has carried its own
`origin`, `destination`, `route`, `cruise_ft` and `approach` since migration
009. `approach` on the plan is what let the bridge read its own arrival out of
a plan row (#131) and fly a man a talkdown after he asked for an ILS.

**Fixed** (migration 031). A plan is `label`, `legs` and `task`. `route`,
`destination` and `cruise_ft` are computed by `filing.derived` from the one
list that has positions in it; `origin` is settled when he asks for his
clearance; `name` is generated from the label rather than typed, because two
hand-authored identifiers for one plan was one too many and the label is the
one with a reason — it has to survive being said out loud through Whisper.

The /file form stopped asking for five things it had no business asking for,
and `task` is read from the cartridge's `KneeboardNotes` — the one field where
a pilot describes his own sortie — rather than defaulted to the string
"training", which told a controller nothing and made every plan score alike.

**A mistake worth recording:** I dropped the columns before backfilling, and
two Nevada plans that predated `legs` lost their routes. Recovered by hand and
the migration now backfills first, so no other database repeats it.

**Amended 13 August — a filed plan is now editable, and the key is not.**

    "maybe we should just be able to edit the label, but the name key is
     immutable (unless deleted)"

Opening a row on `/file` gives you its label, its task, and a cartridge box
that replaces its steerpoints. All three go back through `/plans/check` and
`/plans` with `updating` naming the row, so the rules are the ones that refuse
a new filing — renaming onto another plan's label is refused by the director,
not by the page.

`name` is generated from the label ONCE and never again. It is the FK target
of `assigned_plans.template`, which is `ON DELETE SET NULL`, so a re-key done
as delete-and-insert would quietly cut a pilot's clearance loose from the plan
he was cleared on and leave the old row behind under the old key. After a
rename the key no longer matches the label, and that is what a key is for: it
stays still while the human-facing name moves. It is shown nowhere.

**A bug that immutability creates, fixed in the same commit.** File Domino
(key `domino`), rename it to Marlin: the LABEL Domino is free again while the
KEY `domino` is not. The next plan filed as Domino derived the same key and
`file_plan`'s `ON CONFLICT (name) DO UPDATE` rewrote Marlin's label, legs and
task in place — reporting success, and changing the plan under any clearance
pointing at that key. `filing.next_key` gives the new plan `domino-2`; nobody
types a key, so a suffix costs nothing and the label stays the one identifier
with rules. `file_plan` also refuses an `updating` that names no row, which
otherwise re-created a deleted plan under a key derived from nothing.

---

## [FP-9] A private fix could silently take a published fix's name — #143
labels: bug

**Status:** CLOSED 12 August.

    "I created a private fix called INITIAL this seems to be conflicting with a
     public fix? ... How should we handle naming conflicts like this"

Badly, and silently, which is the worst available answer. `plans.route_fixes`
resolves the published catalogue FIRST, so a plan whose own leg is called
INITIAL had that leg discarded and the controller vectored to the PUBLISHED
initial approach fix instead. The pilot means one place, the controller means
another, both are real points, and every range and bearing spoken is perfectly
plausible. That is the shape of every bad hour this project has had.

**The rule is about DISAGREEMENT, not about the name.** A cartridge carries a
position for every steerpoint including the destination, so a plan routing to
BATUMI arrives with BATUMI's own coordinates — the same aerodrome, not a
redefinition. Refusing on the name alone rejects an ordinary flight plan, which
I nearly shipped. So: a plan may NAME a published fix, and may carry its
position, but if that position is more than a mile from the chart's it is
refused and told how far off it is.

Shadowing the other way is no better: a plan that redefined DIOMI for its own
convenience would make one word mean two places depending on who is holding
which piece of paper.

---

## [FP-10] INITIAL is invented, and its source line said otherwise — #144
labels: bug

**Status:** CLOSED 12 August — the citation is honest now. Whether a fictional
scenario should publish invented fixes at all is left open deliberately.

    "And, we probably made up the fix called INITIAL huh?"

Yes. `core/fixes.py` shows its ident was CHOSEN rather than read:

    # Beacon idents must NOT resemble the letters the ARA-8 keys for homing --
    # U (..-), D (-..), A (.-), N (-.). An earlier build used B (-...), one dot
    # from a homing D, and the two were indistinguishable in flight.
    INITIAL = Fix("INITIAL", "SW", ...)

When the published catalogue moved into configuration (#137) I gave every fix a
REQUIRED `source`, and wrote INITIAL's as *"On the 1944 Batumi letdown plate as
the initial approach fix"* — which describes a ROLE and reads as a CITATION.
That is precisely the failure a required source field exists to prevent, and I
committed it hours after refusing to do the same thing to Nevada's TONOPAH
(#141) on exactly that ground.

The line now says it is invented, that the plate is one we generate, and why
the ident is what it is. Published because it is on the plate the pilot holds —
published BY US, which is a different claim from published by an AIP.

---

## [HO-7] Tower gives a man on final back to Approach, because "airborne" is a state read as an event — #146
labels: bug

The #138 fix stopped this in one of the three places that can decide it, and
the place it did not reach is the one that outranks the other two.

`next_controller` is a cascade — the sim's events, then the ladder, then the
airspace volumes — and #138 put the direction test into `leaving_my_airspace`,
which is the THIRD rung. The first is `handoff_on_the_event`, which reasons:

    not on the ground, and I am Tower  ->  he got airborne, give him to Approach

`on_ground` is a STATE, not the moment it changed. It is equally true of a jet
that has just rotated and of one four miles out on a final approach — so an
arrival on Tower's frequency was handed straight back to Approach, which is the
transmission the pilot got four times inside five miles on 12 August and the
one #138 was written to stop.

**Found by `tools/ghost_flight.py --inbound`**, the first thing that has ever
flown an arrival rather than a departure. Two authorised handoffs two hundred
yards apart, in opposite directions, both correct by their own branch:

    06:20  4.7 nm  Dagger one six, contact Batumi Tower one one eight decimal six.
    06:32  4.5 nm  Dagger one six, contact Batumi Approach one two four decimal
                   four two five.
    06:36  4.5 nm  Dagger16, roger, contact Batumi Approach, one two four
                   decimal four two five.

The last two are the monitor and the receive path arriving at the same wrong
answer independently, which is what one shared cascade is supposed to prevent
and does — it is the cascade's own first rung that is wrong.

**Fixed.** Airborne means DEPARTING, and whether he is departing is a fact we
hold: `handoff_on_the_event` now takes the fix and declines the tower ->
approach direction for an aircraft pointed at the field. The landing direction
(approach -> tower) is untouched, and a controller with no radar picture — no
fix — behaves exactly as before, because a guard that needs a picture must not
disarm somebody who has none.

**And the trend test was written out three times and enforced in two**, which is
how the third one got missed. It is one function now, `coming_towards_us`, read
by `_handoff_state`, `leaving_my_airspace` and the event branch.

Tests: `AirborneIsNotAnEvent` and `OneDefinitionOfInbound` in
`tests/test_the_ladder_has_a_direction.py`; the harness that found it is guarded
by `tests/test_ghost_flies_an_arrival.py`.
Code: `src/marshall/atc/agent_atc.py`, `tools/ghost_flight.py`.

**Status:** CLOSED UNVERIFIED 13 August — flight-test bankruptcy, not a pilot's word. A ghost flew it, structurally, and the rerun is
clean. A pilot still has to fly a real arrival and hear whether the frequency
he is left on is the right one. Re-checked 13 August: `handoff_on_the_event`
still declines the tower-to-approach direction for an aircraft
`coming_towards_us`, and `AirborneIsNotAnEvent`, `OneDefinitionOfInbound` and
`tests/test_ghost_flies_an_arrival.py` are green. Nothing has moved.

---

## [ATIS-4] The runway in use is measured, and the wind spoken beside it is a constant — #148
labels: bug

Found by the `STRUCTURE.md` reconciliation, which set out to date a document
and turned this up on the way.

`STRUCTURE.md` proposed, on 31 July, that the declared wind become a measured
one: *"a hardcoded constant that the sim will now tell us, and the runway in
use is computed from it. A declared wind is a stored answer to a question with
a live input."* **Half of that shipped.** `atis/weather.py` samples the sim's
wind ten metres above each field — deliberately not at the surface, because
DCS's boundary layer reports calm on a usable day — and `atis/store.py` writes
the resulting runway to the `atis` table. `Controller._runway_in_use` ASKS that
table rather than recomputing, which is the whole point of it.

**The wind itself was never rewired.** `WIND_FROM_DEG = 90.0` is still a module
constant in `core/units.py`, and it is what gets said and drawn:

    core/fields.py:126        Field_.active_end falls back to it
    atc/controller.py:1968    _wind_phrase, on every landing and take-off
    atc/assembly.py:487       the clearance
    atc/briefing.py:155,450   the printed brief
    kneeboard/navlog.py       the nav log
    kneeboard/e6b.py          the E6B
    kneeboard/asr_plate.py    the plate
    mission/build.py:500      the .miz weather itself

`controller.py:1862` is the sharp end, because it puts both in one sentence:

    f"{self._runway_in_use()}, {self._wind_phrase()}"

The runway asked from the measurement; the wind read from the constant. So
Tower can clear an aircraft to land on the runway the measured wind chose while
naming a wind that did not choose it — and on a day when the sim's wind is not
090, the ATIS broadcast and the landing clearance disagree about the same
number at the same field. The comment three lines above reads *"so all three
name one runway"*, which is true, and is precisely the fix that did not follow
the wind through.

This is the failure this project exists to prevent, one field over: the chart
and the radio disagreeing. It has survived because the Caucasus mission's
declared wind and its sim wind have been close enough not to change a runway.

**Remaining scope.** The wind is an observation, so it belongs where the
observation lives: `atis` already holds it per field per instant. The spoken
and drawn wind should be read from there, with the constant surviving only as
the fallback for a component with no sim — and saying so, rather than silently
substituting. `mission/build.py` is the exception and should stay: it AUTHORS
the mission's weather, which is the one place a declared wind is the right
answer.

**Acceptance criteria**
1. `Controller._wind_phrase` reads the same source as `_runway_in_use`, so one
   sentence cannot carry two winds.
2. The kneeboard's wind and the ATIS broadcast's wind agree for a given field
   at a given time, and a test asserts it.
3. A component with no sim says which wind it is using rather than presenting
   the fallback as an observation.
4. `mission/build.py` still declares the mission's wind, and the declared value
   is what ATIS then measures.

Tests: a new case beside `tests/test_two_fields.py`, since "the wrong answer is
always plausible" is the same shape.
Code: `src/marshall/core/units.py`, `src/marshall/atc/controller.py`,
`src/marshall/atis/`, `src/marshall/kneeboard/`.

**Status:** FIXED 13 August — commit `b55c589`, the one entry in this run with a
real `Closes` trailer. The wind has one author per aerodrome and it is the
row the runway came out of. `Controller._wind_phrase` asks `atis.store.wind(his
field)`, beside `_runway_in_use`, so the sentence cannot carry two winds; the
broadcast and the clearance are phrased by one renderer (`Wind.spoken`), so
"calm" is a word in both mouths. `units.WIND_FROM_DEG`/`WIND_MPH` are DELETED:
the declared wind is `[theatre] wind_from_deg/wind_mph` in the map's TOML, and
`R.WIND_*` resolves onto it through `route.__getattr__` — so `mission/build.py`
still authors the .miz weather from the declaration, and ATIS measures that
back. `Wind.observed` carries the provenance rather than leaving it to be
inferred, and the surfaces that can only ever have the declaration say so: the
nav log's WIND (FCST), the plate, the comms card, the squadron brief, and the
agent's plate, which is now told plainly that the wind it SAYS is the ATIS's.
`runway_in_use()` with no wind given is the map's declaration too, not the
Caucasus on every map. Guarded by `tests/test_the_wind_has_one_author.py` (15
cases, the sharp one behavioural: an ATIS on the air with weather the
declaration does not describe).

Criterion 2 is met the only way it can be: a kneeboard is generated before the
sim is started, so it shows the DECLARED wind — which is what the mission is
built with and therefore what ATIS measures back. A live chart that reads the
`atis` table is not built and is not wanted until the pages are generated
per-sortie rather than per-container (#137).

---

## [HO-8] "Nothing has told us" is written down three times and read as "he is flying" — #149
labels: bug, architecture

Found by the audit for #146's siblings, 13 August. It is the same defect one
line above the one that was fixed.

**The third answer exists and is documented everywhere it is written.**

    feed/tracks.py:718     "NULL here means the sweep has not run yet, and that
                            is not the same as 'airborne'"
    feed/tracks.py:996     "`in_air IS NULL` ... not down, not flying, not known"
    core/scope.py:124      "NULL means nobody has asked yet, which is a third
                            answer -- and reading it as 'airborne' is what told
                            a parked Mustang it was flying"
    atc/identity.py:140    "False means either 'airborne' or 'nothing has told
                            us', and the caller keeps its own fallback"

**And it is collapsed at every boundary.** `core/scope.py:127` is the sharp
end — `"on_ground": (t.in_air is False)` — which maps NULL and TRUE onto the
same output. `feed/tracks.py:719` and `:998` do the same for the director's own
rendering. By the time `identity.Unit.on_ground` reaches a caller there are two
states where the database has three, and the comment quoted above survives to
tell the reader about a distinction the value no longer carries.

**Who reads it as a definite answer.** `agent_atc.handoff_on_the_event` — the
FIRST rung of `next_controller`'s cascade, the one #146 was about:

    if not unit.on_ground and role == "tower":
        return profile.station_for("approach", field=fld)

Its own docstring closes with *"Silent unless the sim has actually said so.
`on_ground` is False both for an aeroplane in the air and for one nothing has
been reported about, and this must not fire on the second"*. It fires on the
second. The only guard it has is `unit is None` — not on the picture at all —
which was sufficient when the flag came from land/takeoff events and stopped
being sufficient when it moved to a swept column that starts NULL.

`sim_state` has the same shape one function along: a unit on the scope whose
ground state nothing knows, with no radar position, is reported as `airborne`
to the board and to the agent's prompt.

**Why it has not bitten hard.** The window is one sweep — a unit appears, and
`_note_in_air` fills the column on the next pass. It is widest exactly where it
is worst: a fresh mission, a director restart, an aeroplane spawning on a ramp
while a controller is being asked who has him. #114 is the same column read
wrongly in the other direction and cost a whole map's ground ladder.

**Remaining scope.** Carry the third state instead of documenting its loss:
`in_air: bool | None` on the contact dict and on `identity.Unit`, `on_ground`
kept as the convenience it already is, and the branches that mean *"the sim
says he is flying"* asking for positive evidence. The prose path has no third
state and cannot get one, so it keeps today's behaviour and says so.

**Acceptance criteria**
1. A contact whose ground state is unknown is distinguishable from one the sim
   says is airborne, at every layer between `tracks` and `handoff_on_the_event`.
2. `handoff_on_the_event` does not offer Approach to an aeroplane nothing has
   reported a ground state for, and a test asserts it.
3. `sim_state` does not report `airborne` for such an aeroplane.
4. Nothing in `core/scope.py` or `feed/tracks.py` writes a comment about a third
   answer next to an expression that discards it.

Tests: beside `tests/test_events.py` and `tests/test_the_ladder_has_a_direction.py`.
Code: `src/marshall/core/scope.py`, `src/marshall/atc/identity.py`,
`src/marshall/atc/agent_atc.py`, `src/marshall/feed/tracks.py`.

**Status:** FIXED, and this entry was stale — the FIFTH found by the same
grooming sweep on 14 August. All four criteria are met and
`tests/test_nothing_has_told_us_is_not_he_is_flying.py` asserts them, 16 tests
passing. It is not a characterisation test, which is what I took it for on
first reading.

1. `in_air: bool | None` is carried on the contact dict by BOTH producers —
   `core/scope.contacts` and `feed/tracks` — and on `identity.Unit`.
2. `handoff_on_the_event` tests `unit.in_air is True`, which is positive
   evidence and cannot be satisfied by silence.
3. `sim_state` returns `""` rather than `"airborne"` for an aeroplane with no
   report and no position.
4. Every comment about the third answer now sits beside a value that carries
   it, and each says what it used to drop.

**How I misread it, because the misreading is the interesting part.**
`core/scope.py` still contains `"on_ground": (t.in_air is False)` — the exact
line this issue quotes as the sharp end — and I matched that string and
concluded nothing had changed. The line is now correct: `in_air` is emitted on
the line ABOVE it, and `on_ground` was always meant to stay as the convenience
it is. A string that appears in the fix as well as in the fault cannot tell
them apart, which is the fourth time that error has cost something today.
---

## [SEP-16] `landed` may only follow `approach`, so the sim's own fact is refused — #151
labels: bug

Exposed by the `has_flown` fix (#154), 13 August. `phases.derive` opens its reasoning
with *"DOWN IS THE ONE FACT NOBODY ARGUES WITH. The sim says so outright, and it
settles both ends of the sortie"* — and then `may_follow` argues with it:

    approach  -> landed     legal
    arrival   -> landed     REFUSED
    departure -> landed     REFUSED
    holding   -> landed     REFUSED
    missed    -> landed     REFUSED
    enroute   -> landed     REFUSED

All five of those are things an aeroplane does. A straight-in that was never
formally cleared is in `arrival` when the wheels touch; a departure that comes
straight back is in `departure`; a pilot who breaks off a hold and lands is in
`holding`. In each case the sim states the fact, `derive` wants `landed`, the
table refuses, and the phase is kept.

The refusal is at least AUDIBLE now — `phase REFUSED: arrival cannot lead to
landed` — which is what #91 fixed and is the whole reason this is visible rather
than silent. Before the `has_flown` fix these transitions were never even
proposed, because the bridge answered "has he been airborne" with a count of
go-arounds.

**What it costs** is the end of the sortie: `landed` is Tower's and `taxi_in`
follows it, so a phase that never reaches `landed` cannot hand him to Ground
(#77), and `intents` reads the same field to tell "taxi to parking" from "ready
to taxi" (#100).

**What it probably wants.** `landed` follows any phase in which he is airborne,
because touching down is not a procedural transition that can be illegal — it is
an observation. The one that should stay refused is `landed` from a GROUND
phase, which is the case `follows` was written to protect.

**Acceptance criteria**
1. An aeroplane the sim says is down reaches `landed` from every airborne phase.
2. A parked aeroplane that has never flown does not, and the test for it stays.
3. No `phase REFUSED: ... cannot lead to landed` line appears in a normal
   recovery.

Tests: `tests/test_phases_derive.py`, which characterises the current behaviour
in `LandingOutOfAnArrivalIsRefusedByTheTable`.
Code: `src/marshall/atc/phases.py`.

**Status:** FIXED, and this entry was stale — found by a grooming sweep on
14 August, not by anybody hitting it. `phases.py` names `landed` in `follows`
for every airborne phase, with a comment citing this issue and giving its
argument: *"touching down is an OBSERVATION, not a procedural transition, and
an observation cannot be illegal."* Verified behaviourally, not by reading:
every airborne phase reaches `landed`, no ground phase does.
---

## [ASR-9] An empty station list is a MODE SWITCH, in two places — #152
labels: bug, architecture

The other half of #140, and the reason that issue's *"the fix belongs in its own
commit"* is right. #140 records that `BATUMI_APPROACH` carries `stations=[]` and
therefore has no frequencies. What it does not record is that two call sites
read the emptiness as a STATEMENT ABOUT THE ERA rather than as a gap:

    core/approach.py:603      if self.stations:  ... else: derive the station
                              from the FIX -- "on a beacon letdown the station
                              is derived from the fix instead"
    agent_atc.py:5156         if getattr(profile, "stations", None): channels =
                              every station's frequencies
                              else: the arrival fix, the beacon, the outer hold

So "which frequencies does this bridge listen on" and "who works this phase of
the arrival" are both answered by asking whether a LIST IS EMPTY. That is the
same shape as `check_in` concluding *"the controller has no radar"* from the
mere presence of `profile.arrival_fix` (fixed in `1e35bf9`) — a capability
inferred from the shape of neighbouring data, with `AtcCapability` sitting
unread beside it.

**It makes #140 unfixable by data alone**, which is the finding. Filling in
`BATUMI_APPROACH.stations` does not merely give a blind controller some
frequencies: it silently flips both branches, so the bridge stops monitoring the
beacon channels a P-51's ARA-8 is tuned to and `station()` stops returning the
controller who sits on the beacon being flown. The comment at `approach.py:120`
explains exactly why that matters — *"a phase's controller must live on the
beacon flown in that phase"* — and nothing enforces it except the empty list.

**What it wants** is the thing the mode switch is standing in for, said out
loud. A procedure knows whether its controllers live on beacons; that is a
property of the ERA and of the aeroplane's radio, and `AtcCapability` is where
properties of that kind already live.

**Acceptance criteria**
1. No branch anywhere decides how a controller is reached by testing whether
   `stations` is empty.
2. `BATUMI_APPROACH` can be given the theatre's stations without changing which
   channels the bridge monitors, and a test asserts both halves.
3. #140 becomes a data change.

Tests: beside `tests/test_two_fields.py`.
Code: `src/marshall/core/approach.py`, `src/marshall/atc/agent_atc.py`,
`config/theatres/caucasus.toml`.

**Status:** FIXED 13 August — commits `d5e243b` and `1589364`, and the line that
stood here ("OPEN — blocks #140") was stale. `ApproachProfile` has no `stations`
attribute at all any more; the mode switch is the explicit
`theatre_stations: bool = True` in `core/approach.py`, read in one place in
`agent_atc.py`, and no branch decides reachability from a list being empty.
`test_the_beacon_letdown_still_reaches_nobody_on_the_ladder` asserts both halves
— nobody on the ladder through that procedure, Batumi Tower on 132.0 off the
fix. #140 is now the one-line data change this was blocking it from being.

---

## [ARCH-28] The director states an absence as a fact, in three places — #153
labels: bug

From the same audit, 13 August, sweeping `director/` for the #146 shape. Three
sites turn *"we do not know"* into a definite answer, and each one has a
comment nearby stating the rule it breaks.

**1. A merge treats `False` and `0` as "not known".** `src/marshall/atc/board.py:176`

    if keep.get(k) in (None, "", 0) and other.get(k) not in (None, ""):

`False in (None, "", 0)` is `True` in Python. So when two rows are discovered to
be one aeroplane, a surviving row holding `on_visual = False` is judged empty
and overwritten from the losing row — and `on_visual` means *"he is flying it
himself, the talk-down must stop"*. Same for every falsy-but-meaningful column
in `_FIELDS`: `approaches_flown = 0`, `missed_count = 0`, `assigned_ft = 0`,
`sequence_no = 0`. The schema keeps these honest (`NOT NULL DEFAULT false`);
this line is where the distinction is lost, on the identity path.

**2. A failed radar read is returned as an empty sky.** `director/app.py:391`

    except Exception: got = []

Two lines above it: *"`contacts` returns None (not []) when the cache cannot be
read, which is what distinguishes 'cold cache' from 'empty sky'"*. The fallback
discards exactly that. `picture` on the next line comes from a separate call, so
the prose and the structured field can disagree inside one response.

**3. Navigation capability from an absent airframe.** `src/marshall/atc/plans.py:452`

    if not aircraft_type: return "dr"

`clearance.aircraft_type` returns None both when the pilot has not been
correlated to a track yet and when the row is missing, so *"we have not
identified him"* is indistinguishable from *"we know what he is flying"* — and
`help_level` turns it into a flat instruction to the controller: *"Dead
reckoning only… he cannot tell you where he is."* There is no output meaning
"we do not know".

**Acceptance criteria**
1. The flight merge distinguishes an unset column from a false or zero one, and
   a test covers `on_visual=False` surviving a merge.
2. A radar read that failed is reported as failed, and no consumer renders it as
   "nothing is flying".
3. An unknown airframe produces a "we do not know what he is flying" answer
   rather than the most pessimistic capability.

Code: `src/marshall/atc/board.py`, `director/app.py`, `src/marshall/atc/plans.py`.

**Status:** FIXED, and this entry was stale — the third one that grooming
found on 14 August. All three sites now carry the distinction and their own
account of what they used to do: `board._merge` tests `v is None or v == ""`,
`director/app.py` says what separates a cold cache from an empty sky, and
`plans.py` has an output meaning "we do not know" and asks. Covered by
`tests/test_i_do_not_know_is_not_it_does_not_exist.py`, 14 tests passing.
---

## [SEP-17] "Has he been airborne" was answered with a count of go-arounds — #154
labels: bug

Found by the audit for #146's siblings, 13 August, and fixed in the same commit.

`phases.derive` takes `was_airborne` because *"he is stopped on the aerodrome"*
means two opposite things: LANDED for an aeroplane that has flown, STILL ON THE
RAMP for one that has not. The bridge answered it:

    was_airborne=bool(getattr(_ac, "approaches", 0))

`Aircraft.approaches` is incremented by `Controller._do_missed` and by nothing
else. It counts GO-AROUNDS. So every pilot who flew one approach and landed off
it — every normal recovery — was reported as never having been airborne, and the
only thing that could still reach `landed` was the separation engine having
already called it (`separation="landed"`, set by `report_down`).

The same shape as #146 one module over: **a fact taken from a side-effect of one
particular way of it being true, rather than read from the thing that holds it.**
The phase holds it. `approach` IS an airborne phase; the counter agreed only by
accident, and only after a missed approach.

**What it cost is the ground half of the END of a sortie.** `report_down` runs
only from the proactive monitor, only when radar is on, and only for an aircraft
that thread watched fly (`if cs not in flown: continue`) — so a bridge restarted
mid-sortie never sees the landing. Then `sortie_phase` never reaches `landed`,
`handoff.due` has no phase to hand him to Ground with (#77), and `intents` reads
the same field to tell *"taxi to parking"* from *"ready to taxi"* (#100), so the
last request of a flight is answered as the first.

**Fixed.** `phases.has_flown(phase)` is one definition, read by `derive` off the
phase it is already given. `was_airborne` survives for a caller that knows
something the phase does not — a flight row that outlived a restart — and may
only ADD evidence, never withhold it. The bridge stops passing anything.

It immediately exposed #151: with the question answered correctly, an aeroplane
the sim says is down now WANTS `landed` from wherever he is, and the `follows`
table permits it only from `approach`. Those refusals are audible (#91) and are
characterised by a test rather than silently fixed.

Tests: `HavingFlownIsAPhaseAndNotACounter` in `tests/test_phases_derive.py`.
Code: `src/marshall/atc/phases.py`, `src/marshall/atc/agent_atc.py`.

**Status:** CLOSED UNVERIFIED 13 August — flight-test bankruptcy, not a pilot's word. The unit suite is clean. A pilot still has to
fly a recovery and taxi in, which is the behaviour it is about (card rows for
#77 and #100). Re-checked 13 August: `phases.has_flown` is still read by
`derive`, `agent_atc.py` still does not pass `was_airborne` and says so where it
used to, and `HavingFlownIsAPhaseAndNotACounter` is green.

---

## [KB-5] The diagnostics page consoled: a value with no source, no age, and no record of deciding nothing — #155
labels: bug, needs-flight-test

**ADDED 13 August — a position must name what it is measured FROM.**

    "So for 160, the diag screen should show the reference bra - whatever
     that be."

Today the board prints a range and a radial and never says the datum. That is
exactly how #160 stayed invisible: every Center range was measured from Batumi
because `field_origin` fell through to the loaded arrival's beacon, and no
screen anywhere said "Batumi" — you had to read the function to find out.

A number whose reference is unstated is the same defect this whole issue is
about, in its purest form. It is not wrong, it is unfalsifiable.

So the payload carries the reference beside the position — the NAME and WHY it
was chosen — and the board renders it:

    position   23.4 nm / 033°   from BATUMI · his destination
    position   23.4 nm / 033°   from BATUMI · the loaded approach   <- today
    position   18.1 nm / 210°   from BULLSEYE · nobody is working him

**Do this BEFORE #160 is fixed, not after.** The second line is what the board
would print today, and it makes the bug self-evident to anyone glancing at the
page. A board that confesses its provenance is worth more than one that is
quietly right, because the next wrong datum will not be this one.


    "I feel like the diag page might need revamping. I feel like it might have
     been lying a little to console me. I want to make sure that it represents
     what atc is seeing and thinking so that I can rationalize why something is
     happening"

`/diag` printed plausible values with no account of where they came from, how old
they were, or whether anything had decided them — and four of its panels printed
a value nothing had decided at all.

**Four things it answered that nobody had asked.** `active` was deleted from
`flight_plans` by migration 031, so the plans table read an undefined key and
rendered **"no"** for every plan for ever, which is an ANSWER. The neighbouring
cell rendered the em dash entity THROUGH the HTML escaper, so a reader saw the
literal characters `&mdash;`. `releases` — the only record that a board entry
ever existed, since a release destroys its own evidence — is published by the
bridge and `diag.state()` never forwarded it, so the panel written to make nine
wrong releases visible could not draw a row. And the page had ONE clock,
measuring the flight recorder, banner-ed as though it measured the bridge:
*"Recorder last moved 2 h ago — this is the LAST sortie, not live state. Is the
bridge running?"* It was. Its snapshot was one second old.

**And the biggest gap was not a missing measurement.** `watching_him` was written
to record deciding NOTHING — its docstring names the sortie it cost, a pilot
flying from four to thirty miles with no handoff and three minutes of silent log
— and it writes a sentence per decision: *"Georgia Center keeps him — departure,
35 nm, inbound"*. The page read that same file for the CONVERSATION and dropped
every one. So the answer to "why is nothing happening" was in the file the
diagnostics page already had open, and the diagnostics page did not print it.

**Rebuilt portrait-first.** One aeroplane is one card; nothing scrolls sideways.
The board was thirteen columns inside `<div class="scroll">`, a class the
stylesheet never defined — so it did not scroll either, and the file's own
comment admits what that cost: `intent` *"scrolled out of sight, which reads
exactly like a column that was never added"*. Each card carries what the bridge
published about him INCLUDING the four facts the table had no column for —
`sortie_phase` (the one input `handoff.py` reads), the strip he was resolved
from, the engine's own `identified` flag, and his own lines out of the record of
deciding nothing. Two clocks, never one. Every panel is stamped with which
source it was read from and how old that source is.

**Remaining scope — what the page still cannot say honestly, because nothing
publishes it.** Deferred rather than derived, because a page that computes a
fact is the failure this issue is about:

1. **Which values were RESTORED rather than heard.** #136 is the case: `intent:
   asr approach` displayed as fact while the pilot flew an ILS, off an hour-old
   `flights` row restored by `Controller.hydrate`. The controller knows —
   `hydrate` decides it row by row and keeps `skipped_stale` — and
   `publish_state` carries neither, so the page cannot mark a restored value or
   say how old the row was.
2. **Whether a clearance was AGREED.** #105 made FILED / ISSUED / ACKNOWLEDGED
   three real states and `clearance_ack` is a timestamp on the row;
   `Controller.hydrate` reads it into `ac.clearance_agreed` and `board()` does
   not carry it. Ground taxied an aircraft on an unagreed clearance and the board
   said nothing.
3. **Which plan he was CLEARED on.** `flights.flight_plan` and
   `flight_plan_label` have existed since migration 021 — *"a strip names the
   plan a pilot asked for"* — and `assigned_plans` holds the issued clearance.
   The board row carries only the strip the IDENTITY ladder matched him from,
   which is a different fact.
4. **The anomalies and the refusals.** `Controller.anomalies` records impossible
   states it repaired and its own comment says `/diag` shows them — it does not,
   because they are not published. `note_unreachable` records why the engine
   declined to act on a classified intent. Same for `skipped_stale`.
5. **The capability of the controller working him.** A controller said "radar not
   available" while its own capability said `radar=True` (fixed in `1e35bf9`) and
   nothing on the page could have shown the contradiction.
6. **What the controller was handed lasts about two seconds.** `publish_state`
   takes `handed` per call, so the turn publishes the blocks and the scheduler's
   next publish — two seconds later, with no `handed` argument — replaces them
   with an empty list. The panel therefore reads *"nothing sent yet this
   session"* within seconds of every transmission, which is the consoling shape
   again: an emptiness that reads as a fact. The blocks are the INPUT the
   controller's behaviour follows from, and they should survive until the next
   turn replaces them.

All six are one change in one place: `agent_atc.publish_state` puts them on the
row (and stops discarding the last one), and the page renders them the way it
renders everything else.

**Acceptance criteria**
1. No panel renders a value for a key the snapshot does not contain.  DONE
2. A blank fact renders blank — never `0`, never a plausible substitute.  DONE
3. The bridge's snapshot and the flight recorder are aged separately, and the
   staleness banner names which one is old.  DONE
4. Every `handoff/none`, refusal, unvoiced figure, repair and release in the
   recorder is on the page, with its age.  DONE
5. A contact on the scope that appears in neither the board nor the untracked
   panel is named rather than silently filtered.  DONE
6. Nothing on the page scrolls sideways at 1024 px.  DONE
7. The five facts above are published by the bridge and shown per aircraft.
8. **A pilot reads it on the knee, mid-sortie,** and can answer why nothing is
   happening without opening a log.

Tests: `tests/test_diag.py` — `TestTheReasonNothingHappened`,
`TestTwoClocksNeverOne`, `TestNothingIsAnsweredThatNobodyAsked`,
`TestThePanelThatCouldNotDrawARow`, `TestTheCardSaysWhatTheBoardKnew`,
`TestPortrait`.
Code: `src/marshall/kneeboard/diag.py`; the remaining scope is
`src/marshall/atc/agent_atc.py` (`publish_state`) and
`src/marshall/atc/controller.py` (`board`).

**Status:** CLOSED UNVERIFIED 13 August — flight-test bankruptcy, not a pilot's word. 1-6 flown against the live bridge with
`tools/ghost_flight.py --inbound` and read at 1024x1365. 7 is not built and 8 is
a pilot's. Re-checked 13 August: the six named classes in `tests/test_diag.py`
are green and the datum row renders its source, but `agent_atc.publish_state`
still takes only `units, handed, names, plans` — none of criterion 7's five
facts — and cards P9/P10/P11 are unstruck.

---

## [RAD-6] Every aeroplane is `is_aircraft: false`, because the feed names its category — #156
labels: bug

Found while flying a ghost arrival for [KB-5], 13 August.

`agent_atc._contact` decides three things by asking whether the sim gave the
contact a CATEGORY:

    "derived":     _derived_callsign(u.name) if not u.category else "",
    "state":       sim_state(scope, u.name, fix) if not u.category else "",
    "is_aircraft": not u.category,

The reading is *"a category means it is a tank"*. It is not: `feed/tracks.py`
streams one subscription per category and stamps every row with the word —
`airplane`, `helicopter`, `ground`, `ship` — so an aeroplane's category is
`airplane`, which is truthy, and every aeroplane on the scope is published as
`is_aircraft: false` with no derived callsign and no state.

Measured, live, on a ghost the bridge was working: `category: "Airplane"`,
`is_aircraft: false`, `derived: ""`, `state: ""`.

**What it costs.** The untracked panel filters on `is_aircraft` — *"the page does
not know what a T-55 is"*, which is right — so the panel that exists to show **a
manned aeroplane radar can see that nobody is working** can never show one. That
is the failure [ID-5] built it for, and it is the one that is invisible: a pilot
who is talking, whose identity never closed, so every call is answered and
nothing is ever sequenced. The `derived` column is empty for the same reason,
which is the translation the pilot asked to be able to check
(`362nd_Sockeye → Sockeye`).

The older `feed/dcs.py` path sets `"category": ""` for everything, which is why
this ever appeared to work.

**Acceptance criteria**
1. An aeroplane on the scope is published `is_aircraft: true` whatever the feed
   called its category, and armour is not.
2. It carries its derived callsign and its state.
3. A test covers a contact whose category is the sim's own word for aeroplane.

Code: `src/marshall/atc/agent_atc.py` (`_contact`), `src/marshall/feed/tracks.py`
(`_CATEGORY`).

**Status:** FIXED, and this entry was stale — the SIXTH found by grooming on
14 August. All three criteria are met and
`tests/test_a_category_is_one_word.py` covers them, 16 tests passing.
Verified behaviourally rather than by reading, which matters here more than
usual because the diagnosis above points at the wrong file:

    feed says 'Airplane'   -> is_aircraft True   derived 'Sockeye'  level warn
    feed says 'airplane'   -> is_aircraft True   derived 'Sockeye'  level warn
    feed says 'helicopter' -> is_aircraft True   derived 'Sockeye'  level warn
    feed says 'ground'     -> is_aircraft False  derived ''
    feed says 'ship'       -> is_aircraft False  derived ''

**The diagnosis above blames `agent_atc._contact` and that is wrong**, which is
worth leaving in place rather than editing away. `_contact` never sees the
feed's word: `identity.units_on` has already turned it into `Unit.category`,
which means *the category IF IT IS NOT AN AEROPLANE'S* — six readers are
written on that contract and `not u.category` is correct under it. The
comparison that actually produced the bug was the case-sensitive one in
`identity.py`, and one capital letter in `tools/ghost_flight.py`'s `Airplane`
made every ghost a tank in five places at once.

The vocabulary has one home now (`feed/categories.py`) and the five copies ask
it.
---


## [OPS-19] A bridge restart silently changes the approach the sortie is flying — #158
labels: bug

Found while flying the ladder end to end on 13 August, by doing it.

The bridge was live on `batumi-ils`. `uv run python tools/bridge.py restart`
brought it back on **`batumi-asr`** — a different procedure, a different final
approach course, a talkdown instead of an intercept — and the only sign was one
line eight lines up the log:

    approach: batumi-asr (from the theatre)
    flying: ASR runway 13, talkdown, Batumi Approach

`theatre.caucasus` chooses the recovery from `MARSHALL_APPROACH` or the map's
`default_approach`. The launcher carries `MARSHALL_THEATRE` deliberately — it is
in `DEFAULT_ARGS` as `--theatre` — and carries the approach only by accident, if
the operator happens to have exported it in the shell he is restarting from. A
restart from anywhere else silently reverts to the map's default.

`theatre.py` already knows why this matters and says so about a different
mechanism: *"an unknown one is named rather than silently swapped for the
default, which is how a pilot came to fly a talkdown after asking for an ILS."*
The same sentence applies to a restart, which is the far more common way to get
there — a live bridge is restarted several times in a sortie for a patch.

**What it wants**, in order of preference:

1. `restart` means restart. Read the running bridge's approach before stopping
   it — `/proc/<pid>/environ` on this host, or the `approach:` line it printed —
   and carry it forward. A restart that changes the procedure is not a restart.
2. Failing that, `restart` must SAY what it is about to change: "the running
   bridge is on batumi-ils and this will start batumi-asr" is a stop sign a
   human can read, and silence is not.

**Acceptance criteria.**

- Starting the bridge on a non-default approach and restarting it leaves the
  same approach loaded, and a test proves it without a sim.
- If it cannot, it says so on the way past, naming both procedures.

Tests: needs one; `tools/bridge.py` has no test today.
Code: `tools/bridge.py` (`DEFAULT_ARGS`, `_env`, `restart`),
`src/marshall/core/theatre.py`.

**Status:** FIXED 13 August, and CLOSED BY DELETION 18 August. `6e83dc9` made
`restart` read `/proc/<pid>/environ` off the running bridge before stopping it,
so the procedure survived; `--approach` was parsed the way `--theatre` is, and
an operator asking for a different one was told what was about to change.

That was a correct fix to a mechanism that should not have existed. #162
deleted the process-wide approach, so `approach_of`, the `--approach` flag and
the carry-forward went with it: **a restart cannot revert a procedure when no
procedure is attached to the process.** What comes back across a restart is
`flights.cleared_approach` per aeroplane, via `Controller.hydrate` — which is
more than the carry-forward ever managed, since that restored ONE procedure for
everybody on the frequency.

Deletion is the stronger close. A carry-forward can be forgotten, mis-set, or
defeated by starting the radio by hand; a thing that does not exist cannot be
any of those. `tests/test_a_restart_is_a_restart.py` now asserts the absence,
and asks the AST rather than grepping the text — the file has to QUOTE
`MARSHALL_APPROACH` to explain what it forbids.

---

## [SEAM-19] A man who asks for the ILS is written down as flying a talkdown — #159

Every pilot who requested an ILS last night appeared on the board, two seconds
later, as `intent: asr approach`. Three of them, one after another:

    01:20:31  PILOT  "...information alpha, request the ILS runway one three"
    01:20:33  BOARD  Rampart 8-2   intent='asr approach'
    01:22:22  PILOT  "...information alpha, request the ILS runway one three"
    01:22:24  BOARD  Ironside 9-7  intent='asr approach'
    02:57:11  PILOT  "...information alpha, request the ILS runway one three"
    02:57:14  BOARD  Marlin 5-7    intent='asr approach'

**This is not #136 and not #131**, which is why it survived both. Those were a
STALE row — an hour-old `flights` row restored over a live one — and the fix
was hydration. This is a WRONG row, written fresh, two seconds after he spoke,
and it would have been written the same way on an empty database.

**Cause.** `agent_atc._INTENT_SAID` maps the classifier's *kind* to prose, and
`request_approach` was spelled `"asr approach"`. A kind cannot carry which
approach a pilot wants — that is not what a taxonomy is for — and the constant
was written when ASR was the only approach that existed. The same shape as most
of this month: something that was true while there was one of a thing.

**What makes it a seam issue rather than a typo.** The right answer was never
missing. `Intent.wants` is verbatim and short by design — the schema's own
examples are `'VFR to Batumi, visual 13'` and `'ILS 21 left'` — the classifier
fills it, and it already had a path across the seam (`_agreed["intent"]`). So
`flights.intent` had TWO writers and the constant won. One column, one author.

**Fixed** in the same commit as this entry: `intent_said` returns what he said
and falls back to the kind only when he named nothing, and `request_approach`
now reads `"an approach"` — the clearance is the thing that gets to name a
procedure.

**Acceptance criteria.**

- A `request_approach` carrying `wants="ILS 13"` puts `ILS 13` on the strip, and
  nothing anywhere turns it into ASR. Covered by
  `tests/test_untracked.py::TestTheStripSaysWhatHeAskedFor`.
- A request that names no approach reads as unnamed rather than as a talkdown.
- A stated intention on any kind of transmission is recorded — `"VFR to Batumi"`
  on a check-in is what he is here for.

Tests: `tests/test_untracked.py` (5 cases).
Code: `src/marshall/atc/agent_atc.py` (`_INTENT_SAID`, `intent_said`).

**Status:** CLOSED UNVERIFIED 13 August — flight-test bankruptcy, not a pilot's word. Fixed in code (`d81d7b8`), and a pilot has yet to see
the right words on the strip. `intent_said` returns his verbatim `wants` before
it consults the map, `_INTENT_SAID["request_approach"]` reads "an approach"
rather than naming a procedure nobody asked for, and the five cases in
`tests/test_untracked.py::TestTheStripSaysWhatHeAskedFor` are green. The word is
not FIXED because nobody has read the strip in the cockpit.
Labels: needs-flight-test

---

## [RAD-7] A Center measures from whichever arrival the bridge was started with — #160

    "So what is the reference when on center (like right now)"
    "And why batumi? And what would it be in Nevada? I smell a stink"

The stink is real. Every range and bearing a Center speaks — and every distance
the /diag board shows while Center owns the aeroplane — is measured from
**Batumi**, and nothing decided that. It is a fallback.

`field_origin(profile, field)` answers "where does this controller measure
from", and it is correct for a field controller: `field` names his aerodrome
and `PROJECTED` resolves it. **A Center has no field** — its airspace is the
whole theatre — so it is called with `field=""`, drops through the `if field:`
branch, and lands on:

    for attr in ("aerodrome", "arrival_fix", "outer_hold"):

(it read `beacon` first until #163 renamed the field that was doing the
aerodrome's job; the fallback and its consequence are unchanged.)

`profile` is the loaded `ApproachProfile`. On `batumi-ils` that aerodrome is
Batumi, so Center says Batumi. Start the same bridge on `kobuleti-ils` and
every number Center speaks moves forty miles, with no other change and nothing
said. On Nevada it is Nellis, or Tonopah if that is the recovery you picked.

**This is capability inferred from data shape again** — the class the audit
named — and the recurring shape besides: `field_origin` was written when the
only controller who mattered had a field, and the fallback that was harmless
then became a silent wrong answer when Center arrived. The docstring already
tells this story about Kobuleti's controllers and stops one controller short.

**What it should be — REVISED 13 August, and the first answer was wrong.**

This entry originally said a Center measures from the **bullseye**. The owner
asked the better question:

    "is this mostly about the diag screen? Does center actually need a bra
     always computed?"

No, and no. It is not mostly the screen — `scope.origin` feeds any range or
radial the controller SPEAKS, and via `asr.Position.range_nm` it feeds
`Rule("center", "approach", "inbound_within", CENTER_NM)`, so it moves
aeroplanes. But a Center does not need a bearing-range-altitude at all. What a
Center does is route him, descend him, and hand him off at the right point, and
the only range in that is **"is he within 25 miles of the field he is going
to"**.

A bullseye is a TACTICAL reference — an AWACS construct. A Center working an IFR
arrival would not use one, and proposing it here was reaching for the nearest
available origin instead of asking what the number is for. The same mistake this
whole issue is about, one layer up.

**The reference is the aerodrome he is flying to**, which comes from his
clearance — `legs[-1]`, the destination that #142 settled is just the last
steerpoint. And today's accidental answer is already that field: `profile.beacon`
is Batumi's, Batumi is where he is going, so the NUMBER is right. It is wrong
only in PROVENANCE, which is why nothing looks broken until the radio's arrival
and the aeroplane's destination differ — a second aircraft, a diversion, a
restart onto another procedure.

    a field controller   his own field's beacon              (unchanged)
    working an aircraft  the field HE is going to, from his plan
    nobody is working him  the bullseye, for DISPLAY only — the diag board's
                         position column, never anything spoken
    no destination yet   None, and the picture renders nothing — #109 settled
                         that an origin-less picture is not a picture

**So this collapses into #162 step 2** rather than being its own feature. The fix
is not "teach `field_origin` about bullseyes", it is "stop asking the radio, ask
the aeroplane" — the same sentence as every other item tonight.

**PRIORITY, set by the owner 13 August — the datum matters more than the
choice.**

    "I don't really care which airfield is the reference for center's bra,
     should probably be the flight plans destination airfield, but that doesn't
     matter as much as we show / say from where. Else that bra is senseless."

That reorders this issue. Picking the right field is the smaller half and it has
a sensible default (his destination, `legs[-1]`). **Stating the reference is the
half that must land**, and it is required in BOTH directions:

    show   the board prints the datum beside the position       -> #155
    say    a range on the air names what it is measured from

The spoken half is the more serious one and was not previously captured
anywhere. A controller who says "twenty three miles" and nothing else has said a
number a pilot cannot use or check — and unlike the board, there is nothing to
go back and look at. Whether the datum is the right field is then a question a
PILOT can catch in the air, which is the property this issue has lacked from the
start: today a wrong reference produces a real range to a real airport and
sounds exactly like a right one.

So: say the datum first, choose the field second. A stated wrong reference is a
bug somebody finds; an unstated right one is luck.

**THE FOURTH `why` MUST NOT SURVIVE #162, and that is the answer to the question
this issue keeps being asked.** Round two of the board questions, 13 August:

    WHY_APPROACH    = "the loaded approach"   << this should be the same as the
                                                 destination no?

**No — and the fact that they are the same TONIGHT is the entire bug.**
`WHY_DESTINATION` is a fact about the AEROPLANE (`legs[-1]` of the plan he was
cleared on). `WHY_APPROACH` is a fact about the PROCESS (`theatre.default_approach`,
`config/theatres/caucasus.toml`, resolved once at boot into a module-global and
handed to `field_origin` as `profile`). They coincide because he happened to be
flying to the field the radio happened to be started on. A restart onto another
procedure (#158), a diversion, or a second aeroplane separates them, and nothing
in the code notices.

So the fix is not "point `WHY_APPROACH` at the destination". It is that after
#162 there is no loaded approach for a datum to fall back TO, and the fallback
branch — the `for attr in (...)` loop over an `ApproachProfile` — goes with it.
Three `why`s remain and they are exhaustive: his field (the speaking seat), his
destination (the aeroplane), the bullseye (display only, when nobody is working
him). A fourth that names the radio's own startup argument is not a reason, it
is the absence of one.

**Why it is not a one-line change.** `CENTER_NM` — the range at which Center
hands over — is computed against this same origin, so fixing the reference also
moves a handoff boundary. It changes numbers a pilot hears AND when he changes
frequency, which is a ghost flight's worth of verification, not a test's.

**Acceptance criteria.**

- Center's range for an aeroplane is measured from the field HIS plan ends at,
  proven by a test that loads `batumi-ils` and `kobuleti-ils` and asserts
  Center's origin for one aeroplane is IDENTICAL across the two. That test fails
  today and is the whole bug. (This criterion said "the bullseye" until the
  13 August revision above replaced that answer; it is corrected here rather
  than left to contradict the body, which is how #70 came to describe surveys
  that had been flown.)
- With no aeroplane being worked, the board's datum is the bullseye and it is
  never spoken.
- `grep WHY_APPROACH` returns nothing, and no origin anywhere is derived from an
  `ApproachProfile`. A fallback that still exists is a fallback something will
  take.
- A field controller's origin is unchanged — `tests/test_two_fields.py` stays
  green.
- The handoff range change is measured and stated before it flies, not
  discovered from the cockpit.

Tests: needs one; `tests/test_two_fields.py` is the right home.
Code: `src/marshall/atc/agent_atc.py` (`field_origin`, ~3634; caller at 153),
`CENTER_NM`.

**Status:** CLOSED UNVERIFIED 18 August — flight-test bankruptcy, not a
pilot's word, and closed unattested on the owner's instruction. Both halves are
in code and they landed a fortnight apart, which is worth recording because the
first half alone looked like the fix.

**WHAT NO PILOT HAS CONFIRMED**, so that "closed" does not read as "flown": that
a Center's ranges SOUND right measured from the arrival aerodrome. The number is
the same one this system has always spoken on the Caucasus — Batumi — so a
regression here would be silent on the map that is flown and audible only on
Nevada, where a Nellis-recovery Center now measures from Nellis rather than from
whichever ILS the radio was started on. Card rows for the enroute section.

`3bb2cb7` landed `Datum` and the `WHY_*` reasons, so a range NAMES what it is
measured from — necessary, and it left the number exactly where it was. The
board printed "BATUMI, the loaded approach", which is the bug describing itself
accurately.

The number moved with #162. `field_origin` took a `profile` and walked its
`aerodrome`, `arrival_fix` and `outer_hold`; it takes a FIELD, and where no
controller has one — every Center — the answer is the sortie's ARRIVAL
aerodrome. `WHY_APPROACH` is deleted and `WHY_ARRIVAL` replaces it. Same point
on the Caucasus, and now it is Batumi because the sortie recovers there and
says so, rather than because `MARSHALL_APPROACH` happened to be unset.

**The test that could not be written before is written now.** The entry asked
for one that loads `batumi-ils` and `kobuleti-ils` and compares a Center's
origin. There is nothing left to load, so the assertion is stronger and
simpler: ask three times, get one answer.
`TheReferenceIsNamedAndJustified::test_and_the_same_center_no_longer_moves_forty_miles`.

`WHY_DESTINATION` — the field HIS plan ends at — is still declared and unwired,
and it is deliberately not this commit: choosing it moves a number `CENTER_NM`
is computed against, which wants a ghost flight of its own.
Labels: needs-flight-test

---

## [PHR-7] A stopped aeroplane was cleared to land — #161

Found twice on the same night by two independent runs — a live sortie and both
ghost-flight rehearsals.

    03:02:23  ATC    "Marlin five seven, Batumi Tower, welcome. Exit the
                      runway when able."          <- report_down, off radar
    03:02:32  PILOT  "Batumi Tower, Marlin57, on the ground, runway one tree."
    03:02:35  ENGINE "Marlin five seven, roger, cleared to land runway one
                      three, wind zero nine zero at five."

The controller had already seen him land, said the right thing, and then went
BACKWARDS A WHOLE LEG when the pilot confirmed it.

**Cause.** The taxonomy sends both "field in sight, landing" and "on the ground"
to `REPORT_LANDED` — `intents.py` says so: *"field or runway in sight, landing,
down"* — and `Controller.report_landed` had no guard on his already being down.
`report_down` is the method that says the right thing and its docstring argues
this exact case: *"Reading a landing clearance to a man already stopped on the
runway is a controller who has not noticed the aeroplane arrive."* It was
reachable only from the radar poll. **Nothing a pilot could SAY could reach it.**

**Why it hid.** The agent never voiced the wrong sentence. With nothing sensible
to say it fell back to *"Marlin five seven, Batumi Tower, go ahead"*, so the
transcript reads as unhelpful rather than wrong, and only the recorder shows the
engine had lost the plot. That is the second time this month the language half
has masked an engine fault well enough to keep it off the flight test card.

**Fixed** in the same commit: `report_landed` delegates to `report_down` when
`ac.phase is Phase.LANDED`. The engine knows which rung he is on — the same
argument #100 used one case down for the taxi request.

**Acceptance criteria.**

- `report_down` then `report_landed` never produces the words "cleared to land",
  and still tells him to get off the runway.
- A man with the field in sight and still flying is still cleared, with the wind.

Tests: `tests/test_controller.py::TestTheEndOfAnApproachIsAudible` (2 new cases).
Code: `src/marshall/atc/controller.py` (`report_landed`).

**Status:** CLOSED UNVERIFIED 13 August — flight-test bankruptcy, not a pilot's word. Fixed in code by `218f551`, which
carries a real `Closes #161`; needs a pilot to hear the right thing after
touchdown. `report_landed` delegates to `report_down` when the man is already
`Phase.LANDED`, and both named cases in
`tests/test_controller.py::TestTheEndOfAnApproachIsAudible` exist and pass.
Labels: needs-flight-test

---


## [ARCH-29] There is no such thing as the theatre's approach — #162

    "I don't understand what this whole business about a theater default
     approach is. There should be no such thing"

Correct, and it is the root under #160, #158 and the remainder of #2.

**A pilot flies the approach his CLEARANCE names.** That is settled everywhere
else already: migration 031 removed `approach` from `flight_plans` because
*"which arrival you fly is a fact about your clearance, not your route"*, and
`flights.cleared_approach` is the column that holds it, restored across a
restart by `Controller.hydrate`. A field OFFERS a set of approaches —
`approaches_now(theatre)` — and Approach issues one of them to one aeroplane.
Nothing in that story needs a singular "the approach".

But one exists. `theatre.default_approach` in `config/theatres/caucasus.toml`,
overridable by `MARSHALL_APPROACH`, resolved once at boot into a module-global
`APPROACH_NAME` and a single `profile`. It is load-bearing in four places:

    field_origin(profile, "")        a Center has no field, so it measures from
                                     the loaded arrival's beacon        -> #160
    _agreed.setdefault("procedure",  the bridge's arrival is written into a
                       APPROACH_NAME)  PILOT'S agreed clearance as a default
    boot-time check                  warns if the theatre's key and the loaded
                                     profile's kind disagree
    Controller.self.profile          read 26 times. `ac.profile` -- the
                                     per-aircraft one -- is read TWICE.

That last line is the measurement that matters. **#2 [ARCH-1] "One approach
profile per flight, not per bridge" is marked *"FIXED 11 August. All four
criteria met."* and is 2 call sites out of 28.** The mechanism landed and almost
nothing uses it; every symptom above is a consequence of the other 26.

That gap is its own finding, and it is the one worth generalising. All four
criteria WERE met — each is about a flight getting its own profile, and a flight
does. None of them asks *what fraction of the code reads it*, so a mechanism
could be added beside the singleton it was meant to replace and satisfy every
one. **A criterion that a parallel implementation can satisfy does not retire
the thing it was replacing**, and "the old path is gone" is the criterion that
was missing. See the acceptance criteria below, which are written as greps for
exactly that reason.

**What it costs to keep.** A restart from the wrong shell changes the procedure
(#158, done by accident during a rehearsal — `batumi-ils` became `batumi-asr`);
a Center's every range and the handoff boundary derived from it move forty miles
with no other change (#160); and a pilot's clearance can be defaulted to an
arrival he never asked for, which is the mechanism behind the original
*"why on earth is intent still ASR"*.

**What replaces it.**

1. `Theatre` publishes `approaches`, plural, and nothing else. Delete
   `default_approach` from the file and `MARSHALL_APPROACH` from the
   environment. An approach with no clearance naming it is not being flown.
2. Every `self.profile` read becomes `ac.profile`, or takes the field/role it
   actually needs. This is the bulk of the work and it is #2 finished rather
   than a new project.
3. Where there is genuinely no aeroplane — a Center's origin, ATIS choosing a
   runway — the answer comes from the ROLE and the FIELD, not from an arrival.
   #160 specifies that half.

**RESTATED BY THE OWNER, 13 August, unprompted and in the same words**, which is
worth recording because it is the second independent arrival at the same
decision:

    "the radio should not have a default appproach it was loaded with.
     Approaches should be assigned on a per flight basis at runtim ... and also
     make sure that the radio/srs is completely flexible to work any approach"

`config/theatres/caucasus.toml:17` still reads `default_approach = "batumi-asr-13"`
as of that afternoon, so nothing about this has landed yet; `nevada.toml`
already carries none and says so in a comment, which is the shape the Caucasus
file should end up in.

**Acceptance criteria.**

- `grep default_approach` and `grep MARSHALL_APPROACH` return nothing.
- Two aircraft on one bridge fly two different approaches, proven without a sim.
- Restarting the bridge cannot change any procedure, because there is none to
  change; what each aeroplane is cleared for comes back from `flights`.
- `tests/test_two_fields.py` and the approach sweep stay green throughout.

Tests: `tests/test_two_fields.py`, `tests/test_controller.py`, the sweep.
Code: `src/marshall/core/theatre.py`, `src/marshall/atc/agent_atc.py`
(`APPROACH_NAME`, `field_origin`, the `_agreed` default),
`src/marshall/atc/controller.py` (26 `self.profile` reads),
`config/theatres/*.toml`.

**Status:** CLOSED UNVERIFIED 18 August — flight-test bankruptcy, not a
pilot's word, and closed unattested on the owner's instruction. Step 1 has
landed and there is now no such thing as the theatre's approach anywhere in the
tree.

**WHAT NO PILOT HAS CONFIRMED, AND IT IS NOT SMALL.** `_pro` answers None for
an aeroplane nobody has cleared, so that man now gets:

    no ASR guidance          `may_vector(None)` is False
    no missed-approach latch there is no procedure to read the numbers off
    "runway in use"          rather than another field's runway, in the
                             visual-approach offer

Every one of those is correct procedure and every one is a CHANGE from a radio
that vectored everybody down one arrival. Whether the controller now sounds too
quiet to a pilot who has not yet asked for an approach is an ear's question and
nothing in the suite can reach it. The clearance that fills `ac.profile` comes
from clearance delivery filing a plan that names an arrival, so the ordinary
sortie is covered; a pilot who turns up cold is not, by design.

Also unheard: the combined plate. The controller is briefed on four procedures
instead of one, which is ~10,200 characters against ~5,300, and whether that
makes him vaguer about the one being flown is exactly what #176 exists to fix
and exactly what no test can score.

    Theatre.approach / .approach_key   DELETED, plural `approaches` only
    default_approach                   DELETED from catalogue + caucasus.toml
    MARSHALL_APPROACH                  DELETED, and no reader remains
    APPROACH_NAME                      DELETED, all 7 readers with it
    tools/bridge.py --approach         DELETED, with the carry-forward (#158)

Step 2 finished with it, in `agent_atc.py` rather than `controller.py`: the
loop held ONE `profile` and handed it to about twenty-five functions as the
answer to "which procedure" for every aeroplane on the frequency. It is gone,
and what replaced each use is the point —

    field_origin(profile, field)   -> field_origin(field). A datum is a PLACE;
                                      the fallback is the sortie's arrival
                                      aerodrome, so it is the same on every
                                      restart. THIS CLOSES #160.
    true_heading(hdg, profile)     -> true_heading(hdg, field). Grid
                                      convergence is 0.0 at Batumi and 5.74 up
                                      the coast: a property of WHERE, and
                                      `Field_` is where it is declared.
    asr_context, flying_the_missed,
    settle, compose_message        -> ask `ctl.procedure_for(cs)`. His.
    push_fixes / push_sectors /
    push_stations                  -> the theatre and ALL published procedures
    load_and_push_plate(profile)   -> load_and_push_plates(). Every procedure
                                      published, one plate describing all of
                                      them (`briefing.plates`).
    _seats                         -> `theatre.seats_on_the_air()`: the ladder
                                      plus every procedure's beacon seats, so
                                      what the radio can HEAR is not one
                                      aeroplane's procedure to decide.

**`_pro` answers None now**, which is the whole of "the old path is gone": an
aeroplane nobody has cleared has no approach, so he gets no vectors
(`may_vector(None)` is False), no missed-approach latch, and "cleared visual
approach runway **in use**" instead of another field's runway. That is the
honest answer and it is a REAL behaviour change a pilot will notice — see the
flight-test note below.

**Criterion 1 cannot be met as literally written and is met in substance.**
`grep default_approach` and `grep MARSHALL_APPROACH` still hit: the comments
and the tests that FORBID them have to quote them. That is the trap CLAUDE.md
records misfiring four times. `tests/test_a_restart_is_a_restart.py` asks the
AST instead — which names the module binds, which strings it compares `argv`
against, which keys it writes into `os.environ` — and `--theatre` is asserted
PRESENT in the same test as the control.

**One coupling fell out, and it predates this.** The board refresh that reads
`flights` for the cruise level, the agreed clearance and the cleared approach
sat BELOW `separation_context`'s `if intent is None: return "", ""`. So a
transmission the classifier could not read threw away all three. Invisible
while the process-wide arrival covered for the third; load-bearing without it.
Lifted above the early return.

**What a pilot has to judge**, because no suite can: whether an aeroplane that
has NOT been cleared for an approach is now too quiet. The engine will not
vector him, which is correct procedure and a change from a radio that vectored
everybody down one arrival. Card rows for the approach section apply.
Labels: needs-flight-test

---

## [ARCH-30] A beacon is not an airfield — #163

    "A beacon is not an airfield. They are separate things and you have built
     them as though they are. ... I think all approaches have an airfield. Not
     all approaches have a beacon. A beacon may be used for things other than
     an approach"

All three are right, and the theatre file already half-agrees: an `[[approach]]`
row carries `field = "Batumi"` AND `beacon = "BATUMI"`, and the second is doing
the first one's job.

**What `beacon` actually resolves to.** The fix named BATUMI:

    [[fix]] name = "BATUMI"  ident = "OS"  freq_mhz = 132.0  navaid = "ndb"
            lat = 41.609594  lon = 41.600234

That is the AERODROME REFERENCE POINT wearing a beacon's ident and frequency —
and a fictional one: `tools/import_beacons.py` says so in its own docstring,
*"`BATUMI` on `OS` at 132.0 was invented for the period scenario -- the real
Batumi homer is `LU` on 0.430"*. The real one is already in the file, imported
from the sim's own `Beacons.lua`, and **it is 0.72 nm from the aerodrome**. Two
different places, one row.

Both `batumi-ils` and `kobuleti-ils` name a `beacon`. **Neither has one.** An ILS
is a localiser and a glideslope; nobody homes on the field. The row exists
because the object needed a position and `beacon` was the field that had one.

**What it is used for today** — `profile.beacon` does three unrelated jobs:

    a navaid he tunes and holds on   "hold at BATUMI as published", "report
                                     BATUMI inbound" -- real for an NDB
                                     letdown, meaningless on an ILS
    the geometric datum              IAF offsets, the plate, the AIP chart.
                                     `asr_plate.py`: "the radar reference
                                     point IS the field"
    the origin fallback              what a Center measures from       -> #160

Only the first is a beacon's job. The other two are the FIELD's, and the field
is already named on the same row.

**The shape it should be.**

    an approach ALWAYS has a field       -> `field`, required, the datum for
                                            everything positional
    an approach SOMETIMES has a beacon   -> optional, and only where the
                                            procedure actually homes on one
                                            (the 1944 letdown)
    a beacon EXISTS WITHOUT an approach  -> `[[navaid]]`, theatre data. 122 are
                                            already imported per map and no
                                            approach need mention them

**Why it matters beyond tidiness.** This is the conflation under #160: a Center
measured from "the beacon" because the beacon was secretly the field. It is also
why `field_origin` looks reasonable while being wrong — every name in it is
plausible. And a fictional ident on a real aerodrome's row is the thing the
required `source` field exists to prevent.

**Acceptance criteria.**

- `ApproachProfile` has no `beacon` unless the procedure homes on one; `field`
  is what everything positional reads.
- The BATUMI and KOBULETI fixes stop carrying an ident and a frequency. A navaid
  is a `[[navaid]]` row, sourced from `Beacons.lua`.
- The 1944 beacon letdown still names its beacon, on its own frequency, and its
  plate is unchanged — that procedure genuinely has one.
- Nothing a pilot hears changes for the two ILS approaches, proven by snapshot
  the way `d5e243b` proved the station move.

Tests: `tests/test_two_fields.py`, the approach sweep, a snapshot of both plates.
Code: `src/marshall/core/approach.py`, `catalogue.py`, `theatre.py`,
`config/theatres/*.toml`, `kneeboard/asr_plate.py`, `aip_plate.py`,
`atc/asr.py`, `atc/briefing.py`, `atc/controller.py`.

**Status:** FIXED 13 August — commit below. `aerodrome` is required and is the
datum; `homer` is optional and only the 1944 letdown has one; both ILS
approaches and the ASR now name no beacon, because they never had one.

Proved with a worktree at the previous HEAD: geometry, minima, stack levels,
glidepath at nine ranges, MSA and MVA on every 30° bearing, IAF distance, every
station at every field on both maps, and all three plates — **empty diff**.

A THIRD CONFLATION FELL OUT, unlooked for: `field` was left EMPTY on the letdown
to mean "no surveyed minima", so a procedure that plainly lands at Batumi claimed
to happen at no aerodrome at all. One key answering two questions. That is
`published_minima` now, and the letdown's field is Batumi, as it always was.

`ApproachProfile.beacon` survives as a documented transitional property
returning the merged answer, because this change was not permitted to edit
`agent_atc.py` (another agent held it) or `controller.py`'s letdown phrases. Six
readers remain, in two files, and a test PINS that set — a new one fails the
suite. That grep is the criterion #162 found missing on #2, where four
acceptance criteria passed while the old path stayed in 26 of 28 call sites.

Tests fail against the pre-fix tree: 7 failures and 5 errors of 10.

Remaining: the six shim readers, which #162 step 2 retires.
Labels: needs-flight-test

---

## [HO-9] An airborne aeroplane is never Ground's — #164

    "Yes, an airborne airplane is never ground's. Just have tower take him back
     if he's flying - even if he already said welcome go to ground"

#77 made `report_down` name Ground in the roll-out transmission, which is right
and is what a real tower does. It also made a **touch-and-go** worse than it was.

The radar poll runs every four seconds against a ten to twenty second roll, so
it fires: he is told to call Ground, put on `taxi_in` — and then he flies.
Nothing could retrieve him. `handoff_on_the_event` covers only approach and
tower, `phases.derive` refuses `taxi_in -> landed`, and there was **no row out
of a ground seat at all**. He sat on Ground's frequency, airborne, with only the
airspace-volume branch able to move him.

**Written as an invariant, not as a touch-and-go case.** Stated as "an airborne
aeroplane is never Ground's" it also catches the go-around that happens after
the goodbye, and the aeroplane that gets airborne off a taxiway with no take-off
clearance at all — neither of which anybody would have written a special case
for. Tower rather than Departure, because the man who just left the runway is
the runway controller's until he is clear of the circuit, and the existing
tower->departure row then does its normal job.

**Enforced in TWO places, and that is the point.** The rule rows are not enough:
`due` gives a phase whose `aims_at` is "none" outright ownership, by design and
correctly, so `taxi_in` handed a flying aeroplane to Ground before the table was
ever consulted. A rule a stronger branch outranks is not an invariant. So the
phase-ownership branch carries the same guard, and `_GROUND_SEATS` is named once
so the two cannot drift.

**`not on_ground` is not `airborne`.** A track radar has stopped seeing answers
False to `on_ground` — no unit, no position, so the geometry fallback is false
too — and reading that as flying would tear every parked aeroplane off Ground
the moment the stream hiccuped. Same scar as the board entry for an aeroplane
that had left the world. The condition requires radar to positively hold him;
"we cannot tell" leaves him where he is.

**Acceptance criteria.**

- A flying aeroplane on a ground seat is retrieved by Tower — asserted both
  through the rule table and from Ground's own phase.
- A flying aeroplane on TOWER whose phase names Ground is NOT sent to Ground.
- A parked aeroplane stays with Ground, and a landed one still gets the roll-out
  handoff to Ground. The guard is about flying, not about the phase.
- A track radar has lost is left where it is.
- The tests fail with the fix removed. Verified: 4 of 7 go red, and the 3 that
  pass are the negative cases.

Tests: `tests/test_handoff_rules.py::TestAnAirborneAeroplaneIsNeverGrounds`.
Code: `src/marshall/atc/handoff.py` (`_airborne`, `_GROUND_SEATS`, two rule
rows, the phase-ownership guard in `due`).

**Status:** CLOSED UNVERIFIED 13 August — flight-test bankruptcy, not a pilot's word. Retrieval only, and a touch-and-go REQUEST to
Tower is a separate thing the owner has put at very low priority and is not
built. `2cb8e6c` carries a real `Closes #164` and all four enforcement points
survive: `_airborne`, `_GROUND_SEATS`, the two `airborne` rule rows and the
phase-ownership guard in `due`, with all seven cases in
`tests/test_handoff_rules.py::TestAnAirborneAeroplaneIsNeverGrounds` green. Card
row F3b is unstruck, and its question — two frequency changes in a quarter of a
minute — is an ear's.
Labels: needs-flight-test

---

## [SEAM-20] The bridge owes the director two facts it can no longer derive — #166

Two halves of one thing: the director is asked questions only the BRIDGE knows
the answer to, and #162 quietly removed the last channel for one of them.

### The station list has no writer, and that is a regression from #162

`push_sectors` states the rule outright — *"THE BRIDGE KNOWS WHICH MAP IS LOADED
AND THE DIRECTOR DOES NOT"* — and the director container has no `config/` at
all: `catalogue.maps()` returns `[]` and `route.STATIONS` raises
`FileNotFoundError: /config/theatres/caucasus.toml`. So reading the theatre in
the director's process is precisely the mistake that comment records.

Until last night the seats reached it by ACCIDENT: `ApproachProfile` carried a
`stations` list, `profile_to_dict` is `asdict`, and the whole profile is pushed.
**#162 step 1 took stations off the profile — correctly — and nothing replaced
the writer.** `'stations' in profile_to_dict(BATUMI_ASR)` is `False` now, and the
live rows show the seam exactly:

    batumi-asr  | has_stations t | 9      <- fossil, written 25 July
    batumi-ils  | t | 9                   <- fossil
    batumi-ndb  | f | 0                   <- written AFTER the move
    nellis-ils  | t | 9                   <- fossil
    tonopah-ils | t | 8                   <- fossil

`batumi-ndb` is what every row looks like from now on, so on a fresh database
`look_up_frequency` answers *"no station list is published"* to every question
about every field on every map, for ever. The only reason it works today is that
four rows predate the change.

`sectors` is not a substitute: 5 rows, all with geometry, and no Ground, no
Clearance, no Sentry.

**What it wants:** a `push_stations` beside `push_sectors` in `agent_atc.py`,
pushing the theatre's seats as the bridge already pushes its sectors, its fixes
and its plate. Not a table nothing writes — that is what `tools/unwired.py`
exists to catch.

### A promise knows its seat, and the callback still guesses

`src/marshall/atc/agent/hooks.py` now keys hooks on `(session, seat)` and every hook
carries its `station`, `role` and `seat`, so the promise is filed under the man
who made it. The last step is the bridge's: `agent_atc.py:5812` calls
`hook_frequency(why, bridge.heard_on, bridge.last_active_hz[0])`, which falls
back to **the last channel anybody spoke on**. It must read `hook["station"]`
and resolve that seat's own frequency.

The director cannot close this half either — it is never told which frequency a
seat sits on, which is the same asymmetry as above.

**Until it is fixed**, Kobuleti Ground promises *"I'll call you back for taxi"*
and the callback goes out wherever the guess lands — on a busy sortie, Batumi
Approach's channel.

**Acceptance criteria.**

- A fresh director database answers a frequency question correctly for every
  seat on both maps, and a test proves the push happens at bridge start rather
  than asserting the rows exist.
- A hook set by Kobuleti Ground is voiced on Kobuleti Ground's frequency, with
  no other traffic required to disambiguate it.
- `tools/unwired.py` stays green: nothing is added that nothing writes or reads.

Tests: `tests/test_a_promise_belongs_to_a_seat.py` and
`tests/test_a_frequency_comes_off_his_own_map.py` cover the director halves and
pass; both bridge halves are untested because they do not exist.
Code: `src/marshall/atc/agent_atc.py` (`push_sectors` neighbourhood, and
`hook_frequency` at ~5812).

**HALF DONE, 13 August.** The HOOK half is fixed in `7312940`: the bridge reads
`hook["station"]`, resolves that seat with a new by-name lookup, and uses his
own frequency for the call and his own field for the ranges in it. A callback no
longer goes out on the last channel anybody happened to speak on.

That commit says `Closes #166` and it should not have — the STATION half is
still open, and it is the one that matters more, because it is a regression I
caused. Recorded here rather than silently amended: a trailer that overstates is
exactly the drift `tools/issue_sync.py` exists to catch, and it caught this one.

**Still open:** a `push_stations` beside `push_sectors`. Until it exists, a
director database that has been reset answers "no station list is published" to
every question about every field on both maps, and the only reason it works
today is that four rows predate #162.

**BOTH HALVES DONE 13 August.** The station half is `push_stations` beside
`push_sectors`, in the shape `/sectors` already had end to end, with
`frequencies._stations` reading the new table instead of
`approaches.data->'stations'`.

Two decisions in it worth keeping. The per-seat SCAN is gone — the table is
per-run, so there is one list and nothing to walk — but the membership CHECK it
had hardened into stays, because `set_stations` refuses an empty push
(`set_sectors`' rule verbatim: a bridge that could not build a list must not
wipe the last good one, and a 1944 letdown legitimately staffs no ladder). So
the table can still hold the PREVIOUS run's map, and trusting a list only where
it names the seat asking is what keeps a Georgian frequency out of a Nevada
cockpit.

The four fossil rows are deliberately left. They are the only reason the live
lookup answers anything today; migration 032 carries the one line to clean them
once a bridge with the push has run, and a test asserts 032 contains no
`UPDATE approaches`.

**NOT DEPLOYED.** A human runs `cd director && docker compose up -d --build`
(migrations run at container start), then restarts the radio so the first push
happens. Until then `SELECT count(*) FROM stations` is 0 and the lookup fails
closed rather than answering off the wrong map.

**DEPLOYED 13 August and verified on the running system.** `docker compose up -d
--build` applied `032` (`applied 1 migration(s)`), the existing rows survived
(`approaches=5 plans=3`), and the radio's next start printed `pushed 9 controller
seats (the map's station list)`. `/stations` serves all nine at full precision.

The fossil rows in `approaches.data->'stations'` can now be cleaned, using the
line migration 032 carries for it:

    UPDATE approaches SET data = data - 'stations' WHERE data ? 'stations';

Left for a moment when somebody is watching, because until it runs the fossils
are a harmless second copy and after it runs the push is the only source.

**Status:** CLOSED UNVERIFIED 13 August — flight-test bankruptcy, not a pilot's word. Both halves are in AND deployed, which is more
than this file usually gets to say. `push_stations` runs at bridge start beside
`push_sectors` and `frequencies` reads the new table rather than the approach's
JSON (`032bd02`, `1a49e53`); migration 032 is applied on the running director
and the live `stations` table holds nine rows — Batumi Approach 124.425, Ground
121.9, Tower 118.6, Georgia Center 139 with no field, Kobuleti Clearance 125.1,
Departure 123.3, Ground 121.8, Tower 133, Sentry 131. The callback resolves the
promising seat by name for both its frequency and its datum (`7312940`, whose
`Closes #166` covered only that hook half). It is not FIXED because nobody has
heard Kobuleti Ground's callback arrive on 121.800. One correction to the text
above: only three fossil `stations` blobs survive in `approaches.data`, not
four — `batumi-ils-13`'s has already been overwritten by a push.
Labels: needs-flight-test

---

## [SEAM-21] The strip is blank in four places, and only one of them was fixed — #167

`816c97e` claimed to fix the empty `strip` column on /diag. **It fixed one link
of four.** A ghost flying Domino still shows `plan: null`, verified live on
13 August during the #164 rehearsal. The whole chain, end to end:

    approaches.list_flight_plans()   SELECT name, callsign FROM flight_plans
                                     -- no `label`, no `legs`
              v
    GET /flightplans                 {"name": ..., "callsign": ...}
              v
    agent_atc.filed_plans()          names = {p["callsign"] for p in rows}
                                     -- ALWAYS EMPTY: nothing writes that column
              v
    Identity.plan                    matched against `filed_plans()`, so never set
              v
    agent_atc.plan_of                keys on p["label"], which the payload has
                                     never carried. Fixed in 816c97e, on a dict
                                     that was already empty.

**`callsign` is the column #142 retired.** A plan is `label` + `legs` + `task`;
which aeroplane flies it is a fact about a CLEARANCE. The query, the endpoint
and `filed_plans` all still ask for it, so the answer is `NULL` four times and
the strip has been blank for every aeroplane that has ever been on that board.

**A fifth, unfixed, 108 lines below the fix.** `agent_atc.py:4982` —
`_plan_row(p, by_plan.get(p.get("callsign"), ""), ...)` — still joins on the
plan row's own callsign. The identical join `816c97e` corrected one function up.

**And the destination cannot render even on a match**: the served row carries no
`legs`, so `derived()` has nothing to take `legs[-1]` from, and `Domino → BATUMI`
is unreachable regardless.

**What it wants.** The query selects `label` and `legs`; the endpoint serves
them; `filed_plans` collects LABELS, which is the one word a pilot actually says
and the thing `Identity.plan` was always matching against; `destination` is
derived from `legs[-1]` where the strip is rendered rather than stored.

**Why it stayed hidden.** Every link fails to an empty string or an empty set,
never an error, and each looks locally reasonable — this is the "blank reads as
blank" failure the whole /diag revamp (#155) was about. A pilot sees a board
that says the system does not know which plan he is flying, while the controller
is demonstrably getting it right on the radio. That is the third time that exact
shape has been reported on that page.

**Acceptance criteria.**

- A ghost filing and flying a plan shows its label AND its destination on the
  strip, proven from a rehearsal rather than a unit test.
- `grep callsign` over the flight-plan path returns nothing that treats it as a
  plan's identity.
- A test constructs the whole chain — row, endpoint payload, `filed_plans`,
  `Identity.plan`, `plan_of` — and fails if ANY link drops the label. Four
  separate links failing the same way is what made a one-link fix look complete.

Tests: needs one; the chain has never been tested end to end.
Code: `src/marshall/atc/approaches.py` (`list_flight_plans`),
`director/app.py` (`/flightplans`), `src/marshall/atc/agent_atc.py`
(`filed_plans` ~3585, `plan_of` ~4874, `_plan_row` ~4982).

**FIXED 13 August, and there were FIVE links, not four.** The fifth is the one
that would have kept the strip blank regardless of the other four:

    _matches(claim, name)  is  _key(claim) == _key(name)

an equality over the WHOLE transcript. So `Identity.plan` bound only for a pilot
whose entire transmission was the single word "Domino". `_matches` is right for
its own job — a callsign claim already pulled out of a sentence, against a
roster name — and wrong the moment it is handed a whole transmission.
`_names_plan` looks for the label as a contiguous run of words instead, which
also matches the multi-word strips the pre-#142 model still flies in the tests.

One thing that looked like a sixth link and is not: `Identity.plan` is set on
the RADAR rung only, and that is deliberate. Saying a plan's name does not
admit you and does not attach you to it — being seen on radar does. The comment
beside the roster branch already says so, and it is the same door #133 and FEET
WET were about: a SENTENCE must not create a fact.

Each link was reverted independently and the chain test fails for each, only
that one. Whole suite green at 2,115.

**Status:** CLOSED UNVERIFIED 13 August — flight-test bankruptcy, not a pilot's word. All five links are in (`219e620`, a real
`Closes #167`) and `tests/test_a_plan_reaches_the_strip.py` walks the whole
chain in four hops, failing if any one of them drops the label. Needs a pilot to
see a label and a destination on the strip: criterion 1 asks for a rehearsal by
its own wording and refuses a unit test as proof. This is the defect that
started the 13 August session. One residue worth knowing: `flight_plans.callsign`
is still declared and still written by `upsert_flight_plan` and
`PUT /flightplans/{name}`, so a literal `grep callsign` over the filing path
still finds a writer — nothing reads it, so the strip cannot regress from it.
Labels: needs-flight-test

---

## [ARCH-37] The ATIS letter is asked for and thrown away, so the controller can never stop asking — #180
labels: bug, architecture

**Status:** FIXED 18 August. Guarded by `tests/test_he_only_has_to_say_the_letter_once.py`, which fails on either half — the classifier dropping the field, or `dispatch` recording it on check-ins only — and on the general case of a schema field nobody collects. Not labelled `needs-flight-test`: every criterion is a fact a test can assert, and the pilot's complaint was that he was asked twice, which is exactly what the suite now reproduces.

    "Kobuleti Clearance is asking whether or not I have information whiskey
     over and over again, even though I've already told him. That should
     probably be something in the database to record that I have whiskey, so he
     doesn't keep asking"

It IS in the database — `flights.atis_letter`, a column since migration 026,
on the `flight_state` view and restored by `hydrate`. The column was never the
problem. Two faults, stacked, either of which alone would cause it:

    bedrock_intent.classify   asks the model for `atis_letter` in
                              INTENT_SCHEMA and never reads it off the
                              response. `Intent.atis_letter` was always ""
    intents.dispatch          wrote it only under `case IntentKind.CHECK_IN`,
                              so it would have been dropped on the request and
                              read-back calls even once populated

The two writers of `ac.atis_letter` are `dispatch` and `hydrate` — and
`hydrate` restores the column the board flushed *from that same field*. **A
closed loop with no source**, so the field was empty on every call of every
sortie ever flown.

**And it stops the sortie dead**, which is why this is not cosmetic.
`request_clearance` sets the phase, speaks the ATIS phrase and RETURNS — so an
unmatched letter short-circuits the rung before any clearance is issued. Asked
five times in three minutes on 18 August; no clearance was ever issued by the
engine, and `assigned_plans` held no row for the sortie.

**Why nothing caught it.** The field existed, typed, defaulting to `""`. Every
reader compiled, every test constructing an `Intent` by hand passed, and an
unfilled letter is indistinguishable from a pilot who never said one. It needs
a SECOND transmission to show, and only a live pilot sends one.

**What was built.** `classify` reads the field; `dispatch` records it whatever
call it arrived on. Plus a schema-coverage check — every field `INTENT_SCHEMA`
asks the model for must reach the `Intent`, and the mirror — because this is a
CLASS of fault: the copy is hand-written by design (the clamps on
`flight_size` and `wants` are why it is not a `**data` splat), so a field can
be added to the schema and silently never collected.

**Acceptance criteria**
1. A pilot who gives the letter on any kind of call is not asked again.
2. A pilot holding a stale letter is still corrected.
3. A field in `INTENT_SCHEMA` that `classify` does not read fails the suite.

---

## [ARCH-39] A plan named out loud comes back ambiguous, because the label is matched as typed — #182
labels: bug

**Status:** FIXED 18 August, then SUPERSEDED the same day. The first fix compared letters instead of characters, which worked and left the design — *"lets not implement stopgaps"*. The scorer is deleted outright in #183 and the case is guarded there. Kept as its own entry because it is the transcript that found the fault, and because the two-line fix is what made the real one obvious.

    15:13:08  PILOT  Roger Sock, I would like Batumi Test, IFR to Batumi.
    15:13:20  ATC    two plans fit that — say which: transit and recovery
                     filed as Batumi Test, or transit and recovery filed as
                     Domino.

`score` gives 100 points for naming a plan outright — by a distance its
strongest signal — and it could not fire. The test was a plain substring of the
transcript, `label in said`, so `batumitest` was looked for inside *"i would
like batumi test"* and not found.

**A label is TYPED by whoever filed the plan and SPOKEN by the pilot**, and the
two spellings never agree. This fails for every multi-word name, always.

What scored instead was `destination`, worth a deliberate one point because
every plan comes home to the same field — so the two tied and the resolver
asked a question whose answer was already in the transmission. Bare *"Batumi
Test"*, with nothing else said, tied identically.

**And the filing rule is what guarantees the mismatch.** `_LABEL_OK` requires
one word with no spaces, on migration 012's reasoning that *"Samovar One"* and
*"Samovar Two"* are how the wrong sortie gets cleared. That is a good rule, and
its effect is that anybody wanting a two-word name types `BatumiTest` — a
spelling no pilot will ever say. The constraint did not cause the bug; it made
it certain.

**It looked like the model's fault and was not.** The disambiguation was not
among the engine's decisions for that sortie, so it read as the language brain
improvising, alongside the narrated clearance of #180/#181. Only running the
resolver directly showed otherwise.

**Fixed** by comparing on letters alone (`_squash`), which holds across
`BatumiTest`, `Batumi Test`, `batumi-test` and whatever spacing Whisper picks.
#165 is untouched: a request naming nothing is still ambiguous and still gets
the question.

**Acceptance criteria**
1. A pilot who names a filed plan gets that plan, however he spaces it.
2. A request naming no plan is still asked back with the candidates.
3. An empty or unsaid label never scores as named.

---

## [ARCH-43] Errors go to stdout through `print`, where a logger belongs — #186
labels: architecture

**Status:** FIXED 18 August. All 22 exception paths converted; `tests/test_an_error_is_not_a_transcript.py` fails on a new one, and separately on a module that calls `log.` without defining one — which is how the first attempt at this shipped an undefined name that only ruff caught. The transcript prints are untouched and a test says so. **The guard itself hit this repo's oldest reading error on the way in**: it swept for `"log." in src` and failed on eight modules whose PROSE contains the word. Found by AST now.

    "print() should be a smell shouldnt it?"

Yes, and one was added while fixing #185 by copying the neighbours rather than
thinking. Measured across `atc/`:

    agent_atc.py     print=97    logger? NO
    controller.py    print=8     logger? NO
    clearance.py     print=0     logger? yes
    board.py         print=0     logger? yes

**22 exception paths across `atc/` print to stdout.** No level, no filtering,
no routing, interleaved with the sortie transcript, and invisible unless
somebody is watching a console. `agent_atc` had no logger at all, which is why
`log` was undefined the moment one was reached for — ruff caught that, which is
the only reason it did not ship.

**The transcript is NOT the smell and must not be swept up with it.** The `ATC`
and `PILOT` lines are the operator's interface and are meant to be on the
console; what is wrong is that failures share the channel with them, so a
diagnostic cannot be raised in severity, silenced, or sent to a file without
taking the sortie with it.

`agent_atc` now has a module logger and the #185 path uses it. The rest is this
issue.

**Acceptance criteria**
1. No `except` block in `atc/` reports through `print`.
2. The sortie transcript still reaches the console unchanged.
3. A check keeps it that way, since prose has not held on this before.

---

## [ARCH-48] `cruise_ft` is a level nobody filed — #192
labels: architecture

**Status:** FIXED 18 August. Migration 037 drops `cruise_ft` from `flights` and `assigned_plans` and rebuilds both dependent views — `flight_with_plan` carries it too and was found by asking the database rather than by reading. `filing.derived` no longer synthesises it; `plans.top_of_route` computes the top of a route from the LEGS at the one point a controller voices it (*"expect one zero thousand"*); `controller.hydrate` takes `cleared_ft` off `assigned_ft`, which is the level the engine actually issued. The strip asserts no level from the plan at all — what the next controller needs is `MAINTAINING:`, off `assigned_ft`. **Nothing was migrated into another column**: every value was derivable from `legs` and still is, and copying it would have moved the fiction rather than ended it, which is what #031 did by leaving these two behind. `tests/test_the_database_is_the_source_of_truth.py` caught the model drifting from the live schema, which is what it is for.

    "There is no cruise in a flight plan. Where is that coming from. Another
     smell"

Correct. A filed plan has a level per **leg**; there is no cruise. `cruise_ft`
is synthesised in `filing.derived`:

    "cruise_ft": max(alts) if alts else 0

**The number is not wrong — the noun is.** It is the highest level the route
asks for, which is what a controller voices as *"expect"*. `derived`'s own
docstring concedes the ambiguity it cannot resolve:

> the CLEARANCE altitude is `legs[0]`, and which is which is exactly what a
> single `cruise_ft` column could never say.

**And the fiction outlived the migration that removed it.** #031 took
`cruise_ft` off `flight_plans` for being a second answer to a question `legs`
already answers — and it is still a column on **`flights`** and on
**`assigned_plans`**, so the derived value is now stored twice downstream of
the table it was deleted from. Two copies of a number nobody filed, under a
name that asserts a fact the plan does not contain.

The strip says `HIGHEST LEVEL ON ROUTE` as of #191, which is what the value
means. That is a label, not a fix.

**What the plan actually supports.** Two real questions, and one name cannot
carry both:

    what he MAINTAINS now      `legs[0]`, and after a clearance
                               `flights.assigned_ft` — the level the engine
                               issued and the only one he is held to
    what he may EXPECT         the highest level his route asks for

**Acceptance criteria**
1. No stored column claims a cruise level a pilot did not file.
2. The clearance still says maintain-and-expect with the same two numbers.
3. Whatever replaces it distinguishes the level he is HELD to from the level
   his route reaches — `assigned_ft` already answers the first.

---

## [SEP-23] `BANISHED` cost the separation enum a member for a resequencing corner — #193
labels: architecture

**Status:** FIXED 18 August. Enum down to 6, `PHASE_FROM_WORD` a strict inverse, nothing lost on a round trip — asserted in `test_flight_state` over every member rather than for the one that used to collide. Not `needs-flight-test`: the behaviour is unchanged and the three existing tests still hold it.

    "Banished is a tiny little feature in a formation landing procedure that is
     earning way too big a spot in the system"

    "it's only used when a flight is stacked on an approach and we need to
     handle sending him out to resequence. That was discussed very early when i
     thought this system would be easy and we got way ahead of ourselves. We're
     still trying to get a clean single ship clearance."

`Phase.BANISHED` — a pilot parked at the top after `MAX_APPROACHES` goes —
behaved as `HOLDING` everywhere separation actually looks: `_occupied` excluded
both, `_free_slot` saw neither. What differed was the WORDS and the CHANNEL.

**What that cost, in order:**

    a 7th member of the separation enum
    -> `PHASE_WORD` maps two members onto one word ("holding")
    -> the round trip through `flights.cleared` is lossy
    -> a paragraph in `controller.py` explaining why losing it is safe

Four things, none of them separation, for a corner of a procedure that has
never been flown by a human on this system.

**Now derived, and from a column that already exists.** The first attempt made
it a flag on the `Aircraft` and `test_the_database_is_the_source_of_truth`
refused it — correctly: a fact that lives only in memory is one a restart
forgets. `approaches_flown` is already a column and already restored by
`hydrate`, so "at the top of the stack, out of goes" is something the board can
answer without a new fact anywhere.

**The enum is 6 and the round trip is exact** — nothing is lost through
`flights.cleared` any more, so the paragraph explaining the loss is gone too.

**The wider point is the one worth keeping.** This was speculative complexity,
added early against a multi-ship future, sitting in the middle of the one path
that still does not work cleanly. Every remaining finding from the 18 August
sortie — #5 the regex short-circuit, #6 the "go ahead" prefix, #8 the repeated
handoff, #9 the callsign artifact — is on the SINGLE SHIP clearance path.

**Acceptance criteria**
1. Two missed approaches still parks him at the top and frees his slot.
2. He is still worked on the outer hold's channel and told so in those words.
3. A restart restores him as he was — the round trip is exact.

---

## [ARCH-51] A frequency read-back was extracted as an aeroplane — #196
labels: bug

**Status:** FIXED 18 August. `"decimal"` is a stop word; the ghost corpus went 25 wrong to 22 and the baseline moved in the same commit. Not `needs-flight-test`: the corpus is 33 real transmissions off the recorder and holds it better than a sortie would.

    'Sockeye, one two one decimal eight'   ->  ["Decimal 8"]

Reading a frequency back puts a spelled digit after the word "decimal", and
`callsign.extract_all` built a callsign out of it — **dropping his own name to
do it**. Heard on 18 August when the pilot read back the departure frequency;
the reply was recorded as addressed to *"Decimal 3"*.

**It cost nothing this time and that is luck.** The transmitter GUID is the
anchor, so nothing was misrouted. What reads the extracted name is the
callsign-correction path (#172), which tells a pilot the name he used belongs
to nobody on the board — off a fragment of a frequency he was correctly
reading back.

`"decimal"` is a stop word now, beside the others that "turn up immediately
before a number in ordinary radio speech" — the list that already exists for
exactly this, and whose own comment says *"a false positive puts a ghost in the
holding stack"*.

**The ghost corpus improved: 25 wrong -> 22.** Three of its hard cases are
frequency read-backs, and the baseline moved in the same commit.

**Acceptance criteria**
1. Reading a frequency back does not produce a callsign.
2. A real callsign in the same transmission is still extracted.
3. The ghost corpus does not regress past 22.

---

## [OPS-20] The file you open to see what is broken was 59% settled work — #201
labels: chore

**Status:** FIXED 19 August. `docs/ISSUES.md` was 12,241 lines, and 129 of its
198 entries were closed — so the document somebody opens to find out what is
still wrong was mostly a record of what is not. Split into `ISSUES.md` (69
live) and `docs/ISSUES-CLOSED.md` (129 closed).

**The split is about which file a person reads, and nothing else.** Both are
still parsed and still compared against GitHub by `tools/issue_sync.py` and
`tools/file_issues.py`, which read the pair through one `_both()` helper — an
archived issue that quietly disagrees with its own GitHub record is exactly the
drift those tools exist to catch, and moving it out of the live file must not
buy it an exemption.

That guarantee was written into the archive's preamble *before* the tools could
honour it, which is this repo's standing failure mode — a documented constraint
that is not true — and it was caught by running `check.py` rather than by
reading. The claim and the code landed together.

**Two more faults fell out of making the tools read the pair**, both of the
same shape — a value used somewhere it had quietly stopped being right for:

- **Both tools wrote the CONCATENATION back to `ISSUES.md`.** `text` had been
  the live file for as long as the write-back existed, so `ISSUES.write_text`
  was correct until the moment it was not. The first run appended all 129
  archived entries to the live file and said `numbers written back`, because
  the result is a perfectly well-formed document. Caught by the duplicate-slug
  check reporting `[SEAM-21] is both #167 and #167` — the same number twice,
  which is not a naming collision at all and is the only reason anybody looked.
- **`gh issue list --limit 200`, with 201 issues on GitHub.** `gh` returns the
  NEWEST, so `#1` — `[FP-1]`, the first issue this project ever had — was
  reported as *"not on GitHub"*. Nothing was wrong with it. A silent truncation
  does not report a missing answer, it reports a **wrong** one, and it sends
  you to read the entry rather than the query. The fix is not a bigger number,
  which is the same bug with a later date: a result that is exactly the limit
  may have been cut, so it is refused outright.

**Acceptance criteria**
1. `tools/issue_sync.py` reports every issue, live and closed, in step.
2. `tools/file_issues.py --sync` still pushes a drifted body from either file.
3. A closed issue's number cannot be reassigned to a new entry.
4. An entry in the wrong file is reported by name (`IN THE WRONG FILE`).
5. A `gh` list that comes back exactly full is refused, not used.

---

## [RAD-14] The identity alarm cried on every clean shutdown — #203
labels: bug

**Status:** FIXED 19 August. `radio/client.py` announced

    !! SRS roster tracking stopped (stopped); radios will read as GUID stubs
       and identity falls back to weaker evidence

on nearly every line of a `stack_rehearsal` transcript. Nothing had gone
wrong. `why` initialised to `"stopped"`, and the drain loop's own exit
condition is `self._stop.is_set()` — so **every orderly close fell out of the
loop with that value still in hand** and printed the warning. Each synthetic
pilot opens a client, speaks, and closes it, so the alarm fired per pilot per
turn.

**It cost a real diagnosis.** A failing stack rehearsal read as *"identity fell
back to weaker evidence"*, which is a plausible explanation for the sequencer
losing an aeroplane, and it is not what happened.

**One value meaning two things**, again — `""` is now "we asked it to stop" and
a reason is only recorded when there is one. `clearance_agreed` (#181), `due`
(#189), `may_vector` (#197) and this are the same sentence four times.

**The test file already had three cases** — a closed connection, a real error,
and a client that never started — and not the fourth, the orderly shutdown that
happens every single time. That is why it shipped. `test_srs_roster.py` covers
it now, deliberately (`_stop.set()` then drain), not on a timer.

**Acceptance criteria**
1. A clean `close()` prints nothing and leaves `roster_ended` empty.
2. A dropped connection and a socket error still say so, with the reason.

---

## [TEST-7] The harness could not tell "wrong" from "never got there" — #202
labels: chore

**Status:** FIXED 19 August, in `4eadc8f`. *"You should also fly actual tests on
the server yourself to validate the fixes."* First run of
`tools/ladder_rehearsal.py` over real SRS, real Polly and real Whisper: 5 PASS,
2 FAIL, 4 SKIP. **None of the four were the engine.**

- **Q4/Q5 failed because Q3 SKIPPED.** The ladder is a sequence — the read-back
  at Q3 agrees the clearance, and since #181 nothing taxis without one. A lost
  number in the audio loop made Q4 ask for taxi, get correctly refused, and be
  scored as a defect. **A harness that cannot tell "wrong" from "never got
  there" is worse than none**, because that is the one thing it is for.
  Unreachable rows now SKIP and name the row they waited on (`_NEEDS`).
- **Q1a had skipped ALWAYS since #192**, because its guard asked for
  `plan["cruise_ft"]` — which #192 deleted. After that commit the guard was
  permanently true, so the row never ran. **A skip that cannot fail is a check
  that has been switched off**, and it read exactly like a pass.
- A read-back was matched without the callsign, so a transmission not for us
  could score the row.
- The recorder was read from offset 0, so a previous run's events counted.

Final: **10 PASS, 1 SKIP**, and the skip is honest — a fixture that departed in
words has not landed, and the engine is right to refuse it.

**Its number was hand-written and is wrong.** `4eadc8f` and five comments in
`ladder_rehearsal.py` say `#201`, guessed because 200 was the highest at the
time. `tools/file_issues.py` then assigned #201 to something else entirely.
That is the trap `ISSUES.md` already warns about in its own preamble — *never
hand-write a number* — and it produces the worst kind of citation: one that
resolves, to the wrong thing. The comments are corrected to this issue; the
commit trailer is pushed and stays wrong, which is why this entry names it.

**Acceptance criteria**
1. A row whose prerequisite did not run SKIPs and names it, never FAILs.
2. No row's guard can be permanently satisfied by a deleted field.
3. A read-back only scores when it carries our callsign.

---

## [HARNESS-4] A reply belongs to the turn that earned it — #204

labels: tooling

**Status:** FIXED and FLOWN. `mine_only` in `tools/ladder_rehearsal.py`,
guarded by `tests/test_a_reply_belongs_to_its_own_turn.py`.

`say_it` decided the controller had answered by looking for any `atc/` record
written since the byte offset it took before transmitting. That is also true of
a reply to somebody ELSE: one that overruns its own turn's deadline is written
after the NEXT turn has taken its mark, so the next turn sees an `atc/` record
immediately, stops waiting, and reports its predecessor's answer as its own.
From then on every turn is one behind and nothing in the output says so.

`stack_rehearsal.py` ran that way for three flights and scored four separation
violations. The transcript said it plainly and it did not look like a harness
fault, because the symptom is a controller using the wrong callsign and that is
a real bug we have actually had:

    pilot transmits          reply addresses
    Pony one two             "Pony one one ... you are Sockeye"
    Pony one one             "Pony one three ... you are Hoover"
    Pony one three           "Pony one one ... you are Bandit"

Bandit's turns kept collecting Sockeye's answers, so Bandit's own never landed
inside his window and he was never worked at all. The board then said --
correctly -- that an identified aircraft had been given nothing, and `forgotten`
read that as the sequencer losing him. **The engine was never asked the
question, and the harness reported the answer as a defect.** Same shape as #202
in the sibling file: a harness that cannot tell "wrong" from "never got there"
is worse than none.

The bridge writes a `pilot` record when it hears the transmission, so that
record is the boundary: anything before it belongs to somebody else's turn.
No `pilot` record yet means the bridge has not heard us, and the honest answer
is nothing rather than whatever reply happens to be lying there.

`stack_rehearsal.py` also re-read the recorder window itself after `say_it`
returned, which handed back the untrimmed view and undid the fix; it now takes
the turn `say_it` attributed.

**Acceptance criteria**
1. A reply written before the bridge heard this transmission is not attributed
   to it. — met, `mine_only`
2. The `pilot` record is retained so `arrived_intact` can still judge the
   transmission. — met
3. No `pilot` record yields an empty turn, which reports MISHEARD rather than
   passing on somebody else's reply. — met
4. `stack_rehearsal.py` reports what the separation engine does with three
   arrivals, and the result is believable either way. — met, see below

**FIXING IT TURNED THE RUN GREEN AND THE GREEN WAS WORTHLESS.** With the
attribution right, all nine turns were judged, every ship was correctly named,
nothing was forgotten and the run exited 0 — over a board on which all three
aeroplanes were ENROUTE from the first word to the last. Twenty-four board
rows, no holder, no assigned level, no letdown. Every rule in this file is
about aircraft holding or in the letdown, so "no two aircraft shared a level"
was true of a stack with nothing in it.

The cause was in the fixture: `ROUNDS` only ever ASKED for an approach, and
since the approach offer landed that is answered with a MENU of three. Nobody
ever chose, so nobody was ever sequenced. A round that chooses one was added.

The docstring already forbade this -- "A VACUOUS PASS IS NOT A PASS" -- but the
guard it describes only catches an EMPTY board, and this board was full. So the
guard now asks who was actually SEQUENCED, and a run where nobody entered the
stack exits 2 (unreachable) rather than printing the four congratulatory lines.

**What the engine did once it was finally asked**, which is the first real
evidence we have for the stack:

    Bandit    CLEARED   5,000 ft   <- letdown
    Hoover    HOLDING   6,000 ft   "you're number two, expect approach shortly"

One in the letdown, the holder on the level above him, filled from the bottom,
and the sequence said out loud. The separation invariant held.

**One loose end, not a separation fault.** Sockeye said "request the radar
approach" -- the same words that worked for the other two, heard intact, no
mishear -- and got "say again your request", so he was never sequenced. That is
the intent classifier, and `tools/classify_bench.py` is the instrument for it.

---

## [SEP-21] `departure` counts as having flown, so holding short derives as LANDED — #178
labels: bug, needs-flight-test

**Status:** FIXED 18 August, NEEDS A PILOT — card row D9. `has_flown` is a positive list, `departure` is declared as straddling, and migration 035 carries the `has_been_airborne` latch across a restart. A machine can score every criterion here — a phase moved, a handoff fired — so `tools/ladder_rehearsal.py` may close it with an attestation naming the run.

    "I was handed to departure after takeoff. This is when I noticed my status
     was landed. Then departure tried to send me back to tower"

`phases.has_flown` answered from the phase, and that works for every phase but
one. `departure` STRADDLES: you are in it from Tower's first word, through the
roll, until Departure releases you — and most of that is spent stationary on
the runway. The phase genuinely cannot say whether a man holding there has
already flown a circuit, and it guessed in the dangerous direction:

    15:20:12  PILOT  holding short, runway 7, ready for departure   (0 kt)
    15:20:14  board  sortie_phase = departure
    15:20:30  PILOT  clear for takeoff, runway seven                (0 kt)
    15:20:33  board  sortie_phase = LANDED     <- never left the ground
    15:21:20  PILOT  ...actually gets airborne, 47 seconds later

For the next thirteen miles Kobuleti Departure posted him back to Kobuleti
Tower, twelve times, because a landed aeroplane is Tower's. Tower's own
"contact Departure when airborne" was refused as an unauthorised handoff for
the same reason, so a read-back was answered with "go ahead".

**What was built.** `has_flown` is now a POSITIVE list (`AIRBORNE_ONLY`) so a
phase nobody classified fails safe, `departure` is declared as `STRADDLES`, and
a `has_been_airborne` latch on `flights` carries the answer the phase cannot —
set only on positive radar evidence, which is #164's rule and its scar (`not
on_ground` is not `airborne`). Migration 035.

**Acceptance criteria**
1. Holding short after a `departure` handoff never derives as `landed`.
2. Departure does not post an outbound aeroplane back to Tower.
3. A radio restart mid-climb-out does not forget he has flown.

---

## [ARCH-36] We edit what the model said, with regex, instead of fixing the prompt — #179
labels: architecture, needs-flight-test

**Status:** FIXED 18 August, NEEDS A PILOT — card row D10. Both prompts corrected, `settle` no longer doubles the engine's talkdown, the history records what went out, and the two surviving filters are declared with the prompt fault each stands in for. **What a machine cannot score is whether it SOUNDS like one person**, which is the whole of criterion 1 — a pilot has to hear the read-back answered.

    "regex guards like that are a smell we should look for, and actively try to
     reduce, finding the root cause of hallucinations (usually our prompts
     fault) rather than patching output"

A pilot read back a take-off clearance and heard *"Sockeye, Kobuleti Tower, go
ahead"* — an invitation to speak, answering a read-back. Following it back:

    the model said     "Sockeye, that's correct, contact Kobuleti Departure one
                       two three decimal three airborne, good day."
    the engine had     authorised no handoff
    the filter         deleted the clause containing "contact ... Departure",
                       which — because controllers speak in commas rather than
                       full stops — took "that's correct" with it
    the fallback       spoke, because a rule says never transmit silence

Every layer was defensible and the pilot got nonsense. **The model did not
invent it. We told it, four times** — the plate, the per-turn message, its own
history, and the transcript. The rules said "never send a pilot to another
frequency off your own bat" while the plate said "a departure goes to Departure
at 5 miles", and a regex adjudicated between them after the fact.

**And the history kept the uncensored version.** `session_messages` held what
the model wrote; the pilot heard what survived, so the controller believed it
had handed him over. A filter that silently diverges the record from reality
poisons every turn after it.

**What was built.** Both prompts now name WHO and say the timing arrives as a
HANDOFF line; `settle` no longer hands the voice guidance the engine is about
to speak; the history records what went out.
`tests/test_we_do_not_edit_what_the_model_said.py` is a registry — every filter
declares the PROMPT FAULT it stands in for and an undeclared one fails. The
count is a baseline and should go DOWN.

**Acceptance criteria**
1. A read-back is answered as a read-back, not with "go ahead".
2. The mile calls on final go out; the model does not double them.
3. The conversation history matches what was transmitted.

---

## [ARCH-38] Nobody may taxi without a clearance, and the gate asks the wrong question — #181
labels: bug, architecture, needs-flight-test

**Status:** CLOSED 18 August, NEEDS A PILOT — card row G13. The gate now requires ACKNOWLEDGED, and the two refusals say different things. Nine tests failed on the tightening and every one of them was a case that had never been cleared — including `test_nobody_cleared_him_at_all_still_taxis`, which asserted the old rule by name and is now inverted with the reasoning recorded. What survives from that rule is its OTHER half: an empty board must not produce silence, and the refusal names the seat and the frequency. **Only a pilot can score criterion 1**, because the transcript reads plausibly either way — what is being tested is whether the sentence he hears points him at the right fault. On-the-fly VFR plan creation is deliberately NOT in scope and wants its own issue.

    "so we never got a clearance, because clearance never heard that we had
     information whiskey? Then everybody just played along?"

Yes. #180 stopped the clearance rung ever completing; this is why nothing
downstream noticed. The engine issued no clearance, the language brain narrated
one anyway, and Ground, Tower and Departure each waved him on.

**The gate exists and asks the wrong question.** `request_taxi` refuses on:

    if ac.clearance_agreed is False:

`False` means *one was ISSUED and the read-back has not been accepted*. The
read-back was judged `correct=None` — nobody could judge it, there being no
clearance on the board to compare against — so `clearance_agreed` stayed
`None`, and `None` passes straight through. The gate answers **"was the issued
clearance read back?"** and never **"was one ever issued?"**

`controller.py` says so itself, next to the field:

    FILED, ISSUED and ACKNOWLEDGED became three real states in #105 so that
    the next rung could ask which one he was in; nothing asked.

**The rule is not IFR-specific.** At a controlled field a VFR departure calls
Clearance too — *"VFR departure to the west"* — and that is a pre-req to taxi.
The `None` branch was justified on "the ordinary case for VFR", which is wrong
procedure, not just wrong bookkeeping.

**Scope: a plan on file is required for now.** The whole clearance apparatus is
filed-plan-shaped (`assign` copies a filed plan onto a flight), so there is no
path by which a VFR aeroplane with nothing on file can reach ACKNOWLEDGED.
On-the-fly VFR plan creation is deferred to its own issue; until then a filed
plan is a prerequisite for clearance, which makes the existing path the only
path and the predicate safe to tighten.

**And the refusal must name the right problem.** *"Your IFR clearance has not
been read back"* is wrong for a man who never called Clearance at all, and a
pilot can only fix the fault he is told about — which is #135's own complaint.

**Acceptance criteria**
1. An aeroplane the engine never cleared is refused taxi, and told to contact
   Clearance rather than told his read-back is outstanding.
2. An aeroplane whose clearance was issued and not read back keeps the existing
   refusal.
3. A refused aeroplane stays on Clearance's rung — the phase is the handoff.
4. A cleared and acknowledged aeroplane taxis with no extra step.

---

## [ARCH-49] A regex decided whether the engine ran at all — #194
labels: bug, architecture, needs-flight-test

**Status:** FIXED 18 August, NEEDS A PILOT — card row G17. Bench at **21/21** on Haiku and Sonnet (was 16/17 and 15/17, and before that it did not run at all). **Only a pilot can score criterion 1**: the failure is a controller answering pleasantly and the sortie quietly not starting, which reads as a normal exchange on the transcript.

    "that regex matching has bit us so many any times and is way too brittle"

`simple_response` matched a grammar of patterns BEFORE the classifier and
before the engine, and a match meant the transmission was answered and
**dropped**:

    _CLOSE = "down and stopped|clear of the (?:runway|active)|off the runway|
              parking|shutting down|clear of active"
    _ASKS  = "request|taxi|can i|ready|?"

The first transmission of the 18 August sortie was *"Kobuleti Clearance,
sockeye, parking spot, number 22 with information, Delta."* `_CLOSE` matched
**"parking"**, `_ASKS` matched nothing, and a cold opening call was answered
*"roger, welcome, good day"* — with the engine never seeing it.

    "he didn't ask what I wanted, just said good day"

**It had bitten in this same function before**, on *"clear of active, request
taxi to parking"*, and `_ASKS` was the patch. "parking spot" walked past it. A
second grammar competing with the classifier will keep losing, because the
classifier is the thing that reads.

**Which calls deserve a canned answer is the classifier's now.**
`IntentKind.RADIO_CHECK` is split out of `check_in`, and `radio_check_reply
(known)` renders and matches nothing — it takes the GUID-resolved name and has
no transcript to mine, so the class of fault `test_frequency` was written for
is unreachable rather than guarded.

**The closing acknowledgement is gone from the fast path entirely.** *"Clear of
the active"* moves him to `taxi_in`, which is a phase transition and therefore
a handoff — skipping the engine there is #77.

**The new kind is biased AGAINST itself**, because the failure is asymmetric: a
radio check answered instantly costs nothing, and a check-in mistaken for one
is thrown away. *"WHEN IN DOUBT IT IS NOT THIS ONE"* is in the schema, and the
bench holds both directions.

**AND THE BENCH HAD NOT RUN FOR WEEKS.** `tools/classify_bench.py` raised
`AttributeError` on import — it named `REPORT_CONDITIONS`, deleted by [ARCH-4]
"Toss the visual-separation negotiation", and was never updated. CLAUDE.md
sends you there after touching the schema, *"the taxonomy wording moves the
score more than the model does"*, and that advice has been unenforceable since.
Nothing said so: it is a tool, not a check, so `tools/check.py` neither ran it
nor reported it skipped.

Repaired, and it earned its keep on the first run — the new kind was too greedy
and swallowed *"this is Sockeye on 124.0, how do you read"*, which is a
check-in. **21/21 on Haiku and Sonnet**, up from 16/17 and 15/17.

**Acceptance criteria**
1. A pilot's opening call reaches the engine whatever words it contains.
2. A bare radio check is still answered instantly.
3. "Clear of the active" moves the phase and hands him to Ground.
4. The bench runs, and covers the new kind in both directions.

---

## [ID-5] Tracked and untracked, and who owns him — #49

labels: architecture, needs-flight-test

**Status:** CLOSED 31 July, unflown. Guards: `tests/test_untracked.py`,
`TestThePageDoesNotJoin` and `TestAnIndicatorThatCannotGoRed` in
`tests/test_diag.py`. **Code:** `atc/controller.py`, `atc/agent_atc.py`,
`kneeboard/diag.py`.

    "I sign into the sim, get in a jet, I am UNTRACKED. The sim knows that I am
     362nd_Sockeye, knows what im in, where im at and what my as/gs/alt is. The
     sim even knows what my callsign will be 'Sockeye' - because the process of
     stripping a squad off a name should be deterministic and instant."

It is deterministic and instant, and it always was. `identity.handle` is a pure
function over a string the sim publishes on every radar poll. It was reachable
only through `Registry.resolve`, which is the TRANSMISSION path — so a name
available for free was not derived until a pilot keyed a microphone, and the
untracked table printed the raw label.

### The model

**UNTRACKED** — the sim sees him. Named, positioned, owned by nobody. This is
where every aircraft starts and it requires no radio.

**TRACKED** — on the board, and exactly one controller owns him. Enterable
**only** from untracked, which is what makes the ghost class structurally
impossible: a tracked aircraft must have had a sim contact behind it, so no
transcript can mint one. [#40] says *"corroboration is the only filter that can
work, and the obvious version is circular"* — the circularity was corroborating
against a scope tagged by the binding under test. This is not circular, because
untracked is populated before anyone speaks.

**Entering:** contact a controller. Airborne that means radar identification —
"radar contact" is a specific thing a controller says. On the ground it does
not: nobody radar-identifies a man parked on the ramp, and the check-in is
enough.

**Two exits, and only one of them is a release.** A handoff changes the OWNER
and nothing else; he is never unowned in between. Dropping him to untracked
mid-approach loses his level, his place in the letdown and his approach count at
the exact moment two controllers are relying on them — which is materially what
`release_stale` was doing nine times in one sortie.

### Three columns, three authorities

`doing` conflated facts with different sources, which is the shape of every bug
in `tests/test_tonight.py` — a guard reading the wrong input.

| | source | when known |
|---|---|---|
| **state** — parked, taxiing, rolling, airborne | the sim | always, free |
| **intent** — ASR approach, en route, departure | the pilot, when asked | after the controller asks |
| **doing** — HOLDING, CLEARED, MISSED | the separation engine | from its own state machine |

Blank intent is the useful part: it means nobody has established intentions,
which is the first thing a controller is supposed to do.

`sim_state` reads `is_on_the_ground`, never the raw `on_ground` flag — that flag
comes from land/takeoff EVENTS, so an aeroplane that spawned parked never
generated one and it reads False at thirty-nine feet and zero knots. Reading it
directly is the fourth-caller mistake `test_tonight.py` exists to prevent.

### What this fixed on the way

Both faults in `HANDOFF-board.md`, structurally rather than by repair. A board
row now carries its own track, bound by `Controller.bind` at the one place that
holds both names, so `publish_state` looks nothing up. `release_stale` compares
the board's key against what each scope label DERIVES to, using the same
function the untracked table uses.

The prescribed fix — "extract one join, make it case-insensitive" — would have
left every formation blank while looking correct for a single ship: in a flight
the board key is the FLIGHT's name and no folding relates "Apex" to "sockeye".

**A guard that could not fire.** The first version refused to release an entry
whose track was on the scope. It was dead code: the refresh loop already asks
`accounted_for`, so anything radar can account for has had its clock reset and
never reaches the check. And the failure it was meant to catch is the one it
cannot see — the entries dropped wrongly are exactly those our own matcher
failed to relate, and asking the same matcher twice fails identically. There is
no automatic version. So the release is published WITH the scope contents and a
human is the detector: *"released Sockeye; the scope held 362nd_Sockeye"*.

**An indicator that could not go red.** The verdict banner read `d.ghosts`.
Nothing ever published it, so `(d.ghosts || []).length` was 0 on every render the
field ever had and the page reported "board and radar agree" for its whole life,
including while displaying a ghost row underneath.

### The page represents state; it does not enrich

    "Please make sure the diag tool represents state and doesn't enrich
     information. I'm using it to understand how the system works or doesn't"

`board()` opened by looking its own row up in the scope list, with the page's own
fourth copy of the name squasher, falling back to `{}` — so a failed join
rendered as four empty columns, which reads as "the sim did not say" rather than
"this page cannot find him". The bridge had always sent those fields. Removed,
along with `key()`, and guarded by a test that greps the page.

### Acceptance criteria

1. Sitting in a cold jet, before any transmission, the untracked table names him
   and shows the translation `362nd_Sockeye → Sockeye`.  DONE
2. A board entry is never dropped while radar paints the aircraft.  DONE
3. Every release is published with the scope as it stood.  DONE
4. A handoff changes the owner and preserves level, letdown place and track.  DONE
5. `state`, `intent` and `doing` are separately sourced and separately shown.  DONE
6. The page performs no lookup between panels.  DONE
7. **A pilot flies it** — slots in cold, watches himself appear untracked and
   named, checks in, and confirms he moves to tracked with the right owner and
   is never silently dropped. NOT DONE — needs a sortie.

Related: [#40] (the board's key), [#48] (nobody may name himself), [#42] (a
person is his handle), [#41] (the sim already tells us).

---

## [SEAM-12] Clearance delivery searched an empty board, and said so three times — #126
labels: bug, needs-flight-test

    "clearly he doesn't know how to find my flight plan"

    PILOT: Kobuleti Clearance, sockeye, IFR to Batumi with information delta.
    ATC:   Sockeye, I have no flight of that name on the board.
    PILOT: Call sign is Sakai requesting instruments to Batumi.
    ATC:   Sockeye, I have no flight on the board under either Sockeye or Sakai.
    PILOT: Kobuleti Clearance, sockeye, requesting Domino Flight plan.
    ATC:   Sockeye, negative, I have no flight on the board under that callsign.

`Domino` was on the board the whole time and resolves from the plainest request
there is — `pick()` matches it on the destination alone, and on "the only one on
file" with no destination at all.

**THE TOOL NEVER REACHED THE PLAN.** `request_clearance` opens by finding the
AEROPLANE — `_flight(callsign)` — and answers `not_on_the_board` when it cannot.
`flights.find` filters on `mission`; `clearance_tools` takes one as an argument
DEFAULTING to `"default"`; and `app.py` called `clearance_tools()` with none. The
bridge writes every row under the instance key, so the lookup searched an empty
bucket and refused before it ever looked at what was filed.

**It was correct until #119**, which gave rows a real mission instance earlier
the same evening. The shape this project keeps finding, and the fifth time this
month: *while every row was `mission='default'`, a hard-coded "default" could not
be wrong.* I changed what a mission key MEANS and did not follow it into the
director's tools.

**Invisible because this is the one tool factory whose argument has a default.**
`identify_tools(session_id)` and `hook_tools(session_id)` take the session and
would have raised a `TypeError` the first time they were called wrongly. This one
quietly took `"default"`.

The mission now travels on the `/atc` body from the bridge — the trusted side,
the same reason `role` and `station` do — and the agent cache is keyed on it,
because a cached agent built under the previous sortie would go on reading the
previous sortie's flights.

**AND THE SENTENCE IS WRONG EVEN WHEN THE LOOKUP IS RIGHT.** `flight_plans` is
what somebody filed; `flights` is who is airborne. "I have no flight on the
board" is a true statement about the second that says nothing about the first —
and a pilot hears it as his flight plan having gone missing, which is exactly
what happened. Clearance delivery is the one seat where the pilot has NOT yet
been bound to a track, so it is the seat where that confusion is guaranteed.
Open: the refusal should say which board it means, and should look at what is
filed before it decides it cannot help.

**Status:** CLOSED 13 August — the mission wiring `471c0a7` fixed was real, and the symptom this issue is NAMED for is not: `request_clearance` still returns `_not_on_the_board` before it ever calls `resolve(said, callsign)`. Clearance delivery still decides it cannot help without looking at what is filed.
mission travels on the `/atc` body, `director/app.py` calls
`clearance_tools(mission, station)` and keys the agent cache on it, and
`tests/test_the_clearance_reads_this_sortie.py` pins all four legs of that
wiring including that the no-argument form is gone. Half of the "Open:" above
landed with it — `not_on_the_board` now says which board it means and is told in
so many words not to tell him a plan is missing.

**That item has now landed.** `request_clearance` resolves the plan FIRST --
`resolve` is a pure lookup over `flight_plans` with no side effects and no
dependence on the board, so there was never a reason for it to run second, only
the habit of validating the caller first.

The refusal that did not exist is `found_but_not_him`, and it says both facts:
the plan is on file, named, with its origin and destination, AND nothing on the
board answers to that callsign. A pilot who hears "I have Domino, Kobuleti to
Batumi, but nothing under Sockeye" knows in one breath that his filing is fine
and his IDENTITY is the problem, which is the one thing he can fix from the
cockpit. It is still a refusal: `assign` writes against a flight row, and a
sentence must not create the aeroplane.

`nothing is on file` and `not on the board` stay separate, and a test asserts
the fix did not collapse them the other way -- a pilot who really has filed
nothing must not be told his identity is wrong.

**Status:** FIXED 13 August, NEEDS A PILOT — card row G11. The two sibling
tools were checked and deliberately left alone: `clearance_state` and
`flight_plan_help` look up what was ISSUED to an aeroplane, so "you are not on
the board" is the correct and complete answer there, and reordering them would
be a change made by pattern-matching rather than by reading.
---

## [SEP-22] A rule that says "not yet" is read as having no opinion — #189
labels: bug, architecture, needs-flight-test

**Status:** FIXED 18 August, NEEDS A PILOT — card row Q17. Guarded by `tests/test_not_yet_is_an_answer.py`, which holds all three answers and the caller's gate. **Only a pilot can score criterion 1** because both the right and the wrong behaviour are a handoff that arrives — what differs is where he was when it did.

    "tower, switch me over to departure pretty quick, should be at five miles
     I think, just hit it off the end of the runway"

The table says five miles and it works:

    Rule("tower", "departure", "outbound_beyond", DEPARTURE_NM)   # 5.0

Below five it declines; above five it fires. **What it could not do is say
so.** `due` returned `None` both when a rule governed the transition and
decided he stays, and when no rule applied at all — and `next_controller` reads
the second as permission to ask the PostGIS airspace volumes instead:

    v = _handoff.due(...)                    -> None (a rule said NOT YET)
    nxt = ... else v.station                 -> None
    if nxt is None and not down:
        nxt = leaving_my_airspace(...)       -> Kobuleti Departure, at ~1 nm

So geometry answered over the top of procedure and neither knew the other had
spoken. The 5 nm was correct, tested, and unreachable in practice.

**THIS IS #181 ONE MODULE OVER AND ONE DAY LATER.** There, `clearance_agreed is
False` — *he was issued one and has not read it back* — was collapsed into
`None` — *nobody has cleared him at all* — and taxi was granted to a man who
had never been cleared. Same shape, found the same week, in the same engine:

> A deterministic engine that cannot distinguish a DECISION from an ABSENCE OF
> OPINION cannot hold a line, because every refusal reads as an invitation to
> whoever asks next.

**Three answers now, where there were two:**

    a rule fired              Verdict with a station. Hand him over.
    a rule governs, not yet   Verdict with keep=True. Nobody else decides.
    no rule at all            None. The airspace may answer.

`same_station=True` on the keep verdict is deliberate — to every existing
caller that already means *"no frequency change, no transmission"*, which is
exactly what not-yet amounts to, so nothing else had to learn about the flag.

**The distinction cuts both ways and the test says so.** The airspace branch
exists because a region has a shape and a rule has a number; turning every
refusal into a keep would silence the mechanism #51 was fixed by, where a pilot
held at 44 nm with nothing able to move him.

**Sixteen assertions changed from `assertIsNone(due(...))` to `assertFalse`.**
They meant *"nobody is handed anywhere"* and were written against the sentinel
— which is how the ambiguity survived: the tests encoded it too.

**Acceptance criteria**
1. A departure stays with Tower to 5 nm, then is handed to Departure.
2. An aeroplane no rule governs is still handed over by the airspace volumes.
3. A pilot at the edge of a terminal area is still handed on (#51 does not
   regress).

---

## [ARCH-55] A controller could only be made to forget by restarting his container — #212

labels: bug

**Status:** FIXED 28 August -- `POST /atc/forget` clears the cached `Agent` and
the `session_messages` rows together, scoped to a seat.

Nothing could evict `_atc_agents`. Deleting the rows left the live agent
reasoning from the copy in Python, and a bridge restart does not touch the
director's container. So a stale conversation was unfixable in the field, and
during a live sortie it took a container restart to clear -- with a pilot
sitting in the seat.

Scoped deliberately: `station` forgets ONE seat and leaves the others, because
a seat's conversation legitimately spans several pilots and a controller who
forgets everybody because one aeroplane went home is a worse bug than the one
being fixed. Forgetting a single PILOT within a seat is not possible yet and is
not faked -- nothing records whose sortie a turn belonged to. That is #209.

`tools/ladder_rehearsal.py`'s `a_clean_board()` now calls it, which closes a
hole of my own making: every smoke test I ran seeded the controllers, and one
of those transcripts is what the pilot was being answered from.

---

## [SEP-26] "Down and stopped" is believed from an aeroplane that has never flown — #206

labels: bug, needs-flight-test

**Status:** CLOSED. Found by a pilot, live, 28 August.

Cold and dark on Kobuleti spot 22, the sortie's first transmission was
*"Kobuleti Clearance, sockeye is down and stopped, spot 22"* -- card row G17's
prescribed odd opening call. `Controller.report_landed` latched
`Phase.LANDED`, and the very first board snapshot of the sortie read:

    17:16:29   sep_phase=LANDED   sortie_phase=clearance

**The sim never said he landed.** His entire event history for the mission is
three records -- `birth` 17:11:53, `birth` 17:13:46 (he re-slotted), `takeoff`
17:25:11. There is no landing event anywhere in it. LANDED came from words.

`report_landed` guards against reporting down TWICE (`if ac.phase is
Phase.LANDED`) and does not ask the only question that matters: **has he ever
been airborne.** `Aircraft.has_been_airborne` exists, is a durable latch, and
is documented "SET ON POSITIVE EVIDENCE ONLY" -- and this path never reads it.

**What it then cost, which is the reason this is not cosmetic.** The sortie
phase walked correctly the whole way -- clearance, taxi, holding_short,
departure -- driven by the conversation. At take-off `phases._wanted` ran:

    if on_ground is True:
        if was_airborne or has_flown(current) or sep == "landed":
            return "landed"

`has_flown("departure")` is False, deliberately: #178 moved `departure` out of
`AIRBORNE_ONLY` precisely so a man holding on the runway is not called landed.
That protection is **bypassed by the `sep == "landed"` disjunct**, which reads
the separation phase as evidence of having flown when it may itself have come
from a claim. So the board went `landed` at 17:26:00 -- after the sim's own
takeoff event -- and Kobuleti Departure posted him back to Tower for fourteen
miles, because a landed aeroplane is Tower's.

Same sentence as #48, one field over: **a claim is not a fact.** He may no more
declare himself down than he may name himself.

**Acceptance criteria**
1. `report_landed` refuses an aeroplane that has never been airborne, and says
   so rather than silently doing nothing.
2. A pilot who says "down and stopped" while parked, having never flown, does
   not move the separation phase.
3. A real landing after a real flight still reports down exactly as now.
4. The `sep == "landed"` disjunct cannot be fed a phase that came from a claim.

---

## [SEAM-22] An agreed read-back is thrown away, so the next word restarts it — #208

labels: bug, needs-flight-test

**Status:** CLOSED. Found 28 August from a pilot's sortie, reproduced in isolation.

`_read_back_correct` carries what a pilot has said forward across a correction,
so a man told two items are missing may read back exactly those two and be
finished -- that is #157 and it works. When nothing is left outstanding it then
does this:

    if not missed:
        said.pop(key, None)              # agreed; nothing left to carry

and the accumulator is gone. The clearance is supposed to be marked
`acknowledged` in the same breath, which makes the next call early-return with
nothing to judge -- so the pop is harmless only for as long as the
acknowledgement actually lands. **When it does not, the next thing the pilot
says is judged as a fresh read-back of the WHOLE clearance and fails**, naming
items he read back correctly two transmissions ago. Driven in isolation:

    turn 1  "...maintain 5,000 ... frequency 1-2-3-4-5, and squawk"   missing freq, squawk
    turn 2  "departure frequency one two three decimal three, squawking 6789"  missing squawk
    turn 3  "corrections, squawking 0055"                              AGREED -- accumulator popped
    turn 4  "Sockeye will maintain 5,000."                             missing freq, squawk

Turn 4 is a man being told he is wrong about two numbers he has already got
right, immediately after being told he was correct. On the sortie he read that
as the correction never terminating, and aborted.

**The state lives in two places and only one of them is cleared.** `said` is
the working memory of an unfinished read-back; `acknowledged` is the durable
record that it finished. Popping the first while the second may silently fail
to be written leaves no memory of a conversation that, as far as everything
downstream is concerned, never concluded. Whichever way #185 is fixed, this
one wants the pop to depend on the acknowledgement having actually been
recorded rather than on the verdict alone.

**Acceptance criteria**
1. After an agreed read-back, a further transmission is not judged as a fresh
   read-back of the whole clearance.
2. The accumulator is only discarded once the acknowledgement is durably
   recorded, not merely decided.
3. A pilot who keeps talking after "readback correct" is never told he is
   negative on items he has already read back.

---

## [FP-11] Import a route from a DKS kneeboard link, not only a cartridge — #219
labels: enhancement

**Status:** DONE 1 September, verified through the running page.

**COMMITS CITE `#218` FOR THIS WORK AND NO SUCH ISSUE EXISTED WHEN THEY WERE
WRITTEN.** Same fault as [RAD-15] above, one number along: I referenced an
issue I had not filed. The code is corrected to this issue; the trailers cannot
be.

A data cartridge is an F-16 thing. The Phantoms on the Kobuleti ramp cannot
export one, so their pilots had no way to hand us a route at all. A DKS design
is read instead -- not by parsing the page, which serves the words "Loading
kneeboard..." and a script tag, but from `/api/public/design/<uuid>`, which the
page's own bundle calls and which needs no key.

It is a better source than the cartridge: decimal degrees rather than
degrees-and-decimal-minutes strings, targets and threats in their own arrays
rather than hidden among the route, and a `startPoint` the cartridge has no
equivalent for.

**ONE PLAN BUILDER, TWO READERS.** Both normalise to `{seq, name, lat, lon,
alt_ft}` and meet at `dtc.plan_from_route`. Only the kneeboard notes stayed
format-specific.

**THE PLAN SAYS WHERE IT STARTS NOW** (migration 039). `filing.derived` used to
say "NOT `origin`... where he is standing is not something he should have had
to write down in advance", which was true while the only importer was a
cartridge whose first waypoint is already airborne. The design carries
`startPoint`, so the tool he plans in wrote it down for him. It does not replace
`assigned_plans.origin`, which stays where he actually called Clearance from.

**AND THE IMPORT CHECKS HIS RADIO CARD.** The frequencies are not in the design
-- each channel carries an agency reference, resolved by POST to
`/api/public/agencies`. I recorded that this could not be done on the strength
of a guessed URL returning 405, which is METHOD NOT ALLOWED and was the endpoint
saying the path was right and the verb was wrong. The pilot could see on his own
kneeboard the frequencies I had just called unreadable.

**Acceptance criteria**
1. A kneeboard link files a route. (met)
2. The two ends are right -- `startPoint` names the departure field. (met)
3. A disagreement between his card and our theatre is reported. (met)
4. The cartridge path still works.

---
