"""The board a controller reads, and the page a pilot files onto.

    "A plan can be filed without touching the database by hand."  -- [UI-1] #22

A DESK page, not a kneeboard page: it is used before the sortie with a keyboard,
unlike everything else this server renders. It still has to LAY OUT at kneeboard
width, because OpenKneeboard is where somebody will inevitably open it.

Three things decide its whole shape.

**The legs table IS the plan.** Not a summary of it, not a `route` string beside
it. After migration 031 a plan is a label, its legs and a task; `route` and
`destination` are derived at read time by `director/tools/filing.py::derived`
and exist so a CONTROLLER can say them out loud. Neither is a field on this
page. Showing a derived string beside the thing it was derived from is what made
a pilot ask why the route stopped one steerpoint short of where he was going --
twice, in two sittings -- and then ask the question underneath it: "why there is
a 'Route' and not just a list of coordinates with altitudes?" There is not; there
is a list of coordinates with altitudes, and that is now what he sees.
`destination`
appears in exactly one place, a board row, and only in its speech role -- "IFR
to Nellis".

**It decides nothing.** Every refusal and every warning on this page came out of
the director's `/plans/check`, while you type and again when you press the
button. A form that knows the rules is a second copy of them and the two would
disagree the first time a fix moved. The page is a way of TALKING to the check.

**A leg carries its own position, so nothing else needs asking.** The page used
to fetch `/fixes` to decide whether a route was drawable, and to colour names by
whether the published catalogue held them -- which marked a pilot's own
steerpoints as broken (#129) and marked real Nevada fixes as private purely
because that catalogue was not loaded (#141). A colour that means two things
means neither. The table shows what the plan holds; a leg with no position says
so, in one place, in the row it belongs to.

**A plan on the board is amendable, and its KEY is not.**

    "maybe we should just be able to edit the label, but the name key is
     immutable (unless deleted)"

Opening a row gives you its label, its task and an import box that REPLACES its
steerpoints. It takes a DKS kneeboard LINK or a data cartridge, and the server
decides which by looking at what was pasted -- a design id is a UUID and a
cartridge is base64, so neither can be mistaken for the other and there is no
second button to press by mistake. The link is the only way in for an aeroplane
that cannot export a cartridge, which is every Phantom on the ramp. All three go back through the same two calls a new plan makes
-- `/plans/check` while you look at it, `/plans` when you press Save -- with
`updating` naming the row, which is the only thing that distinguishes an
amendment from a filing. The key was generated from the label once and stays
put; it is what `assigned_plans.template` points at, and it appears nowhere on
this page because nobody types it and there is nothing to do with it.

While an imported route is staged BOTH leg tables are on screen and the map draws the
incoming one. Replacing the legs is the largest thing that can be done to a
plan -- the legs ARE the plan -- so it is shown before it happens rather than
reported after.

No commentary in the rendered page. The reasoning lives here and in
docs/ISSUES.md, which is where it was asked for.
"""

from __future__ import annotations

STYLE = """
  /* border-box, and it is not a nicety: every input here is `width: 100%`
     inside a grid column, and under content-box each one overflows its column
     by its own padding and border. */
  .file, .file * { box-sizing: border-box; }
  .file { font: 15px/1.5 "Courier New", monospace; color: #241f18;
          background: #d9cfb4; padding: 18px 20px 40px; max-width: 880px; }
  .file [hidden] { display: none !important; }
  .file h1 { font-size: 21px; margin: 0 0 14px; letter-spacing: 1.5px; }
  .file h2 { font-size: 12px; margin: 0 0 8px; letter-spacing: .09em;
             text-transform: uppercase; color: #5a5142; font-weight: normal; }
  .file .card { border: 1px solid #8a8069; padding: 12px 14px; margin: 0 0 16px; }
  .file label { display: block; margin: 0 0 2px; font-size: 12px;
                letter-spacing: .09em; text-transform: uppercase;
                color: #5a5142; }
  .file input { width: 100%; font: 15px "Courier New", monospace;
    padding: 5px 7px; border: 1px solid #8a8069; background: #efe7d2;
    color: #241f18; }
  .file textarea { width: 100%; height: 76px; font: 12px/1.35 "Courier New",
    monospace; padding: 6px 7px; border: 1px solid #8a8069; background: #efe7d2;
    color: #241f18; resize: vertical; word-break: break-all; }
  .file .two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
               margin-bottom: 12px; }
  /* One column when the window is a kneeboard rather than a desk. */
  @media (max-width: 620px) { .file .two { grid-template-columns: 1fr; } }
  .file .acts { margin-top: 12px; display: flex; gap: 12px;
                align-items: baseline; }
  .file button { font: bold 15px "Courier New", monospace; padding: 7px 16px;
    border: 1px solid #241f18; background: #c6bb9c; color: #241f18;
    cursor: pointer; }
  .file button[disabled] { opacity: .45; cursor: not-allowed; }
  .file button.link { font-weight: normal; font-size: 13px; background: none;
    border: 0; padding: 0; text-decoration: underline; }
  .file .out p { margin: 6px 0; padding: 7px 10px; }
  .file .bad { background: #f2e3c4; border-left: 4px solid #b03024; }
  .file .warn { background: #f2ecd6; border-left: 4px solid #b8860b; }
  .file .ok { background: #e2ecd6; border-left: 4px solid #4a7a24; }
  .file .miss { color: #b03024; }
  .file .note { font-size: 12px; color: #5a5142; margin: 4px 0 0; }

  .file table.legs { border-collapse: collapse; width: 100%; font-size: 13px;
                     margin-top: 6px; }
  .file table.legs td, .file table.legs th { padding: 3px 10px 3px 0;
    text-align: left; font-weight: normal; border-bottom: 1px solid #c6bb9c; }
  .file table.legs th { color: #5a5142; font-size: 11px; letter-spacing: .07em;
    text-transform: uppercase; }
  .file table.legs .n { text-align: right; }

  /* Twenty lines of Web Mercator over OSM tiles -- see drawMap. No library,
     so nothing here needs a CDN OpenKneeboard's Chromium may not reach. */
  .file .map { position: relative; overflow: hidden; margin: 12px 0 0;
    border: 1px solid #8a8069; background: #cfd9c4; height: 380px; }
  .file .map img { position: absolute; width: 256px; height: 256px; }
  .file .map svg { position: absolute; inset: 0; width: 100%; height: 100%; }
  .file .map .attrib { position: absolute; right: 3px; bottom: 2px;
    font-size: 10px; background: rgba(239,231,210,.8); padding: 0 4px; }

  .file .row { display: flex; gap: 10px; align-items: baseline; padding: 6px 0;
    border-bottom: 1px solid #c6bb9c; cursor: pointer; }
  .file .row:hover { background: #e2dbc3; }
  .file .row b { font-size: 17px; letter-spacing: .5px; }
  /* min-width:0 or a long task refuses to shrink and shoves the destination
     off the end of the row. */
  .file .row .task { color: #5a5142; font-size: 13px; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap; flex: 1 1 auto; min-width: 0; }
  .file .row .to { margin-left: auto; color: #2f4a24; font-size: 13px;
    white-space: nowrap; }
  .file .row .rm { font-size: 12px; font-weight: normal; padding: 1px 8px;
    background: none; border: 1px solid #8a8069; }
  .file .exp { padding: 4px 0 16px; }
  .file .exp h2 { margin: 16px 0 4px; }
  .file .exp textarea { height: 58px; }
"""

BODY = """
<div class="file">
  <h1>FLIGHT PLANS</h1>

  <section class="card">
    <h2>Import a route</h2>
    <p class="note">Paste a DKS <b>kneeboard link</b> or a <b>data cartridge</b>.
      A cartridge is an F-16 thing -- an aeroplane that cannot export one, like
      the Phantom, files by link.</p>
    <textarea id="dtc" spellcheck="false"
      placeholder="https://www.digitalkneeboardsimulator.com/okb?design=...
or RQsAAB+LCAAAAAAAAAPdVt..."></textarea>
    <div class="acts"><button id="read" type="button">Read route</button></div>
    <div class="out" id="readout"></div>
  </section>

  <form class="card" id="draft" autocomplete="off" hidden>
    <h2>To file</h2>
    <div class="two">
      <div><label for="lab">Label</label>
        <input id="lab" name="label" placeholder="Domino" required></div>
      <div><label for="tsk">Task</label>
        <input id="tsk" name="task" placeholder="Transit and recovery" required></div>
    </div>
    <div id="draftlegs"></div>
    <div class="out" id="verdict"></div>
    <div class="acts">
      <button id="go" type="submit">File it</button>
      <button id="discard" type="button" class="link">discard</button>
    </div>
    <div class="map" id="draftmap"></div>
  </form>

  <div class="out" id="filed"></div>
  <section id="board"></section>
</div>

<script>
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

// THE LEGS ARE NOT A FORM FIELD. They come from the cartridge, and building the
// POST body out of FormData alone is how a five-leg plan was filed as "a plan
// needs at least one leg" while the page showed all five of them.
let LEGS = [];

const draft = () => ({label: $('#lab').value.trim(),
                      task: $('#tsk').value.trim(), legs: LEGS});

async function post(path, body) {
  const r = await fetch(path, {method: 'POST',
    headers: {'content-type': 'application/json'}, body: JSON.stringify(body)});
  return await r.json();
}

// THE PAGE NEVER JUDGES. Every line rendered here is the director's verdict.
function verdict(el, res) {
  const bad = res.refused || [], warn = res.warnings || [];
  el.innerHTML = bad.map(b => `<p class="bad">${esc(b)}</p>`).join('')
    + warn.map(w => `<p class="warn">${esc(w)}</p>`).join('');
  return bad.length;
}

// ---- the plan, as a table --------------------------------------------------
//
//     "that is a perfectly rich and accurate representation of a plan imo"
//
// -- of the raw cartridge waypoint list. So this is the same shape: a place, a
// level and a position, in the order he flies them. The last row is where he is
// going and is not marked as anything, because in the plan it is not: nothing
// in the engine branches on it.
function legsTable(legs) {
  if (!legs.length) return '<p class="miss">no legs</p>';
  return '<table class="legs"><tr><th>#</th><th>fix</th><th class="n">alt</th>'
    + '<th class="n">lat</th><th class="n">lon</th></tr>'
    + legs.map((l, i) => `<tr><td class="n">${i + 1}</td><td>${esc(l.fix)}</td>`
        + `<td class="n">${Number(l.alt_ft || 0).toLocaleString()} ft</td>`
        + (l.lat != null && l.lon != null
            ? `<td class="n">${l.lat.toFixed(4)}</td>`
              + `<td class="n">${l.lon.toFixed(4)}</td>`
            : '<td class="n miss" colspan="2">no position</td>')
        + '</tr>').join('')
    + '</table>';
}

// ---- the plan, as a picture ------------------------------------------------
//
//     "Maybe an open maps picture of the route?"
//
// NO MAP LIBRARY. This needs no panning, no zooming and no interaction -- one
// still picture of a handful of points and the legs between them. Web Mercator
// is twenty lines and the tiles come straight from OSM, so there is nothing to
// vendor and nothing OpenKneeboard's Chromium has to be able to reach for the
// ROUTE to draw: the line and the names are SVG on top, and survive the tiles
// failing.
//
// Everything below is in TILE units at the chosen zoom, so a pixel is `t * 256`
// and the arithmetic stays in one frame -- which is the trick to not getting
// this wrong.
const TILE = 256;
function proj(lat, lon, z) {
  const n = Math.pow(2, z), r = lat * Math.PI / 180;
  return {x: (lon + 180) / 360 * n,
          y: (1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * n};
}

// FROM THE PLAN'S OWN POSITIONS. A leg carries lat/lon since #129, so a route
// made entirely of a pilot's private steerpoints draws exactly like one made of
// published fixes -- it used to draw nothing at all, because this asked the
// published catalogue where each name was.
function drawMap(el, legs) {
  const pts = legs.filter(l => l.lat != null && l.lon != null)
    .map(l => ({name: l.fix, lat: l.lat, lon: l.lon}));
  const lost = legs.length - pts.length;
  if (!pts.length) { el.innerHTML =
    '<p class="note" style="padding:8px">no positions to draw</p>'; return; }
  const W = el.clientWidth || 700, H = el.clientHeight || 380;
  // ZOOM TO FIT, then step back one: the largest zoom whose span still fits
  // leaves the outermost fixes on the very edge, where a marker is half a
  // marker.
  let z = 11;
  for (let t = 12; t >= 3; t--) {
    const ps = pts.map(p => proj(p.lat, p.lon, t));
    const dx = (Math.max(...ps.map(p => p.x)) - Math.min(...ps.map(p => p.x))) * TILE;
    const dy = (Math.max(...ps.map(p => p.y)) - Math.min(...ps.map(p => p.y))) * TILE;
    if (dx < W * 0.82 && dy < H * 0.82) { z = t; break; }
  }
  const ps = pts.map(p => proj(p.lat, p.lon, z));
  const cx = (Math.max(...ps.map(p => p.x)) + Math.min(...ps.map(p => p.x))) / 2;
  const cy = (Math.max(...ps.map(p => p.y)) + Math.min(...ps.map(p => p.y))) / 2;
  // Where tile (0,0) of the world sits, in page pixels.
  const ox = W / 2 - cx * TILE, oy = H / 2 - cy * TILE;

  let h = '';
  const x0 = Math.floor(-ox / TILE), x1 = Math.floor((W - ox) / TILE);
  const y0 = Math.floor(-oy / TILE), y1 = Math.floor((H - oy) / TILE);
  const n = Math.pow(2, z);
  for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) {
    if (y < 0 || y >= n) continue;
    const wx = ((x % n) + n) % n;
    h += `<img loading="lazy" src="https://tile.openstreetmap.org/${z}/${wx}`
      + `/${y}.png" style="left:${ox + x * TILE}px;top:${oy + y * TILE}px">`;
  }
  const sx = p => ox + p.x * TILE, sy = p => oy + p.y * TILE;
  h += `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">`
    + `<polyline points="${ps.map(p => `${sx(p)},${sy(p)}`).join(' ')}"`
    + ` fill="none" stroke="#b03024" stroke-width="2.5" stroke-linejoin="round"/>`
    + ps.map((p, i) => `<circle cx="${sx(p)}" cy="${sy(p)}" r="5"`
        + ` fill="#efe7d2" stroke="#241f18" stroke-width="2"/>`
        + `<text x="${sx(p) + 9}" y="${sy(p) + 4}"`
        + ` font-family="Courier New, monospace" font-size="12"`
        + ` stroke="#efe7d2" stroke-width="3" paint-order="stroke"`
        + ` fill="#241f18">${esc(pts[i].name)}</text>`).join('')
    + '</svg>'
    + '<div class="attrib">&copy; OpenStreetMap contributors</div>';
  el.innerHTML = h;
  // A FACT ABOUT THE DRAWING, not a verdict about the plan -- half a line is
  // more honest than a straight one through a place we cannot find.
  if (lost) el.insertAdjacentHTML('afterend',
    `<p class="note">${lost} leg${lost > 1 ? 's' : ''} carries no position `
    + 'and is not drawn</p>');
}

// ---- reading a route -------------------------------------------------------
//
// TWO WIRE FORMATS, ONE BOX. The server decides which by looking at what was
// pasted -- a design id is a UUID and a cartridge is base64, and neither can be
// mistaken for the other -- so the pilot does not have to tell it, and there is
// no second button to press by mistake.
//
// From there it is the ordinary path either way: `/plans/check` while he looks
// at it, `/plans` when he presses the button. An importer that could file
// itself would be a second filing path and the two would disagree the first
// rule that changed.
$('#read').onclick = async () => {
  const res = await post('/dtc', {cartridge: $('#dtc').value});
  if (res.refused) { verdict($('#readout'), res); return; }
  // WHAT HE IMPORTED, when the source knows. A design id is a UUID and tells
  // him nothing; the aeroplane and the crew tell him at a glance whether this
  // is the sortie he meant. A cartridge carries none of that and says nothing.
  const d = res.design;
  // WHAT HE IMPORTED, and then what disagrees with us. The second is the half
  // worth reading: a frequency he cannot reach us on fails silently and in the
  // air, and this is the one moment his card and our ladder are both to hand.
  const bad = res.comms || [];
  $('#readout').innerHTML = (d
    ? '<p class="note">' + [d.name, d.aircraft,
        (d.crew || []).map(c => c.callsign).join(", "),
        d.home_plate && d.home_plate.field
          ? 'recovering ' + d.home_plate.field : ''
      ].filter(Boolean).join(' &middot; ') + '</p>'
    : '')
    + (bad.length
        ? '<p class="bad">Check his radio card:</p><ul class="bad">'
          + bad.map(b => '<li>' + b + '</li>').join('') + '</ul>'
        : '');
  LEGS = (res.draft || {}).legs || [];
  // HIS PROSE, where he wrote any. `task` comes off KneeboardNotes and is
  // editable rather than final -- the notes may be a checklist or nothing.
  if (!$('#tsk').value) $('#tsk').value = (res.draft || {}).task || '';
  $('#draftlegs').innerHTML = legsTable(LEGS);
  $('#verdict').innerHTML = '';
  $('#go').disabled = false;
  $('#draft').hidden = false;
  // AFTER it is in the document: the tile grid is sized from the element's real
  // width, and an element nobody has laid out yet has none.
  document.querySelectorAll('#draft .note').forEach(p => p.remove());
  drawMap($('#draftmap'), LEGS);
  $('#lab').focus();
};

$('#discard').onclick = () => {
  LEGS = [];
  $('#draft').hidden = true;
  $('#draft').reset();
  $('#verdict').innerHTML = '';
};

// CHECKED WHILE HE TYPES, and only once he has -- asking the director about an
// empty form returns a refusal for a label nobody has written yet, and a page
// that is red before you touch it teaches you to ignore red.
let pending;
$('#draft').addEventListener('input', () => {
  clearTimeout(pending);
  pending = setTimeout(async () => {
    const res = await post('/plans/check', draft());
    // A refusal DISABLES the button rather than hiding it, so the reason stays
    // on screen beside the thing that caused it.
    $('#go').disabled = verdict($('#verdict'), res) > 0;
  }, 350);
});

$('#draft').addEventListener('submit', async e => {
  e.preventDefault();
  const res = await post('/plans', draft());
  if (!res.filed) { $('#go').disabled = verdict($('#verdict'), res) > 0; return; }
  $('#filed').innerHTML = `<p class="ok">Filed as ${esc(res.name)}. A pilot can `
    + 'ask for it by name on the radio now.</p>'
    + (res.warnings || []).map(w => `<p class="warn">${esc(w)}</p>`).join('');
  $('#dtc').value = '';
  $('#discard').onclick();
  open_ = res.name;           // he lands on his own plan, drawn
  board();
});

// ---- the board -------------------------------------------------------------
//
// One row per plan, and the row opens IN PLACE. It used to open a panel in a
// second column, which at kneeboard width is below the fold -- you clicked
// something and nothing appeared to happen.
let open_ = '';
// The expanded plan, as the director last described it, and the legs a
// cartridge has been read for but which are not filed yet.
let OPEN = null, STAGED = null;
async function board() {
  const plans = ((await (await fetch('/plans')).json()).plans || []);
  $('#board').innerHTML = `<h2>On the board — ${plans.length}</h2>`
    + (plans.map(p => `<div class="row" data-n="${esc(p.name)}">`
        + `<b>${esc(p.label || p.name)}</b>`
        + `<span class="task">${esc(p.task || '')}</span>`
        // THE ONE PLACE A DESTINATION APPEARS, and only in the job it has:
        //
        //     "nothing special about it except perhaps when referring to the
        //      plan 'IFR flight to Nellis'"
        //
        // It is the last leg. It is in the table below like every other leg.
        + `<span class="to">&rarr; ${esc(p.destination || '')}</span>`
        + `<button class="rm" type="button" data-n="${esc(p.name)}">remove</button>`
        + '</div>'
        + `<div class="exp" id="exp-${esc(p.name)}"></div>`).join('')
       || '<p class="note">nothing filed</p>');
  if (open_ && !plans.some(p => p.name === open_)) open_ = '';
  OPEN = open_ ? plans.find(p => p.name === open_) : null;
  if (OPEN) expand(OPEN);
}

// ---- amending a plan that is already on the board --------------------------
//
// THE ROW IS NAMED, NOT THE LABEL. `updating` says which plan this is, so the
// director keys the write off that and never off the label being typed:
//
//     "maybe we should just be able to edit the label, but the name key is
//      immutable (unless deleted)"
//
// Which is also why the label refusal still works while you rename: the check
// drops THIS row from the board and compares against the rest, so renaming onto
// somebody else's label is refused there, by the same rule that refuses it when
// filing. Nothing here decides anything.
const edited = () => ({name: OPEN.name, updating: OPEN.name,
                       label: $('#ed-lab').value.trim(),
                       task: $('#ed-tsk').value.trim(),
                       legs: STAGED || OPEN.legs || []});

function expand(p) {
  const el = document.getElementById('exp-' + p.name);
  if (!el) return;
  el.innerHTML =
      '<div class="two">'
    + `<div><label for="ed-lab">Label</label>`
    + `<input id="ed-lab" value="${esc(p.label || '')}"></div>`
    + `<div><label for="ed-tsk">Task</label>`
    + `<input id="ed-tsk" value="${esc(p.task || '')}"></div>`
    + '</div>'
    // BOTH TABLES WHILE ONE IS WAITING TO REPLACE THE OTHER. The legs are the
    // plan, so replacing them is the largest thing this page can do to one --
    // and the only honest way to show it is the outgoing list beside the
    // incoming one, in the same table, before anything is written.
    + (STAGED
        ? '<h2>Steerpoints now</h2>' + legsTable(p.legs || [])
          + `<h2>Replacing with — ${STAGED.length} imported</h2>`
          + legsTable(STAGED)
          + '<div class="acts"><button class="link" id="ed-keep" '
          + 'type="button">keep the ones it has</button></div>'
        : '<h2>Steerpoints</h2>' + legsTable(p.legs || []))
    + '<h2>Replace steerpoints</h2>'
    + '<p class="note">A DKS kneeboard link or a data cartridge.</p>'
    + '<textarea id="ed-dtc" spellcheck="false" '
    + 'placeholder="https://www.digitalkneeboardsimulator.com/okb?design=...'
    + '&#10;or RQsAAB+LCAAAAAAAAAPdVt..."></textarea>'
    + '<div class="acts"><button id="ed-read" type="button">Read route'
    + '</button></div>'
    + '<div class="out" id="ed-readout"></div>'
    + '<div class="out" id="ed-verdict"></div>'
    + '<div class="acts"><button id="ed-save" type="button">Save</button></div>'
    + `<div class="map" id="m-${esc(p.name)}"></div>`;
  // THE ROUTE THAT IS ABOUT TO BE FILED, which is the staged one when there is
  // one -- a picture of the plan as it stands is not what he is deciding about.
  drawMap(document.getElementById('m-' + p.name), STAGED || p.legs || []);
}

async function checkEdit() {
  if (!OPEN || !$('#ed-save')) return;
  const res = await post('/plans/check', edited());
  $('#ed-save').disabled = verdict($('#ed-verdict'), res) > 0;
}

let epending;
$('#board').addEventListener('input', e => {
  if (e.target.id !== 'ed-lab' && e.target.id !== 'ed-tsk') return;
  clearTimeout(epending);
  epending = setTimeout(checkEdit, 350);
});

$('#board').addEventListener('click', async e => {
  if (e.target.id === 'ed-keep') { STAGED = null; await board(); return; }
  if (e.target.id === 'ed-read') {
    // THE SAME DECODER THE NEW-PLAN BOX USES. A second cartridge path would
    // read the same bytes into a different plan the first rule that changed.
    const res = await post('/dtc', {cartridge: $('#ed-dtc').value});
    if (res.refused) { verdict($('#ed-readout'), res); return; }
    STAGED = (res.draft || {}).legs || [];
    await board();
    // The warnings belong to the legs he is about to file, not the ones he
    // filed before -- so the check runs on the staged plan straight away.
    await checkEdit();
    return;
  }
  if (e.target.id === 'ed-save') {
    const res = await post('/plans', edited());
    if (!res.filed) {
      $('#ed-save').disabled = verdict($('#ed-verdict'), res) > 0;
      return;
    }
    STAGED = null;
    await board();
    // BESIDE THE THING THAT CHANGED. The board is a long page at kneeboard
    // width and a confirmation at the top of it is a confirmation off screen.
    const out = $('#ed-verdict');
    if (out) out.innerHTML = '<p class="ok">Saved.</p>'
      + (res.warnings || []).map(w => `<p class="warn">${esc(w)}</p>`).join('');
    return;
  }
  const rm = e.target.closest('.rm');
  if (rm) {
    const res = await (await fetch('/plans/' + encodeURIComponent(rm.dataset.n),
                                   {method: 'DELETE'})).json();
    if (res.removed) $('#filed').innerHTML = ''; else verdict($('#filed'), res);
    board();
    return;
  }
  const row = e.target.closest('.row');
  if (!row) return;
  open_ = open_ === row.dataset.n ? '' : row.dataset.n;
  // A cartridge staged against one plan is not staged against the next one.
  STAGED = null;
  board();
});

board();
</script>
"""


def build() -> str:
    # A DOCTYPE and a charset, which this page has never had. Without the first
    # it renders in quirks mode; without the second the em dashes the director
    # writes into its own refusals depend entirely on the response header being
    # believed. Both are one line and neither is worth debugging twice.
    #
    # BUILT BY CONCATENATION, not an f-string. The whole page used to be one
    # f-string, so every brace in the CSS and every `${...}` in the JS had to be
    # doubled -- 200 lines of JavaScript written in a dialect that is not
    # JavaScript, which no editor checks and which is a permanent invitation to
    # a syntax error nobody sees until the page is silent.
    return ('<!doctype html>\n<meta charset="utf-8">\n'
            "<title>Flight plans</title>\n<style>" + STYLE + "</style>\n" + BODY)
