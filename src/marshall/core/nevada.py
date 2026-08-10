"""Nellis, on the Nevada map. The second theatre, and the test of whether any of
this was ever really about the Caucasus.

    "How well do you think this system is going to transport to a totally
     different map and field? ... There had not been anything in code that locks
     it into caucuses"

Largely right, and measured rather than assumed: stripping comments and
docstrings, twenty-nine CODE references to a Caucasus place survive outside the
data modules, and twenty-four of them are kneeboard PROSE -- page titles and
briefing text with "Batumi" written into them. The architecture is already
field-parameterised, because adding Kobuleti forced it to be. What is genuinely
map-bound is data, and data is what this file is.

EVERY NUMBER HERE COMES FROM THE SIM'S OWN FILES, cross-checked against the
published plate, and the two agree:

    Beacons.lua   ILS 109.100, ident IDIQ, localiser antenna on 040.11 TRUE
    Radio.lua     "NellisControl" on 132.550 / 327.000
    AirNav        1,869 ft, variation 12E, 21L is 209 magnetic / 221 true

The localiser reading is worth stating because it is easy to get backwards. The
antenna sits beyond the STOP end and radiates back up the approach, so its 040
bearing is the reciprocal of the course an arriving aircraft flies: 220 true,
which at 12 east is 208 magnetic -- and the runway is painted 21. The sim, the
plate and the arithmetic all land in the same place.

And DCS models ONE controller at Nellis -- "NellisControl", ground, tower and
approach on a single frequency -- which happens to be the real Tower frequency.
The ladder below is the published one; the DCS radio is Tower's rung of it, so
a pilot who tunes what the mission editor shows him reaches the right man.

WHAT IS NOT HERE, AND MUST BE MEASURED RATHER THAN GUESSED: the minimum
vectoring altitudes. Batumi's were surveyed out of the sim with
`tools/survey_terrain.py` over a polar grid, and Nellis needs the same before
anybody is vectored -- it sits in a bowl with terrain above 11,000 ft inside
thirty miles, where Batumi's highest is 10,623 at twenty-three. Numbers from one
map applied to the other are not conservative, they are fiction. `mva_cells` is
deliberately empty until that survey is run, and `mva_for` falls back to the
published MSA, which is the safe direction to be wrong in.
"""

from __future__ import annotations

from marshall.core.approach import ApproachProfile, AtcCapability
from marshall.core.fields import Field_
from marshall.core.fixes import Fix
from marshall.core.stations import Station

# THE FIELD ITSELF.
#
# Position is the airport's own point from pydcs's Nevada terrain, in DCS metres
# for THAT map -- the coordinate frames of two terrains have nothing to do with
# each other, which is why none of the Caucasus fixes can be reused.
#
# `ends` is (03, 21) and not derived by rounding the heading. 209 magnetic
# rounds to 21 and happens to be right here; at Batumi the same arithmetic gives
# "runway 12" for a strip painted 13. The designator is data.
#
# NELLIS HAS TWO PARALLEL RUNWAYS, 03L/21R and 03R/21L, and `Field_` models one
# pair. The ILS is on 21L, so that is the pair described. A parallel-runway field
# wants an L/R designator on the end and this is where that will be noticed --
# noted rather than papered over.
NELLIS_FIELD = Field_(
    # ORDER MATTERS: `ends[0]` is the end whose heading is `runway`. 209 is the
    # 21 end, so the pair is (21, 03) and not (03, 21) -- written the wrong way
    # round first, and `runway_in_use` then named runway 03 with the wind from
    # 210, which is the downwind end of the ILS runway. Exactly the fault that
    # put a Kobuleti departure on runway 25 in a 090 wind.
    "Nellis", -398195, -17233, 1869, 209, ends=(21, 3), atis_mhz=118.400,
    magvar_deg=12.0,
    note="Nellis AFB (KLSV). Field elevation 1,869 ft -- a mile above Batumi, "
         "which is the first thing here that has never been exercised. "
         "03R/21L 10,051 x 150 ft, ILS on 21L. TACAN LSV 12X. Parallel "
         "03L/21R not modelled. MVA cells NOT surveyed; see the module note.")

# THE LADDER, from the published plate. DCS itself gives Nellis a single
# "NellisControl" covering ground, tower and approach on 132.550 -- which is the
# real Tower frequency, so Tower's rung agrees with what the mission editor
# shows a pilot and the rest are the positions that genuinely exist.
#
# Ground on 121.800 is also Kobuleti Ground's number. Harmless -- they are on
# different maps and never loaded together -- but it is exactly the sort of
# coincidence that makes a wrong answer look right, so it is written down.
NELLIS_CLEARANCE = Station("Nellis Clearance", 120.900, "clearance",
                           field="Nellis", also=("delivery",), voice="Gregory",
                           manner="Brisk and procedural. Reads a clearance the "
                                  "way a man reads a form, and will make you "
                                  "read it back again if you fumble it.")
NELLIS_GROUND = Station("Nellis Ground", 121.800, "ground", field="Nellis",
                        voice="Joey",
                        manner="Unhurried and faintly amused. Knows every "
                               "taxiway and expects you to know the one he "
                               "just gave you.")
NELLIS_TOWER = Station("Nellis Tower", 132.550, "tower", channels=(327.000,),
                       field="Nellis", voice="Matthew",
                       manner="Clipped. Owns the runway and nothing else, and "
                              "says so when asked for something that is not "
                              "his.")
NELLIS_APPROACH = Station("Nellis Approach", 118.125, "approach",
                          field="Nellis", voice="Stephen",
                          manner="Calm and economical, the way somebody sounds "
                                 "when the terrain is high and he has done this "
                                 "a great many times.")
NELLIS_DEPARTURE = Station("Nellis Departure", 135.100, "departure",
                           field="Nellis", voice="Stephen",
                           manner="The same man as Approach, going the other "
                                  "way, and just as short about it.")

# TONOPAH TEST RANGE (KTNX), 124 nm north-west and a mile and a half up.
#
# DCS calls it "Silverbow" on 124.750 -- which is the real Tower frequency, the
# same happy accident as Nellis -- and models TWO ILS approaches, one to each
# end. Both are in the sim's Beacons.lua and both agree with the plate:
#
#     I-RVP  108.300  antenna on 337.08 true  ->  course 157 true  ->  rwy 15
#     I-UVV  111.700  antenna on 157.10 true  ->  course 337 true  ->  rwy 33
#
# THE DESIGNATORS ARE 15/33 AND THE HEADINGS ARE 141/321 MAGNETIC, which is the
# `Field_.ends` comment proving itself on a second map: 141 rounds to 14, and
# the paint says 15. Deriving a runway name from its heading is wrong here for
# exactly the reason it was wrong at Batumi.
#
# VARIATION 16 EAST, against Nellis's 12. Two fields on one map with four
# degrees between them -- which is why a single theatre-wide MAGVAR was always
# going to be wrong somewhere, and why it now lives on the field.
TONOPAH_FIELD = Field_(
    "Tonopah", -226613, -174653, 5550, 141, ends=(15, 33), atis_mhz=118.600,
    magvar_deg=16.0,
    note="Tonopah Test Range (KTNX). Field elevation 5,550 ft -- nearly a mile "
         "above Nellis and three above Batumi. 15/33, 12,001 x 150 ft, ILS to "
         "both ends. MVA cells NOT surveyed; see the module note.")

TONOPAH_GROUND = Station("Silverbow Ground", 127.250, "ground",
                         channels=(335.500,), field="Tonopah", voice="Joey",
                         manner="Laconic. It is a test range and there is "
                                "rarely anybody else moving.")
TONOPAH_TOWER = Station("Silverbow Tower", 124.750, "tower",
                        channels=(257.950,), field="Tonopah",
                        also=("clearance", "delivery"), voice="Matthew",
                        manner="Dry and unhurried. Works the runway and the "
                               "clearances both, because nobody staffs a "
                               "delivery position out here.")
TONOPAH_APPROACH = Station("Silverbow Approach", 119.450, "approach",
                           channels=(233.950,), field="Tonopah",
                           also=("departure",), voice="Stephen",
                           manner="Careful about terrain and says so. The "
                                  "valley floor is high and the ridges are "
                                  "higher.")

TONOPAH_STATIONS = [TONOPAH_TOWER, TONOPAH_GROUND, TONOPAH_APPROACH]

# THE ENROUTE PICTURE. Tonopah VORTAC (TPH) on 117.200, channel 119, is a real
# world_* beacon in the sim rather than an airfield one -- the navaid the leg
# between the two fields is flown on.
TPH = Fix("TONOPAH", "TPH", -200809, -196936, 117.200,
          sector="Silverbow Approach",
          note="Tonopah VORTAC, channel 119. Enroute, not an airfield beacon.")
LSV = Fix("NELLIS", "LSV", -398195, -17233, 0.0,
          sector="Nellis Approach",
          note="Nellis TACAN 12X. Field reference for the ILS to 21L.")
NEVADA_FIXES = [LSV, TPH]

NELLIS_STATIONS = [NELLIS_CLEARANCE, NELLIS_GROUND, NELLIS_TOWER,
                   NELLIS_DEPARTURE, NELLIS_APPROACH]
NEVADA_STATIONS = NELLIS_STATIONS + TONOPAH_STATIONS
NEVADA_FIELDS = (NELLIS_FIELD, TONOPAH_FIELD)


# --- the approaches ---------------------------------------------------------
#
# ONE PROFILE PER PROCEDURE, exactly as at Batumi and Kobuleti. `guidance` is
# "intercept" for both: an ILS puts the glidepath in the aeroplane, so the
# controller vectors him to the localiser and stops flying it for him. That is
# the single field that separates this from the Batumi talkdown.
#
# THE MINIMA ARE THE PUBLISHED ONES where the plate gives them and the ICAO
# default where it does not, and `min_hat_ft=200` is what says this is an ILS at
# all -- a Category I decision height. Transcribing the ASR's seven hundred onto
# an ILS is the mistake `min_hat_ft` exists to prevent.

NELLIS_ILS = ApproachProfile(
    controller=NELLIS_APPROACH.name,
    beacon=LSV,
    outer_hold=TPH,
    kind="ils",
    guidance="intercept",
    stations=list(NEVADA_STATIONS),
    hold_base_ft=9000,               # the valley floor is 1,869 and the ridges
    final_crs=209,                   # magnetic, and what is painted on 21L
    final_crs_true_measured=220.11,  # Beacons.lua: localiser antenna + 180
    touchdown_offset_nm=0.83,        # half of 10,051 ft, from the field centre
    grid_convergence_deg=0.0,        # NOT MEASURED -- see the module note
    magvar_deg=12.0,                 # AirNav: 12E (2015)
    field_elev_ft=NELLIS_FIELD.elevation_ft,
    field_thr_elev_ft=NELLIS_FIELD.elevation_ft,
    runway="21",
    platform_ft=6000,
    ceiling_ft=400,
    min_hat_ft=200,
    final_intercept_nm=12.0,
    fap_nm=7.0,
    map_nm=0.5,
    msa_sectors=list(NELLIS_FIELD.msa_sectors),
    mva_cells=list(NELLIS_FIELD.mva_cells),
    iaf=TPH,
    iaf_alt_ft=11000,
    chart_name="KLSV ILS OR LOC X RWY 21L",
    altimeter_datum="QNH",           # a US field: altimeter, not QFE
    atc=AtcCapability(radar=True, dme=True, separation="radar", era="modern"),
)

TONOPAH_ILS = ApproachProfile(
    controller=TONOPAH_APPROACH.name,
    beacon=TPH,
    outer_hold=TPH,
    kind="ils",
    guidance="intercept",
    stations=list(NEVADA_STATIONS),
    hold_base_ft=12000,              # 5,550 ft of field, then the ridges
    final_crs=141,                   # magnetic, painted 15
    final_crs_true_measured=157.08,  # Beacons.lua: I-RVP antenna + 180
    touchdown_offset_nm=0.99,        # half of 12,001 ft
    grid_convergence_deg=0.0,        # NOT MEASURED -- see the module note
    magvar_deg=16.0,                 # AirNav: 16E (2005)
    field_elev_ft=TONOPAH_FIELD.elevation_ft,
    field_thr_elev_ft=TONOPAH_FIELD.elevation_ft,
    runway="15",
    platform_ft=9000,
    ceiling_ft=400,
    min_hat_ft=200,
    final_intercept_nm=12.0,
    fap_nm=7.0,
    map_nm=0.5,
    msa_sectors=list(TONOPAH_FIELD.msa_sectors),
    mva_cells=list(TONOPAH_FIELD.mva_cells),
    iaf=TPH,
    iaf_alt_ft=13000,
    chart_name="KTNX ILS RWY 15 (I-RVP 108.30)",
    altimeter_datum="QNH",
    atc=AtcCapability(radar=True, dme=True, separation="radar", era="modern"),
)
