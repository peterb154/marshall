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
      + `<button class="drop" data-n="${{esc(p.name)}}">remove</button></div>`)
      .join('') || '<div class="hint">nothing filed</div>';
  document.querySelectorAll('.drop').forEach(b => b.onclick = async () => {{
    const r = await fetch('/plans/' + encodeURIComponent(b.dataset.n),
                          {{method: 'DELETE'}});
    const res = await r.json();
    if (!res.removed) say(res); else {{ $('#out').innerHTML = ''; board(); }}
  }});
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
