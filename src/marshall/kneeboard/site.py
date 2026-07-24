"""Build index.html -- one OpenKneeboard tab, one page per chart.

OpenKneeboard's page API, confirmed by probing the running instance rather than
from documentation:

    await api.EnableExperimentalFeatures(
        [{name: "PageBasedContent", version: 2024073001}])   # this exact stamp
    await api.GetPages()          # SetPages throws without calling this first
    await api.SetPages([{guid, pixelSize}, ...])
    api.addEventListener("pageChanged", e => e.detail.page.guid)

SetPages and GetPages do not exist on window.OpenKneeboard until the feature is
enabled, so probing for them beforehand reports them missing.

The charts are INLINED rather than iframed: OpenKneeboard's embedded Chromium
rendered the outer document but never painted the same-origin iframes, giving
three blank pages of the correct background colour. Each chart's CSS is scoped
to its own section so the three documents cannot collide.

    uv run python build_site.py
"""

import re
from pathlib import Path

from marshall import config

from marshall.kneeboard import e6b as build_e6b
from marshall.kneeboard import navlog as build_kneeboard
from marshall.kneeboard import plate as build_plate

HERE = Path(__file__).parent

# Stable GUIDs: OpenKneeboard remembers the current page, so these must not
# change between builds or the pilot loses their place every time.
PAGES = [
    ("{a1c8e0f2-3b47-4d91-9f2a-6c5e10b74d01}", "NAV LOG", "navlog",
     build_kneeboard.build),
    ("{b2d9f103-4c58-4ea2-a03b-7d6f21c85e02}", "BATUMI 13", "plate",
     build_plate.build),
    ("{c3ea0214-5d69-4fb3-b14c-8e7032d96f03}", "E6B", "e6b", build_e6b.build),
]

PAGE_W, PAGE_H = 1024, 1365
PAGE_FEATURE_VERSION = 2024073001


def split(doc: str) -> tuple[str, str, str]:
    """Pull a generated chart apart into (css, html, js)."""
    css = "\n".join(re.findall(r"<style>(.*?)</style>", doc, re.S))
    js = "\n".join(re.findall(r"<script>(.*?)</script>", doc, re.S))
    html = re.sub(r"<(style|script)>.*?</\1>", "", doc, flags=re.S)
    html = re.sub(r"<title>.*?</title>", "", html, flags=re.S)
    return css, html.strip(), js


def scope(css: str, sel: str) -> str:
    """Prefix every rule with `sel` so three documents share one page safely.

    body/html rules become the section itself; everything else nests under it.
    The charts use plain selectors, so a textual transform is enough and a CSS
    parser would be overkill.
    """
    out = []
    for block in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors = re.sub(r"/\*.*?\*/", "", block.group(1), flags=re.S).strip()
        body = block.group(2).strip()
        if not selectors or selectors.startswith("@"):
            continue
        parts = []
        for one in selectors.split(","):
            one = one.strip()
            if not one:
                continue
            if one == "*":
                parts.append(f"{sel} *")
            elif one in ("body", "html"):
                parts.append(sel)
            else:
                parts.append(f"{sel} {one}")
        if parts:
            out.append(f"{', '.join(parts)} {{ {body} }}")
    return "\n".join(out)


def build() -> str:
    styles, sections, scripts = [], [], []
    for guid, name, slug, builder in PAGES:
        css, html, js = split(builder())
        styles.append(f"/* ---- {name} ---- */\n" + scope(css, f"#p-{slug}"))
        first = ' class="on"' if not sections else ''
        sections.append(
            f'<section id="p-{slug}" data-guid="{guid}"{first}>{html}</section>')
        if js.strip():
            # Wrapped so each chart keeps its own locals.
            scripts.append(f"// ---- {name} ----\n(function() {{\n{js}\n}})();")

    page_js = ",".join(
        f'{{guid:"{guid}",pixelSize:{{width:{PAGE_W},height:{PAGE_H}}}}}'
        for guid, _, _, _ in PAGES)
    buttons = "".join(f'<button data-guid="{guid}">{name}</button>'
                      for guid, name, _, _ in PAGES)
    nl = chr(10)

    return f"""<title>362nd Kneeboard</title>
<style>
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; background: #d9cfb4; }}
  /* The first section carries class="on" in the markup, so the nav log paints
     with CSS alone. Waiting for script meant OpenKneeboard captured three
     hidden sections and showed three blank pages. */
  section {{ display: none; }}
  section.on {{ display: block; }}
  #nav {{ display: none; gap: 6px; padding: 6px; position: fixed;
         top: 0; left: 0; right: 0; z-index: 99;
         background: rgba(36,31,24,.9); }}
  #nav.on {{ display: flex; }}
  #nav button {{ flex: 1; background: #cabf9f; color: #241f18;
    border: 1px solid #241f18; font-family: "Courier New", monospace;
    font-size: 14px; font-weight: bold; min-height: 38px; cursor: pointer; }}
  #diag {{ display: none; font: 12px/1.4 "Courier New", monospace;
          color: #7a2318; background: #efe7d2; border: 2px solid #7a2318;
          padding: 8px; white-space: pre-wrap; position: fixed; top: 54px;
          left: 8px; right: 8px; z-index: 99; max-height: 60%; overflow: auto; }}
  #diag.on {{ display: block; }}
{nl.join(styles)}
</style>

<div id="nav">{buttons}</div>
<div id="diag"></div>
{"".join(sections)}

<script>
  const PAGES = [{page_js}];
  const log = [];
  const note = m => log.push(m);

  // OpenKneeboard returns the guid WITHOUT braces in pageChanged, while
  // SetPages and our markup use the braced form. Comparing them raw matches
  // nothing, so every section loses .on and the sheet goes blank -- which is
  // exactly what happened. Normalise both sides.
  const norm = g => String(g || "").replace(/[{{}}]/g, "").toLowerCase();

  function show(guid) {{
    const want = norm(guid);
    const secs = [...document.querySelectorAll("section")];
    if (!secs.some(s => norm(s.dataset.guid) === want)) {{
      note("unknown page guid: " + guid);   // never blank the sheet
      return;
    }}
    secs.forEach(s => s.classList.toggle("on", norm(s.dataset.guid) === want));
  }}

  function useButtons(why) {{
    note("fell back to on-screen buttons: " + why);
    const nav = document.getElementById("nav");
    nav.classList.add("on");
    nav.addEventListener("click", e => {{
      const b = e.target.closest("button");
      if (b) show(b.dataset.guid);
    }});
    const d = document.getElementById("diag");
    d.textContent = log.join("\\n");
    d.classList.add("on");
  }}

  async function init() {{
    show(PAGES[0].guid);              // never leave a blank sheet
    const api = window.OpenKneeboard;
    if (!api) {{ useButtons("window.OpenKneeboard absent"); return; }}
    try {{
      await api.EnableExperimentalFeatures(
        [{{ name: "PageBasedContent", version: {PAGE_FEATURE_VERSION} }}]);
      await api.GetPages();
      await api.SetPages(PAGES);
      if (api.SetPreferredPixelSize)
        await api.SetPreferredPixelSize({PAGE_W}, {PAGE_H});
      api.addEventListener("pageChanged", e => {{
        const guid = e?.detail?.page?.guid;
        if (guid) show(guid);
      }});
    }} catch (err) {{
      useButtons("page API: " + err);
    }}
  }}

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
</script>

<script>
{nl.join(scripts)}
</script>
"""


if __name__ == "__main__":
    config.ensure_dirs(); out = config.KNEEBOARD_OUT / "index.html"
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out}  ({out.stat().st_size} B, charts inlined)")
    for _, name, slug, _ in PAGES:
        print(f"  page {name:11} #p-{slug}")
