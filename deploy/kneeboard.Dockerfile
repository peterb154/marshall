# The kneeboard chart server. Pure-Python, no sim dependency -- it generates the
# charts from the route/profile and serves them for OpenKneeboard's Web Dashboard.
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
# [server] pulls FastAPI + uvicorn; the chart generators themselves are stdlib.
RUN pip install --no-cache-dir ".[server]"

ENV MARSHALL_BUILD=/data \
    KNEEBOARD_PORT=8362
EXPOSE 8362

# Generate every chart -- the individual pages and the inlined multi-page tab --
# then serve them. Charts are regenerated on every start, and docker-compose
# mounts src over the copy below, so a restart genuinely picks up a chart
# change. Without that mount this only ever regenerates the baked-in code.
CMD ["sh", "-c", "python -m marshall.kneeboard.navlog && python -m marshall.kneeboard.plate && python -m marshall.kneeboard.e6b && python -m marshall.kneeboard.site && python -m marshall.kneeboard.serve"]
