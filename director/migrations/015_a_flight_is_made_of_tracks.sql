-- Which aeroplanes make up a flight, as a join rather than a string.
--
-- A formation is ONE entity to the separation engine -- one level, one
-- clearance, one place in the letdown -- and `flights.lead_of` named the flight
-- in a TEXT column. That cannot be joined on, cannot be constrained, and cannot
-- answer "which tracks is this flight made of" without matching names, which is
-- the operation this project has got wrong more than any other.
--
-- WHY THE ASSOCIATION LIVES WITH ATC. The first draft put `flight_id` on
-- `tracks` as a nullable foreign key, which was elegant: `IS NULL` would have
-- meant "untracked", and the invariant -- every contact is on the board or in
-- the untracked list, never both -- would have been structural instead of
-- something `publish_state` recomputes. It recomputed it wrongly on 31 July and
-- put one Mustang in both.
--
-- But `tracks` is shared and `flights` belongs to ATC, so that key points a
-- shared table at a domain: the layering upside down. And it must sit on
-- `tracks` because that is the many side, so it cannot be turned round. A join
-- table owned by the asserting domain is the version that keeps the arrow
-- pointing downward. Untracked becomes a LEFT JOIN, which is the price.
--
-- NOT A FOREIGN KEY TO `tracks`, deliberately. A member can be named before
-- radar has the contact -- a wingman who has checked in but is not yet painted
-- -- and a flight that loses radar must not lose its membership. The join is by
-- name and is allowed to find nothing; that is a real state, not an error.
--
-- ON DELETE CASCADE to `flights` because membership has no meaning without the
-- flight, and a released board entry that left its members behind would be a
-- new way to grow ghosts.

CREATE TABLE IF NOT EXISTS flight_member (
    flight_id   BIGINT      NOT NULL REFERENCES flights(id) ON DELETE CASCADE,
    track_name  TEXT        NOT NULL,
    joined_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (flight_id, track_name)
);

-- "Which flight is this track in?" is asked once per contact per radar poll,
-- which is the hot direction.
CREATE INDEX IF NOT EXISTS flight_member_track ON flight_member (track_name);
