-- Take the place names back out of Domino's task. They have their own fields.
--
-- Filed two hours ago as "transit from Kobuleti to Batumi, radar recovery",
-- which reads perfectly well and is scored at ten points a word. The route and
-- the destination already carry BATUMI, so that one plan collected credit for
-- the same fact three times -- and "Hoover one one, IFR to Batumi, ready to
-- copy", a request that every plan on the board answers equally and which the
-- sweep exists to keep AMBIGUOUS, resolved confidently onto the Kobuleti
-- departure.
--
-- That is the exact failure migration 012 was written about: not an error, a
-- plausible answer to a question nobody asked. A pilot at Batumi asking for his
-- clearance would have been cleared onto a sortie that starts at another
-- aerodrome, and the first sign of it would be a route that made no sense.
--
-- THE OTHER HALF OF THIS FIX IS IN `tools/plans.py`, and it is the one that
-- actually pays. `origin` was never scored, because until today every plan on
-- the board departed Batumi and scoring it would have added a point to all of
-- them. It is now the most discriminating field there is -- one row, one origin
-- that is not Batumi -- so "clearance for the transit from Kobuleti to Batumi"
-- resolves on the ORIGIN, which is what the pilot actually said, instead of on
-- a task string that was quietly duplicating it.
--
-- The other five tasks were already right and are the model: "Night patrol of
-- the coastline", "Weather reconnaissance out to Ingress". They say what he is
-- DOING. Anvil names Kobuleti because going there IS the job, not because it is
-- the destination -- and its destination is Batumi.

UPDATE flight_plans
   SET task = 'Transit and radar recovery'
 WHERE name = '362nd-kobuleti-batumi';
