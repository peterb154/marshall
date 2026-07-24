# A one-shot headless-chromium screenshotter, so charts can be inspected on a
# Linux box with no browser. tools/render.sh runs this image with `docker run
# --rm`, passing the chromium flags and a --screenshot target; it is NOT a
# long-running service. Keeps the ~250-package chromium dependency in a
# container instead of on the LXC host.
#
#   docker build -t marshall-render -f deploy/render.Dockerfile deploy
#
# Fonts matter: without dejavu/liberation the plate's text renders as boxes.
FROM debian:12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      chromium \
      fonts-dejavu-core \
      fonts-liberation \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# chromium is the entrypoint; render.sh supplies --headless/--screenshot/URL.
ENTRYPOINT ["chromium"]
