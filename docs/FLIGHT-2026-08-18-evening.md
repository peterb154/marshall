# Flight test, 18 August 2026, evening — the first sortie on the BatumiTest board

    Type: WORK RECORD
    Flown: 18 August 2026, 21:28–21:38, Kobuleti → airborne, ended at 19 nm
    Recorder: build/logs/flight-hooks.jsonl
    Radio: pid 2433940, commit 1f84fc4
    Board: BatumiTest (FOO, BAR, SPAM, INITIAL, BATUMI), NellisTest

Ten minutes, eighteen exchanges. **Ended by the pilot on a finding**, not by a
crash. Nine findings; the last one is why the mission stopped.

---

## What the morning's fixes did, measured

**Every one of yesterday's seven held.** This is the first sortie where the
clearance rung completed end to end, and the database proves it rather than the
transcript:

    flights          sockeye · departure · has_been_airborne=True
                     atis_letter='Delta' · clearance_ack 21:30:46
                     mission 362nd-Blind-Flying-1444@1786509383
    assigned_plans   BatumiTest · origin=Kobuleti · squawk 7457 · acknowledged

- **#180** — the letter was recorded on the first call and never asked for
  twice. *"Information Delta is current. Say your request."*
- **#183** — *"request IFR to Batumi, via the BatumiTest flight plan"* resolved
  to BatumiTest with no disambiguation question.
- **#185** — no `unbacked` records. The clearance was real.
- **#187** — the row is in the same bucket a fresh process resolves.
- **#178** — `sortie_phase` went clearance → taxi → holding_short → departure
  and **never** `landed`.
- **#184** — the arrival queue read `UNKNOWN` the whole way down the ground
  ladder and only became `ENROUTE` at 21:36:01, once airborne.
- **origin at clearance time** — `assigned_plans.origin = Kobuleti`, from the
  seat, exactly as designed.

---

## 1. Asked for his own waypoint, he was given one from a retired flight plan

**THE ONE THAT ENDED THE SORTIE.**

    21:38:00  PILOT  Kobuleti Departure, can you tell me what my first, my
                     second waypoint is, I'm headed to steer point two.
    21:38:06  ATC    Sockeye, steerpoint two is feet wet, heading two seven
                     zero for one two miles off steerpoint one.
    21:38:34  NOTE   that's a serious issue. She said, steer point two is feet
                     wet. That's an old World War II waypoint. The waypoint two
                     for my flight plan is bar. I'm ending this mission

His route is **FOO → BAR → SPAM → INITIAL → BATUMI**, and it resolves cleanly:
`route_fixes` reports nothing missing. `flight_plan_help(callsign)` exists for
exactly this question and returns that route. The controller did not use it.

**FEET WET is a fix from the retired plan set**, still published in the theatre
file and still in the fix table:

    fixes held:  batumi, egress, FEET WET, ingress, initial, kobuleti,
                 kutaisi, steerpoint 1..6, tsutsnvati, waypoint 1..6
    NOT held:    FOO, BAR, SPAM      <- this flight's actual route

So the two vocabularies are not reconciled: the pilot navigates by the names on
his own plan, and the controller answers from a theatre list that contains the
old sortie's fixes and none of his. This is the over-fitment `BatumiTest` was
created to expose, doing exactly what it was built to do.

---

## 2. Departure sent him back to Tower, contradicting the engine in the same turn

    21:36:11  PILOT     Kobuleti Departure, sockeye with you, 1.6 for 5.   [on 123.3]
    21:36:13  ENGINE    Sockeye, Kobuleti Departure, radar contact.
    21:36:14  handoff   Kobuleti Departure keeps him -- departure, 3 nm, outbound
    21:36:18  ATC       Sockeye, you should be with Tower, one three three
                        decimal zero — you're still with me. Continue your climb.

He was on the right frequency, having been sent there four seconds earlier. The
engine identified him and the handoff rule said Departure keeps him; the voice
said the opposite in the same turn.

**This is yesterday's finding 2 in shape and NOT in cause.** #178 fixed the
phase — the board reads `departure`, owner `Kobuleti Departure`, and the engine
is right. What spoke here is the agent's own wrong-frequency correction, firing
against a decision the engine had already made.

    "clearly departure doesn't think I should be with or yet"

---

## 3. `cleared for` is blank on the board, and this time the data IS there

    21:31:11  NOTE  I finally got the read back correct, which was good, but
                    cleared for, is still showing blank on my board
    21:33:30  NOTE  I wonder if Kobuleti Clearance actually put me on the
                    clearance because the board says cleared for Dash, but I'm
                    guessing he just remembers that from the conversation
                    history, not actually putting it in the database

**The guess was reasonable and is wrong, which is the point.** Yesterday it was
right — nothing was written. Tonight `assigned_plans` holds `BatumiTest,
Kobuleti, 7457, acknowledged`. The value exists and the page does not render
it, so what was a data bug yesterday is a display bug today, wearing the same
face. A pilot cannot tell those apart, and spent two transmissions and a taxi
back to Clearance finding out.

---

## 4. Ground cannot say which plan he is on, and sends him back for it

    21:31:41  PILOT  Kobuleti Ground, can you tell me which IFR flight plan I
                     am cleared for?
    21:31:47  ATC    Sockeye, that's Clearance's business, not mine — contact
                     Kobuleti Clearance one two five decimal one.
    21:32:03  NOTE   clearly, she doesn't know what flight plan I have. I'll go
                     back to Clearance and see

**Reading a fact is not issuing a clearance.** The rule that nobody issues a
clearance that is not his is right and this is not that: he asked what he had
already been given. `clearance_state` and `flight_plan_help` both answer it and
neither is seat-restricted. Cost: a taxi back to Clearance and four
transmissions, and a second handoff to Ground (see 8).

---

## 5. The first call of the sortie was answered with a farewell

    21:28:09  PILOT  Kobuleti Clearance, sockeye, parking spot, number 22 with
                     information, Delta.
    21:28:09  ATC*   Sockeye, roger, welcome, good day.
    21:28:30  NOTE   he didn't ask what I wanted, just said good day

`atc/simple` — the fast path. *"Welcome"* is for an arrival and *"good day"*
closes an exchange; he was cold on the ramp opening one. The engine's own
clearance-delivery phrase (*"Say your request"*) exists and was not used until
his second call.

---

## 6. A correction was prefixed with "go ahead"

    21:30:09  PILOT  Maintain one zero thousand, squawk, and seven four five
                     sevens, okay.
    21:30:12  ENGINE Sockeye, negative — say again one two three decimal three,
                     seven four five seven.
    21:30:15  ATC    Sockeye, Kobuleti Clearance, go ahead. Say again one two
                     three decimal three, squawk seven four five seven.

He was mid read-back. *"Go ahead"* invites a call that is already in progress.
The engine's wording was correct and the voice added the greeting in front of
it — the same family as card row S15 and the open #10 C3, and the third time
this exact seam has been heard.

---

## 7. Tower handed him to Departure off the end of the runway

    21:35:14  ATC   runway zero seven, cleared for takeoff, wind zero nine zero at five
    21:35:49  ATC   Sockeye, contact Kobuleti Departure one two three decimal three
    21:36:45  NOTE  tower, switch me over to departure pretty quick, should be
                    at five miles I think, just hit it off the end of the runway

Thirty-five seconds after the take-off clearance. Note this is the ENGINE's
handoff, not the voice's — the timing rule is the engine's to hold, and #179
deliberately took the *when* away from the model. So this is the handoff rule
itself, not a controller volunteering it.

---

## 8. Clearance handed him to Ground twice

    21:30:49  ATC  readback correct, contact Kobuleti Ground one two one decimal eight
    21:32:36  ATC  that's correct, contact Kobuleti Ground one two one decimal eight, good day

The second came after he taxied back to ask his question (4). A man already
taxiing on Ground's frequency was handed to Ground again. Harmless on the
radio, but the board bounced owner Clearance → Ground → Clearance → Ground,
and a handoff that fires twice is one that could fire wrongly.

---

## 9. A read-back of a frequency became a callsign

    21:35:58  PILOT  1, 2, 3, decimal, 3, sockeye.       -> addressed to "Decimal 3"
    21:36:18  ATC    ...                                 -> addressed to "Decimal 0"

The recorder shows `to=Decimal 3` and `to=Decimal 0`. He was reading back
123.3 with his callsign at the end, and the addressee resolver took the digits.
The reply reached him anyway — the transmitter GUID is the anchor and did its
job — so this cost nothing tonight. It is recorded because the correction path
(#172) fires on the addressee, and a spoken frequency is the most common thing
on the channel after a callsign.

---

## Not bugs — the pilot's own notes, kept so they are not lost

- **21:33:50** — *"let's change this mission to have me parked on spot number
  one, that'll make taxiing a lot faster and test cycles quicker."* A test-bed
  change, not a defect.
- **21:35:02** — *"let's reorder the board, the DAG board, to put the reasoning
  from AI above the decided against, I can't see in a single flash what the AI
  is thinking."* A `/diag` layout request.

---

## What worked, recorded so it is not re-fixed

- **The clearance rung completed for the first time**, with a row in
  `assigned_plans` to prove it — the whole of yesterday's 4, 5 and 6.
- **The read-back verifier did its job twice**, naming the missing element each
  time rather than restarting the clearance, and accepted the third attempt.
- **`BatumiTest` resolved from the pilot's own words** with no disambiguation.
- **The taxi gate did not fire**, because he was properly cleared — #181's
  quiet half.
- **The board told the truth about the arrival queue and the sortie phase all
  the way down the ladder**, which is #184 and #178 together.
