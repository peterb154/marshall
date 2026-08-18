-- Two terminal areas may now overlap, so the tie has to be broken.
--
--     "Real terminal areas overlap, and two fields twenty-two miles apart
--      whose approaches both reach thirty are one radar room with two names."
--
-- #139 removed the midpoint split. It existed so two aerodromes could not
-- claim the same sky, and the arithmetic it produced was absurd: Kobuleti and
-- Batumi are 22.6 nm apart, so both terminal areas were eleven-mile circles --
-- while Batumi's ILS holds at KOBULETI, twenty-two miles out. The procedure
-- began at double the radius of the airspace that owned it, so "he is outside
-- my airspace" fired on a man flying the approach exactly as published.
--
-- Areas are derived from the procedures they serve now, and they overlap:
--
--     Batumi     27.5 nm     Kobuleti   28.8 nm     apart 22.6 nm
--
-- WHICH LEAVES A REAL AMBIGUITY THAT DID NOT EXIST BEFORE. `flight_airspace`
-- picked the containing sector by `ORDER BY s.rank DESC LIMIT 1`, and rank
-- separates a circuit from a terminal area from a Center -- it says nothing
-- between two TERMINAL areas, which are the same rank by construction. With
-- overlap legal, an aeroplane in both got whichever row Postgres happened to
-- return: stable in practice, arbitrary by contract, and the kind of thing
-- that changes under an ANALYZE and looks like a bug in something else.
--
-- THE NEARER FIELD OWNS HIM. It is what a radar room does, it is what a pilot
-- expects, and it needs no new column: the volume is a circle about the field,
-- so its centroid IS the field. Rank still wins first -- inside Batumi's
-- circuit he is Batumi Tower's however close Kobuleti is -- and distance only
-- separates rows rank cannot.
--
-- Re-runnable: the view is dropped and recreated.

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
           -- Rank first, then the nearer centre. `s.name` last so that two
           -- volumes about the SAME point -- which is what a field's own
           -- tower and approach areas are -- still resolve to one answer
           -- rather than to whichever came back first.
           ORDER BY s.rank DESC,
                    ST_Distance(ST_Centroid(s.volume::geometry)::geography,
                                t.geog) ASC,
                    s.name ASC
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
