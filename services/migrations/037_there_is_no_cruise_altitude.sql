-- A plan has a level per LEG. There is no cruise altitude, and there never was.
--
--     "There is no cruise altitude, this has been something I've harped on for
--      weeks. And it's still in the schema? There is only leg altitude."
--
-- `cruise_ft` was never filed by anybody. It was `max(alt_ft)` synthesised in
-- `filing.derived` on the way out of the table, and then written down:
--
--     migration 009   flight_plans.cruise_ft      a column a pilot filled
--     migration 030   legs arrive -- "a plan has altitudes, not an altitude"
--     migration 031   flight_plans.cruise_ft DROPPED as a second answer to a
--                     question `legs` already answers
--
-- and it survived on `flights` and on `assigned_plans`, so from 031 onward a
-- number nobody filed was stored TWICE, downstream of the table it had just
-- been deleted from. `filing.derived` kept computing it, so both copies looked
-- populated and correct, and nothing could tell they were an invention.
--
-- THE NAME IS THE DEFECT, NOT THE NUMBER. The value is the highest level a
-- route asks for, which is exactly what a controller voices as "expect one
-- zero thousand" -- and `filing.derived`'s own docstring conceded that one
-- column could not carry both questions while emitting it anyway:
--
--     the CLEARANCE altitude is legs[0], and which is which is exactly what a
--     single cruise_ft column could never say.
--
-- TWO QUESTIONS, TWO ANSWERS, NEITHER OF THEM A CRUISE:
--
--     what he is HELD to      `flights.assigned_ft` -- the level the engine
--                             issued him, which is the only one he may be
--                             held to and the only one separation reads
--     what he may EXPECT      the top of his route, computed from the legs
--                             where it is spoken (`plans.top_of_route`) and
--                             stored nowhere
--
-- NOTHING IS MIGRATED INTO ANOTHER COLUMN, deliberately. There is no fact here
-- to preserve: every value was derivable from `legs` and is still derivable
-- from `legs`. Copying it somewhere else would move the fiction rather than
-- end it, which is what 031 did by leaving these two behind.  [#192]

-- BOTH VIEWS FIRST, because Postgres refuses to drop a column anything
-- selects. TWO of them do, and the second was found by asking the database
-- rather than by reading: `flight_with_plan` carries `a.cruise_ft` and is not
-- mentioned anywhere this change would otherwise have looked.
--
-- Rebuilt from `pg_get_viewdef` rather than from memory -- migration 035's own
-- note records what happens otherwise: its first draft reconstructed four
-- columns and got all four wrong, none of them loudly.
DROP VIEW IF EXISTS flight_state;
DROP VIEW IF EXISTS flight_with_plan;

ALTER TABLE assigned_plans DROP COLUMN IF EXISTS cruise_ft;
ALTER TABLE flights DROP COLUMN IF EXISTS cruise_ft;

CREATE VIEW flight_with_plan AS
 SELECT f.id,
    f.mission,
    f.callsign,
    f.track_name,
    f.controller,
    f.cleared,
    a.template,
    a.label,
    a.origin,
    a.destination,
    a.route,
    a.task,
    a.approach,
    a.assigned_at,
    a.acked_at
   FROM flights f
     LEFT JOIN assigned_plans a ON a.flight_id = f.id;

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
