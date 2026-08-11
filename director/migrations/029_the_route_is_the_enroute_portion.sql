-- Take the aerodromes back out of the route.
--
--     "So ORIGIN and DESTINATION - should these be on the flightplan as fixes?"
--
-- No. ICAO keeps them apart on purpose -- field 13 departure, field 15 the
-- ENROUTE portion, field 16 destination -- and `flight_plans` has all three
-- columns. Writing the aerodromes into `route` as well was duplication, and the
-- validator quietly came to depend on it: `check_live` refused anything with
-- "fewer than two fixes", and that rule only ever passed BECAUSE the endpoints
-- were padding the list.
--
-- So a genuine direct flight -- Kobuleti to Batumi with nothing published in
-- between, which is most of what is actually flown here -- had zero enroute
-- fixes and could not be filed at all without writing its endpoints in twice.
--
-- The rule is now the one `filing.py`'s own docstring says it is for: every fix
-- NAMED is one the sim holds. Empty is legal, which is what "direct" means. A
-- route that still repeats an aerodrome is warned about rather than refused,
-- because every row filed before today does it.
--
-- THIS FILE IS THE ROWS. The code change alone would leave the board carrying
-- "KOBULETI, FOO, BAR, SPAM, BATUMI" for ever -- true, harmless, and quietly
-- teaching the next reader that the endpoints belong there.
--
-- Only the ENDS are stripped. An aerodrome genuinely in the middle of a route
-- is an overflight and is a real thing to file; trimming those would be
-- deleting a fact rather than a duplicate. See #127.

-- TWO PASSES, NOT ONE EXPRESSION. Stripping the leading origin first leaves the
-- destination with no comma in front of it, so a single nested replace missed
-- "NELLIS, TONOPAH" on a Nellis-to-Tonopah plan -- it took the origin off and
-- left the destination standing as the whole route. A direct flight has an
-- EMPTY enroute portion, which is the case this whole change exists for.
UPDATE flight_plans SET route =
    trim(both ', ' from regexp_replace(
        route, '^\s*' || upper(origin) || '\s*(,|$)', '', 'i'))
WHERE route IS NOT NULL AND origin IS NOT NULL;

UPDATE flight_plans SET route =
    trim(both ', ' from regexp_replace(
        route, '(^|,)\s*' || upper(destination) || '\s*$', '', 'i'))
WHERE route IS NOT NULL AND destination IS NOT NULL;
