-- A flight plan carries a level per leg, not one number for the whole route.
--
--     "A flight plan shouldn't have a cruise altitude. Just waypoints and
--      altitude at each."
--
-- Right, and the cartridge has always said so: DKS writes an elevation on every
-- steerpoint. `flight_plans.cruise_ft` is one integer, so importing a route
-- meant choosing which leg to believe -- and whichever was chosen, the other
-- legs became a fiction the controller then read out.
--
-- Choosing the HIGHEST was the least bad answer and was still wrong on the air:
--
--     "The Clearance delivery gave me a clearance to 1,000, even though my
--      first waypoint is 5,000. We need to look into that"
--
-- He was cleared to maintain ten thousand off the ramp because a later leg
-- wanted it. The real phrase is "maintain five thousand, expect one zero
-- thousand one zero minutes after departure" -- and `plans.clearance` has
-- composed exactly that for weeks, from an `initial_ft` the caller passed as
-- `cruise_ft`, so the "expect" clause could never fire.
--
-- `legs` is the route as the pilot actually flies it: an ordered list of
-- {fix, alt_ft}. `cruise_ft` stays, DERIVED as the highest leg, because it is
-- what a controller means by "cruise" and what `check_live` reads -- but it is
-- no longer the only altitude the plan knows, and the clearance reads the first
-- leg for the level he is to maintain now.
--
-- NULL is legal and means what it always meant: a plan filed before this, or by
-- hand, with one altitude and no profile.

ALTER TABLE flight_plans ADD COLUMN IF NOT EXISTS legs jsonb;

COMMENT ON COLUMN flight_plans.legs IS
  'Ordered [{fix, alt_ft}] as flown. cruise_ft is the highest of these.';
