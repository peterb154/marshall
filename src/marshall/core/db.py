"""One way to reach Postgres, for every part that needs it.

    "If we have ONE SQLAlchemy data model, and EVERYBODY has access to the
     database, we get incredible speed, we have full OO access to objects. It
     should make the code a LOT simpler."

WHY THIS IS IN `core`. The director reached the database through
`strands_pg._pool`, which is an upstream framework's pool and lives inside the
container. The bridge could not reach it AT ALL -- Postgres published no host
port -- so every board read had to be an HTTP call to a handler written by hand,
and twelve CRUD endpoints grew in front of a database everybody could have
queried. Measured on this box:

    direct psycopg, pooled, in process     0.086 ms
    PostgREST over HTTP                    0.85  ms
    our own FastAPI /flights endpoint      1.34  ms
    one Bedrock reply                      6300  ms

The hand-written endpoint is the slowest of the three, and all of them are noise
beside the model call. Speed was never the argument for going direct; sharing
`core.schema` between two deployables was, and this is what makes that possible.

THE SESSION IS A CACHE, and that is the one trap the ORM ships with. A
SQLAlchemy `Session` holds an identity map: objects loaded through it are
remembered, and a second query for the same row returns the object you already
have rather than what the table now says. Held across turns, that is `_FIXES`
again -- a lazily-loaded copy that never invalidates, which cost this project a
night. So: **a session per turn, never a module-level one.** `session()` is a
context manager for exactly that reason, and there is deliberately no
`get_session()` returning a long-lived object.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from functools import lru_cache

# The environment variable the director already sets for `strands_pg`, so one
# DSN serves both and there is no second place to configure the same fact.
DSN_ENV = "STRANDS_PG_DSN"

# What a process OUTSIDE the compose network needs. Inside a container the host
# is `db`; on the LXC it is localhost against the published port. The bridge is
# a host process, so it cannot use the container's DSN and must not be given a
# hand-edited copy of it -- that is two places holding one fact.
HOST_DSN_ENV = "MARSHALL_PG_DSN"


def dsn() -> str:
    """The connection string, from the environment.

    `MARSHALL_PG_DSN` wins when set, so a host process can point at the
    published port while a container keeps using the compose network name. When
    neither is set this raises rather than guessing at localhost: a default that
    silently connects to the wrong database is worse than one that will not
    connect at all.
    """
    got = os.environ.get(HOST_DSN_ENV) or os.environ.get(DSN_ENV)
    if not got:
        raise RuntimeError(
            f"No Postgres DSN. Set {HOST_DSN_ENV} (a host process, against the "
            f"published port) or {DSN_ENV} (inside the compose network).")
    # THE DRIVER, NAMED. SQLAlchemy reads a bare `postgresql://` as psycopg2 and
    # this project runs psycopg 3, so an unqualified DSN fails at import with
    # "No module named 'psycopg2'" -- a confusing error about a package nobody
    # asked for. The same string still works for raw psycopg, which ignores the
    # dialect suffix, so one environment variable serves both.
    if got.startswith("postgresql://"):
        got = "postgresql+psycopg://" + got[len("postgresql://"):]
    elif got.startswith("postgres://"):
        got = "postgresql+psycopg://" + got[len("postgres://"):]
    return got


@lru_cache(maxsize=1)
def engine():
    """The SQLAlchemy engine. One per process, which is what an engine is for.

    `pool_pre_ping` because the sim pauses, the director restarts, and a
    connection that died quietly between sorties should cost one retry rather
    than one exception on the voice path.
    """
    from sqlalchemy import create_engine
    return create_engine(dsn(), pool_pre_ping=True, pool_size=5, max_overflow=5,
                         future=True)


@contextmanager
def session():
    """A session for ONE unit of work. Commits on success, rolls back on error.

    USE IT AND DROP IT. Everything a turn reads should be read inside one
    `with session()`, and nothing should survive the block: an ORM object that
    outlives its session is a stale copy of a row, which is the exact bug class
    this whole refactor exists to remove. If a value is needed after the block,
    take the value, not the object.
    """
    from sqlalchemy.orm import Session
    s = Session(engine(), future=True)
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
