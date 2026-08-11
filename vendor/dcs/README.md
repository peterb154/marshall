# Vendored DCS terrain data

`Beacons.lua`, copied verbatim from the server's DCS install:

    <DCS>\Mods\terrains\<Theatre>\Beacons.lua

**Why a copy rather than a live read.** These are the ILS localisers, TACANs,
VORs and NDBs the sim actually transmits — the one class of number that is
neither ours to choose nor the chart's to declare. A pilot flying a published
approach tunes the published frequency, and if the sim is on a different one he
gets silence; no amount of correct phraseology saves that.

    "looks to me like DKS is using real plates... DCS, stuck in time, doesnt
     match in many cases. Probably with freqs and mag headings."

Right, and measured: Nevada's six approaches match their FAA plates to the
kilohertz, while Kutaisi's localiser is 109.75 in the sim and 110.1 on the
current Georgian AIP — because that AIP was reissued in August 2025 and the real
aerodrome's navaids were upgraded underneath a sim that froze years earlier.

So `check.py` audits our profiles against this file, and a discrepancy becomes a
NOTAM on the ATIS rather than a puzzled pilot on final. That check must run
offline and on every commit, which a file in the repo does and an SSH to a
Windows box in the garage does not. It is static terrain data of a few kilobytes
and a DCS update that moves a frequency shows up as a visible diff here.

**Refreshing** is deliberate, not automatic — `tools/beacons.py --refresh`.
