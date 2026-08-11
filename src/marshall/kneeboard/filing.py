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
          background: #d9cfb4; padding: 20px 22px; max-width: 760px; }
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
  .file .wps { font-size: 13px; margin-top: 10px; }
  .file .wps table { border-collapse: collapse; width: 100%; }
  .file .wps td, .file .wps th { padding: 2px 8px 2px 0; text-align: left;
    font-weight: normal; }
  .file .wps th { color: #5a5142; font-size: 11px; letter-spacing: .07em;
    text-transform: uppercase; }
  .file .wps .n { text-align: right; }
  .file .look { margin-top: 8px; font-size: 13px; background: #efe7d2;
    border-left: 4px solid #8a8069; padding: 8px 11px; }
  .file .look dt { color: #5a5142; font-size: 11px; letter-spacing: .07em;
    text-transform: uppercase; margin-top: 6px; }
  .file .look dd { margin: 0; }
  .file .miss { color: #b03024; }
  .file .ok { background: #e2ecd6; border-left: 4px solid #4a7a24;
              padding: 8px 11px; margin: 6px 0; }
  .file .board { margin-top: 22px; border-top: 1px solid #8a8069;
                 padding-top: 10px; font-size: 14px; }
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
  <div class="sub">Goes on the board the controller reads. A pilot asks for it
    by its <b>label</b>, out loud, so the label is one word and the rules about
    it are the director's — this page only asks.</div>

  <div class="cart">
    <h2>from a data cartridge</h2>
    <div class="hint">Paste what DKS put on your clipboard. It fills the form
      below — it does not file anything, because a cartridge that filed itself
      would be a second filing path and the two would disagree the first time a
      rule changed.</div>
    <textarea id="dtc" spellcheck="false"
      placeholder="RQsAAB+LCAAAAAAAAAPdVt..."></textarea>
    <label style="display:inline; text-transform:none; letter-spacing:0">
      <input type="checkbox" id="sp" style="width:auto"> file his own named
      steerpoints (FOO, BAR…) as fixes for this sortie</label>
    <div class="hint">His names are SHARED, not published — he typed them and
      they are on his HSI. They belong to one aeroplane and die with the sortie:
      the bridge's catalogue push at start-up takes them off the fix table.</div>
    <button id="read" type="button">Read cartridge</button>
    <div id="cartout"></div>
  </div>

  <form id="f" autocomplete="off">
    <div class="two">
      <div><label>label — what a pilot says</label>
        <input name="label" placeholder="Domino" required>
        <div class="hint">One word, no digits. "Samovar One" is how the wrong
          sortie gets cleared.</div></div>
      <div><label>name — the key</label>
        <input name="name" placeholder="362nd-kobuleti-batumi" required>
        <div class="hint">lowercase, hyphens. Goes in URLs and migrations.</div></div>
    </div>
    <label>task — what he is DOING</label>
    <input name="task" placeholder="Transit and radar recovery" required>
    <div class="hint">Not where he is going: origin and destination have their
      own boxes and are read from them. Repeating a place name here makes this
      plan outrank the board on any request that mentions it.</div>
    <div class="two">
      <div><label>origin</label><input name="origin" placeholder="Kobuleti" required></div>
      <div><label>destination</label><input name="destination" placeholder="Batumi" required></div>
    </div>
    <label>route — fixes, comma separated</label>
    <input name="route" list="fixes" placeholder="KOBULETI, INITIAL, BATUMI" required>
    <datalist id="fixes"></datalist>
    <div class="hint" id="fixhint">the places the sim actually holds</div>
    <div class="two">
      <div><label>cruise altitude, feet</label>
        <input name="cruise_ft" type="number" step="100" placeholder="5000" required></div>
      <div><label>approach on arrival</label>
        <select name="approach"><option value="">(none)</option></select></div>
    </div>
    <button id="go" type="submit">File it</button>
  </form>

  <div class="out" id="out"></div>
  <div class="board" id="board"></div>
</div>

<script>
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g,
  c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));

function values() {{
  const o = {{}};
  new FormData($('#f')).forEach((v, k) => o[k] = v);
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
      + `<button class="look" data-n="${{esc(p.name)}}">inspect</button>`
      + `<button class="drop" data-n="${{esc(p.name)}}">remove</button>`
      + `<div id="look-${{esc(p.name)}}"></div></div>`)
      .join('') || '<div class="hint">nothing filed</div>';
  document.querySelectorAll('button.look').forEach(
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
    body: JSON.stringify({{cartridge: $('#dtc').value,
                          name: v.name, label: v.label,
                          approach: v.approach,
                          steerpoints: $('#sp').checked}})}});
  const res = await r.json();
  if (res.refused) {{ await say(res); return; }}

  const d = res.draft || {{}};
  // Only what the cartridge actually knows. A label and a key are a human's to
  // choose and are left alone if already typed.
  for (const k of ['origin', 'destination', 'route', 'cruise_ft']) {{
    if (d[k] != null && d[k] !== '') $(`[name=${{k}}]`).value = d[k];
  }}
  if (!$('[name=task]').value) $('[name=task]').value = d.task || '';

  const wps = res.waypoints || [];
  let h = `<div class="wps"><table><tr><th>#</th><th>name</th>`
    + `<th class="n">lat</th><th class="n">lon</th><th class="n">alt</th></tr>`
    + wps.map(w => `<tr><td>${{w.seq}}</td><td>${{esc(w.name || 'STPT')}}</td>`
        + `<td class="n">${{w.lat.toFixed(4)}}</td>`
        + `<td class="n">${{w.lon.toFixed(4)}}</td>`
        + `<td class="n">${{(w.alt_ft || 0).toLocaleString()}} ft</td></tr>`).join('')
    + `</table>`;
  const m = res.misc || {{}};
  if (m.ils_mhz) h += `<div class="hint">cartridge also carries ILS `
    + `${{esc(m.ils_mhz)}} / course ${{esc(m.ils_course)}}, TACAN `
    + `${{esc(m.tacan)}}X — those are the jet's, not the plan's.</div>`;
  if (res.notes) h += `<div class="look"><dt>kneeboard notes</dt>`
    + `<dd>${{esc(res.notes)}}</dd></div>`;
  h += `</div>`;
  $('#cartout').innerHTML = h;

  if ($('#sp').checked) {{
    const p = await (await fetch('/dtc/steerpoints', {{method: 'POST',
      headers: {{'content-type': 'application/json'}},
      body: JSON.stringify({{cartridge: $('#dtc').value}})}})).json();
    if (p.refused) await say(p);
    else if ((p.pushed || []).length)
      $('#cartout').innerHTML += `<div class="ok">his steerpoints, for this `
        + `sortie: ${{esc(p.pushed.join(', '))}}</div>`;
  }}
  check();
}};

// INSPECT ONE. The board row says label and destination; this says everything
// the controller will actually read, and marks a route fix the sim does not
// hold -- which is the failure that reads as "no fix called KOBULETI" at the
// moment somebody asks for a clearance.
async function look(name) {{
  const plans = ((await (await fetch('/plans')).json()).plans || []);
  const p = plans.find(x => x.name === name);
  const box = document.getElementById('look-' + name);
  if (!box) return;
  if (box.innerHTML) {{ box.innerHTML = ''; return; }}
  if (!p) {{ box.innerHTML = '<div class="bad">not on the board</div>'; return; }}
  let known = [];
  try {{ known = ((await (await fetch('/plans/fixes')).json()).fixes || [])
                  .map(s => s.toUpperCase()); }} catch (e) {{}}
  const legs = String(p.route || '').split(',').map(s => s.trim())
    .filter(Boolean)
    .map(f => known.length && !known.includes(f.toUpperCase())
      ? `<span class="miss">${{esc(f)}} ?</span>` : esc(f));
  box.innerHTML = `<div class="look">`
    + `<dt>key</dt><dd>${{esc(p.name)}}</dd>`
    + `<dt>said on the radio</dt><dd>${{esc(p.label || '(none)')}}</dd>`
    + `<dt>task</dt><dd>${{esc(p.task || '(none)')}}</dd>`
    + `<dt>route</dt><dd>${{legs.join(' &rarr; ') || '(none)'}}</dd>`
    + `<dt>cruise</dt><dd>${{(p.cruise_ft || 0).toLocaleString()}} ft</dd>`
    + `<dt>recovery</dt><dd>${{esc(p.approach || '(none)')}}</dd>`
    + (legs.some(l => l.includes('miss'))
        ? `<div class="bad">a fix in red is not on the sim's table — a `
          + `clearance naming it would be refused</div>` : '')
    + `</div>`;
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
