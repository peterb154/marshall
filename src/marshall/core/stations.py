"""The controllers: who is on which frequency, and what he owns.

A Station is a PERSON ON A RADIO, deliberately distinct from a Fix. It carries
a name, its frequencies, the role it works, the field it sits at, and the voice
and manner it speaks with.

A ROLE IS ONLY UNIQUE WITHIN AN AERODROME. That is the lesson the second field
taught, and it cost four bugs to learn: there is no such thing as "the tower",
there is Kobuleti Tower and there is Batumi Tower, and a lookup that finds "a
station whose role is tower" will hand a departing pilot the controller at the
field he is flying to. `ApproachProfile.station_for` takes a field for that
reason, and `Station.field` is what it matches on.

`Station.field` is a STRING and not a `Field_`. Pointing it at the object would
make the two definitions circular; `fields.field_named` is the join.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Station:
    """A controller: a name, a frequency, and the phase of flight he owns.

    Distinct from a Fix on purpose. A Fix is a place; a Station is a person on a
    radio. They were the same thing while the approach was a beacon letdown --
    the controller had to sit on the beacon you were homing, because the ARA-8
    tunes and homes on one frequency at a time. Under radar the pilot navigates
    by nothing at all, so a frequency is free to be just a frequency, and the
    controllers can be split the way real ones are: Center, Approach, Tower.
    """
    name: str
    freq_mhz: float
    role: str = ""              # his PRIMARY job, and what he is called
    # Everything else he also works. A field this size does not staff a seat per
    # phase of flight: one man has ground and tower, another has departure and
    # approach, and that is how it is done for real. It matters because a
    # departing aircraft and an arriving one then share a controller and a
    # frequency, which is where sequencing gets interesting -- he is fitting
    # departures into the airspace he is recovering through.
    #
    # Empty means "just the primary role", so the simple case stays simple.
    also: tuple = ()
    # The Polly voice this controller speaks with. On the STATION rather than
    # passed to the bridge, because a voice handed in separately drifts from the
    # identity it belongs to -- you end up with Tower's manner in Center's voice
    # and no single place that says which is which. Changing sector should sound
    # like meeting a different person, which is the point of splitting them.
    voice: str = "Matthew"
    # MORE THAN ONE FREQUENCY FOR ONE MAN, and it is not a convenience.
    #
    #     "The reason ours round is that the WW2 airplanes can't tune to those
    #      finer frequencies... I wonder if SRS lets us duplex a channel, so we
    #      can use both 124.425 for modern and 124.00 for a SCR-522 radio
    #      seamlessly."
    #
    # It does. The SRS voice packet has always carried a variable-length
    # frequency list, so one transmission reaches both -- verified live with a
    # warbird on 124.000 and a jet on 124.425 hearing the same call once.
    #
    # The published AIP plate for Batumi says APP 124.425 because that IS the
    # frequency. The SCR-522 in a P-51 tunes four crystal channels and cannot
    # reach it. Without this the two aeroplanes are on different fields, and the
    # only alternatives are lying on the plate or excluding one of them.
    #
    # `freq_mhz` stays the PRIMARY -- the published one, what a modern radio
    # tunes and what the chart prints. `channels` are the same facility, same
    # controller, same conversation, reachable by older sets.
    #
    # AND THE PRESET BUDGET IS WHY A WARBIRD FIELD LOOKS DIFFERENT. The SCR-522
    # has FOUR crystal channels, set by the mission designer and unchangeable in
    # the cockpit:
    #
    #     "There is probably only room for a single freq per airport in a WW2
    #      airplane. It will be something like Batumi (source), Senaki
    #      (destination), Georgia Center (en route) and Sentry (opfor
    #      controller)."
    #
    # So a 1944 field is ONE facility -- one man answering as tower, ground,
    # approach and departure, because there is no second preset to spend on
    # splitting him. A modern field presents the same airport as three or four
    # positions. The AERODROME does not change; what the aeroplane can reach
    # does.
    #
    # `also` already models one controller wearing several hats, and
    # `AtcCapability` already models what a mission's aircraft can do. Nothing
    # here needs to know which era it is: a warbird profile declares one Station
    # with every role in `also`, and a modern one declares several. That is a
    # data decision per mission, which is what it should be.
    channels: tuple[float, ...] = ()
    # WHICH AERODROME HE WORKS, and it is the thing that makes two fields
    # possible at all.
    #
    # A role was globally unique while there was one airport: `station_for
    # ("tower")` walked the list and returned the only Tower there was. Add
    # Kobuleti and that same call returns whichever Tower is listed first, so a
    # departure from Kobuleti gets handed to Batumi Tower forty miles away --
    # silently, because both answers are a valid Station and nothing can tell
    # them apart.
    #
    # So a role is unique WITHIN A FIELD, not across the theatre, and this is
    # what scopes it. Empty means the station is not a field's at all, which is
    # the honest answer for Center and for Sentry: they own a region, and asking
    # which aerodrome they belong to is a category error rather than a missing
    # value.
    field: str = ""
    # HOW HE SOUNDS. Never what he decides.
    #
    #     "See if you can add some soul to each of the controllers so there's a
    #      different texture in the way they talk to us. Some might be grouchy.
    #      Some might be super helpful."
    #
    # Eight controllers who are all the same person is the tell that there is
    # one prompt behind them. Real ones are not interchangeable: the man on
    # clearance delivery reads you a form, the ground controller at a busy field
    # has no time for you, and the approach controller talking you down in
    # weather is the calmest voice you will hear all day. A pilot learns them,
    # and knowing who he is about to talk to is part of knowing where he is.
    #
    # THE LINE THIS MUST NOT CROSS, and it is the whole reason this is a
    # sentence on a Station rather than eight system prompts: manner changes the
    # WORDS AROUND the numbers and never the numbers. A grouchy controller
    # issues the same altitude as a cheerful one, in the same phraseology, with
    # the same separation behind it -- he is just shorter about it. The moment a
    # personality is allowed to decline work, skip a required read-back or round
    # off a heading, it has stopped being a voice and started being a fault, and
    # it will be diagnosed as one by somebody reading the separation engine.
    #
    # `voice` is the Polly timbre; this is the manner spoken in it. They belong
    # together on the station for the same reason -- a voice handed in
    # separately drifts from the identity it belongs to.
    manner: str = ""

    @property
    def freqs(self) -> tuple[float, ...]:
        """Every frequency this facility is heard on, primary first."""
        return (self.freq_mhz, *self.channels)

    def hears(self, mhz: float, tol: float = 0.001) -> bool:
        """Is this facility listening on that frequency?

        Any of them. A pilot who checks in on the warbird channel is talking to
        the same controller as one on the published frequency, and every
        `station_on` lookup has to agree or he is answered by nobody.
        """
        return any(abs(f - mhz) < tol for f in self.freqs)


# From the Batumi AIP (AD 2.UGSB-IAC-12-ILSy): APP 124.425, TWR 118.600 --
# rounded to whole megahertz, because a WW2 set tunes crystal channels and
# quarter-megahertz spacing is a jet-age convention. Approach lands on 124.000,
# which is also one of the stock preset channels both WW2 airframes ship with,
# so it works even where a preset override does not apply.
#
# There is no published Center for the region, so Georgia Center keeps a stock
# channel and is the one frankly invented number here.
#
# CENTER IS NOT A FIELD'S CONTROLLER. Approach and Tower belong to an aerodrome;
# a Center owns a region and hands you between aerodromes, so there is one for
# the whole theatre rather than one per airfield.
CENTER = Station(
    "Georgia Center", 139.000, "center", voice="Brian",
    manner="Unhurried and a little remote, like a man with a very large piece "
           "of sky and no particular reason to rush. Formal without being "
           "stiff. He works in whole minutes and hundreds of miles, so a "
           "fifteen-mile problem does not move him. Never chatty, never curt "
           "-- just distant, the way a voice sounds when it is not standing at "
           "the same airfield you are.")
# THE PUBLISHED FREQUENCY FIRST, the tunable one beside it.
#
# AIP Georgia AD 2.UGSB-IAC-12-ILSy (10 AUG 2023) gives APP 124.425 and TWR
# 118.600. Those are the real numbers and they are what the scanned plate on the
# kneeboard prints, so they are what a pilot reads and expects to dial.
#
# An SCR-522 cannot dial them. It has four crystal channels and no fractions, so
# a 1944 Mustang physically cannot reach 124.425 -- which left three options:
# lie on the plate, exclude the warbirds, or carry both. We carry both. One
# transmission goes out on every frequency the facility owns and each pilot
# hears it once; see `Station.channels` and `radio/client.transmit`.
# THE STEADIEST VOICE ON THE MAP, and deliberately so. He is the one talking a
# pilot down through cloud to a runway he cannot see, which is the single moment
# in this whole system where a controller's manner does real work. Everybody
# else can afford a temper.
APPROACH = Station("Batumi Approach", 124.425, "approach",
                   channels=(124.000,),
                   also=("departure",), voice="Matthew", field="Batumi",
                   manner="Calm, methodical, and entirely unflappable -- the "
                          "voice you want in the weather. He talks in an even "
                          "rhythm and never speeds up, because the man on the "
                          "other end is flying an instrument approach and "
                          "takes his pace from yours. Warm, but economical: "
                          "no chat during the talk-down, and every "
                          "transmission is a number the pilot needs. If "
                          "something goes wrong he gets quieter and more "
                          "precise rather than louder. The one controller who "
                          "is never, under any circumstances, short with "
                          "anybody.")
# GROUND IS ITS OWN SEAT NOW, and it used to be part of Tower's `also`.
#
# That was right while Batumi was the only aerodrome and a warbird had four
# presets to spend: one man took tower, ground and delivery because there was no
# channel left to reach a second. A modern field with a seven-preset ladder can
# afford the real arrangement, and the split matters -- Ground owns the taxiways
# and Tower owns the runway, and the handoff between them is a procedure we want
# to be able to get wrong and then fix.
#
# The 1944 arrangement is not deleted, it moved to `WW2_STATIONS` below.
TOWER = Station("Batumi Tower", 118.600, "tower", channels=(118.000,),
                voice="Joey", field="Batumi",
                manner="Cheerful and genuinely pleased to see aeroplanes. He "
                       "has a window and he uses it -- he will tell you the "
                       "wind is being kind today, or that he has you visual on "
                       "a two-mile final. Brisk when there is a sequence to "
                       "run, friendly the rest of the time, and he says "
                       "\"welcome back\" to somebody who has just landed out "
                       "of the weather. Never gushing, and never so chatty "
                       "that a landing clearance gets buried in it.")
# 121.900 IS ASSIGNED BY US, not published. The AIP extract we hold for UGSB
# gives APP and TWR and nothing else, so rather than invent a number with no
# shape, this takes the frequency that ground control sits on at most of the
# world's aerodromes. It is a plausible number honestly labelled, which is the
# most we can claim for it.
GROUND = Station("Batumi Ground", 121.900, "ground",
                 also=("delivery", "clearance"), voice="Stephen",
                 field="Batumi",
                 manner="Gruff, and has been doing this a very long time. He "
                        "uses as few words as the job allows and none at all "
                        "for pleasantries -- \"taxi bravo, hold short one "
                        "three\" and nothing after it. Faintly put upon by "
                        "anyone who needs the taxiways explained, though he "
                        "will explain them, correctly, every time. Not rude "
                        "and never unsafe: he simply regards conversation as "
                        "something that happens on other frequencies. A pilot "
                        "who thanks him gets \"mm-hm\".")

# ---------------------------------------------------------------------------
# KOBULETI (UG5X) -- the departure field.
#
# MEASURED AND PUBLISHED, not guessed. The aerodrome chart gives elevation 59 ft
# (the sim agrees to the foot), runway 07/25 at 2400 x 60 m, variation 6 E, and
# a VHF set of three frequencies. The sim gave the position and the runway
# geometry, and the convergence below was measured from its own thresholds.
#
# AND THE CHART REPEATS THE BUG `geo.py` WAS WRITTEN ABOUT. It prints runway 25
# as "250 T". The geodesic bearing between the two published thresholds is
# 255.94; 250.03 is the DCS GRID heading. The chart has labelled a grid course
# as true, which is exactly the error that put the old nav log 5.74 degrees out
# on every leg. We take the number and correct the frame rather than inheriting
# the mistake because it came off a plate.
# ---------------------------------------------------------------------------

# 125.100 is ASSIGNED. The chart publishes no clearance delivery -- a Soviet-era
# military field would not have had one -- so this is ours, and marked.
KOB_CLEARANCE = Station("Kobuleti Clearance", 125.100, "clearance",
                        also=("delivery",), voice="Gregory", field="Kobuleti",
                        manner="Precise to the point of pedantry, and reads a "
                               "clearance like a man reading a form -- because "
                               "that is exactly what it is. Unhurried, "
                               "slightly officious, mildly satisfied when a "
                               "read-back is correct and entirely willing to "
                               "make you do it again when it is not. He will "
                               "not let a wrong frequency or a wrong altitude "
                               "past him, ever, and he is polite about it in a "
                               "way that makes it worse.")
# 133.000 AND 122.100 ARE BOTH PUBLISHED, and both are the Tower. The chart
# lists 133.000 as TWR and 122.100 under "Additional Combined Frequencies" as
# Tower again -- a real facility reachable on two VHF channels, which is what
# `channels` has always meant. This is the first use of it for a genuine
# published alternate rather than a warbird accommodation.
#
# IT ANSWERS AS GROUND AND AS TOWER, which is the one judgement call in this
# ladder. The seven presets asked for have a Kobuleti Clearance, Ground and
# Departure but no Tower, and somebody has to clear an aeroplane to take off.
# Combining ground and tower into one seat is how a field this size actually
# runs, so the missing preset costs nothing real. If a separate Tower is wanted
# it is one more row and one more preset.
# GROUND NO LONGER WEARS THE TOWER HAT, and this is the correction:
#
#     "Ground should clear to the runway only, telling them to hold short of
#      the runway. Once they check in and report holding short they should be
#      handed off to tower. Ground should not clear for takeoff. That's tower."
#
# Combining them was my judgement call when the ladder had no Kobuleti Tower in
# it, and it was the wrong one. Who owns the RUNWAY is not an economy to be
# made at a quiet field -- it is the one piece of separation on the aerodrome,
# and a controller who moves aeroplanes on taxiways must not also be the man
# who puts them on the strip. So Kobuleti gets its Tower and the ladder gets an
# eighth rung.
#
# 121.900 is ASSIGNED, matching Batumi's ground frequency by convention -- the
# chart publishes no ground for Kobuleti, which a Soviet-era military field
# would not have had separately. The published 133.000/122.100 pair goes to
# TOWER, where the chart puts it.
KOB_GROUND = Station("Kobuleti Ground", 121.800, "ground",
                     voice="Justin", field="Kobuleti",
                     manner="Brisk and strictly territorial. He owns the "
                            "taxiways and nothing else, and he is scrupulous "
                            "about the boundary -- you are cleared TO the "
                            "runway and told to hold short of it, every time, "
                            "in those words. Ask him for take-off and he will "
                            "tell you that is Tower's, without warmth and "
                            "without apology. No wasted syllables; he expects "
                            "you to keep up.")
# THE PUBLISHED TOWER, on the chart's own numbers. 133.000 is TWR and 122.100
# is listed beside it under the additional combined frequencies -- one facility
# reachable on two VHF channels, which is what `channels` has always meant.
KOB_TOWER = Station("Kobuleti Tower", 133.000, "tower",
                    channels=(122.100,), voice="Joanna", field="Kobuleti",
                    manner="Owns the runway and nothing else, and is entirely "
                           "relaxed about it -- there is rarely a queue. Warm "
                           "and unhurried on the ground, crisp the moment "
                           "anything is rolling. She will tell you the wind "
                           "with a take-off clearance because that is what it "
                           "is for, and she does not chat while an aeroplane "
                           "is on the strip.")
# 123.300 IS PUBLISHED, as "GCA" -- ground controlled approach, the radar
# controller. Kobuleti is a PAR/SRA field, so the man on this frequency is the
# same kind of controller Batumi Approach is, and giving him departures as well
# as arrivals is what the chart already implies.
KOB_DEPARTURE = Station("Kobuleti Departure", 123.300, "departure",
                        also=("approach",), voice="Kevin", field="Kobuleti",
                        manner="Dry, laconic, and comfortable with silence. A "
                               "radar man: he tells you what he sees and then "
                               "stops talking, and he does not fill the gaps. "
                               "Occasional deadpan humour, never at the "
                               "pilot's expense and never during anything that "
                               "matters. If he says \"radar contact\" and "
                               "nothing else for four minutes, that is because "
                               "there is nothing else you need.")

# The mission commander. Not a new kind of machine -- a controller with a wider
# scope, which is why it is a Station like the others: it has a frequency, a
# voice, and aircraft it works. What it does differently is give a flight a JOB
# rather than a heading, and it is the only one here that does not care where
# the runway is.
#
# Fourth preset deliberately. A period set has four buttons and the other three
# are spoken for, so this is the last one available -- which is also true of a
# real WW2 cockpit and is a reasonable constraint to design inside.
OVERLORD = Station("Sentry", 131.000, "overlord", voice="Kimberly",
                   manner="Command, not service. Crisp, directive and "
                          "impersonal -- she gives a flight a job rather than "
                          "a heading, and she does not soften it. No small "
                          "talk, no reassurance, and no interest in how you "
                          "feel about the tasking. The only voice here that "
                          "tells you what to do rather than what you are "
                          "cleared to do.")

STATIONS = [KOB_CLEARANCE, KOB_GROUND, KOB_TOWER, KOB_DEPARTURE, CENTER,
            APPROACH, TOWER, GROUND, OVERLORD]

# THE ORDER A PILOT DIALS THEM, which is a fact about the SORTIE and not about
# the airport. It is written down once, here, because three things have to agree
# about it or the ladder is a lie: the radio presets burned into the aeroplane,
# the comms card on the kneeboard, and what a controller says out loud when he
# hands you on ("contact departure, preset three").
#
#     "Let's set the radio presets in order of what's required -- k clearance 1,
#      k ground 2, k departure 3, center 4, b approach 5, b tower 6, b ground 7."
#
# EIGHT NOW, because Kobuleti gained a Tower:
#
#     "Ground should not clear for takeoff. That's tower."
#
# The seven above folded Ground and Tower onto one seat at the departure field,
# which was my judgement call and the wrong one -- who owns the runway is the
# one piece of separation on an aerodrome and is not an economy to make. The
# renumbering is deliberate and everything that prints a card reads this list,
# so the aeroplane, the kneeboard and the controller move together.
#
# Sentry is deliberately NOT on it. He is the mission commander, not a step in
# the ladder, and a pilot flying Kobuleti to Batumi never needs him -- so he
# keeps a preset above the ladder rather than a rung inside it.
PRESET_LADDER = [KOB_CLEARANCE, KOB_GROUND, KOB_TOWER, KOB_DEPARTURE,
                 CENTER, APPROACH, TOWER, GROUND]


# WHERE THE SORTIE STARTS AND WHERE IT ENDS.



# WHAT THE CARD CALLS A BUTTON, and it stopped being a letter.
#
# An SCR-522 has four buttons labelled A B C D, so every card this system had
# ever printed indexed `"ABCD"[i]` -- in six different files. A seven-rung
# ladder walks straight off the end of that string: four rows print and the
# fifth raises IndexError, or worse, a slice quietly drops Batumi off the
# kneeboard and the pilot never learns he had three more.
#
# Numbers, because that is what the pilot was promised and what a modern set
# shows. The letters stay reachable for a period card, where the buttons really
# are lettered and calling one "preset 3" would not match the cockpit.
PRESET_LETTERS = "ABCD"


def preset_label(n: int, letters: bool = False) -> str:
    """The label for button `n`, one-based."""
    if letters and 1 <= n <= len(PRESET_LETTERS):
        return PRESET_LETTERS[n - 1]
    return str(n)


def preset_of(station) -> int | None:
    """Which button he is on, or None if he is not on the ladder.

    So a controller can say "contact Batumi Approach, preset five" and be right
    about the number, rather than the pilot hunting for a frequency he was told
    in megahertz while flying an instrument approach.
    """
    for i, s in enumerate(PRESET_LADDER, start=1):
        if s.name == getattr(station, "name", station):
            return i
    return None


# THE 1944 ARRANGEMENT IS NOT HERE, and deliberately not written as a second
# list sitting unused beside this one.
#
#     "The Batumi Clearance controller would just sit idle in a ww2 mission. And
#      the ww2 controller would sit idle during a modern mission."
#
# That is the right model -- two sets, one live per mission, no interoperation
# needed. But the beacon letdown does not read a station list at all today: it
# derives its controllers from the beacons, because on an ARA-8 the man you talk
# to IS the frequency you home (see `stations` on ApproachProfile). So declaring
# a WW2 list now would be a name nothing reads, which is the exact fault
# `AtcCapability.era` has -- declared, never consulted, and wrong without
# anything noticing. It gets written when the profile that selects it does.
