-- Give Center back the airspace nobody else claimed.
--
-- 005 says it plainly, and means it:
--
--     NULL means "everywhere not claimed by anyone else", which is what a
--     Center actually is -- drawing a polygon round the whole Caucasus to say
--     so would be a lie in the shape of precision.
--
-- The view then filtered those sectors out (`WHERE s.volume IS NOT NULL`), so
-- the fallback existed in the comment and nowhere else. An aircraft outside
-- Approach's and Tower's volumes resolved to `should_be_with = NULL`, and since
-- `due_handoff` skips NULLs, the disagreement that IS the handoff trigger could
-- never fire in that direction.
--
-- What that cost, live: a flight departing Batumi on a CAS sortie was handed
-- from Center to Approach on range alone -- inside 25 nm of the field, so
-- Approach's problem -- and then never handed back as it left, because leaving
-- resolved to nobody. The pilot's version was exactly right:
--
--     "georgia center handed us off the approach oftly early... should have
--      given us vectors and kept us with him until we left his airspace"
--
-- Handing off on range alone cannot express "until he leaves", because range
-- does not know whether he is arriving or departing. Airspace does.
--
-- So: bounded sectors win where they contain him, highest rank first (descending
-- and closing, he ends with Tower); otherwise the unbounded sector of lowest
-- rank has him, which is the Center. No polygon, no lie.

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
         -- Nobody's polygon holds him, so he is the Center's. Lowest rank,
         -- because a Center is the outermost seat and the one you fall back to.
         (SELECT s.name FROM sectors s
           WHERE s.volume IS NULL
           ORDER BY s.rank ASC
           LIMIT 1)
       )                                  AS should_be_with,
       t.geog,
       t.alt_ft
FROM flights f
LEFT JOIN tracks t ON t.name = f.track_name;
