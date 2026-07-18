# watertwin-ingest: hardened, tenant-isolated advisory file ingestion service.
#
# Container hardening (see docs/deployment/ingest-deployment.md and the k8s
# securityContext in deploy/deployment.yaml):
#   * non-root user (UID 10001), no shell in the final image
#   * read-only root filesystem at runtime (writable tmpfs mounted at /tmp)
#   * all Linux capabilities dropped
#   * seccomp profile (deploy/seccomp.json) applied at the orchestrator
#   * multi-stage build so build tooling never ships in the runtime image
#
# The service is read-only to OT: it never talks to SCADA/PLC/OPC UA/MQTT, and
# its parser workers have deny-all egress (see deploy/networkpolicy.yaml).

# --- Build stage: install deps into a venv (build tools stay here only) -------
FROM python:3.12-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY services/watertwin-ingest/requirements.txt ./requirements.txt
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# --- Runtime stage: distroless-style, no shell, non-root, read-only ----------
# gcr.io/distroless/python3 ships no shell and no package manager, which removes
# the "no shell in the runtime image" attack surface entirely.
FROM gcr.io/distroless/python3-debian12:nonroot

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app:/app/packages"

WORKDIR /app

# Bring the resolved virtualenv and the application code over.
COPY --from=build /opt/venv /opt/venv
COPY packages/ /app/packages/
COPY services/watertwin-ingest/app/ /app/app/

# distroless "nonroot" is UID 65532; be explicit that we never run as root.
USER 65532:65532

# In-process healthcheck (no shell, no socket) — see app/healthcheck.py.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-m", "app.healthcheck"]

EXPOSE 8300

# The distroless image's entrypoint is `python`, so pass module args only.
CMD ["-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8300"]
