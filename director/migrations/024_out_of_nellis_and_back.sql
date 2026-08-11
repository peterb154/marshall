-- The sortie a Nevada pilot actually wants: out of Nellis, and home to Nellis.
--
--     "Make sure everything works for a test flight out of Nellis then back in
--      on the ils"
--
-- Migration 022 filed Nellis to Tonopah, which is a one-way transit and leaves
-- the pilot at the other field. A range sortie departs and RECOVERS AT HOME, and
-- that is not the same plan with the destination edited: the recovery approach
-- is different, and the recovery approach is what the bridge loads.
--
--     "a flight that departs Nellis, works the range, and returns to Nellis
--      needs that profile and its arrival state during the same sortie. It
--      cannot be selected concurrently with the Tonopah recovery."
--                                                -- CODEX_NTTR_AUDIT.md
--
-- Correct, and the honest scope of this migration is the second half of the
-- problem only. The bridge still runs ONE arrival profile at a time; what this
-- adds is a plan whose recovery is the Nellis ILS, so the sortie the pilot asked
-- for can be selected. Per-flight procedure selection -- so an outbound and an
-- inbound aircraft can be worked at once, each on its own approach -- is the
-- real fix and is #111.
--
-- **Route** NELLIS, TONOPAH, NELLIS. The TPH VORTAC is the turning point, which
-- is what the leg is flown on and what `core/nevada.py` publishes as a fix. It
-- is not a range route: nothing here models the ranges, and calling a
-- there-and-back transit a range mission would be the plausible wrong answer
-- this project keeps meeting.
--
-- **Cruise 24,000**, the same reasoning as 022: Tonopah's surveyed vectoring
-- minima reach 10,500 and its stack starts at 12,000, so an enroute level has to
-- sit clear above both. The leg passes over the same ground in both directions.
--
-- **Recovery is the Nellis ILS to 21L.** Nellis's runway is 209 magnetic and the
-- wind is 210 at 8, so 21 is the end the weather chooses -- the same rule the
-- ATIS applies, arrived at from the same numbers.
--
-- NOT ACTIVE, for the same reason 022 is not: `active` picks what a bridge
-- loads, the theatres must not fight over it, and a Nevada bridge sets its own
-- when it starts.

INSERT INTO approaches (name, field, data)
SELECT 'nellis-ils', 'Nellis', '{}'::jsonb
 WHERE NOT EXISTS (SELECT 1 FROM approaches WHERE name = 'nellis-ils');

INSERT INTO flight_plans (name, label, callsign, approach, origin, destination,
                          route, cruise_ft, task, active)
VALUES ('nevada-nellis-nellis', 'Redflag', NULL, 'nellis-ils',
        'Nellis', 'Nellis', 'NELLIS, TONOPAH, NELLIS', 24000,
        'Local transit and instrument recovery', false)
ON CONFLICT (name) DO UPDATE SET
    label       = EXCLUDED.label,
    approach    = EXCLUDED.approach,
    origin      = EXCLUDED.origin,
    destination = EXCLUDED.destination,
    route       = EXCLUDED.route,
    cruise_ft   = EXCLUDED.cruise_ft,
    task        = EXCLUDED.task;
