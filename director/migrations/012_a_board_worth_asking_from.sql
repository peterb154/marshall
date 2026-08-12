-- Five plans on file, named so a pilot can say them, and nothing else.
--
-- Three was enough to prove the mechanism and not enough to test it. A pilot
-- validating clearance delivery needs a board where the WRONG answer is
-- available: several plans that could plausibly be what he meant, one pair that
-- genuinely cannot be told apart, and enough distinct tasks that most requests
-- resolve on the first transmission the way they should.
--
-- Five is the whole board. Last night's rows are not preserved -- they were a
-- record of one sortie, not a filing cabinet, and carrying them forward would
-- mean a test board that is half real history and half fixture, where a
-- surprising answer sends you looking through both.
--
-- **Labels are one word each, and all five are far apart in the mouth.**
-- Migration 010 says exactly this and then named the first two Samovar One and
-- Samovar Two, which is the "Alpha One / Alpha Two" it warns against; a
-- transcriber that turns "one" into "won" picks the wrong sortie. The two plans
-- that ARE nearly the same sortie are told apart by their TASK instead, which is
-- also how a pilot would ask for them.
--
-- **Routes** name the fixes route.py publishes and the sim projects, spelled as
-- they are named there -- BATUMI, FEET WET, INITIAL, INGRESS, TSUTSNVATI,
-- EGRESS, KOBULETI, KUTAISI. A route naming a fix nobody holds is refused at
-- clearance delivery, which is correct behaviour and a nuisance when the cause
-- is a typo here.
--
-- **Everything comes home to Batumi**, because it is the only blue aerodrome on
-- the map. Kobuleti and Kutaisi are turning points, never somewhere to land --
-- which is the whole reason a destination cannot pick a plan here and the match
-- has to run on what he is DOING.
--
-- **Cruise levels** come from the ground under the leg rather than from a round
-- number: low over the water because there is nothing to hit and nobody
-- watching, eleven thousand coming home over the ridge because that clears the
-- highest thing on the line by two.

-- The working rows from building this, which were never a filed plan anybody
-- meant to keep. A stale plan on a test board is worse than a missing one: it
-- answers a request, plausibly, with something nobody wrote.
--
-- FIRST, before anything is renamed. A spoken label is unique on lower(label),
-- so a row still holding "Kettle" makes assigning that name below fail on the
-- index rather than doing what it says.
DELETE FROM flight_plans
 WHERE name IN ('362nd-kutaisi-ferry', '362nd-kobuleti-ferry',
                '362nd-kutaisi-transit', '362nd-initial-workup');

-- `362nd-batumi-asr` stays, under a new name. Not sentiment: it is the row the
-- bridge upserts at startup to build the plate, so deleting it means it comes
-- back on the next boot with no route, no task and no label -- a plan on the
-- board with nothing filed on it.
UPDATE flight_plans SET
    label       = 'Samovar',
    callsign    = NULL,          -- filed against nobody; any pilot may take it
    origin      = 'Batumi',
    destination = 'Batumi',
    route       = 'BATUMI, FEET WET, INGRESS, TSUTSNVATI, EGRESS, BATUMI',
    cruise_ft   = 11000,
    task        = 'CAS over Tsutsnvati'
 WHERE name = '362nd-batumi-asr';

-- Its twin, and the reason there is a twin: the SAME sortie flown two ways,
-- differing only in the recovery at the end. "The CAS over Tsutsnvati" names
-- both of these and nothing else, so the only correct answer is to ask which --
-- and a resolver that quietly picks the better-scoring one looks perfect right
-- up until it clears somebody on the wrong approach.
UPDATE flight_plans SET
    label       = 'Kettle',
    callsign    = NULL,
    origin      = 'Batumi',
    destination = 'Batumi',
    route       = 'BATUMI, FEET WET, INGRESS, TSUTSNVATI, EGRESS, BATUMI',
    cruise_ft   = 11000,
    task        = 'CAS over Tsutsnvati, beacon letdown on return'
 WHERE name = '362nd-batumi-ndb';

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
