# Gotchas

Hard-won, mostly undocumented. Each cost real time; several present as silent
failures with nothing useful in a log.

## pydcs (0.15) writes several fields wrong by default

DCS reports a malformed mission as a bare "load failed". `mission/validate.py`
asserts all of this before a mission is ever loaded.

- **`RadioTransmission` frequency is Hz, not kHz** — pydcs defaults to `124000`,
  which reads as kHz. Pass `int(mhz * 1_000_000)`.
- **`modulation` must be numeric `0` (AM) / `1` (FM)**, but pydcs types it `bool`
  and emits `false`. In Lua `false ~= 0`.
- **`DoScript(String(text))` inlines the script as a dictionary *key*** and fails
  at run time (`getValueDictByKey` returns the key name, which DCS tries to
  compile: `'=' expected near '<eof>'`). Use `DoScriptFile` with a resource file.
- **pydcs never writes the top-level `theatre` file** the ME always includes.
  Add it in a zip post-pass.
- **pydcs will not create `Avionics/<type>/<unitId>/VHF_RADIO/SETTINGS.lua`** —
  without it the SCR-522's channels cannot be set (they are ground-only presets).
  Inject via zipfile, keyed on `unit.id`.
- **Speed must be set in BOTH places:** route waypoints default to 25 m/s *and*
  each unit's own spawn speed to 27 m/s (61 mph) — the Mustang stalls on spawn.
- **A group's frequency defaults to 251 MHz (UHF)** which DCS rejects outright.
  The SCR-522 is VHF 100–156.
- pydcs writes `["k"]=v` (no spaces); the ME writes `["k"] = v`. Regexes over
  mission text must tolerate both.

## DCS `radioTransmission` — the filename needs an `l10n/DEFAULT/` prefix

A **bare filename produces no audio, no error, and nothing in the log.** Only a
filename carrying the `l10n/DEFAULT/` prefix plays:

```lua
trigger.action.radioTransmission("l10n/DEFAULT/bcn_alfa.wav", pt, 0, true, 124000000, 1000, "tx")
```

The mission-editor "Radio Transmission" action fails the same way (its resource
key resolves to a bare filename) and cannot be fixed from the editor — **build
beacons from Lua at mission start, not from trigger actions.** Ruled out as
irrelevant in the same flight test: audio format (16-bit/22050 fine), power
(1000 fine), modulation (AM correct).

Debugging lesson: always test against a *known-good* transmitter (a terrain VOR)
first, to prove the receive chain before suspecting your own transmitter.

## DCS aural navigation (P-51D)

- **AN/ARA-8 homing adapter is the -30 only** (`if submodel == "P-51D-30-NA"`),
  wired into the SCR-522. It is a direction finder (two antennas, compare), so it
  homes on **any steady AM VHF carrier** — a terrain VORTAC or a scripted
  transmission alike. AM only, 10 W, 3 kHz bandwidth.
- **Cockpit setup is mandatory and has no default keybind:** mode switch to
  **HOMING** (not TRANS/COMM), CW/MCW switch to **MCW**. Bind under category
  "Homing Adapter" or click them in the pit. Wrong mode = silence.
- **Four-course A/N radio range does not exist in DCS.** No Lorenz/SBA/range in
  `BeaconTypes.lua`.
- **The Detrola (LF) is non-directional** despite its "beamReceiver" class name,
  and its **frequency dial is unusable** — beacons 190 kHz apart read within two
  units of each other. Identify LF beacons by **Morse ident, never by dial**.
- **Beacon idents must not resemble the homing letters** the ARA-8 keys —
  U (`..-`), D (`-..`), A (`.-`), N (`-.`). An early build used B (`-...`), one
  dot from a homing D, and the two were indistinguishable in flight.

## OpenKneeboard Web Dashboard tabs

- **Wants a URL, not a file** — pages must be served (`kneeboard/serve.py`,
  threaded + no-cache).
- **IFRAMES ARE NEVER LOADED** — the embedded Chromium renders the outer document
  but never even *requests* same-origin iframe sources. **Inline everything** and
  scope each fragment's CSS to its section (`kneeboard/site.py`).
- **Serve with no-cache headers and a THREADED server.** `TCPServer`
  (single-threaded) wedges on Chromium's keep-alive, and every later request
  hangs — OpenKneeboard then shows "No Pages", identical to a page-API failure.
- **Restart OpenKneeboard fully after updating it** — before restarting,
  `window.OpenKneeboard` held only the old `SimHubHooks` shim.
- **Multi-page tab API** (mapped page buttons flip charts):
  `EnableExperimentalFeatures([{name:"PageBasedContent", version:2024073001}])`
  first — **`GetPages`/`SetPages` do not exist until it is enabled** (so probing
  reports them missing). `GetPages()` must be called before `SetPages()`.
  The event is `pageChanged`.
- **GUID braces are asymmetric** — `SetPages` takes `{...}`, `pageChanged`
  returns the guid *without* braces. Normalise both sides or every section loses
  its visible class and the sheet goes blank.
- **Do not scale the sheet with a CSS transform** — it computes `scale(0)` while
  OpenKneeboard resizes the surface after load and the page vanishes. Plain
  `max-width` cannot fail.
- `SetCursorEventsMode` is **not** an experimental feature; cursor defaults to
  doodling (which is what the charts want).

## Rendering (for self-checking output)

- **PDFs** (AIP plates): `uv run --with pymupdf python` renders pages to PNG.
  No poppler/cairo on the boxes.
- **HTML charts**: `tools/render.sh` screenshots via headless **Windows Edge**.
  From the LXC, ssh to the gaming rig to run it, or install headless chromium.

## Environment

- The WSL/gaming-rig dev env had **no push credentials, no `gh`, no rsync on the
  LXC** — repo moved to the LXC via tar-over-ssh; pushes happen from a box with
  creds.
- `uv` for Python (system WSL Python was 3.8, no pip). `python -m marshall.<pkg>`.
