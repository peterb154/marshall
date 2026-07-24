-- 362nd blind-flying mission -- beacon network and pilot aids.
--
-- BEACONS is prepended by build_mission.py from route.py, so the stations here
-- are the same data the kneeboard charts are drawn from.
--
-- THE FILENAME MUST CARRY THE l10n/DEFAULT/ PREFIX. Established by flight test
-- 2026-07-24: a bare filename produces no audio, no error and no log line. The
-- mission-editor Radio Transmission action fails the same way and cannot be
-- fixed from the editor, which is why every beacon is created here instead.

local BEACONS = BEACONS or {}
if #BEACONS == 0 then
  env.error("[362] BEACONS is empty -- rebuild with build_mission.py")
  trigger.action.outText("Mission built wrong: no beacons defined.", 60)
  return
end

local NM = 1852.0
local TICK = 5

local function startBeacons()
  for _, b in ipairs(BEACONS) do
    local site = {
      x = b.x,
      y = land.getHeight({ x = b.x, y = b.z }) + 10,
      z = b.z,
    }
    local ok, err = pcall(trigger.action.radioTransmission,
      "l10n/DEFAULT/" .. b.file, site,
      0,                      -- AM; the ARA-8 is AM only
      true,                   -- loop
      b.freq * 1000000,       -- Hz
      b.power or 1000,
      "tx_" .. string.lower(b.ident))
    env.info(string.format("[362] beacon %s (%s) %.3f MHz ok=%s %s",
      b.name, b.ident, b.freq, tostring(ok), ok and "" or tostring(err)))
  end
end

-- ---------------------------------------------------------------------------
-- Position reporting.
--
-- The controller is deliberately blind: it knows only what pilots tell it. For
-- the first test flights the report goes through the F10 menu rather than
-- voice, so the procedure can be exercised before any speech plumbing exists.
-- The wording matches what will eventually be spoken.

local reports = {}

local function reportFix(args)
  local unit = Unit.getByName(args.unit)
  if not unit then return end
  local p = unit:getPoint()
  -- Round to the nearest 500 ft, the way a pilot reads an altimeter aloud.
  local said = math.floor(p.y * 3.28084 / 500 + 0.5) * 500

  local truth = {}
  for _, b in ipairs(BEACONS) do
    local dx, dz = b.x - p.x, b.z - p.z
    truth[#truth + 1] = string.format("%s=%.1fnm", b.ident,
      math.sqrt(dx * dx + dz * dz) / NM)
  end

  reports[#reports + 1] = { unit = args.unit, fix = args.fix, alt = said,
                            t = timer.getTime() }
  -- Log the claim AND the truth side by side. The controller never sees the
  -- truth; this exists purely so the debrief can show who reported accurately.
  env.info(string.format(
    "[362-REPORT] unit=%s claims=%s alt=%d t=%.1f truth: %s",
    args.unit, args.fix, said, timer.getTime(), table.concat(truth, " ")))

  trigger.action.outTextForUnit(unit:getID(), string.format(
    "REPORTED: %s, %d feet", args.fix, said), 8)
end

local tracked = {}

local function attachMenus(unit)
  local gid = unit:getGroup():getID()
  local name = unit:getName()
  local root = missionCommands.addSubMenuForGroup(gid, "Position Report")
  for _, b in ipairs(BEACONS) do
    missionCommands.addCommandForGroup(gid,
      string.format("%s (%s)", b.name, b.ident), root, reportFix,
      { unit = name, fix = b.name })
  end
  missionCommands.addCommandForGroup(gid, "MISSED APPROACH", root, reportFix,
    { unit = name, fix = "MISSED APPROACH" })
end

local function tick()
  for _, side in pairs({ coalition.side.BLUE, coalition.side.RED }) do
    for _, u in pairs(coalition.getPlayers(side) or {}) do
      if u:isExist() and not tracked[u:getName()] then
        tracked[u:getName()] = true
        attachMenus(u)
        env.info("[362] tracking " .. u:getName())
      end
    end
  end
  return timer.getTime() + TICK
end

startBeacons()
timer.scheduleFunction(tick, nil, timer.getTime() + 5)
env.info("[362] mission script loaded, " .. #BEACONS .. " beacons")
