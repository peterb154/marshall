# Flight test card — squadron-night fixes

One sortie, in order. Each test names the change behind it, so **a failure points
at one commit and one function** instead of at "the ATC was weird".

Every row names an **issue** in `docs/ISSUES.md`, which carries the acceptance
criteria. **Everything a script can close has been taken off this card.** Thirty-five rows
went as their issues closed; they live on in `tools/` and run from
`tools/check.py`, so nothing is unguarded — it is simply no longer yours to fly.

**Sections B, C, D and F are gone** — every row in them was closed and its
script lives in `tools/`, run by `tools/check.py`. What is left is what a human
is still the only instrument for, in the order you fly it: the ramp (A), the
clearance (G), the approach (H), **identity (J)**, and section E, which exists
so you do not spend a sortie re-finding something already understood.

**Section J is new on 28 July** and is the one to fly first if time is short. It
tests the change that re-keyed the whole board off a spoken callsign onto
evidence nobody speaks, and not one of its rows has ever run in the air. A test that fails is a comment on that issue; a section that passes
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
| A8 | P1 | **In an F-16**, fly the approach from 20 nm and compare every "left/right of course" call against your HSI | The side he calls matches the needle, all the way in. This is the one that settles whether the P-51's instruments were the story | [#35] frames |
| A9 | P1 | Go around, and write down the altitude in the go-around instruction AND the one on the next check-in | The **same number** both times, and it is the plate's missed approach altitude | [#36] |
| A7 | P1 | On the ramp, draw on a chart page with a pen or the mouse, turn the page and come back, then go to the **E6B** page and press a button | Ink appears; the E6B still **works**, because that page is a calculator and keeps its clicks | [#34] `SetCursorEventsMode` |

**A1–A5 are closed** — flown on the ramp on 27 July and attested on #4 and #25.
The engineering channel itself is the tool you use for everything else and it is
working: ask for it in your own words, talk, say thanks or goodbye, and the
frequency goes back to the controller. Their regression checks live in
`tools/` and `tests/test_bridge.py`.

**A6 closed 27 July** — two go-arounds, nothing invented either time. What is
left in this section is A7 (doodling), A8 and A9.

**What it is actually checking**




**A8** — Your idea, and it is the right one. In the Mustang "which side am I
on" is a judgement made by looking out of the window, and tonight we learned its
instruments cannot be trusted for this: the wet compass read 139 where the F10
map said 123 magnetic, and the DG beside it had drifted seven the other way. An
F-16 has an inertial platform and an HSI, so the same question becomes an
instrument reading. If the needle agrees with the controller, the P-51 was the
story and #35 closes. If it does not, the residual is real and we finally have a
clean measurement of it. Fly the same track both ways if you have the patience —
the answer must not depend on what aeroplane you are sitting in.

**A9** — Seen once, live: "climb and maintain three thousand" on the go-around,
then "maintain two thousand" thirty seconds later on the check-in, with your
read-back in between. Write both numbers down as he says them; the specific pair
is the evidence.

**A7** — You said it was a setting, and it was. The tab defaults to mouse
emulation, so a pen stroke arrives as a mouse drag and draws nothing; the page
now asks for `DoodlesOnly` instead. What to check is the pair: ink on the pages
you write on, AND the E6B still taking button presses, because that one is a
calculator and switching the whole tab to ink would have quietly broken it. If
the strokes vanish on a page turn, say so — that is OpenKneeboard's ink and how
long it keeps it is its business, not ours, but it decides whether this is
finished or whether we draw our own.


---

## G — clearance delivery, at the ramp

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

---

---

---

## H — the approach, rebuilt overnight (the main event)

Everything in this section changed after the 27 July sortie and **none of it has
been flown**. It is one approach, start to finish, and it is the whole point of
tomorrow.

Three things moved, and each has a row that can fail on its own:

* **The approach is flown to the THRESHOLD**, not to the runway centre half a
  mile beyond it. This is the "I was always too high" fix.
* **The centreline is in the right frame.** It was six degrees off — the course
  was in the sim's grid frame and the radials are true.
* **Corrections on final are RELATIVE.** "Turn left ten degrees", no heading.

**Fly it in the Jug** (its compass is honest) and **reset the DG before you turn
inbound**. If everything below passes, #19, #20, #35 and #37 all close on your
name in one sortie.

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| H1 | P1 | Inbound from 20 nm, on the centreline. Compare each "left/right of course" call against where the runway actually is | The side he calls is the side you are on, **every call, all the way in**. This is the one that was wrong all night | [#35] frames |
| H2 | P1 | Fly the descent profile as given and note your altitude crossing the **threshold** | You arrive at the threshold at minimums, not 200 ft high with half a mile of descent owed | [#19] touchdown |
| H3 | P1 | Listen to the range calls near the end | "One mile from the runway" means one mile from the **threshold**. Previously it meant one mile from the runway centre, which is where you were already landing | touchdown |
| H11 | P2 | With Shooter, or by asking for the approach while somebody else is on it: **get yourself held** | *"hold at five thousand, right turns, one eight zero outbound one minute, then three six zero inbound one minute"* — a shape and a clock you can actually fly with no navaid. Not "hold at BATUMI as published" | hold |
| H12 | P1 | Arrive **180 out of phase** — on the centreline heading away from the field — and ask for the approach | Downwind, base, then a 30-45 degree turn onto final. Recognisable legs and no reversal. Previously he was aimed at the fix and turned hard 180 | [#39] |
| H13 | P2 | Fly the approach **fast** — 400 kt or more — and watch the turn from base onto final | He may overshoot: **known open**, criterion 2. The sweep at 450 kt says 181 dithering events and a 5.1 nm turn radius against a 3 nm base leg — so expect **left/right reversals**, not a clean overshoot. Report how far through you go | [#39] |
| H10 | P1 | Arrive high — **5,000 ft or above, 30 nm out** — and ask for the approach. Note where he starts you down | He keeps you high, then sends you down **once**, timed so you reach 2,000 arriving at the initial fix. Not levelled at 2,000 ten miles early | [#37] descent |
| H9 | P1 | Once established, listen to the **altitude** part of each mile call | *"four miles, on course, **descend to** one thousand three hundred"* — an instruction for the NEXT mile, arriving in time to fly it. Not "altitude should be", which tells you where you already ought to be | anticipatory |
| H4 | P1 | Once established, listen to how he corrects you | **"Turn left ten degrees"** — no heading at all, rounded to five. If he gives you an absolute heading inside the final approach course, that is the failure | [#37] |
| H5 | P1 | While being vectored (before established), note the headings | Absolute, and ending in **0 or 5** — "heading three one five", never "three one three" | [#37] |
| H6 | P1 | **Deliberately mis-set your DG by 20 degrees** before you turn inbound, then fly the approach on his corrections alone | You still arrive. This is the whole argument for relative corrections and it could not have been passed yesterday | [#37] |
| H7 | P2 | Inbound, **2–3 nm off course, between 11 and 16 nm** — get yourself there on purpose | He gives you an intercept heading. If he sends you OUTBOUND to reposition, that is E1 and it is still open | [#19] |
| H8 | P2 | Arrive from **behind the field**, 8–12 nm on the departure side, and ask for the approach | He takes you out and brings you round. Circling near the field is E2 | [#20] |
| H14 | P1 | **The ladder, step 1.** F-16, whole approach at **300 kt or less** | Clean. The sweep flies this exact grid at 300 kt: 1296/1296 arrive, **zero** dithering. Anything else here is new and matters more than H16 | [#39] |
| H15 | P1 | **The ladder, step 2.** Same approach in the **P-51** | Clean, and for a different reason than H14 — this is the speed the engine was built at, so a failure here is a regression, not a limit | [#39] |
| H16 | P1 | **The ladder, step 3.** F-16, **450 kt or more** inbound | **Predicted to fail**, and how: reversals. At 450 kt a 30° bank gives a 5.1 nm turn radius and the base leg is built around 3, so the engine orders a turn he cannot make and then orders the opposite. If it fails any OTHER way, that is new information and worth more than the expected one | [#39] |
| H17 | P1 | Note **every speed instruction** you are given, and the number | You are asked to slow down at all — this has never been heard on the radio. In the F-16 **never below 210 kt**; the published profile wanted 174, which is the P-51's number | [#39] |
| H18 | P1 | Once established on final, listen for what happens to the speed restriction | *"Resume normal speed"*, **once**, and no further speed assignments. On final the pilot owns his own speed — the controller does not know your fuel or stores | [#39] |

**What each one is actually checking**

**H1** — The bug that cost the whole night. The final approach course was taken
from the F10 map and the aircraft compass, which are in DCS's x/z grid frame,
while the radials come from lat/lon and are true. At Batumi those differ by 5.74
degrees, so every centreline this system ever drew sat south of the runway. It
is confirmed against your own two calls from last night; what it has never had
is somebody flying it afterwards.

**H2** — Your catch, and the most satisfying fix of the night. The descent was
aimed at the runway centre, half a mile past the threshold, so the profile
always had you high by whatever half a mile of glidepath is worth — about 200 ft
at two miles. Note the altitude as the threshold goes under the nose.

**H3** — The same fix heard rather than felt. If "one mile" still sounds like it
arrives late, say so.

**H11** — Yours. With no navaid you cannot hold OVER anything, so a heading
with no leg time is not a hold at all — it is a vector you fly until somebody
stops you. It now gives the level, which way you turn, and both headings with
the time on each, in one transmission and in the order you fly it. Fixing it
also turned up a second code path that wrote its own hold and told you to hold
at BATUMI *as published* on a radar approach — over a beacon you have no
receiver for. Both go through one phrase now. **If you hear "as published" at
Batumi on the radar approach, that is the bug back.**

**H12** — Yours, and the biggest change to the approach since the frames. The
engine used to steer at a POINT, which is why fast meant circles (the bearing to
a point rotates as fast as you turn) and slow meant a hard 180 (arriving at a
place says nothing about arriving on a heading). It now flies you legs.

**H13** — The half of it that is not fixed, written down so you do not report it
as new. At 450 knots the turn from base onto final still overshoots, and the
number you give me — how far through the centreline you went — is what sizes the
fix, because the intercept has to scale with your groundspeed.

**H10** — Yours too, and it needed a whole engine. The old profile was 318 feet
per mile, which is a three-degree path at exactly one speed and wrong for
everything else; 500 fpm costs five miles in the Jug and ten in a jet. It now
computes minutes from the rate and miles from your groundspeed, and holds you up
until the last responsible moment. **Note the range where "descend to two
thousand" arrives** — that number is the whole test, and it should be further in
than it used to be for a slow aeroplane and further out for a fast one. Worth
flying twice, once slow and once fast, if you have the fuel.

**H9** — Yours, and it pairs with H2. The old call was an observation about the
present — "three miles, altitude should be twelve hundred" — so by the time you
had heard it, started down and arrived, you were a mile further in and behind
again. Chasing the profile from above for the whole approach. Now the four-mile
call carries the three-mile altitude and you have a mile to fly it. The last
step says **"descend to minimums"** rather than 732, because nobody sets that on
a subscale.

**H4** — The relative corrections. Absolute headings are only as good as the
gyro you set them on, and yours drifted seven degrees while the wet compass read
sixteen off the map. A difference between two headings cancels all of that.

**H5** — And the other half of the rule: while repositioning you have time to
set a gyro, so those stay absolute — but rounded, because a round number is
easier to hold and to read back.

**H6** — The test that proves the point. Set the DG deliberately wrong, do not
correct it, and fly what he tells you. If relative corrections work, the error
is irrelevant and you land anyway. **Do this one at altitude first if you would
rather not find out on short final.**

**H7** — E1, mapped: inbound, 2 nm or more off, between 11 and 16 nm, and he
sends you outbound to reposition rather than giving you a heading. Under 1.5 nm
off, or beyond 18 nm, it behaves. You will have to put yourself there on purpose
— it is a narrow band and you did not meet it last night.

**H8** — E2. Two starts in 1,296 still orbit on the sweep, both 12 nm behind the
field. The touchdown fix took it from three to two, so it may already be gone
from the air; this is the cheapest way to find out.

---

---

## J — who the controller thinks you are

The board used to be keyed on a string Whisper guessed at from audio. It is now
keyed on evidence nobody speaks: the radio's SRS name, matched against the name
radar prints, and the sim's own account of who has a person in the seat. See
[#40].

**None of this has ever run in the air.** It could not until the morning of
28 July, because the bridge did not know what any radio was CALLED — a socket
timeout had been quietly killing the roster thread, so every client read as a
six-character GUID stub and the strongest evidence in the system was never
available. These rows are the first real exercise of it.

**Run `uv run python tools/identity_watch.py` in a second window.** One line per
transmission: the radio, what the words claimed, and which authority resolved
it. The column that matters is **authority**.

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| J1 | P1 | Fly with your **usual** SRS name and check in normally. Read the `authority` column | **`radar`** — the chain with no microphone in it: SRS name → the name radar prints → your track. If it reads `plan` or `roster` on every call, the roster fix did not take and I want to know before Andre, not after | [#40] `unit_for_radio` |
| J2 | P1 | **Andre checks in cold** — a radio this controller has never heard, nothing filed for him, no setup of any kind | He is identified and vectored on his first call. Ask engineering what `authority` said. `radar` means his SRS name matched his DCS name, which is the expected and best case; `plan` or elimination means the chain did not close and I want the reason | [#40] |
| J3 | P1 | Garble or omit your callsign on one call — mumble it, or say only *"request the approach"* | He answers, and your identity does **not** move. The aeroplane you are in decides who you are; the words are only a claim | [#40] |
| J4 | P1 | With a second aircraft up, say **his** callsign by mistake on one of your calls | Your report must not be filed against his aeroplane. That is a separation error, and it is the one nothing in the system used to report | [#40] |
| J5 | P2 | Read back an instruction sloppily — *"maintained two thousand"*, *"left three sixty"* | **No new aeroplane appears.** Ask engineering for the board if unsure. These exact phrases each invented an aircraft that took a holding level | [#40] guards |
| J6 | P2 | Get radar to lose you — sit on the ramp, or go well out — then call in | *"Not radar identified, say your position and altitude"*, and **nobody is held behind you**. Being unseen must cost you a place in the queue, not give you one | [#40] `may_be_sequenced` |

**What it is actually checking**

**J1** is the whole architecture in one column. Everything else in this section
is a fallback for when it does not close.

**J2** is the one that decides whether a guest can just turn up. It was
originally going to need a flight plan filed for him in advance — which is
setup, and therefore not an answer to "he should work without setting anything
up".

It was also, briefly, written as *"change your SRS name to something unrelated
to your DCS name"* — which cannot be done. **With DCS running, the SRS client
takes its name from the DCS export**, so a pilot cannot set the two
independently. Only a standalone client not attached to DCS can choose its own
name, which is how the synthetic pilots in `srs/crowd.py` connect.

That is worth having straight, because it makes the identity chain STRONGER
than it was designed for: the radio's name and the name radar prints are the
same string, so the match is exact rather than approximate. The elimination
rung stays as the fallback for a pilot radar has not painted yet — and it is
exercised by `crowd.py`, not by a human, since a human cannot produce the
mismatch it handles.

**J4** is the failure that made all of this worth doing. With one pilot a
mis-heard callsign is a ghost, which is untidy. With two it moves the wrong
aeroplane's altitude and place in the queue, and nothing reports it.

---

## E — known broken. Do not report these as new

Open bugs with repros. Seeing one means the world is as expected — they are on
the card so you do not spend a sortie re-finding something already understood.

**Each has an ID so you can still call it.** "E1 again, eighteen miles" is worth
saying: it tells me the conditions, and I have never had a repro for E1 from a
real aeroplane. What is *not* worth a call is discovering it.

| ID | Prio | What you will see | Where the line is — what would be NEW | Issue |
|----|------|-------------------|----------------------------------------|-------|
| E1 | note | Inbound and **2 nm or more off course between 11 and 16 nm**: he sends you outbound to reposition instead of giving you an intercept. Mapped exactly — inside 1.5 nm off, or beyond 18 nm, it behaves | A turn away when you are **under 2 nm off**, or beyond 18 nm, or a REVERSAL rather than a reposition | [#19] |
| E2 | note | After a go-around or arriving from behind the field: he circles you near the field instead of taking you out | Circling while you are **inbound and established** — E2 is a repositioning bug, not an approach one | [#20] |
| ~~E3~~ | — | **CLOSED 27 July** — flown clean twice, nothing invented on either go-around. Guarded by `tools/atc_dryrun.py` | — | — |

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
