"""Generate the mission-specific 'plate' prompt block from route.py.

The agent's soul and rules are field-agnostic and hand-written — how a controller
talks, identifies, hooks, stays honest. The FACTS — this field's beacon, runway,
altitude ladder, headings, timing, wind, and the controller's capability /
handicaps — are data, and they already live in `route.py`. This turns that data
into the markdown block the bridge pushes to the director as the 'plate' prompt
part, so standing up a new field or dialing in a handicap is a route.py change,
not a prompt rewrite. It also keeps the plate and the actual mission/chart from
ever disagreeing, since all three read the one profile.
"""

from __future__ import annotations

from marshall.core.say import freq_text

from marshall.core import route as R

_PHON = {"A": "Alpha", "B": "Bravo", "C": "Charlie", "D": "Delta", "E": "Echo",
         "F": "Foxtrot", "G": "Golf", "H": "Hotel", "I": "India", "J": "Juliet",
         "K": "Kilo", "L": "Lima", "M": "Mike", "N": "November", "O": "Oscar",
         "P": "Papa", "Q": "Quebec", "R": "Romeo", "S": "Sierra", "T": "Tango",
         "U": "Uniform", "V": "Victor", "W": "Whiskey", "X": "Xray", "Y": "Yankee",
         "Z": "Zulu"}


def _phonetic(ident: str) -> str:
    return " ".join(_PHON.get(c.upper(), c) for c in ident)


def _inbound_hdg(profile: R.ApproachProfile) -> int:
    """The charted inbound course, falling back to the runway designation.

    final_crs wins. Deriving the course from the runway number instead ("12" ->
    120) is off by however much the runway's real centreline differs from its
    rounded name -- at Batumi that is 124 vs 120, so the agent was reading the
    plate four degrees off the nav log the pilot flies.
    """
    if profile.final_crs:
        return profile.final_crs
    try:
        return int(profile.runway) * 10
    except (ValueError, TypeError):
        return 0


def _mmss(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    return f"{m} minutes {s} seconds"


def _channels(profile: R.ApproachProfile) -> list[str]:
    """Which controller sits on which frequency, and why it is not a choice.

    The aircraft has four radio presets and its homing adapter works only on the
    frequency the set is tuned to, so the pilot cannot listen to you on one
    channel while homing a beacon on another. Each phase's controller therefore
    lives on the beacon flown in that phase.
    """
    # A 1944 CONSTRAINT, and only a 1944 aeroplane has it. The paragraph below
    # is about a set whose homing adapter works on the tuned frequency, so the
    # pilot cannot listen on one channel while homing on another. An F-16 has
    # two radios and a separate navigation receiver and none of it applies.
    #
    # The guard is `arrival_fix`: an approach with no enroute homing fix has
    # nothing to say here. It also stopped the bridge dead on Nevada --
    # `profile.arrival_fix.name` on a None -- which is how this was found.
    #
    # AND THE BEACON IS GUARDED FOR THE SAME REASON, not because a procedure
    # exists today with an arrival fix and no beacon, but because the paragraph
    # below is about homing one and there is now such a thing as an approach
    # that homes nothing at all (#163). Two Nones, one lesson.
    if (getattr(profile, "arrival_fix", None) is None
            or getattr(profile, "navaid", None) is None):
        return []
    enr_name, enr_freq = profile.station(enroute=True)
    twr_name, twr_freq = profile.station()
    out = []
    if enr_freq and enr_freq != twr_freq:
        out.append(
            f"- **Channels.** Enroute he homes {profile.arrival_fix.name} and is "
            f"on **{freq_text(enr_freq)}** ({enr_name}); the letdown is flown homing "
            f"{profile.navaid.name}, so it belongs to {twr_name} on "
            f"**{freq_text(twr_freq)}**. Hand him over as he leaves "
            f"{profile.arrival_fix.name}. He physically cannot hear you on a "
            "channel he is not homing.")
    return out


def _own_seats(profile: R.ApproachProfile) -> list[str]:
    """The seats of a procedure that is NOT on the theatre's ladder.

    One document may not contradict itself, and until this existed it did. The
    shared block lists the map's controllers -- Batumi Tower on 118.6 -- and
    the 1944 letdown's own channels paragraph puts Batumi Tower on 132.0,
    because on that procedure the man you talk to IS the frequency you home.
    Both are true and only one applies to any given aeroplane; a controller
    reading them together would have had to guess, and the wrong guess sends a
    Mustang to a frequency his ARA-8 cannot tune.

    Empty for every modern approach, which is the normal case: `seats_now`
    hands those the ladder and there is nothing to distinguish. See
    `theatre.beacon_seats`, which is where the derivation lives -- this only
    says it out loud. [#140, #162]
    """
    if getattr(profile, "theatre_stations", True):
        return []
    from marshall.core import theatre as _t
    seats = _t.beacon_seats(profile)
    if not seats:
        return []
    who = "; ".join(f"**{s.name} {freq_text(s.freq_mhz)}**" for s in seats)
    return [
        f"- **THE SEATS ON THIS PROCEDURE ARE ITS BEACONS**, and they are not "
        f"the ladder listed above: {who}. An aeroplane flying this letdown "
        f"tunes and homes one frequency at a time, so the controller working "
        f"him sits on the beacon he is homing. Never read him the ladder's "
        f"frequencies — they are real seats on radios he has not got.",
    ]


def _formation(flight: str, size: int,
               profile: R.ApproachProfile | None = None) -> list[str]:
    """How to handle a formation. Deliberately says nothing about WHICH one.

    This block used to name the flight the mission expected -- callsign, size,
    every member -- which reads as "this is who is coming" and taught the
    controller to expect one aeroplane in particular. A pilot noticed the
    consequence immediately: Center greeted him already knowing where he was
    going. The plate describes the FIELD and its procedures; who turns up, in
    what, going where, is theirs to say and the controller's to ask.

    NOR WHICH LADDER, when there is more than one procedure in front of him.
    The break-up puts a level between two aeroplanes and the levels come from
    the approach each is flying, so quoting one procedure's stack while
    describing several is the same error the whole of #162 is about: a real
    set of altitudes belonging to the wrong arrival. With no profile it points
    at the procedure instead of naming numbers.
    """
    ladder = (", ".join(f"{ft}" for ft in profile.stack_ft[:4])
              if profile is not None else "")
    ladder = (f"the ladder is {ladder}" if ladder
              else "the holding stack is the one listed under his procedure "
                   "below, bottom first")
    return [
        "- **A formation is ONE aircraft to you while it is together**: one "
        "clearance, one altitude, lead answers for all of them. Address it as "
        "a flight. A wingman who transmits is the flight talking — do not open "
        "a second conversation with him.",
        "- **Break a flight up before the approach**, into individually-"
        "sequenced singles. Ask first whether they can maintain visual "
        "separation: in visual conditions they may split inside ONE level, in "
        "trail; in cloud you separate them yourself, a level each, lead lowest "
        f"so he lands first ({ladder}). Never assume — assuming "
        "they can see each other puts several aeroplanes on one level in cloud.",
        "- After the break-up they are ordinary singles on their own callsigns.",
    ]

def _setting(profile: R.ApproachProfile) -> str:
    """The altimeter setting this field passes, spoken.

    QFE or QNH is the field's convention and it changes the number. It also
    changes what every altitude on the plate MEANS -- height above the runway
    or altitude above the sea -- which is why the datum is said out loud rather
    than assumed.
    """
    if getattr(profile, "altimeter_datum", "QNH").upper() == "QFE":
        return R.altimeter_spoken(R.qfe_inhg(profile.field_elev_ft))
    return R.altimeter_spoken()


def _asr_lines(profile: R.ApproachProfile) -> list[str]:
    """The facts for a surveillance-radar approach. THIS PROCEDURE ONLY.

    A different procedure needs a different briefing, not the letdown's with
    words changed: on an ASR the controller navigates, so what he must know is
    the course to put the pilot on, the altitudes, and where to stop -- there
    are no legs for the pilot to fly and nothing for him to home.

    Returns LINES rather than a document, and that is what lets one prompt
    describe every procedure the map publishes instead of the one the process
    was started on. The theatre's own facts -- the seats, the departure field,
    the sortie, what is shooting -- are `_theatre_lines` and are said once for
    all of them. [#162]
    """
    inbound = profile.final_crs
    rwy = profile.runway or "in use"
    return [
        f"- This is a **surveillance radar approach** to runway **{rwy}** at "
        f"**{profile.aerodrome.name}**. **You** navigate; the pilot flies the "
        "headings you give him. He has no approach aid of his own.",
        f"- Final approach course **{inbound:03d}**. Vector him to intercept it "
        f"by **{profile.final_intercept_nm:.0f} miles** from the field.",
        f"- Vectoring altitude **{profile.platform_ft}** until established on "
        f"final; then down to **MDA {profile.mda_ft}** "
        f"({profile.mda_ft - profile.field_elev_ft} ft above the field).",
        f"- Missed approach point **{profile.map_nm:.1f} miles** from the field. "
        f"Missed approach: climbing **{profile.missed_turn}** turn to "
        f"**{profile.missed_ft}**, re-sequence.",
        "- **Call range every mile on final**, with his position relative to the "
        "course: \"six miles from the runway, on course\", \"drifting right of "
        "course, turn left heading one two zero\".",
        "- **There is no glidepath.** You give range and course; his descent is "
        "his own. Never invent a glidepath call.",
        f"- **Altimeter {_setting(profile)}** ({profile.altimeter_datum}) — pass "
        "it when you call radar contact, and to anyone who asks. Every height "
        "you read him is measured against this datum; a pilot who never gets it "
        "is holding a different one and neither of you knows by how much.",
        f"- Wind **{int(R.WIND_FROM_DEG):03d} at {int(R.WIND_MPH)}** mph, "
        "**briefed** — the mission was built with it. THE WIND YOU SAY IS THE "
        "MEASURED ONE, off the ATIS, and it reaches you in the directive with "
        "the landing clearance; never read this briefed number on the air, and "
        "never work one out. Do NOT pass the wind as a correction while "
        "vectoring either — you are watching his ground track, so the drift is "
        "already inside the heading you give him. Correct what the scope shows, "
        "not what the wind should do. It IS said with the landing clearance, "
        "where it tells him what to expect in the flare.",
        f"- Assignable altitudes: **{profile.platform_ft}** vectoring, "
        f"**{profile.mda_ft}** MDA, **{profile.missed_ft}** missed. Nothing else.",
    ]


def _departure_field() -> list[str]:
    """The OTHER aerodrome, which the plate knew nothing about.

    The plate has always described the field being approached, because that was
    the only field there was. The sortie now departs Kobuleti, so three of the
    seven controllers on this frequency list work an aerodrome the plate never
    mentioned -- they had its frequency and nothing else.

    THEY DID NOT SAY SO. They guessed, and the guess was plausible: asked for
    taxi, Kobuleti Ground cleared an aircraft to runway 25 with the wind at
    090, which is the downwind end of his own runway. Nobody would query it on
    the radio. It is the same failure shape as the radar origin -- a real
    number belonging to the wrong airport -- and it is why "which runway" is
    computed here from the wind rather than left to a model that has not been
    told the field exists.
    """
    # THE LOADED THEATRE'S DEPARTURE FIELD, and its own controllers.
    #
    # This was `R.KOBULETI_FIELD` with Kobuleti's three frequencies written into
    # the prose. On Nevada that put "Kobuleti Clearance 125.1" into the Nellis
    # controller's own briefing -- a real facility, on another continent, in the
    # one document he is told to believe. Wrong field, plausible answer: the
    # same fault as `station_for`, in the prompt rather than in the code.
    from marshall.core import theatre as _t
    th = _t.current()
    f = th.field_named(th.departure)
    if f is None:
        return []
    rwy = f.runway_in_use(th.wind_from_deg)
    here = [s for s in th.stations if s.field == f.name]
    who = ", ".join(f"**{s.name} {freq_text(s.freq_mhz)}**" for s in here) or "nobody"
    arr = th.field_named(th.arrival)
    out = [
        f"- **DEPARTURE FIELD — {f.name.upper()}.** Field elevation "
        f"**{f.elevation_ft} ft**. Runways **{f.ends[0]:02d}/{f.ends[1]:02d}**. "
        f"With today's wind the runway in use is **{rwy:02d}** — taxi, "
        f"line-up and departures are all {rwy:02d}, and the reciprocal is "
        f"downwind. Do not offer the other end.",
        f"- {f.name} is worked by {who}. A departure leaves the aerodrome's "
        "controllers for Departure at about **5 miles**.",
    ]
    # ONLY WHEN THEY ARE TWO PLACES. A sortie that recovers where it departed
    # has no other aerodrome to confuse, and warning a controller off a field he
    # is standing on reads as nonsense.
    if arr is not None and arr.name != f.name:
        out.append(
            f"- {f.name} is a DIFFERENT AERODROME from {arr.name}, with a "
            f"different runway. Never read {arr.name}'s runway, course or "
            f"minima to somebody standing on {f.name}.")
    return out


def _mission() -> list[str]:
    """What the squadron is actually doing today, and who owns which part.

    Without this a controller knows the route but not the sortie, which makes
    him a very well-informed taxi service: he can vector a pilot to a waypoint
    and has no idea why anyone would go there, cannot answer "how long have I
    got", and will happily send a flight home past the thing it was sent to
    attack. A real controller knows what the aeroplanes on his frequency are
    for.

    Deliberately short. This is context, not a script -- the detail belongs to
    whoever is working him at the time, and the overlord's own brief covers
    tasking.
    """
    overlord = None
    for s in R.STATIONS:
        if getattr(s, "role", "") == "overlord":
            overlord = s
    tgt = getattr(R, "TARGET_AREA", None)
    if tgt is None:
        return []
    lines = [
        "- **Today's mission.** Armed reconnaissance and close air support over "
        f"**{tgt.name}**, the town on the lake east of Kutaisi. The flight "
        "transits out, works the area under tasking, and recovers here. It is "
        "1945, the war is over, and the ground east of Kutaisi has not been "
        "told.",
        "- **Batumi is the only friendly field.** There is no alternate and "
        "nowhere to divert. A pilot who cannot get in comes round and tries "
        "again, so keep something in reserve for him and do not let a fuel "
        "state creep up on you.",
    ]
    if overlord:
        lines.append(
            f"- **{overlord.name} on {freq_text(overlord.freq_mhz)} owns the "
            "tasking**, not you. Targets, time on station and what is down "
            "there are his to give. If a pilot asks you for a target, send him "
            f"to {overlord.name} — and if he is coming home early, that is "
            "worth knowing, because it usually means something went wrong.")
    return lines


def _sortie() -> list[str]:
    """The route the squadron is flying today, so a controller recognises it.

    Without this a pilot says "we are routing via FEET WET to NORTH" and the
    controller has never heard either name -- it can vector him perfectly well
    but cannot talk about his PLAN, which is most of what an enroute controller
    does. With it, "cleared as filed" means something, "report NORTH" is a
    trigger he owns, and a request to route direct can be answered against what
    was actually filed.

    It is today's plan, not a permanent fact about the field. Wording matters:
    a controller who assumes every arrival is flying it will greet a stranger
    by name, which is the over-fitting that got caught once already.
    """
    # THE LOADED THEATRE'S ROUTE. This read `core.route`'s strike sortie
    # whatever map was up, so a Nellis controller's plate carried FEET WET,
    # TSUTSNVATI and a leg over the Black Sea.
    from marshall.core import theatre as _t
    th = _t.current()
    if not th.legs or not th.waypoints:
        return []
    legs = R.solve_route(legs=list(th.legs))
    line = ", ".join(f"**{n}** {f.name}" for n, f in th.waypoints)
    detail = "; ".join(
        f"{R.steerpoint(l.frm)} to {R.steerpoint(l.to)}, "
        f"{l.heading_mag:03.0f} at {l.distance_nm:.0f} nm" for l in legs)
    return [
        f"- **Today's filed route** (the squadron's, not every aircraft's): "
        f"{line}. Legs: {detail}.",
        "- **Use the NUMBERS on the radio.** \"Report steerpoint two\" "
        "survives a bad channel and a worse accent; \"report FEET WET\" "
        "arrives as \"fee twet\", and TSUTSNVATI has no chance at all. The "
        "names are for the chart he is reading, the numbers for the radio he "
        "is listening to.",
        "- He may not be flying it. Ask what he wants rather than assuming he "
        "is on the frag — a pilot who has never mentioned it is just an "
        "aeroplane going somewhere.",
    ]


def _threats() -> list[str]:
    """What is shooting, and how far it reaches.

    The controller has radar and the pilot has a chart, and only one of them can
    see where the aeroplane actually is relative to a battery. A pilot asking to
    be kept clear of Kutaisi is asking a reasonable thing; without this the
    controller has never heard of Kutaisi's guns and says something reassuring
    and useless.
    """
    # THEATRE DATA, not a module constant. `R.DEFENDED` exists whatever map is
    # loaded, so a Nevada plate briefed the Nellis controller on Kutaisi's
    # anti-aircraft guns -- in the one document he is told to believe.
    from marshall.core import theatre as _t
    defended = _t.current().defended
    if not defended:
        return []
    fields = "; ".join(f"**{n}** ({r:.0f} nm)" for n, _, _, r in defended)
    return [
        f"- **Defended enemy fields**: {fields}. Heavy anti-aircraft guns that "
        "reach well above transit altitude. Everything outside Batumi is "
        "hostile, and these three are the ones that shoot back.",
        "- **Keep him clear of them, and say so when you do.** If his track is "
        "closing on one, turn him — \"come left twenty degrees, you are "
        "closing on the Kutaisi defences\" — and if he asks to be routed round "
        "them, do it. You can see his position against them; he is looking at a "
        "chart and guessing.",
    ]


def plate(profile: R.ApproachProfile,
          flight: str = R.FLIGHT_CALLSIGN,
          size: int = R.FLIGHT_SIZE) -> str:
    """The field-specific facts, as the procedure being flown decides them.

    THE PROCEDURE IS REQUIRED, and it used to default to `R.BATUMI_ASR`. A
    default argument is evaluated at `def` time -- at module IMPORT -- and
    `route.__getattr__` resolves that name against the configured theatre, so
    the map was chosen before anybody had chosen it:

        MARSHALL_THEATRE=nevada  import marshall.atc.briefing
          -> AttributeError: BATUMI_ASR names approach 'batumi-asr', which the
             configured theatre does not publish.

    `agent_atc.load_and_push_plate` imports this module unguarded and `_run_srs`
    calls it unguarded, so THE SRS BRIDGE -- the live ATC -- died during
    start-up on the second map. Not a wrong number: no controller at all.

    `core/route.py:126-138` had already written the lesson down, about a
    different function, in its own docstring: "a default argument is bound at
    import, which on a theatre that is chosen by environment is a fact captured
    before anybody has chosen." It was not applied one file over.

    There is no sensible default here anyway. Which approach is being flown is
    a fact about a CLEARANCE -- `flights.cleared_approach` is the column that
    holds it -- and a caller who has not got one is not asking for the Batumi
    surveillance approach, he is asking a question with no answer. [#162]

    THREE PROCEDURES, THREE BRIEFINGS, and the difference is WHO NAVIGATES.

        surveillance   the CONTROLLER navigates. Headings, ranges every mile,
                       no glidepath, and the pilot has no aid of his own.
        beacon letdown the PILOT navigates, homing a beacon round a published
                       pattern, and the controller separates him.
        ILS            the pilot navigates, on his own aid, down a glidepath
                       the controller cannot see and must never call.

    An ILS used to be given the beacon letdown's briefing, which describes
    station passage and legs the pilot is not flying -- and on Nevada it also
    dereferenced an `arrival_fix` that does not exist and killed the bridge on
    startup.

    ONE PROCEDURE. `plates` is what the live controller is given, because he
    works whatever each aeroplane has been CLEARED for and not whatever the
    process was started on. This stays for the tools that render a single
    plate on purpose -- `python -m marshall.atc.briefing batumi-ils-13`, the
    sweep, the tests -- where the caller has named one.
    """
    return "\n".join([PLATE_HEADING, "",
                      *_procedure_lines(profile),
                      *_theatre_lines(flight, size, profile)])


PLATE_HEADING = "# This mission's plate (the field-specific facts)"


def _procedure_lines(profile: R.ApproachProfile) -> list[str]:
    """Which of the three briefings this procedure gets. Nothing shared."""
    if getattr(profile, "vectored", False):
        return _asr_lines(profile)
    if (getattr(profile, "guidance", "") or "").lower() == "intercept":
        return _ils_lines(profile)
    return _ndb_lines(profile)


def _theatre_lines(flight: str, size: int,
                   profile: R.ApproachProfile | None = None) -> list[str]:
    """The facts every procedure on this map shares, said once.

    THE SEATS ARE THE FIRST OF THEM and they used to be written into each
    renderer separately. A seat belongs to an aerodrome, and the aerodrome does
    not change when another approach is loaded -- which is why the station
    table came off the profile in the first place (#162). So do the departure
    field, today's sortie, and what is shooting at it: none of them is a
    property of the arrival anybody has been cleared for.

    `profile` is only the ladder in the formation paragraph, and `None` is a
    real answer rather than a missing one: `plates` describes several
    procedures at once and their stacks differ, so the break-up rule names the
    procedure's own levels instead of one procedure's numbers.
    """
    stations = "; ".join(f"**{s.name} {freq_text(s.freq_mhz)}**"
                         for s in R.STATIONS)
    return [
        f"- Controllers: {stations}.",
        *_departure_field(),
        *_mission(),
        *_sortie(),
        *_threats(),
        *_formation(flight, size, profile),
    ]


def plates(procedures,
           flight: str = R.FLIGHT_CALLSIGN,
           size: int = R.FLIGHT_SIZE) -> str:
    """EVERY procedure this map publishes, as the one 'plate' prompt part.

    This is the half of #162 that the deletions on their own would have broken.
    A controller was handed the plate for the arrival the process was started
    with, so the radio could work exactly one approach: ask it for anything
    else and it had the numbers for a different procedure, all of them real and
    all of them wrong.

        "make sure that the radio/srs is completely flexible to work any
         approach"

    It is when it has been briefed on all of them. A field OFFERS a set and
    Approach issues one to one aeroplane, which is the shape everything else
    already had -- `flights.cleared_approach`, `Controller._pro(ac)`, the
    stack keyed per procedure. The prompt was the last thing still holding a
    singular.

    IT IS NOT FOUR TIMES THE TOKENS. Roughly half of a plate was never about
    the procedure at all -- the seats, the departure field, today's tasking,
    the filed route, what shoots -- and those are said once here for the map
    rather than once per renderer. Four Caucasus procedures cost about twice
    one plate, not four times.

    TAKES THE KEYED MAPPING `theatre.approaches_now()` returns, because the key
    is not on the profile: a procedure does not know what it is filed as, and
    reconstructing `<field>-<kind>-<runway>` here would be a second copy of
    `agent_atc._key_of` in a module that has no business deriving one.

    Ordered by key so two runs of the same map produce the same bytes; a
    prompt that reshuffles itself is one nobody can diff.
    """
    out = [PLATE_HEADING, "", *_theatre_lines(flight, size)]
    for key, p in sorted(dict(procedures).items()):
        # NAMED BY ITS KEY, because that is what a clearance says and what
        # `flights.cleared_approach` stores. A section headed "ILS runway 13"
        # is unambiguous to read and ambiguous to LOOK UP the moment a field
        # publishes an approach to the other end -- which is #165's whole
        # finding, one axis over.
        out += ["", f"## Cleared for `{key}` — "
                    f"{(p.kind or '').upper()} runway {p.runway or 'in use'} "
                    f"at {p.aerodrome.name}", ""]
        out += _procedure_lines(p)
    return "\n".join(out)


def _ils_lines(profile: R.ApproachProfile) -> list[str]:
    """The facts for an instrument approach the PILOT flies. THIS ONE ONLY.

    What the controller owns here is small and it matters that he knows it is
    small: get the aeroplane onto the localiser at a sensible altitude and
    range, clear him, and give him to Tower. Everything after that is the
    pilot's, and the commonest way to get an ILS wrong is to keep talking.
    """
    from marshall.core import theatre as _t
    th = _t.current()
    rwy = profile.runway or "in use"
    inbound = profile.final_crs
    dh = profile.mda_ft - profile.field_elev_ft
    return [
        f"- This is an **ILS** to runway **{rwy}** at "
        f"**{profile.aerodrome.name}**. "
        "**He** navigates. You vector him to intercept, clear him, and hand him "
        "to Tower — the approach itself is his.",
        f"- Final approach course **{inbound:03d}**. Vector to intercept it by "
        f"**{profile.final_intercept_nm:.0f} miles**, at or above "
        f"**{profile.platform_ft}** until established.",
        f"- **Decision height {profile.mda_ft}** ({dh} ft above the field). "
        "That is HIS number, not a level you assign — do not read it to him as "
        "an instruction.",
        f"- Missed approach: climbing **{profile.missed_turn}** turn to "
        f"**{profile.missed_ft}**, re-sequence.",
        "- **There are no mile calls on an ILS.** He has a localiser and a "
        "glidepath and is flying both; ranges every mile are the surveillance "
        "approach's job and here they are chatter over a busy man. Say nothing "
        "between the clearance and his report.",
        "- **Never call the glidepath.** You cannot see it. \"On glidepath\" "
        "and \"above glidepath\" are radar-approach phrases and asserting one "
        "here is inventing an instrument reading.",
        "- **He reports established**, and that is what hands him to Tower. Ask "
        "for it once with the clearance and then wait.",
        f"- **Altimeter {_setting(profile)}** ({profile.altimeter_datum}) — pass "
        "it when you call radar contact, and to anyone who asks. Every height "
        "you read him is measured against this datum.",
        f"- Wind **{int(th.wind_from_deg):03d} at {int(th.wind_mph)}**, "
        "**briefed** — what the mission was built with, not what is blowing. "
        "The wind you SAY is the measured one and arrives with the landing "
        "clearance, where it tells him what to expect in the flare — never as "
        "a correction while vectoring, and never recalled from here.",
        f"- Assignable altitudes: **{profile.platform_ft}** vectoring, "
        f"**{profile.missed_ft}** missed, and the holding stack "
        f"**{profile.stack_ft[0]}** and up. Nothing else.",
    ]


def _ndb_lines(profile: R.ApproachProfile) -> list[str]:
    """The 1944 beacon letdown. THIS PROCEDURE ONLY.

    The formation paragraph used to sit in the middle of this list, between the
    wind and the assignable levels, because this renderer predates the shared
    helpers the other two grew. It is a theatre fact rather than a procedure's
    and is said once for the map now, so the bullets a controller is given are
    the same set in a different order. [#162]
    """
    cap = profile.atc
    b = profile.navaid
    inbound = _inbound_hdg(profile)
    outbound = (inbound + 180) % 360
    hold, platform = profile.stack_ft[0], profile.platform_ft
    mda, missed = profile.mda_ft, profile.missed_ft
    rwy = profile.runway or "in use"

    return [
        f"- Controller **{profile.controller}**, recovering to runway **{rwy}**.",
        f"- Beacon **{b.name}**, **{freq_text(b.freq_mhz)}**, Morse ident "
        f"**{_phonetic(b.ident)}** — the pilot homes it.",
        *_channels(profile),
        *_own_seats(profile),
        f"- Capability: radar **{'ON' if cap.radar else 'OFF'}**, "
        f"aircraft DME **{'yes' if cap.dme else 'NO'}**, "
        f"separation **{cap.separation}**, era **{cap.era}**.",
        "",
        "The letdown, in order — never skip a leg:",
        f"1. Inbound to the beacon: home it, descend and maintain **{hold}**.",
        "2. Station passage (crossing the beacon) begins the approach.",
        f"3. Outbound heading **{outbound:03d}** for the procedure turn, descend "
        f"to platform **{platform}**. The outbound leg runs about two minutes.",
        f"4. Procedure turn, back inbound on the beam heading **{inbound:03d}**.",
        f"5. Down the beam to **MDA {mda}**. Runway in sight → land {rwy}; not in "
        f"sight → missed.",
        f"- Missed approach: climbing **{profile.missed_turn}** turn to "
        f"**{missed}**, back to the beacon, re-sequence.",
        f"- Timing: about **{_mmss(profile.final_approach_sec)}** from established "
        "inbound to the threshold — flown on a watch (no cone of silence).",
        f"- Wind **{int(R.WIND_FROM_DEG):03d} at {int(R.WIND_MPH)}** briefed — "
        f"expect a tailwind float on {rwy}; plant it early. The wind you say on "
        f"the air is the ATIS's.",
        f"- Assignable levels: holding **{', '.join(str(f) for f in profile.stack_ft)}** "
        f"(bottom first), platform **{platform}**, MDA **{mda}**, missed "
        f"**{missed}** — and headings **{outbound:03d} out / {inbound:03d} in**. "
        "Nothing else.",
    ]


if __name__ == "__main__":
    # NAMED, not defaulted. This is the demo that used to be the reason `plate`
    # had a default argument at all, and one convenience import-bound a fact
    # for every caller in the process. It asks the configured map instead, and
    # says what that map publishes when asked for something it has not got.
    import sys as _sys

    from marshall.core import theatre as _t

    _pubs = _t.approaches_now()
    # NO ARGUMENT MEANS ALL OF THEM, which is what the live controller is
    # given. It used to fall back to `current().approach_key` -- the process's
    # one arrival -- so the demo showed whichever procedure the shell had
    # chosen and there was no way to see the others without knowing to ask.
    if len(_sys.argv) <= 1:
        print(plates(_pubs))
        raise SystemExit(0)
    _key = _sys.argv[1]
    if _key not in _pubs:
        raise SystemExit(f"{_t.current().name} publishes {sorted(_pubs)}, "
                         f"not {_key!r}")
    print(plate(_pubs[_key]))
