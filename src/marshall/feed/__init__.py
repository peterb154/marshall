"""The sim, mirrored into Postgres. Nothing reads the world through this.

`feed` subscribes to DCS once -- the unit stream, the event stream -- and keeps
`tracks` current: upsert on a unit update, delete on `gone`, wipe when the world
restarts. Everything else then reads rows, and no part of the system asks the
sim a question that another part has already asked.

WHY IT IS HORIZONTAL. Every domain needs tracks. `atc` separates them,
`traffic` will materialise and cull them, a planner will place things among
them -- so this belongs beside `core` rather than inside any one of them, and
it writes a table rather than serving an API. A domain that had to go through
`feed` to see the world would be a domain coupled to it.

IT ONLY EVER WRITES. There is no `feed.get_contacts()`, deliberately: readers
read the table (`core.scope`), so the mirror can never become a bottleneck, a
cache, or a second opinion about what the sim said.
"""
