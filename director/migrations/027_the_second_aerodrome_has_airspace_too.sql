-- Kobuleti has controllers and no sky.
--
-- `sectors` held three rows -- batumi-approach, batumi-tower, georgia-center --
-- and 005's own comment predicted this file:
--
--     "...the moment a second aerodrome exists, and a second aerodrome is the
--      next test."
--
-- It exists. So a jet three miles off Kobuleti's runway at two thousand feet is
-- inside nobody's volume, and 008's COALESCE then makes him GEORGIA CENTER'S --
-- because the fallback sector is "everywhere not claimed by anyone else", and
-- nobody had claimed Kobuleti. Found by `tools/ghost_flight.py` on its first
-- run: departure handed to Center at 3 nm, still in the circuit.
--
--     ATC[handoff] Bishop six eight, contact Georgia Center one three nine
--                  decimal zero.
--
-- THE FALLBACK IS NOT WRONG; THE MAP WAS INCOMPLETE. "He is in no terminal
-- area" and "no terminal area has been described where he is" are different
-- facts and the view could not tell them apart, so absence read as an answer.
-- That is the same fault as `field_origin` defaulting to Batumi's beacon, as
-- `station_for` returning the first Tower, as `channels_for` taking the first
-- four stations -- every one of them correct while there was ONE of a thing.
-- This is the last place it was hiding.
--
-- The consumer is guarded too, in `leaving_my_airspace`: inside the ladder's
-- own terminal distance the RULE TABLE owns him and the volumes do not get a
-- vote. Data and policy, because either alone leaves the next theatre exposed
-- -- Nevada has the identical hole today.
--
-- WHY BATUMI'S VOLUMES ARE REDRAWN AND NOT JUST COPIED. Its approach volume was
-- a box roughly twenty-five miles on the half-side, and the two aerodromes are
-- twenty-two miles apart -- so any honest Kobuleti volume of the same size sits
-- almost entirely inside Batumi's, and an aeroplane on Kobuleti's ramp resolves
-- to Batumi Approach. Equal ranks cannot break that tie and should not have to.
-- Twelve miles each meets near the midpoint, which is where a boundary between
-- two terminal areas twenty-two miles apart actually goes.
--
-- Circles rather than boxes because a terminal area IS a radius from the field
-- -- see `handoff.py`, whose rules are all distances -- and a box was only ever
-- easier to type.

-- 12 nm = 22224 m. Ceilings unchanged: 15,000 for approach, 4,000 for tower,
-- which is what 005 chose and what the talkdown guard in `leaving_my_airspace`
-- already reasons about out loud.
UPDATE sectors SET volume = ST_Buffer(
    ST_SetSRID(ST_MakePoint(41.5997, 41.6103), 4326)::geography,
    22224)::geography(Polygon,4326)
  WHERE name = 'batumi-approach';
UPDATE sectors SET volume = ST_Buffer(
    ST_SetSRID(ST_MakePoint(41.5997, 41.6103), 4326)::geography,
    9260)::geography(Polygon,4326)
  WHERE name = 'batumi-tower';

INSERT INTO sectors (name, label, role, field, freq_mhz, rank,
                     floor_ft, ceiling_ft, volume)
VALUES
  ('kobuleti-approach', 'Kobuleti Approach', 'approach', 'Kobuleti', 123.3,
   20, NULL, 15000,
   ST_Buffer(ST_SetSRID(ST_MakePoint(41.8656, 41.9297), 4326)::geography,
             22224)::geography(Polygon,4326)),
  ('kobuleti-tower', 'Kobuleti Tower', 'tower', 'Kobuleti', 133.0,
   30, NULL, 4000,
   ST_Buffer(ST_SetSRID(ST_MakePoint(41.8656, 41.9297), 4326)::geography,
             9260)::geography(Polygon,4326))
ON CONFLICT (name) DO UPDATE
  SET label = EXCLUDED.label, role = EXCLUDED.role, field = EXCLUDED.field,
      freq_mhz = EXCLUDED.freq_mhz, rank = EXCLUDED.rank,
      floor_ft = EXCLUDED.floor_ft, ceiling_ft = EXCLUDED.ceiling_ft,
      volume = EXCLUDED.volume;
