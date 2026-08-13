"""An approach as DATA: the procedure, the geometry, and what the controller can do.

    "Real ATC by default. Handicaps are a per-mission AtcCapability you dial in."

`AtcCapability` is that dial. Its defaults describe a real, radar-equipped
modern controller; a 1944 beacon letdown sets `radar=False`, `dme=False` and
procedural separation, and everything downstream reads the capability rather
than checking which mission is loaded.

`ApproachProfile` is the procedure itself -- the fixes, the final approach
course, the minimums, the missed approach and the holding stack. THE PROFILE IS
THE SINGLE SOURCE FOR THE PROCEDURE: the mission builder, the kneeboard plate
and the controller all read the same one, so they cannot disagree about where
the final approach point is. It is not the source for anything else, and the
station list is the one that proved it -- see the class docstring.

It serialises to a plain dict for the database at the bottom of this file.
Properties recompute from the fields, so only the fields are stored.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

from marshall.core.airspace import msa_for, mva_for
from marshall.core.fields import (ARRIVAL_FIELD)
from marshall.core.fixes import Fix
from marshall.core.units import MAGVAR, MPH_PER_KT


@dataclass
class AtcCapability:
    """What the controller can DO on a given mission -- the dial between a real,
    capable controller and a period handicap.

    Defaults describe a REAL controller: it has radar, it separates on radar, it
    talks like a modern controller. A 1944-style mission dials the handicaps in
    (radar off, no DME, blind procedural separation, period phraseology) -- the
    Batumi beacon letdown is one such configured flavour, not the baseline. The
    bridge reads this to generate the agent's prompt and to decide whether to feed
    it a radar picture at all, so "handicap the ATC for this mission" is data here,
    not a prompt rewrite.
    """
    radar: bool = True          # sees aircraft positions -> can read range off a scope
    dme: bool = False           # the PILOT's aircraft carries DME (the P-51 doesn't)
    separation: str = "radar"   # "radar" | "procedural" (blind assigned-altitude stack)
    era: str = "modern"         # phraseology flavour: "modern" | "ww2"
    # WHETHER HE MAY VECTOR, which is NOT the same question as whether he has a
    # scope, and one flag was answering both.
    #
    # `BATUMI_APPROACH` is the 1944 beacon letdown and carries `radar=True` on
    # purpose -- "Radar ON (you wanted eyes)" -- because the controller reads
    # ranges off his own scope while the pilot, with no DME, flies the published
    # pattern himself. Seeing him and steering him are different things.
    #
    # Keying "does he vector?" on `radar` would therefore give a period letdown
    # radar phraseology: turning an aeroplane round a procedure the pilot is
    # flying on a beacon. `Controller._vectored` avoided it by naming the
    # PROCEDURE KINDS instead -- a workaround with a comment explaining itself,
    # which is how it survived since 2 August. [#53]
    #
    # None means "ask the procedure", which is the honest default: an ASR or an
    # ILS is vectored by construction and a beacon letdown is not. A profile
    # that wants to say otherwise now can.
    vectors: bool | None = None


def may_vector(profile) -> bool:
    """May this controller give headings at all?

    ONE QUESTION, ONE ANSWER, and it was being asked three different ways --
    `profile.vectored`, `profile.guidance`, and `AtcCapability.vectors` -- which
    disagreed. The beacon letdown carries `guidance="talkdown"` AND
    `vectored=False`, because the pilot is talked down a procedure he flies on
    his own homing adapter: a heading destroys his only reference, since the
    adapter points the nose at the beacon.

    The capability wins where it is stated (#53 added it for exactly this), and
    where it is not the procedure decides: a surveillance approach or an ILS is
    vectored by construction, a beacon letdown is not.

    Used by `Controller._vectored` and by the bridge's `asr_context`, because
    two implementations of this question is how an ILS came to receive no
    guidance at all while a beacon letdown nearly received headings.
    """
    cap = getattr(profile, "atc", None)
    want = getattr(cap, "vectors", None) if cap is not None else None
    if want is not None:
        return bool(want)
    if getattr(profile, "vectored", False):
        return True
    return (getattr(profile, "guidance", "") or "").lower() == "intercept"


def _round_up(value: int, step: int) -> int:
    return -(-int(value) // int(step)) * int(step)


@dataclass
class ApproachProfile:
    """One field's approach, in one place.

    WHAT IS ACTUALLY IN HERE, because this docstring used to claim the
    controller "reads the beacon, the controller name and the altitude ladder
    from here and nothing else" -- and that stopped being true the day a
    station table was added, which review kept believing anyway:

        the place       `aerodrome` -- the field this procedure arrives at, and
                        the datum every range, radial and plate is measured
                        from. Required. See #163: it used to be called `beacon`
        the fixes       homer (only where one is flown), outer hold, arrival
                        fix, IAF
        the geometry    final approach course, IF, FAP, MAP, glidepath, the
                        descent table, the missed approach, the touchdown offset
        the heights     platform, minima, MSA/MVA tables, the holding stack
        the speeds      pattern and approach, and the descent limit
        the capability  `atc: AtcCapability` -- what this controller may DO
        the paperwork   runway, plate, chart name, altimeter datum

    All of it is one PROCEDURE at one field, which is the test for whether
    something belongs here. `theatre_stations` is the one bit that looks like
    an exception and is not: it says how this procedure's controllers are
    REACHED, not who they are.

    WHAT IS NOT IN HERE, AND WHY IT MATTERS. The station table was, and it made
    this object the whole ATC world model: `station_for("tower")` on a Batumi
    arrival answered for Kobuleti Ground, so the comms ladder of both
    aerodromes was reached through one procedure. A station is a property of
    the THEATRE -- a role is unique only within an aerodrome, and neither the
    aerodrome nor the role changes because a different approach was loaded. Ask
    `theatre.station_for` / `theatre.station_on` (or `route.station_for`,
    `route.station_on`, which is the same thing through the façade). [#162]

    The plates read the same aerodrome and ladder plus the geometry they need
    to draw -- and the letdown's plate reads the same homer. Change a stack
    level here and both the clearances and the plate's table move together,
    because they share this one definition.
    """
    controller: str                 # radio callsign, e.g. "Batumi Approach"
    # THE AERODROME. Required, and it is the datum for everything positional:
    # the ranges the controller speaks, the IAF offset, the plates, the AIP
    # card. Every approach has one -- an approach is a way of arriving at an
    # AIRFIELD -- which is why it has no default and cannot be omitted.
    #
    #     "A beacon is not an airfield. They are separate things and you have
    #      built them as though they are. ... I think all approaches have an
    #      airfield. Not all approaches have a beacon."
    #
    # This slot used to be called `beacon` and held the fix named BATUMI, which
    # is the aerodrome reference point wearing an ident and a frequency that
    # `tools/import_beacons.py` says outright were invented for the period
    # scenario. So one field did three unrelated jobs -- a navaid the pilot
    # tunes, the geometric datum, and the origin a Center falls back to -- and
    # only the first is a beacon's. Both ILS approaches named a beacon and
    # NEITHER HAS ONE: an ILS is a localiser and a glideslope, and nobody homes
    # on the field. The row existed because the object needed a position and
    # `beacon` was the field that had one. [#163]
    aerodrome: Fix
    outer_hold: Fix                 # escape-valve fix for repeated misses
    # THE NAVAID THIS PROCEDURE HOMES ON, where there is one. None is the
    # normal case and is not a gap: an ILS and a surveillance approach have no
    # beacon at all, and the 1944 letdown has one because the whole procedure
    # is flown on it.
    #
    # It is a separate slot from `aerodrome` rather than the same one, because
    # a beacon and an airfield are different things in all three directions: an
    # approach always has a field, sometimes has a beacon, and a beacon exists
    # perfectly well with no approach attached -- 122 of them per map sit in
    # `[[navaid]]` rows that no procedure mentions.
    #
    # Named `homer` and not `beacon` for one reason, and it is a transitional
    # one: `beacon` is still a property below, kept alive for the call sites in
    # `atc/agent_atc.py` and `atc/controller.py` that this change was not
    # allowed to touch. See that property.
    homer: Fix | None = None

    # Where the flight is worked BEFORE it reaches the beacon. None means one
    # controller owns the whole arrival.
    #
    # This exists because of a hard constraint of the aircraft, not of ATC: a
    # WW2 set has four preset channels and the ARA-8 homes only on the frequency
    # it is tuned to. So the pilot cannot listen to a controller on one channel
    # while homing a beacon on another -- and therefore **a phase's controller
    # must live on the beacon flown in that phase**. Enroute to INITIAL he is on
    # INITIAL's frequency, so that is where Approach talks to him; the moment he
    # turns for the letdown he is homing BATUMI, so Tower owns him from there.
    # Getting this wrong is not cosmetic: it puts the controller on a channel the
    # pilot physically cannot be listening to.
    arrival_fix: Fix | None = None

    # The holding stack is GENERATED, not a fixed list. A stack is just 1,000-ft
    # increments from the base, and how many you need depends on who shows up --
    # a four-ship breaking up for individual approaches wants four levels on its
    # own. Hard-coding four made a formation break-up a capacity problem the
    # controller had to refuse, which is not a thing a real controller does; he
    # just stacks them higher. The only genuine ceiling here is OXYGEN: a P-51D
    # holding for a long recovery has no business above 10,000 ft.
    hold_base_ft: int = 4000        # bottom of the stack -- first arrival gets this
    # How thick the cloud is above the briefed base. Only needed to work out
    # where the tops are, and the tops are what decide whether a hold is
    # possible at all on a vectored approach -- see stack_ft.
    cloud_thickness_ft: int = 3000
    vmc_margin_ft: int = 1000       # clear air above the tops to hold in
    hold_step_ft: int = 1000        # vertical separation between holders
    hold_top_ft: int = 10000        # ceiling (P-51: oxygen, not airspace)

    # What this field's controller can do. Default is a real, radar-equipped
    # controller; set it per mission to handicap him (see AtcCapability).
    atc: AtcCapability = field(default_factory=AtcCapability)

    # --- surveillance-radar approach ------------------------------------
    # The controller navigates: he vectors the aircraft onto the final approach
    # course and talks it down to minimums, calling range each mile. Needs
    # nothing in the cockpit but a radio, so it works in any aeroplane -- unlike
    # the beacon letdown, which needs the ARA-8 and therefore a P-51D-30.
    kind: str = "ndb"               # "ndb" | "asr" | "ils" | "visual"

    # WHERE THE CONTROLLER STOPS. This is the only axis on which the approaches
    # we care about actually differ, and naming it is what stops the hardest one
    # becoming the shape the others have to fit.
    #
    # All three are the same job up to the intercept: sequence him, vector him
    # onto the final approach course, watch the ground track. Every bit of that
    # is geometry and none of it knows what kind of approach it serves. What
    # differs is who owns the aeroplane afterwards.
    #
    #   "talkdown"  the controller never stops -- he navigates the aircraft to
    #               the missed approach point, calling range every mile and
    #               reading advisory heights, because there is no glidepath and
    #               nothing in the cockpit to fly. This is the ASR, and it is
    #               the hardest of the three for the controller by a distance.
    #
    #   "intercept" the controller stops at the intercept. Once established the
    #               AIRCRAFT flies it -- localiser and glideslope -- and the
    #               controller's remaining job is to say so and get off the air.
    #               This is the ILS, and for the controller it is mostly
    #               sequencing. Calling ranges down an ILS is chatter over a
    #               pilot who is busy and already has better information.
    #
    #   "visual"    the controller stops when the pilot reports the field. Until
    #               then it is a vector towards a close base; after, it is the
    #               pilot's approach and the controller's spacing.
    #
    # The difference is three words, and the alternative -- an engine per
    # procedure -- is three copies of the geometry that will drift apart.
    guidance: str = "talkdown"
    # From the AIP plate. IF: established on the course, level, by 11 nm. FAP:
    # 6 nm, still 2,000 -- the descent begins HERE, not at the IF. The segment
    # between them is deliberately level, which is what makes the approach
    # flyable; a single gradient from the gate has him descending the whole way.
    final_intercept_nm: float = 11.0     # the IF -- established by here
    fap_nm: float = 6.0                  # descent begins
    map_nm: float = 0.6             # missed approach point, range from the TOUCHDOWN point
    # WHERE TOWER TAKES HIM, on any approach.
    #
    #     "Tower should handle inside a xx 2?? mile radius.. even on ASR
    #      approach."
    #
    # A number rather than a rule derived from the procedure, because it is a
    # fact about the FIELD -- whose airspace the last two miles are -- and not
    # about which aid the pilot is flying. See `hands_to_tower_nm`.
    # FIVE, not two. Two put the boundary inside the talkdown -- the controller
    # is still reading ranges every mile at two miles, so the pilot changes
    # frequency in the middle of the procedure flying his approach. Five is
    # about where real practice puts it (the final approach fix), and it leaves
    # the ASR question open rather than answering it badly:
    #
    #     "Let's do 5 nm then. We'll fix ASR approach later"
    tower_takes_nm: float = 5.0
    # How far the TOUCHDOWN POINT is from the reference the radar measures
    # against, along the approach course. Positive means the aircraft reaches
    # the touchdown point FIRST.
    #
    # It is not a nicety. The radar reference at Batumi is the runway CENTRE --
    # `Airbase:getRunways()` returns the centre and route.py's BATUMI fix is that
    # point to within a metre -- so every range call, and with it the whole
    # descent profile, was aimed half a mile beyond where the wheels go:
    #
    #     "I was always too high because he's trying to get me to zero at
    #      runway center point, not threshold."
    #
    # Half the runway length. Batumi's is 2,070 m, so 0.559 nm.
    touchdown_offset_nm: float = 0.0
    # GRID CONVERGENCE: how far the sim's idea of north is from true north here.
    #
    # DCS reports an aircraft's heading in its own x/z grid, which is a
    # transverse Mercator, while radar RADIALS come from lat/lon and are true.
    # Mixing them is what drew every centreline six degrees off. The radials
    # were fixed by putting the course in the true frame; this is the other
    # half, because a HEADING arrives in the grid frame too.
    #
    # Measured, like everything else here: the geodesic bearing between the two
    # runway thresholds is 311.30, and `getRunways().course` for the same runway
    # is 305.56.
    grid_convergence_deg: float = 0.0
    approach_hands_over_nm: float = 25.0   # Center gives him to Approach here
    # The initial approach fix: where he must be established, on course and at
    # iaf_alt_ft, before the approach proper begins. A published fix rather than
    # a computed one -- the vectoring used to aim at a "join point" it invented
    # and moved, which is how a pilot ended up being turned away from the field,
    # orbiting, and vectored out to sea on three separate sorties.
    iaf: Fix | None = None
    iaf_alt_ft: int = 2000
    # WHAT THE PLATE CALLS THE FINAL APPROACH FIX, because the controller must
    # say the words the pilot is reading.
    #
    #     "Lets not invent fix names that are not on the plate. That will be
    #      confusing... We need the plate the pilot is looking at to match what
    #      the controller says"
    #
    # The FAA clearance quotes position FROM A FIX -- the 'P' of PTAC, one of
    # the two elements a vectored approach clearance may never omit -- and the
    # obvious way to supply one is to make a name up. That is precisely wrong:
    # a pilot hearing a fix that is not on his chart has been given a reference
    # he cannot check, which is worse than being given none.
    #
    # THE REAL PLATES IN THIS THEATRE DO NOT NAME THEIRS. Batumi's AIP ILS
    # (AD 2.UGSB-IAC-12-ILSy, kneeboard/plates/ugsb-ils-12.png) labels its
    # fixes by FUNCTION and identifies them by DME:
    #
    #     IF    ILU D11.0 / BTM D11.9   2000'
    #     FAP   ILU D6.0  / BTM D6.9    2000'
    #
    # which is where `final_intercept_nm`, `fap_nm` and `platform_ft` came from
    # in the first place. So the fix has always existed and has always had a
    # name -- "the final approach point" -- and it is ICAO's word rather than
    # the FAA's "final approach fix", because it is a Georgian chart.
    #
    # A profile transcribed from a plate that DOES name its fixes should say so
    # here, and then the controller says that instead. One field, read by the
    # chart and by the controller, so they cannot disagree.
    faf_label: str = "the final approach point"
    # The glidepath, in degrees. Off the plate: Batumi's AIP ILS prints "GP 3.0"
    # in the profile view, which is the standard everywhere and is written down
    # rather than assumed because the clearance depends on it -- an aircraft may
    # only be cleared for the approach at an altitude NOT ABOVE the glideslope,
    # so a controller that does not know where the glideslope is cannot obey the
    # rule. See `talkdown.is_the_intercept`.
    glidepath_deg: float = 3.0
    # THE GLIDEPATH DOES NOT REACH THE GROUND AT THE THRESHOLD, and leaving this
    # out put it 260 ft low at six miles -- checked against the plate's own
    # descent table, which is the point of having one. "ILS RDH 51'" is printed
    # on AD 2.UGSB-IAC-12-ILSy in a box of its own: the reference datum height,
    # where the beam crosses the threshold. Every glidepath has one and they are
    # all about fifty feet, which is why it looks like a detail and is not.
    rdh_ft: int = 50

    def glidepath_ft_at(self, range_nm: float) -> float:
        """How high the glidepath is, this far out. Feet above sea level.

        Three corrections, and the plate's descent table checks all three at
        once -- at ILU D6.0 it publishes 2010 ft (1993 above the threshold), and
        that is the number to reproduce.

        Measured from the THRESHOLD, which is not where our ranges are measured
        from: they come off the field's beacon, and `touchdown_offset_nm` is the
        difference. Referenced to the THRESHOLD's elevation rather than the
        aerodrome's -- 17 ft here against 37. And offset by the reference datum
        height, because the beam crosses the threshold fifty-odd feet up rather
        than at the tarmac.
        """
        import math
        d = max(0.0, range_nm - self.touchdown_offset_nm)
        return (self.field_thr_elev_ft + self.rdh_ft
                + d * 6076.12 * math.tan(math.radians(self.glidepath_deg)))
    field_thr_elev_ft: int = 0   # runway threshold, which is lower than the ARP

    # The real published chart this profile is transcribed from, if we have it.
    # Scanned plate under kneeboard/plates/, and the chart's own name so a
    # disagreement can be traced back to a page of a real document. Optional:
    # a field with no scan still flies, it just has no scan on the kneeboard.
    plate_png: str = ""
    chart_name: str = ""

    # Which pressure datum this field works to, and therefore what every
    # altitude in this profile MEANS.
    #
    # "QNH" is sea-level pressure: set it and the altimeter reads elevation on
    # the ground, so the numbers are altitudes above the sea. "QFE" is field
    # pressure: the altimeter reads zero on the runway, so the numbers are
    # heights above the field. Ex-Soviet fields, Batumi among them, are worked
    # to QFE.
    #
    # At a 32-foot field the two settings differ by 0.03 inches and it looks
    # like pedantry. It is not: the DATUM decides whether "two thousand" means
    # two thousand above the sea or two thousand above the runway, and at a
    # field a few thousand feet up those are different places. Getting it wrong
    # is a whole approach flown at the wrong height.
    altimeter_datum: str = "QNH"

    # The plate's own descent table: (range_nm, altitude_ft), read straight off
    # the chart. Published data beats a computed gradient -- our derivation came
    # out at 315 ft per mile against the chart's 325, which is fifty feet by
    # short final, and there is no reason to be fifty feet out from a number
    # somebody already printed. It also settles what "3 degrees" is measured
    # from, which is the sort of thing a derivation quietly gets wrong.
    #
    # A field with no table falls back to the gradient joining its published
    # fixes, so this is an improvement where we have the chart and not a
    # requirement for having one.
    descent_table: list = field(default_factory=list)
    # Minimum safe altitude per quadrant around the field. Vectoring is done at
    # platform, and platform is only safe where the ground is low -- at Batumi
    # that is the sea to the north-west and nowhere else. A controller who
    # vectors on geometry alone will happily turn an aircraft over eleven
    # thousand feet of Caucasus at two thousand, which is exactly what a pilot
    # caught in flight: "he's going to fly me into the mountains here, if I were
    # IMC right now."
    msa_sectors: list = field(default_factory=list)
    mva_cells: list = field(default_factory=list)

    def min_safe_ft(self, bearing_deg: float,
                    range_nm: float | None = None) -> int:
        """The lowest altitude that may be ASSIGNED out on this bearing.

        The MVA, not the published MSA -- see the note on the two tables above.
        Never below platform, since platform is the approach's own floor.

        A profile carries its OWN tables and falls back down a ladder rather
        than borrowing: a surveyed MVA if it has one, otherwise the published
        MSA, which is conservative but safe, otherwise platform. Defaulting to
        the module's tables instead would hand a new field Batumi's mountains,
        and a field on flat ground would be vectored eleven thousand feet up
        for terrain a hundred miles away.
        """
        if self.mva_cells:
            return max(self.platform_ft,
                       mva_for(bearing_deg, range_nm, self.mva_cells))
        if self.msa_sectors:
            return max(self.platform_ft, msa_for(bearing_deg, self.msa_sectors))
        return self.platform_ft

    def briefed_msa_ft(self, bearing_deg: float) -> int:
        """The published figure, for the plate and for what the pilot is told."""
        return msa_for(bearing_deg, self.msa_sectors) if self.msa_sectors else 0
    # HOW THIS PROCEDURE'S CONTROLLERS ARE REACHED -- not who they are.
    #
    # True: the theatre's comms ladder, which is the normal case. Clearance,
    # Ground, Tower, Departure, Center, Approach; ask `theatre.station_for`.
    #
    # False: the beacons. On an ARA-8 the set homes whatever it is tuned to, so
    # the pilot cannot listen to a controller on one channel while homing a
    # beacon on another, and a phase's controller must therefore LIVE on the
    # beacon flown in that phase -- see `arrival_fix` above and `station`
    # below. That is a property of the aeroplane's radio and of the era, which
    # is why it is a bit on the procedure and not a list.
    #
    # It carried this meaning before as `stations == []`, which is #152: an
    # emptiness read as a statement about the era, in two places, and the
    # reason #140 cannot be fixed by data alone. Moving the table out (#162)
    # does not fix that -- it just stops the switch being invisible. The bit
    # keeps the same name the theatre file already uses for it.
    theatre_stations: bool = True
    # Magnetic variation at this field, degrees EAST. On the profile rather than
    # a module constant because it belongs to a PLACE: point route.py at another
    # theatre and the variation changes with it, and a controller who carries the
    # Caucasus figure to the Gulf draws every centreline wrong.
    #
    # Measured, not looked up: taxi an aeroplane onto the runway centreline,
    # stop at both ends, and take the bearing between the two fixes. Batumi's
    # 13 threshold measured 131.0 TRUE against a briefed 124 magnetic.
    magvar_deg: float = MAGVAR
    # The final approach course in TRUE, when somebody has actually MEASURED it.
    #
    # Deriving it from the briefed magnetic course plus the variation is a good
    # estimate and it is still an estimate: at Batumi it gives 130 where the
    # runway measures 131.0. One degree is 0.17 nm at ten miles, which is inside
    # the noise -- but the derivation is only as good as a variation figure
    # nobody has checked for this theatre and epoch, and this is the number every
    # cross-track in the system hangs off.
    #
    # None means "derive it". A figure here means somebody MEASURED it in the
    # sim -- and measured it well, which is a real caveat: the first attempt
    # took the bearing between two points an aeroplane stopped at, and came out
    # 5 degrees wrong because it had only covered 3,900 ft of an 8,000 ft runway
    # and 100 ft of lateral error over that baseline is 1.5 degrees. The F10
    # ruler and the aircraft's own radar heading while lined up agreed with each
    # other and not with it. Prefer those two.
    final_crs_true_measured: float | None = None

    @property
    def vectored(self) -> bool:
        """True when the CONTROLLER owns navigation.

        The two are mutually exclusive and must never be mixed: a homing adapter
        points the nose at the beacon, so a pilot handed a vector heading loses
        the only course reference he has. Either he navigates and we watch, or we
        navigate and he stops homing.
        """
        return self.kind == "asr"

    # Used only by the plate, not by ATC (it is blind and cannot see the field).
    # THE COURSE A CONTROLLER SAYS OUT LOUD, which is MAGNETIC, because that is
    # what the pilot reads off his compass and sets on his gyro.
    #
    # It is NOT the number the geometry may compute with. Radar reports position
    # and heading in TRUE, and comparing a magnetic course against a true bearing
    # draws the extended centreline in the wrong place -- by exactly the
    # variation, seven degrees here, which is 1.2 nm of cross-track at ten miles
    # and a quarter of a mile on short final. Use `final_crs_true` for anything
    # geometric. See `magvar_deg`.
    final_crs: int = 0              # inbound = runway heading, MAGNETIC
    hold_turns: str = "RIGHT"
    # The racetrack a holding aircraft flies when it has nothing to hold OVER.
    # Given as two headings because headings are the one thing every aeroplane
    # can fly, navaid or not. Aligned with the approach so that leaving the hold
    # points him roughly the right way; the inbound leg is the reciprocal.
    hold_outbound_hdg: int = 180
    # How long each leg of a timed hold takes, and which way he turns.
    #
    # An aeroplane with no navaid cannot hold OVER anything, so the hold is a
    # shape and a clock: fly this heading for this long, turn, fly the
    # reciprocal for this long, repeat. Without the clock he has a heading and
    # no idea when to turn, which is what he was being given.
    #
    # One minute is the standard leg at or below 14,000 ft, and it is the right
    # choice here for a reason beyond convention: it keeps him in a small piece
    # of sky. A two-minute leg at 200 knots is nearly seven miles of racetrack,
    # and the whole point of holding him is that the controller knows roughly
    # where he is. Put to the test pilot, who flies it: "1 min hold below 14k is
    # fine." Confirmed rather than assumed, which is the difference between a
    # default and a decision.
    #
    # Right turns, also standard, and also the safer default -- everybody in the
    # stack turning the same way keeps the pattern predictable when the only
    # thing separating them is altitude.
    hold_leg_minutes: float = 1.0
    hold_turns: str = "right"
    field_elev_ft: int = 0
    runway: str = ""

    # --- the letdown, no DME. -------------------------------------------
    # Cleared, you descend to the platform on the reversal (out over water),
    # then -- only while established on the beam (steady tone) -- down to MDA.
    # Station passage (the cone of silence over the field beacon) is the missed
    # approach point: no DME, no timing. Because the field is coastal and at sea
    # level, the altimeter reads a true height and there is nothing but water
    # under the whole approach, so MDA can sit low.
    platform_ft: int = 2000         # level here on the reversal before the beam
    # Pattern speed in MPH, because a WW2 USAAF airspeed indicator reads MPH and
    # the number the pilot flies has to be the number we brief. This was
    # `speed_kt = 240` and was divided into nautical miles as if it were knots,
    # which stretched every derived distance by 15% -- the same trap solve_route
    # already carries a comment about.
    speed_mph: int = 240
    # Approach speed. A separate number because the descent rate falls out of
    # it and nothing else, and it is bounded from BOTH ends. Too fast and the
    # path becomes a dive: 240 mph on three degrees is eleven hundred feet a
    # minute. Too slow and the aeroplane will not fly it -- a Mustang is unhappy
    # below about 130 and 150 is marginal, which is what an earlier value here
    # asked for. 200 is a speed the airframe is comfortable at, and it is also
    # about the floor for anything modern, so it generalises.
    final_speed_mph: int = 200
    descent_fpm: int = 500          # never steeper than this

    @property
    def speed_kt(self) -> float:
        """Pattern speed in knots -- i.e. nautical miles per hour, which is what
        every distance here is measured in."""
        return self.speed_mph / MPH_PER_KT

    @property
    def final_speed_kt(self) -> float:
        """Approach speed in knots, for the same reason."""
        return self.final_speed_mph / MPH_PER_KT

    def speed_kt_at(self, along_nm: float, established: bool = True) -> float:
        """The speed he should be doing this far down the approach.

        One place to ask, so the descent gradient, the mission's AI tasking and
        anything a controller says about speed cannot drift apart. The
        reduction is asked for a little before the final approach point rather
        than at it -- an aeroplane does not slow down instantly, and arriving at
        the point where the descent starts still doing pattern speed is how the
        descent becomes a dive.
        """
        # The reduction belongs at the INTERMEDIATE FIX, not at the point where
        # the descent starts. Two reasons, and the second is the one the sim
        # showed. Comfort first: a pilot who arrives at the final approach point
        # still doing pattern speed has to dive to stay on the path, and 240 mph
        # on a three degree gradient is eleven hundred feet a minute. But also,
        # decelerating and descending at once is asking for both at the expense
        # of each -- flown live, an aircraft told to slow two miles before the
        # point managed 478 fpm of the 690 the path wanted, and arrived six
        # hundred feet high. Slowing at the fix buys five level miles to settle,
        # so the descent starts from a stable aeroplane already at approach
        # speed and only has to do one thing.
        #
        # Inbound and actually ON the approach: along-track alone is not enough,
        # since an aircraft abeam the field four miles off the centreline has a
        # small along-track and is nowhere near final. Negative means past the
        # field, same answer.
        if established and 0 < along_nm <= self.final_intercept_nm:
            return self.final_speed_kt
        return self.speed_kt

    # MDA is not chosen freely: it must sit just below the briefed cloud base so
    # that levelling at minimums actually reveals the runway. Ceiling and MDA
    # move together -- the mission generator reads the same ceiling for weather.
    ceiling_ft: int = 400           # briefed cloud base for this mission
    breakout_ft: int = 100          # MDA this far below the ceiling
    # Never lower than the field plus this, whatever the weather says. The
    # figure is a property of the APPROACH TYPE, not of the field: how low you
    # may go depends on how precisely the procedure knows where you are.
    #
    # An ILS knows within feet and gets a decision height around 200. A
    # surveillance radar approach knows where you are to the width of a radar
    # return and has no vertical guidance at all -- the controller reads
    # advisory heights off a table and the pilot descends at his own rate -- so
    # its minima are far higher, five hundred feet at the very least and often
    # closer to a thousand.
    #
    # This mattered: the Batumi profile was transcribed from an ILS plate and
    # inherited its minima, so a radar approach was being flown to 300 feet.
    # That is below the chart's own obstacle clearance altitude of 687, on a
    # procedure with none of the ILS's precision.
    min_hat_ft: int = 150

    # Missed approach (Batumi real AIP: straight to 800', LEFT to 330', 3000').
    missed_straight_ft: int = 800
    missed_turn: str = "LEFT"
    missed_hdg: int = 330
    missed_climb_ft: int = 3000     # below the stack; ATC re-sequences from here

    @property
    def final_crs_true(self) -> float:
        """The final approach course as RADAR sees it.

        Everything geometric -- cross-track, along-track, intercept headings,
        "is he flying the approach" -- happens in true, because that is the
        frame the sim reports positions and headings in. Only the spoken number
        is magnetic.
        """
        if self.final_crs_true_measured is not None:
            return self.final_crs_true_measured % 360
        return (self.final_crs + self.magvar_deg) % 360

    @property
    def mda_ft(self) -> int:
        """Lowest he may go before the runway has to be in sight.

        The weather can only ever raise it. Briefing a low cloud base does not
        buy a lower minimum -- it just means he is more likely to go missed,
        which is the point of a hard mission.
        """
        return max(self.field_elev_ft + self.min_hat_ft,
                   self.ceiling_ft - self.breakout_ft)

    @property
    def missed_ft(self) -> int:     # what ATC assigns a go-around
        return self.missed_climb_ft

    @property
    def inbound_descent_nm(self) -> float:
        """Track needed to lose platform->MDA at the descent limit. The inbound
        beam must be at least this long or you cannot be down by station
        passage -- which is the plate's constraint on the racetrack size."""
        minutes = (self.platform_ft - self.mda_ft) / self.descent_fpm
        return self.speed_kt / 60 * minutes

    @property
    def final_approach_sec(self) -> float:
        """Seconds from established inbound on the beam to station passage -- the
        missed approach point. DCS produces no usable cone of silence, so the MAP
        is flown on a WATCH from beacon-inbound: the pilot times it (this goes on
        the plate) and ATC times the same number to call the missed as backup.
        One value, both readers, so the watch and the controller never disagree."""
        return self.inbound_descent_nm / self.speed_kt * 3600

    def station(self, enroute: bool = False, banished: bool = False) -> tuple[str, float]:
        """(controller name, frequency) for a phase of the arrival.

        Under radar this is an ordinary sector split -- Center has him enroute,
        Approach works him inbound, Tower takes the landing -- because a vectored
        pilot navigates by nothing and a frequency is free to be just a
        frequency.

        On a beacon letdown it is not free. The ARA-8 homes on whatever the set
        is tuned to, so the controller has to sit on the beacon being flown in
        that phase, and the "station" is derived from the fix instead. Which of
        the two this procedure is, is `theatre_stations` -- it used to be
        whether the profile's own station list happened to be empty (#152).
        """
        # THE SEATS ARE THE THEATRE'S. Imported here rather than at the top
        # because `theatre` reads `route`, which re-exports this module.
        from marshall.core import theatre as _th
        seats = _th.stations_now() if self.theatre_stations else ()
        if seats:
            # By ROLE, not by position in the list. Picking the last one was
            # fine while the list ended at Tower, and quietly wrong the moment a
            # mission commander was appended -- it would have sent a pilot to
            # land on the overlord's frequency. A list order is not a fact about
            # who works an arrival.
            # AT THE ARRIVAL FIELD, and the qualifier is not decoration.
            #
            # This method answers "who works this phase of the ARRIVAL", and
            # the arrival happens at one specific aerodrome. Unqualified, it
            # returns whichever Tower is listed first -- which became Kobuleti's
            # the moment the departure field got one, so a Batumi landing
            # clearance would have gone out on Kobuleti's frequency. `say` uses
            # this to choose the channel it transmits on, so the aeroplane on
            # short final would simply not have heard it.
            #
            # Same fault as `station_for` had, in a method that was missed
            # because it takes no role and so did not look like a lookup.
            fld = ARRIVAL_FIELD
            if enroute or banished:
                s = _th.station_for("center", field=fld) or seats[0]
            else:
                s = (_th.station_for("tower", field=fld)
                     or _th.station_for("approach", field=fld)
                     or seats[0])
            return s.name, s.freq_mhz
        if banished:
            fix = self.outer_hold
        elif enroute and self.arrival_fix is not None:
            fix = self.arrival_fix
        else:
            # THE HOMER, and the aerodrome only if there is none. A procedure
            # that reaches this branch is one whose controllers live on the
            # beacons rather than on the ladder, so it has a homer by
            # definition; the fallback is there so that a mis-configured
            # procedure gives its own controller on no frequency rather than
            # raising on a None halfway through an arrival.
            fix = self.homer or self.aerodrome
        return (fix.sector or self.controller,
                fix.freq_mhz if fix.freq_mhz else 0.0)

    # `station_for` AND `station_on` WERE HERE AND ARE DELETED. They live in
    # `core/stations.py` as `role_at` and `on_frequency`, bound to the map by
    # `theatre.station_for` and `theatre.station_on`.
    #
    # They were methods on a PROCEDURE, so the comms ladder of every aerodrome
    # on the map was reached through one arrival: `report_landed` found Batumi
    # Tower through the profile the bridge happened to load, and Kobuleti
    # Ground's frequency came out of Batumi's ILS. Neither the aerodrome nor
    # the role changes when a different approach is loaded, so neither can be
    # the approach's to answer.
    #
    # THE FIELD ARGUMENT SURVIVED THE MOVE UNCHANGED, and had to: a role is
    # unique only within an aerodrome, and an unqualified lookup returns a real
    # controller at the wrong airport. See tests/test_two_fields.py. [#162]

    # `handoff_from` WAS HERE AND IS DELETED. See `atc/handoff.py`, which is
    # now the only place that answers "who has him next".
    #
    # It was a second set of handoff rules, consulted when the pilot
    # TRANSMITTED, while a rule table in `atc/handoff.py` answered the same
    # question for the proactive monitor. They were not duplicates -- they were
    # complementary halves of one table, each missing what the other had:
    #
    #     handoff_from    knew center -> approach, not tower -> departure
    #     handoff.RULES   knew tower -> departure, not center -> approach
    #
    # So which rules applied depended on whether the pilot happened to key the
    # mic. A live sortie was held by Center at 44 nm with nothing in the system
    # able to move him on, because the only rule that could was in the half the
    # monitor does not read. He declared an emergency. [#51]
    #
    # IT ALSO BELONGS IN `atc/` ON THE LAYERING. A handoff is procedure, and
    # `core` may not depend on `atc` -- so the rule table cannot live here even
    # if we wanted two. The direction of the dependency picked the winner.
    #
    # `approach_hands_over_nm` and `tower_takes_nm` survive as the FIELD's
    # numbers, which is what they always were; the rules that read them moved.

    @property
    def hands_to_tower_nm(self) -> float:
        """Where Approach gives him up -- and on a talkdown, that is not the
        intercept.

        On an ILS the aeroplane has its own approach aid, so once established
        there is nothing left for Approach to do and Tower takes him. On a
        talkdown the controller IS the approach aid: he reads the range every
        mile and corrects the heading to the missed approach point. Handing off
        at the intercept therefore abandons the pilot at the exact moment the
        procedure begins.

        It did, live, at ten miles in cloud -- "contact Batumi Tower now" while
        the same controller was still transmitting a mile-by-mile talkdown, so
        the pilot was told to leave the frequency that was flying his approach.

        Real practice keeps him: the final controller obtains the landing
        clearance from Tower and relays it, and the pilot never changes
        frequency inside the final. So a talkdown holds him well down the
        approach rather than releasing him at the intercept.

        AND IT IS ONE NUMBER NOW, on every approach:

            "Don't treat the ASR different for handoffs at this time. Just make
             2 mile radius the tower airspace"

        Which removes the branch rather than adding to it. This property used to
        return the missed approach point on a talkdown and the intercept
        otherwise -- two very different distances (0.6 nm and 11 nm) derived
        from which AID the pilot happened to be flying. Both were wrong in
        opposite directions: at 11 nm he was told to leave the frequency that
        was talking him down, and at 0.6 nm Tower was landing an aeroplane it
        had never spoken to.

        Whose airspace the last two miles are is a fact about the FIELD. It does
        not change because the pilot has an ILS, or because the controller is
        reading him ranges. So: a radius, and everything inside it is Tower's.
        """
        return self.tower_takes_nm

    @property
    def tops_ft(self) -> int:
        """Cloud tops, above which an aircraft can see and be seen."""
        return self.ceiling_ft + self.cloud_thickness_ft

    @property
    def hold_in_clear_air(self) -> bool:
        """Is the bottom of the stack above the weather?

        It is, by construction, on a vectored approach -- stack_ft raises the
        base above the tops so that "hold present position" is a thing a pilot
        can actually do. Which makes this the normal case rather than a lucky
        one, and that changes how a formation holds: if they can see each other
        there is no reason to separate them vertically, so a flight holds as ONE
        aeroplane at ONE level, in trail. Altitude separates FLIGHTS from each
        other; it does not separate a flight from itself.

        Climbing to find clear air is cheap and every aircraft can do it -- an
        F-16 holds at eighteen or twenty thousand without thinking about it, and
        a Mustang will climb too. The hold is a chance to regroup before the
        approach, not something to sweat.
        """
        return bool(self.stack_ft) and self.stack_ft[0] > self.tops_ft

    @property
    def stack_ft(self) -> list[int]:
        """The holding levels, bottom first. Derived, so there is no list to keep
        in step with the base/step/ceiling -- and no stored copy in the DB that
        could drift from them."""
        # On a VECTORED approach the stack must sit ABOVE THE CLOUD TOPS, and
        # that is not a nicety. The beacon letdown held aircraft over a fix, and
        # the fix was what kept them apart -- everyone flying the same published
        # pattern, separated by a level each. Take the beacon away, as a radar
        # approach does, and there is no pattern and nothing for an aeroplane
        # with no receiver to hold over. What is left is "hold present position",
        # which is only a real instruction if the pilot can SEE: in cloud he has
        # nothing to hold relative to and will drift out of his own airspace.
        #
        # So the bottom of the stack is raised to clear air. The levels still
        # provide the separation; the visibility is what makes each level
        # holdable.
        base = self.hold_base_ft
        if getattr(self, "vectored", False) or self.kind == "asr":
            base = max(base, _round_up(self.tops_ft + self.vmc_margin_ft,
                                       self.hold_step_ft))
        return list(range(base, self.hold_top_ft + 1,
                          self.hold_step_ft))

    @property
    def top_ft(self) -> int:
        return self.stack_ft[-1]

    @property
    def bottom_ft(self) -> int:
        return self.stack_ft[0]


# Batumi. ATC needs only controller / beacon / stack / missed / outer_hold;
# the rest is for the plate. Outer hold is Kobuleti -- the departure beacon,
# on land up the coast, whose job is done by the time the flight is on approach,
# so a repeatedly-missing aircraft can be banished there without a spare channel.
# Values anchored to the real Batumi (UGSB) ILS RWY 12 plate: inbound 124,
# missed straight to 800' then LEFT to 330' climbing 3000', reversal to 2000'
# over the water. We fly the same geometry with a scripted VHF homing beacon
# (the real LU is a 430 kHz LF NDB the ARA-8 cannot steer on) and station
# passage in lieu of the DME the P-51 does not carry.
# THE FOUR PROCEDURES THAT USED TO BE HERE ARE NOW DATA.
#
#     BATUMI_APPROACH  KOBULETI_ILS  BATUMI_ASR  BATUMI_ILS
#
# They live in `config/theatres/caucasus.toml` as `[[approach]]` tables and are
# served to the ~300 call sites that read `R.BATUMI_ASR` by a module
# `__getattr__` in `route.py`. There is one copy now; there were two while the
# migration was half done, bound only by a test.
#
# What STAYS in this file is everything a procedure DOES rather than everything
# one IS: `ApproachProfile` itself, `may_vector`, the descent geometry, the
# glidepath arithmetic. Shapes and behaviour are code; instances were data.
# See docs/CONFIG.md and #137.



# Batumi, worked as a SURVEILLANCE RADAR approach -- the default now.
#
# The controller does the navigating: he vectors the aircraft onto the final
# approach course and talks it down, calling range each mile. Two things the
# beacon letdown could not do fall out of that for free.
#
# It works in ANY aeroplane. The beacon approach needs the AN/ARA-8 homing
# adapter, which exists on the P-51D-30 and nothing else, so the whole procedure
# was the property of one airframe. An ASR needs a radio and nothing else, so a
# Spitfire, a 109 or a Jug can fly it and the approach belongs to the FIELD.
#
# And it works in wind. Homing points the nose at the beacon, so tracking a
# straight line means crabbing -- and crabbing destroys the only course
# reference the pilot has. Flight testing hit this twice. Under radar the
# controller watches the ground track, absorbs the drift into the heading he
# assigns, and nobody in the aeroplane needs to know the wind exists.
#
# Runway note: DCS names this runway 13/31 (heading 310 true = 304 magnetic, so
# 124 magnetic inbound). We brief the course, not the name, and 124 is the same
# number the old AIP-anchored letdown used.
# ---------------------------------------------------------------------------
# KOBULETI ILS RUNWAY 07 -- and it is a ROW, which is the point of it.
#
#     "Fly Kobuleti ILS to prove the data drives it." [#3, TEST-1]
#
# The stated acceptance was that no file under `src/marshall/atc/` changes to
# make this work, and none did. Everything below is a number off a chart or a
# measurement off the sim; the controller, the sequencer, the handoff table and
# the phase machine were already general enough and were not touched.
#
# WHAT MAKES IT SIMPLER THAN THE RADAR APPROACH is one field: `guidance`. On an
# ASR the controller IS the approach aid -- he reads the range every mile and
# corrects the heading, and he keeps the aeroplane to the ground. On an ILS the
# AEROPLANE has localiser and glideslope, so the controller's job ends at the
# intercept: vector him on, clear him, and hand him to Tower once established.
# That difference is already in `_inbound_within`, which makes landing the
# trigger on a talkdown and a distance on everything else.
#
# THE FRAME, again, because the chart repeats the error `geo.py` exists for. It
# prints runway 07 as "070 T"; 070.03 is the DCS GRID heading and the geodesic
# bearing between the published thresholds is 075.94. Convergence here is
# +5.91, measured from those thresholds, not Batumi's +5.85.
#
# Magnetic works out at 069.9 and is spoken as 070, which is the number painted
# on the runway -- so the three frames agree for once, and that is a coincidence
# of this field rather than a rule.




# THE SAME PLATE, FLOWN THE WAY IT IS DRAWN.
#
#     "Lets program the Batumi ILS"
#
# `BATUMI_ASR` above is transcribed from AD 2.UGSB-IAC-12-ILSy and then flown as
# a SURVEILLANCE approach -- the controller reads ranges because the aeroplane
# it was built for had no localiser. This is the same chart flown as what it
# actually is, and the two differ in one thing that changes everything: who owns
# the descent.
#
#     ASR    the controller IS the approach aid, all the way to the MAP
#     ILS    he owns the intercept, clears him, and then STOPS
#
# So the geometry is shared -- IF at 11.0, FAP at 6.0, both at 2,000 feet, GP
# 3.0 coming down to meet them -- and only `kind`, `guidance` and the minima
# move. Anything that had to be re-typed here would be a second transcription of
# one chart and would drift; see docs/STATE.md, which is about exactly that.
#
# THE RUNWAY IS 13 AND THE PLATE SAYS 12. Magnetic variation drifted from about
# 12 degrees east to 7, the Georgian AIP renamed the runway, and DCS is frozen
# on the old designator -- pydcs still calls the strip "31-13". The controller
# says what is painted and what the ATIS announces, so 13; the plate's title
# will disagree by one digit and that is correct, because it is the same strip.
# See #125 for the variation itself, which is a live and separate question.

# --- serialization: an ApproachProfile <-> a plain dict (for the DB) ----------
# An approach is static reference data; storing it means round-tripping the
# profile (and its nested Fix / AtcCapability) through JSON. Properties like
# mda_ft recompute from the fields, so only the fields are serialized.

def profile_to_dict(p: ApproachProfile) -> dict:
    return asdict(p)


def profile_from_dict(d: dict) -> ApproachProfile:
    """Rebuild a profile from a stored record, tolerating older shapes.

    Approaches are persisted, so a row written by a previous version outlives the
    code that wrote it. Unknown keys are dropped rather than raising -- a stale
    row should cost you a field, not the whole approach (and the fallback for a
    failed load is the route.py constant, which would silently ignore whatever
    the mission actually briefed).
    """
    d = dict(d)
    # A ROW WRITTEN BEFORE #163 CARRIES `beacon` AND NO `aerodrome`, and what
    # that field held on such a row was the aerodrome reference point -- that
    # is the whole finding. So it becomes the datum, and the procedure comes
    # back with no homer, which is right for the three of four that never had
    # one and wrong only for a stored letdown, whose beacon and whose field are
    # the same point anyway. Dropping it instead would leave `aerodrome`
    # missing, and it is required: the profile would not rebuild at all.
    if "beacon" in d and "aerodrome" not in d:
        d["aerodrome"] = d["beacon"]
        # ...AND THE HOMER TOO, but only on a letdown. `kind` is on the row, so
        # the question "was that stored beacon a real beacon?" is answerable
        # rather than guessed: on `ndb` it was one and the procedure is flown on
        # it, on an ILS or an ASR it was the aerodrome wearing an invented ident
        # and the profile must come back with no beacon at all.
        if (d.get("kind") or "").strip().lower() == "ndb":
            d["homer"] = d["beacon"]
    d.pop("beacon", None)
    # Every nested Fix has to be rebuilt, not just the two obvious ones -- a dict
    # left in arrival_fix survives every check and only fails at the moment the
    # controller asks which frequency to talk on, which is mid-approach.
    for key in ("aerodrome", "homer", "outer_hold", "arrival_fix"):
        if isinstance(d.get(key), dict):
            d[key] = Fix(**d[key])
    # A STORED `stations` LIST IS DROPPED, and there is no rebuilding of it any
    # more. It used to be rebuilt here -- a list of dicts passes every check and
    # fails only when somebody asks a Station for its name, which for a stored
    # profile is during bridge start-up in front of a waiting pilot. The table
    # is the theatre's now (#162), so a row written before the move carries a
    # copy of a table nobody reads, and the `known` filter at the bottom is what
    # discards it. `theatre_stations` is what the row should have carried; a row
    # that predates it keeps the default, which is the ladder.
    d["atc"] = AtcCapability(**d.get("atc", {}))

    # stack_ft used to be a stored list; it is now derived from base/step/ceiling.
    # Recover the base from a legacy row so an old record still holds at the right
    # bottom level instead of silently jumping to the default.
    legacy_stack = d.pop("stack_ft", None)
    if legacy_stack and "hold_base_ft" not in d:
        d["hold_base_ft"] = min(legacy_stack)
        d["hold_step_ft"] = (sorted(legacy_stack)[1] - sorted(legacy_stack)[0]
                             if len(legacy_stack) > 1 else 1000)

    known = {f.name for f in fields(ApproachProfile)}
    return ApproachProfile(**{k: v for k, v in d.items() if k in known})
