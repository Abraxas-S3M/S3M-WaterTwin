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

-- 3. Audit trail (tamper-evident, append-only) ----------------------------
-- Every advisory action (scenario run, recommendation created/decided, report
-- generated, reset) is appended here. The trail is a hash chain: each row
-- records the hash of the previous row (prev_hash) and its own hash, computed
-- as sha256(prev_hash + canonical(event)). Altering any stored event breaks
-- its hash and every hash after it, so tampering is detectable by re-walking
-- the chain (GET /api/v1/audit/verify). ``seq`` gives the deterministic append
-- order used for verification.
CREATE TABLE IF NOT EXISTS audit_event (
    seq       BIGSERIAL,
    id        UUID        PRIMARY KEY,
    ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind      TEXT        NOT NULL,
    actor     TEXT        NOT NULL DEFAULT 'system',
    subject   TEXT,
    payload   JSONB       NOT NULL DEFAULT '{}'::jsonb,
    prev_hash TEXT        NOT NULL DEFAULT '',
    hash      TEXT        NOT NULL DEFAULT ''
);

-- Backfill columns for databases created before the hash chain existed.
ALTER TABLE audit_event ADD COLUMN IF NOT EXISTS seq BIGSERIAL;
ALTER TABLE audit_event ADD COLUMN IF NOT EXISTS prev_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE audit_event ADD COLUMN IF NOT EXISTS hash TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS audit_event_seq_idx ON audit_event (seq);
CREATE INDEX IF NOT EXISTS audit_event_ts_idx ON audit_event (ts DESC);
CREATE INDEX IF NOT EXISTS audit_event_kind_idx ON audit_event (kind);

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
    facility_id       TEXT,
    train_id          TEXT,
    status            TEXT        NOT NULL DEFAULT 'pending',
    card              JSONB       NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS recommendation_status_idx ON recommendation (status);
CREATE INDEX IF NOT EXISTS recommendation_ts_idx ON recommendation (ts DESC);

-- 5. Operator feedback -----------------------------------------------------
-- One row per operator confirm/dismiss decision recorded against a
-- condition-intelligence alert. This is the ground-truth signal the condition
-- framework's back-test and calibration harnesses learn from. Advisory only;
-- there is no control state or control-write path here.
CREATE TABLE IF NOT EXISTS operator_feedback (
    feedback_id       TEXT        PRIMARY KEY,
    ts                TIMESTAMPTZ NOT NULL DEFAULT now(),
    alert_id          TEXT        NOT NULL,
    recommendation_id TEXT,
    asset_id          TEXT,
    model_id          TEXT,
    decision          TEXT        NOT NULL,
    actor             TEXT        NOT NULL DEFAULT 'operator',
    note              TEXT,
    payload           JSONB       NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS operator_feedback_alert_idx ON operator_feedback (alert_id);
CREATE INDEX IF NOT EXISTS operator_feedback_ts_idx ON operator_feedback (ts DESC);
