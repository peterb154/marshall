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

## [FP-1] Flight plans: many on file, assigned per flight — #1
labels: feature, needs-flight-test

**Status:** SHIPPED/UNVERIFIED — built, script-checked, never said to a human.
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

Code: `director/tools/approaches.py`, `director/migrations/`, `flights` table
(columns already exist and nothing writes them).

---

## [ARCH-1] One approach profile per flight, not per bridge — #2
labels: architecture

**Status:** FIXED 11 August, needs the next sortie. Criteria 1, 3 and 4 met;
criterion 2 (`asr_sweep.py` against a named profile) still open and is now a
tooling change rather than an architectural one.

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
3. The plate, the kneeboard and the ATC agree on the field, course and minima.
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

## [APP-3] Visual approaches, without having to argue for one — #10
labels: needs-flight-test

**Status:** CLOSED — commit `4d011ed`

> "the controllers have to be forced to give us a visual approach"

**Acceptance criteria**
1. Asking for a visual gets one, first time, with no argument.
2. Once cleared visual, **no mile calls** — he is spacing, not talking you down.
3. "Field in sight" is still read as a report, not a request.
4. A visual does not jump the queue.

Tests: C1, C2, C3
Code: `controller.request_visual`, intent ordering in `intents.py`

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
`director/tools/identify.py`

---

## [ID-2] Noise must not become an aeroplane — #13
labels: needs-flight-test

**Status:** SHIPPED/UNVERIFIED — commits `631173a`, `50cebe7`

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

**Status:** OPEN — reproduced, narrowed, and now MAPPED. 27 July.

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

**Status:** OPEN

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

**Status:** SHIPPED/UNVERIFIED — `bd2db1b`..`d6d5b11`. Window
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
`director/tools/hooks.py` and nothing calls it.

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
(`director/tools/plans.py`). It works until somebody says an ordinary thing that
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

## [CHART-1] Chart the enroute fixes, not just the letdown — #26
labels: feature

**Status:** TODO

The kneeboard has the plate and the route map; the enroute fixes are not drawn
to scale anywhere.

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

## [ASR-4] Vector him onto a BASE LEG, not at a point — #39

labels: bug, needs-flight-test

**Status:** SHIPPED/UNVERIFIED for the pattern; **criterion 2 still open**.

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

**Status:** SHIPPED/UNVERIFIED — designed with the pilot 29 July and built the
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

**Status:** SHIPPED/UNVERIFIED — `7c9ca15`..`91a9d3f`. `land`,
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

**Status:** SHIPPED/UNVERIFIED — `ffb6bab`..`a17998f`. The
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

## [ID-5] Tracked and untracked, and who owns him — #49

labels: architecture, needs-flight-test

**Status:** BUILT 31 July, unflown. Guards: `tests/test_untracked.py`,
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

## [ARCH-6] `agent_atc.py` is the bridge, the loop, the monitor and the assembly — #55
labels: refactor

**Status:** PARTLY DONE 3 August — 5,802 lines down to 4,713. Criteria 1 and 3
are met; 2 is not.

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

**Status:** FOUNDATION DONE 10 August. `comms` converted; the rest follow the
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

## [HO-3] Nothing hands a landed aircraft to Batumi Ground — #77
labels: bug, needs-flight-test

**Status:** FIXED 10 August with [SEP-5] / #88, needs the next sortie. It was
one of three symptoms of the same unreachable branch, not a gap of its own.
bullet under "still dead ends" in an issue all of whose own criteria are met.

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
into it IS the handoff. The rule wants to be `landed -> ground at the arrival
field`, in the same table as the rest.

**Acceptance criteria**
1. After landing and clearing, the pilot is handed to Batumi Ground with the
   frequency, unprompted, with no request.
2. It is the ARRIVAL field's Ground — not Kobuleti's, which is the failure mode
   two aerodromes made reachable.
3. `tests/test_handoff_rules.py` covers it, and the structural test that every
   rule reads the trend still passes.
4. Card row F5 stops describing a known gap and becomes an ordinary check.

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

## [SEAM-1] A decided fact that is not spoken must not be silently lost — #79
labels: bug, architecture

**Status:** OPEN. Highest priority of the split-brain seam work.

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

## [SEAM-3] Every controller is handed every tool, and prose says who may use them — #81
labels: architecture

**Status:** DONE 10 August, verified against the running director.

`director/tools/capability.py` maps a seat to what it may reach for, and
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

**Status:** OPEN.

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
