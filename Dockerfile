# openwrt-jualan — Xiaomi router root-shell exploit toolkit
#
# build: docker build -t openwrt-jualan .
# run:   docker run --network host -it openwrt-jualan
#
# NOTE: run with --network host (or from the host network) — the script must
# reach the router, and the stok must come from a login on the same IP.

FROM python:3.12-slim-bookworm

# Proxy support for proxied build environments.
# Pass at build time: --build-arg HTTP_PROXY=... --build-arg HTTPS_PROXY=...
ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ARG http_proxy=""
ARG https_proxy=""

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN if [ -n "$HTTP_PROXY" ]; then \
      export http_proxy="$HTTP_PROXY" https_proxy="$HTTPS_PROXY" \
             HTTP_PROXY="$HTTP_PROXY" HTTPS_PROXY="$HTTPS_PROXY"; \
    fi && \
    pip install --no-cache-dir -r requirements.txt

COPY . ./

CMD ["python", "remote_command_execution_vulnerability.py"]
