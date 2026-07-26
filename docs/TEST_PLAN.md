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
| A1 | Ask engineering for a radio check on 124, then again on 118 | Answer on **both**, same voice, within a second | [ENG-1] `engineering_ack` |
| A2 | Ask on a frequency when nobody is at the bench | *"not at the bench right now, keep talking, every word is recorded"* — **never silence** | [ENG-1] `engineering_attended` |
| A3 | After A1, say something with no `debug log` prefix | *"Copied, logged."* — and **Approach must not answer it** | [ENG-1] `_ENG_CALL` |
| A4 | Say `thanks engineering`, then call Approach normally | Released; the next call goes to ATC | [ENG-1] `_ENG_DONE` |

**P1.** A1–A4 are the tool you will use for everything else, so they go first. If
A2 gives silence, stop and tell me — every other test gets harder to report.

---

## B — the approach (the one that has been flown most, and broken most)

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| B1 | P2 | Call Approach from ~20 nm NW for the radar approach | Radar contact, altimeter, vectors — **all on 124** | [RAD-3] |
| B1a | **P1** | Get handed from Center to Approach, then **wait** before checking in | Approach says **nothing** until you check in — no half-finished instruction | [RAD-2] `_heard_on` |
| B2 | P2 | Fly it in | Mile calls every mile, one voice, one channel | [RAD-3] `final_hz` |
| B3 | P2 | Watch the vectors between 20 and 11 nm | Should converge. **A turn away from the field is the known outbound flip — report it** | *unfixed*, see §E |
| B4 | P1 | At about 4 nm, key the mic and talk for ~15 seconds | Controller **waits**, then makes the call it was holding. It must not be lost | [RAD-1] `channel_is_free` |
| B5 | P1 | Read back a clearance immediately after he issues one | ~7 s of quiet for you to do it | [RAD-1] readback window |
| B6 | P2 | Continue to the missed approach point | *"over the missed approach point"* — and **no handoff to Tower before it** | [APP-1] `hands_to_tower_nm` |
| B7 | P2 | Land and stop | Controller stops working you within a sweep or two | [APP-2] `on_the_ground` |
| B8 | **P1** | **Go around at the point.** Climb out on the published missed (330) | Every call is about the missed — climb, published heading, re-sequencing. **No turn back towards the field. Never "left of course"** | [APP-4] `flying_the_missed` |
| B9 | P1 | Reaching the missed approach altitude | Re-sequenced normally; he is an ordinary arrival again | [APP-4] |

**B4 is the headline test of this sortie.** It is the "talks over us constantly"
fix and it has only ever been proven against a synthetic pilot.

---

## C — the things never flown by a human

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| C1 | P1 | Ask Approach for a **visual approach** | Granted without argument: *"cleared visual approach runway one three, report the field in sight"* | [APP-3] `request_visual` |
| C2 | P1 | On the visual, listen for mile calls | **Silence.** He is spacing, not talking you down | [APP-3] `may_be_vectored` |
| C3 | P1 | Report `field in sight` (do **not** say "request the visual") | Treated as a report, not a request | [APP-3] intent ordering |
| C4 | P1 | Two-ship: check in as a flight, then request break-up | Each aircraft **named in order** and asked to check in individually | [ID-1] `_identify_phrase` |
| C4a | P2 | Lead checks in as the FLIGHT ("Pony one, flight of two"), then after the split says "Pony one one" | He is addressed as **Pony one one** from then on, not as the flight | [ID-1] `transmitter_callsign` |
| C4b | P2 | Wingman checks in as "Pony one two" | Addressed as **Pony one two**, distinct from lead, and it sticks | [ID-1] `transmitter_callsign` |
| C4c | P2 | Anywhere: say something with a number but no callsign — "I have two aircraft", "say my altitude" | **No new aircraft appears in the stack** | [ID-2] `_plausible_callsign` |
| C5 | P1 | Depart Batumi on the sortie, outbound past 25 nm | Center **keeps you** until you leave his airspace — no early handoff to Approach | [HO-1] `leaving_my_airspace` |
| C6 | P1 | Coming home, inbound | Center hands you to Approach normally | [HO-1] `handoff_from` |
| C7 | P2 | Ask Sentry for range to `ingress`, `waypoint three`, and the target | Computed, and **consistent when asked twice** | [OVL-1] `push_fixes` |
| C8 | P1 | Ask Sentry for something with no fix | *"no fix for that"* — an honest miss, never an invented mile count | [OVL-1] overlord brief |
| C9 | P2 | Ask Sentry to place a target somewhere | Placed, then tasked onto with a bearing and range | [OVL-1] `spawn_ground` |

**C5 is the one I am least sure of.** It fires on live geometry I could not
reproduce alone. If Center hands you off on departure anyway, that is the fix
not working, not you misreading it.

---

## F — two pilots at once (needs Hoover + one more)

The case with the least evidence behind it. One controller, two aeroplanes, one
frequency — and the failure is not a wrong instruction, it is a **right
instruction the wrong man hears, or nobody hears at all**.

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| F1 | P1 | Both check in. Watch who each reply is addressed to | Every reply names the man who actually spoke | [ID-3] the FROM line |
| F2 | P1 | **One of you on final taking mile calls, the other calls Approach with a long request** | The mile calls **pause** and resume — not lost, not on top of him | [RAD-1] `channel_is_free` |
| F3 | P1 | Same, but transmit again the moment the other man stops, before ATC answers | ATC answers the first man. The metronome must **not** fill the thinking time | [RAD-1] `answering` |
| F4 | P1 | Number two, while holding | Hears the hold and **nothing else**. No vectors until it is his turn | [SEQ-1] `may_be_vectored` |
| F5 | P2 | Break up, then each say his own callsign once | Addressed individually from then on | [ID-1] `transmitter_callsign` |

**F2 and F3 are the ones I could not prove alone.** Synthetic pilots take turns
politely and my AI aircraft drifted past the field, so the metronome never had
much to say and never really contested the channel. The failure mode to watch
for is a mile call landing where your answer should have been.

**F4 matters most for safety.** If the man holding starts getting vectors, that
is two aircraft flying the same intercept — stop and say so.

---

## D — identity and the radio

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| D1 | P2 | Say your callsign clearly on the first call, then mumble one later | He keeps calling you the right thing | [ID-2] `transmitter_callsign` |
| D2 | P1 | Say `Sentry` and `ingress` a few times across the sortie | Transcribed correctly — was coming through as "Century" and "in-grass" | [ID-2] `whisper_vocabulary` |
| D3 | P2 | Call Approach by the wrong name (say "Batumi Tower" on 124) | Corrected **and told which frequency you are on** | [RAD-3] |
| D4 | P3 | Two aircraft airborne, neither cleared | **Neither** gets vectors until one is cleared | [SEQ-1] `may_be_vectored` |
| D5 | P3 | Try to start a second bridge while one runs *(ground test, my end)* | Refuses, names the PID | [OPS-1] `claim_the_frequency` |

---

## E — known broken. Do not report these as new

These are open bugs with repros. Seeing them means the world is as expected;
they are on the card so you do not spend a sortie re-finding them.

| What you will see | Status |
|---|---|
| An outbound turn around 14 nm while inbound and >2 nm off course | [BUG-1] — open. Four attempts, all regressed the sweep |
| Circling near the field instead of being taken out (rare; behind the field) | [BUG-2] — open, 3 of 1,296 on the sweep |
| The controller naming a field or frequency that is not on your chart | [BUG-3] — open. "proceed KOBULETI, contact Kobuleti Departure" was invented whole |

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
