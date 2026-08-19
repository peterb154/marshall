"""Who has him next, and when. Rules as data, because more controllers are coming.

    "Don't hard code these rules too much yet, because we haven't added
     clearance delivery or ground yet. Those will be different controllers with
     different handoffs."

WHAT THIS REPLACES. `handoff_on_the_event` was a hardcoded pair:

    on the ground and I am approach  -> tower
    airborne and I am tower          -> approach

Two roles, two branches. Add clearance delivery, ground, departure and center
and that is a matrix living in an if-chain, with every field wanting different
numbers -- which is the shape of a thing that should have been a table since the
second controller.

So: the RULE is code and the NUMBER is data, the same split `STRUCTURE.md`
draws for procedures. A new controller adds rows. Only a genuinely new KIND of
condition adds a predicate.

RANGE ALONE IS AMBIGUOUS, and this is why the conditions are named for the
event rather than the distance. Five miles outbound climbing and five miles
inbound descending are the same range and opposite situations; a bare
`at_5nm` rule would hand a departing aircraft straight back to Tower. So
`outbound_beyond` and `inbound_within` are separate conditions, and each reads
the trend as well as the distance.

The module said that from the beginning and one of its own conditions did not
obey it: `airborne_beyond` checked the range and not the trend, and got away
with it because the only rule using it was tower -> departure, where an arrival
is rarely still on Tower's frequency. It is `outbound_beyond` now. A principle
stated in a docstring is not enforced by the docstring.

THERE IS ONE TABLE, and there used to be two. `route.handoff_from` answered
this same question for the receive path while these rules answered it for the
proactive monitor, and they were not duplicates -- they were complementary
halves, each missing what the other had. Which rules applied therefore depended
on whether the pilot happened to key the mic. A live sortie was held by Center
at 44 nm with nothing able to move him on, because the only rule that could was
in the half the monitor does not read; he declared an emergency to get out of
it. `handoff_from` is deleted. [#51]

A CONDITION MAY CONSULT THE PROCEDURE, not just the geometry -- it is handed
the profile and its own rule. That is what lets "a talkdown makes landing the
trigger rather than a distance" live here rather than as an `if` at one call
site, which is how the split started.

A STATION IS WHO HAS HIM; A ROLE IS WHAT HE IS CALLED.

    "Batumi Approach and Batumi Departure would always run on the same frequency
     (even at busy airports like Nellis) and they are synonyms for each other."

So a "handoff" whose target resolves to the SAME station is not a handoff. The
man does not change, the frequency does not change, and telling a pilot to
contact the person he is already talking to is nonsense on the radio. What
changes is what that controller answers as -- Departure while you are going out,
Approach while you are coming back -- which `Station.also` already models and
nothing was reading. See `due`, which returns that case separately.
"""

from __future__ import annotations

from dataclasses import dataclass

from marshall.atc import phases as _phases
from marshall.core import airspace as _airspace
from marshall.core import route as _route

# How far out he must be before Tower is finished with him, and how close before
# Approach gives him back. Defaults, in nautical miles.
#
# THESE BELONG TO THE FIELD, not to this module -- Kobuleti may want eight and a
# fighter base may want fifteen. They are arguments with defaults until the
# airfield table exists (see SCHEMA.md), and the day it does they become a
# column and this comment becomes wrong, which is the point of writing it here.
DEPARTURE_NM = 5.0
ARRIVAL_NM = 5.0
# Where Center gives him to Approach. Bigger than the others by an order of
# magnitude because it is a different kind of boundary: the others are circuit
# distances and this is the edge of the terminal area.
#
# It lived on the profile as `approach_hands_over_nm` and was read by a SECOND
# handoff mechanism -- see the module docstring on why there is only one now.
#
# AND IT IS THE SAME NUMBER AS THE EDGE OF APPROACH'S VOLUME, so it is imported
# rather than restated. They are two statements of one boundary -- this one in
# procedure, that one in geography -- and holding them separately is one edit
# away from a ladder that hands a man over at twenty-five miles into airspace
# that stops at twenty. Procedure may read geography; the reverse would put a
# rule table underneath a map. See LAYERS.md and `core.airspace.TERMINAL_NM`.
CENTER_NM = _airspace.TERMINAL_NM


@dataclass(frozen=True)
class Rule:
    """One controller finishing with an aircraft, and who gets him.

    `when` names a condition rather than describing a distance, because the
    distance is the parameter and the situation is the rule.
    """
    frm: str            # the role he is with now
    to: str             # the role that should have him
    when: str           # a name from CONDITIONS below
    nm: float | None = None
    # IS `nm` THE EDGE OF THE TERMINAL AREA, or a distance of its own?
    #
    # A circuit distance is a circuit distance -- five miles is five miles at
    # every aerodrome on every map. The terminal boundary is not: it is derived
    # from the procedures the field publishes, so Batumi's is 27.5 and
    # Kobuleti's 28.8 while the constant says 25.
    #
    # Without this the rows below carried a number the map did not draw, which
    # is exactly what `CENTER_NM`'s own comment warns against two screens up.
    # `nm` stays the fallback for a field nothing can be derived for. [#130]
    terminal_edge: bool = False


# THE ORDER IS THE PRIORITY. First rule whose condition holds, wins -- so a
# specific case can be put above a general one without either knowing about the
# other.
RULES: tuple[Rule, ...] = (
    # Outbound. Tower keeps him until he is clear of the circuit.
    #
    # A GO-AROUND FIRST, because it is the more specific case and the order is
    # the priority. Same range, same shape -- climbing away from the runway --
    # and a different destination: he has already flown an approach, so he goes
    # back to Approach to be sequenced rather than on to Departure. [#200]
    Rule("tower", "approach", "going_around_beyond", DEPARTURE_NM),
    Rule("tower", "departure", "outbound_beyond", DEPARTURE_NM),
    # ENROUTE TO TERMINAL. Center gives him up at the edge of the area.
    #
    # THIS ROW IS THE BUG. It existed only in `route.handoff_from`, which is
    # consulted when the pilot TRANSMITS -- so the proactive monitor, which is
    # what hands everybody else over unprompted, could never move anyone off
    # Center at all. A live sortie sat at 44 nm being told to continue holding,
    # nineteen miles outside the airspace Approach would have taken him in,
    # with no mechanism in the system that could have helped him. He declared
    # an emergency. [#51]
    Rule("center", "approach", "inbound_within", CENTER_NM,
         terminal_edge=True),
    # AND THE MIRROR OF IT, which only became visible once the ladder could be
    # read end to end in one place. Nothing handed a DEPARTURE to Center, so a
    # jet leaving Kobuleti stayed with Kobuleti Departure to the far side of
    # the map while the comms card told him preset 4 was for the enroute leg.
    # The same fault as the missing Center row and in the same table -- found
    # by printing the ladder rather than by anybody flying it.
    Rule("departure", "center", "outbound_beyond", CENTER_NM,
         terminal_edge=True),
    # Inbound. Approach hands him over when the runway is his problem.
    Rule("approach", "tower", "inbound_within", ARRIVAL_NM),
    # On the ground under a radar controller at all is a mistake to correct --
    # he has landed and nobody noticed, or he never left. Either way Tower.
    Rule("approach", "tower", "on_ground"),
    Rule("departure", "tower", "on_ground"),
    # AND THE MIRROR: AN AIRBORNE AEROPLANE IS NEVER GROUND'S.
    #
    #     "Yes, an airborne airplane is never ground's. Just have tower take
    #      him back if he's flying - even if he already said welcome go to
    #      ground"
    #
    # These rows exist because `report_down` now names Ground in the roll-out
    # transmission (#77), which is right, and which makes a TOUCH-AND-GO worse
    # than it was. The poll runs every four seconds against a ten to twenty
    # second roll, so it fires: he is told to call Ground, put on `taxi_in` --
    # and then he flies. Nothing could retrieve him. `handoff_on_the_event`
    # covers only approach and tower, `phases.derive` refuses `taxi_in ->
    # landed`, and there was no row out of a ground seat at all, so he sat on
    # Ground's frequency, airborne, with only the airspace volumes able to move
    # him.
    #
    # Written as an INVARIANT rather than as a touch-and-go case, deliberately.
    # Stated as "an airborne aeroplane is never Ground's" it also catches the
    # go-around that happens after the goodbye, and the aeroplane that gets
    # airborne off a taxiway with no take-off clearance at all -- neither of
    # which anybody would have thought to write a special case for.
    #
    # Tower, not Departure: the man who just left the runway is the runway
    # controller's until he is clear of the circuit, and the tower->departure
    # row above then does its normal job. A touch-and-go REQUEST is a thing to
    # ask Tower for one day; this is only the retrieval.
    Rule("ground", "tower", "airborne"),
    Rule("clearance", "tower", "airborne"),
    # THE GROUND TRANSITIONS ARE NOT ROWS, and that is the design rather than
    # an omission. These two used to be listed here as deliberately-absent:
    #
    #   clearance -> ground   when the clearance has been read back
    #   ground    -> tower    when he is holding short
    #
    # Neither is a distance. Two aircraft parked side by side, one waiting for
    # a clearance and one waiting for the runway, are the same range and the
    # same direction and belong to different controllers -- so writing them as
    # geometry would be inventing a measurement that does not exist.
    #
    # They are handled by PHASE OWNERSHIP in `due` instead: a phase with no
    # geometry is owned outright by the controller the phase table names, and
    # moving into it IS the handoff. That is what `phases.py` said this design
    # was for. It also means the next ground procedure -- pushback, de-icing,
    # progressive taxi -- needs a phase and no row at all.
)


def _outbound_beyond(st, nm: float | None, profile=None, rule=None) -> bool:
    """Far out AND going further. The trend, for the same reason as arrivals.

    THIS USED TO BE `airborne_beyond` AND IGNORED THE DIRECTION, which broke
    the rule this module's own docstring opens with: five miles outbound
    climbing and five miles inbound descending are the same range and opposite
    situations.

    It survived because the only rule using it was tower -> departure, and an
    arrival is rarely still on Tower's frequency at six miles. Adding
    departure -> center made it reachable immediately: an aeroplane twenty-five
    miles out INBOUND, being worked by Approach -- who also wears the departure
    hat -- matched "airborne beyond twenty-five" and was handed to Center, away
    from the field he was arriving at.

    Caught by a test that had been passing for weeks, on a rule I had just
    added. The condition was wrong the whole time; nothing had asked it the
    question from the other side.
    """
    return bool(not st.on_ground and not st.inbound and st.range_nm is not None
                and nm is not None and st.range_nm >= nm)


def _inbound_within(st, nm: float | None, profile=None, rule=None) -> bool:
    """Close AND getting closer. The trend is what makes it an arrival.

    Without it this fires on a departure at the same range, and a climbing
    aeroplane gets handed to Tower on his way out.

    A TALKDOWN KEEPS HIM TO THE GROUND, and that rule used to live as an `if`
    in the bridge's receive path, which meant only half the system obeyed it:

        "Real practice keeps him: the final controller obtains the landing
         clearance from Tower and relays it, and the pilot never changes
         frequency inside the final."

    On a surveillance approach the controller IS the approach aid -- he reads
    the range every mile and corrects the heading -- so handing him to Tower at
    five miles abandons the pilot at the moment the procedure starts. It did,
    live, at ten miles in cloud.

    The guard was written in the bridge because `handoff_from` had no idea
    whether the aeroplane was inbound, on the ground, or going around, and
    blocking the whole transition was the only tool available. Here there is
    `on_ground` -- so the talkdown does not suppress the handoff, it just makes
    LANDING the trigger instead of a distance, which is what it always was.
    """
    if (profile is not None
            and getattr(rule, "to", "") == "tower"
            and getattr(profile, "guidance", "") == "talkdown"
            and not st.on_ground):
        return False
    return bool(not st.on_ground and st.range_nm is not None
                and nm is not None and st.range_nm <= nm and st.inbound)


def _on_ground(st, nm: float | None, profile=None, rule=None) -> bool:
    return bool(st.on_ground)


def _airborne(st, nm: float | None, profile=None, rule=None) -> bool:
    """He is flying, POSITIVELY -- not merely "not known to be down".

    `not on_ground` is the wrong test and there is a scar for it: an aircraft
    radar has stopped seeing answers False to `on_ground` -- no unit, no
    position, so the geometry fallback is false too -- and reading that as
    "airborne" put an aeroplane which had LEFT THE WORLD onto the board as
    flying. Here the same mistake would tear a parked aeroplane off Ground
    every time his track went quiet.

    So it requires radar to actually have him: a range means the scope holds a
    contact. Same guard `_outbound_beyond` uses, for the same reason. "We
    cannot tell" leaves him exactly where he is, which is the answer a
    controller would give.
    """
    return bool(not st.on_ground and st.range_nm is not None)


def _going_around_beyond(st, nm: float | None, profile=None,
                         rule=None) -> bool:
    """Climbing away after an approach, and far enough out to hand back.

    THE SAME RANGE AS A DEPARTURE, and that is the point:

        "I don't see why the handoff to departure is any different on a go
         around. Still use the 5nm airspace rule right?"

    Right. A go-around and a departure are the same shape -- an aeroplane
    climbing away from the runway -- and Tower keeps both until they are clear
    of the circuit. What differs is only WHO gets him: a departure goes to
    Departure, a man who has just missed goes back to Approach to be sequenced
    again.

    That was decided by the sim-EVENT branch instead, which fired the moment he
    was airborne, at any range, and could not tell a go-around from a departure
    or from a roll-out (#200). Expressed as a rule it is one mechanism, one
    range, and a row somebody can read.
    """
    return (st.phase or "").lower() == "missed" and _outbound_beyond(
        st, nm, profile, rule)


CONDITIONS = {
    "outbound_beyond": _outbound_beyond,
    "inbound_within": _inbound_within,
    "on_ground": _on_ground,
    "airborne": _airborne,
    "going_around_beyond": _going_around_beyond,
}

# THE PHASES THAT HAPPEN ON THE GROUND. `holding_short` is deliberately not
# here: he is stopped at the holding point and he is TOWER's, which is the
# whole reason the runway has one owner.
_GROUND_PHASES = ("clearance", "taxi", "taxi_in")

# ...AND THE SEATS THAT WORK THEM, DERIVED FROM THE PHASE TABLE.
#
# This was `("ground", "clearance")`, hand-written, under a comment saying
# "named once, because the invariant is enforced in two places and two lists
# would drift". It drifted anyway, through a spelling nobody had counted:
# `phases.clearance.owner` is **"delivery"**, not "clearance". `Station.also`
# carries both so every lookup worked, and the guard below asked
# `want in _GROUND_SEATS` -- which was False for "delivery".
#
# Measured: an aeroplane at eight thousand feet in the `clearance` phase was
# handed to Batumi Ground. The invariant is the pilot's own words --
#
#     "Yes, an airborne airplane is never ground's. Just have tower take him
#      back if he's flying"
#
# -- and it was enforced everywhere except through the one seat whose role has
# two names. Deriving the set from the phase table means a rename in `phases.py`
# carries here by construction; the two literals stay as a floor, because a
# theatre that staffs no delivery seat still has a Ground that cannot have a
# flying aeroplane. [#168]
_GROUND_SEATS = tuple(sorted(
    {_phases.owner_of(p) for p in _GROUND_PHASES} - {""} | {"ground", "clearance"}))


@dataclass(frozen=True)
class State:
    """What a rule is allowed to look at.

    Deliberately small. A condition that needs something not in here is a
    condition that wants a new fact published, and making that visible is worth
    more than the convenience of passing the whole world in.
    """
    on_ground: bool
    range_nm: float | None
    inbound: bool
    # WHAT HE IS DOING, which is how the ground half of the sortie is handed
    # over at all.
    #
    # Every rule above this is geometry: a range and a direction. That works in
    # the air and says nothing whatever on the ramp, where the transitions are
    # procedural -- his clearance was read back correctly, he reported holding
    # short -- and a distance cannot see any of it. Two aircraft parked side by
    # side, one waiting for a clearance and one waiting for the runway, are the
    # same range and the same direction and belong to different controllers.
    #
    # Empty means "not told", and everything falls back to the geometry, which
    # is what the airborne half has always done.
    phase: str = ""


def reach_of(field: str) -> float | None:
    """How far THIS aerodrome's terminal area goes, or None if unknowable.

    One number, authored by `core.airspace` and read here. Procedure may read
    geography; the reverse would put a rule table underneath a map, which is
    the direction LAYERS.md forbids.

    NONE IS A REAL ANSWER and the caller keeps its constant when it comes back.
    A field the theatre does not publish, a map still loading, a test that
    hand-builds a Station -- none of those are errors, and a boundary that
    collapsed to zero because a lookup missed would hand every aeroplane over
    the instant it left the ground.

    TRIED ONCE BEFORE AND REVERTED, on 13 August, and the difference is #139.
    Reading the map was right and the map was wrong: terminal areas were
    eleven-mile circles around approaches that begin at twenty-two, so
    `center -> approach` would have held an arrival until eleven miles, inside
    the final and later than the rule #51 exists to fix. The areas hold their
    own procedures now, so the same change is now the correct one.
    """
    if not field:
        return None
    try:
        from marshall.core import theatre as _t
        fields = list(_t.fields_now())
    except Exception:
        return None
    f = next((x for x in fields if x.name.lower() == field.lower()), None)
    if f is None:
        return None
    return _airspace.terminal_reach_nm(f, [o for o in fields if o is not f])


def _at(me, profile) -> str:
    """WHICH AERODROME THIS HANDOFF IS ABOUT, spelled as a Station spells it.

    His current controller's field, and where that controller has none, THE
    FIELD HE IS GOING TO. A role is unique only within an aerodrome, so every
    lookup below has to be qualified or it returns whichever seat is listed
    first -- a real controller at a real facility, forty or a hundred and
    twenty-four miles from the man who actually has him.

    `me.field` alone was the qualifier, and it is empty for exactly the seat
    that matters most. Center and Sentry are DELIBERATELY fieldless --
    `test_two_fields` asserts it and calls it correct, because owning a region
    is not owning an aerodrome -- so the one row this table exists for,

        Rule("center", "approach", "inbound_within", CENTER_NM)

    the row added after a pilot declared an emergency at 44 nm to get himself
    off Center (#51), was the one row asked with no field at all. Measured:

        inbound to TONOPAH at 20 nm  -> "contact Nellis Approach one one
                                         eight decimal one two five"

    Nellis is 124 nm away. He changes frequency and talks to nobody who can see
    him. On the Caucasus the same call sends a Kobuleti recovery to Batumi
    Approach, and it is invisible on the default sortie only because Batumi
    Approach is the sole seat whose PRIMARY role is `approach`, so first-match
    happens to be right.

    The destination was never missing -- `due` is handed the profile, and a
    procedure's `aerodrome` is the field it arrives at. It simply was not
    consulted.

    AND THE PROFILE MAY NOW BE NONE, which is what #162 made possible: `_pro`
    answers None for an aeroplane nobody has cleared, and that is the common
    case for a man on Center forty miles out who has not asked for anything.
    NOTHING IS INVENTED FOR HIM. The lookup goes back to being UNQUALIFIED,
    which still resolves -- `station_for("approach", field="")` returns the
    first seat with that primary role -- so

        Rule("center", "approach", "inbound_within", CENTER_NM)

    still fires and #51 does not come back. An unqualified answer that is right
    by first-match is a known, tested weakness with its own name in this
    docstring; a field guessed from the sortie's destination would be a
    CONFIDENT wrong answer on the day two aeroplanes recover at two fields,
    which is the failure this whole function exists to prevent. Guessing was
    tried here and reverted for exactly that reason; the two tests below pin
    it. See `test_a_handoff_names_the_field_he_is_going_to.py`.

    `field_named` is the join, and it is here because the two catalogues do not
    agree on case: a procedure's datum is a Fix and the fixes are shouted
    ('NELLIS', 'KOBULETI') while the aerodrome rows are not. An unknown name
    comes back as EMPTY rather than as itself, on purpose -- an unmatchable
    field resolves no role at all, and a handoff that never fires is #51 again
    rather than a safer version of it.
    """
    mine = getattr(me, "field", "")
    if mine:
        return mine
    fix = getattr(profile, "aerodrome", None)
    fld = _route.field_named(getattr(fix, "name", "") or "")
    return fld.name if fld is not None else ""


@dataclass(frozen=True)
class Verdict:
    """What should happen, and whether the pilot hears about it."""
    station: object          # the Station that should have him
    role: str                # what that station answers as now
    same_station: bool       # True -> no frequency change, no transmission
    # A RULE GOVERNS THIS AEROPLANE AND THE ANSWER IS "NOT YET".
    #
    # `due` used to return None for that, which is the same value it returns
    # when no rule applies at all -- so a DECISION and an ABSENCE OF OPINION
    # were the same answer, and `next_controller` reads the second as
    # permission for the airspace volumes to decide instead.
    #
    # 18 August: Tower handed a departure over at about a mile. The table says
    # five (`Rule("tower", "departure", "outbound_beyond", DEPARTURE_NM)`) and
    # it works -- below five it declined, `due` returned None, and
    # `leaving_my_airspace` treated the silence as its turn. Procedure lost to
    # geometry without either knowing the other had spoken.
    #
    #     "tower, switch me over to departure pretty quick, should be at five
    #      miles I think, just hit it off the end of the runway"
    #
    # This is `clearance_agreed is False` versus `None` (#181) one module over
    # and one day later: "I decided no" collapsed into "I don't know". A
    # deterministic engine that cannot say NOT YET has no way to hold a line.
    # [#189]
    keep: bool = False

    def __bool__(self) -> bool:
        return self.station is not None


def due(profile, me, st: State) -> Verdict | None:
    """Is a handoff due, and is it a real one?

    `me` is the station the pilot is CURRENTLY talking to -- from the frequency
    he checked in on, never from whichever channel a thread happens to transmit
    over. Reading the wrong one made every aircraft look like Approach's and the
    tower-to-departure rule could not fire for anybody.

    Returns None when nothing is due. Returns a Verdict with `same_station` set
    when the next role is covered by the man he already has: Approach and
    Departure are one person on one frequency, so that is a change of NAME and
    not of controller.
    """
    if me is None or not getattr(me, "role", ""):
        return None
    role = me.role
    # THE PHASE OWNS HIM, WHERE THERE IS NO GEOMETRY TO ARGUE WITH.
    #
    #     "This is what makes a handoff a consequence rather than a special
    #      case: the phase changes, the owner changes with it."
    #      -- phases.py, which declared this design before anything used it
    #
    # The ground half of a sortie has no distances in it. Clearance hands to
    # Ground when the clearance is read back; Ground hands to Tower when he is
    # holding short. Neither is a range, and writing them as ranges would be
    # inventing a geometry that is not there.
    #
    # So a phase whose `aims_at` is "none" -- clearance, taxi, holding short,
    # landed -- is owned OUTRIGHT by the controller the phase table names, and
    # moving into it IS the handoff. No row is needed, and adding a ground
    # procedure later needs no row either.
    #
    # Phases that DO aim at something (enroute, arrival, approach) are left to
    # the rules below, and must be: an arrival in `holding` is owned by
    # Approach the whole time, but he is Center's until twenty-five miles, and
    # phase-ownership alone would snatch him at any distance.
    if st.phase:
        want = _phases.owner_of(st.phase)
        aims = getattr(_phases.get(st.phase), "aims_at", "")
        # ...UNLESS HE IS FLYING. A phase owned by a ground seat cannot own an
        # airborne aeroplane, and outright ownership is exactly what would make
        # that stick: `taxi_in` aims at nothing, so without this the phase hands
        # a flying aircraft to Ground on every poll and the rule table below --
        # which now says an airborne aeroplane is Tower's -- is never consulted.
        #
        # This is the guard rather than a rule because the branch above it wins
        # by design. The invariant has to be stated in both places or it is not
        # an invariant, it is a row that something else outranks.
        if want in _GROUND_SEATS and _airborne(st, None):
            want = ""
        if want and aims == "none" and want != role \
                and want not in getattr(me, "also", ()):
            nxt = _route.station_for(want, field=_at(me, profile),
                                     procedure=profile)
            if nxt is not None:
                same = (getattr(nxt, "name", None) == getattr(me, "name", None))
                return Verdict(station=nxt, role=want, same_station=same)
    governed = False
    for rule in RULES:
        if rule.frm != role and rule.frm not in getattr(me, "also", ()):
            continue
        cond = CONDITIONS.get(rule.when)
        # The profile and the rule are passed so a condition can consult the
        # PROCEDURE as well as the geometry -- a talkdown makes landing the
        # trigger rather than a distance. Without them that rule has to live as
        # an `if` at one call site, which is how this ended up with two handoff
        # mechanisms that disagreed.
        # THE FIELD'S OWN BOUNDARY, where the rule is about one. `rule.nm` is
        # the fallback; `reach_of` is what the map actually drew.
        nm = rule.nm
        if rule.terminal_edge:
            nm = reach_of(_at(me, profile)) or rule.nm
        if cond is None or not cond(st, nm, profile, rule):
            # GOVERNED, BUT NOT YET. A rule for this seat exists and its
            # condition has not been met, which is an ANSWER -- see
            # `Verdict.keep`. Recorded rather than returned here, because a
            # later rule may still fire: `approach -> tower` has a distance
            # row and an `on_ground` row, and the first declining must not
            # stop the second being asked.
            governed = True
            continue
        # HIS FIELD, or the handoff crosses the theatre. A role is unique within
        # an aerodrome and not across one -- with Kobuleti and Batumi both on
        # the route there are two Towers and two Departures, and an unqualified
        # lookup returns whichever is listed first. That put a Kobuleti
        # departure on Batumi Departure's frequency, forty miles from the man
        # who actually had him, and nothing raised: both answers are a real
        # Station. See `station_for`, which is why it takes a field at all --
        # and `_at`, which is why the field is not always the seat's own.
        nxt = _route.station_for(rule.to, field=_at(me, profile),
                                 procedure=profile)
        if nxt is None:
            continue
        same = (getattr(nxt, "name", None) == getattr(me, "name", None))
        return Verdict(station=nxt, role=rule.to, same_station=same)
    # A RULE HAD AN OPINION AND IT WAS "NOT YET". Returning None here is what
    # let the airspace volumes overrule the table -- see `Verdict.keep`.
    if governed:
        # `same_station=True` DELIBERATELY: to every existing caller that
        # means "no frequency change, no transmission", which is precisely
        # what a rule saying not-yet amounts to. So nothing that unwraps a
        # Verdict has to learn about `keep` -- only the one place that must
        # stop asking the airspace, which is the whole point of the flag.
        return Verdict(station=None, role="", same_station=True, keep=True)
    return None
