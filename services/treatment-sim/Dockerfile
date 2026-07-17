# treatment-sim: read-only RO process-simulation service (WaterTAP/IDAES).
#
# The NLP solver (ipopt) is installed HERE ONLY, via the IDAES solver
# extensions. It must never be added to the shared API image.
#
# Build context is the repository root so the shared `packages/` and
# `watertwin/` sources can be copied in:
#   docker build -f services/treatment-sim/Dockerfile -t treatment-sim .
FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app:/app/packages

# System libraries required by the IDAES/WaterTAP compiled solver binaries
# (BLAS/LAPACK, gfortran runtime) plus curl for the healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
        libgfortran5 \
        liblapack3 \
        libblas3 \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/treatment-sim/requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# Fetch the ipopt NLP solver binaries into the image (solver lives ONLY here).
# Non-fatal at build time: if the download is unavailable the service still
# starts and transparently uses the analytical engine.
RUN idaes get-extensions --verbose || echo "WARN: idaes get-extensions failed; analytical engine will be used"
ENV PATH="/root/.idaes/bin:${PATH}"

COPY packages ./packages
COPY watertwin ./watertwin
COPY services/treatment-sim/app ./app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8080/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
