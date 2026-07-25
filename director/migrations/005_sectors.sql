-- Airspace, and the people who work it.
--
-- The same rule as flights, one level up: which sector an aircraft is INSIDE is
-- geometry, recomputed from the scope every sweep. Which controller is WORKING
-- him is agreed -- Center keeps him until Center hands him over, and an
-- aeroplane does not change frequency by crossing a line on a chart.
--
-- Putting them on opposite sides of that rule makes the handoff trigger fall
-- out for nothing: he is inside Approach's airspace and still on Center's
-- frequency, therefore hand him over. It is the same shape as "you are four
-- hundred feet below your assigned altitude" -- a disagreement between what was
-- agreed and what is true -- and it replaces the range threshold that has been
-- sending aircraft to Tower too early, because a distance from the field is a
-- guess at a boundary that can simply be drawn.

-- The POSITION: a seat, not a person. "Batumi Approach" is a job that exists
-- whether or not anyone is sitting at it, and it owns the frequency and the
-- airspace.
CREATE TABLE IF NOT EXISTS sectors (
    name        text PRIMARY KEY,       -- 'batumi-approach'
    label       text NOT NULL,          -- 'Batumi Approach', as spoken
    role        text NOT NULL,          -- 'center' | 'approach' | 'tower' | 'ground'
    field       text,                   -- the aerodrome it serves, if any
    freq_mhz    double precision,
    -- The volume. NULL means "everywhere not claimed by anyone else", which is
    -- what a Center actually is -- drawing a polygon round the whole Caucasus
    -- to say so would be a lie in the shape of precision.
    volume      geography(Polygon, 4326),
    floor_ft    integer,
    ceiling_ft  integer,
    -- Lower numbers are handed off TO as an aircraft descends and closes:
    -- centre 10, approach 20, tower 30. Ordering the seats rather than
    -- hard-coding the sequence means a field with a Director or an Arrivals
    -- position slots in without touching code.
    rank        integer NOT NULL DEFAULT 0
);

-- The PERSON. A controller is somebody, and the same somebody may work Center
-- tonight and Tower tomorrow -- which is the point: a pilot should recognise a
-- voice and a manner across sectors, because that is what makes the field feel
-- staffed rather than generated. The voice belongs to the person, never to the
-- seat.
CREATE TABLE IF NOT EXISTS controllers (
    name        text PRIMARY KEY,       -- 'matthew'
    label       text NOT NULL,          -- 'Matthew', for logs
    voice       text NOT NULL,          -- the Polly voice, his and not the seat's
    soul        text,                   -- the prompt part that makes him himself
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Who is sitting where, right now. Separate from both, because it changes
-- while neither the seat nor the person does.
CREATE TABLE IF NOT EXISTS sector_staffing (
    mission     text NOT NULL DEFAULT 'default',
    sector      text NOT NULL REFERENCES sectors (name) ON DELETE CASCADE,
    controller  text NOT NULL REFERENCES controllers (name) ON DELETE CASCADE,
    since       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (mission, sector)
);

-- flights.controller names a SECTOR, not a role. 'approach' is ambiguous the
-- moment a second aerodrome exists, and a second aerodrome is the next test.
CREATE INDEX IF NOT EXISTS flights_sector ON flights (mission, controller);

-- Working position and observed position, side by side, and the gap between
-- them. `should_be_with` is the lowest-ranked sector whose volume actually
-- contains him: descending and closing, he ends up with Tower. When it differs
-- from `controller`, a handoff is due -- that comparison is the whole point and
-- it is deliberately not made here, because whether to act on it is a
-- controller's judgement and not a view's.
CREATE OR REPLACE VIEW flight_airspace AS
SELECT f.id,
       f.mission,
       f.callsign,
       f.controller                       AS working_with,
       (SELECT s.name FROM sectors s
         WHERE s.volume IS NOT NULL
           AND ST_Intersects(s.volume, t.geog)
           AND (s.floor_ft   IS NULL OR t.alt_ft >= s.floor_ft)
           AND (s.ceiling_ft IS NULL OR t.alt_ft <= s.ceiling_ft)
         ORDER BY s.rank DESC
         LIMIT 1)                         AS should_be_with,
       t.geog,
       t.alt_ft
FROM flights f
LEFT JOIN tracks t ON t.name = f.track_name;
