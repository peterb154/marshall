# Flight test card

    Type: WORK RECORD
    Validated against: 10 August 2026

> The card a pilot flies.


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
| 1 | **Q — the ladder, Kobuleti to Batumi** | [#1] [#16] | solo | **fly this first.** The theatre has two aerodromes as of 31 July and none of it has been heard. It is also where you are sitting: the sortie now starts at Kobuleti, so section Q is simply the first ten minutes of the flight |
| 2 | **N — what he calls you** | [#48] | solo | everything about identity changed on 30 July and none of it has been heard. The quickest to falsify: three transmissions on the ramp |
| 3 | **M — how fast he answers alone** | [#45] | solo | one radio check. Ground units stopped counting as traffic, so the classifier is off the path — you are judging a pause, and you can only judge it while you still remember the old one |
| 4 | **J — who he thinks you are** | [#40] | solo | identity under stress: garble it, omit it, lose radar. N says he gets it right; J says he keeps it when things go wrong |
| 5 | **G — clearance at the ramp** | [#1] | solo | the awkward half: a wrong read-back, a deliberate ambiguity, an amendment |
| 6 | **H — the approach** | [R#19] [#37] [#39] | solo | the main event, and where the open bugs live |
| 7 | **F — landing and the handoff** | [#41] | solo | the sim's own events now drive Tower. Never flown |
| 8 | **K — does he remember** | [#43] | solo, better with two | shipped 30 July, never flown |
| 9 | **R — ATIS and the letter** | [#17] | solo | built 2 August, never heard. Three transmissions on the ramp |
| 10 | **S — does it sound right** | [#17] | solo | **ears only.** Nothing else on this card can falsify it and I cannot test it at all |
| 11 | **T — the Kobuleti ILS** | [#3] | solo | a whole second approach added as data. Fly it last; it needs no new procedure from you |
| — | **D — flights** | [#42] | **two aircraft** | skip it solo. A formation cannot be flown by one aeroplane, and the break-up rules changed on 30 July |
| — | **E — known broken** | | | read it, so you do not re-find something already understood |

**Solo today?** Q, N, M, J, G, H, F, K, R, S, T — in that order. Only D needs a
second aeroplane. Note that N3, N5 and N6 inside section N are formation rows and want
one too; the rest of N is flyable alone and is the part that changed most.

## How to report

Say `engineering, come up`, then `test H4 failed, he vectored me at four miles`.
The ID is the whole point; detail is optional. Engineering answers on whatever
channel you called from and logs to `build/debug-notes.md`.

### Who you are on the radio

**Your callsign is the name radar prints — `Sockeye`.** Not `Viper 1-1`, which
is the mission's name for the SLOT you took. The system is right to correct you,
and this card was wrong to tell you otherwise: Q1 and H18 both scripted the slot
name, so a pilot reading the card was instructed to misname himself and then
told off for it.

`/diag`'s Untracked table shows both side by side — `362nd_Sockeye` as the sim
publishes it, `Sockeye` as it is derived — which is the point of P1.

### The issue column says one of two different things

A row's `[#n]` used to mean whatever the writer had in mind, and the two
meanings pull opposite ways when the issue closes:

| notation | means | when #n closes |
|---|---|---|
| `[#n]` | **this row is chasing finding #n** — it exists because something is wrong | the row has served its purpose; **retire it** (strike the ID through) |
| `[R#n]` | **this row exercises the fix in #n** — it is the regression check | **nothing happens.** The row is why we would find out if that fix rotted |

Seventeen rows sat in the first form while meaning the second, so the check
told us to delete the only rows that test handoffs between two aerodromes —
because the single-aerodrome fixes they exercise had been closed on earlier
sorties. *A row is not spent because its subject is fixed; it is spent when a
pilot has flown it.* See #60.

**Striking a row through retires it from the cockpit list and keeps its
script** — that is the record of what was flown, and it is the only thing that
retires a row.

**Seventy more moved to `[R#n]` on 13 August, and not one row was struck.** The
backlog was closed unverified that evening — "flight-test bankruptcy" — and the
closing note on every one of those issues says what survives: *"the cockpit card
row, which is the re-fly script."* A row whose subject was closed without a
pilot is the definition of the second form: nothing about it was flown, so it is
not spent, and it is now the regression that tells us whether the fix rotted
while it waited. The notation changed; the script, the ID and the priority did
not.

**Comms — the ladder, in the order you press it.** The sortie departs
**Kobuleti** and recovers into **Batumi**: eight rungs and two aerodromes,
rather than the four buttons at one field this started as.

| ch | freq | station | when |
|---|---|---|---|
| 1 | 125.100 | Kobuleti Clearance | start-up, IFR clearance |
| 2 | 121.800 | Kobuleti Ground | taxi to the runway — **not** take-off |
| 3 | 133.000 (also 122.100) | Kobuleti Tower | holding short, take-off |
| 4 | 123.300 | Kobuleti Departure | after take-off, to about 5 nm |
| 5 | 139.000 | Georgia Center | en route |
| 6 | 124.425 (also 124.000) | Batumi Approach | recovery and the whole ASR |
| 7 | 118.600 (also 118.000) | Batumi Tower | the landing |
| 8 | 121.900 | Batumi Ground | taxi in |
| 9 | 131.000 | Sentry | mission commander, not a rung |

**ATIS** — listen, never transmit. **On the UHF box now**, buttons 1 and 2, so
you can hear the weather without leaving the controller you are working. The
same broadcast goes out on both bands in one transmission.

| field | UHF preset | VHF | |
|---|---|---|---|
| Kobuleti | **1** — 279.000 | 127.400 | departure |
| Batumi | **2** — 280.000 | 127.100 | arrival |

The VHF ladder on box 2 is unchanged: presets 1–9, Clearance through Sentry.

Two frequencies on one row is **one controller on both** — a warbird that cannot
dial fractions reaches the same man on the round number. Say either.

The approach is all on **124**, and on the ASR you are kept there **to the
ground** — the controller is your approach aid, so he does not hand you away
mid-procedure. Landing is what gives you to Tower.

**Every rung can now be left, and reached.** Both former dead ends closed:
reading your clearance back hands you to Ground, and landing hands you to Batumi
Ground for taxi in. If either goes quiet on you, that is a regression and worth
reporting.

**Priority:** **P1** never flown, this sortie is the first real test ·
**P2** seen working once, confirming it stuck · **P3** nice to have.

## Things that are not bugs

- **~2.2 s of extra delay on every transmission**, including a radio check, when
  the mission holds armour or distant AI. `count_contacts` cannot tell a T-55
  from a Viper. [#45]
- **The board engages while you are alone**, same cause. `/diag` will show it.
- **Kobuleti Ground REFUSES a request to take off** — "take-off is Tower's,
  contact Kobuleti Tower one three three decimal zero". That is correct and
  deliberate: the runway belongs to one controller. Ground clears you *to* the
  runway and says hold short, every time.
- **The nav log heading changed by ~2°** from the last card. The wind is 090/5
  now rather than 180/5 — picked so runway 13 at Batumi and 07 at Kobuleti are
  both into it. Courses did not move; the drift correction did.

*(The paper nav log being 5.74° out on every leg was the first finding of the
29 July audit and is **fixed** — `core/geo.py` names the frame in every function
and the convergence is measured per field, +5.85 at Batumi and +5.91 at
Kobuleti. It is off this list because it is closed, not because it stopped
mattering.)*

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
| J1 | P1 | Fly with your **usual** SRS name and check in normally. Read the `authority` column | **`radar`** — the chain with no microphone in it: SRS name → the name radar prints → your track. If it reads `plan` or `roster` on every call, the roster fix did not take and I want to know before Andre, not after | [R#40] `unit_for_radio` |
| J2 | P1 | **Andre checks in cold** — a radio this controller has never heard, nothing filed for him, no setup of any kind | He is identified and vectored on his first call. Ask engineering what `authority` said. `radar` means his SRS name matched his DCS name, which is the expected and best case; `plan` or elimination means the chain did not close and I want the reason | [R#40] |
| J3 | P1 | Garble or omit your callsign on one call — mumble it, or say only *"request the approach"* | He answers, and your identity does **not** move. The aeroplane you are in decides who you are; the words are only a claim | [R#40] |
| J4 | P1 | With a second aircraft up, say **his** callsign by mistake on one of your calls | Your report must not be filed against his aeroplane. That is a separation error, and it is the one nothing in the system used to report | [R#40] |
| J5 | P2 | Read back an instruction sloppily — *"maintained two thousand"*, *"left three sixty"* | **No new aeroplane appears.** Ask engineering for the board if unsure. These exact phrases each invented an aircraft that took a holding level | [R#40] guards |
| J6 | P2 | Get radar to lose you — sit on the ramp, or go well out — then call in | *"Not radar identified, say your position and altitude"*, and **nobody is held behind you**. Being unseen must cost you a place in the queue, not give you one | [R#40] `may_be_sequenced` |

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
| G3 | P1 | Ask again for Marlin, and read it back with **one number wrong** | He corrects **that number only** and asks for it again — not the whole clearance, and never a shrug | [R#1] `clearance_read_back` |
| G4 | P1 | Ask by what you are DOING, no name — *"request clearance for the weather run out to Ingress"* | Lantern's clearance, five thousand. You should never have had to say a plan name | [R#1] `plans.pick` |
| G5 | P1 | *"request clearance for the CAS over Tsutsnvati"* | A **question** naming both — the plain one, and the one with the beacon letdown on return. He must not pick for you | [R#1] `plans.pick` |
| G6 | P1 | Answer it — *"the beacon letdown one"* | Kettle: eleven thousand, and the route out through Ingress to Tsutsnvati | [R#1] `plans.pick` |
| G7 | P2 | *"request clearance to Vaziani"* | *"nothing on file"* and a question. **Not** the nearest plan read out as though you had asked for it | [R#1] `plans.pick` |
| G8 | P2 | After a clearance, change your mind — *"request a change, make it Anvil"* | A **complete** new clearance (four thousand), read back again. He must not say only what changed | [R#1] `assign` amends |
| G9 | P2 | With Shooter: both of you ask for **Marlin**, one after the other | Both get it, both are cleared to three thousand, and neither clearance changes the other's | [R#1] one plan, two flights |
| G10 | P3 | Airborne later — *"what am I doing"* or *"where am I going next"* | He answers from your plan without you repeating it, and does not read you ranges you do not need | [R#1] `flight_plan_help` |

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
| D1 | P1 | Lead: *"approach, &lt;handle&gt;, request creation of Apex flight"* | *"&lt;handle&gt;, you are now the lead of Apex flight. Each member of Apex check in to be joined"* — and he uses your HANDLE, not a slot name | [R#42] `parse_create` |
| D2 | P1 | Wingman, formed up inside a mile: *"approach, &lt;handle&gt;, joining Apex"* | *"Roger &lt;handle&gt;, joined to Apex."* From then on **both** of you are answered as *Apex* | [R#42] `join`, `speaking_as` |
| D3 | P1 | A third aircraft well outside a mile tries to join | Refused **with the number**: *"negative, radar shows you N miles from Apex — you must be within one mile to join"* | [R#42] `JOIN_NM` |
| D4 | P1 | Ask to join a flight that does not exist | *"unable, Bolt flight doesn't exist"* — an answer, not silence | [R#42] |
| D5 | P1 | As a flight, request the approach | Worked as **one aeroplane**: one clearance, one sequence number | [R#42] |
| D6 | P1 | Wingman: *"approach, &lt;handle&gt;, separating from Apex flight"* **while still close to the lead**, then ask for vectors | *"you are no longer in Apex flight, what are your intentions?"*, addressed by his own handle again. If the vectors then fail with "not radar identified", that is the known wingman-position gap — report it as **D6b** | [R#42], [#47] |
| D7 | P2 | Lead leaves the slot or crashes while the flight exists | The flight **dissolves**, survivors are asked their intentions, nobody inherits the name | [R#42] lead loss |
| D8 | P2 | Say something intra-flight — *"Apex two, tighten it up"* | The controller says **nothing**. It was not addressed to him | [R#42] `is_intra_flight` |

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
| H18 | P1 | **Cleared for the approach, ask for it again.** Once you have the approach clearance, request it a second time — "Sockeye, request the approach" | *"You are cleared"*, in some form. **Never "number two"** — behind whom? There is nobody else up. On Fred's 31 July sortie this told the only aeroplane in the sky he was second behind himself, four transmissions running at 44 nm, and he declared an emergency to break the loop. From the cockpit it is indistinguishable from being forgotten | [R#50] |
| H19 | P1 | Then **change frequency and check in again** while still cleared | Still cleared. The root cause of H18 was a check-in resetting a CLEARED aircraft to en-route on *every* frequency change — so the ladder, which changes frequency seven times, was the thing most likely to trigger it | [R#50] |
| H11 | P2 | With Shooter, or by asking for the approach while somebody else is on it: **get yourself held** | *"hold at five thousand, right turns, one eight zero outbound one minute, then three six zero inbound one minute"* — a shape and a clock you can actually fly with no navaid. Not "hold at BATUMI as published" | hold |
| H13 | P2 | Fly the approach **fast** — 400 kt or more — and watch the turn from base onto final | He may overshoot: **known open**, criterion 2. The sweep at 450 kt says 181 dithering events and a 5.1 nm turn radius against a 3 nm base leg — so expect **left/right reversals**, not a clean overshoot. Report how far through you go | [R#39] |
| H10 | P1 | Arrive high — **5,000 ft or above, 30 nm out** — and ask for the approach. Note where he starts you down | He keeps you high, then sends you down **once**, timed so you reach 2,000 arriving at the initial fix. Not levelled at 2,000 ten miles early | [#37] descent |
| H9 | P1 | Once established, listen to the **altitude** part of each mile call | *"four miles, on course, **descend to** one thousand three hundred"* — an instruction for the NEXT mile, arriving in time to fly it. Not "altitude should be", which tells you where you already ought to be | anticipatory |
| H4 | P1 | Once established, listen to how he corrects you | **"Turn left ten degrees"** — no heading at all, rounded to five. If he gives you an absolute heading inside the final approach course, that is the failure | [#37] |
| H5 | P1 | While being vectored (before established), note the headings | Absolute, and ending in **0 or 5** — "heading three one five", never "three one three" | [#37] |
| H6 | P1 | **Deliberately mis-set your DG by 20 degrees** before you turn inbound, then fly the approach on his corrections alone | You still arrive. This is the whole argument for relative corrections and it could not have been passed yesterday | [#37] |
| H7 | P2 | Inbound, **2–3 nm off course, between 11 and 16 nm** — get yourself there on purpose | He gives you an intercept heading. If he sends you OUTBOUND to reposition, that is E1 and it is still open | [R#19] |
| H8 | P2 | Arrive from **behind the field**, 8–12 nm on the departure side, and ask for the approach | He takes you out and brings you round. Circling near the field is E2 | [R#20] |
| H14 | P1 | **The ladder, step 1.** F-16, whole approach at **300 kt or less** | Clean. The sweep flies this exact grid at 300 kt: 1296/1296 arrive, **zero** dithering. Anything else here is new and matters more than H16 | [R#39] |
| H15 | P1 | **The ladder, step 2.** Same approach in the **P-51** | Clean, and for a different reason than H14 — this is the speed the engine was built at, so a failure here is a regression, not a limit | [R#39] |
| H16 | P1 | **The ladder, step 3.** F-16, **450 kt or more** inbound | **Predicted to fail**, and how: reversals. At 450 kt a 30° bank gives a 5.1 nm turn radius and the base leg is built around 3, so the engine orders a turn he cannot make and then orders the opposite. If it fails any OTHER way, that is new information and worth more than the expected one | [R#39] |
| H17 | P1 | Note **every speed instruction** you are given, and the number | You are asked to slow down at all — this has never been heard on the radio. In the F-16 **never below 210 kt**; the published profile wanted 174, which is the P-51's number | [R#39] |
| H22 | P1 | Once established on final, listen for what happens to the speed restriction | *"Resume normal speed"*, **once**, and no further speed assignments. On final the pilot owns his own speed — the controller does not know your fuel or stores | [R#39] |
| **H20** | Get established on the final approach course, then say nothing for two calls | You are **never told to hold** once radar shows you established. A holding clearance there is stale by definition — you cannot both be on final and be waiting to start. A pilot at ten miles was once told, in one transmission, that he was on final AND to climb to five thousand and hold | [#80] | **P1** |
| **H21** | The same, listening for a **second altitude** anywhere in the transmission | One altitude per transmission. The talk-down and a holding level together is the regression | [#80] | **P1** |
| **H23** | **Take off and climb out normally.** Listen all the way to the hand-off to Center | **No approach vectors on the departure.** He must not turn you, must not descend you, and must not tell you you have gone around. On 10 August a departure off Kobuleti was flown on Batumi's approach geometry — six headings and a descent to two thousand while climbing out to five, thirty miles from either field | [R#86] | **P1** |
| **H24** | **Inbound, once Batumi Approach has you.** Watch that the vectors settle | No **reversal** — a heading that swings back the other way by a hundred degrees or more between calls. On 10 August the phase never left `departure`, so the pilot-path guidance was switched off while the proactive monitor went on vectoring, and the two disagreed. If it happens, say so on the radio: the log now prints `phase REFUSED` and the inputs that caused it, and that line is the diagnosis | [#91] [R#92] | **P1** |
| **H25** | **Immediately after take-off**, listen for two calls | You are **not** told you are established, cleared, or on final. On 11 August the approach geometry was asked about an aeroplane at 0.6 nm and 472 feet climbing off Kobuleti, said yes, and the engine cleared him for an approach he had not started — which wedged the phase for the rest of the flight | [R#93] | **P1** |
| **H26** | **Being vectored, note every altitude you are given against the chart MVA** | It is never below it. On 11 August the geometry said *"maintain 8000"* at nineteen miles on the 056 radial — where the surveyed MVA is 8,000 — and what reached the air was *"level five thousand five hundred"*. The terrain was surveyed cell by cell so this could not happen; the number was dropped between deciding it and saying it | [#95] | **P1** |
| **H27** | **En route, level at your cleared altitude**, report it | He agrees with it. On 11 August a pilot level at five thousand — the altitude on his own clearance — was told *"assigned altitude is five thousand five hundred, not five thousand"* and made to climb. Two ideas of one number, and the strip is the one that counts | [R#98] | **P1** |
| **H28** | **With company: two other aircraft holding.** Note every altitude the controller gives out | **No two aeroplanes at one level.** On 11 August, the first time three arrivals were ever sequenced at once, the aircraft cleared for the approach kept the bottom of the stack and the next arrival was assigned the same altitude — both over the beacon, both at five thousand. This is the accident the deterministic engine exists to prevent and it is the DEFAULT outcome of three aeroplanes arriving together. Reproducible in three lines with no radio; see #108, which is a design call and may be answered by fixing the board instead | [R#108] | **P1** |

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

**F6 is struck, flown by a ghost on 13 August at `49953cd`** — Ground said
*"taxi to parking, your discretion"* and nothing was handed anywhere after him.
The rest of this section still needs a pilot. **F5 and F5b changed on 13 August
and are now ordinary rows**: the handoff to Ground is issued during the
ROLL-OUT rather than after anybody watches you vacate — *"welcome, exit the
runway and contact Batumi Ground one two one decimal niner"* — so you do not
have to be clear, and you do not have to ask. The note that used to stand here,
warning that the card and the design disagreed because `taxi_in` was entered by
the pilot's request, is settled: the trigger moved from your mouth to the sim
and the request still works if you get there first.

**F5, F5b and F3b were flown by a ghost on 13 August at `806a728`**
(`tools/ghost_flight.py --sortie` and `--touch-and-go`, session `hooks`,
`MARSHALL_APPROACH=batumi-ils`). What the harness could answer, it answered: the
roll-out transmission fired off the radar poll with no pilot in it, named
**Batumi Ground one two one decimal nine** — the arrival field's — and was
booked as `atc/handoff to: ground` in the same instant, so the words and the
record agree. A ghost then got airborne off the roll-out and was **not** given
to Ground, and one that had already checked in with Ground was **retrieved by
Batumi Tower**. The rows stay on the card because what is left on them is a
pilot's.

**Listen for the timing rather than the words**, because that is the half no
rehearsal can score. It arrives while you are still rolling, which is what a
real tower does — and if it lands on top of you at a moment that makes no sense,
that is the finding.

**And listen for how MANY times he says it.** A ghost that landed and then
reported down and then asked Tower for taxi was told *"contact Batumi Ground one
two one decimal nine"* **three times in forty seconds** — once unprompted on the
roll-out, once when he reported down, once when he asked for parking. Every one
of them is correct on its own (he had not changed frequency, so telling him
again is what a tower does) and a machine cannot say whether the third was
tiresome. You can.

| ID | Prio | Test | What should happen | Fix under test |
|----|------|------|--------------------|----------------|
| F1 | P1 | Fly the approach to a full stop | Handed to **Tower over the runway**, not at a range on final, and nothing tells you to climb once you are down | [R#41] `land` |
| F2 | P1 | Go around from short final | **No handoff to Tower**, and no reversal back towards the field while you are climbing out. A go-around at half a mile is closer than a landing at one | [R#41], [#19] |
| F3 | P2 | Touch and go | You are **not** handed to Tower for the few seconds you are on the runway — `runway_touch` is deliberately not acted on | [R#41] `DOWN` |
| **F3b** | **P1** | **Touch and go, and then say nothing** — or get airborne again at any point after Tower has said goodbye | **Nobody hands a flying aeroplane to Ground.** The roll-out goodbye moves you to `taxi_in` while you are still rolling, so an aeroplane that then flies is a ground controller's aeroplane in the air; before 13 August nothing could retrieve it and you sat on 121.900, airborne. If you have already checked in with Ground, **Batumi Tower takes you back** — *"contact Batumi Tower one one eight decimal six"*. A ghost flew both halves on 13 August and both fired. **What is yours:** on the touch-and-go the goodbye is followed about fourteen seconds later by *"contact Batumi Approach one two four decimal four two five"*, with nothing from you in between. It is defensible — you are airborne, leaving, and Batumi has no Departure seat — but it is two frequency changes in a quarter of a minute at a hundred feet, and whether that is a controller working or a controller thrashing is an ear's question | [R#164], [R#77] |
| F4b | **P1** | **Say something Whisper will mangle** — a hurried call, a name half-swallowed, someone else's callsign — then check `/diag` | **No aeroplane appeared that does not exist.** One P-47 once entered the stack as "Hammer 1-1", "Hammer 1-3", "All 4" and "Maintained 2" — four aircraft, three imaginary, each with a place in the queue. With one ship that is untidy; with two a ghost at the head holds real pilots for an aeroplane that will never arrive. The identity work since means a radio is bound by RADAR and a mangled name should reach nothing, but the closure condition here has always been a live sortie and nobody has flown one | [R#13] | ghosts |
| F4 | P2 | Land, stop, leave the slot, take a new aeroplane and check in | The old callsign is **gone from the board**. Watch `/diag` — a leftover here is the ghost that held a real pilot in the stack for a whole approach | [R#41] `player_leave_unit` |
| F5 | **P1** | **Land, and say nothing at all for the rest of the sortie** | On the roll-out Tower says *"welcome, exit the runway and contact Batumi Ground one two one decimal niner"*, and you reach a stand without ever keying the mic. This was the last dead end in the ladder. Tower should **not** clear you to taxi to parking — that is Ground's; he names the man who owns it | [R#88], [R#77] |
| **F5b** | **P1** | Check WHICH Ground, and when | It is the ARRIVAL field's — Batumi **121.900**, never Kobuleti's **121.800** (this row said 118.600 until 13 August, which is Batumi *Tower* — the wrong number for the right controller, on the row about naming the right one). And it arrives **during the roll-out**, not after you are clear: there is no runway polygon in the aerodrome table, so "he has vacated" is not a fact this system can observe, and issuing it early is what a real tower does anyway | [R#77] |
| ~~F8~~ | **Mid-sortie, ask me to restart the bridge**, then carry on talking | **He knows you.** Same rung, same level, same approach, and if you were cleared he still has you on it — not a controller meeting you for the first time. The board was built only by transmissions until 11 August, so a restart forgot every rung climbed and every level assigned while the aeroplanes went on flying, and with an empty letdown would clear somebody else onto your approach | [#120] | **P1** |
| ~~F7~~ | **Fly two sorties back to back without anybody touching the database.** On the second, ask Clearance for a clearance and then check `/diag` | **The board holds you, once.** One row, your callsign on it, and the intent you stated — *"VFR to Batumi, visual 13"* — carried to every controller after the one you said it to. On 11 August a single sortie made THREE rows in thirty seconds, none bound to the pilot, because a transmission carrying only an SRS name matched nothing and inserted; and nothing had ever written `intent` at all, so each controller met him for the first time. Leave the slot and your row should go with you | [#119] | **P1** |
| ~~F6~~ | After Ground has you and you are taxiing in, wait | **He parks you** — *"taxi to parking, your discretion"* — and hands you nowhere. | **He does not hand you anywhere.** Ground is the end of the ladder; there is nothing after him. On 11 August he sent the pilot back to Batumi Tower — a rung that hands BACKWARDS, onto a controller who has already finished with him. He should also give a **parking instruction**, which is his, not decline to own one | [#100] | **P1** |

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
| K1 | P1 | Say *"approach, <you>, I have a question"*. Let him say standby. Then let **the other pilot** take a vector and read it back. Then wait | He comes back to you unprompted: *"<you>, go ahead with your questions"*. He must not need reminding, and he must not have forgotten what it was about | [R#43] the window |
| K2 | P1 | Same as K1, but make the interleaved call one that needs a tool — a **vector, a clearance or a "call you in five miles"** | Identical result. Tool calls used to cost two messages each and quietly shortened his memory exactly when it was busiest | [R#43] |
| K3 | P2 | Ask him something that refers back four or five calls — *"that heading you gave me earlier, say again"* | He knows. If he asks which heading, the window is still too short and I want the number it was set to | [R#43] |
| K4 | P2 | Somewhere mid-sortie, ask engineering to dump the last message sent to the model | **No radar picture in any remembered turn** — only your words and his replies. A stale scope in there is the bug, whatever else looks fine | [R#43] no stale situation |
| K5 | P3 | Fly a long sortie, then ask engineering for the transcript | Postgres still has **all** of it. Trimming what he is SENT must not trim what can be replayed afterwards | [R#43] |

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
| L1 | P1 | With a flight formed, say something intra-flight on the ATC frequency — *"Apex two, tighten it up"* | He **answers**. Previously this was dropped and you heard nothing. What he says is the model's judgement; that he says *something* is the fix | [R#40] |
| L2 | P1 | Same, then check how he addresses you on the **next** call | Still your handle or your flight — **never "Apex 1-2"**. A member number is not a name anybody is addressed by, and it must not become your label | [R#40] |
| L3 | P1 | Say *"engineering, L3 check, how do you read"* while on the approach frequency | Engineering answers and logs it, and **you are not put in a mode** — your next call goes to ATC with no "engineering, clear" needed. Say his name again next time you want him | [R#40] |
| L4 | P1 | Read back an instruction **correctly** | **Silence is correct here.** He does not acknowledge your acknowledgement. If he answers every read-back the frequency will fill up with two of you, and it gets worse with four | [R#40] |
| L5 | P2 | Read back an instruction **wrongly** — say the wrong altitude | He corrects you. This is the case the silence in L4 is buying | [R#40] |
| L6 | P2 | Transmit with no callsign at all, out of the blue | *"Station calling, say your callsign"* — a canned local answer that costs no model call. He is not ignoring you | [R#40] |

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
| P9 | **P1** | **The moment you notice nothing is happening** — holding, or waiting for a handoff that has not come — read your own card, bottom line | **NOT DONE names who is keeping you and why**: *"Batumi Approach keeps him — approach, 20 nm, inbound"*. That sentence has been written down since 1 August and appeared nowhere. If the line is blank while nothing is happening, the monitor is not reaching the decision at all, which is a different fault and worth saying on the radio | [R#155] `watching_him` |
| P10 | P1 | Read the two clocks in the header, at any moment | **bridge** is the age of everything on the board; **recorder** is the age of the last thing said on the radio. On a quiet frequency the second goes minutes old while the first stays at 1s — that is correct and is not a warning about the bridge. One number used to stand for both, and accused a running bridge of being dead | [R#155] |
| P11 | P1 | **On the knee, at kneeboard width, mid-sortie.** Not on a monitor | Nothing scrolls sideways, and everything about you — what he thinks you asked for, what you are cleared for, where the engine has you, which rung of the ladder, and why nothing is happening — is on one card without hunting. The board used to be thirteen columns in a horizontal scroller and `intent` was off the right-hand edge | [R#155] |

**What it is actually checking**

**P1 and P5 are the section.** P1 says the system knows you for free; P5 says it
does not then lose you. Everything else is detail around those two.

**A blank cell is information here, not a rendering fault.** The page was
changed to stop falling back to a plausible-looking value when it cannot find
the real one — so an empty `callsign`, `owner` or `state` means the bridge does
not have it, and that is worth reporting rather than squinting past.

---

## Q — the ladder, Kobuleti to Batumi

**Flown 10 August, solo in an F-16 (Sockeye).** Q2, Q4, Q5, Q7, Q8, Q9, Q9b,
Q10 and Q11 passed and are struck — their scripts stay as the regression record.
Attested at `be7fefb`.

**And flown end to end by a synthetic pilot, 13 August, at `49953cd`.**
`uv run --extra voice python tools/ghost_flight.py --sortie` puts a ghost on the
stand at Kobuleti, speaks every rung over real SRS through real Whisper, flies
him to Batumi and stops him on a stand there. Two runs, twenty-four and
twenty-nine minutes. What it closed here is **Q3**, **Q3c** and **Q6** — three
structural facts a machine may judge: a handoff was authorised, a phase moved,
and the number that went out was the right field's. The board went
`clearance -> taxi -> holding_short -> departure -> arrival -> approach ->
landed -> taxi_in`, which is the first time anything has reached the last two.

What it did NOT close, and cannot: whether it sounded like one person, whether
a seam was audible, whether a transmission arrived at a moment that made sense.
Those are section S's and stay yours.

Still live: **Q1** (he offered both plans instead of picking Domino — see #89),
and **Q12/Q13**, which were not reached.

**Never flown. This is the new test bed and the reason the card changed.**

Until today the theatre had one aerodrome, so a "handoff" only ever moved you
between two seats at Batumi and half the ladder did not exist. The sortie now
starts at **Kobuleti**, and the whole point of section Q is that a role belongs
to a *field*: there are two Towers and two Departures on the map now, and asking
for the wrong one sends you to a controller forty miles away who will answer
perfectly and give you the wrong numbers.

You are parked at Kobuleti with the radio already on **preset 1**.

**Your plan is on the board as "Domino"** — Kobuleti to Batumi, KOBULETI /
INITIAL / BATUMI, five thousand, radar recovery. It is on the new **PLANS** tab
of the kneeboard along with everything else filed; read it there rather than
from here, because that tab is what a pilot would actually have.

Until 7 August there was no such row. Every plan on the board departed Batumi,
so this sortie had nothing on file at all and the first call of the night would
have been answered with "nothing on file for you" — see [#56].

| id | do this | expected | issue | pri |
|---|---|---|---|---|
| **Q1** | Preset 1. *"Kobuleti Clearance, Sockeye, request clearance."* — **your own callsign**, the one radar prints, not the jet's slot name | He answers as **Kobuleti Clearance** — not Batumi anything — and gives you **Domino** without asking which. He knows you are calling from Kobuleti and it is the only plan that departs Kobuleti. Clearance to Batumi, an altitude, and a departure frequency of **123.300** | [R#56] | **P1** |
| **Q1a** | With **both** Domino and Silverstate on the board, ask Kobuleti Clearance for a clearance | **Domino, unasked.** Silverstate departs *Nellis*, three thousand miles away, and is not even active — a plan that is not from your field is not yours, and offering it as a choice is the resolver ignoring what it knows. On 10 August he offered both and made the pilot pick | [#89] | **P1** |
| **Q1b** | Instead say *"...request IFR clearance to Batumi."* | He should **ask which** and Domino must be among the ones he offers. Every plan on the board ends at Batumi, so naming the destination narrows nothing — a controller who picks one confidently here has guessed. Before 7 August this resolved to *Anvil*: a real plan, someone else's sortie, because "Kobuleti" in your callsign line scored against Anvil's task | [R#57] | **P1** |
| ~~Q2~~ | Read the clearance back, deliberately getting the departure frequency wrong — say *"departure one two four decimal four two five"* | He corrects it. 124.425 is Batumi Approach: a real controller, wrong field. This is the exact failure the field-scoping was built to prevent | [#1] | **P1** |
| ~~Q3~~ | Read it back **correctly** | He hands you to **Kobuleti Ground, 121.800**. A correct read-back is what ends Delivery's business — a wrong one leaves you exactly where you are, which is the point of reading it back | [#1] [#90] | **P1** |
| ~~Q3c~~ | Read it back **badly** — the level and the destination, no frequency and no squawk — then ask **Ground** for taxi before fixing it | **He refuses, and says which state you are in:** *"your IFR clearance has not been read back, contact Kobuleti Clearance one two five decimal one."* No taxi clearance in the reply, and **nobody hands you to Ground** — a refusal that moves you on anyway is the same error with better manners. Then correct only the missing items and he takes it: *"readback correct, contact Kobuleti Ground one two one decimal eight"* | [#134] [#135] | **P1** |
| **Q0** | **Before saying anything else**, ask Kobuleti Clearance for a clearance on a sortie you have not flown yet | He **issues** one. He must not say you are *already* cleared, and must not say your read-back was correct — you have not read anything back. A plan **on file** is not a clearance **issued**, and not a clearance **acknowledged**; "read-back correct" is the phrase that ends Delivery's business and hands you to Ground, so asserting it unprompted skips the rung it exists to close. Found by the ladder rehearsal on a deliberately clean board | [R#105] | **P1** |
| **Q3b** | On check-in with **any** controller, listen for the ATIS | He asks: *"advise you have information Alpha"*, or tells you which letter is current if you named one. On 10 August the engine asked on three consecutive transmissions and **not one reached the air** — it carried no decision, so nothing checked it had been said | [R#90] | **P1** |
| **Q4b** | **Read the taxi clearance back** — *"taxi to runway zero seven, holding short of runway zero seven"* | **Nothing moves.** He acknowledges and you stay with Ground. On 11 August that read-back was heard as a REPORT of holding short, so the phase moved and the ladder sent you to Tower before you had taxied an inch. Then, at three miles, say a debug note — it must reach the recorder and **not** the controller; one at 1,900 ft was classified as "I have landed" and suppressed the whole approach | [R#121] | **P1** |
| ~~Q4~~ | Preset 2. *"Kobuleti Ground, ready to taxi."* | *"Taxi to runway zero seven, hold short of runway zero seven."* **Runway 07** — the wind is 090/5. If he offers 25 the runway is not following the weather | [#41] | **P1** |
| ~~Q5~~ | Still on preset 2, ask **Ground** for take-off | **He refuses**, politely, and sends you to Tower with the frequency: *"take-off is Tower's, contact Kobuleti Tower one three three decimal zero."* Ground owning the runway is the one thing on an aerodrome that must not be shared. If he clears you, that is the most serious finding on this card | [#65] | **P1** |
| ~~Q6~~ | Report holding short | He hands you to **Kobuleti Tower, 133.000** | [R#16] | **P1** |
| ~~Q7~~ | Preset 3. Ask Tower for take-off | Cleared, with the runway and the wind | [#41] | **P1** |
| ~~Q8~~ | Airborne. Say nothing and climb straight ahead | At about **5 nm** he hands you to **Kobuleti Departure, 123.300**, unprompted. Not Batumi. Not on request | [R#16] | **P1** |
| ~~Q9~~ | Preset 4, check in with Departure | He answers as **Kobuleti Departure**. Ask your range from the field: it must be *your* field. On the ramp this read 23 miles because everything was measured from Batumi | [R#16] | **P1** |
| ~~Q9b~~ | Listen to how that check-in is ANSWERED | A **departure** greeting. He must not ask you to report the field in sight, and must not ask whether you have information Alpha — you left the ground ninety seconds ago. It happened five times in one sortie, including from Center at thirty miles. The seat does not tell the two jobs apart; the PHASE does | [#66] | **P1** |
| ~~Q10~~ | Proceed to INITIAL at 5,000 | At about **25 nm out** he hands you to **Georgia Center, 139.000**. Nothing could do this until 2 August — Center had no proactive handoff at all in either direction | [#51] | **P1** |
| ~~Q11~~ | Inbound, say nothing | Inside **25 nm** Center hands you to **Batumi Approach, 124.425** unprompted. This is the fix for the sortie that ended in a Mayday: he sat at 44 nm with nothing in the system able to move him on | [#51] | **P1** |
| **Q12** | At any point, ask a Kobuleti controller for something only Batumi can give — *"request the ASR"* on preset 2 | He should send you to the right man rather than inventing an answer. A controller who works one field must not clear you into another's approach | [R#21] | P3 |
| **Q13** | On any Kobuleti frequency ask *"say again the ground frequency"*, then *"and tower?"* | **121.800** and **133.000**. Until 7 August he was handed no frequency but Departure's and invented the rest — he answered "Ground is one three three decimal zero" (that is Tower) and "Tower is one one eight decimal zero" (that is *Batumi* Tower). Both in faultless phraseology. He now carries his own field's list | [R#58] | **P1** |

**What it is actually checking**

**Q1, Q2, Q5 and Q9 are the section.** Q1 and Q2 say the controller knows which
*airport* he works; Q5 says he knows which *clearances are his*; Q9 says his
geometry is measured from where he is standing. Everything else is the ladder
walking normally.

**Q3 through Q7 are the ground procedure**, which is new on 2 August and has
never been heard. Clearance hands to Ground on a correct read-back; Ground
clears you *to* the runway and says hold short; reporting holding short hands
you to Tower; Tower owns the runway. None of those transitions is a distance —
they are all driven by what you say — so this is the one part of the ladder a
script cannot exercise.

**The steerpoints are in the jet.** The flight plan is written into the mission
as waypoints, so the DTC should come up with INITIAL and BATUMI already loaded —
you should not have to hand-enter them. If they are missing, that is a real
finding and it is worth more than any row here.

**What a wrong answer looks like.** Every failure in this section is a
*plausible* one. A controller who answers as Batumi Approach on Kobuleti's
frequency, a departure frequency of 124.425, a range of 23 miles while you are
parked — each is a real controller, a real frequency, a real distance. None of
them will sound wrong on the radio. Read the numbers against this card rather
than against whether the reply sounded competent.

---

## R — ATIS, and what a controller does with it

**Never flown.** Built 2 August. The broadcast itself is not on the air yet —
the transmitter is the last piece — so these rows are about what the
**controller** does with the information letter, which works now.

| id | do this | expected | issue | pri |
|---|---|---|---|---|
| **R1** | Check in with Batumi Approach saying *"with information Bravo"* (use whatever `/diag` shows as current) | *"Information Bravo is current. Say your request."* | [R#17] | **P1** |
| **R2** | Check in claiming the **wrong** letter — *"with Alpha"* | *"Information Bravo is current now, not Alpha."* Then he asks your request. **He must not refuse you anything** | [R#17] | **P1** |
| **R3** | Check in mentioning **no** letter | *"Advise you have information Bravo."* A prompt, not a telling-off | [R#17] | P2 |
| **R4** | Any of the above | Every one ends by asking **what you want**. He must never assume the ASR — that was a real complaint from the air, and there are two approaches published plus a visual | [R#17] | **P1** |
| **R5** | Check in with **Tower** on short final | He says nothing about the ATIS. Quizzing a man at two miles is noise at the worst moment | [R#17] | P3 |
| **R6** | Ask Ground for taxi, note the runway; then ask Tower for take-off | **The same runway**, both times. It comes from the broadcast, not from each controller's own reading of the wind — that is the whole reason it lives in the database | [R#17] | **P1** |
| **R7** | With a wrong letter, immediately ask for the visual | **Granted.** Nothing about the ATIS gates an approach; you may call the field in sight and take the visual at any point | [R#10] | **P1** |
| ~~R8~~ | Tune the ATIS and listen to the **time** | A real one — *"time one three two one Zulu"*, the mission's hour. It said *"time zero zero zero zero Zulu"* on every broadcast until 11 August, which came back through Whisper as *"0, 0, 0, 0, 0, julium"* | [#94] | P2 |

**What it is actually checking.** R2 and R7 are the section: the letter is a
cross-check, never a condition. R6 is the architectural one — two controllers
naming different runways is what the single source of truth exists to prevent,
and it only shows up if they disagree.

---

## S — does it sound right

**Read this one with your ears, not the card.** Everything else here can be
falsified from a transcript; this cannot, and I have no way to test it at all.

| id | listen for | expected | issue | pri |
|---|---|---|---|---|
| **S1** | Any altitude, heading or frequency | *"niner"*, *"fife"*, *"tree"* — never nine, five, three. This is applied to **every** string on its way to the radio, including the agent's own prose | [R#17] | **P1** |
| **S2** | Your callsign | **"sock-eye"**, the fish. It was being read as one Japanese-looking word and came out like the rice wine | [R#17] | **P1** |
| **S3** | *"Batumi"*, *"Kobuleti"* | Three and four syllables run together, not spelled out and not paused between. The old spellings used CAPITALS for stress, which Polly reads as an initialism, and SPACES between syllables, which it reads as word breaks | [R#17] | **P1** |
| **S4** | The nine controllers across one sortie | Nine distinct voices and nine distinct manners. Batumi Ground is gruff, Kobuleti Clearance is a pedant, Batumi Approach is the calm one | [R#21] | P2 |
| **S5** | Anything said twice — *"roger"*, *"readback correct"* | **Instant** the second time. It is cached after the first render; a pause there means the cache is not hitting | [R#17] | P3 |
| **S6** | Any vector while being repositioned | A heading **in fives** — "two five zero", "two six five". Never "two six seven" | [R#19] | **P1** |
| **S7** | The final approach course | **NOT** rounded — it is 125, the number on the plate. Rounding a published course is the one place five degrees is wrong | [R#19] | **P1** |
| **S8** | Several vectors in a row | The word **"amend"** should be rare. It belongs to changing a clearance already given, not to every turn — there were 25 in one sortie | [#45] | **P1** |
| **S9** | A descent through the repositioning legs | **Steps**, not a slide. Roughly 6500 → 5500 → 3000, not seven numbers 500 ft apart. And no altitude repeated when it has not moved | [#45] | **P1** |
| **S10** | **Every clearance, all sortie.** Taxi, take-off, the approach, landing, a hold, a handoff, a refusal | **The numbers are in it.** A taxi or take-off clearance names the runway; a hold names the level; a handoff or a refusal names the station **and** its frequency. What must never happen is a clearance arriving as a bare *"roger"* or *"go ahead"* — that is the whole test. On the last sortie *"runway one three, cleared for take-off"* reached the air as **"Sockeye, roger."**, and *"contact Kobuleti Tower one three three decimal zero"* as **"go ahead."** Both were flown | [#79] | **P1** |
| **S12** | **When Whisper mangles your callsign** — it will, roughly one transmission in seven — listen to what comes back | ONE sentence, his, not two. He must not tell you he does not have you on the board while clearing you in the same breath: radar named you before you keyed the microphone. A genuinely WRONG callsign — call yourself something that is not yours — must still be corrected, and that is the other half to try | [#172] | **P1** |
| **S11** | **Listen for a transmission with a seam in it** — one that sounds like two sentences stitched together, or says the same thing twice | There should not be one. When the controller leaves a number out, the bridge now adds the missing clause to what he said rather than replacing it — so a failure here sounds like a natural sentence followed by a stiffer, text-book one, or like being told the runway twice. **Report the exact words if you hear it.** Nothing offline can test this: whether it still sounds like one person is the only question on this card a machine cannot answer | [#79] | P2 |
| **S12** | Any digit in any transmission | **Never a spoken numeral.** "runway one three", not "thirteen"; "two thousand", not "two zero zero zero"; "one three three decimal zero", not "one thirty-three point oh". Every quantity is spelled on its way to the radio now | [#79] | **P1** |
| ~~S13~~ | **The landing clearance, on short final** | It arrives. On 10 August the engine issued *"cleared to land runway one three"* and the pilot heard **nothing** — the director returned a 500 and the reply was empty. Report any transmission that simply does not come | [#87] | **P1** |

**Anything that sounds wrong is a line in a table**, not a code change — see
`radio/tts.py`. Tell engineering the word and roughly what it sounded like.

**S6 to S9 are new on 3 August and none has been heard.** S9 is the one to
watch: the descent planner still slides continuously underneath, and what
changed is what gets SAID. If you hear the old behaviour — an altitude every
call, 500 ft apart — the renderer is not on the transmit path yet, which is a
known gap rather than a bug.

---

## T — the Kobuleti ILS

**Never flown.** The point of it is [#3]: a second approach, of a different
kind, at a different field, added as **data only**. If it needs code, the claim
that this is data-driven should stop being made.

**The plate is not drawn.** The kneeboard still renders Batumi's ASR, so you
have numbers and no chart. That is criterion 3 of #3 and it is open.

| id | do this | expected | issue | pri |
|---|---|---|---|---|
| **T1** | Recover into **Kobuleti** rather than Batumi, ILS runway 07 | Vectored to intercept, cleared for the ILS. Final course **070**, decision height 200 above the field | [#3] | **P1** |
| **T2** | Once established, say so | **He hands you to Tower.** This is the difference from the ASR — the aeroplane is flying it, so there is nothing left for Approach to do | [#3] | **P1** |
| **T3** | Compare against the Batumi ASR | On the ASR you are kept to the ground and never asked to report established, because you have no instrument to know. On the ILS you are asked, because you have | [#3] | **P1** |
| **T4** | Ask for a vector east of the field | Nothing below **9,600 ft** within 25 nm. There is 8,556 ft of Caucasus out there and it was surveyed for this | [#3] | **P1** |

---

## U — Nevada: out of Nellis and home again

**A different map, and the point of it is portability.** Everything in this
section is `config/theatres/nevada.toml` and the theatre selection working, or
not — no Nevada-specific controller code exists, and since #137 no
Nevada-specific DATA does either: the fields, the seats, the fixes and the two
ILS procedures are rows read through the same models the Caucasus is. If any
Python is needed the claim that this is data-driven should stop being made.

**Start the bridge with `MARSHALL_THEATRE=nevada`.** The default sortie is
`nevada-nellis-nellis`: out of Nellis, over the Tonopah VORTAC, home to Nellis
on the ILS to 21L. `MARSHALL_SORTIE=tonopah` flies the one-way transit instead.

**What is NOT modelled, so do not report it:** SIDs, STARs, transitions, and the
ranges themselves. There is one ILS end at each field and the controller vectors
everything between the fixes. [#113]

| id | do this | expected | issue | pri |
|---|---|---|---|---|
| **U1** | Preset 1, *"Nellis Clearance, request clearance"* | He answers as **Nellis Clearance** and issues **Redflag** — Nellis to Nellis via Tonopah, cruise **24,000**. Not Silverstate, which is the one-way transit, and not anything Georgian | [R#110] | **P1** |
| **U2** | Work the ladder to take-off: Ground 121.800, Tower 132.550 | The same rungs as the Caucasus, at Nevada frequencies. Nellis Ground is on 121.800, which is *also* Kobuleti Ground's number — a coincidence, written down in `config/theatres/nevada.toml` precisely because it is the sort that makes a wrong answer look right | [R#110] | **P1** |
| **U3** | **Airborne, climbing out, say nothing** | At about 5 nm **Nellis Departure, 135.100**, unprompted. Then at 25 nm **Los Angeles Center, 133.400** — and this is the rung that did not exist. Nevada had no Center at all, so a departure worked cleanly through four controllers and then stayed with Departure for the whole flight, silently. If Center never comes, that is the finding | [R#110] | **P1** |
| **U4** | Ask Center for a range or bearing to **Tonopah** | A real number. The fix catalogue used to be read off `core.route`, so a Nevada bridge published **Kobuleti and Batumi** and never Nellis — and a plan naming a fix the table does not hold is refused at delivery. Ask for **Nellis** too | [R#110] | **P1** |
| ~~U5~~ | **Any vector, anywhere.** Compare it against the chart | The variation is **12 East at Nellis, 16 at Tonopah** — surveyed per aerodrome. A fixed 6 degrees was compiled in for every map until 11 August, so every Nevada vector would have been six to ten degrees out. A vector is the one place that shows | [#109] | **P1** |
| **U5b** | **Anywhere a handoff is due**, listen to the whole transmission | It is a handoff **or** an instruction, never both. On the first Nevada stack run: *"Bandit, contact Los Angeles Center one three three decimal four. Good day. Hold at present position, maintain one zero thousand..."* — sent away and given an order by the man who sent him, and he cannot obey both. Report the exact words | [R#115] | **P1** |
| **U6b** | **On the ILS, watch the vectors for a reversal** | A heading ordered one way and reversed on the next call. `asr_sweep.py` finds 103 of them on the Nellis ILS and none at all on Batumi's ASR — the geometry had never been swept anywhere but Batumi until 11 August, and both Nevada fields sit in terrain that reaches 10,500 ft. Three starts never reach the missed approach point at all | [#117] | **P1** |
| ~~U6~~ | Turn inbound and recover at **Nellis, ILS 21L** | Vectored to intercept and cleared for the ILS at **Nellis** — not Tonopah. The bridge used to load Tonopah's recovery on this map, so a pilot going home would have been worked against a profile for a field 124 miles away | [#2] | **P1** |
| **U0** | **Before anything else, on the ramp at Nellis, just ask for a clearance** | He gives you one. He does **not** say you are past his boundary and send you to Los Angeles Center — which is what happened on the first Nevada run, to a stationary aeroplane. "On the ground" was measured from SEA level against a 200 ft threshold, and the Nellis ramp is at 1,849 ft, so every parked jet on the map read as airborne. Tonopah is worse at 5,550 | [R#114] | **P1** |
| **U7** | Being vectored, check every altitude against the chart minima | Never below them. Nellis and Tonopah carry their own 48-cell surveys, and the terrain here is a mile and a half up — a Caucasus-shaped assumption is not a small error over the Spring Mountains | [R#110] | **P1** |
| **U8** | After landing, the taxi in | Ground has you and nothing hands you back to Tower. Same rung as F6 on the Caucasus, on a map where none of it has ever been flown | [R#100] | P2 |

## V — the radio has no arrival of its own

**Never flown, and the point is what a machine cannot check.** All three rows
below are things that are *correct by luck* on a Kobuleti-to-Batumi sortie —
the radio is loaded with Batumi's ILS and Batumi is where you are going, so a
wrong reference and a right one give the same number. They separate only when
the two differ, which is why they want a pilot and not a sweep.

| id | do this | expected | issue | pri |
|---|---|---|---|---|
| **V1** | On Georgia Center, ask for a range or bearing | It is measured from **where you are going**, and he SAYS so — "twenty three miles from Batumi". A Center has no aerodrome of its own, so a datum that goes unstated is one you cannot check; if he gives a bare "twenty three miles", that is the defect | [#160] | **P1** |
| **V2** | Recover into **Kobuleti** on the same sortie the radio was started for Batumi | Every range Center and Approach speak is measured from **Kobuleti**. This is the one that separates a chosen datum from a fallback: today the radio's loaded arrival decides it, and on this route that is the wrong field by forty miles | [#160] | **P1** |
| **V3** | Ask Approach for the **ILS runway one three** by name | Cleared for that procedure, and the strip and the clearance both name the runway. Asking for "the ILS" when a field publishes two must get a question back, never whichever is listed first — that is #131, which cost a sortie on 12 August | [#165] | **P1** |
| **V4** | With two aircraft recovering to **different fields**, listen to both | Each is worked on his own approach: his own minima, his own stack, his own tower's frequency. One radio, two arrivals. Nothing on the air should suggest the second aeroplane is flying the first one's procedure | [#162] | **P1** |

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
