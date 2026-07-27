# Flight test card — squadron-night fixes

One sortie, in order. Each test names the change behind it, so **a failure points
at one commit and one function** instead of at "the ATC was weird".

Every row names an **issue** in `docs/ISSUES.md`, which carries the acceptance
criteria. **Everything a script can close has been taken off this card.** Thirty-five rows
went as their issues closed; they live on in `tools/` and run from
`tools/check.py`, so nothing is unguarded — it is simply no longer yours to fly.

What is left is the engineering channel, which is the one thing on this project
a script genuinely cannot judge (whether a human on the other end is USEFUL), and
the three known-broken rows in section E, which are there so you do not spend a
sortie re-finding them. A test that fails is a comment on that issue; a section that passes
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
| A6 | P1 | On the go-around, listen to every instruction | Nothing named that is not on your chart. **"Proceed Kobuleti, contact Kobuleti Departure" is the failure** — it exists nowhere | [#30] |
| A4 | Say `thanks engineering`, then call Approach normally | Released; the next call goes to ATC | [#4] `_ENG_DONE` |

**P1.** A1–A4 are the tool you will use for everything else, so they go first. If
A2 gives silence, stop and tell me — every other test gets harder to report.

**What each one is actually checking**

**A1** — Say it however you like: *"get engineering on the line"*, *"engineering, you there?"*, *"Hoover one one for engineering"*, *"need engineering"* — it is looking for you ASKING, not for a magic phrase. Merely mentioning the word does not summon him, so *"engineering said the vectors are fixed"* still reaches the controller. Engineering has to be reachable on **more than one channel** — it used to be a process launched by hand per frequency, so when you changed radio there was simply nothing there.

**A2** — Somebody has to arrange this: while an engineer holds the bench you will always get the cheerful answer. `tools/bench.py off` vacates it (`on` claims it, no argument asks) — say so on the radio and engineering will do it. Silence is the actual bug. You could not tell a dead channel from an engineer with his head in the code, so it now always tells you which world you are in.

**A3** — Once you have called engineering up, your words come to me and **not** to the controller. Without this the ATC answers your bug report, and the report ends up buried in its reply.


**A6** — The one you asked to fly next, and the reason is the pattern: it has landed on the **missed approach both times**. That is when the model has least to work with and the most pressure to say something, so it invents a procedure — a field, a frequency and a handoff that exist nowhere in the plan, offered to a pilot who has just gone around and is looking for instructions. Go around, then read back every name he says and check it against your chart. Say exactly what he named; the specific words are the evidence.

**A4** — And you can hand the frequency back without restarting anything — otherwise talking to engineering costs you the controller for the rest of the sortie.

---

## G — clearance delivery, at the ramp (before B)

Flown before you start the engine, on **118** — Tower also works ground and
clearance delivery, because a field this size does not staff a seat per phase of
flight. Everything here is new and has never been said to a human.

**The board is on the PLANS tab** of this kneeboard, read live from the director
— five plans, one word each. Samovar and Kettle share a task on purpose (the CAS
over Tsutsnvati, flown two ways) and are marked as such; that pair is G5.

Ten to fifteen minutes on the ramp, in order — each row sets up the next, so
they read as one conversation rather than eight. **Have something to write on.**
The whole point of G2 is whether you can get it down.

Most of this is script-checked already: which plan a request resolves to
(`tools/plan_sweep.py`, twelve phrasings) and that two flights can hold two plans
without treading on each other (`tools/plan_assign_check.py`). What no script can
judge is whether a clearance is **copyable** — whether a man with a pencil, in a
cockpit, can actually get it down at the pace it is read.

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| G1 | P1 | *"Batumi Ground, Hoover one one, request IFR clearance, Marlin"* | The **whole** CRAFT clearance: cleared to Batumi, as filed, three thousand, departure frequency one two four decimal zero, and a squawk | [#1] `request_clearance` |
| G2 | P1 | Write G1 down as he says it, then read it back **correctly** | You got all five elements without asking for a repeat, and he says *"readback correct"* and stops talking | [#1] copyable |
| G3 | P1 | Ask again for Marlin, and read it back with **one number wrong** | He corrects **that number only** and asks for it again — not the whole clearance, and never a shrug | [#1] `clearance_read_back` |
| G4 | P1 | Ask by what you are DOING, no name — *"request clearance for the weather run out to Ingress"* | Lantern's clearance, five thousand. You should never have had to say a plan name | [#1] `plans.pick` |
| G5 | P1 | *"request clearance for the CAS over Tsutsnvati"* | A **question** naming both — the plain one, and the one with the beacon letdown on return. He must not pick for you | [#1] `plans.pick` |
| G6 | P1 | Answer it — *"the beacon letdown one"* | Kettle: eleven thousand, and the route out through Ingress to Tsutsnvati | [#1] `plans.pick` |
| G7 | P2 | *"request clearance to Vaziani"* | *"nothing on file"* and a question. **Not** the nearest plan read out as though you had asked for it | [#1] `plans.pick` |
| G8 | P2 | After a clearance, change your mind — *"request a change, make it Anvil"* | A **complete** new clearance (four thousand), read back again. He must not say only what changed | [#1] `assign` amends |
| G9 | P2 | With Shooter: both of you ask for **Marlin**, one after the other | Both get it, both are cleared to three thousand, and neither clearance changes the other's | [#1] one plan, two flights |
| G10 | P3 | Airborne later — *"what am I doing"* or *"where am I going next"* | He answers from your plan without you repeating it, and does not read you ranges you do not need | [#1] `flight_plan_help` |

**What each one is actually checking**

**G1** — The one that matters. The words come back from a tool already finished
and the question is whether the controller reads them or improvises around them.
The **departure frequency is the element to watch**: it went missing in the dry
run twice, and a pilot who never hears it is airborne not knowing whom to call.
The squawk is worth a glance too — it is invented, because DCS has no
transponder, but it is invented in octal, so **a digit above seven is a bug**.

**G2** — Not a formality. A clearance is the one long transmission on the
frequency and it exists to be written down; if you cannot get five elements down
at the pace he reads them, that is a real finding and the fix is his pacing, not
your pencil. A correct read-back is also the only place *"readback correct"*
belongs — airborne, silence is the acknowledgement.

**G3** — A controller who accepts a wrong read-back has recorded an agreement
that was never made. Get the squawk wrong, or the altitude; the failure to watch
for is him reading the entire clearance again, which on a busy frequency is how a
read-back correction becomes worse than the error.

**G4** — The whole design bet. A pilot says what he is DOING, not a database
name — "the weather run out to Ingress" is how he would ask a real controller,
and it names one plan here. If you have to fall back on the label, say so: the
labels are the escape hatch, not the interface.

**G5** — Two plans on file are the same sortie flown two ways, differing only in
the recovery at the end. Asking is the correct answer and the hard one; the easy
failure sounds decisive and clears you on somebody else's plan. Listen for
whether he describes them by what they ARE — a name you were given yesterday is
not something to recognise under a running engine.

**G6** — And having asked, he has to use your answer. Check the **level**: eleven
thousand is Kettle, three thousand is Marlin, and getting Samovar instead is
invisible until you are on the wrong approach at the end of the sortie.

**G7** — The opposite failure to G5. A resolver that always picks its best match
never says "nothing on file", which looks perfect right up until the night it
routes you somewhere you never asked to go.

**G8** — An amendment REPLACES; it does not accumulate. Two live plans for one
aeroplane is the ambiguity the whole design removes, and a controller who reads
you only the changed part leaves you holding half of one clearance and half of
another. Your read-back also stops counting — you agreed to the old one.

**G9** — The reason plans became templates. Assignment COPIES, so one plan can be
flown by two aeroplanes at once and by the squadron again next week. Script-
checked already; what a script cannot tell you is whether it sounds right on the
radio when two men ask for the same sortie a minute apart.

**G10** — What the aeroplane can do decides how much help you get: a moving map
wants the fix named and nothing else, a Mustang wants position reports and
vectors. It is keyed on the type radar reports, so nobody has to declare it — if
you are in the Mustang and he is terse, or in something modern and he will not
stop reading you ranges, that is the bug.

---

## B — the approach (the one that has been flown most, and broken most)

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|

**B4 is the headline test of this sortie.** It is the "talks over us constantly"
fix and it has only ever been proven against a synthetic pilot.

**What each one is actually checking**

---

## C — the things never flown by a human

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|

**C5 and C6 are script-checked now** (`tools/handoff_check.py`). "I could not
reproduce it alone" turned out to mean "not while somebody was flying" —
spawned traffic and the airspace view drive it perfectly well, including the
case that matters: an aircraft that has left Approach's airspace being handed
back to Center.

**What each one is actually checking**

---

## F — two pilots at once (needs Hoover + one more)

The case with the least evidence behind it. One controller, two aeroplanes, one
frequency — and the failure is not a wrong instruction, it is a **right
instruction the wrong man hears, or nobody hears at all**.

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|

**F2 and F3 are script-checked now** (`tools/channel_check.py`). "Synthetic
pilots take turns too politely" was true of my harness and not of scripts: one
can contest a channel far more precisely than two people, transmitting exactly
when a call is due and again the instant the other man stops. Still worth a
listen in the air — a mile call landing where your answer should have been is
the thing to notice.

**F4 matters most for safety.** If the man holding starts getting vectors, that
is two aircraft flying the same intercept — stop and say so.

**What each one is actually checking**

---

## D — identity and the radio

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|

**What each one is actually checking**

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
| E3 | note | A field, frequency or fix named that is not on your chart — *"proceed KOBULETI, contact Kobuleti Departure one two four"* | Any of it. Say what he named; every instance is a separate escape | [#30] |

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
