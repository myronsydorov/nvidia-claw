# Custody watcher base image (ADR-0001): one OpenShell sandbox per watcher is created from this.
# Built by scripts/build-watcher-image.sh; the build context is the repo's watcher_runtime/.
# python:3.12-slim-bookworm, pinned by digest.
FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e

# iproute2: OpenShell's supervisor sets up the sandbox network namespace with it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends iproute2 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The OpenShell convention: an unprivileged `sandbox` user (998:998) whose home is /sandbox.
RUN groupadd -r -g 998 sandbox \
    && useradd -r -u 998 -g sandbox -d /sandbox -s /bin/bash sandbox \
    && mkdir -p /sandbox /w \
    && chown sandbox:sandbox /sandbox /w

# Pinned, hash-checked dependencies exported from uv.lock, then the runtime itself as a wheel
# built on the host (no build backend is fetched or run inside the image build).
COPY image/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt && rm /tmp/requirements.txt
COPY image/dist/*.whl /tmp/
RUN pip install --no-cache-dir --no-deps --no-index /tmp/*.whl && rm /tmp/*.whl

WORKDIR /sandbox
USER sandbox
