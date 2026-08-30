-- Whether he has reported CLEAR OF THE RUNWAY, as a fact of its own.
--
-- The runway check read `sortie_phase`, and that rung moves to `taxi_in` the
-- moment Tower hands a landed aeroplane to Ground -- which is true of who OWNS
-- him (#100) and false of where his aeroplane is. He is still rolling.
--
--     17:03:29  Shooter ... welcome. Exit the runway, contact Ground
--     17:06:24  board: Shooter taxi_in   <- "off the runway, to a stand"
--     17:06:53  Sockeye ... cleared to land runway one three
--     17:07:33  "I see shooter on the runway right now"
--
-- So the occupancy question gets its own column rather than borrowing a rung
-- that answers a different one. It is a latch like `has_been_airborne` and the
-- opposite way round: false until the pilot's own report, because there is no
-- geometry to fall back on -- an aerodrome row carries a position and a landing
-- heading and no thresholds. It fails SAFE: an aeroplane nobody has heard from
-- holds the runway.
--
-- DEFAULT FALSE AND BACKFILLED TRUE for rows already at rest. A flight that is
-- finished when this lands has vacated by any reasonable reading, and leaving
-- it false would have every historic strip holding a runway it left hours ago.
ALTER TABLE flights ADD COLUMN IF NOT EXISTS runway_vacated boolean DEFAULT false;

UPDATE flights
   SET runway_vacated = true
 WHERE runway_vacated IS NOT TRUE
   AND lower(coalesce(sortie_phase, '')) = 'taxi_in';
