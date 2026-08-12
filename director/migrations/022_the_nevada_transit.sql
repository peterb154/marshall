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
