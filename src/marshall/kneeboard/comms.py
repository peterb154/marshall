"""The comms ladder: which button, who is on it, and when you use it.

A pilot in a period cockpit has four buttons and no way to dial a frequency, so
the card is not a convenience -- it is the entire radio. Getting it wrong is not
a missed call, it is inaudibility: he transmits into an empty channel and hears
nothing back, and from the cockpit that is indistinguishable from an ATC that is
not answering. It has happened here, twice.

So this page is generated from the same `route.py` stations the mission writes
into the aeroplane and the bridge listens on. Three things that must agree, one
source. And it is ordered by the SORTIE rather than by frequency, because that
is the order the buttons get pressed: ground, departure, enroute, and back.
"""

from __future__ import annotations

from marshall.atc import phases
from marshall.core.stations import preset_label
from marshall.core.units import altimeter_spoken, qfe_inhg
from marshall.kneeboard.card import Card, current

# The sortie, in order, and which phase sends you to each button. Only phases
# that actually change the frequency appear -- a ladder listing every state
# would be a table of the phase machine and not a radio card.
LADDER = [
    ("Start-up, taxi", ("clearance", "taxi")),
    ("Take-off, departure", ("departure",)),
    ("Enroute, transit", ("enroute", "rtb")),
    ("Tasking, on station", ("tasked", "on_station")),
    ("Recovery, approach", ("arrival", "holding", "approach", "missed")),
    # BOTH RUNGS, because the recovery ends with two controllers and not one.
    # `landed` is Tower's -- down, still on the strip -- and `taxi_in` is
    # Ground's, and listing only the first is what left the man who parks you
    # owning no phase at all on the card. See below.
    ("Landing, taxi in", ("landed", "taxi_in")),
]

# WHICH HALF OF THE SORTIE A LABEL BELONGS TO.
#
# A station covers what it covers -- Kobuleti Departure also works approaches,
# Batumi Ground also works start-ups -- and on a one-field sortie that was the
# same thing as what you USE him for. Flying Kobuleti to Batumi it stops being
# the same thing, and the card started telling the pilot his departure
# controller handled recoveries and that he would start up at the field he was
# landing at. Both true of the seat. Neither any use in the cockpit.
#
# So a field's rows are filtered to the half of the flight that happens there.
OUTBOUND = ("Start-up, taxi", "Take-off, departure")
INBOUND = ("Recovery, approach", "Landing, taxi in")

STYLE = """
  .comms { font: 15px/1.5 "Courier New", monospace; color: #2b2620;
           background: #d9cfb4; padding: 18px 20px; }
  .comms h1 { font-size: 20px; margin: 0 0 2px; letter-spacing: 1px; }
  .comms .sub { font-size: 12px; color: #5a5142; margin-bottom: 14px; }
  .comms table { border-collapse: collapse; width: 100%; margin-bottom: 16px; }
  .comms th, .comms td { border: 1px solid #8a8069; padding: 5px 7px;
                         text-align: left; }
  .comms th { background: #c6bb9c; font-size: 12px; letter-spacing: .5px; }
  .comms .ch { font-size: 22px; font-weight: bold; text-align: center;
               width: 42px; }
  .comms .fq { font-size: 17px; font-weight: bold; white-space: nowrap; }
  .comms .who { font-weight: bold; }
  .comms .note { font-size: 12px; color: #5a5142; }
  .comms h2 { font-size: 14px; margin: 16px 0 6px; letter-spacing: 1px;
              border-bottom: 1px solid #8a8069; padding-bottom: 3px; }
  .comms .facts td { font-size: 13px; }
  .comms .warn { background: #c9b98f; }
  .comms .fld { font-size: 12px; color: #5a5142; white-space: nowrap; }
  .comms .alt { font-size: 12px; font-weight: normal; color: #5a5142; }
  .comms tr.sep td { height: 6px; padding: 0; border-bottom: 2px solid #8a8069; }
"""


def build(card: Card | None = None, profile=None) -> str:
    """The radio card, for whichever theatre this kneeboard is serving.

    A CARD IN, A PAGE OUT. This used to take a profile and then read the
    stations, the fields and the sortie's two ends out of `route` -- so the
    parameter chose the approach and the module chose the theatre, and pointing
    it at Nevada produced Nellis frequencies under Batumi headings.

    `profile` is still accepted because callers pass it, and it overrides the
    card's own. Everything else comes off the card.
    """
    card = card or current()
    profile = profile or card.profile
    # THE LADDER, NOT THE FIRST FOUR OF THE STATION LIST.
    #
    # This card used to slice `stations[:4]` and call itself "four presets",
    # which was true while a warbird's SCR-522 was the only radio in the
    # theatre. The sortie runs Kobuleti to Batumi now and the ladder is seven
    # rungs; the old slice would have printed the departure field and Center and
    # stopped -- handing the pilot a card that goes quiet exactly when he starts
    # his approach.
    # THE LADDER IS THE CARD'S STATION LIST, in its own order.
    #
    # This intersected `route.PRESET_LADDER`, which names Caucasus stations,
    # so a Nevada card came out EMPTY -- a comms page with no frequencies on
    # it at all, which is the inaudibility failure this file's docstring is
    # about, arrived at from a third direction.
    #
    # A theatre's station list is already written in the order the buttons
    # are pressed, so it IS the ladder.
    #
    # AND IT IS ONLY THE CARD'S NOW. This intersected the card's list with the
    # PROFILE's, which was the same theatre table reached through an arrival
    # procedure -- a no-op when the profile carried it and a no-op when it did
    # not, so the intersection never removed anything and only obscured where
    # the list came from. The table came off the profile in #162.
    stations = list(card.stations)

    rows = []
    last_field = None
    for i, s in enumerate(stations, start=1):
        # A RULE BETWEEN AERODROMES. Seven rows of frequencies read as one
        # undifferentiated block, and the thing the pilot most needs to see at a
        # glance is where he stops talking to one airport and starts talking to
        # the next.
        fld = getattr(s, "field", "")
        if last_field is not None and fld != last_field:
            rows.append("<tr class='sep'><td colspan='5'></td></tr>")
        last_field = fld
        # What this seat covers, said in the pilot's language rather than the
        # phase table's. He does not care that "arrival" and "holding" are
        # different states; he cares which button to press.
        covers = [s.role, *getattr(s, "also", ())]
        when = [label for label, ph in LADDER
                if any(phases.owner_of(p) in covers for p in ph)]
        # Only the half of the sortie that happens at his field. A fieldless
        # controller -- Center -- keeps whatever is left, which is the enroute
        # middle, and that is exactly right for him.
        if fld == card.departure:
            when = [w for w in when if w in OUTBOUND]
        elif fld == card.arrival:
            when = [w for w in when if w in INBOUND]
        if not when:
            # A SEAT THE PHASE MACHINE CANNOT REACH.
            #
            # BATUMI GROUND USED TO BE ONE, and is not any more. `phases` gives
            # "landed" to Tower, which was correct while Tower also wore the
            # ground hat -- there was nobody else to give it to. Splitting
            # Ground off left a real controller, on a real preset, owning no
            # phase at all, so this column rendered a dash for the man who takes
            # you to the ramp, and the note here said that until "landed" could
            # hand on to a ground seat no automatic handoff would ever send
            # anybody to this frequency and the pilot had to ask.
            #
            # It does now: Tower gives him Ground on the roll-out and the phase
            # moves to `taxi_in`, which is Ground's and is on the ladder above
            # (#77). The fallback stays for the seat that genuinely owns no
            # phase -- the card says what a controller does, and inventing a
            # phase here to fill a column would be the papering-over this
            # comment was written to refuse.
            when = ["Taxi in" if fld == card.arrival else s.role.title()]
        # EVERY FREQUENCY HE IS ON, because a facility can own several and the
        # card is the only place a pilot finds that out. The second one is what
        # a set that cannot dial fractions tunes.
        extra = "".join(f"<div class='alt'>{c:.3f}</div>"
                        for c in getattr(s, "channels", ()))
        rows.append(
            f"<tr><td class='ch'>{preset_label(i)}</td>"
            f"<td class='fq'>{s.freq_mhz:.3f}{extra}</td>"
            f"<td class='who'>{s.name}</td>"
            f"<td class='fld'>{fld or '&mdash;'}</td>"
            f"<td class='note'>{'; '.join(when) or '&mdash;'}</td></tr>")

    # THE ATIS FREQUENCIES, which belong to the AERODROME rather than to any
    # controller -- so they are not rungs on the ladder and get their own
    # block. A pilot tunes one, listens, and never transmits on it.
    atis_rows = "".join(
        f"<tr><td class='who'>{f.name}</td>"
        f"<td class='fq'>{f.atis_mhz:.3f}</td>"
        f"<td class='note'>{'departure' if f.name == card.departure else 'arrival'}"
        f"</td></tr>"
        for f in card.fields if getattr(f, "atis_mhz", 0))

    inbound = profile.final_crs
    rwy = profile.runway or "in use"
    qfe = altimeter_spoken(qfe_inhg(profile.field_elev_ft))
    return f"""<title>Comms &amp; {card.arrival} {rwy}</title>
<style>{STYLE}</style>
<div class="comms">
  <h1>COMMS LADDER</h1>
  <div class="sub">{card.departure} &rarr; {card.arrival}. {len(rows and stations)} presets, in
    the order you press them. This card, the aeroplane's radio and the
    controller all come from one source &mdash; if they ever disagree, believe
    nothing and say so.</div>

  <table>
    <tr><th>CH</th><th>FREQ</th><th>STATION</th><th>FIELD</th><th>WHEN</th></tr>
    {''.join(rows)}
  </table>

  <h2>ATIS</h2>
  <table>
    <tr><th>FIELD</th><th>FREQ</th><th></th></tr>
    {atis_rows}
  </table>
  <div class="note">Listen before you call. Approach and Clearance will ask
    which information you have &mdash; a wrong letter is a cross-check, never a
    refusal, and nothing about it gates an approach.</div>

  <h2>{card.arrival.upper()} &mdash; RUNWAY {rwy} &mdash; {profile.kind.upper()} APPROACH</h2>
  <table class="facts">
    <tr><td>Final approach course</td><td><b>{inbound:03d}&deg;</b> magnetic</td></tr>
    <tr><td>Initial approach fix</td>
        <td><b>{profile.final_intercept_nm:.0f} nm</b> at
            <b>{profile.iaf_alt_ft:,} ft</b> &mdash; established by here</td></tr>
    <tr><td>Final approach point</td>
        <td><b>{profile.fap_nm:.0f} nm</b> &mdash; begin descent</td></tr>
    <tr><td>Minimums (MDA)</td>
        <td><b>{profile.mda_ft:,} ft</b>
            ({profile.mda_ft - profile.field_elev_ft:,} above the field)</td></tr>
    <tr><td>Missed approach point</td><td><b>{profile.map_nm:.1f} nm</b></td></tr>
    <tr class="warn"><td>Missed approach</td>
        <td>straight ahead; at <b>{profile.missed_straight_ft:,}</b> turn
            <b>{profile.missed_turn}</b> heading
            <b>{profile.missed_hdg:03d}</b>, climb
            <b>{profile.missed_climb_ft:,}</b></td></tr>
    <tr><td>Approach speed</td>
        <td><b>{profile.final_speed_mph}</b> mph from the fix
            (pattern {profile.speed_mph})</td></tr>
    <tr><td>Altimeter</td>
        <td><b>{qfe}</b> ({profile.altimeter_datum})</td></tr>
    <tr><td>Wind</td>
        <td>{int(card.wind_from_deg):03d} at {int(card.wind_mph)} mph
            (forecast &mdash; the ATIS has the actual)</td></tr>
    <tr><td>Holding</td>
        <td><b>{profile.stack_ft[0]:,} ft</b> and up, in clear air &mdash;
            {profile.hold_outbound_hdg:03d} outbound,
            {(profile.hold_outbound_hdg + 180) % 360 or 360:03d} inbound</td></tr>
  </table>

  <div class="sub">The controller navigates: you fly the headings he gives you
    and he absorbs the wind. There is no glidepath &mdash; his altitudes are
    advisory and the descent rate is yours.</div>
</div>
"""


if __name__ == "__main__":
    from marshall import config
    config.ensure_dirs()
    out = config.KNEEBOARD_OUT / "comms.html"
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out}")
