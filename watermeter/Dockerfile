# Built by Home Assistant itself on the device (BUILD_FROM comes from build.yaml; the default is the same image for a
# plain `docker build`). app/ is the snapshot of the Watermeter files published with this add-on (tools/publish_addon.py).
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-debian:bookworm
FROM $BUILD_FROM

# Debian bookworm has Python 3.11.
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv \
 && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt /app/requirements.txt
RUN python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt

COPY app /app
WORKDIR /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
EXPOSE 8099
# The base image's s6-overlay /init clears the environment before it runs the CMD (SUPERVISOR_TOKEN and the ENV lines
# above included); with-contenv puts it back.
CMD ["/command/with-contenv", "/opt/venv/bin/python", "-m", "watermeter", "/data", "/app/models"]
