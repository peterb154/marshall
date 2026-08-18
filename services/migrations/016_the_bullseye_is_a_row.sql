-- The sim's bullseye per coalition, stored rather than cached in a process.
--
-- ASKED, NOT DEFINED. DCS has one per coalition and every pilot's HSI is
-- referenced to it, so inventing our own would give the controller a reference
-- nobody in a cockpit can see. Same rule as the coordinate projection: the sim
-- is the authority on its own map.
--
-- WHY IT STOPS BEING A MODULE DICT. `tools.tracks._BULLSEYE` cached it with
-- this reasoning:
--
--     "Cached because it does not move within a mission, and a mission change
--      restarts this process."
--
-- That was true when it was written and is not true any more. The mission reset
-- added on 31 July detects the mission clock running backwards and wipes the
-- world WITHOUT restarting anything, so the cache would outlive the mission it
-- described and serve the previous map's bullseye -- confidently, with no way
-- to tell. A cache whose invalidation story is "the process dies" is a bug
-- waiting for the day the process stops dying, and that day was today.
--
-- It is also what blocked the bridge from reading the scope out of `tracks`:
-- the /radar payload carried this and the table did not, so switching would
-- have blanked the "from bullseye" column on the untracked table -- the only
-- reference that means anything for a contact nobody is working.
--
-- PER MISSION, so it is wiped with everything else flown. A bullseye belongs to
-- a world, and when the world restarts this one is about somewhere else.

CREATE TABLE IF NOT EXISTS bullseye (
    coalition   TEXT PRIMARY KEY,          -- 'red' | 'blue'
    lat         DOUBLE PRECISION NOT NULL,
    lon         DOUBLE PRECISION NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
