"""The mission brief. Flavour on top, real numbers underneath.

A brief that is only atmosphere gets read once and never again; a brief that is
only a table does not tell you why you are getting up at four in the morning.
This is both, and the numbers come from `route.py` like everything else, so the
squadron humour cannot end up quoting a frequency the aeroplane does not have.

The scenario is deliberately thin -- it exists to give the sorties a shape and
a reason to fly the whole comms ladder rather than shooting the same approach
forty times. Autumn 1945, the war is won, and nobody has told the people east
of Kutaisi.
"""

from __future__ import annotations

from marshall.core import route as R

P = R.BATUMI_ASR

STYLE = """
  .brief { font: 14px/1.55 "Courier New", monospace; color: #2b2620;
           background: #d9cfb4; padding: 20px 22px; }
  .brief h1 { font-size: 21px; margin: 0; letter-spacing: 2px; }
  .brief .unit { font-size: 12px; color: #5a5142; letter-spacing: 1px;
                 margin-bottom: 14px; }
  .brief h2 { font-size: 13px; letter-spacing: 1.5px; margin: 18px 0 6px;
              border-bottom: 1px solid #8a8069; padding-bottom: 3px; }
  .brief p { margin: 0 0 9px; }
  .brief .stamp { border: 2px solid #7a2318; color: #7a2318; display: inline-block;
                  padding: 2px 10px; font-weight: bold; letter-spacing: 3px;
                  transform: rotate(-2deg); margin-bottom: 10px; }
  .brief table { border-collapse: collapse; width: 100%; margin: 6px 0 10px; }
  .brief td, .brief th { border: 1px solid #8a8069; padding: 4px 7px;
                         text-align: left; font-size: 13px; }
  .brief th { background: #c6bb9c; font-size: 11px; letter-spacing: 1px; }
  .brief .load { background: #c9b98f; }
  .brief .aside { font-size: 12px; color: #5a5142; font-style: italic; }
"""


def build(profile=P) -> str:
    st = {s.role: s for s in (getattr(profile, "stations", None) or R.STATIONS)}
    ch = {s.freq_mhz: "ABCD"[i]
          for i, s in enumerate(getattr(profile, "stations", None) or R.STATIONS)}
    legs = R.solve_route(legs=R.SORTIE_LEGS)
    total_nm = sum(l.distance_nm for l in legs)
    total_min = sum(l.minutes for l in legs)
    overlord = st.get("overlord")
    center = st.get("center")
    ctr_ch = ch.get(center.freq_mhz, "A") if center else "A"
    ctr_fq = f"{center.freq_mhz:.3f}" if center else "&mdash;"
    ovl_ch = ch.get(overlord.freq_mhz, "D") if overlord else "D"
    ovl_fq = f"{overlord.freq_mhz:.3f}" if overlord else "&mdash;"

    return f"""<title>Mission Brief</title>
<style>{STYLE}</style>
<div class="brief">
  <div class="stamp">SECRET</div>
  <h1>OPERATION SAMOVAR</h1>
  <div class="unit">362ND FIGHTER SQUADRON &middot; BATUMI &middot; AUTUMN 1945</div>

  <h2>SITUATION</h2>
  <p>The war has been over for months. Nobody appears to have circulated the
  memorandum east of Kutaisi, where our former allies have developed a sudden
  and enthusiastic interest in the refugee columns coming down out of the
  mountains &mdash; on the grounds, we are told, of "escorting them to safety",
  which is a novel use of armour.</p>

  <p>Batumi is the only field on this coast still flying our colours. Every
  other strip within reach has changed hands, changed flags, or changed its
  mind. There is nowhere to divert to. If you cannot get in here, you come
  round and get in here again.</p>

  <p class="aside">Group has asked that we avoid the phrase "the next war" in
  written correspondence. Group is welcome to come and fly the patrol.</p>

  <h2>MISSION</h2>
  <p>Depart Batumi, transit to the valley east of Kutaisi, and hold over
  <b>Tsutsnvati</b> &mdash; the town on the western shore of the lake, which is
  the only water for miles and the one thing down there you cannot mistake for
  something else &mdash; awaiting tasking from <b>{overlord.name if overlord else "Overlord"}</b>.
  Targets will be passed in the air. Do not go looking for work on your own
  initiative; the refugees are down there too, and they all look identical from
  eight thousand feet.</p>

  <table>
    <tr><th>LEG</th><th>HDG&deg;M</th><th>DIST</th><th>TIME</th></tr>
    {''.join(f'<tr><td>{l.frm.name} &rarr; {l.to.name}</td>'
             f'<td><b>{l.heading_mag:03.0f}</b></td>'
             f'<td>{l.distance_nm:.1f} nm</td><td>{l.time_str}</td></tr>'
             for l in legs)}
    <tr><td><b>TOTAL</b></td><td></td><td><b>{total_nm:.1f} nm</b></td>
        <td><b>{int(total_min)}:{round((total_min % 1) * 60):02d}</b></td></tr>
  </table>

  <h2>LOADOUT</h2>
  <table class="load">
    <tr><td><b>500 lb bombs</b> and/or <b>rockets</b>. Both if the aeroplane
        will carry them and you will still get off the runway.</td></tr>
  </table>
  <p>You are being sent to discourage tanks, not to escort anybody anywhere.
  Guns alone will annoy a T-55 and little else. Take the ordnance.</p>

  <h2>RECOVERY</h2>
  <p>Batumi, runway <b>{profile.runway}</b>, radar approach &mdash; the
  controller navigates and you fly the headings he gives you. Minimums
  <b>{profile.mda_ft:,} ft</b>. Weather here does what it likes off the sea,
  so brief the missed approach before you need it: straight ahead, at
  <b>{profile.missed_straight_ft:,}</b> turn <b>{profile.missed_turn}</b> onto
  <b>{profile.missed_hdg:03d}</b> and climb <b>{profile.missed_climb_ft:,}</b>.
  That takes you over water. Everything else takes you into a mountain.</p>

  <h2>COMMS</h2>
  <table>
    <tr><th>CH</th><th>FREQ</th><th>WHO</th><th>FOR</th></tr>
    <tr><td>{ch.get(st['tower'].freq_mhz, 'C')}</td><td>{st['tower'].freq_mhz:.3f}</td>
        <td>{st['tower'].name}</td><td>start-up, taxi, landing</td></tr>
    <tr><td>{ch.get(st['approach'].freq_mhz, 'B')}</td><td>{st['approach'].freq_mhz:.3f}</td>
        <td>{st['approach'].name}</td><td>departure and recovery</td></tr>
    <tr><td>{ctr_ch}</td><td>{ctr_fq}</td>
        <td>{center.name if center else '&mdash;'}</td><td>transit</td></tr>
    <tr><td>{ovl_ch}</td><td>{ovl_fq}</td>
        <td>{overlord.name if overlord else '&mdash;'}</td>
        <td>tasking, on station</td></tr>
  </table>

  <p class="aside">Altimeter {R.altimeter_spoken(R.qfe_inhg(profile.field_elev_ft))},
  {profile.altimeter_datum}. Wind {int(R.WIND_FROM_DEG):03d} at
  {int(R.WIND_MPH)}. Bring the aeroplane back; there is a shortage.</p>
</div>
"""


if __name__ == "__main__":
    from marshall import config
    config.ensure_dirs()
    out = config.KNEEBOARD_OUT / "brief.html"
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out}")
