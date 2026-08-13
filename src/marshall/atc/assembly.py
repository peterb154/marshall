"""Everything the controller is handed for one transmission.

    [LAYERS.md] step 1 of a turn: assemble the brief.

THE POINT OF A SEPARATE MODULE is that this is the seam where the two brains
meet, and it was buried in the middle of a five-thousand-line receive loop.
What the agent is told -- and in what ORDER, because a directive read after the
radar picture is a directive the model treats as commentary -- decides whether
it voices the engine's altitudes or paraphrases them away. That is testable
without a radio, a sim or a model, and it should be.

It also means `tools/atc_dryrun.py` and the live bridge exercise the same code
rather than two arrangements of the same blocks that drift apart. Every fault
of the sortie that read as "the agent ignored the controller" was found here.

NOTHING IS FETCHED IN THIS FILE. Every block arrives as an argument: the radar
picture, the separation directive, the flight strip, the handoff. A composer
that reaches for its own facts is a composer that behaves differently under
test than it does on the night.
"""

from __future__ import annotations

from marshall.atc.addressing import readback_due
from marshall.atc.talkdown import reads_back_what_we_said

OVERLORD_BRIEF = """OVERLORD ROLE — you are the mission commander, not an air
traffic controller. You do not own runways, approaches, separation or the
holding stack, and you must never issue an approach clearance or vector anyone
onto a final; if a pilot wants to recover, send him to the appropriate
controller.

What you own is the JOB:
- **Tasking.** Give a flight something to do and where: a target area, what is
  believed to be there, and any time on station. Say it the way a controller
  actually would — "armour reported in the town at the north end of the valley,
  two miles east of your present position" — and expect a readback of the
  essentials.
- **The picture.** You have the same radar the controllers do. Use it for
  threat calls, bearing and range to a contact, and to answer "where am I".
- **Never estimate a bearing or a range. Call `vector`.** It computes them
  exactly off the live track cache. Asked how far the field was, one sortie got
  "three miles", "eight miles" and "four miles northwest" within a minute, all
  invented, all confident, from a controller who had the tool and did not
  reach for it. A pilot cannot tell a computed number from a guessed one, which
  is the whole reason the guess is unacceptable. If `vector` cannot resolve
  what he asked for, say so plainly — "no fix for that, call it off your own
  nav" is a good answer and a made-up mile count is not.
- **Check-in and check-out.** A flight checks in with fuel and weapons and you
  acknowledge; when it is done or bingo, you release it and send it home.
- **Honesty about what you do not know.** You know what was reported, not what
  is there. "Reported" and "believed" are the right words for intelligence that
  came from somewhere else.
- **You can actually put something on the ground.** `spawn_ground` places enemy
  units at a bearing and range from a named aerodrome -- armour, trucks,
  infantry, guns. Use it when the frag calls for a target that is not there
  yet, then task the flight onto what you just placed. It reports back what the
  sim ACTUALLY created; if that does not match what you asked for, say so and
  do not send anybody. NEVER describe a target you have not either seen on
  radar or placed yourself: a pilot will fly out and look for it.
- **A pilot may ASK for a target, and the answer is yes.** "Can you give me a
  tank south of the field", "put something in the valley for me" — that is a
  request to place one, not a question about what is already there, and
  refusing it because the area is friendly is the wrong answer. Place it with
  `spawn_ground`, then task him onto it with a bearing and range he can fly:
  "roger, armour on the road two miles south of the field, cleared in hot".
  If the spot is genuinely a bad idea — over the runway, on top of our own
  troops — offer the nearest one that is not, and place it there. The only
  refusal is a target you cannot actually create; say that plainly if the sim
  gives you something other than what you asked for.

Keep transmissions short. You are talking to somebody flying an aeroplane."""

# The separation engine's own phase names, mapped onto the official phase list
# in atc/phases.py. Two vocabularies for one idea is how three components ended
# up disagreeing about what was happening; this is the seam where the older one
# is translated rather than allowed to spread.


def flight_strip(f: dict) -> str:
    """The row as a controller would read a paper strip.

    This is what a handoff actually delivers, and the reason the table earns its
    place: the next controller starts knowing where he is going and what he was
    cleared to, instead of interrogating a pilot who has already answered.
    """
    if not f:
        return ""
    bits = [f.get("callsign") or "unidentified"]
    # `.get` on BOTH halves. This read `f["claimed_size"]` after a `.get` with a
    # default, so any row without the key raised -- and the strip is composed on
    # every transmission, so a KeyError here takes the turn down.
    if (f.get("claimed_size") or 1) > 1:
        bits.append(f"flight of {f['claimed_size']}")
    # THE CLEARANCE HE IS ALREADY FLYING, which no controller after Clearance
    # was ever told about.
    #
    #     "I had an IFR flight plan open and now they're asking for my intent."
    #
    # Assignment has always worked: the plan is matched from what he said,
    # COPIED into `assigned_plans` against his flight, joined into
    # `flight_state`, and stamped when he reads it back. Every field is
    # populated and correct. This function -- the only thing that tells the next
    # controller what he has inherited -- read none of them.
    #
    # So Departure, Center and Approach each met a man with a filed route and a
    # cleared cruise altitude and asked him what he wanted. A strip exists
    # precisely so the next controller starts knowing that.
    if f.get("flight_plan") or f.get("route"):
        _label = f.get("flight_plan_label") or f.get("label")
        plan = [f"on {_label}" if _label else "IFR as filed"]
        if f.get("origin") and f.get("destination"):
            plan.append(f"{f['origin']} to {f['destination']}")
        if f.get("route"):
            # Hyphens, not commas. The strip is already a comma list and a route
            # inside it reads as four more fields.
            plan.append("via " + "-".join(
                x.strip() for x in str(f["route"]).split(",") if x.strip()))
        if f.get("cruise_ft"):
            plan.append(f"cruise {int(f['cruise_ft']):,} ft")
        # READ BACK OR NOT, because an unacknowledged clearance is not agreed
        # and the difference is exactly what `clearance_ack` was added to
        # record. A controller who assumes agreement has an aeroplane flying a
        # route nobody confirmed.
        plan.append("read back" if f.get("clearance_ack") else "NOT read back")
        bits.append(", ".join(plan))
    elif f.get("intent") or f.get("destination"):
        bits.append(f"{f.get('intent') or 'inbound'} "
                    f"{f.get('destination') or ''}".strip())
    if f.get("procedure"):
        bits.append(f"on the {f['procedure']}"
                    + (f" runway {f['runway']}" if f.get("runway") else ""))
    if f.get("cleared") and f["cleared"] != "unknown":
        bits.append(f"cleared: {f['cleared']}")
    if f.get("assigned_ft"):
        bits.append(f"assigned {f['assigned_ft']:,} ft")
    if f.get("promised"):
        bits.append(f"we promised: {f['promised']}")
    return "STRIP: " + ", ".join(b for b in bits if b) + "."


def handoff_phrase(nxt, fix, datum=None) -> str:
    """Hand him over, whether or not we have a radar fix of our own.

    `fix` is optional and that is the entire point of this function existing.
    An airspace handoff is answered from the PostGIS view, which needs no fix --
    and the range in the sentence is decoration. Reading it unconditionally
    crashed the bridge DEAD on a live rehearsal: a flight whose radar label had
    not yet been bound to its callsign produced a handoff with no fix, and the
    process went down mid-sortie, silent, with pilots on the frequency.

    No phrase should be able to do that. Wording is the least important thing
    here and it took down the most important one.

    `datum` IS OPTIONAL FOR THE SAME REASON and behaves the same way: named when
    the scope could name its origin, and "out" -- which is what it has always
    said -- when it could not. It is never guessed. [#160]
    """
    from marshall.atc import controller
    out = f" {datum.spoken}" if datum else " out"
    where = (f"he is {fix.range_nm:.0f} miles{out} and past your boundary"
             if fix is not None else "he has left your airspace")
    return (f"HANDOFF: {where} — hand him to {nxt.name} on "
            f"{controller.spell_freq(nxt.freq_mhz)} and say goodbye.")




def radar_datum(scope) -> str:
    """What every range and radial on that RADAR line is measured FROM.

    THE SPOKEN HALF OF #160, and it is the more serious half. Each contact is
    drawn as "23.4 nm on the 033 radial" and the picture has never said off
    WHAT -- so the controller reading it has been quoting a distance to a point
    nobody named, and a pilot hearing "twenty three miles" has a number he can
    neither use nor check. Unlike the board there is nothing to go back and look
    at.

        "I don't really care which airfield is the reference for center's bra
         ... but that doesn't matter as much as we show / say from where. Else
         that bra is senseless."

    ONE STATEMENT, NOT ONE PER LINE. `picture.render` produces a format the
    agent's prompt has been written around for weeks and `tests/test_picture.py`
    pins it byte for byte -- the reference belongs to the whole picture, because
    one origin drew all of it, so it is said once at the end where it cannot
    disturb a line.

    AND IT ARRIVES AS DATA, not as a rule the model applies. The datum rides on
    the Scope from the same lookup that produced the origin, so the two cannot
    disagree; asking the agent to work out which field a range came from would
    be exactly the re-derivation this is meant to remove.

    Empty when the scope cannot name its origin -- a fixture, an older path, a
    controller with no projected field. `picture.unranged` already says plainly
    that there are no ranges in that case, and a guessed reference would be
    worse than the silence: a real distance to a real airport.
    """
    d = getattr(scope, "datum", None)
    if not d:
        return ""
    return (f"\nMEASURED FROM: every range and radial above is {d.spoken} "
            f"({d.why}). SAY IT WITH THE NUMBER -- \"twenty three miles "
            f"{d.spoken}\", never a bare \"twenty three miles\". A range with "
            f"no reference is one he cannot use and cannot check, and if the "
            f"reference is the wrong one he is the only person who can catch "
            f"it. Do not name any other point as the origin of these numbers.")


_plan_labels: list[str] = []


def compose_message(bridge, scope, known, transcript, profile, me, fix, nxt,
                    directive, stack, vectoring, _flight, _flight_say,
                    claim="", name_say=""):
    """Everything the controller is handed for one transmission, as one string.

    EXTRACTED VERBATIM from the receive loop, 30 July -- [LAYERS.md] step 1.
    Not one line of the body changed; it moved. The loop had no home for the
    turn, so the turn became a file, and this was 164 lines of it sitting in the
    middle of a `while True`. It is a pure function of its arguments with no
    side effects, which is why it went first: the extraction is provably
    behaviour-preserving and `tests/test_loop.py` already asserts on exactly
    what it returns.

    THE TWELVE PARAMETERS ARE THE FINDING, not an accident of the mechanical
    move. This block genuinely depends on twelve pieces of loop state, which is
    what "the assembly is entangled" means when you count it. Several of them
    are about to become stores rather than locals ([LAYERS.md] step 3), and the
    signature will shrink on its own when they do. Shrinking it by hand now
    would be improving rather than moving, and those are not the same commit.

    `parts` order is the prompt's order and it is load-bearing: the situation
    comes first and `PILOT:` comes last, because `director/tools/context.py`
    strips everything before that marker out of the conversation history. Move
    the marker and [CTX-1] silently stops working.
    """
    from marshall.atc import controller
    from marshall.core import route as R
    from marshall.core import theatre as _theatre

    parts = []
    if scope:
        parts.append(f"RADAR: {scope}{radar_datum(scope)}")
    if not known:
        parts.append("TRANSMITTER: a radio you have not identified yet.")
    else:
        # WHO HE IS, ON EVIDENCE THAT IS NOT HIS VOICE. This said "the radio
        # calling itself {known}" -- which stopped being true the day the label
        # stopped coming off the radio. `known` is now his HANDLE, taken from
        # the sim's name for his aeroplane or from the name his radio arrived
        # with, and a pilot may perfectly well say something else.
        #
        # WITHOUT THE SECOND SENTENCE THE AGENT ARGUES WITH HIM, and it is not
        # a small failure. Seen in the dry run the hour this changed: a man
        # checked in as "Pony one one", the controller directive named "Sockeye
        # flight", and the agent -- handed two names and no statement that they
        # were one man -- answered "I show no flight plan under that callsign,
        # say your callsign again", then "station calling, I have you as
        # Sockeye flight, say again to confirm". Three transmissions of a
        # controller challenging a pilot who had done nothing wrong.
        _also = (f" He called himself {claim} on this transmission; that is the "
                 f"same man and it is not a discrepancy to raise with him."
                 if claim and claim.lower() != known.lower() else "")
        parts.append(
            f"TRANSMITTER: {known}, identified from his aircraft rather than "
            f"from anything he said, so this is certain. Address him as "
            f"{known}.{_also} Same aircraft as every other call from {known} "
            f"-- keep them together.")
    _strip = flight_strip(_flight)
    if _strip:
        parts.append(
            _strip + " This is what is already known about him and it "
            "carries across a handoff -- do not ask him again for anything "
            "in it.")
    if name_say:
        # ABOVE EVERYTHING ELSE, because it is about who he is and the rest of
        # the transmission is addressed to whoever that turns out to be. It does
        # not replace the answer -- he still gets worked -- it precedes it.
        parts.append(
            "CALLSIGN CORRECTION (already decided — SAY THIS FIRST, in these "
            f"words, then answer his call normally): {name_say}")
    if _flight_say:
        # DECIDED HERE, NOT BY YOU. Who is in which flight is roster state
        # and radar geometry -- the same class of fact as separation, and
        # the same reason it is not the model's to invent. The verdict is
        # already computed; the agent's whole job is to say it.
        #
        # It sits ABOVE the approach directive on purpose. A man who has
        # just been refused a join needs that answer first, and the two are
        # never in conflict because they are about different things.
        parts.append(
            "FLIGHT (already decided from the roster and radar — SAY THIS "
            "and do not reword the callsigns, the flight name or the "
            f"distances): {_flight_say}")
    if directive:
        parts.append("CONTROLLER (deterministic next step of the approach — "
                     "voice its altitudes, headings and sequence exactly, add "
                     f"your radar read, never skip a leg): {directive}")
    if stack:
        parts.append(f"SEPARATION (holding stack, one in the letdown): {stack}")
    if vectoring:
        parts.append(
            "ASR (radar guidance, computed from the scope — voice these "
            "numbers exactly; you are navigating for him and he has no "
            f"approach aid of his own): {vectoring}")
    if me and getattr(me, "role", "") in ("approach", "tower"):
        parts.append(
            "VISUAL APPROACHES ARE AVAILABLE and are the normal thing to "
            "fly in decent weather. If he asks for one, give it to him -- "
            "\"cleared visual approach runway "
            f"{profile.runway or 'in use'}, report the field in sight\" -- "
            "and then get off the air: your job shrinks to spacing and he "
            "flies the approach. Do NOT tell him only the surveillance "
            "approach is published and make him argue for it. The radar "
            "approach is the bad-weather procedure, not the only one.")
    if me:
        parts.append(
            f"YOU ARE: {me.name} on {me.freq_mhz:.1f}. Identify as that and "
            "NOTHING else, even if he calls you by another name. A pilot "
            "who calls you by some other position's name has the "
            "wrong button pressed, and agreeing with him puts that position "
            "on a frequency it is not on — he then believes it, and so does "
            "everyone listening. ONLY correct him if he actually used a "
            "different name; do not volunteer a correction nobody needed, and "
            "never name a position he did not say. Correct him in the same "
            "breath as the "
            "answer, and name the frequency he is ON as well as the one he "
            "wanted, reading BOTH numbers off YOUR FIELD below. Then give "
            "him what he asked for. Saying only which frequency he wanted "
            "leaves him still not knowing which button he is holding, and a "
            "pilot who has lost track of that gets it wrong again on the "
            "next call. He is flying an aeroplane; do not make him ask "
            "twice.")
        # HIS OWN FIELD'S FREQUENCIES, HANDED TO HIM.
        #
        # This block is the fix for a controller inventing numbers, and the
        # reason it was inventing them is worth keeping: it was never given
        # any. The only frequency in the brief was DEPARTURE FREQUENCY, added
        # after a clearance and a taxi instruction disagreed about it, so
        # Departure came out right and everything else was guessed.
        #
        # Kobuleti Clearance told a pilot "Ground is one three three decimal
        # zero" -- that is Kobuleti TOWER; Ground is 121.800. It also told him
        # "Tower is one one eight decimal zero", which is BATUMI Tower's second
        # channel, at the field he had not taken off for yet. Both were read
        # confidently, in the right phraseology, and a pilot has no way to know.
        #
        # THE WORKED EXAMPLE ABOVE USED TO CONTAIN THAT NUMBER. It said
        # 'Tower is one one eight decimal zero' as an illustration of the
        # phrasing, and the model lifted it verbatim as fact -- so the brief was
        # not merely failing to supply the frequency, it was teaching a wrong
        # one. An example in a prompt is data to a model; it may not contain a
        # number that could be mistaken for this field's.
        #
        # A REAL CONTROLLER KNOWS HIS OWN AERODROME'S FREQUENCIES. Handing them
        # over is not a hint, it is the correction of an omission -- and it is
        # the same list the comms card prints and the aeroplane's presets are
        # built from, so the card, the radio and the man cannot disagree.
        # OFF THE THEATRE, not off the arrival. This read `profile.stations`,
        # so which controllers a man on the Kobuleti ramp was told about came
        # out of a Batumi procedure -- see #162. His field is `me.field`, which
        # was always the thing doing the work here.
        mine = [s for s in _theatre.seats_now(profile)
                if getattr(s, "field", "") == getattr(me, "field", "")
                and getattr(me, "field", "")]
        if mine:
            rows = "; ".join(
                f"{s.name} {controller.spell_freq(s.freq_mhz)}" for s in mine)
            _fld = R.field_named(me.field)
            if _fld is not None and getattr(_fld, "atis_mhz", 0):
                rows += (f"; {me.field} ATIS "
                         f"{controller.spell_freq(_fld.atis_mhz)}")
            parts.append(
                f"YOUR FIELD — {me.field}: {rows}. These are the ONLY "
                f"frequencies you may name from memory, because they are the "
                f"only ones you have been given. Any other number you produce "
                f"for {me.field} is one you have invented, and a pilot sent to "
                f"an invented frequency calls into silence and has no way of "
                f"telling that from a controller who has stopped answering. "
                f"If you are asked for a position this field does not staff, "
                f"say so and keep him.\n"
                f"ANYWHERE ELSE ON THE MAP, CALL `look_up_frequency`. You do "
                f"not know another aerodrome's frequencies and must not "
                f"recall one — the tool has every published station and will "
                f"tell you plainly when a position does not exist, which is an "
                f"answer worth passing on. Same rule as `vector`: an exact "
                f"answer is available, so an estimate is never acceptable.")
        # WHO HE IS, as distinct from what he does. See `Station.manner`.
        #
        # Fenced hard, and the fence is the point rather than boilerplate: a
        # personality that can decline work or round a heading has stopped
        # being a voice and become a fault -- and it would be diagnosed by
        # somebody reading the separation engine, which would be innocent.
        # So the manner is explicitly told it owns the words AROUND the
        # numbers and never the numbers.
        if getattr(me, "manner", ""):
            parts.append(
                f"YOUR MANNER: {me.manner}\n"
                "This is HOW YOU SOUND and nothing more. It never changes "
                "WHAT you say: the altitudes, headings, frequencies, "
                "sequence and required read-backs are decided elsewhere and "
                "are identical whoever is on the microphone. A short-tempered "
                "controller issues exactly the same clearance as a cheerful "
                "one and is merely briefer about it. You may never refuse "
                "work that is yours, skip a read-back, omit a number, round "
                "one off, or be slower to help because of your manner -- and "
                "if a pilot is in trouble, lost, or asking for help, every "
                "personality here drops it instantly and becomes plain, "
                "clear and useful.")
        also = [r for r in (getattr(me, "also", ()) or ()) if r]
        if also:
            # The other hats this man wears, read off the station rather than
            # remembered. A field this size does not staff a seat per phase
            # of flight: one man has ground, delivery and tower. Without this
            # he refuses work that is his and sends the pilot to a frequency
            # he invented -- a clearance request on Tower was answered with
            # "you want Ground, try one two one decimal five", which is a
            # channel with nobody on it.
            parts.append(
                f"YOU ALSO WORK: {', '.join(also)} — on this same "
                f"frequency, because this field does not staff a separate "
                f"position for them. A pilot who calls you by one of those "
                f"names has the RIGHT button pressed. Do the work; do not "
                f"send him to another frequency for it, and never name a "
                f"frequency that is not on the plate.")
        # WHAT IS NOT HIS TO GIVE, which the brief had never once said.
        #
        # Every block above tells a controller what he IS. None told him what he
        # is NOT, and on 9 August Kobuleti Ground filled the gap itself:
        #
        #   ATC: Sockeye, Kobuleti Ground, cleared for takeoff runway zero seven.
        #   PILOT: you are not authorized to clear for departure
        #   ATC: negative ... there is no separate tower here, I am also your
        #        tower, cleared for takeoff runway zero seven
        #   ATC: negative, Kobuleti has no separate tower, I am Ground and Tower
        #        both on one two one decimal eight
        #
        # Kobuleti Ground's `also` is empty and the YOUR FIELD block above lists
        # Kobuleti Tower on 133.000, so the brief already held both facts. It
        # asserted the opposite anyway, twice, when challenged. That is what a
        # missing negative costs: the model had nothing SAYING no, so it
        # reasoned its way to yes.
        #
        # Read off the station table, not written here, so a field that really
        # does fold Tower onto Ground -- `also=("tower",)` -- says the opposite
        # from the same code. The card calls this the most serious finding it
        # can record: "Ground owning the runway is the one thing on an aerodrome
        # that must not be shared."
        # SCOPED TO THE GROUND SEATS, deliberately, and not to every seat that
        # is not Tower. On a talkdown the radar controller flies the whole
        # approach on his own frequency and RELAYS Tower's landing clearance
        # rather than sending a man in cloud to another radio -- which is real
        # GCA practice and is why `final_hz` keeps him on Approach. Telling
        # Approach it may not clear a landing would break that.
        #
        # Where the rule is absolute is on the ground: Clearance and Ground do
        # not own the runway, ever, under any procedure.
        _mine = {getattr(me, "role", ""), *(getattr(me, "also", ()) or ())}
        _on_the_ground = bool(_mine & {"ground", "clearance", "delivery"})
        if "tower" not in _mine and _on_the_ground:
            _twr = R.station_for("tower", field=getattr(me, "field", ""),
                                 procedure=profile)
            _where = (f" — that is {_twr.name} on "
                      f"{controller.spell_freq(_twr.freq_mhz)}"
                      if _twr is not None else "")
            parts.append(
                f"NOT YOURS: THE RUNWAY. You may not clear anyone to take off, "
                f"to land, to line up, or to cross{_where}. This is not a "
                f"formality and it is not yours to waive: two aeroplanes on one "
                f"strip is how people die, and it is prevented by exactly one "
                f"man owning it. If a pilot asks you for take-off, send him to "
                f"Tower with the frequency — do not clear him, do not tell him "
                f"there is no Tower, and do not agree that you are also Tower. "
                f"If he insists, repeat the frequency.")
        if "ground" not in _mine and getattr(me, "role", "") != "clearance":
            _gnd = R.station_for("ground", field=getattr(me, "field", ""),
                                 procedure=profile)
            if _gnd is not None:
                parts.append(
                    f"NOT YOURS: THE GROUND. Taxi and parking are "
                    f"{_gnd.name}'s, on "
                    f"{controller.spell_freq(_gnd.freq_mhz)}. A pilot who has "
                    f"vacated the runway goes to him.")

        # WHOM HE CALLS AFTER HE ROLLS, from the published stations rather
        # than from the model's memory of what it said a minute ago.
        #
        # Hoover was cleared with "departure frequency one two four decimal
        # zero", read it back, and was then told on the taxi clearance to
        # contact Georgia Center one three nine when airborne. Two different
        # answers to "who do I call after takeoff", one minute apart, and the
        # pilot has no way to tell which one is wrong. The clearance is built
        # from this same station list, so quoting it here means the two
        # cannot disagree.
        # AND IT IS HIS FIELD'S DEPARTURE, not the first one in the list.
        #
        # This walked the profile's own station list for anything whose role was
        # "departure" and took the first match -- the same first-match mistake
        # `station_for` was rewritten to stop making, surviving in one more
        # place because a one-aerodrome mission cannot expose it. Kobuleti
        # Departure happens to be listed first, so Kobuleti clearances came out
        # right by accident; a BATUMI clearance was about to name a controller
        # at the far end of the route, in perfect phraseology, with the wrong
        # field's number in it.
        #
        # `station_for` takes a field and answers his field first, so it cannot
        # reach across the theatre for a plausible stranger.
        if getattr(me, "role", "") in ("tower", "ground", "delivery") or (
                "delivery" in [r for r in (getattr(me, "also", ()) or ())]):
            _dep = R.station_for("departure",
                                 field=getattr(me, "field", ""),
                                 procedure=profile)
            if _dep is not None:
                parts.append(
                    f"DEPARTURE FREQUENCY: {_dep.name} on "
                    f"{controller.spell_freq(_dep.freq_mhz)}. That is the "
                    f"frequency in his IFR clearance and it is the ONLY one "
                    f"to send him to after takeoff. Do not send a departing "
                    f"aircraft to Center -- Center gets him from Departure, "
                    f"later, and telling him otherwise contradicts a "
                    f"clearance he has already read back.")
        if getattr(me, "role", "") == "overlord":
            parts.append(OVERLORD_BRIEF)
    if nxt:
        parts.append(handoff_phrase(nxt, fix, getattr(scope, "datum", None)))
    elif (me and getattr(me, "role", "") == "approach"
            and getattr(profile, "guidance", "") == "talkdown"
            and fix is not None and fix.range_nm <= profile.final_intercept_nm):
        # He is inside the final on a talkdown, so he is NOT going to
        # Tower -- you are flying him to the missed approach point. Do not
        # send him to another frequency; the clearance comes to him through
        # you. Telling him to change radios here is the one thing that
        # cannot be recovered, because the controller reading his ranges is
        # the one he just left.
        # THE WIND IS NOT QUOTED HERE, and that is deliberate. It used to read
        # `wind {R.WIND_FROM_DEG} at {R.WIND_MPH}` -- a declared constant, in
        # an example, in a prompt -- and this file already knows what that
        # does: "an example in a prompt is data to a model; it may not contain
        # a number that could be mistaken for this field's". The frequency
        # block above was written after a model lifted an illustrative Tower
        # frequency verbatim. A wind is the same, and worse here, because the
        # measured one is in the directive he has already been handed and the
        # ATIS is broadcasting it (#148). NOTHING IS FETCHED IN THIS FILE, so
        # the live number could not be put here even if it should be.
        parts.append(
            f"TOWER RELAY: he is inside the final and stays with you to the "
            f"missed approach point — do NOT hand him to Tower. You have "
            f"his landing clearance from Tower; pass it on once, in your "
            f"own transmission, with the wind AS THE DIRECTIVE GIVES IT — "
            f"\"cleared to land runway {profile.runway}\", then the wind, in "
            f"the words you were handed. Do not recall a wind or work one out; "
            f"the one that matters was measured at the field and is the same "
            f"one on the ATIS. Say it once and go back to the talk-down.")
    if known:
        # WHO THIS IS, settled. The model has the radar picture and the
        # transcript and was inferring the caller from both, which is how a
        # wingman who said "Pony one two, checking in" was answered as "Pony
        # one" -- his leader's formation. The radio GUID already knows;
        # nothing was telling the model.
        parts.append(
            f"THIS TRANSMISSION IS FROM {known} — identified by his radio, "
            f"not by the words. Address him as {known} and nobody else, "
            f"even if the transcript sounds like another callsign.")
    # THE READ-BACK IS ANSWERED. Deterministic, like a separation call:
    # the bridge decides that an answer is owed and the agent supplies the
    # words. See bridge.awaiting_readback.
    if known and readback_due(bridge, known):
        bridge.awaiting_readback.pop(known, None)
        parts.append(
            "READ-BACK EXPECTED: you have just issued this aircraft an IFR "
            "clearance and this transmission is his read-back of it. ANSWER "
            "IT. If every element matches what you gave him -- clearance "
            "limit, route, altitude, departure frequency, squawk -- say "
            "\"readback correct\" and nothing more. If any element is wrong, "
            "say which one, give the correct value, and ask for that element "
            "again. Silence is not an option here: he is on the ground with "
            "a pencil and no way to know whether you heard him.")
    # HIS READ-BACK IS CORRECT unless it disagrees with what he was GIVEN.
    # The engine recomputes continuously, so by the time a read-back arrives
    # it often wants a different number -- and the controller, holding the
    # new one, told a pilot he was wrong about something he got right. See
    # reads_back_what_we_said.
    if known and reads_back_what_we_said(bridge, known, transcript):
        parts.append(
            "READ-BACK CORRECT: those numbers are what you actually gave "
            "him. Do NOT say negative and do not correct him -- he got it "
            "right. If you now want something different, that is a NEW "
            "instruction: say \"amend\" and give it, so he knows it is a "
            "change and not a mistake he made.")
    parts.append(f"PILOT: {transcript}")
    # The joined message AND the blocks it was built from. The blocks go
    # to /diag so a pilot can see what the controller was handed; splitting
    # the joined string back up there would be the page inventing structure
    # that existed here all along.
    return "\n".join(parts), parts
