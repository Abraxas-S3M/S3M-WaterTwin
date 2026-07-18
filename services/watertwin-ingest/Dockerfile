# watertwin-ingest: sandboxed customer-file ingestion service.
#
# Runs as a NON-ROOT user and is intended to run with a READ-ONLY root
# filesystem; the only writable path is the sandbox scratch directory, mounted
# as a tmpfs/volume (see WATERTWIN_INGEST_SCRATCH_DIR). The parse worker further
# hardens itself at runtime (privilege drop, RLIMIT caps, no network egress).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WATERTWIN_INGEST_SCRATCH_DIR=/scratch

WORKDIR /app

COPY services/watertwin-ingest/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Shared canonical packages and the service app.
COPY packages /packages
COPY services/watertwin-ingest/app ./app
ENV PYTHONPATH=/packages

# Non-root runtime user; scratch dir is the only writable location.
RUN useradd --create-home --uid 10001 ingest \
    && mkdir -p /scratch \
    && chown -R ingest:ingest /scratch
USER ingest

EXPOSE 8200
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8200"]
