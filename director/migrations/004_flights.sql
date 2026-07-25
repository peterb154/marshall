-- One aircraft, one state, one place to ask.
--
-- Three components used to hold their own idea of what was happening to an
-- aeroplane, and they disagreed on the radio in front of a pilot. The
-- vectoring computes from the scope and sees everything but remembers nothing.
-- The separation engine remembers everything and sees nothing -- it learns only
-- what is said to it -- so a flight established on final at ten miles checked
-- in, was filed as a fresh arrival, and told to climb to five thousand and hold
-- while the other half was talking it down. The agent voiced both, in one
-- transmission.
--
-- ============================================================================
-- THE RULE: this table stores what was AGREED. The scope stores what is TRUE.
-- ============================================================================
--
-- "Cleared to two thousand" is agreed; no radar will ever tell you it.
-- "Descending through sixteen hundred" is true; no database should. Neither is
-- redundant -- and the DISAGREEMENT between them is the most useful thing a
-- controller has. "You are through your assigned altitude." "You are drifting
-- right of course." Today those cannot even be expressed, because the two
-- halves live in different processes and never compare notes.
--
-- The corollary is the discipline: if the scope can compute it, it does not go
-- here. Which leg of the intercept he is flying, how far off course he is,
-- whether he is established -- all geometry, all recomputed every radar sweep,
-- all excluded. Storing them would create a second answer that goes stale,
-- which is the bug this table exists to kill.
--
-- The awkward cases are the ones where a fact looks geometric and is not. An
-- aircraft over the threshold at four hundred feet may be landing or may be
-- going around; the scope cannot tell you which, because the difference is
-- what he SAID. So "missed" is stored -- it is a declaration -- while "past
-- the threshold" is not.

CREATE TABLE IF NOT EXISTS flights (
    -- A surrogate key, because every natural one fails. The callsign collides
    -- (Whisper hears "Pony one one" for two different radios). The SRS GUID is
    -- absent for AI traffic, which has no radio at all and still has to be
    -- controlled. The sim's unit name is absent for a pilot who has called but
    -- not yet been radar-identified, which is where every arrival begins.
    id           bigserial PRIMARY KEY,

    -- The MISSION owns flights, not a chat session. Center, Approach and Tower
    -- are one process today and will not be -- once airspace splits them, a
    -- session-scoped table would partition the aircraft at exactly the moment
    -- it is handed over.
    mission      text NOT NULL DEFAULT 'default',

    -- The same aeroplane has three names and none of them match. Binding them
    -- IS the identity problem; holding the binding is this table's job. All
    -- three are nullable because an aircraft can be known by any one of them
    -- first: a voice with no track, a track with no voice, a plan with neither.
    callsign     text,          -- as spoken: what a controller actually has
    track_name   text,          -- tracks.name: the sim's unit
    srs_guid     text,          -- the radio that keyed the mic. The anchor when
                                -- present: free on every call, and stable even
                                -- when Whisper mangles the callsign itself.
    srs_name     text,

    -- ---- what he TOLD us -------------------------------------------------
    -- Never inferred. A Center has no reason to think anyone is bound for a
    -- particular field, and guessing produced a controller that greeted a pilot
    -- already knowing where he was going.
    intent       text,          -- 'land' | 'transit' | 'depart' | ...
    destination  text,          -- 'Batumi'
    -- What he SAYS he has -- a claim, not a count. Radar shows a formation as
    -- one contact and cannot count it, and the number can change in flight; one
    -- was lost on a go-around tonight and the pilot said four out of habit. The
    -- controller noticed the scope showed three and asked, which is exactly
    -- right and needs no machinery: a lead knows how many he has, and the
    -- question costs one transmission.
    claimed_size integer NOT NULL DEFAULT 1,

    -- ---- who is working him ----------------------------------------------
    -- This is what the whole table buys, and it is worth stating plainly.
    --
    -- Georgia Center asks a pilot where he is going and he says Batumi. That
    -- answer is expensive: it cost a transmission, the pilot's patience, and a
    -- Whisper transcription that might have needed a "say again". Today it
    -- lives in one agent's conversation history, so when he changes frequency
    -- to Approach he is a stranger again and has to say it a second time.
    --
    -- With the intent stored against the aircraft rather than against the
    -- conversation, the handoff carries everything: Approach already knows he
    -- is inbound to Batumi, what he was cleared to, what level he was left at,
    -- and what Center promised him. That is what a handoff IS between real
    -- controllers -- the strip goes across the room -- and it is the difference
    -- between three controllers and one controller with three voices.
    controller   text,          -- stations.role: 'center' | 'approach' | 'tower'
    handed_off_at timestamptz,

    -- ---- what we AGREED --------------------------------------------------
    procedure    text,          -- approaches.name, e.g. 'batumi-asr'
    runway       text,
    -- The cleared state, not the observed one. 'final' here means "we cleared
    -- him for the approach", not "the scope shows him on the centreline" --
    -- that second question is asked of the geometry, and the gap between the
    -- two answers is the interesting part.
    cleared      text NOT NULL DEFAULT 'unknown',
        -- unknown | enroute | holding | approach | missed | landed
    assigned_ft  integer,       -- the level we gave him
    assigned_hdg integer,       -- the heading we gave him
    sequence_no  integer,       -- his place in the queue
    -- Set only when he declares it or we clear it. An aeroplane over the
    -- threshold might be landing; only the declaration tells them apart.
    missed_count integer NOT NULL DEFAULT 0,

    -- ---- what we PROMISED ------------------------------------------------
    -- So a callback can be kept, and an unkept one noticed. The agent has said
    -- "expect clearance in five minutes" and then not called back.
    promised     text,
    promised_at  timestamptz,

    -- ---- formations ------------------------------------------------------
    -- A flight is one aeroplane to a controller until it breaks up, after
    -- which its members are ordinary singles that remember where they came
    -- from. Members exist as rows from the moment of the break-up, with no
    -- track_name until they separate enough for radar to tell them apart --
    -- which is honest: unidentified is a real state and must not be hidden.
    lead_of      text,          -- the flight callsign, on a member's row

    first_seen   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

-- A callsign is unique among ACTIVE flights but recurs across a mission, so it
-- is indexed rather than constrained; two live aircraft answering to one
-- callsign is a real situation the controller has to resolve out loud.
CREATE INDEX IF NOT EXISTS flights_callsign ON flights (mission, callsign);
CREATE INDEX IF NOT EXISTS flights_cleared  ON flights (mission, cleared);
CREATE INDEX IF NOT EXISTS flights_lead     ON flights (mission, lead_of);
CREATE INDEX IF NOT EXISTS flights_ctrl     ON flights (mission, controller);
-- These two ARE unique when present: one radio is one aeroplane, one sim unit
-- is one aeroplane. Partial, so the many rows with neither do not collide.
CREATE UNIQUE INDEX IF NOT EXISTS flights_srs_guid
    ON flights (mission, srs_guid) WHERE srs_guid IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS flights_track
    ON flights (mission, track_name) WHERE track_name IS NOT NULL;

-- Agreed and observed, side by side, which is the whole point. A flight with no
-- radar track still appears: on the radio and unidentified is a real state, and
-- it must not vanish from the picture just because we cannot see him.
-- Dropped and recreated rather than REPLACEd: a later migration adds columns
-- to the underlying table, and `SELECT f.*` then changes this view's column
-- ORDER, which CREATE OR REPLACE refuses. Migrations have to be replayable
-- from nothing in sequence, and this one was not.
DROP VIEW IF EXISTS flight_state;
CREATE VIEW flight_state AS
SELECT f.*,
       t.geog,
       t.alt_ft    AS observed_alt_ft,
       t.heading   AS observed_heading,
       t.last_seen AS observed_at,
       (t.name IS NOT NULL) AS radar_identified,
       -- The disagreement, computed where both numbers are in scope. Null when
       -- we have not assigned an altitude or cannot see him.
       (t.alt_ft - f.assigned_ft) AS alt_error_ft
FROM flights f
LEFT JOIN tracks t ON t.name = f.track_name;
