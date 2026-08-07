-- The Kobuleti departure, on file, because tonight it is what is being flown.
--
-- Every plan on the board departs Batumi. That was correct while Batumi was the
-- only aerodrome with controllers on it, and it quietly stopped being correct
-- the day Kobuleti got a full station set and the F-16s were moved onto its
-- ramp. Nobody noticed, because nothing FAILS: a pilot calls Kobuleti Clearance,
-- asks for his clearance to Batumi, and the delivery tool searches a board on
-- which no such sortie exists.
--
-- WHAT THAT SOUNDS LIKE IN THE COCKPIT is the thing worth writing down. It is
-- not an error message. It is a controller saying he has nothing on file for
-- you, in perfect phraseology, on the first transmission of the night -- and
-- from the seat that is indistinguishable from having mistyped your own
-- callsign. The pilot spends the next three calls proving who he is.
--
-- ORIGIN IS NOT BATUMI, and this is the first row on the board for which that
-- is true. Migration 012 wrote "everything comes home to Batumi, because it is
-- the only blue aerodrome on the map" -- which is still true of the DESTINATION
-- and was never true of the departure end. It only looked true because there
-- was one field.
--
-- **Label** is one word and far from the others in the mouth: the board already
-- holds Samovar, Kettle, Marlin, Lantern and Anvil, and "Domino" shares an
-- opening consonant with none of them. Migration 012's warning applies -- a
-- label that is a near-miss for another label is a transcriber picking the
-- wrong sortie, silently, and clearing a man onto somebody else's route.
--
-- **Route** names the fixes as `core/fixes.py` publishes them, spelled exactly:
-- KOBULETI, INITIAL, BATUMI. That is the transit `FIXES` and `solve_route`
-- already compute -- 23.9 nm out to INITIAL on 243 magnetic, then the turn
-- inbound, which is deliberately runway heading so rolling out puts him on the
-- approach course already. The nav log kneeboard times these same legs, so the
-- card and the clearance come from one place.
--
-- **Cruise five thousand.** Migration 012 takes levels from the ground under the
-- leg; here the leg runs out over open water to an offshore fix with no terrain
-- in any quadrant, so nothing pushes it up. Five is `CRUISE_ALT_FT`, which is
-- what the nav log prints and the DTC waypoints carry -- three things that must
-- not disagree about how high he is.
--
-- **Recovery is the Batumi radar approach**, because Batumi has no ILS profile
-- in `core/approach.py`. Kobuleti has the ILS and he is leaving it behind. This
-- is worth stating plainly: an F-16 pilot may reasonably expect to shoot an ILS
-- at his destination, and the answer tonight is that the destination does not
-- publish one -- so he gets vectors and a surveillance approach, or he calls the
-- field in sight and takes the visual, which he may always do.
--
-- NOT ACTIVE. `active` picks the approach the bridge loads at start-up, and that
-- is already `362nd-batumi-asr` pointing at the same `batumi-asr` procedure.
-- Flipping it would change nothing about the approach and everything about which
-- row is "the" plan; a filed plan does not need to be active to be assignable,
-- which is exactly how Marlin and Anvil are asked for today.

INSERT INTO flight_plans (name, label, callsign, approach, origin, destination,
                          route, cruise_ft, task, active)
VALUES ('362nd-kobuleti-batumi', 'Domino', NULL, 'batumi-asr',
        'Kobuleti', 'Batumi', 'KOBULETI, INITIAL, BATUMI', 5000,
        'transit from Kobuleti to Batumi, radar recovery', false)
ON CONFLICT (name) DO UPDATE SET
    label       = EXCLUDED.label,
    approach    = EXCLUDED.approach,
    origin      = EXCLUDED.origin,
    destination = EXCLUDED.destination,
    route       = EXCLUDED.route,
    cruise_ft   = EXCLUDED.cruise_ft,
    task        = EXCLUDED.task;
