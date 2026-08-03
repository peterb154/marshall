# The work, as issues

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

**Status:** TODO — blocked on nothing, but large. **THIS IS THE
WALL IN FRONT OF MULTIPLE AIRPORTS.** Everything else on this list makes one
field work better; nothing else lets there be a second one. It has sat
unprioritised since the beginning while three days went on ghosts

`_run_srs` holds a single `profile`, and `asr.guide`, `controller.py`, the
metronome and the plate all read it. Two aircraft recovering to different fields
need a profile each. This is the wall in front of [FP-1] point 8 and in front of
the Kobuleti test [TEST-1].

**Acceptance criteria**
1. Two aircraft, two fields, two approaches flown concurrently without either
   controller using the other's numbers.
2. `asr_sweep.py` runs against a named profile and still reports the same
   figures for Batumi.

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

**Status:** TODO — the DB half is [FP-1]

A pilot files a plan before the sortie and the ATC knows him when he calls. The
schema arrives with [FP-1]; this is the way in. Evaluate Digital Kneeboard
Simulator before writing one.

**Acceptance criteria**
1. A plan can be filed without touching the database by hand.
2. A filed plan is assignable by voice on the night with no further setup.
3. It survives a mission reload.

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

## [ID-3] Nobody may name himself — the label comes off the aeroplane, not the radio — #48

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

## [SEQ-1] Nobody is number two behind himself — #50
labels: needs-flight-test

**Status:** FIXED — commit pending. Found live, 31 July, on Fred's first sortie.

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
4. **Still open:** what returned him to `HOLDING` while cleared. The deadlock is
   gone, but the state transition that caused it has not been found, and until
   it is this is a guard rather than a cure.

---

## [HO-2] Georgia Center has no proactive handoff at all — #51
labels: bug

**Status:** FIXED — one cascade, `agent_atc.next_controller`. Found live, 31 July.

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
- `Batumi Ground` — not deliberate; see F5 on the card.

---

## [ID-6] Frequency read-backs are parsed as callsigns — #52
labels: bug

**Status:** OPEN. Found live, 31 July.

Reading a frequency back produced callsign corrections addressed to fragments of
the number:

    PILOT: "124, decimal four. Batumi Approach, sockeye, over."
    ATC:   "Decimal four, I do not have you on the board. You are Sockeye..."
    ATC:   "Batumi four, I do not have you on the board..."

The identity was correct throughout — he was never mis-bound, and the correction
names the right callsign. The fault is that a number spoken in a read-back is
treated as a claimed callsign at all, so the controller opens every reply by
correcting a name nobody used.

Cosmetic in effect, but it is on **every** frequency change, which is once per
rung of a seven-rung ladder.

**Acceptance criteria**
1. A read-back containing a frequency produces no callsign correction.
2. A genuinely wrong callsign is still corrected — this must not be bought by
   disabling the guard, which is [ID-3]/#48's whole point.
3. Guarded by a unit test over the recorded transmissions, not by ear.

---

## [APP-5] The NDB letdown profile claims radar — #53
labels: bug

**Status:** OPEN. Found 2 August while making the ILS a vectored procedure.

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

**Status:** OPEN

5,802 lines. It is the file every live fix lands in, which is exactly why it
keeps growing and exactly why that is dangerous: the receive loop, the radar
injection, the hook scheduler, the guards and the message assembly all share one
namespace, so a change to any of them can reach any other and nothing says so.

**Acceptance criteria**
1. The message assembly — what the agent is told, in what order — is a module
   that can be tested without a radio.
2. The guards are separable from the loop that runs them.
3. `tools/atc_dryrun.py` and the live bridge drive the same assembly code.
