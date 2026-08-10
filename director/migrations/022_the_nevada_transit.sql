-- The Nellis to Tonopah leg, on the board, so the Nevada theatre has a plan.
--
-- The bridge seeds a flight plan at start-up and reads its approach back as the
-- source of truth -- see `load_and_push_plate`. Which plan is a property of the
-- THEATRE now (`core/theatre.py`), so a Nevada bridge asks for a row that has
-- to exist, and a row with no route or label is the empty-strip problem of
-- migration 018 all over again.
--
-- **Route** names the fixes `core/nevada.py` publishes, spelled as they are
-- there: NELLIS, TONOPAH. The leg between them is flown on the TPH VORTAC,
-- which is a fix in its own right.
--
-- **Cruise 24,000.** Not a round number for its own sake: Tonopah's surveyed
-- vectoring minima reach 10,500 ft and its holding stack starts at 12,000, so
-- an enroute level has to sit clear above both. The Caucasus plans cruise at
-- three to eleven thousand, which over Nevada would be inside the terrain.
--
-- **Recovery is the Tonopah ILS to 15**, which is what the wind chooses at 210.
-- Both ends have an ILS; only 15 is modelled.
--
-- NOT ACTIVE. `active` picks what a bridge loads, and the two theatres must not
-- fight over it: the Caucasus plan holds the flag today and a Nevada bridge
-- sets this one when it starts.

INSERT INTO approaches (name, field, data)
SELECT 'tonopah-ils', 'Tonopah', '{}'::jsonb
 WHERE NOT EXISTS (SELECT 1 FROM approaches WHERE name = 'tonopah-ils');

INSERT INTO flight_plans (name, label, callsign, approach, origin, destination,
                          route, cruise_ft, task, active)
VALUES ('nevada-nellis-tonopah', 'Silverstate', NULL, 'tonopah-ils',
        'Nellis', 'Tonopah', 'NELLIS, TONOPAH', 24000,
        'Transit and instrument recovery', false)
ON CONFLICT (name) DO UPDATE SET
    label       = EXCLUDED.label,
    approach    = EXCLUDED.approach,
    origin      = EXCLUDED.origin,
    destination = EXCLUDED.destination,
    route       = EXCLUDED.route,
    cruise_ft   = EXCLUDED.cruise_ft,
    task        = EXCLUDED.task;
