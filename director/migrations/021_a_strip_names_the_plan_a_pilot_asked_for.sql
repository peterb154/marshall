-- The spoken label, on the flight row, so a controller's strip can say it.
--
-- Assignment has always worked. A pilot asks Clearance for "Domino", the plan is
-- matched from his own words, COPIED into `assigned_plans` against his flight,
-- denormalised onto `flights`, and stamped when he reads it back. Every field is
-- populated and correct.
--
-- What was missing is that `flights` kept the plan's NAME -- 362nd-kobuleti-batumi
-- -- and not its LABEL. The name is a key; the label is the word the pilot said
-- and the word a controller would use back. So a strip could say "on
-- 362nd-kobuleti-batumi", which is a database row read out loud, or say nothing,
-- which is what it did.
--
-- Denormalised alongside `flight_plan`, `route` and `cruise_ft` for the same
-- reason those are: this is what was AGREED with one aeroplane, and relabelling
-- the template later must not retrospectively change what he was cleared on.
-- `assigned_plans` already keeps the authoritative copy.

ALTER TABLE flights ADD COLUMN IF NOT EXISTS flight_plan_label text;

-- What is already flying keeps its name. One row today; the join is cheap and
-- this file should not need a second run.
UPDATE flights f
   SET flight_plan_label = a.label
  FROM assigned_plans a
 WHERE a.flight_id = f.id
   AND f.flight_plan_label IS NULL
   AND a.label IS NOT NULL;

DROP VIEW IF EXISTS flight_state;
CREATE VIEW flight_state AS
SELECT f.*,
       t.geog,
       t.alt_ft        AS observed_alt_ft,
       t.heading       AS observed_heading,
       t.last_seen     AS observed_at,
       (t.name IS NOT NULL) AS radar_identified,
       t.alt_ft - f.assigned_ft::double precision AS alt_error_ft
  FROM flights f
  LEFT JOIN tracks t ON t.name = f.track_name;
