-- AI control for autonomous ATC testing.
--
-- The tasking API (Controller:setTask) lives ONLY in the mission scripting
-- environment -- which is exactly where this DoScript runs. So we task test
-- traffic here and drive it from outside by flipping named user flags over
-- DCS-gRPC (SetUserFlag). The mission owns the AI-control code; gRPC is the
-- remote. Set a flag to stage a maneuver; the poll applies it and clears it.
--
-- Coordinates: mission-env route points are {x = north, y = east}. route.py
-- (and the injected BEACONS table) store x = north, z = east, so a fix maps to
-- {x = fix.x, y = fix.z}.

local function fixByName(name)
  for _, b in ipairs(BEACONS or {}) do
    if b.name == name then return b end
  end
end

local BAT = fixByName('BATUMI')

-- Send a group to a point as a fresh Mission route, replacing whatever it was
-- doing (an orbit, its old route). Enough to drive a visible, deliberate track.
local function flyTo(groupName, x, y, altM, speedMs)
  local grp = Group.getByName(groupName)
  if not grp then
    trigger.action.outText('AICTRL: no group ' .. tostring(groupName), 10)
    return
  end
  grp:getController():setTask({
    id = 'Mission',
    params = {
      airborne = true,
      route = { points = { [1] = {
        type = 'Turning Point', action = 'Turning Point',
        x = x, y = y, alt = altM, alt_type = 'BARO', speed = speedMs,
        task = { id = 'ComboTask', params = { tasks = {} } },
      } } },
    },
  })
  trigger.action.outText('AICTRL: ' .. groupName .. ' tasked', 10)
end

-- Fly a HEADING, not a place. A radar approach is nothing but a sequence of
-- headings, so testing one against AI traffic needs the aircraft to accept an
-- arbitrary heading on command -- which the DCS AI has no direct task for. The
-- way to say it is a waypoint far enough down that heading that the leg IS the
-- heading: at sixty miles the track is straight for as long as anyone cares,
-- and the next instruction replaces it long before it arrives.
--
-- Headings and altitudes arrive as user flags because flags are the only thing
-- gRPC can push into the mission environment. ai_hdg is degrees magnetic,
-- ai_alt is hundreds of feet -- flags are integers.
-- The leg has to be long enough that flying to its end IS flying the heading,
-- and short enough that the altitude on it is a real instruction. DCS spreads
-- a climb or descent across the whole leg, so a sixty-mile waypoint at two
-- thousand feet is a gradient of thirty feet a mile -- the aircraft nods and
-- does almost nothing. Flown live, that arrived over the threshold twelve
-- hundred feet high while tracking the centreline to within a hundred yards:
-- the vectoring was right and the descent was decorative. Ten miles is still
-- straight for far longer than the four seconds between radar looks, and it
-- makes "descend to two thousand" mean it.
local LEG_M = 10 * 1852

local function flyHeading(groupName, hdgDeg, altFt, speedMs)
  local grp = Group.getByName(groupName)
  if not grp then
    trigger.action.outText('AICTRL: no group ' .. tostring(groupName), 10)
    return
  end
  local u = grp:getUnit(1)
  if not u then return end
  local p = u:getPoint()
  -- Mission-env x is NORTH and y is EAST, so a compass heading resolves the
  -- ordinary way round: north by cos, east by sin. Getting this pair the wrong
  -- way round mirrors every vector about the 045 line and looks almost right.
  local r = math.rad(hdgDeg)
  grp:getController():setTask({
    id = 'Mission',
    params = {
      airborne = true,
      route = { points = { [1] = {
        type = 'Turning Point', action = 'Turning Point',
        x = p.x + LEG_M * math.cos(r),
        y = p.z + LEG_M * math.sin(r),
        alt = altFt * 0.3048, alt_type = 'BARO', speed = speedMs,
        task = { id = 'ComboTask', params = { tasks = {} } },
      } } },
    },
  })
  trigger.action.outText(
    string.format('AICTRL: %s heading %03d, %d ft', groupName, hdgDeg, altFt), 10)
end

-- Maneuvers keyed to flag NAMES. Extend this table as tests need more (orbit a
-- fix, go missed, hold). Each runs once when its flag goes to 1, then resets.
local MANEUVERS = {
  -- The controller's vector, applied to whichever group ai_grp selects: 1 is
  -- the single, 2 the four-ship. One flag per number because that is the whole
  -- vocabulary a user flag has.
  ai_vector = function()
    local grp = (trigger.misc.getUserFlag('ai_grp') == 2) and 'Pony 1' or 'Traffic'
    local hdg = trigger.misc.getUserFlag('ai_hdg')
    local alt = trigger.misc.getUserFlag('ai_alt') * 100
    local kts = trigger.misc.getUserFlag('ai_kts')
    if kts == 0 then kts = 210 end
    flyHeading(grp, hdg, alt, kts * 0.514444)
  end,

  ai_inbound = function()
    if BAT then flyTo('Traffic', BAT.x, BAT.y or BAT.z, 300, 90) end
  end,

  -- The four-ship, inbound to the beacon as a FORMATION. A DCS group is tasked
  -- as a whole and the wingmen fly lead's wing, so this is one cluster on the
  -- scope -- which is the point: it is the radar picture of a formation, and
  -- what the controller has to work as a single entity.
  ai_flight_inbound = function()
    if BAT then flyTo('Pony 1', BAT.x, BAT.y or BAT.z, 1830, 90) end
  end,

  -- Send the formation back out to hold, so a run can be repeated without
  -- reloading the mission.
  ai_flight_outbound = function()
    local INI = fixByName('INITIAL')
    if INI then flyTo('Pony 1', INI.x, INI.y or INI.z, 1830, 90) end
  end,
}

local function poll()
  for flag, run in pairs(MANEUVERS) do
    if trigger.misc.getUserFlag(flag) == 1 then
      trigger.action.setUserFlag(flag, 0)
      run()
    end
  end
  return timer.getTime() + 2
end

timer.scheduleFunction(poll, nil, timer.getTime() + 5)
