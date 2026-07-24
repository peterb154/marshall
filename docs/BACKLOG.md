# Backlog

Deferred work, captured so it isn't lost. Not a promise of order.

## OpenKneeboard: split doodle pages from clickable pages

OpenKneeboard's Web Dashboard defaults to **mouse emulation** — the tablet pen
acts as a mouse (click links, press the page buttons, scroll). That is
**mutually exclusive** with the doodle/ink layer you get on PDFs and images: a
page can be clickable *or* drawable, not both.

Flipping to draw-on-top is per-page, via the experimental cursor-events API, and
it **disables all interaction** (including scrollbars), so it only suits
single-screen content:

```js
await OpenKneeboard.EnableExperimentalFeatures([
  {name: "DoodlesOnly", version: 2024071802},
  {name: "SetCursorEventsMode", version: 2024071801},
]);
await OpenKneeboard.SetCursorEventsMode("DoodlesOnly");
```

**Implication for our tabs:**
- **E6B** must stay **clickable** (its buttons/inputs) → mouse emulation, no doodles.
- **Charts / tables (briefing)** want **doodles** (annotate the plate) → DoodlesOnly,
  single-screen, no scrolling.

So these belong on **separate pages** with different cursor-events modes — the
E6B can't share a doodle-enabled sheet. `kneeboard/site.py` builds the multi-page
tab; the mode would be set per section when that section is shown. Note the
`SetCursorEventsMode` version stamp differs from `PageBasedContent`.
