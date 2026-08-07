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
from marshall.kneeboard import asr_plate
from marshall.kneeboard import aip_plate
from marshall.kneeboard import brief as build_brief
from marshall.kneeboard import routemap as build_routemap
from marshall.kneeboard import comms as build_comms
from marshall.kneeboard import navlog as build_kneeboard
from marshall.kneeboard import plans as build_plans
from marshall.kneeboard import plate as build_plate

from marshall.core import route as R

HERE = Path(__file__).parent

# Stable GUIDs: OpenKneeboard remembers the current page, so these must not
# change between builds or the pilot loses their place every time.
def pages(profile: R.ApproachProfile = R.BATUMI_ASR):
    """The kneeboard's tabs, for whichever approach is loaded.

    Derived from the profile rather than written out, so pointing route.py at
    another field gives that field's kneeboard -- its runway in the tab, its
    scanned chart on the AIP page -- with no edit here. The tab for the real
    chart only appears when we actually hold a scan of it; an empty tab reads
    as a missing page rather than as "there is no published plate".
    """
    rwy = profile.runway or "--"
    out = [
        # First tab on purpose: it is the one page a pilot needs before he has
        # done anything at all, and the one that makes the radio usable.
        ("{b4e8c1a7-5f39-4d82-9e04-7a2b16d3f508}", "BRIEF", "brief",
         lambda: build_brief.build(profile)),
        ("{c9d20e51-8a34-4b76-bf15-2e6407a9d813}", "ROUTE", "routemap",
         lambda: build_routemap.build(profile)),
        ("{f7a1b3c9-2d45-4e60-8a71-3c9d05e2b641}", "COMMS", "comms",
         lambda: build_comms.build(profile)),
        ("{a1c8e0f2-3b47-4d91-9f2a-6c5e10b74d01}", "NAV LOG", "navlog",
         build_kneeboard.build),
        # WHAT IS ON FILE, which the pilot has to be able to READ before he can
        # ask for it. `plans.py` was written for exactly this and was never
        # given a tab, so the board existed in the database, on the controller's
        # side of the radio, and nowhere the pilot could see it.
        #
        # Its own docstring says the reason plainly: he cannot ask for "Marlin"
        # if he cannot remember what is on the board. Clearance delivery is the
        # first exchange of the sortie and it opens with him naming a plan.
        #
        # Built LIVE on every page turn, not baked at container start -- plans
        # are filed by migration and by hand between sorties, and a page built
        # at boot shows last night's board with no way to tell.
        ("{9f3c7b21-0e84-4a6d-b57f-1d2043c8ea96}", "PLANS", "plans",
         build_plans.build),
        ("{b2d9f103-4c58-4ea2-a03b-7d6f21c85e02}", f"{profile.kind.upper()} {rwy}",
         "asr", lambda: asr_plate.build(profile)),
    ]
    if aip_plate.has_plate(profile):
        out.append(("{e5fb2436-7a80-4d15-c36e-af9254fb18a5}", f"PLATE {rwy}",
                    "aip", lambda: aip_plate.build(profile)))
    out += [
        ("{d4fb1325-6e7a-40c4-c25d-9f8143ea7f04}", "NDB 13", "plate",
         build_plate.build),
        ("{c3ea0214-5d69-4fb3-b14c-8e7032d96f03}", "E6B", "e6b", build_e6b.build),
    ]
    return out


PAGES = pages()

PAGE_W, PAGE_H = 1024, 1365
PAGE_FEATURE_VERSION = 2024073001

# Letting a pilot WRITE on the page. OpenKneeboard's ink layer is available to a
# web dashboard, but only if the page asks for it: by default the tab is in
# "MouseEmulation" and every pen stroke is delivered to the document as a mouse
# drag, which draws nothing.
#
#     "I want to doodle on the OpenKneeboard pages."
#
# DoodlesOnly hands the cursor to OKB's ink instead. The cost is that the page
# stops receiving clicks -- which is why this is requested only AFTER the page
# API is working, since page turns then come from OpenKneeboard itself and the
# on-page buttons are a fallback nobody needs. If the page API failed we are
# navigating by those buttons, and taking clicks away would leave a pilot on
# page one of a document he cannot turn.
#
# v1.9 and above. Requested separately from PageBasedContent on purpose: an
# older OpenKneeboard rejects the whole EnableExperimentalFeatures call if it
# does not know one of the names, and losing page navigation to gain doodling
# is a bad trade.
DOODLE_FEATURES = (("DoodlesOnly", 2024071802),
                   ("SetCursorEventsMode", 2024071801))

# ...except where the page is a TOOL rather than a document. The E6B is a working
# wind-triangle calculator with plus and minus buttons on it, and DoodlesOnly
# takes its clicks away -- so the mode follows the PAGE. A chart, a plate and a
# test card are things to write on; a calculator is a thing to press.
#
# By slug, because the guid is a constant nobody should have to match by eye.
INTERACTIVE_SLUGS = {"e6b"}


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


def build(page_list=None) -> str:
    """Render one OpenKneeboard multi-page document from a list of tabs.

    Takes the list so a SECOND kneeboard can be built from the same machinery --
    the flight-test card is the same shape of thing as the charts and should not
    grow a parallel renderer that drifts.
    """
    page_list = PAGES if page_list is None else page_list
    styles, sections, scripts = [], [], []
    for guid, name, slug, builder in page_list:
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
        for guid, _, _, _ in page_list)
    buttons = "".join(f'<button data-guid="{guid}">{name}</button>'
                      for guid, name, _, _ in page_list)
    nl = chr(10)
    doodle_js = "[" + ", ".join(
        f'{{name: "{name}", version: {ver}}}' for name, ver in DOODLE_FEATURES) + "]"
    clicky_js = "[" + ", ".join(
        f'"{guid.strip("{}").lower()}"'
        for guid, _, slug, _ in page_list if slug in INTERACTIVE_SLUGS) + "]"

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

  // WRITE ON IT, unless the page is a tool. DoodlesOnly hands the cursor to
  // OpenKneeboard's ink; MouseEmulation gives it back to the document, which the
  // E6B needs because it has buttons. Switched on every page turn, and only when
  // it actually changes -- a pilot turning pages should not be waiting on a
  // promise per turn for no reason.
  const CLICKY = {clicky_js};
  let API = null, cursorMode = null;

  async function setCursorMode(guid) {{
    if (!API || !API.SetCursorEventsMode) return;
    const want = CLICKY.includes(norm(guid)) ? "MouseEmulation" : "DoodlesOnly";
    if (want === cursorMode) return;
    try {{
      await API.SetCursorEventsMode(want);
      cursorMode = want;
    }} catch (err) {{
      note("cursor mode " + want + ": " + err);
    }}
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
        if (guid) {{ show(guid); setCursorMode(guid); }}
      }});
    }} catch (err) {{
      useButtons("page API: " + err);
      return;                          // clicks are the only way to navigate
    }}
    // Pages work. NOW ask for ink -- see DOODLE_FEATURES. Its own try/catch, so
    // an OpenKneeboard that has never heard of it still turns pages.
    try {{
      await api.EnableExperimentalFeatures({doodle_js});
      API = api;
      await setCursorMode(PAGES[0].guid);
    }} catch (err) {{
      console.log("doodling unavailable: " + err);
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
