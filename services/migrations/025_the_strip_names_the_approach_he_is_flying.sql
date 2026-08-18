-- Which approach this flight was cleared for, on the strip.
--
--     "One approach profile per flight, not per bridge -- THIS IS THE WALL IN
--      FRONT OF MULTIPLE AIRPORTS."                            -- #2, day one
--
-- `assigned_plans.approach` has named it since the plans table existed, and
-- `flight_state` did not expose it -- so the bridge, which joins the view and
-- nothing else, could not find out which procedure an aeroplane was recovering
-- on. It read the one profile the bridge had been started with and gave every
-- aircraft that field's runway, minima, missed approach and stack levels.
--
-- Every number is real, which is why nothing looked wrong: it is a genuine
-- approach to a genuine runway, belonging to the wrong airport. The same shape
-- as `station_for` before it took a field.
--
-- EXACTLY THE GAP MIGRATION 023 CLOSED FOR THE SQUAWK, and its comment says
-- why in general terms: "a fact that exists in `assigned_plans` alone is a fact
-- nothing can reach. That is the shape this project keeps finding, and it is
-- cheaper to avoid than to rediscover." Rediscovered anyway, eleven days later,
-- one column along.
--
-- `procedure` on `flights` is NOT this. That is what a controller has observed
-- or been told he is flying, set by `flight_agree`; this is what his CLEARANCE
-- says, which is the thing the engine must compute his letdown from. Two facts,
-- both worth having, and conflating them would mean a pilot's own description
-- of what he was doing could change the minima he is held to.

DROP VIEW IF EXISTS flight_state;
CREATE VIEW flight_state AS
SELECT f.id, f.mission, f.callsign, f.track_name, f.srs_guid, f.srs_name,
       f.intent, f.destination, f.claimed_size, f.controller, f.handed_off_at,
       f.procedure, f.runway, f.cleared, f.assigned_ft, f.assigned_hdg,
       f.sequence_no, f.missed_count, f.promised, f.promised_at, f.lead_of,
       f.first_seen, f.updated_at, f.flight_plan, f.origin, f.route,
       f.cruise_ft, f.clearance_ack, f.flight_plan_label,
       a.squawk,
       a.approach AS cleared_approach,
       t.geog,
       t.alt_ft   AS observed_alt_ft,
       t.heading  AS observed_heading,
       t.last_seen AS observed_at,
       t.name IS NOT NULL AS radar_identified,
       t.alt_ft - f.assigned_ft::double precision AS alt_error_ft
  FROM flights f
  LEFT JOIN tracks t ON t.name = f.track_name
  LEFT JOIN assigned_plans a ON a.flight_id = f.id;
