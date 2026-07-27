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
suite has never been sufficient for it.

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

**Status:** TODO — blocked on nothing, but large

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
labels: test

**Status:** TODO

The stated proof that this is data-driven and not Batumi-shaped. Load a Kobuleti
ILS profile and fly it with no code change.

**Acceptance criteria**
1. A Kobuleti ILS profile is loaded from data alone.
2. The talkdown does NOT run (`guidance: "intercept"` — the aircraft has its own
   aid) and Tower takes him at the intercept, not at the missed approach point.
3. The plate, the kneeboard and the ATC agree on the field, course and minima.
4. No file under `src/marshall/atc/` changes to make it work.

Partly de-risked already: handoff distance, the final's frequency and the
descent table now all derive from the profile.

---

## [ENG-1] Engineering channel: getting a human on the line — #4
labels: needs-flight-test

**Status:** SHIPPED/UNVERIFIED — commit `cffad1a`

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

**Status:** SHIPPED/UNVERIFIED — commits `8464b4b`, `c0c5d29`

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

**Status:** SHIPPED/UNVERIFIED — commit `c0c5d29`

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

**Status:** SHIPPED/UNVERIFIED — commit `296b33d`

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

**Status:** SHIPPED/UNVERIFIED — commit `faac653`

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

**Status:** SHIPPED/UNVERIFIED — commit `faac653`

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

**Status:** SHIPPED/UNVERIFIED — commit `4d011ed`

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

**Status:** SHIPPED/UNVERIFIED — commit `36ea1a4`

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

**Status:** SHIPPED/UNVERIFIED — commits `50cebe7`, `ed18e97`

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

**Status:** SHIPPED/UNVERIFIED — commit `c0c5d29`

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

**Status:** SHIPPED/UNVERIFIED — commit `296b33d`

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

**Status:** SHIPPED/UNVERIFIED — commit `8a4ce0f`

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

**Status:** SHIPPED/UNVERIFIED — commits `0b08330`, `296b33d`

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
Code: `agent_atc.push_fixes`, `director/tools/tracks.py`, `spawn_ground`

---

## [OPS-1] One bridge at a time — #18
labels: needs-flight-test

**Status:** SHIPPED/VERIFIED (ground) — commit `296b33d`

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

**Status:** OPEN — **reproduced**, 27 July, and criterion 3 is met.

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

**Status:** OPEN

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

**Status:** TODO

"I will call you in five miles" has to actually happen, and a conditional hook
must stay conditional.

**Acceptance criteria**
1. Every promise on the air is either kept or explicitly withdrawn.
2. A hook whose condition has passed does not fire anyway.

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

**Status:** SHIPPED/UNVERIFIED — the pilot was right, it is a setting, and it is
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

**Status:** OPEN — partly explained, not solved.

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

**Status:** OPEN — seen once, live, 27 July.

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

## [PHR-1] Phraseology a real controller would actually use — #30
labels: bug

**Status:** OPEN — two found so far, both by a pilot

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

**Status:** SHIPPED/UNVERIFIED — commit `72b79cc`

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

**Status:** TODO

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

**Status:** TODO

**Acceptance criteria**
1. Every row on the flight test card names an issue.
2. Every SHIPPED/UNVERIFIED issue is closed by a human flight, not by a green
   unit test.
3. `docs/BACKLOG.md` keeps the debriefs and the reasoning; this file keeps the
   work.
