# Flight test card — squadron-night fixes

One sortie, in order. Each test names the change behind it, so **a failure points
at one commit and one function** instead of at "the ATC was weird".

Every row names an **issue** in `docs/ISSUES.md`, which carries the acceptance
criteria. **Everything a script can close has been taken off this card.** Twenty-three rows
went when their issues closed; they live on in `tools/` and run from
`tools/check.py`, so nothing is unguarded — it is just no longer yours to fly.
What is left needs a person. A test that fails is a comment on that issue; a section that passes
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
| B1a | [script] | Get handed from Center to Approach, then **wait** before checking in | Approach says **nothing** until you check in — no half-finished instruction | [#6] `_heard_on` |
| B3 | P2 | Watch the vectors between 20 and 11 nm | Should converge. **A turn away from the field is the known outbound flip — report it** | [#19] — open, see §E |
| B4 | P1 | At about 4 nm, key the mic and talk for ~15 seconds | Controller **waits**, then makes the call it was holding. It must not be lost | [#5] `channel_is_free` |
| B5 | P1 | Read back a clearance immediately after he issues one | ~7 s of quiet for you to do it | [#5] readback window |
| B8 | **P1** | **Go around at the point.** Climb out on the published missed (330) | Every call is about the missed — climb, published heading, re-sequencing. **No turn back towards the field. Never "left of course"** | [#11] `flying_the_missed` |
| B9 | P1 | Reaching the missed approach altitude | Re-sequenced normally; he is an ordinary arrival again | [#11] |

**B4 is the headline test of this sortie.** It is the "talks over us constantly"
fix and it has only ever been proven against a synthetic pilot.

**What each one is actually checking**

**B1a** — A controller must not start working you before you have tuned him. The metronome knew you from *Center's* frequency and began mid-instruction.

**B3** — **The last reversal, and the one I have never been able to fix.** Between about 20 and 11 miles the controller is closing you onto the final approach course, and each vector should bring you nearer to it — a heading that swings *further* from the field is the bug. It shows up when you are inbound and more than about two miles off course, and it is the only thing on this card that has beaten four separate attempts: every fix I tried made the synthetic sweep worse, so the geometry you are flying is deliberately the old, known one.

What a good pass looks like: corrections that get smaller as you close, rolling you out on about 124. What the failure looks like: one turn that points you away, usually around fourteen miles, often after you have drifted well off course.

**The four things worth saying if it happens** — your range, roughly how far off course you were, which way he turned you, and whether he corrected it on the next call or kept going. The bridge log records the radar picture for every transmission, so with your range and rough offset I can re-run the exact geometry afterwards and test a fix against it without you flying again. That is worth more than the fix attempt itself: I have four failures because I had no repro.

**B4** — A radio is half duplex and so are the manners. The metronome transmitted on its own schedule regardless of who was talking — and a call it holds must be **made afterwards, not dropped**.

**B5** — A readback needs somewhere to go. Filling that gap destroys the only check anyone has on whether you got the numbers right, and several were mangled the night this was found.

**B8** — Open for three sessions and four failed attempts: climbing out on the published missed, you were vectored back towards the field. The fix is new and **has never been flown**.

**B9** — The other half of B8 — the latch has to release. Stuck on the missed approach for ever would be a worse bug than the one it fixed.

---

## C — the things never flown by a human

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| C1 | P1 | Ask Approach for a **visual approach** | Granted without argument: *"cleared visual approach runway one three, report the field in sight"* | [#10] `request_visual` |
| C2 | P1 | On the visual, listen for mile calls | **Silence.** He is spacing, not talking you down | [#10] `may_be_vectored` |
| C3 | P1 | On any approach, once you can see the runway: *"Hoover one one, field in sight"* | **A landing clearance and the wind** — *"cleared to land runway one three, wind two seven zero at two zero"* | [#10] intent ordering |

**C5 and C6 are script-checked now** (`tools/handoff_check.py`). "I could not
reproduce it alone" turned out to mean "not while somebody was flying" —
spawned traffic and the airspace view drive it perfectly well, including the
case that matters: an aircraft that has left Approach's airspace being handed
back to Center.

**What each one is actually checking**

**C1** — Asking for a visual should be enough. The controller used to refuse outright and had to be argued into it.

**C2** — A visual means he stops talking you down. Reading ranges to a man looking at the runway is chatter over somebody busy.

**C3** — *"Request the visual"* and *"field in sight"* are one word apart and mean opposite things: one is asking for an approach, the other is telling him you already have the runway. They used to classify the same way, because the bare word *visual* belonged to the reporting pattern and swallowed both.

The failure is easy to hear and slightly absurd: instead of clearing you to land he offers you a visual approach and asks you to **report the field in sight** — which you just did. If that happens, say so; it means the two have swapped again.

The other direction is the dangerous one and you are unlikely to see it from the cockpit: a *request* read as a *report* would clear an aircraft to land while it is still in cloud with no runway anywhere.

---

## F — two pilots at once (needs Hoover + one more)

The case with the least evidence behind it. One controller, two aeroplanes, one
frequency — and the failure is not a wrong instruction, it is a **right
instruction the wrong man hears, or nobody hears at all**.

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| F2 | [script] | **One of you on final taking mile calls, the other calls Approach with a long request** | The mile calls **pause** and resume — not lost, not on top of him | [#5] `channel_is_free` |
| F3 | [script] | Same, but transmit again the moment the other man stops, before ATC answers | ATC answers the first man. The metronome must **not** fill the thinking time | [#5] `answering` |
| F4 | [script] | Number two, while holding | Hears the hold and **nothing else**. No vectors until it is his turn | [#15] `may_be_vectored` |

**F2 and F3 are script-checked now** (`tools/channel_check.py`). "Synthetic
pilots take turns too politely" was true of my harness and not of scripts: one
can contest a channel far more precisely than two people, transmitting exactly
when a call is due and again the instant the other man stops. Still worth a
listen in the air — a mile call landing where your answer should have been is
the thing to notice.

**F4 matters most for safety.** If the man holding starts getting vectors, that
is two aircraft flying the same intercept — stop and say so.

**What each one is actually checking**

**F2** — The same courtesy as B4, but contested: one of you is taking mile calls while the other talks. **This has never been properly tested** — synthetic pilots take turns too politely.

**F3** — The gap between you stopping and the answer arriving is three to nine seconds of model thinking, and the metronome would happily fill it with somebody else's mile call.

**F4** — The safety one. If the man holding starts getting vectors, that is two aircraft flying the same intercept — stop and say so.

---

## D — identity and the radio

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| D4 | **P1** | Both of you check in with Approach. **Neither asks for the approach yet.** Wait a minute | He talks to you both, but issues **no vectors to either**. First vector comes only after somebody is cleared | [#15] `may_be_vectored` |

**What each one is actually checking**

**D4** — **The safety one, and the reason the deterministic engine exists at all.** With traffic on frequency a vector is not information, it is an *invitation to start the approach* — so issuing one to two aircraft that have not been sequenced is two aeroplanes flying the same intercept to the same fix at the same altitude. That is not a talk-down, it is a collision brief.

To set it up: both check in, neither requests the approach. He should be perfectly happy to talk to you — altimeter, radar contact, questions — while issuing **no turn to anybody**. The moment one of you is cleared, that one starts getting vectors and the other should hear only his hold.

**What the failure looks like:** you both get *"turn right heading..."*, usually with different headings and different altitudes, seconds apart on one frequency. If that happens, **stop and say so immediately** — do not fly it and see what happens.

It has happened, and the cause is worth knowing because it makes this a regression watch rather than a one-off: the guard asked the *blind* engine how many aircraft existed, and that engine only learns of an aeroplane when somebody says its name on the radio. A bridge restart emptied it, so the very next radar sweep saw "fewer than two aircraft known" and vectored both. **Anything that restarts the bridge mid-sortie re-opens this**, which is why it is worth a minute of a two-ship sortie every time.

---

## E — known broken. Do not report these as new

Open bugs with repros. Seeing one means the world is as expected — they are on
the card so you do not spend a sortie re-finding something already understood.

**Each has an ID so you can still call it.** "E1 again, eighteen miles" is worth
saying: it tells me the conditions, and I have never had a repro for E1 from a
real aeroplane. What is *not* worth a call is discovering it.

| ID | Prio | What you will see | Where the line is — what would be NEW | Issue |
|----|------|-------------------|----------------------------------------|-------|
| E1 | note | Inbound, more than ~2 nm off course, somewhere around 14 nm: one vector turns you **away** from the field | A turn away when you are ON course, or inside 11 nm, or on the second attempt after correcting | [#19] |
| E2 | note | After a go-around or arriving from behind the field: he circles you near the field instead of taking you out | Circling while you are **inbound and established** — E2 is a repositioning bug, not an approach one | [#20] |
| E3 | note | A field, frequency or fix named that is not on your chart — *"proceed KOBULETI, contact Kobuleti Departure one two four"* | Any of it. Say what he named; every instance is a separate escape | [#21] |

**What each one actually is**

**E1** — The last reversal, and the one that has beaten four attempts. Between 20
and 11 miles he is closing you onto the final approach course and each vector
should bring you nearer to it; one that swings further out is this bug. Every fix
tried made the synthetic sweep worse, so the geometry you are flying is
deliberately the old known one. **Worth calling anyway** — your range and rough
offset let me re-run the exact geometry afterwards, and four failed attempts is
what having no repro costs.

**E2** — Three starts in 1,296 on the sweep, all of them 8–12 nm *behind* the
field on the departure side. The aircraft is sent to reposition, the bearing to
the entry gate rotates the same way it is turning, and it chases it round — a
stable orbit that, sampled once a revolution, looks like an aeroplane frozen in
the sky. You are unlikely to meet it: it needs you to arrive from the wrong side
at holding altitude. If you do, it will feel like being ignored rather than being
turned.

**E3** — The model inventing a procedure whole. Three have reached the air:
clearing a Mustang with no ADF for a *beacon* approach and asking him to report a
fix he had no receiver for; "landing assured", which is your determination and not
his; and the Kobuleti handoff, which named a field, a frequency and a procedure
that exist nowhere in the plan. **All three were caught by a pilot and none by
anything here**, because a test can check that a call was made, not that it is
something a controller would ever say. That is why every instance is worth
reporting even though the class is known — the specific words are the evidence.

**The go-around reversal is FIXED.** It sat on this list for three sessions and is
now test B8. If it comes back, that is a regression and the most important thing
you can tell me all sortie.

**A reversal that is not E1 or E2 is new** — say what you were doing and roughly
where. New is more valuable than confirming.

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
