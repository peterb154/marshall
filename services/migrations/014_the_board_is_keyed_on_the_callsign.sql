-- One row per callsign per mission, because that is what a board IS.
--
-- The separation engine is a dict keyed on the callsign; two entries under one
-- name is not a state it has any meaning for. This table has enforced one row
-- per TRACK (flights_track, migration 012) and one per RADIO (flights_srs_guid)
-- since the board was designed -- but never one per NAME, which is the key the
-- engine actually uses and the only one it can be asked about.
--
-- It matters now because the board is moving out of that dict and into this
-- table. `save_board` upserts on (mission, callsign), and an upsert needs a
-- constraint to conflict against; without one the ON CONFLICT clause is a
-- syntax error and the board silently never persists.
--
-- WHY THIS IS SAFE TO ADD TODAY and would not have been last week: rows here
-- accumulated across missions for days, so duplicate callsigns from different
-- sorties were normal and expected. They are not any more -- the world is
-- wiped when the mission restarts (`tracks.clear_all`), so every row in this
-- table describes the aeroplane flying right now. A duplicate callsign is a
-- bug rather than history.
--
-- NULL callsigns are excluded. A row can exist before anybody has been named --
-- the radio has been heard and identity has not closed -- and several such rows
-- are not a conflict, they are several unidentified aircraft.

-- Any leftovers from before the mission-reset rule. Keep the most recently
-- updated of each name: it is the one the engine last believed.
DELETE FROM flights a
      USING flights b
      WHERE a.mission = b.mission
        AND a.callsign IS NOT NULL
        AND a.callsign = b.callsign
        AND (a.updated_at, a.id) < (b.updated_at, b.id);

CREATE UNIQUE INDEX IF NOT EXISTS flights_mission_callsign
    ON flights (mission, callsign)
    WHERE callsign IS NOT NULL;
