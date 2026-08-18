-- Everything the board remembers about an aeroplane, in the table.
--
--     "there really shouldn't be much in memory data structures - we addressed
--      this - database is fast and should be the single source of truth"
--
-- `Controller.aircraft` holds the whole board and four of the things it holds
-- have no column, so they exist only inside one process: a bridge restart
-- forgets them while the aeroplanes go on flying. See docs/STATE.md and #120.
--
-- `sortie_phase` IS THE IMPORTANT ONE. `flights.cleared` already carries the
-- SEPARATION enum -- where he sits in the arrival queue -- and `sortie_phase` is
-- a different question: what he is DOING. Clearance, taxi, holding short,
-- departure, enroute, approach, landed, taxi_in. It is what `handoff.due` reads
-- to decide who owns him, and a phase with no geometry is owned outright by the
-- controller the phase table names -- so losing it on a restart means losing
-- the entire ground half of a sortie and every handoff that follows from it.
--
-- The other three are smaller and are the same argument:
--
--   on_visual         he is flying it himself. The talk-down must stop, and a
--                     restart that forgets it starts reading ranges to a man
--                     looking out of the window.
--   approaches_flown  how many he has already flown, which is what a second
--                     missed approach is counted against.
--   atis_letter       which information he said he has, so the next controller
--                     does not ask him again.
--
-- NOT position, NOT altitude observed, NOT speed. Those are radar's and live in
-- `tracks`, reconciled every sweep. A second copy of a position is the bug that
-- table exists to kill, and nothing here may hold one.

ALTER TABLE flights ADD COLUMN IF NOT EXISTS sortie_phase text;
ALTER TABLE flights ADD COLUMN IF NOT EXISTS on_visual boolean NOT NULL DEFAULT false;
ALTER TABLE flights ADD COLUMN IF NOT EXISTS approaches_flown integer NOT NULL DEFAULT 0;
ALTER TABLE flights ADD COLUMN IF NOT EXISTS atis_letter text;

-- AND ON THE STRIP. `flight_state` is what every reader actually joins -- the
-- bridge, the plate, the diag page -- so a fact that exists in `flights` alone
-- is a fact nothing can reach. Migration 023 said exactly this about the squawk
-- and 025 rediscovered it about the approach; this is the third time, which is
-- why the view is rebuilt in the same file as the columns rather than later.
DROP VIEW IF EXISTS flight_state;
CREATE VIEW flight_state AS
SELECT f.id, f.mission, f.callsign, f.track_name, f.srs_guid, f.srs_name,
       f.intent, f.destination, f.claimed_size, f.controller, f.handed_off_at,
       f.procedure, f.runway, f.cleared, f.assigned_ft, f.assigned_hdg,
       f.sequence_no, f.missed_count, f.promised, f.promised_at, f.lead_of,
       f.first_seen, f.updated_at, f.flight_plan, f.origin, f.route,
       f.cruise_ft, f.clearance_ack, f.flight_plan_label,
       f.sortie_phase, f.on_visual, f.approaches_flown, f.atis_letter,
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
