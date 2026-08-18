-- WHICH SORTIE A ROW BELONGS TO, decided once and looked up thereafter.
--
-- Every flight, contact and assigned plan is scoped to a `mission` key so that
-- yesterday's sortie cannot answer today's question. The key was DERIVED, on
-- every process start, as:
--
--     started = int(wall_clock_now - timer.getTime())
--
-- `timer.getTime()` is DCS MODEL time. It does not advance while the mission
-- is paused and wall clock does, so the difference is not a constant -- it
-- grows by every pause the server takes. The key therefore MOVES over the life
-- of one mission, and every process that starts after a pause computes a
-- different one.
--
-- Measured 18 August on a mission that had been up 6.7 days:
--
--     rows on the board were written under   ...@1786509383
--     a process starting now computes        ...@1786509377
--
-- Six seconds apart, so `board.find(mission=...)` matched nothing and the rows
-- were invisible. Not deleted -- unreachable, which is worse, because the
-- table looks empty rather than wrong. A pilot on the radio was refused his
-- clearance with "nobody is listed under that callsign" while his own row sat
-- in `flights` under a key nobody would compute again:
--
--     "We agreed weeks ago that a flight plan does not need to have a
--      pilot/aircraft on it ... Why would the agent respond like this?"
--
-- It was never about the plan. The plan was found; the AEROPLANE was in
-- another bucket.
--
-- SO THE KEY IS WRITTEN DOWN THE FIRST TIME A MISSION IS SEEN, and every
-- process afterwards reads it rather than recomputing. A derived value that
-- drifts cannot be made to stop drifting by rounding it -- that only widens
-- the window in which two processes agree, and this project has already
-- learned what a tolerance buys you.
--
-- A GENUINE RELOAD IS STILL A DIFFERENT WORLD, and is detected by the one
-- signal that cannot be faked: `timer.getTime()` RESTARTS. Model time is
-- monotonic within a mission, so elapsed going BACKWARDS means the sim loaded
-- something new, and only then is a fresh instance minted. Pauses move the
-- derived start; they never move elapsed backwards.
--
-- `last_elapsed` is carried for exactly that comparison and is the only column
-- that is updated after insert.  [#187]

CREATE TABLE IF NOT EXISTS mission_instances (
    id            bigserial PRIMARY KEY,
    -- The mission's own name, from `GetMissionName`. Not unique: one mission
    -- file flown twice is two instances, and telling them apart is the whole
    -- job of this table.
    name          text        NOT NULL,
    -- The instance key everything else is scoped by -- `name@started`. Stored
    -- whole rather than reassembled by each reader, because a key that is
    -- built in two places is a key that can be built two ways.
    instance      text        NOT NULL UNIQUE,
    -- Wall-clock second the mission is believed to have started. Kept for
    -- diagnosis; nothing matches on it, which is the point of the change.
    started       bigint      NOT NULL,
    -- The last model time seen for this instance. A LOWER value on a later
    -- read means the sim reloaded.
    last_elapsed  double precision NOT NULL,
    first_seen    timestamptz NOT NULL DEFAULT now(),
    last_seen     timestamptz NOT NULL DEFAULT now()
);

-- The lookup is always "the newest instance of this mission name".
CREATE INDEX IF NOT EXISTS mission_instances_by_name
    ON mission_instances (name, last_elapsed DESC);

-- ADOPT WHAT IS ALREADY ON THE BOARD, so this migration does not orphan the
-- rows it exists to stop orphaning. Every distinct `mission` value in
-- `flights` becomes a known instance, with its elapsed seeded to zero -- the
-- lowest possible value, so the first live reading is necessarily higher and
-- is not mistaken for a reload.
--
-- Rows whose mission carries no `@` are from before the scheme existed (the
-- shared 'default' bucket) and are left alone: they have no start to adopt,
-- and inventing one would claim knowledge nobody has.
INSERT INTO mission_instances (name, instance, started, last_elapsed)
SELECT DISTINCT
       split_part(f.mission, '@', 1),
       f.mission,
       COALESCE(NULLIF(split_part(f.mission, '@', 2), '')::bigint, 0),
       0
  FROM flights f
 WHERE f.mission LIKE '%@%'
   AND split_part(f.mission, '@', 2) ~ '^[0-9]+$'
ON CONFLICT (instance) DO NOTHING;
