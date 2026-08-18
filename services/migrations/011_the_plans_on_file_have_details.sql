-- The plans on file get the details a pilot would ask for them BY.
--
-- 009 gave `flight_plans` an origin, a destination, a route, a cruise and a
-- task; 010 gave them a spoken name. Neither filled anything in, so what was on
-- file was rows naming an approach and nothing else -- and asking for "the CAS
-- over Tsutsnvati" matched nothing, because nowhere did it say that is what the
-- plan was for. Tonight's rows were filled in by hand while the feature was
-- being built; this is the same content as a migration, so a database built from
-- scratch has it too.
--
-- The routes name the fixes route.py publishes and the sim projects into the
-- `fixes` table, spelled exactly as they are named there. That is not a
-- formatting nicety: a route naming a fix nobody holds is refused at clearance
-- delivery, which is correct behaviour and a nuisance when the only reason is a
-- typo here.
--
-- The hand-filled third plan ferried spares TO Kutaisi, which route.py describes
-- as a red field and "the transit turning point, not a diversion" -- you cannot
-- deliver stores to an aerodrome the other side holds. The route was never the
-- problem: going out and turning at Kutaisi is exactly what it is for. Only the
-- word "ferry" was, so the plan says what it actually does.

UPDATE flight_plans SET
    origin      = 'Batumi',
    destination = 'Batumi',
    route       = 'BATUMI, FEET WET, INGRESS, TSUTSNVATI, EGRESS, BATUMI',
    cruise_ft   = 11000,
    task        = 'CAS over Tsutsnvati'
 WHERE name = '362nd-batumi-asr';

-- Deliberately the SAME task area as the one above, because that is the case
-- this whole feature exists for: two plans a destination cannot separate, where
-- the difference is the approach flown at the end of it and the only correct
-- thing a controller can do is ASK which one he wants.
UPDATE flight_plans SET
    origin      = 'Batumi',
    destination = 'Batumi',
    route       = 'BATUMI, FEET WET, INGRESS, TSUTSNVATI, EGRESS, BATUMI',
    cruise_ft   = 11000,
    task        = 'CAS over Tsutsnvati, beacon letdown on return'
 WHERE name = '362nd-batumi-ndb';

-- The one that is nothing like the others, so a request naming its task is
-- unambiguous on the first transmission -- and the reason the sweep can tell a
-- clean match from a question the controller has to ask.
UPDATE flight_plans SET label = NULL WHERE name = '362nd-kutaisi-ferry';



DELETE FROM flight_plans WHERE name = '362nd-kutaisi-ferry';

-- SEEDED PLANS REMOVED, 12 August 2026.
--
-- A migration creates the SHAPE. It must not create the CONTENTS, and this
-- file used to INSERT a flight plan -- so every deployment of Marshall
-- anywhere was born believing somebody was flying it. #131 was the bridge
-- reading its approach out of exactly such a row, and the pilot's objection
-- was the plainer one:
--
--     "i dont understand this active business. sounds like mis-alignment
--      between you and me"
--
-- A flight plan is something a PILOT files. He files it from his own cartridge
-- (`core/dtc.py`) or from the /file page, and a fresh install should have an
-- empty board rather than somebody else's sortie on it.
--
-- Applied databases are unaffected: migrations are tracked by FILENAME with no
-- checksum, so this file will not run again and the rows it once created stay
-- until somebody deletes them. Only a fresh install sees the difference.
-- See docs/CONFIG.md and #137.
