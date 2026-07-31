# Your agent's image. Everything here is yours — edit freely.
# BUILT FROM THE REPO ROOT, not from this directory. The shared package lives
# at src/marshall and both deployables import it -- one squash, one bearing, one
# schema -- so a build context that could not see it was the thing forcing every
# copy this project spent a month deleting. See docs/STRUCTURE.md.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/_grpc

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl libpq5 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY director/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Vendored framework code — you own this, edit if you need to.
COPY director/strands_pg/ /app/strands_pg/
COPY director/migrations/ /app/migrations/

# Your agent.
COPY director/app.py      /app/
COPY director/tools/     /app/tools/
# The shared package: core (names, geo, db, schema, scope) and feed (the sim
# mirrored into Postgres). Both deployables import these, which is the whole
# point -- see docs/STRUCTURE.md. Compose mounts them over the top for editing.
COPY src/marshall/       /app/marshall/
COPY director/_grpc/     /app/_grpc/
COPY director/prompts/   /app/prompts/
COPY director/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV STRANDS_PG_MIGRATIONS_DIR=/app/migrations \
    PORT=8000

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
