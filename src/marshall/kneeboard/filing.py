"""The form that puts a plan on the board, so nobody has to write a migration.

    "A plan can be filed without touching the database by hand."  -- [UI-1] #22

This is a DESK page, not a kneeboard page. It is used before the sortie with a
keyboard, unlike everything else the kneeboard server renders, which is read in
a cockpit through OpenKneeboard and cannot be typed into.

**It decides nothing.** Every rule about what a plan may contain lives in the
director's `tools/filing.py`, and this page asks it — while you are still
typing, through `/plans/check`, and again when you press the button. That is
deliberate and not laziness: a form that knows the rules is a second copy of
them, and the two would disagree the first time a fix was added. The page is a
way of TALKING to the check; it is not the check.

For the same reason the route field offers the fixes the director actually
holds. A typo is better prevented than diagnosed, and the list comes from the
`fixes` table — which is what the sim projected, not what `route.py` says.
"""

from __future__ import annotations

STYLE = """
  .file { font: 15px/1.5 "Courier New", monospace; color: #241f18;
          background: #d9cfb4; padding: 20px 22px; max-width: 1500px;
          display: grid; gap: 8px 30px;
          grid-template-columns: minmax(430px, 560px) 1fr;
          grid-template-areas: "head head" "left right"; align-items: start; }
  .file > h1, .file > .sub { grid-area: head; }
  .file .col-l { grid-area: left; min-width: 0; }
  .file .col-r { grid-area: right; min-width: 0; position: sticky; top: 20px; }
  /* One column under a narrow window -- this is a desk page, but a laptop is
     a desk and 1500px of it is not guaranteed. */
  @media (max-width: 1080px) {
    .file { grid-template-columns: 1fr;
            grid-template-areas: "head" "left" "right"; }
    .file .col-r { position: static; }
  }
  .file .col-r .empty { border: 1px dashed #8a8069; padding: 26px 18px;
    text-align: center; color: #5a5142; font-size: 13px; }
  .file h1 { font-size: 21px; margin: 0 0 2px; letter-spacing: 1.5px; }
  .file .sub { font-size: 13px; color: #5a5142; margin-bottom: 16px; }
  .file label { display: block; margin: 10px 0 2px; font-size: 12px;
                letter-spacing: .09em; text-transform: uppercase;
                color: #5a5142; }
  .file input, .file select { width: 100%; font: 15px "Courier New", monospace;
    padding: 5px 7px; border: 1px solid #8a8069; background: #efe7d2;
    color: #241f18; }
  .file .two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .file .hint { font-size: 12px; color: #5a5142; margin-top: 2px; }
  .file button { margin-top: 16px; font: bold 15px "Courier New", monospace;
    padding: 8px 18px; border: 1px solid #241f18; background: #c6bb9c;
    color: #241f18; cursor: pointer; }
  .file button[disabled] { opacity: .45; cursor: not-allowed; }
  .file .out { margin-top: 14px; font-size: 14px; }
  .file .bad { background: #f2e3c4; border-left: 4px solid #b03024;
               padding: 8px 11px; margin: 6px 0; }
  .file .warn { background: #f2ecd6; border-left: 4px solid #b8860b;
                padding: 8px 11px; margin: 6px 0; }
  .file textarea { width: 100%; height: 84px; font: 12px/1.35 "Courier New",
    monospace; padding: 6px 7px; border: 1px solid #8a8069; background: #efe7d2;
    color: #241f18; resize: vertical; word-break: break-all; }
  .file .cart { border: 1px dashed #8a8069; padding: 12px 14px; margin: 0 0 18px; }
  .file .cart h2 { font-size: 14px; margin: 0 0 4px; letter-spacing: .09em;
    text-transform: uppercase; color: #5a5142; }
  .file .cart button { margin-top: 10px; margin-right: 8px; }
  /* What the cartridge supplied. Marked so it is visibly not something you
     were asked to know -- and still editable, because a derived answer you
     cannot correct is worse than one you were asked for. */
  .file .from-dtc { border-left: 3px solid #8a8069; padding-left: 11px;
    margin: 12px 0; }
  .file .from-dtc label i, .file label i { font-style: normal;
    text-transform: none; letter-spacing: 0; color: #8a8069; }
  .file .wps { font-size: 13px; margin-top: 10px; }
  .file .wps table { border-collapse: collapse; width: 100%; }
  .file .wps td, .file .wps th { padding: 2px 8px 2px 0; text-align: left;
    font-weight: normal; }
  .file .wps th { color: #5a5142; font-size: 11px; letter-spacing: .07em;
    text-transform: uppercase; }
  .file .wps .n { text-align: right; }
  /* A SIBLING OF THE ROW, NOT A CHILD. `.board .row` is flex, so the detail
     box was squeezed into it as another column and never appeared -- "just
     tried to open a flightplan.. was unable". */
  .file .detail { margin: 0 0 14px; font-size: 13px; background: #efe7d2;
    border-left: 4px solid #8a8069; padding: 8px 11px; }
  .file .detail dt { color: #5a5142; font-size: 11px; letter-spacing: .07em;
    text-transform: uppercase; margin-top: 6px; }
  .file .detail dd { margin: 0; }
  /* The inspect button is a link, like remove -- not another beige box. It
     shared a class name with the box and inherited its styling. */
  .file .board .peek { margin: 0; font-size: 12px; background: none;
    border: 0; text-decoration: underline; padding: 0 4px; cursor: pointer;
    color: #241f18; }
  .file .map { position: relative; overflow: hidden; margin: 10px 0 2px;
    border: 1px solid #8a8069; background: #cfd9c4; height: 520px; }
  .file .map img { position: absolute; width: 256px; height: 256px; }
  .file .map svg { position: absolute; inset: 0; width: 100%; height: 100%; }
  .file .map .attrib { position: absolute; right: 3px; bottom: 2px;
    font-size: 10px; background: rgba(239,231,210,.8); padding: 0 4px; }
  .file .miss { color: #b03024; }
  /* His own steerpoint: not published, not wrong. */
  .file .own  { color: #1d4e89; }
  .file .ok { background: #e2ecd6; border-left: 4px solid #4a7a24;
              padding: 8px 11px; margin: 6px 0; }
  .file .board { margin-top: 22px; border-top: 1px solid #8a8069;
                 padding-top: 10px; font-size: 14px; }
  .file .board .row.on { background: #efe7d2; outline: 2px solid #8a8069; }
  .file .board .row { display: flex; gap: 10px; align-items: baseline;
                      padding: 4px 0; }
  .file .board b { font-size: 17px; }
  .file .board .rt { color: #2f4a24; font-size: 13px; }
  .file .board .drop { margin-left: auto; font-size: 12px; background: none;
    border: 1px solid #8a8069; padding: 2px 8px; cursor: pointer; margin: 0; }
"""


def build() -> str:
    return f"""<title>File a flight plan</title>
<style>{STYLE}</style>
<div class="file">
  <h1>FILE A FLIGHT PLAN</h1>
  <div class="sub">Goes on the board the controller reads.</div>

  <div class="col-l">
  <div class="cart">
    <h2>DKS data cartridge import</h2>
    <textarea id="dtc" spellcheck="false"
      placeholder="RQsAAB+LCAAAAAAAAAPdVt..."></textarea>

    <button id="read" type="button">Read cartridge</button>
    <div id="cartout"></div>
  </div>

  <form id="f" autocomplete="off">

    <div class="two">
      <div><label>label</label>
        <input name="label" placeholder="Domino" required>
        <div class="hint">One word, no digits.</div></div>
    </div>
    <label>task — what he is DOING</label>
    <input name="task" placeholder="Transit and recovery" required>


    <!-- WHAT A PLAN IS, after migration 031: a label, the legs, and the task.
         The boxes that used to sit here asked for four things that were not
         flight-plan fields at all:

           name         a key. Generated from the label now -- two
                        hand-authored identifiers for one plan was one too
                        many, and the label is the one with a reason: it has to
                        survive being said out loud through Whisper.
           origin       "determined at request time". He calls Clearance from a
                        parking spot; asking him to have written down where he
                        is standing is asking him to tell you what you can see.
           cruise_ft    "there should be no cruise alt in flight plan". Each
                        leg carries its own.
           approach     "We should not define an approach in the flight plan."
                        Which arrival you fly is a fact about your CLEARANCE,
                        and this selector is what let the bridge read its own
                        procedure out of a plan row -- #131, which cost a
                        sortie flown as a talkdown after the pilot asked for an
                        ILS.

         The route is shown back rather than asked for, because the cartridge
         has it and a form that asks twice teaches you to distrust the answer
         it already holds. -->
    <div class="from-dtc" id="derived">
      <label>route <i>read from the cartridge</i></label>
      <input name="route" list="fixes" readonly>
      <datalist id="fixes"></datalist>
      <div class="hint" id="fixhint">the last leg is the destination</div>
    </div>
    <button id="go" type="submit">File it</button>
  </form>

  <div class="out" id="out"></div>
  <div class="board" id="board"></div>
  </div>

  <div class="col-r">
    <div id="pane"><div class="empty">Pick <b>inspect</b> on a filed plan and
      it appears here &mdash; what the controller reads, and where it goes.</div></div>
  </div>
</div>

<script>
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g,
  c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));

// THE LEGS ARE NOT A FORM FIELD, and that is why filing a cartridge failed
// with "a plan needs at least one leg" while the page showed five of them.
// `values()` is built from FormData -- form INPUTS -- and the legs come from
// the cartridge, so they were displayed and then dropped on the floor.
let LEGS = [];

function values() {{
  const o = {{}};
  new FormData($('#f')).forEach((v, k) => o[k] = v);
  o.legs = LEGS;
  return o;
}}

// THE PAGE NEVER JUDGES. Every verdict below is the director's, rendered.
async function say(res) {{
  const bad = res.refused || [], warn = res.warnings || [];
  let h = '';
  if (res.filed) h += `<div class="ok">Filed as <b>${{esc(res.name)}}</b>. `
    + `A pilot can ask for it by name on the radio now.</div>`;
  bad.forEach(b => h += `<div class="bad">${{esc(b)}}</div>`);
  warn.forEach(w => h += `<div class="warn">${{esc(w)}}</div>`);
  $('#out').innerHTML = h;
  // A refusal disables the button rather than hiding it: the reason stays on
  // screen next to the thing that caused it.
  $('#go').disabled = bad.length > 0;
}}

let pending;
async function check() {{
  clearTimeout(pending);
  pending = setTimeout(async () => {{
    const r = await fetch('/plans/check', {{method: 'POST',
      headers: {{'content-type': 'application/json'}},
      body: JSON.stringify(values())}});
    say(await r.json());
  }}, 350);
}}
$('#f').addEventListener('input', check);

$('#f').addEventListener('submit', async e => {{
  e.preventDefault();
  const r = await fetch('/plans', {{method: 'POST',
    headers: {{'content-type': 'application/json'}},
    body: JSON.stringify(values())}});
  const res = await r.json();
  await say(res);
  if (res.filed) {{ $('#f').reset(); board(); }}
}});

async function board() {{
  const r = await fetch('/plans');
  const plans = (await r.json()).plans || [];
  $('#board').innerHTML = `<label>on the board — ${{plans.length}}</label>` +
    plans.map(p => `<div class="row"><b>${{esc(p.label || p.name)}}</b>`
      + `<span>${{esc(p.task || '')}}</span>`
      + `<span class="rt">${{esc(p.origin)}}&rarr;${{esc(p.destination)}}`
      + ` ${{(p.cruise_ft || 0).toLocaleString()}} ft</span>`
      + `<button class="peek" data-n="${{esc(p.name)}}">inspect</button>`
      + `<button class="drop" data-n="${{esc(p.name)}}">remove</button></div>`)
      .join('') || '<div class="hint">nothing filed</div>';
  document.querySelectorAll('button.peek').forEach(
    b => b.onclick = () => look(b.dataset.n));
  document.querySelectorAll('.drop').forEach(b => b.onclick = async () => {{
    const r = await fetch('/plans/' + encodeURIComponent(b.dataset.n),
                          {{method: 'DELETE'}});
    const res = await r.json();
    if (!res.removed) say(res); else {{ $('#out').innerHTML = ''; board(); }}
  }});
}}

// READ A CARTRIDGE INTO THE FORM. The server decodes it -- gzip inside base64 --
// and hands back a draft. Everything after that is the ordinary path.
$('#read').onclick = async () => {{
  const v = values();
  const r = await fetch('/dtc', {{method: 'POST',
    headers: {{'content-type': 'application/json'}},
    body: JSON.stringify({{cartridge: $('#dtc').value, label: v.label}})}});
  const res = await r.json();
  if (res.refused) {{ await say(res); return; }}

  const d = res.draft || {{}};
  // ONLY THE BOXES THAT STILL EXIST, and this is why "Read Cartridge" stopped
  // working: the loop wrote `origin`, `destination` and `cruise_ft` into
  // inputs that migration 031 removed from the form, so `$(...)` came back
  // null, `.value =` threw, and everything after it -- the waypoint table, the
  // notes, the validation -- never ran. A dead handler and a silent page.
  //
  // Guarded rather than trimmed to a fixed list: the next field to go should
  // not take the reader with it.
  for (const [k, val] of Object.entries(d)) {{
    const el = $(`[name=${{k}}]`);
    if (el && val != null && val !== '' && !el.value) el.value = val;
  }}
  // The route is shown back, not typed, so it is set whether or not it is empty.
  if ($('[name=route]')) $('[name=route]').value = d.route || '';
  LEGS = d.legs || [];
  if (!$('[name=task]').value) $('[name=task]').value = d.task || '';

  const wps = res.waypoints || [];
  let h = `<div class="wps"><table><tr><th>#</th><th>name</th>`
    + `<th class="n">lat</th><th class="n">lon</th><th class="n">alt</th></tr>`
    + wps.map(w => `<tr><td>${{w.seq}}</td><td>${{esc(w.name || 'STPT')}}</td>`
        + `<td class="n">${{w.lat.toFixed(4)}}</td>`
        + `<td class="n">${{w.lon.toFixed(4)}}</td>`
        + `<td class="n">${{(w.alt_ft || 0).toLocaleString()}} ft</td></tr>`).join('')
    + `</table>`;
  if (res.notes) h += `<div class="detail"><dt>kneeboard notes</dt>`
    + `<dd>${{esc(res.notes)}}</dd></div>`;
  h += `</div>`;
  $('#cartout').innerHTML = h;

  // THE STEERPOINT CHECKBOX IS GONE, and it is worth saying what it did.
  //
  //     "What is the checkbox 'file his own named steerpoints' even for?"
  //
  // It pushed his private steerpoints into the SHARED fix table -- which is
  // exactly #129: that table is the published catalogue, the bridge replaces
  // it on every start, and a plan routing via FOO stopped resolving the moment
  // anything restarted. A plan carries its own fixes now, with their positions,
  // so there is nothing left to push and the box only offered a way to break
  // the thing it looked like it was helping.
  check();
}};

// A PICTURE OF THE ROUTE, from OpenStreetMap tiles laid out by hand.
//
//     "Maybe an open maps picture of the route?"
//
// NO MAP LIBRARY. Leaflet would be four lines here and a vendored megabyte
// there, and this needs no panning, no zooming and no interaction -- it needs
// one still picture of four points and the legs between them. Web Mercator is
// twenty lines, and the tiles come straight from OSM.
//
// The projection is the standard slippy-map one: longitude scales linearly,
// latitude through the Mercator log. Everything below is in TILE units at the
// chosen zoom, so a pixel is `t * 256` and the arithmetic stays in one frame --
// which is the whole trick to not getting this wrong.
const TILE = 256;
function proj(lat, lon, z) {{
  const n = Math.pow(2, z), r = lat * Math.PI / 180;
  return {{x: (lon + 180) / 360 * n,
          y: (1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * n}};
}}

function drawMap(el, pts) {{
  if (pts.length < 2) {{ el.innerHTML =
    '<div class="hint" style="padding:8px">no positions for these fixes</div>';
    return; }}
  const W = el.clientWidth || 700, H = el.clientHeight || 300;
  // ZOOM TO FIT, then step back one. Choosing the largest zoom whose span still
  // fits leaves the outermost fixes on the very edge, where a marker is half a
  // marker; one level out is the difference between a route on a map and a
  // route in a box.
  let z = 11;
  for (let t = 12; t >= 3; t--) {{
    const ps = pts.map(p => proj(p.lat, p.lon, t));
    const dx = (Math.max(...ps.map(p => p.x)) - Math.min(...ps.map(p => p.x))) * TILE;
    const dy = (Math.max(...ps.map(p => p.y)) - Math.min(...ps.map(p => p.y))) * TILE;
    if (dx < W * 0.82 && dy < H * 0.82) {{ z = t; break; }}
  }}
  const ps = pts.map(p => proj(p.lat, p.lon, z));
  const cx = (Math.max(...ps.map(p => p.x)) + Math.min(...ps.map(p => p.x))) / 2;
  const cy = (Math.max(...ps.map(p => p.y)) + Math.min(...ps.map(p => p.y))) / 2;
  // Where tile (0,0) of the world sits, in page pixels.
  const ox = W / 2 - cx * TILE, oy = H / 2 - cy * TILE;

  let h = '';
  const x0 = Math.floor(-ox / TILE), x1 = Math.floor((W - ox) / TILE);
  const y0 = Math.floor(-oy / TILE), y1 = Math.floor((H - oy) / TILE);
  const n = Math.pow(2, z);
  for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) {{
    if (y < 0 || y >= n) continue;
    const wx = ((x % n) + n) % n;
    h += `<img loading="lazy" src="https://tile.openstreetmap.org/${{z}}/${{wx}}`
      + `/${{y}}.png" style="left:${{ox + x * TILE}}px;top:${{oy + y * TILE}}px">`;
  }}
  const sx = p => ox + p.x * TILE, sy = p => oy + p.y * TILE;
  const line = ps.map(p => `${{sx(p)}},${{sy(p)}}`).join(' ');
  h += `<svg viewBox="0 0 ${{W}} ${{H}}" preserveAspectRatio="none">`
    + `<polyline points="${{line}}" fill="none" stroke="#b03024"`
    + ` stroke-width="2.5" stroke-linejoin="round"/>`
    + ps.map((p, i) => `<circle cx="${{sx(p)}}" cy="${{sy(p)}}" r="5"`
        + ` fill="#efe7d2" stroke="#241f18" stroke-width="2"/>`
        + `<text x="${{sx(p) + 9}}" y="${{sy(p) + 4}}" font="12px monospace"`
        + ` font-family="Courier New, monospace" font-size="12"`
        + ` stroke="#efe7d2" stroke-width="3" paint-order="stroke"`
        + ` fill="#241f18">${{esc(pts[i].name)}}</text>`).join('')
    + `</svg>`
    + `<div class="attrib">&copy; OpenStreetMap contributors</div>`;
  el.innerHTML = h;
}}

// INSPECT ONE. The board row says label and destination; this says everything
// the controller will actually read, and marks a route fix the sim does not
// hold -- which is the failure that reads as "no fix called KOBULETI" at the
// moment somebody asks for a clearance.
let showing = '';
async function look(name) {{
  const plans = ((await (await fetch('/plans')).json()).plans || []);
  const p = plans.find(x => x.name === name);
  const box = $('#pane');
  document.querySelectorAll('.board .row').forEach(r => r.classList.remove('on'));
  if (showing === name) {{
    showing = '';
    box.innerHTML = '<div class="empty">Pick <b>inspect</b> on a filed plan '
      + 'and it appears here.</div>';
    return;
  }}
  showing = name;
  const btn = document.querySelector(`.peek[data-n="${{CSS.escape(name)}}"]`);
  if (btn) btn.closest('.row').classList.add('on');
  if (!p) {{ box.innerHTML = '<div class="bad">not on the board</div>'; return; }}
  // WHERE the fixes are, not just what they are called -- the route has to be
  // drawable, and a name cannot be plotted.
  let where = {{}};
  try {{ where = (await (await fetch('/fixes')).json()).fixes || {{}}; }}
  catch (e) {{}}
  const known = Object.keys(where).map(s => s.toUpperCase());
  // A PLAN DEFINES ITS OWN FIXES, and it is where the private ones live.
  //
  // This asked ONE question -- "is it on the published table?" -- and marked
  // everything else red as "a clearance naming it would be refused". That was
  // true until #129 and is now exactly backwards: FOO, BAR and SPAM are the
  // pilot's own steerpoints, they live in `legs` with their positions, the
  // plan validates clean and clears. The page was calling a working plan
  // broken and drawing no map for it.
  //
  // Three states now, because there are three:
  //     published   on a plate or an aerodrome -- anybody can resolve it
  //     private     this plan defines it, with a position. His, and fine.
  //     unknown     neither. THAT is the one a clearance would be refused for.
  const mine = {{}};
  for (const l of (p.legs || [])) {{
    if (l && l.fix && l.lat != null && l.lon != null)
      mine[String(l.fix).toUpperCase()] = [l.lat, l.lon];
  }}
  const legs = String(p.route || '').split(',').map(s => s.trim())
    .filter(Boolean)
    .map(f => {{
      const u = f.toUpperCase();
      if (known.includes(u)) return esc(f);
      if (mine[u]) return `<span class="own">${{esc(f)}}</span>`;
      return `<span class="miss">${{esc(f)}} ?</span>`;
    }});
  box.innerHTML = `<div class="detail">`
    + `<dt>key</dt><dd>${{esc(p.name)}}</dd>`
    + `<dt>label</dt><dd>${{esc(p.label || '(none)')}}</dd>`
    + `<dt>task</dt><dd>${{esc(p.task || '(none)')}}</dd>`
    + `<dt>route</dt><dd>${{legs.join(' &rarr; ') || '(direct)'}}</dd>`
    // WHERE HE IS GOING, which had disappeared from this panel entirely.
    //
    //     "Route - shouldnt this include the final steerpoint which was
    //      Batumi? Maybe that was lost?"
    //
    // Not lost -- `route` is the ENROUTE portion and the destination is the
    // last leg, so it was correct and invisible, which is its own kind of
    // wrong. It gets its own row rather than being appended to the route,
    // because "via" and "to" are different things and a controller reads them
    // differently.
    + `<dt>to</dt><dd>${{esc(p.destination || '(none)')}}</dd>`
    + `<dt>cruise</dt><dd>${{(p.cruise_ft || 0).toLocaleString()}} ft</dd>`
    + `<dt>recovery</dt><dd>${{esc(p.approach || '(none)')}}</dd>`
    + (legs.some(l => l.includes('class="miss"'))
        ? `<div class="bad">red: on no chart and not in this plan — it would `
          + `be refused</div>` : '')
    + (legs.some(l => l.includes('class="own"'))
        ? `<div class="hint">blue: this plan's own steerpoint.</div>` : '')
    + `</div>`
    + `<div class="map" id="map-${{esc(name)}}"></div>`;

  // Drawn AFTER the box is in the document, because the tile grid is sized
  // from the element's real width and an element nobody has laid out yet has
  // none. Only the fixes we have a position for -- a route naming one we do
  // not is exactly the case the red marking above is for, and half a line is
  // more honest than a straight one through a place we cannot find.
  // THE PLAN'S OWN POSITIONS FIRST. It carries lat/lon per leg since #129, so
  // a route of private steerpoints is perfectly drawable -- and used to render
  // as "no positions for these fixes" and an empty box, because this looked
  // only at the published table.
  const pts = String(p.route || '').split(',').map(s => s.trim())
    .filter(Boolean)
    .map(f => ({{name: f, ll: mine[f.toUpperCase()] || where[f.toLowerCase()]}}))
    .filter(o => Array.isArray(o.ll) && o.ll.length === 2)
    .map(o => ({{name: o.name, lat: o.ll[0], lon: o.ll[1]}}));
  drawMap(document.getElementById('map-' + name), pts);
}}

// The route box offers what the DIRECTOR holds, so a typo is a thing you
// cannot make rather than a thing you are told about afterwards.
(async () => {{
  try {{
    const f = (await (await fetch('/plans/fixes')).json()).fixes || [];
    $('#fixes').innerHTML = f.map(n =>
      `<option value="${{esc(n.toUpperCase())}}">`).join('');
    $('#fixhint').textContent = `${{f.length}} fixes the sim holds`;
    const a = (await (await fetch('/plans/approaches')).json()).approaches || [];
    $('select[name=approach]').innerHTML = '<option value="">(none)</option>' +
      a.map(n => `<option>${{esc(n)}}</option>`).join('');
  }} catch (e) {{ $('#fixhint').textContent = 'could not reach the director'; }}
  board();
}})();
</script>
"""
