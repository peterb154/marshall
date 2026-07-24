# The kneeboard chart server. Pure-Python, no sim dependency -- it generates the
# charts from the route/profile and serves them for OpenKneeboard's Web Dashboard.
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

ENV MARSHALL_BUILD=/data \
    KNEEBOARD_PORT=8362
EXPOSE 8362

# Generate every chart -- the individual pages and the inlined multi-page tab --
# then serve them. A container restart rebuilds them, so a code change is picked
# up by a restart rather than needing a manual step.
CMD ["sh", "-c", "python -m marshall.kneeboard.navlog && python -m marshall.kneeboard.plate && python -m marshall.kneeboard.e6b && python -m marshall.kneeboard.site && python -m marshall.kneeboard.serve"]
