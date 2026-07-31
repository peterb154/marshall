# Flight test card

One sortie, in order. Every row names an **issue** in `docs/ISSUES.md`, which
carries the acceptance criteria — so a failure points at one commit and one
function rather than at "the ATC was weird".

**Everything a script can close is already off this card.** What is left is what
a human is the only instrument for. Section letters and row IDs are stable: they
are cited on the issues and in the attestations, so J4 is J4 forever even when
the sections are reordered.

## Fly in this order

| | section | issue | needs | why it is on the card |
|---|---|---|---|---|
| 1 | **N — what he calls you** | [#48] | solo | **fly this first.** Everything about identity changed on 30 July and none of it has been heard. It is also the quickest to falsify: three transmissions on the ramp |
| 2 | **M — how fast he answers alone** | [#45] | solo | one radio check. Ground units stopped counting as traffic, so the classifier is off the path — you are judging a pause, and you can only judge it while you still remember the old one |
| 3 | **J — who he thinks you are** | [#40] | solo | identity under stress: garble it, omit it, lose radar. N says he gets it right; J says he keeps it when things go wrong |
| 4 | **G — clearance at the ramp** | [#1] | solo | the awkward half: a wrong read-back, a deliberate ambiguity, an amendment |
| 5 | **H — the approach** | [#19] [#37] [#39] | solo | the main event, and where the open bugs live |
| 6 | **F — landing and the handoff** | [#41] | solo | the sim's own events now drive Tower. Never flown |
| 7 | **K — does he remember** | [#43] | solo, better with two | shipped 30 July, never flown |
| — | **D — flights** | [#42] | **two aircraft** | skip it solo. A formation cannot be flown by one aeroplane, and the break-up rules changed on 30 July |
| — | **E — known broken** | | | read it, so you do not re-find something already understood |

**Solo today?** N, M, J, G, H, F, K — in that order. Only D needs a second
aeroplane. Note that N3, N5 and N6 inside section N are formation rows and want
one too; the rest of N is flyable alone and is the part that changed most.

## How to report

Say `engineering, come up`, then `test H4 failed, he vectored me at four miles`.
The ID is the whole point; detail is optional. Engineering answers on whatever
channel you called from and logs to `build/debug-notes.md`.

**Comms:** A 139 Center · B 124 Approach · C 118 Tower · D 131 Sentry.
Everything on the approach is on **124**. You should not be sent to Tower until
you are over the runway.

**Priority:** **P1** never flown, this sortie is the first real test ·
**P2** seen working once, confirming it stuck · **P3** nice to have.

## Three things that are not bugs

- **~2.2 s of extra delay on every transmission**, including a radio check, when
  the mission holds armour or distant AI. `count_contacts` cannot tell a T-55
  from a Viper. [#45]
- **The board engages while you are alone**, same cause. `/diag` will show it.
- **The paper nav log is 5.74° out on every leg** — grid convergence is applied
  on the radar side and not in `bearing_distance`. 2.39 nm of cross-track on
  KOBULETI→INITIAL.

**New instrument:** `http://<host>/diag` — who he thinks you are, the board
against radar with ghosts flagged, the last decision trail, and the flight
roster, refreshed every two seconds. The fastest way to answer "which brain did
that?" without reading a log.

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

---

## D — flights: forming, joining, breaking up

**Needs a second aeroplane. Skip this section solo.**

Built 29 July and exercised over real SRS against synthetic pilots: created,
joined at 0.2 nm, refused at 8.9 nm, refused an unknown flight, broke out and
rejoined, every verdict voiced correctly. **No human has flown it.** What
synthetic pilots cannot test is anything gated on MANNED — an AI unit reports no
player name, so the elimination rung and the ground-state marker were untouched
by that rehearsal. See [#42].

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| D1 | P1 | Lead: *"approach, &lt;handle&gt;, request creation of Apex flight"* | *"&lt;handle&gt;, you are now the lead of Apex flight. Each member of Apex check in to be joined"* — and he uses your HANDLE, not a slot name | [#42] `parse_create` |
| D2 | P1 | Wingman, formed up inside a mile: *"approach, &lt;handle&gt;, joining Apex"* | *"Roger &lt;handle&gt;, joined to Apex."* From then on **both** of you are answered as *Apex* | [#42] `join`, `speaking_as` |
| D3 | P1 | A third aircraft well outside a mile tries to join | Refused **with the number**: *"negative, radar shows you N miles from Apex — you must be within one mile to join"* | [#42] `JOIN_NM` |
| D4 | P1 | Ask to join a flight that does not exist | *"unable, Bolt flight doesn't exist"* — an answer, not silence | [#42] |
| D5 | P1 | As a flight, request the approach | Worked as **one aeroplane**: one clearance, one sequence number | [#42] |
| D6 | P1 | Wingman: *"approach, &lt;handle&gt;, separating from Apex flight"* **while still close to the lead**, then ask for vectors | *"you are no longer in Apex flight, what are your intentions?"*, addressed by his own handle again. If the vectors then fail with "not radar identified", that is the known wingman-position gap — report it as **D6b** | [#42], [#47] |
| D7 | P2 | Lead leaves the slot or crashes while the flight exists | The flight **dissolves**, survivors are asked their intentions, nobody inherits the name | [#42] lead loss |
| D8 | P2 | Say something intra-flight — *"Apex two, tighten it up"* | The controller says **nothing**. It was not addressed to him | [#42] `is_intra_flight` |

**What it is actually checking.** D2 and D6 are the pair. Joining is the moment
the controller stops separating you individually; breaking out is the moment he
must start again. D6 is also where the known gap lives — a wingman inside the
2 nm cluster has no radar position of his own, so vectors after a break-out can
fail for a reason that has nothing to do with the flight model.

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
| H11 | P2 | With Shooter, or by asking for the approach while somebody else is on it: **get yourself held** | *"hold at five thousand, right turns, one eight zero outbound one minute, then three six zero inbound one minute"* — a shape and a clock you can actually fly with no navaid. Not "hold at BATUMI as published" | hold |
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

---

## F — landing, and the handoff to Tower

The sim now states what used to be inferred from altitude and speed: `land`,
`takeoff` and `player_leave_unit` are consumed and drive the handoff and the slot
release. A taxiing aeroplane used to read as a go-around, and a parked one was
told to climb to three thousand. **Never flown.** See [#41].

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| F1 | P1 | Fly the approach to a full stop | Handed to **Tower over the runway**, not at a range on final, and nothing tells you to climb once you are down | [#41] `land` |
| F2 | P1 | Go around from short final | **No handoff to Tower**, and no reversal back towards the field while you are climbing out. A go-around at half a mile is closer than a landing at one | [#41], [#19] |
| F3 | P2 | Touch and go | You are **not** handed to Tower for the few seconds you are on the runway — `runway_touch` is deliberately not acted on | [#41] `DOWN` |
| F4 | P2 | Land, stop, leave the slot, take a new aeroplane and check in | The old callsign is **gone from the board**. Watch `/diag` — a leftover here is the ghost that held a real pilot in the stack for a whole approach | [#41] `player_leave_unit` |

---

## K — does he remember the conversation

The controller is handed his situation fresh on every call and remembers only
what was SAID. Before this, 97% of every remembered turn was a radar picture
that had since gone stale, and the window held about six transmissions — fewer
when he was busy, because that is when he uses tools. See [#43].

The point of these rows is a CONVERSATION, not a single exchange. Everything
else on this card can be flown one call at a time; this cannot.

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| K1 | P1 | Say *"approach, <you>, I have a question"*. Let him say standby. Then let **the other pilot** take a vector and read it back. Then wait | He comes back to you unprompted: *"<you>, go ahead with your questions"*. He must not need reminding, and he must not have forgotten what it was about | [#43] the window |
| K2 | P1 | Same as K1, but make the interleaved call one that needs a tool — a **vector, a clearance or a "call you in five miles"** | Identical result. Tool calls used to cost two messages each and quietly shortened his memory exactly when it was busiest | [#43] |
| K3 | P2 | Ask him something that refers back four or five calls — *"that heading you gave me earlier, say again"* | He knows. If he asks which heading, the window is still too short and I want the number it was set to | [#43] |
| K4 | P2 | Somewhere mid-sortie, ask engineering to dump the last message sent to the model | **No radar picture in any remembered turn** — only your words and his replies. A stale scope in there is the bug, whatever else looks fine | [#43] no stale situation |
| K5 | P3 | Fly a long sortie, then ask engineering for the transcript | Postgres still has **all** of it. Trimming what he is SENT must not trim what can be replayed afterwards | [#43] |

**What it is actually checking**

**K1 and K2 are the same test with and without a tool call**, and that is
deliberate: the window counts MESSAGES, so a tool call costs the same as a whole
extra exchange. If K1 passes and K2 fails, the fix sized the window against the
wrong unit.

**K4** is the one that cannot be judged from the cockpit. Ask for it.

---

---

## L — one channel, three parties

Changed 30 July. ATC, engineering and the pilots now share the frequency and
each transmission says who it is for. The gates that used to infer whether a
call was "for the controller" are gone — ship-to-ship does not belong on this
channel, because real aircraft carry a second radio and this squadron uses
Discord.

**The rule is NEVER SILENTLY IGNORE, not always transmit.** A correct read-back
is still answered with silence, on purpose — an uncorrected read-back is the
acknowledgement. What changed is that silence is now a decision with a reason
behind it rather than a gate that ate the transmission.

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| L1 | P1 | With a flight formed, say something intra-flight on the ATC frequency — *"Apex two, tighten it up"* | He **answers**. Previously this was dropped and you heard nothing. What he says is the model's judgement; that he says *something* is the fix | [#40] |
| L2 | P1 | Same, then check how he addresses you on the **next** call | Still your handle or your flight — **never "Apex 1-2"**. A member number is not a name anybody is addressed by, and it must not become your label | [#40] |
| L3 | P1 | Say *"engineering, L3 check, how do you read"* while on the approach frequency | Engineering answers and logs it, and **you are not put in a mode** — your next call goes to ATC with no "engineering, clear" needed. Say his name again next time you want him | [#40] |
| L4 | P1 | Read back an instruction **correctly** | **Silence is correct here.** He does not acknowledge your acknowledgement. If he answers every read-back the frequency will fill up with two of you, and it gets worse with four | [#40] |
| L5 | P2 | Read back an instruction **wrongly** — say the wrong altitude | He corrects you. This is the case the silence in L4 is buying | [#40] |
| L6 | P2 | Transmit with no callsign at all, out of the blue | *"Station calling, say your callsign"* — a canned local answer that costs no model call. He is not ignoring you | [#40] |

**What it is actually checking.** L1 and L4 look contradictory and are the same
rule: never silently ignore is about not DROPPING a transmission, not about
transmitting on every one. L4 is a deliberate silence; L1 was an accidental one.

---

## M — how fast he comes back when you are alone

Changed 30 July, and it is a **latency** card — the only instrument is your own
sense of the pause between releasing the button and hearing him start.

Radar knows a T-55 from a Mustang now; it always did, and threw it away before
the picture was drawn. The counter that decides whether the deterministic
separation engine engages was counting the tanks. So on any mission with armour
in it — which is all of them — a pilot alone in the sky was being sequenced
against ground units, and every transmission he made, radio checks included,
was routed through the intent classifier at 2.2 seconds a call.

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| M1 | P1 | **Alone in the mission**, on a map with armour and ships in it, say *"Batumi, Hoover, radio check"* | He comes back **noticeably faster than you remember** — the classifier is off the path. Report the feel: "same", "quicker", "much quicker" | [#45] |
| M2 | P1 | Still alone, fly a full approach — check-in, descent, the letdown | Everything he says is **unchanged**. This card is about the pause, not the words. Any difference in phraseology or sequencing is a regression, not a pass | [#45] |
| M3 | P1 | Get a **second** aeroplane airborne (AI counts), then transmit | The engine is **back on** — you are sequenced, told to hold if the letdown is occupied. Alone-is-cheap must not mean two-is-cheap | [#45] |
| M4 | P2 | Alone again, but this time with an **AI flight parked on the ramp** at your field | Judgement call, and the reason this is P2: he is an aeroplane, so he counts, so you get the engine. Report whether that felt right or silly | [#45] |

**What would falsify it.** M3 is the one that matters. The direction of failure
here is dangerous — a counter that reads too low switches separation OFF, and
nobody hears a missing hold instruction until two aeroplanes are in the same
letdown. If M3 gives you the cheap path, stop and say so.

---

---

## N — what he calls you, and who breaks up a formation

Changed 30 July, and it is the biggest behaviour change on this card. **Nothing
you say decides what you are called any more.** Your identity is your handle —
taken from your aeroplane and your radio, neither of which can be mis-heard —
and a flight name replaces it while you are in one. A member number is neither
and can no longer exist.

The formation rules moved with it, because the engine used to invent member
callsigns off the flight name and that only worked while the flight name looked
like a callsign.

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| N1 | P1 | Check in as **any callsign you like** — "Batumi, Pony one one, checking in" | **He calls you Sockeye.** Not "Pony one one". You are your handle; what you said is a claim, and it never names you. He must also not challenge you, ask you to say it again, or tell you he has no flight plan under it | [#48] |
| N2 | P1 | Say a **different** callsign on your next call, and a third one after that | **Nothing happens at all.** Not "handled gracefully" — there is nothing to handle. You cannot rename yourself, because your name was never made of what you say. Still Sockeye, same track, no re-identification, no lost clearance | [#48] |
| N2a | P1 | Check in as **"Falcon one one"** — a name belonging to nobody | *"Falcon one one, I do not have you on the board. You are Sockeye — use that callsign."* Said **first**, then he answers your call normally. You are corrected, not refused | [#48] |
| N2b | P1 | Say it **again** on your next two calls | He corrects you **once**. Repeating it every transmission would fill the frequency with the correction instead of the approach | [#48] |
| N2c | P2 | Now use **"Sockeye"** | Silence on the subject. Nothing to correct | [#48] |
| N3 | P1 | Form a flight, then have a **wingman** transmit | He is answered as the FLIGHT. Never "Apex one two" — a member number is not a name anybody is addressed by | [#48] |
| N4 | P1 | As a flight, fly the **whole approach in formation** — check in, hold, letdown, land, never asking to split | He works you as ONE aeroplane the whole way. He must **never** break you up, never offer to, never say he is unable to work a formation, and never ask whether you can maintain visual separation between your own aircraft | [#48] |
| N5 | P1 | While the flight is together, have a **wingman** ask for a range | The range describes **lead's** aeroplane, not the wingman's. Check it against lead's DME/position — if the number moves depending on who asks, the geometry is following the wrong ship | [#48] |
| N6 | P1 | Now **ask to break up** | He breaks you up, and names **nobody**. He should ask each of you to check in with your own callsign. If you hear him read out a list — "one one, one two, one three, one four" — those are invented and it is a regression | [#48] |
| N7 | P1 | Each of you then checks in individually | *"radar contact, say intentions"* — and nothing is assigned until you ask for something. Then normal sequencing, one in the letdown | [#48] |
| N8 | P2 | Break up **half way down the approach**, with lead already cleared | Somebody gets cleared. The bug here was silent: the dissolved flight kept the letdown, so all four sat holding and the controller appeared to forget about you | [#48] |
| N9 | P2 | Fly with **armour and ships on the map**, alone | Covered by M1, and it belongs here too: a tank is not traffic and must not put you in a sequence | [#45] |

**The one to watch.** N4 and N6 are the same rule from opposite sides: the
formation is yours, and the only thing that splits it is you saying so. Any
transmission where he initiates it — however reasonable his reason sounds — is
the bug.

**N1 is expected to FAIL, and it is written as a failure on purpose.** The
agent is told to address you by your handle and, in the dry runs, still mostly
echoes the callsign you spoke. That is a defect against [#48], not a preference
to be surveyed — an earlier draft of this row offered "your handle, or the
callsign you gave" as two acceptable answers, which is a criterion bent to fit
behaviour that was already known to be wrong. There is one right answer. Report
what you actually hear.

**What N1 and N2 are really checking** is that a callsign is a POSITION and not
a person. A man flies several in a night; the aeroplane he is sitting in and the
radio he keyed do not change with them. Everything the controller does with you
— the board key, the holding stack, the strip he matches — hangs off the second
pair, and none of it should so much as twitch when the first one changes.

**Neither row can be flown by a second aircraft standing in for you.** They are
about one man's identity surviving his own words.

**N2a is the one to think about while you fly it.** The controller knows exactly
who you are — the radio told him before you spoke — and corrects you anyway,
because a callsign nobody answers to is how a clearance gets read back by the
wrong man once four aeroplanes are listening. Judge whether the correction
sounds like a controller doing his job or like a machine being pedantic, and
whether hearing it once is enough.

**A knock-on you may notice at a NO-RADAR field.** A filed plan's callsign no
longer admits anybody — it was typed when the mission was built and matches a
live pilot only by coincidence. So with radar off you are *audible and not on
the board* until a clearance assigns you a plan, and N2a is what you will hear.
With radar up you are admitted the moment you are painted and none of this
applies.

---

## P — tracked, untracked, and who owns you

Three minutes, on the ramp, before you start anything. **Open `/diag` on a
second screen** — this whole section is read off it, and the point of the
section is that the page now shows you what the system believes rather than a
tidied-up version of it.

The claim being tested is that the sim already knows everything about you the
moment you take a slot: your name, your aeroplane, where you are, and what you
will be called. None of it needs a radio. See [#49].

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| P1 | P1 | **Slot into a cold jet and say nothing.** Look at the Untracked table | You are there, with **both names**: `362nd_Sockeye` on the left, `Sockeye` on the right. Not "Viper 1-4", not blank. If the right cell is empty the derivation is broken and that is exactly what the column is for | [#49] `_derived_callsign` |
| P2 | P1 | Still silent — read the `state` for yourself | **parked**. Not "airborne", not blank. The flag the sim sends says airborne for a jet that spawned on the ramp, so this is the one that catches a lazy read | [#49] `sim_state` |
| P3 | P1 | Check in with Approach. Watch yourself move between the two tables | You leave Untracked and appear on **Tracked**, with `owner` = the controller you called. You may not be in both, and you may not be in neither | [#49] |
| P4 | P1 | On Tracked, read your row **before** he asks your intentions | `intent` reads *not established*. Once you tell him what you want, it fills in. A blank here means nobody has asked — which is a controller not doing his first job | [#49] |
| P5 | P1 | **Fly a full approach and keep half an eye on Tracked.** Do not let this one pass unnoticed | Your row **never disappears**. It came off nine times in one sortie on 30 July, at 0.4 nm, with you on the scope. If a "came off the board" panel ever appears under Tracked, stop and tell engineering what it says | [#49] `release_stale` |
| P6 | P1 | Get handed to Tower | `owner` changes to `tower` **and nothing else about your row does** — same level, same place in the letdown. You must not blink through Untracked on the way | [#49] `Controller.bind` |
| P7 | P2 | Taxi out, then take off, watching `state` | **parked → taxiing → rolling → airborne**. Rough transitions are fine; the ones that matter are that parked is not "airborne" and that airborne eventually arrives | [#49] `sim_state` |
| P8 | P2 | Anywhere in the sortie, check the banner at the top | It says *board and radar agree* only when they do. It read that unconditionally before, because the page asked for a field nothing published | [#49] ghosts |

**What it is actually checking**

**P1 and P5 are the section.** P1 says the system knows you for free; P5 says it
does not then lose you. Everything else is detail around those two.

**A blank cell is information here, not a rendering fault.** The page was
changed to stop falling back to a plausible-looking value when it cannot find
the real one — so an empty `callsign`, `owner` or `state` means the bridge does
not have it, and that is worth reporting rather than squinting past.

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

---

## Already flown, and kept as the regression record

A row is not an issue. These passed in the air; their scripts stay in
`tools/` and run from `tools/check.py`, which is what tells us if a fix
rots. Flown by Hoover 28 July, attested at `8a01149`.

**Section A**

| ~~A8~~ | P1 | **In an F-16**, fly the approach from 20 nm and compare every "left/right of course" call against your HSI | The side he calls matches the needle, all the way in. This is the one that settles whether the P-51's instruments were the story | [#35] frames |
| ~~A9~~ | P1 | Go around, and write down the altitude in the go-around instruction AND the one on the next check-in | The **same number** both times, and it is the plate's missed approach altitude | [#36] |
| ~~A7~~ | P1 | On the ramp, draw on a chart page with a pen or the mouse, turn the page and come back, then go to the **E6B** page and press a button | Ink appears; the E6B still **works**, because that page is a calculator and keeps its clicks | [#34] `SetCursorEventsMode` |

**Section E**

| ~~E3~~ | — | **CLOSED 27 July** — flown clean twice, nothing invented on either go-around. Guarded by `tools/atc_dryrun.py` | — | — |

**Section G**

| ~~G1~~ | P1 | *"Batumi Ground, Hoover one one, request IFR clearance, Marlin"* | The **whole** CRAFT clearance: cleared to Batumi, as filed, three thousand, departure frequency one two four decimal zero, and a squawk | [#1] `request_clearance` |
| ~~G2~~ | P1 | Write G1 down as he says it, then read it back **correctly** | You got all five elements without asking for a repeat, and he says *"readback correct"* and stops talking | [#1] copyable |

**Section H**

| ~~H1~~ | P1 | Inbound from 20 nm, on the centreline. Compare each "left/right of course" call against where the runway actually is | The side he calls is the side you are on, **every call, all the way in**. This is the one that was wrong all night | [#35] frames |
| ~~H2~~ | P1 | Fly the descent profile as given and note your altitude crossing the **threshold** | You arrive at the threshold at minimums, not 200 ft high with half a mile of descent owed | [#19] touchdown |
| ~~H3~~ | P1 | Listen to the range calls near the end | "One mile from the runway" means one mile from the **threshold**. Previously it meant one mile from the runway centre, which is where you were already landing | touchdown |
| ~~H12~~ | P1 | Arrive **180 out of phase** — on the centreline heading away from the field — and ask for the approach | Downwind, base, then a 30-45 degree turn onto final. Recognisable legs and no reversal. Previously he was aimed at the fix and turned hard 180 | [#39] |


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
