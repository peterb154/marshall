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

# Just serve. The multi-page documents are built on every request (about five
# milliseconds) and the server reloads a chart module when its file changes, so
# there is nothing to pre-generate and no reason to restart after an edit.
#
# The individual page generators are still runnable by hand
# (`python -m marshall.kneeboard.navlog`) for rendering a single chart to a file.
CMD ["python", "-m", "marshall.kneeboard.serve"]
