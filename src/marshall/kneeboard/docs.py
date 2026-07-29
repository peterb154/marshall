"""The long-form docs, rendered as pages on the kneeboard server.

    "Can you put the findings and documentation on two pages of the web server
     so that I can read comfortably?"

`docs/WIRING.md` and the audit are the two documents a pilot reads AWAY from the
aeroplane -- one to understand how the thing is wired, one to decide what to fix
next. Both are long, both are full of diagrams, and neither is any use as raw
markdown in a terminal.

RENDERED PER REQUEST, like every other page on this server and for the same
reason: the charts were generated once at container start for months, and
editing one changed nothing until somebody bounced the server. Editing
`docs/WIRING.md` shows up on the next page turn.

MERMAID IS SERVED FROM DISK, not from a CDN. The kneeboard is a LAN thing and is
read inside OpenKneeboard's embedded Chromium, which cannot be assumed to have
the internet. `build/vendor/mermaid.min.js` is fetched once by `tools/vendor.sh`
and served from `/vendor/`; if it is missing the page falls back to the CDN and
says so in the corner, rather than silently showing a wall of diagram source.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from marshall import config

REPO = Path(__file__).resolve().parents[3]
VENDOR = config.BUILD_DIR / "vendor"
MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"

# The documents this server publishes: url slug -> (file, title, blurb).
PAGES: dict[str, tuple[str, str, str]] = {
    "wiring": (
        "docs/WIRING.md",
        "How Marshall is wired",
        "What talks to what, in what order, and which of the two brains "
        "produced the transmission you heard.",
    ),
    "audit": (
        "docs/AUDIT-2026-07-29.md",
        "Audit, 29 July 2026",
        "Thirty findings, each verified against the source and put to a "
        "skeptic told to refute it.",
    ),
}


def _slug(text: str, taken: set[str]) -> str:
    s = re.sub(r"<[^>]+>", "", text)
    s = re.sub(r"[^\w\s-]", "", s).strip().lower()
    s = re.sub(r"[\s_]+", "-", s) or "section"
    out, n = s, 1
    while out in taken:
        n += 1
        out = f"{s}-{n}"
    taken.add(out)
    return out


def render(slug: str) -> str:
    """One document as a standalone page. Raises KeyError for an unknown slug."""
    import markdown

    rel, title, blurb = PAGES[slug]
    src = REPO / rel
    if not src.exists():
        raise FileNotFoundError(src)
    text = src.read_text(encoding="utf-8")

    # Mermaid fences come out BEFORE the markdown parser sees them: it would
    # escape the arrows into a code block and the diagram would render as its
    # own source.
    blocks: list[str] = []

    def _stash(m: re.Match) -> str:
        blocks.append(m.group(1))
        return f"\n\nMERMAIDBLOCK{len(blocks) - 1}END\n\n"

    text = re.sub(r"```mermaid\n(.*?)```", _stash, text, flags=re.S)

    body = markdown.markdown(
        text, extensions=["tables", "fenced_code", "attr_list", "sane_lists"])

    body = re.sub(
        r"<p>MERMAIDBLOCK(\d+)END</p>",
        lambda m: f'<figure class="diagram"><pre class="mermaid">'
                  f'{html.escape(blocks[int(m.group(1))])}</pre></figure>',
        body)

    # Headings get ids so the rail can link to them, and so a finding can be
    # sent to somebody as a URL.
    nav: list[tuple[int, str, str]] = []
    taken: set[str] = set()

    def _head(m: re.Match) -> str:
        lvl, inner = int(m.group(1)), m.group(2)
        sid = _slug(inner, taken)
        nav.append((lvl, sid, re.sub(r"<[^>]+>", "", inner)))
        return f'<h{lvl} id="{sid}">{inner}</h{lvl}>'

    body = re.sub(r"<h([23])>(.*?)</h\1>", _head, body, flags=re.S)
    body = (body.replace("<table>", '<div class="scroll"><table>')
                .replace("</table>", "</table></div>"))

    rail = "\n".join(
        f'<a href="#{sid}">{html.escape(txt)}</a>'
        for lvl, sid, txt in nav if lvl == 2)

    others = "\n".join(
        f'<a class="other" href="/docs/{s}">{html.escape(PAGES[s][1])} &rarr;</a>'
        for s in PAGES if s != slug)

    local = (VENDOR / "mermaid.min.js").exists()
    script = "/vendor/mermaid.min.js" if local else MERMAID_CDN
    warn = "" if local else (
        '<p class="warn">mermaid is being loaded from the internet &mdash; run '
        '<code>tools/vendor.sh</code> to serve it from disk</p>')

    return _PAGE.format(title=html.escape(title), blurb=html.escape(blurb),
                        rail=rail, others=others, body=body,
                        script=script, warn=warn, css=_CSS)


def index() -> str:
    """The little chooser at /docs."""
    items = "\n".join(
        f'<a href="/docs/{s}"><b>{html.escape(t)}</b>'
        f'<span>{html.escape(b)}</span></a>'
        for s, (_f, t, b) in PAGES.items())
    return _INDEX.format(items=items, css=_CSS)


# --- the page ---------------------------------------------------------------
#
# An approach plate is the visual language this earns: monochrome, hairline
# rules, tabular figures, and every label doing a job. Light is chart stock,
# dark is the cockpit at night, and the accent is instrument amber in both.
_CSS = """
:root{
  --paper:#E9EAE6; --surface:#F3F4F1; --ink:#16181A; --ink-soft:#4B5157;
  --rule:#C6C9C3; --rule-soft:#DADCD6; --accent:#9C6414; --accent-ink:#7A4E10;
  --code-bg:#DFE1DC;
  --sans:ui-sans-serif,system-ui,"Segoe UI",Helvetica,Arial,sans-serif;
  --serif:ui-serif,Georgia,"Iowan Old Style","Times New Roman",serif;
  --mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme:dark){
  :root{--paper:#0E1114;--surface:#151A1E;--ink:#D7DADC;--ink-soft:#8B939A;
    --rule:#272D33;--rule-soft:#1E242A;--accent:#E0A040;--accent-ink:#EFBE72;
    --code-bg:#161B20}
}
*{box-sizing:border-box}
body{background:var(--paper);color:var(--ink);font-family:var(--serif);
  font-size:17px;line-height:1.68;margin:0;-webkit-font-smoothing:antialiased}
.wrap{display:grid;grid-template-columns:16rem minmax(0,1fr);gap:3.5rem;
  max-width:92rem;margin:0 auto;padding:0 2rem}
.rail{position:sticky;top:0;align-self:start;max-height:100vh;overflow-y:auto;
  padding:3rem 0;border-right:1px solid var(--rule-soft)}
.rail .eyebrow{font-family:var(--mono);font-size:.66rem;letter-spacing:.16em;
  text-transform:uppercase;color:var(--ink-soft);margin:0 0 .9rem}
.rail a{display:block;font-family:var(--sans);font-size:.83rem;line-height:1.35;
  color:var(--ink-soft);text-decoration:none;padding:.34rem 1rem .34rem .75rem;
  border-left:2px solid transparent;margin-left:-.75rem}
.rail a:hover{color:var(--ink);border-left-color:var(--accent)}
.rail a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.rail .other{margin-top:.5rem;color:var(--accent-ink);font-weight:600}
.rail hr{border:0;border-top:1px solid var(--rule-soft);margin:1.4rem 0}
main{padding:3rem 0 6rem;min-width:0}
main>*{max-width:70ch}
main>.scroll,main>figure,main>pre{max-width:none}
h1{font-family:var(--sans);font-size:2.5rem;line-height:1.06;font-weight:700;
  letter-spacing:-.025em;text-wrap:balance;margin:0 0 .6rem}
.blurb{font-family:var(--sans);font-size:.95rem;color:var(--ink-soft);
  margin:0 0 2.5rem;max-width:56ch}
h2{font-family:var(--sans);font-size:1.42rem;font-weight:650;letter-spacing:-.012em;
  text-wrap:balance;margin:4rem 0 1.05rem;padding-top:1.4rem;
  border-top:1px solid var(--rule)}
h3{font-family:var(--sans);font-size:1.02rem;font-weight:650;
  text-wrap:balance;margin:2.5rem 0 .65rem;color:var(--accent-ink)}
h4{font-family:var(--mono);font-size:.75rem;letter-spacing:.13em;
  text-transform:uppercase;color:var(--ink-soft);margin:1.9rem 0 .55rem}
p{margin:0 0 1.05rem}
a{color:var(--accent-ink)}
strong{font-weight:640}
hr{border:0;border-top:1px solid var(--rule-soft);margin:2.8rem 0}
ul,ol{margin:0 0 1.1rem;padding-left:1.3rem}
li{margin:.3rem 0}
blockquote{margin:1.5rem 0;padding:.85rem 0 .85rem 1.1rem;
  border-left:2px solid var(--accent);color:var(--ink-soft);font-size:.94rem}
blockquote p:last-child{margin-bottom:0}
code{font-family:var(--mono);font-size:.855em;background:var(--code-bg);
  padding:.1em .34em;border-radius:2px;overflow-wrap:break-word}
pre{background:var(--surface);border:1px solid var(--rule-soft);border-radius:3px;
  padding:1rem 1.15rem;overflow-x:auto;font-size:.83rem;line-height:1.55;margin:1.35rem 0}
pre code{background:none;padding:0;font-size:1em}
.scroll{overflow-x:auto;margin:1.45rem 0;border:1px solid var(--rule-soft);border-radius:3px}
table{border-collapse:collapse;width:100%;font-family:var(--sans);font-size:.845rem;
  line-height:1.5;font-variant-numeric:tabular-nums}
th{text-align:left;font-family:var(--mono);font-size:.68rem;letter-spacing:.1em;
  text-transform:uppercase;color:var(--ink-soft);font-weight:600;padding:.7rem .85rem;
  border-bottom:1px solid var(--rule);white-space:nowrap;background:var(--surface)}
td{padding:.7rem .85rem;border-bottom:1px solid var(--rule-soft);vertical-align:top}
tr:last-child td{border-bottom:0}
/* WIDE THINGS GET THE WHOLE COLUMN. The prose measure is for prose. */
figure.diagram{margin:1.9rem 0;padding:1.3rem 1rem;background:var(--surface);
  border:1px solid var(--rule-soft);border-radius:3px;width:100%;
  max-width:none;position:relative;cursor:zoom-in}
figure.diagram pre.mermaid{background:none;border:0;padding:0;margin:0;
  display:flex;justify-content:center;overflow:visible}
figure.diagram svg{max-width:100%;height:auto}
figure.diagram::after{content:"click to enlarge";position:absolute;
  right:.6rem;bottom:.45rem;font-family:var(--mono);font-size:.62rem;
  letter-spacing:.08em;text-transform:uppercase;color:var(--ink-soft);
  opacity:0;transition:opacity .12s}
figure.diagram:hover::after{opacity:.75}
/* Full-screen, at natural size, for the ones that are genuinely large --
   the data model has forty tables and will never fit a column. */
#zoom{position:fixed;inset:0;background:var(--paper);z-index:50;display:none;
  overflow:auto;padding:2.5rem;cursor:zoom-out}
#zoom.on{display:block}
#zoom svg{max-width:none!important;height:auto}
#zoomclose{position:fixed;top:.9rem;right:1.1rem;font-family:var(--mono);
  font-size:.72rem;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink-soft);z-index:51}
.warn{font-family:var(--mono);font-size:.7rem;color:var(--ink-soft);
  border:1px dashed var(--rule);padding:.5rem .7rem;border-radius:3px}
.chooser{max-width:40rem;margin:0 auto;padding:6rem 2rem}
.chooser a{display:block;text-decoration:none;color:var(--ink);
  border:1px solid var(--rule);border-radius:3px;padding:1.1rem 1.25rem;
  margin:.85rem 0}
.chooser a:hover{border-color:var(--accent)}
.chooser b{font-family:var(--sans);font-size:1.05rem;display:block;margin-bottom:.2rem}
.chooser span{font-family:var(--sans);font-size:.85rem;color:var(--ink-soft)}
@media (max-width:880px){
  .wrap{grid-template-columns:1fr;gap:0;padding:0 1.15rem}
  .rail{position:static;max-height:none;border-right:0;
    border-bottom:1px solid var(--rule);padding:1.75rem 0 1.1rem;columns:2;column-gap:1.5rem}
  main{padding-top:1.75rem}
  h1{font-size:1.95rem}
  body{font-size:16px}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""

_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>{css}</style></head><body>
<div id="zoom"><span id="zoomclose">esc / click to close</span><div id="zoombody"></div></div>
<div class="wrap">
  <nav class="rail" aria-label="Contents">
    <p class="eyebrow">Contents</p>
    {rail}
    <hr>
    {others}
    <a class="other" href="/">Marshall home &rarr;</a>
  </nav>
  <main>
    <h1>{title}</h1>
    <p class="blurb">{blurb}</p>
    {warn}
{body}
  </main>
</div>
<script src="{script}"></script>
<script>
  // Mermaid renders on load, and again on a theme flip so the diagrams do not
  // stay in the palette they were first drawn in.
  (function () {{
    if (!window.mermaid) return;
    var dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)');
    function draw() {{
      mermaid.initialize({{
        startOnLoad: false,
        theme: dark && dark.matches ? 'dark' : 'neutral',
        securityLevel: 'strict',
        // TRUE, and it was false. Mermaid then drew every diagram at its
        // natural size inside a column narrower than the diagram, which is
        // why they had to be scrolled sideways. Fit the column; the
        // full-size copy is one click away.
        flowchart: {{ useMaxWidth: true }},
        sequence: {{ useMaxWidth: true }},
        er: {{ useMaxWidth: true }},
      }});
      document.querySelectorAll('pre.mermaid').forEach(function (el) {{
        if (el.dataset.src === undefined) el.dataset.src = el.textContent;
        el.removeAttribute('data-processed');
        el.innerHTML = el.dataset.src;
      }});
      mermaid.run({{ querySelector: 'pre.mermaid' }});
    }}
    draw();
    if (dark && dark.addEventListener) dark.addEventListener('change', draw);

    // CLICK TO ENLARGE. Fitting the column is right for reading; some of these
    // -- the data model especially -- have more in them than any column can
    // carry, and squinting at a shrunk SVG is its own kind of useless. The
    // overlay shows the same SVG at natural size and scrolls in both axes,
    // which is what horizontal scrolling should have been all along: opt-in,
    // and only for the diagram you asked about.
    var zoom = document.getElementById('zoom');
    var zoomBody = document.getElementById('zoombody');
    function close() {{ zoom.classList.remove('on'); zoomBody.innerHTML = ''; }}
    document.addEventListener('click', function (ev) {{
      var fig = ev.target.closest && ev.target.closest('figure.diagram');
      if (fig && !zoom.classList.contains('on')) {{
        var svg = fig.querySelector('svg');
        if (!svg) return;
        zoomBody.innerHTML = svg.outerHTML;
        var big = zoomBody.querySelector('svg');
        if (big) {{ big.removeAttribute('width'); big.removeAttribute('height');
                    big.style.width = 'auto'; big.style.maxWidth = 'none'; }}
        zoom.classList.add('on');
      }} else if (zoom.classList.contains('on')) {{
        close();
      }}
    }});
    document.addEventListener('keydown', function (ev) {{
      if (ev.key === 'Escape') close();
    }});
  }})();
</script>
</body></html>
"""

_INDEX = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Marshall documents</title><style>{css}</style></head><body>
<div class="chooser">
  <h1>Documents</h1>
  <p class="blurb">Rendered from the markdown in <code>docs/</code> on every
     request, so an edit shows up on the next page turn.</p>
  {items}
  <p class="blurb" style="margin-top:2rem"><a href="/">&larr; Marshall home</a></p>
</div>
</body></html>
"""
