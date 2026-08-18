-- An approach key carries the runway it serves.
--
--     "batumi_ils … I don't know what that is. There could be multiple ils
--      approaches into a field"
--
-- Right, and Batumi is 13/31. An ILS to 31 is the same localiser from the other
-- end and an ordinary thing to publish -- and a key of `<field>-<kind>` can NAME
-- only one of them, so the second could not be filed at all. Real procedures are
-- named for the runway they serve: ILS RWY 13, VOR RWY 31.
--
-- The keys became `<field>-<kind>-<runway>` in `config/theatres/*.toml`. Two
-- tables hold them and both are rewritten here:
--
--   approaches.name        the pushed profile, keyed by name. A bridge carrying
--                          the new keys UPSERTS new rows and leaves the old ones
--                          behind -- five orphans that `_approach_named` would
--                          then find as extra candidates and refuse on, which is
--                          the ambiguity refusal firing for a reason that is
--                          entirely our own fault.
--   assigned_plans.approach  which procedure a man was CLEARED for. #142/#2 put
--                          it here rather than on the plan, and it is the value
--                          `Controller.hydrate` restores across a restart. A
--                          stale key here means an aeroplane comes back from a
--                          restart cleared for a procedure nothing publishes.
--
-- UNAMBIGUOUS TODAY, WHICH IS WHY IT IS SAFE. Every field publishes exactly one
-- approach of each kind right now, so old -> new is a function. The day a second
-- ILS exists this rewrite would be a guess, and there would be nothing to guess
-- FROM -- which is the whole argument for putting the runway in the key before
-- that day rather than after it. [#165]
--
-- Re-runnable: each statement matches only the old spelling.

UPDATE approaches SET name = 'batumi-asr-13'   WHERE name = 'batumi-asr';
UPDATE approaches SET name = 'batumi-ils-13'   WHERE name = 'batumi-ils';
UPDATE approaches SET name = 'batumi-ndb-12'   WHERE name = 'batumi-ndb';
UPDATE approaches SET name = 'kobuleti-ils-07' WHERE name = 'kobuleti-ils';
UPDATE approaches SET name = 'nellis-ils-21'   WHERE name = 'nellis-ils';
UPDATE approaches SET name = 'tonopah-ils-15'  WHERE name = 'tonopah-ils';

UPDATE assigned_plans SET approach = 'batumi-asr-13'   WHERE approach = 'batumi-asr';
UPDATE assigned_plans SET approach = 'batumi-ils-13'   WHERE approach = 'batumi-ils';
UPDATE assigned_plans SET approach = 'batumi-ndb-12'   WHERE approach = 'batumi-ndb';
UPDATE assigned_plans SET approach = 'kobuleti-ils-07' WHERE approach = 'kobuleti-ils';
UPDATE assigned_plans SET approach = 'nellis-ils-21'   WHERE approach = 'nellis-ils';
UPDATE assigned_plans SET approach = 'tonopah-ils-15'  WHERE approach = 'tonopah-ils';

-- NO CONSTRAINT ADDED, deliberately. A CHECK that a key matches
-- `<field>-<kind>-<runway>` would refuse every row a future map files before
-- anybody has taught this file about that map's runways, and the resolver
-- already accepts the runway-less form while it is unambiguous -- so the
-- constraint would be stricter than the code that reads it, which is how a
-- database comes to refuse something the system considers legal.
