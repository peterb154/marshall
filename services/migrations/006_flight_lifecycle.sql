-- A flight starts before it flies, and we had only modelled the arrival.
--
-- `cleared` was unknown|enroute|holding|approach|missed|landed, which is the
-- last twenty minutes of a sortie. But a flight plan is filed before there is
-- an aeroplane; a clearance is read back on the ramp; a departure is a
-- controller's problem too, and so is the hour in between. All of it is the
-- SAME aircraft with the same identity, the same stated intent and the same
-- controller ownership -- which is the argument for one row rather than an
-- arrival-shaped one, and it only became obvious once the arrival worked.
--
-- The states, in order, with who owns him:
--
--   filed        a plan exists, no aeroplane yet          -- nobody
--   clearance    IFR clearance delivered and read back    -- delivery/ground
--   taxi                                                  -- ground
--   departure    rolling and climbing out                 -- tower
--   enroute      the long middle                          -- centre
--   arrival      descending, being set up                 -- centre/approach
--   holding      waiting for the approach                 -- approach
--   approach     cleared for it                           -- approach
--   missed       went around                              -- approach
--   landed                                                -- tower/ground
--
-- Only "filed" is genuinely new machinery; the rest are the same row moving
-- through, and every one of them is a thing that was AGREED, which keeps it on
-- the right side of the rule.

-- Postgres has no cheap way to widen a CHECK that was never written, and the
-- column is deliberately un-constrained text: an enum here would need a
-- migration every time a field turns out to work differently, which is exactly
-- the kind of change this project makes weekly. The comment is the contract.
COMMENT ON COLUMN flights.cleared IS
    'What was AGREED, over the whole life of the flight: filed | clearance | '
    'taxi | departure | enroute | arrival | holding | approach | missed | '
    'landed. Never what the scope observes -- that is geometry.';

ALTER TABLE flights
    -- The plan he filed, if he filed one. This is the point of the flight
    -- planning front end: intent known BEFORE first contact, so the first
    -- transmission is "Marshall, Pony one one, ready to taxi" and the
    -- controller already has the strip -- rather than an interrogation.
    ADD COLUMN IF NOT EXISTS flight_plan   text,
    -- Departure as well as destination. Symmetry that costs one column and is
    -- needed the moment we work a departure at all.
    ADD COLUMN IF NOT EXISTS origin        text,
    -- The route as filed or as cleared. Deliberately text: at this stage a
    -- route is "direct Batumi" or a list of fixes, and pretending to a schema
    -- we have not designed would be worse than a string we can read.
    ADD COLUMN IF NOT EXISTS route         text,
    ADD COLUMN IF NOT EXISTS cruise_ft     integer,
    -- Set when the clearance has been read back correctly. "Readback correct"
    -- is a ground phrase and this is the only place it belongs; airborne, a
    -- correct readback is answered with silence.
    ADD COLUMN IF NOT EXISTS clearance_ack timestamptz;

CREATE INDEX IF NOT EXISTS flights_plan ON flights (mission, flight_plan);
