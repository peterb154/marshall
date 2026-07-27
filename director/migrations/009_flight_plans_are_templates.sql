-- Flight plans become filed TEMPLATES, and a flight gets a COPY.
--
-- Today there is exactly one plan and it is mission-wide: `active` is a boolean,
-- every insert does `UPDATE flight_plans SET active=false` first, and the bridge
-- loads that one at startup to build the plate. Two flights cannot be going to
-- two different places, and a plan cannot be flown twice.
--
--     "Perhaps a flight plan on file doesn't have a callsign assigned to it yet.
--      When a flight plan is assigned - it is copied to an active flight plan
--      assigned to a flight. This would allow 2 flights to reuse the same plan.
--      Or the same plan to be reused night after night."
--
-- That is the shape. A template is filed against nobody; assignment copies it
-- onto the flight. The copy is the point rather than a convenience: it is the
-- same rule as everything else here -- the TEMPLATE is what was filed, the
-- INSTANCE is what was agreed -- so a controller amending one flight's routing
-- never edits the plan somebody else is flying, and never edits tonight's plan
-- for next week.
--
-- `callsign` stays on the template and becomes advisory: "this plan is normally
-- flown by Pony 1-1", used to offer a plan to a caller who does not name one. It
-- no longer OWNS the plan.

ALTER TABLE flight_plans ADD COLUMN IF NOT EXISTS origin      text;
ALTER TABLE flight_plans ADD COLUMN IF NOT EXISTS destination text;
ALTER TABLE flight_plans ADD COLUMN IF NOT EXISTS route       text;
ALTER TABLE flight_plans ADD COLUMN IF NOT EXISTS cruise_ft   integer;
-- What the flight is FOR -- "CAS on the lake", "ferry", "patrol". The controller
-- can answer "what am I doing" from this, and the overlord can task against it.
ALTER TABLE flight_plans ADD COLUMN IF NOT EXISTS task        text;

-- The assigned copies. One row per flight that has been given a plan; the
-- flight's own row points here by id, so `flights` keeps carrying only what was
-- AGREED and the routing lives beside it rather than inside it.
CREATE TABLE IF NOT EXISTS assigned_plans (
    id          serial PRIMARY KEY,
    mission     text NOT NULL DEFAULT 'default',
    flight_id   integer NOT NULL REFERENCES flights (id) ON DELETE CASCADE,
    -- The template it came from, kept for provenance. ON DELETE SET NULL because
    -- deleting a filed plan must never take a flight's clearance with it.
    template    text REFERENCES flight_plans (name) ON DELETE SET NULL,
    origin      text,
    destination text,
    route       text,
    cruise_ft   integer,
    task        text,
    approach    text REFERENCES approaches (name),
    assigned_at timestamptz NOT NULL DEFAULT now(),
    -- Set when the pilot reads the clearance back. Filed and agreed are not the
    -- same thing, and the gap between them is a controller's business.
    acked_at    timestamptz
);

-- One live plan per flight. A flight given a second plan is being AMENDED, and
-- an amendment replaces rather than accumulates -- two live plans for one
-- aeroplane is the ambiguity this table exists to remove.
CREATE UNIQUE INDEX IF NOT EXISTS assigned_plans_one_per_flight
    ON assigned_plans (flight_id);

CREATE INDEX IF NOT EXISTS assigned_plans_mission ON assigned_plans (mission);

-- What a controller actually wants to know: who is flying, what they were
-- given, and where they are going. Joined so nothing has to ask twice.
DROP VIEW IF EXISTS flight_with_plan;
CREATE VIEW flight_with_plan AS
SELECT f.id,
       f.mission,
       f.callsign,
       f.track_name,
       f.controller,
       f.cleared,
       a.template,
       a.origin,
       a.destination,
       a.route,
       a.cruise_ft,
       a.task,
       a.approach,
       a.assigned_at,
       a.acked_at
FROM flights f
LEFT JOIN assigned_plans a ON a.flight_id = f.id;
