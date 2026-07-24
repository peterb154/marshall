-- Terrain survey.
--
-- Procedure design needs real minimum safe altitudes, and terrain height is only
-- available inside a running mission (land.getHeight). pydcs ships no elevation
-- data. So: sample a grid once at mission start, dump it to dcs.log, and do the
-- actual design offline against real numbers.
--
-- Load the mission, wait for "[SURVEY] done", quit. Nothing needs to be flown.

local CENTRE = SURVEY_CENTRE or { x = -355811, z = 617386 }   -- Batumi
local RADIUS_NM = SURVEY_RADIUS_NM or 25
local STEP_NM = SURVEY_STEP_NM or 1
local NM = 1852.0

local function run()
  local half = RADIUS_NM * NM
  local step = STEP_NM * NM
  local count, highest, hx, hz = 0, -1, 0, 0

  env.info(string.format("[SURVEY] begin centre x=%.0f z=%.0f radius=%.0fnm step=%.1fnm",
    CENTRE.x, CENTRE.z, RADIUS_NM, STEP_NM))

  local x = CENTRE.x - half
  while x <= CENTRE.x + half do
    local row = {}
    local z = CENTRE.z - half
    while z <= CENTRE.z + half do
      -- land.getHeight takes a 2D point where y is the DCS z axis (east).
      local h = land.getHeight({ x = x, y = z }) or 0
      row[#row + 1] = string.format("%d", math.floor(h + 0.5))
      if h > highest then highest, hx, hz = h, x, z end
      count = count + 1
      z = z + step
    end
    -- One log line per row keeps dcs.log parseable without huge single lines.
    env.info(string.format("[SURVEY] row x=%.0f z0=%.0f dz=%.0f %s",
      x, CENTRE.z - half, step, table.concat(row, ",")))
    x = x + step
  end

  env.info(string.format(
    "[SURVEY] done samples=%d highest=%.0fm (%.0fft) at x=%.0f z=%.0f",
    count, highest, highest * 3.28084, hx, hz))
  trigger.action.outText(string.format(
    "Survey complete: %d samples, highest %.0f ft. Safe to quit.",
    count, highest * 3.28084), 60)
  return nil
end

timer.scheduleFunction(run, nil, timer.getTime() + 2)
