-- A flight plan needs a name a pilot can SAY.
--
--     "each one will need an id and name that can be used with atc for
--      clearance delivery"
--
-- `name` is a slug -- `362nd-batumi-asr` -- which is right for a primary key and
-- unsayable on a radio. Asking a pilot to request "three sixty second dash
-- batumi dash a s r" is not clearance delivery, it is a password prompt.
--
-- So `label` is the spoken form, and the rules it has to satisfy are the
-- transcriber's rather than a database's:
--
--   * PHONETICALLY DISTINCT. Two plans called "Alpha One" and "Alpha Two" put
--     the whole feature at the mercy of one syllable, and this project has
--     already watched "Pony one two" arrive as "Pony one too".
--   * ORDINARY WORDS. Whisper is primed with what is in play, and it hears a
--     real word far better than an invented one -- SAMOVAR beats XR7.
--   * SHORT. It is said at the start of a transmission, before the request.
--
-- The pilot then has two ways in, and neither requires him to read a slug:
--
--     "Batumi Approach, Hoover one one, request clearance, Samovar One"
--     "Batumi Approach, Hoover one one, request clearance as filed"
--
-- The second is the normal one and needs no label at all -- the controller
-- offers whatever is filed for his callsign. The label is for the night there
-- is more than one, which is the night this whole feature is for.

ALTER TABLE flight_plans ADD COLUMN IF NOT EXISTS label text;

-- Unique where present: two plans answering to one spoken name is exactly the
-- ambiguity the label exists to remove, and a controller cannot ask "which
-- Samovar One did you mean".
CREATE UNIQUE INDEX IF NOT EXISTS flight_plans_label
    ON flight_plans (lower(label)) WHERE label IS NOT NULL;

-- Give the plans already on file something sayable, derived from what they are
-- rather than invented: the existing rows are the 362nd's Batumi approaches.
UPDATE flight_plans SET label = 'Samovar One'
 WHERE name = '362nd-batumi-asr' AND label IS NULL;
UPDATE flight_plans SET label = 'Samovar Two'
 WHERE name = '362nd-batumi-ndb' AND label IS NULL;

-- And the assigned copy remembers what it was called when it was given out. The
-- template can be relabelled later; what the pilot was cleared on cannot change
-- retrospectively.
ALTER TABLE assigned_plans ADD COLUMN IF NOT EXISTS label text;

DROP VIEW IF EXISTS flight_with_plan;
CREATE VIEW flight_with_plan AS
SELECT f.id,
       f.mission,
       f.callsign,
       f.track_name,
       f.controller,
       f.cleared,
       a.template,
       a.label,
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
