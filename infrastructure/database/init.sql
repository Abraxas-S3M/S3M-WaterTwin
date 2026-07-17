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
    facility_id TEXT,
    train_id    TEXT,
    provenance  TEXT             NOT NULL DEFAULT 'synthetic',
    quality     TEXT             NOT NULL DEFAULT 'good'
);

-- Convert to a TimescaleDB hypertable (idempotent).
SELECT create_hypertable('telemetry', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS telemetry_asset_metric_time_idx
    ON telemetry (asset_id, metric, time DESC);

-- 3. Audit trail -----------------------------------------------------------
-- Every advisory action (scenario run, recommendation created/decided, report
-- generated, reset) is appended here. Append-only from the application's view.
CREATE TABLE IF NOT EXISTS audit_event (
    id      UUID        PRIMARY KEY,
    ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind    TEXT        NOT NULL,
    actor   TEXT        NOT NULL DEFAULT 'system',
    subject TEXT,
    payload JSONB       NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS audit_event_ts_idx ON audit_event (ts DESC);
CREATE INDEX IF NOT EXISTS audit_event_kind_idx ON audit_event (kind);

-- 4. Recommendations -------------------------------------------------------
-- Recommendation cards produced by the Simulation Center, with their operator
-- approval status. Approval is an operator action only; it never writes to
-- equipment.
CREATE TABLE IF NOT EXISTS recommendation (
    recommendation_id TEXT        PRIMARY KEY,
    ts                TIMESTAMPTZ NOT NULL DEFAULT now(),
    facility_id       TEXT,
    train_id          TEXT,
    status            TEXT        NOT NULL DEFAULT 'pending',
    card              JSONB       NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS recommendation_status_idx ON recommendation (status);
CREATE INDEX IF NOT EXISTS recommendation_ts_idx ON recommendation (ts DESC);
