-- The information letter is a fact about a SORTIE, not about a place.
--
--     "But again, I still have never heard anything but information Alpha.. im
--      not sure its rotating today."
--
-- It was not. Both fields read Alpha, and had for three hours and fifty
-- minutes -- while `broadcast.first_letter`, written precisely so a field is
-- "already broadcasting when you tune it", would have given Batumi SIERRA and
-- Kobuleti FOXTROT. So the rows were written by something that predates that
-- function, and no path could ever replace them: `first_letter` runs only when
-- the stored letter is EMPTY, and once a row exists it never is again.
--
-- Three mechanisms then kept it welded:
--
--   * `first_letter` unreachable, per above.
--   * every bridge restart takes the "no frames, re-record the same letter"
--     branch -- correct in itself, since a pilot who copied Alpha two minutes
--     ago has not been overtaken by an hour.
--   * hourly rotation needs a PREVIOUS observation, which is None on the first
--     tick after a restart -- and this bridge restarts far more often than
--     hourly.
--
-- None of those is wrong on its own. Together they are a value written once
-- that outlives the world it described, which is docs/STATE.md's whole
-- subject, one table further along than #119 found it.
--
-- `atis` was keyed on `field` alone, so Batumi's row survives a mission load, a
-- theatre change and a week of sorties. Keyed on the mission INSTANCE as well,
-- a new sortie simply has no row -- and the derivation that was already written
-- takes over, giving each aerodrome its own letter, stable across a restart and
-- advancing through the day on its own.
--
-- The old rows are dropped rather than migrated. They belong to a world that no
-- longer exists, and carrying them forward is the bug.

ALTER TABLE atis ADD COLUMN IF NOT EXISTS mission text NOT NULL DEFAULT 'default';
DELETE FROM atis;
ALTER TABLE atis DROP CONSTRAINT IF EXISTS atis_pkey;
ALTER TABLE atis ADD PRIMARY KEY (mission, field);
