-- S3M-WaterTwin persistent store bootstrap (idempotent).
--
-- Executed once by the TimescaleDB container on first start
-- (/docker-entrypoint-initdb.d/init.sql). Safe to re-run: every statement is
-- guarded with IF NOT EXISTS / idempotent TimescaleDB helpers.
--
-- Scope: advisory artifacts only. This schema stores synthetic/simulated
-- telemetry, the audit trail, and recommendation cards. There is no control
-- state and no control-write path anywhere in the platform.

-- 1. TimescaleDB extension -------------------------------------------------
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- 2. Telemetry hypertable --------------------------------------------------
-- Long, narrow time-series of synthetic/simulated readings. One row per
-- (asset, metric, time). Provenance is always recorded so a reading can never
-- be mistaken for validated, measured plant data.
CREATE TABLE IF NOT EXISTS telemetry (
    time        TIMESTAMPTZ      NOT NULL DEFAULT now(),
    asset_id    TEXT             NOT NULL,
    metric      TEXT             NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    unit        TEXT,
    tenant_id   TEXT,
    facility_id TEXT,
    train_id    TEXT,
    provenance  TEXT             NOT NULL DEFAULT 'synthetic',
    quality     TEXT             NOT NULL DEFAULT 'good'
);

-- Multi-tenant scoping: add tenant_id to databases created before it existed and
-- migrate the pre-existing single-facility data into the default tenant.
ALTER TABLE telemetry ADD COLUMN IF NOT EXISTS tenant_id TEXT;
UPDATE telemetry SET tenant_id = 's3m-default' WHERE tenant_id IS NULL;

-- Convert to a TimescaleDB hypertable (idempotent).
SELECT create_hypertable('telemetry', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS telemetry_asset_metric_time_idx
    ON telemetry (asset_id, metric, time DESC);
CREATE INDEX IF NOT EXISTS telemetry_tenant_facility_time_idx
    ON telemetry (tenant_id, facility_id, time DESC);

-- Idempotency ledger for telemetry ingest. Each forwarded batch is recorded by
-- its stable ``batch_id`` (an edge gateway's store-and-forward key). A repeat
-- delivery of the same batch_id is a no-op, so a gateway that replays its
-- on-disk spool after a crash/restart never double-writes telemetry or the
-- audit trail -- making store-and-forward recovery both lossless and
-- duplicate-free. ``digest`` binds the recorded batch to its content.
CREATE TABLE IF NOT EXISTS telemetry_batch (
    batch_id      TEXT        PRIMARY KEY,
    ts            TIMESTAMPTZ NOT NULL DEFAULT now(),
    reading_count INTEGER     NOT NULL DEFAULT 0,
    digest        TEXT        NOT NULL DEFAULT '',
    source        TEXT
);

CREATE INDEX IF NOT EXISTS telemetry_batch_ts_idx ON telemetry_batch (ts DESC);

-- 3. Audit trail (tamper-evident, append-only) ----------------------------
-- Every advisory action (scenario run, recommendation created/decided, report
-- generated, reset) is appended here. The trail is a hash chain: each row
-- records the hash of the previous row (prev_hash) and its own hash, computed
-- as sha256(prev_hash + canonical(event)). Altering any stored event breaks
-- its hash and every hash after it, so tampering is detectable by re-walking
-- the chain (GET /api/v1/audit/verify). ``seq`` gives the deterministic append
-- order used for verification.
CREATE TABLE IF NOT EXISTS audit_event (
    seq         BIGSERIAL,
    id          UUID        PRIMARY KEY,
    ts          TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind        TEXT        NOT NULL,
    actor       TEXT        NOT NULL DEFAULT 'system',
    subject     TEXT,
    tenant_id   TEXT,
    facility_id TEXT,
    payload     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    prev_hash   TEXT        NOT NULL DEFAULT '',
    hash        TEXT        NOT NULL DEFAULT ''
);

-- Backfill columns for databases created before the hash chain existed.
ALTER TABLE audit_event ADD COLUMN IF NOT EXISTS seq BIGSERIAL;
ALTER TABLE audit_event ADD COLUMN IF NOT EXISTS prev_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE audit_event ADD COLUMN IF NOT EXISTS hash TEXT NOT NULL DEFAULT '';

-- Add tenant/facility scoping and migrate pre-existing events into the default
-- tenant. tenant_id/facility_id are NOT part of the hashed event core, so this
-- backfill leaves every existing hash — and the append-only chain — unchanged.
-- It runs before the append-only trigger is (re)installed below.
ALTER TABLE audit_event ADD COLUMN IF NOT EXISTS tenant_id TEXT;
ALTER TABLE audit_event ADD COLUMN IF NOT EXISTS facility_id TEXT;
UPDATE audit_event SET tenant_id = 's3m-default' WHERE tenant_id IS NULL;

CREATE INDEX IF NOT EXISTS audit_event_seq_idx ON audit_event (seq);
CREATE INDEX IF NOT EXISTS audit_event_ts_idx ON audit_event (ts DESC);
CREATE INDEX IF NOT EXISTS audit_event_kind_idx ON audit_event (kind);
CREATE INDEX IF NOT EXISTS audit_event_tenant_facility_idx
    ON audit_event (tenant_id, facility_id, seq DESC);

-- Append-only enforcement at the storage layer: reject any UPDATE or DELETE of
-- an audit row. Inserts (appends) are always allowed; TRUNCATE (used only by
-- the demo reset convenience) is intentionally not blocked by a row trigger.
CREATE OR REPLACE FUNCTION audit_event_reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_event is append-only: % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_event_no_mutation ON audit_event;
CREATE TRIGGER audit_event_no_mutation
    BEFORE UPDATE OR DELETE ON audit_event
    FOR EACH ROW EXECUTE FUNCTION audit_event_reject_mutation();

-- 4. Recommendations -------------------------------------------------------
-- Recommendation cards produced by the Simulation Center, with their operator
-- approval status. Approval is an operator action only; it never writes to
-- equipment.
CREATE TABLE IF NOT EXISTS recommendation (
    recommendation_id TEXT        PRIMARY KEY,
    ts                TIMESTAMPTZ NOT NULL DEFAULT now(),
    tenant_id         TEXT,
    facility_id       TEXT,
    train_id          TEXT,
    status            TEXT        NOT NULL DEFAULT 'pending',
    card              JSONB       NOT NULL DEFAULT '{}'::jsonb
);

-- Add tenant scoping and migrate pre-existing recommendations into the default
-- tenant/facility.
ALTER TABLE recommendation ADD COLUMN IF NOT EXISTS tenant_id TEXT;
UPDATE recommendation SET tenant_id = 's3m-default' WHERE tenant_id IS NULL;
UPDATE recommendation SET facility_id = 'S3M-DESAL-01' WHERE facility_id IS NULL;

CREATE INDEX IF NOT EXISTS recommendation_status_idx ON recommendation (status);
CREATE INDEX IF NOT EXISTS recommendation_ts_idx ON recommendation (ts DESC);
CREATE INDEX IF NOT EXISTS recommendation_tenant_facility_idx
    ON recommendation (tenant_id, facility_id);
