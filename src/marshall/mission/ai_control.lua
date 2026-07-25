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

-- Maneuvers keyed to flag NAMES. Extend this table as tests need more (orbit a
-- fix, go missed, hold). Each runs once when its flag goes to 1, then resets.
local MANEUVERS = {
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
