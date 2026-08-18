-- Every controller on the loaded map, in a table the bridge writes.
--
-- `look_up_frequency` exists so a controller asked for somebody else's
-- frequency reads one instead of INVENTING one -- confidently, in correct
-- phraseology, with a plausible number. A pilot sent to an invented frequency
-- calls into silence and cannot tell that from a controller who has stopped
-- answering.
--
-- IT HAS BEEN READING A FOSSIL. The tool was built over
-- `approaches.data->'stations'`, on the argument that "the profile carries the
-- whole station list" -- true when `ApproachProfile` had a `stations` field and
-- `profile_to_dict` (which is `asdict`) pushed the lot. #162 moved the station
-- table off the procedure and onto the THEATRE, correctly: a station is a
-- property of the map, not of an arrival. Nothing replaced the writer, so the
-- live rows read:
--
--     batumi-asr  | 9 stations   <- written 25 July, before the move
--     batumi-ils  | 9            <- likewise
--     batumi-ndb  | 0            <- written AFTER it
--     nellis-ils  | 9            <- likewise a fossil
--     tonopah-ils | 8
--
-- `batumi-ndb` is what every row looks like from now on. On a database that has
-- been reset the tool answers "no station list is published" to every question
-- about every field on both maps, for ever, and the controller falls back to
-- the exact behaviour it was built to stop. Four rows that predate the change
-- are the only reason it works today.
--
-- WHY A TABLE HERE AND NOT A QUERY THERE. This container has no `config/`:
-- `catalogue.maps()` returns `[]` and `route.STATIONS` raises FileNotFoundError
-- for `/config/theatres/caucasus.toml`. THE BRIDGE KNOWS WHICH MAP IS LOADED
-- AND THIS CONTAINER DOES NOT -- the same sentence `push_sectors` is written
-- under, and the same one a first version of `/atis` ignored before it walked
-- `theatre.current().fields` in here and confidently reported Batumi on a
-- Nevada sortie. So the seats arrive the way the fixes, the volumes and the
-- plate arrive: pushed at bridge start.
--
-- `sectors` IS NOT THIS TABLE and cannot be made into it. A sector is a VOLUME,
-- so it exists only for a seat that owns airspace: five rows on the Caucasus,
-- with no Ground, no Clearance and no Sentry. Half the ladder is missing from
-- it, and the half a pilot most often asks for -- "say again Kobuleti ground"
-- -- is the missing half.
--
-- NO ROWS ARE SEEDED HERE, for 027's reason: a migration that also wrote them
-- would be the second writer of a fact the theatre already holds, which is the
-- shape docs/STATE.md is about. A fresh database has no stations until a bridge
-- starts, and that is correct -- with no bridge there is no controller.
CREATE TABLE IF NOT EXISTS stations (
    -- As spoken, and it is the KEY. "Batumi Approach" -- because a role is
    -- unique only within an aerodrome, so `role` cannot identify anybody once
    -- there are two fields, and every seam this month has been that fault.
    name       text PRIMARY KEY,
    -- The aerodrome he works. EMPTY IS A REAL ANSWER, not a missing one: a
    -- Center and a Sentry own a region, and asking which airport they belong to
    -- is a category error.
    field      text NOT NULL DEFAULT '',
    role       text NOT NULL DEFAULT '',
    freq_mhz   double precision,
    -- Everything else he works. One man has ground and tower, another has
    -- departure and approach, which is how a field this size is really staffed
    -- -- so a pilot asking for "approach" at a field with no approach position
    -- must still be given the man who answers to it.
    also       jsonb NOT NULL DEFAULT '[]'::jsonb
);

-- THE FOSSILS STAY. `approaches.data->'stations'` is what makes the tool work
-- on the live database TODAY, and this table is empty until a bridge that
-- knows how to fill it has been deployed and started. Dropping the old key in
-- the same migration would take a working lookup away and give nothing back
-- until the next bridge start, which is a regression fixed into an outage.
--
-- They can be cleaned when a bridge carrying `push_stations` has started
-- against this database and `SELECT count(*) FROM stations` is non-zero -- at
-- which point nothing reads the old key and this is the statement:
--
--     UPDATE approaches SET data = data - 'stations' WHERE data ? 'stations';
--
-- Left un-run on purpose. It is one line and it wants a human who has seen the
-- new table filled, not a migration that runs before the writer exists.

SELECT 1;
