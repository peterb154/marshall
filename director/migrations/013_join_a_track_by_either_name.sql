-- The airspace view could not find anybody's aeroplane.
--
-- `tracks` is keyed on the sim's UNIT name ("Testbed 1-1"), but the radar
-- picture prints the LABEL -- player name first, which is what a human is
-- actually called ("362nd_sockeye") -- and the label is therefore what every
-- consumer of that picture knows him by. The join used the unit name alone, so
-- a flight bound from the radar picture matched no row, came back with no
-- geography, and fell through the COALESCE to "Center owns the rest".
--
-- Live effect: a pilot under vectors at eleven miles, comfortably inside
-- Approach's twenty-five mile volume, was told to contact Georgia Center eight
-- times in one approach. Nothing was wrong with the sectors or the radius --
-- he simply had no position, so no polygon could contain him.
--
-- Either identifier now resolves him. They are both the sim's own strings and
-- neither is spoken, so accepting both costs nothing and closes the gap
-- between what the picture says and what the table is keyed on.
DROP VIEW IF EXISTS flight_airspace;
CREATE VIEW flight_airspace AS
SELECT f.id,
       f.mission,
       f.callsign,
       f.controller                       AS working_with,
       COALESCE(
         (SELECT s.name FROM sectors s
           WHERE s.volume IS NOT NULL
             AND ST_Intersects(s.volume, t.geog)
             AND (s.floor_ft   IS NULL OR t.alt_ft >= s.floor_ft)
             AND (s.ceiling_ft IS NULL OR t.alt_ft <= s.ceiling_ft)
           ORDER BY s.rank DESC
           LIMIT 1),
         (SELECT s.name FROM sectors s
           WHERE s.volume IS NULL
           ORDER BY s.rank ASC
           LIMIT 1)
       )                                  AS should_be_with,
       t.geog,
       t.alt_ft
FROM flights f
LEFT JOIN tracks t
       ON t.name = f.track_name
       OR t.label = f.track_name;
