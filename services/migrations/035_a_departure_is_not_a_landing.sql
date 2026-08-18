-- Has he left the ground on this sortie? A LATCH, because the phase cannot say.
--
-- `phases.has_flown` answers this from the phase, and that works for every
-- phase except one. `departure` STRADDLES: you are in it from Tower's first
-- word, through the roll, until Departure lets you go -- and most of that is
-- spent stationary on the runway. So the phase genuinely does not know whether
-- a man holding there has already flown a circuit.
--
-- It guessed, and it guessed in the dangerous direction. 18 August, live:
--
--     15:20:12  PILOT  holding short, runway 7, ready for departure   (0 kt)
--     15:20:14  board  sortie_phase = departure
--     15:20:30  PILOT  clear for takeoff, runway seven                (0 kt)
--     15:20:33  board  sortie_phase = LANDED     <- never left the ground
--     15:21:20  PILOT  ...actually gets airborne, 47 seconds later
--
-- For the next thirteen miles Kobuleti Departure posted him back to Kobuleti
-- Tower, twelve times, because a landed aeroplane is Tower's. Tower's own
-- "contact Departure when airborne" was refused as an unauthorised handoff for
-- the same reason, so a read-back was answered with "go ahead".
--
-- WHY A COLUMN AND NOT A FLAG. The board is a write-through cache of this
-- table and a restart rebuilds it here. Without a column, a reconnect
-- mid-climb-out forgets he ever flew -- and since `departure` is no longer
-- evidence of having flown, the first time he stops on a runway he would not
-- be recognised as landed. That is the same bug wearing the opposite sign,
-- reachable by the restart that the write-through cache exists to survive.
--
-- SET ON POSITIVE EVIDENCE ONLY, which is #164's rule and its scar: `not
-- on_ground` is not `airborne`. A track radar has stopped seeing answers False
-- to `on_ground` with no position at all, and reading that as flying would
-- latch every aeroplane whose track went quiet on the ramp. The writer
-- requires the scope to actually hold him.
--
-- ONCE TRUE IT STAYS TRUE. He cannot un-fly a sortie.  [#178]

ALTER TABLE flights ADD COLUMN IF NOT EXISTS has_been_airborne boolean;

-- BACKFILLED FROM THE PHASE, which is the only evidence the existing rows
-- carry. An aeroplane already in a phase that only exists in the air has
-- certainly flown; anything else is left NULL rather than guessed, because a
-- false latch would derive a parked aeroplane as landed and that is the defect
-- this migration is for.
UPDATE flights
   SET has_been_airborne = true
 WHERE has_been_airborne IS NULL
   AND sortie_phase IN ('enroute', 'tasked', 'on_station', 'rtb',
                        'arrival', 'holding', 'approach', 'missed', 'landed',
                        'taxi_in');

-- ...AND ONTO THE VIEW THE RADIO ACTUALLY READS. `flight_state` is what
-- `Controller.hydrate` joins; a column the view does not carry is a column the
-- board cannot restore, which is how four facts were lost across a restart
-- before migration 026 put them here.
--
-- COLUMNS LISTED, NOT `f.*`, because that is how the view is written and a
-- migration is not the place to change the shape of something it only needs to
-- extend. Reproduced from `pg_get_viewdef` rather than from memory: the first
-- draft of this file had `squawk` coming from `tracks` (it is
-- `assigned_plans`), `observed_at` as `t.observed_at` (it is `t.last_seen`),
-- `radar_identified` as a column (it is `t.name IS NOT NULL`) and
-- `alt_error_ft` off `cruise_ft` (it is `assigned_ft`). Four wrong in one
-- view, none of which would have failed loudly.
DROP VIEW IF EXISTS flight_state;
CREATE VIEW flight_state AS
 SELECT f.id,
    f.mission,
    f.callsign,
    f.track_name,
    f.srs_guid,
    f.srs_name,
    f.intent,
    f.destination,
    f.claimed_size,
    f.controller,
    f.handed_off_at,
    f.procedure,
    f.runway,
    f.cleared,
    f.assigned_ft,
    f.assigned_hdg,
    f.sequence_no,
    f.missed_count,
    f.promised,
    f.promised_at,
    f.lead_of,
    f.first_seen,
    f.updated_at,
    f.flight_plan,
    f.origin,
    f.route,
    f.cruise_ft,
    f.clearance_ack,
    f.flight_plan_label,
    f.sortie_phase,
    f.on_visual,
    f.approaches_flown,
    f.atis_letter,
    f.has_been_airborne,
    a.squawk,
    a.approach AS cleared_approach,
    t.geog,
    t.alt_ft AS observed_alt_ft,
    t.heading AS observed_heading,
    t.last_seen AS observed_at,
    t.name IS NOT NULL AS radar_identified,
    t.alt_ft - f.assigned_ft::double precision AS alt_error_ft
   FROM flights f
     LEFT JOIN tracks t ON t.name = f.track_name
     LEFT JOIN assigned_plans a ON a.flight_id = f.id;
