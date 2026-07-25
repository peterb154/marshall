-- This is a combat sim, and until now the world contained only aeroplanes.
--
-- The scenario that makes the point: a flight plan to fly CAS over somewhere
-- remote. Tasking arrives -- an overlord has quietly spawned armour in a town
-- and now wants it dead. The flight goes, works it, comes home, and finishes
-- with an approach. Every part of that is the same aircraft, the same identity,
-- the same stated intent, moving through the same state row; only the middle is
-- new.
--
-- An OVERLORD is not a new kind of machine. It is a controller with a wider
-- scope: it has a frequency, it has a personality, it works aircraft, and it
-- fits the sectors table already -- role 'overlord', volume NULL, which is
-- exactly what a Center is. What it adds is the ability to give a flight a job
-- rather than a heading.
--
-- And it obeys the same rule as everything else here:
--
--     AGREED   what he was tasked with, where his station is, what he was
--              told the target was, when he is due off
--     TRUE     where the armour actually is, whether it is still alive,
--              whether he is anywhere near it
--
-- Which gives target validation for nothing. The tasking says "kill this"; the
-- world says whether it is still there. Nobody has to model destruction: the
-- track stops being in `tracks`, and that IS the answer -- the same shape as
-- "assigned 8,000, observed 7,600".
--
-- REQUIRES a change outside this file: tools/tracks.py streams only
-- GROUND_UNIT's air cousins (AIRPLANE, HELICOPTER), so armour never reaches the
-- table. Adding GROUND_UNIT and SHIP to the streamed categories is what turns
-- these columns from a schema into a working picture.

CREATE TABLE IF NOT EXISTS taskings (
    id          bigserial PRIMARY KEY,
    mission     text NOT NULL DEFAULT 'default',
    flight_id   bigint REFERENCES flights (id) ON DELETE CASCADE,

    -- Who gave it, so a pilot can be told to go back to them, and so two
    -- overlords cannot quietly countermand each other.
    issued_by   text,                   -- sectors.name of the overlord

    kind        text NOT NULL,          -- 'cas' | 'cap' | 'strike' | 'escort' |
                                        -- 'recce' | 'tanker' | 'rtb'
    -- What he was TOLD. Free text on purpose: "armour in the town at the north
    -- end of the valley" is how this is actually said, and a schema for it
    -- would be a schema for a sentence.
    briefing    text,

    -- Where. A point plus a radius covers a station, a target area and a
    -- kill box; a polygon can come later if a shape ever needs to be a shape.
    area        geography(Point, 4326),
    radius_m    integer,
    -- The specific thing, when there is one. tracks.name, so "is it still
    -- alive" is a lookup and not a judgement.
    target_name text,
    target_desc text,                   -- what he was told it was

    -- Time on station: fragged, and actual.
    on_station_from timestamptz,
    on_station_to   timestamptz,
    checked_in_at   timestamptz,
    checked_out_at  timestamptz,

    -- AGREED status. Whether the target is actually dead is a question for the
    -- world, not for this column -- this records what the overlord and the
    -- pilot last agreed had happened.
    status      text NOT NULL DEFAULT 'assigned',
        -- assigned | acknowledged | on_station | engaged | complete |
        -- aborted | no_joy
    result      text,                   -- what he reported

    issued_at   timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS taskings_flight  ON taskings (mission, flight_id);
CREATE INDEX IF NOT EXISTS taskings_status  ON taskings (mission, status);
CREATE INDEX IF NOT EXISTS taskings_area    ON taskings USING gist (area);

COMMENT ON COLUMN flights.cleared IS
    'What was AGREED, over the whole life of the flight: filed | clearance | '
    'taxi | departure | enroute | tasked | on_station | rtb | arrival | '
    'holding | approach | missed | landed. Never what the scope observes -- '
    'that is geometry.';

-- Tasking beside the world, which is the only view that matters here. Is the
-- target still there, and is he anywhere near it -- both answered from the live
-- track cache rather than from anything anyone claimed. `target_alive` is null
-- rather than false when no specific target was named, because "no target" and
-- "target destroyed" are different answers and collapsing them would let an
-- overlord congratulate a flight for a kill nobody made.
CREATE OR REPLACE VIEW tasking_state AS
SELECT k.*,
       f.callsign,
       f.controller,
       (SELECT true FROM tracks t WHERE t.name = k.target_name)  AS target_alive,
       (SELECT ST_Distance(t.geog, k.area) FROM tracks t
         WHERE t.name = ft.track_name)                           AS metres_from_area
FROM taskings k
JOIN flights f  ON f.id = k.flight_id
LEFT JOIN flights ft ON ft.id = k.flight_id;
