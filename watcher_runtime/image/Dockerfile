# Custody watcher base image (ADR-0001): one OpenShell sandbox per watcher is created from this.
# Built by scripts/build-watcher-image.sh; the build context is the repo's watcher_runtime/.
FROM python:3.12-slim-bookworm

# iproute2: OpenShell's supervisor sets up the sandbox network namespace with it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends iproute2 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The OpenShell convention: an unprivileged `sandbox` user (998:998) whose home is /sandbox.
RUN groupadd -r -g 998 sandbox \
    && useradd -r -u 998 -g sandbox -d /sandbox -s /bin/bash sandbox \
    && mkdir -p /sandbox /w \
    && chown sandbox:sandbox /sandbox /w

# Pinned, hash-checked dependencies exported from uv.lock, then the runtime itself (no deps).
COPY image/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt && rm /tmp/requirements.txt
COPY pyproject.toml /opt/watcher_runtime/pyproject.toml
COPY src /opt/watcher_runtime/src
RUN pip install --no-cache-dir --no-deps /opt/watcher_runtime && rm -rf /opt/watcher_runtime

WORKDIR /sandbox
USER sandbox
