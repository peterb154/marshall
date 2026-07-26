# Flight test card — squadron-night fixes

One sortie, in order. Each test names the change behind it, so **a failure points
at one commit and one function** instead of at "the ATC was weird".

Every row names an **issue** in `docs/ISSUES.md`, which carries the acceptance
criteria. A test that fails is a comment on that issue; a section that passes
closes it. Nothing here is closed by a green unit test — that is the point.

Report by ID over the radio. Say `engineering, come up` first, then
`test B3 failed, he vectored me at four miles` — the ID is the whole point, and
you can add detail or not. Engineering answers on whatever channel you called
from and logs everything to `build/debug-notes.md`.

**Comms:** A 139 Center · B 124 Approach · C 118 Tower · D 131 Sentry.
Everything on the approach — vectors, mile calls, landing clearance — is on
**124**. You should not be sent to Tower until you are over the runway.

Priority column: **P1** never flown, this sortie is the first real test ·
**P2** seen working live once, confirming it stuck · **P3** nice to have.

---

## A — before you start the engine

| ID | Test | What should happen | Fix under test |
|----|------|--------------------|----------------|
| A1 | **Ask** for engineering, in your own words, on 124 — then again on 118 | Answer on **both**, same voice, within a second | [#4] `engineering_ack` |
| A2 | Have engineering step away (`tools/bench.py off`), then ask for him | *"not at the bench right now, keep talking, every word is recorded"* — **never silence** | [#4] `engineering_attended` |
| A3 | After A1, say something with no `debug log` prefix | *"Copied, logged."* — and **Approach must not answer it** | [#4] `_ENG_CALL` |
| A4 | Say `thanks engineering`, then call Approach normally | Released; the next call goes to ATC | [#4] `_ENG_DONE` |

**P1.** A1–A4 are the tool you will use for everything else, so they go first. If
A2 gives silence, stop and tell me — every other test gets harder to report.


**What each one is actually checking**

**A1** — Say it however you like: *"get engineering on the line"*, *"engineering, you there?"*, *"Hoover one one for engineering"*, *"need engineering"* — it is looking for you ASKING, not for a magic phrase. Merely mentioning the word does not summon him, so *"engineering said the vectors are fixed"* still reaches the controller. Engineering has to be reachable on **more than one channel** — it used to be a process launched by hand per frequency, so when you changed radio there was simply nothing there.

**A2** — Somebody has to arrange this: while an engineer holds the bench you will always get the cheerful answer. `tools/bench.py off` vacates it (`on` claims it, no argument asks) — say so on the radio and engineering will do it. Silence is the actual bug. You could not tell a dead channel from an engineer with his head in the code, so it now always tells you which world you are in.

**A3** — Once you have called engineering up, your words come to me and **not** to the controller. Without this the ATC answers your bug report, and the report ends up buried in its reply.

**A4** — And you can hand the frequency back without restarting anything — otherwise talking to engineering costs you the controller for the rest of the sortie.

---

## B — the approach (the one that has been flown most, and broken most)

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| B1 | P2 | Call Approach from ~20 nm NW for the radar approach | Radar contact, altimeter, vectors — **all on 124** | [#7] |
| B1a | **P1** | Get handed from Center to Approach, then **wait** before checking in | Approach says **nothing** until you check in — no half-finished instruction | [#6] `_heard_on` |
| B2 | P2 | Fly it in | Mile calls every mile, one voice, one channel | [#7] `final_hz` |
| B3 | P2 | Watch the vectors between 20 and 11 nm | Should converge. **A turn away from the field is the known outbound flip — report it** | [#19] — open, see §E |
| B4 | P1 | At about 4 nm, key the mic and talk for ~15 seconds | Controller **waits**, then makes the call it was holding. It must not be lost | [#5] `channel_is_free` |
| B5 | P1 | Read back a clearance immediately after he issues one | ~7 s of quiet for you to do it | [#5] readback window |
| B6 | P2 | Continue to the missed approach point | *"over the missed approach point"* — and **no handoff to Tower before it** | [#8] `hands_to_tower_nm` |
| B7 | P2 | Land and stop | **Tower sends you off the runway** — *"welcome, exit the runway when able, taxi to parking, good day"* — then goes quiet | [#9] `report_down` |
| B8 | **P1** | **Go around at the point.** Climb out on the published missed (330) | Every call is about the missed — climb, published heading, re-sequencing. **No turn back towards the field. Never "left of course"** | [#11] `flying_the_missed` |
| B9 | P1 | Reaching the missed approach altitude | Re-sequenced normally; he is an ordinary arrival again | [#11] |

**B4 is the headline test of this sortie.** It is the "talks over us constantly"
fix and it has only ever been proven against a synthetic pilot.


**What each one is actually checking**

**B1** — Everything about the approach on ONE channel. The talkdown used to transmit on Tower's frequency while the model answered on Approach's, which arrived as two voices disagreeing.

**B1a** — A controller must not start working you before you have tuned him. The metronome knew you from *Center's* frequency and began mid-instruction.

**B2** — The mile calls ARE the surveillance approach — one voice, one channel, every mile. Silence is indistinguishable from having been forgotten.

**B3** — **The last reversal, and the one I have never been able to fix.** Between about 20 and 11 miles the controller is closing you onto the final approach course, and each vector should bring you nearer to it — a heading that swings *further* from the field is the bug. It shows up when you are inbound and more than about two miles off course, and it is the only thing on this card that has beaten four separate attempts: every fix I tried made the synthetic sweep worse, so the geometry you are flying is deliberately the old, known one.

What a good pass looks like: corrections that get smaller as you close, rolling you out on about 124. What the failure looks like: one turn that points you away, usually around fourteen miles, often after you have drifted well off course.

**The four things worth saying if it happens** — your range, roughly how far off course you were, which way he turned you, and whether he corrected it on the next call or kept going. The bridge log records the radar picture for every transmission, so with your range and rough offset I can re-run the exact geometry afterwards and test a fix against it without you flying again. That is worth more than the fix attempt itself: I have four failures because I had no repro.

**B4** — A radio is half duplex and so are the manners. The metronome transmitted on its own schedule regardless of who was talking — and a call it holds must be **made afterwards, not dropped**.

**B5** — A readback needs somewhere to go. Filling that gap destroys the only check anyone has on whether you got the numbers right, and several were mangled the night this was found.

**B6** — On a talkdown the controller IS your approach aid, so sending you to Tower mid-approach takes you off the frequency that is flying it. On an ILS the same handoff is correct — the difference is the procedure, not the field.

**B7** — The scope knows you are down; nothing was reading it, so a pilot once sat parked while Tower worked him as a missed approach. The thing to listen for is a **positive instruction**, not an absence: silence would be indistinguishable from a controller who has crashed or simply lost you, and this is the last thing that happens on every flight. He should say it once, within a sweep or two of you stopping, and then stay off the air. It is a taxi instruction rather than a farewell on purpose — *"landing assured, good day"* is what you say to somebody still in the air, and hearing it while sitting on the runway is a controller who has not noticed you arrive.

It is also the moment the runway frees for whoever is holding behind you, so on a two-ship this is what lets number two start down.

**B8** — Open for three sessions and four failed attempts: climbing out on the published missed, you were vectored back towards the field. The fix is new and **has never been flown**.

**B9** — The other half of B8 — the latch has to release. Stuck on the missed approach for ever would be a worse bug than the one it fixed.

---

## C — the things never flown by a human

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| C1 | P1 | Ask Approach for a **visual approach** | Granted without argument: *"cleared visual approach runway one three, report the field in sight"* | [#10] `request_visual` |
| C2 | P1 | On the visual, listen for mile calls | **Silence.** He is spacing, not talking you down | [#10] `may_be_vectored` |
| C3 | P1 | Report `field in sight` (do **not** say "request the visual") | Treated as a report, not a request | [#10] intent ordering |
| C4 | P1 | Two-ship: check in as a flight, then request break-up | Each aircraft **named in order** and asked to check in individually | [#12] `_identify_phrase` |
| C4a | P2 | Lead checks in as the FLIGHT ("Pony one, flight of two"), then after the split says "Pony one one" | He is addressed as **Pony one one** from then on, not as the flight | [#12] `transmitter_callsign` |
| C4b | P2 | Wingman checks in as "Pony one two" | Addressed as **Pony one two**, distinct from lead, and it sticks | [#12] `transmitter_callsign` |
| C4c | P2 | Anywhere: say something with a number but no callsign — "I have two aircraft", "say my altitude" | **No new aircraft appears in the stack** | [#13] `_plausible_callsign` |
| C5 | P1 | Depart Batumi on the sortie, outbound past 25 nm | Center **keeps you** until you leave his airspace — no early handoff to Approach | [#16] `leaving_my_airspace` |
| C6 | P1 | Coming home, inbound | Center hands you to Approach normally | [#16] `handoff_from` |
| C7 | P2 | Ask Sentry for range to `ingress`, `waypoint three`, and the target | Computed, and **consistent when asked twice** | [#17] `push_fixes` |
| C8 | P1 | Ask Sentry for something with no fix | *"no fix for that"* — an honest miss, never an invented mile count | [#17] overlord brief |
| C9 | P2 | Ask Sentry to place a target somewhere | Placed, then tasked onto with a bearing and range | [#17] `spawn_ground` |

**C5 is the one I am least sure of.** It fires on live geometry I could not
reproduce alone. If Center hands you off on departure anyway, that is the fix
not working, not you misreading it.


**What each one is actually checking**

**C1** — Asking for a visual should be enough. The controller used to refuse outright and had to be argued into it.

**C2** — A visual means he stops talking you down. Reading ranges to a man looking at the runway is chatter over somebody busy.

**C3** — 'Request the visual' and 'field in sight' are one word apart and mean opposite things — asking versus reporting. Backwards, it either denies you an approach or clears one while you are still in cloud.

**C4** — Identity has to be settled BEFORE anyone is separated. A controller who cannot tell two aeroplanes apart cannot keep them apart.

**C4a** — A lead who checked in for the formation was stuck with the flight's name. Saying your own callsign **once** must be enough to change it — you cannot out-vote yourself.

**C4b** — The wingman ends up distinct and stays that way, including when the transcriber hears 'Pony one *too*'.

**C4c** — Noise must not become an aeroplane. A garbled call once put 'Waypoint 3' in the holding stack, and real aircraft were sequenced behind a ghost.

**C5** — Range cannot express 'keep him until he leaves', because range does not know whether you are arriving or departing. Airspace does.

**C6** — And the ordinary inbound handoff still has to work — the risk in C5 is breaking this.

**C7** — Computed off the live track cache, not estimated. Ask twice and get the same answer, because a pilot cannot tell a computed number from a guessed one.

**C8** — An honest miss beats an invented number every time. 'No fix for that' is a good answer.

**C9** — The overlord can actually put something in the world and task you onto it — and reports what the sim really created, not what she asked for.

---

## F — two pilots at once (needs Hoover + one more)

The case with the least evidence behind it. One controller, two aeroplanes, one
frequency — and the failure is not a wrong instruction, it is a **right
instruction the wrong man hears, or nobody hears at all**.

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| F1 | P1 | Both check in. Watch who each reply is addressed to | Every reply names the man who actually spoke | [#14] the FROM line |
| F2 | P1 | **One of you on final taking mile calls, the other calls Approach with a long request** | The mile calls **pause** and resume — not lost, not on top of him | [#5] `channel_is_free` |
| F3 | P1 | Same, but transmit again the moment the other man stops, before ATC answers | ATC answers the first man. The metronome must **not** fill the thinking time | [#5] `answering` |
| F4 | P1 | Number two, while holding | Hears the hold and **nothing else**. No vectors until it is his turn | [#15] `may_be_vectored` |
| F5 | P2 | Break up, then each say his own callsign once | Addressed individually from then on | [#12] `transmitter_callsign` |

**F2 and F3 are the ones I could not prove alone.** Synthetic pilots take turns
politely and my AI aircraft drifted past the field, so the metronome never had
much to say and never really contested the channel. The failure mode to watch
for is a mile call landing where your answer should have been.

**F4 matters most for safety.** If the man holding starts getting vectors, that
is two aircraft flying the same intercept — stop and say so.


**What each one is actually checking**

**F1** — Two pilots, and every reply names the man who actually spoke. The bridge knew and was not telling the model, which inferred the caller and got it wrong.

**F2** — The same courtesy as B4, but contested: one of you is taking mile calls while the other talks. **This has never been properly tested** — synthetic pilots take turns too politely.

**F3** — The gap between you stopping and the answer arriving is three to nine seconds of model thinking, and the metronome would happily fill it with somebody else's mile call.

**F4** — The safety one. If the man holding starts getting vectors, that is two aircraft flying the same intercept — stop and say so.

**F5** — Identity through the split, with two real radios. One SRS client is one radio, so this cannot be tested any other way.

---

## D — identity and the radio

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| D1 | P2 | Say your callsign clearly on the first call, then mumble one later | He keeps calling you the right thing | [#13] `transmitter_callsign` |
| D2 | P1 | Say `Sentry` and `ingress` a few times across the sortie | Transcribed correctly — was coming through as "Century" and "in-grass" | [#13] `whisper_vocabulary` |
| D3 | P2 | Call Approach by the wrong name (say "Batumi Tower" on 124) | Corrected **and told which frequency you are on** | [#7] |
| D4 | P3 | Two aircraft airborne, neither cleared | **Neither** gets vectors until one is cleared | [#15] `may_be_vectored` |
| D5 | P3 | Try to start a second bridge while one runs *(ground test, my end)* | Refuses, names the PID | [#18] `claim_the_frequency` |


**What each one is actually checking**

**D1** — Your identity is anchored to the RADIO, not to the words, so it survives a mangled or missing callsign.

**D2** — The transcriber is primed with the names actually in play — these came through as 'Century' and 'in-grass', and one garble hijacked a radio for a whole sortie.

**D3** — He corrects you rather than accepting whatever he is called, and tells you which frequency you are on — agreeing would put Tower on a frequency Tower is not on.

**D4** — With traffic and nobody cleared, a vector is an invitation that two aircraft accept at once.

**D5** — Two bridges on one frequency was the most-repeated failure of squadron night, and killing the launcher does not kill the process.

---

## E — known broken. Do not report these as new

These are open bugs with repros. Seeing them means the world is as expected;
they are on the card so you do not spend a sortie re-finding them.

| What you will see | Status |
|---|---|
| An outbound turn around 14 nm while inbound and >2 nm off course | [#19] — open. Four attempts, all regressed the sweep |
| Circling near the field instead of being taken out (rare; behind the field) | [#20] — open, 3 of 1,296 on the sweep |
| The controller naming a field or frequency that is not on your chart | [#21] — open. "proceed KOBULETI, contact Kobuleti Departure" was invented whole |

**The go-around reversal is FIXED** — it was on this list for three sessions and
is now test B8. If it comes back, that is a regression and the most important
thing you can tell me.

**If a reversal happens that is not one of these**, that is new and worth the
radio call — say what you were doing and roughly where.

---

## Notes for whoever flies this

- **You do not have to do it all.** A is 3 minutes and makes everything else
  reportable. B is one approach. C needs a second pilot only for C4.
- **A failure is more useful than a success**, and a *description* of a failure
  is more useful than a verdict. "He said turn left one six nine at four miles
  and I was on course" beats "the vectors are broken".
- Everything you say to engineering lands in `build/debug-notes.md` with a
  timestamp, and the bridge log has the radar picture for every call — so a
  bad vector can be re-run against the geometry afterwards without flying again.

## The ladder, and what has been through it

Cheapest first, per CLAUDE.md. Nothing reaches a human until the two tiers
below it are clean, because a person's time is the expensive one and a
synthetic pilot never gets bored.

| Tier | What | Cost |
|------|------|------|
| 1 | `uv run python -m unittest discover -s tests -t .` | milliseconds |
| 1b | `tools/asr_sweep.py` (add `--sloppy`) — 1,296 approaches | seconds |
| 2 | `python -m marshall.srs.rehearsal --srs <host> 124.0 breakup` — synthetic pilots on real radios, real Whisper, real Polly | a few minutes |
| 3 | AI aircraft in the sim (`tools/spawn.py`) + synthetic pilots — the first tier where a radio, a callsign and a TRACK are three different things | minutes |
| 4 | **A human.** This card. | a sortie |

**Tier 3 earns its keep too.** It found a crash -- `handoff_phrase` read a
radar fix that an airspace handoff does not have, and the bridge went down
silent with pilots on the frequency. Wording took out the process. It also
caught the controller working a man before he had checked in, and the model
addressing a wingman as his leader because the scope had a formation bound to
it as if it were an aeroplane.

**Tier 2 earns its keep.** The break-up identification work passed tier 1 and
was then rejected by tier 2, which produced "Pony won", "Pony12" and an
aeroplane called "21-2" that took a place in the holding stack behind two real
ones. A unit test cannot find that, because the defect only exists once real
speech is in the loop.

*Correlations are to `main`; `git show <hash>` for the reasoning behind any of
them.*
