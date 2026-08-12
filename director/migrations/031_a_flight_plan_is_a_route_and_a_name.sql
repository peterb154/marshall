-- A flight plan is a label, a route, and what he is going out to do.
--
--     "And yes, the origin should be determined at request time, the
--      destination is the last point. We should not define an approach in the
--      flight plan. there should be no cruise alt in flight plan."
--
-- Every column dropped here was one of two things: a fact about the CLEARANCE
-- wearing a plan's clothes, or a second copy of the route.
--
-- THE CLEARANCE ALREADY OWNS THEM, which is what makes this safe rather than
-- lossy. `assigned_plans` has carried its own `origin`, `destination`, `route`,
-- `cruise_ft` and `approach` since migration 009 -- so the split this makes is
-- one the schema had already half-built and nobody finished. Where you departed
-- from and which approach you are flying are things a controller ISSUES, and
-- they belong on the row that records what was issued.
--
--   approach   which arrival you fly is a fact about your clearance, not your
--              route. This column is what let the bridge read its own arrival
--              out of a plan row (#131) and fly a man a talkdown after he asked
--              for an ILS.
--   cruise_ft  "A flight plan shouldn't have a cruise altitude. Just waypoints
--              and altitude at each." Each leg carries its own; a single number
--              beside them is a second answer to the same question.
--   origin     determined at request time. He calls Kobuleti Clearance from a
--              parking spot at Kobuleti; asking him to have written it down
--              beforehand is asking him to tell you where he already is.
--   destination the last leg. It was in the row twice.
--   route      the legs, spoken. THE TWO ALREADY DISAGREED on the live board --
--              route said "FOO, BAR, SPAM, INITIAL" while legs ended at BATUMI,
--              so validation read one and the map read the other. Derived now,
--              from the one list that has positions in it.
--   active     dead since #131, and a NOT NULL column nothing sets is a thing
--              somebody will eventually read again.
--   weather    never used.
--
-- WHAT IS LEFT is `label` (the one word a pilot says), `legs` (the route, with
-- a position and an altitude each) and `task`. `name` stays as the key -- it is
-- the FK target for `assigned_plans.template` -- but stops being something a
-- pilot types: it is generated from the label now. Two hand-authored
-- identifiers for one plan was one too many, and the label is the one with a
-- reason: it has to survive being said out loud through Whisper.

-- BACKFILL BEFORE DROPPING, and I did not the first time.
--
-- Two Nevada plans on the live board carried their route in `route` and had no
-- `legs` at all -- they were filed before migration 030 added them -- so the
-- DROP took their routes with it. Recovered by hand there; written here so no
-- other database loses them, and so a re-run is harmless.
--
-- The legs are built from the enroute fixes plus the destination, at the old
-- cruise level. No lat/lon: these are PUBLISHED names or they are nothing, and
-- inventing a position for one is exactly what #133 and FEET WET were about.
UPDATE flight_plans
   SET legs = (
        SELECT COALESCE(jsonb_agg(jsonb_build_object(
                   'fix', upper(trim(f)), 'alt_ft', COALESCE(cruise_ft, 0))
               ORDER BY ord), '[]'::jsonb)
          FROM unnest(string_to_array(
                 CASE WHEN COALESCE(route, '') = '' THEN destination
                      ELSE route || ', ' || destination END, ',')
               ) WITH ORDINALITY AS s(f, ord)
         WHERE trim(f) <> '')
 WHERE (legs IS NULL OR legs = '[]'::jsonb)
   AND COALESCE(destination, '') <> '';

ALTER TABLE flight_plans
    DROP COLUMN IF EXISTS approach,
    DROP COLUMN IF EXISTS cruise_ft,
    DROP COLUMN IF EXISTS origin,
    DROP COLUMN IF EXISTS destination,
    DROP COLUMN IF EXISTS route,
    DROP COLUMN IF EXISTS active,
    DROP COLUMN IF EXISTS weather;

-- A plan with no legs is not a plan. It could be filed before this, and it
-- read on the board as a route to nowhere with a name attached.
ALTER TABLE flight_plans
    ALTER COLUMN legs SET DEFAULT '[]'::jsonb;

UPDATE flight_plans SET legs = '[]'::jsonb WHERE legs IS NULL;
