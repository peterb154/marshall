-- A CLEARANCE IS NOT RECORDED UNTIL ALL OF IT IS.
--
-- `assigned_plans` holds the clearance limit, the route, the cruise level and
-- the approach -- everything a pilot writes down except the squawk, which was
-- computed from the flight id at the moment the words were composed and then
-- thrown away.
--
-- It cost a card row. `clearance_read_back` exists to end Delivery's business
-- and hand the aircraft to Ground, and it can only judge a read-back against
-- the clearance that was issued. With the squawk missing, a read-back that got
-- the squawk wrong -- which is exactly what happened on 10 August, twice --
-- would have verified as correct against altitude and frequency alone, and the
-- pilot would have been handed on mid-correction.
--
-- Derived, not random (`plans.squawk_for`), so this is recoverable for existing
-- rows; storing it is about the RECORD being complete, which is the same
-- argument as `acked_at`: filed, given and agreed are three different things.
ALTER TABLE assigned_plans ADD COLUMN IF NOT EXISTS squawk text;

-- AND ON THE STRIP, not only in the copy. `flight_state` is what every reader
-- actually joins -- the bridge, the plate, the diag page -- so a fact that
-- exists in `assigned_plans` alone is a fact nothing can reach. That is the
-- shape this project keeps finding, and it is cheaper to avoid than to
-- rediscover.
DROP VIEW IF EXISTS flight_state;
CREATE VIEW flight_state AS
SELECT f.id, f.mission, f.callsign, f.track_name, f.srs_guid, f.srs_name,
       f.intent, f.destination, f.claimed_size, f.controller, f.handed_off_at,
       f.procedure, f.runway, f.cleared, f.assigned_ft, f.assigned_hdg,
       f.sequence_no, f.missed_count, f.promised, f.promised_at, f.lead_of,
       f.first_seen, f.updated_at, f.flight_plan, f.origin, f.route,
       f.cruise_ft, f.clearance_ack, f.flight_plan_label,
       a.squawk,
       t.geog,
       t.alt_ft   AS observed_alt_ft,
       t.heading  AS observed_heading,
       t.last_seen AS observed_at,
       t.name IS NOT NULL AS radar_identified,
       t.alt_ft - f.assigned_ft::double precision AS alt_error_ft
  FROM flights f
  LEFT JOIN tracks t ON t.name = f.track_name
  LEFT JOIN assigned_plans a ON a.flight_id = f.id;
