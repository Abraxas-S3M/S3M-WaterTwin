import { useMutation } from '@tanstack/react-query';
import { KpiCard } from '../components/KpiCard';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { useSecurityOverview } from '../hooks';
import { api } from '../api/client';
import { fmtNumber, fmtTime, titleCase } from '../lib/format';
import type {
  ConfidenceBand,
  ConsistencyStatus,
  SecurityStatus,
  SiemExportResponse,
} from '../api/types';

// Map each qualitative status onto one of the shared status-chip classes.
function chipClass(kind: 'ok' | 'warn' | 'bad'): string {
  return kind === 'ok' ? 'approved' : kind === 'warn' ? 'pending' : 'rejected';
}

function statusKind(status: SecurityStatus): 'ok' | 'warn' | 'bad' {
  return status === 'ok' ? 'ok' : status === 'attention' ? 'warn' : 'bad';
}

function consistencyKind(status: ConsistencyStatus): 'ok' | 'warn' | 'bad' {
  return status === 'consistent' ? 'ok' : status === 'deviation' ? 'warn' : 'bad';
}

function confidenceKind(band: ConfidenceBand): 'ok' | 'warn' | 'bad' {
  return band === 'high' ? 'ok' : band === 'medium' ? 'warn' : 'bad';
}

function download(filename: string, content: string, mime: string) {
  // Guard for non-browser (test) environments that lack URL.createObjectURL.
  if (typeof URL === 'undefined' || typeof URL.createObjectURL !== 'function') return;
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function Security() {
  const overview = useSecurityOverview();

  const jsonExport = useMutation({
    mutationFn: () => api.getSiemExport(),
    onSuccess: (data: SiemExportResponse) => {
      download(
        'watertwin-siem-export.json',
        JSON.stringify(data, null, 2),
        'application/json',
      );
    },
  });
  const cefExport = useMutation({
    mutationFn: () => api.getSiemExportCef(),
    onSuccess: (text: string) => {
      download('watertwin-siem-export.cef', text, 'text/plain');
    },
  });

  const data = overview.data;
  const audit = data?.audit_integrity;
  const source = data?.source_health;
  const confidence = data?.sensor_confidence ?? [];
  const consistency = data?.cyber_physical_consistency ?? [];
  const lowestConfidence = confidence[0];
  const lastExport = jsonExport.data;

  return (
    <div className="stack" data-testid="security">
      <div className="page-header">
        <div>
          <h2>Cyber-Physical Security</h2>
          <div className="context">
            Read-only cyber-physical security posture: sensor-confidence scoring, cyber-physical
            consistency (observed telemetry vs. the plant&apos;s hydraulic/physical design
            expectation), telemetry source-health and tamper-evident audit-chain integrity.
            Findings are <strong>advisory and preliminary</strong> on a synthetic basis — not a
            validated security determination. This view is monitoring only; <strong>no control
            write is ever issued</strong>.
          </div>
        </div>
        <ProvenanceBadge provenance={data?.provenance ?? 'preliminary'} />
      </div>

      {overview.isError ? (
        <div className="card" data-testid="security-error">
          <div className="empty">
            {(overview.error as Error)?.message ?? 'Unable to load the security posture.'}
          </div>
        </div>
      ) : null}

      <div className="grid kpis" data-testid="security-kpis">
        <KpiCard
          label="Security Posture"
          value={
            <span className={`status-chip ${chipClass(statusKind(data?.status ?? 'attention'))}`}>
              {data?.status ?? '—'}
            </span>
          }
          provenance="preliminary"
        />
        <KpiCard
          label="Audit-Chain Integrity"
          value={
            <span className={`status-chip ${chipClass(audit?.ok ? 'ok' : 'bad')}`}>
              {audit ? (audit.ok ? 'verified' : 'broken') : '—'}
            </span>
          }
          footer={audit ? `${fmtNumber(audit.count, 0)} events` : undefined}
        />
        <KpiCard
          label="Telemetry Source"
          value={
            <span className={`status-chip ${chipClass(source?.status === 'healthy' ? 'ok' : 'warn')}`}>
              {source?.status ?? '—'}
            </span>
          }
          footer={source?.active_source ? `source: ${source.active_source}` : undefined}
        />
        <KpiCard
          label="Lowest Sensor Confidence"
          value={lowestConfidence ? fmtNumber(lowestConfidence.confidence * 100, 0) : '—'}
          unit={lowestConfidence ? '%' : undefined}
          provenance="preliminary"
          footer={lowestConfidence?.asset_name}
        />
      </div>

      {/* Audit-chain integrity */}
      <div className="card" data-testid="audit-integrity">
        <h3>
          Audit-Chain Integrity
          <ProvenanceBadge provenance="measured" className="prov-inline" />
        </h3>
        <p className="muted">
          The audit trail is a tamper-evident, append-only hash chain. This is the live
          <code> /api/v1/audit </code>verify status; a break identifies the first event whose
          contents or link no longer match.
        </p>
        {audit ? (
          <table className="data">
            <tbody>
              <tr>
                <th>Status</th>
                <td>
                  <span className={`status-chip ${chipClass(audit.ok ? 'ok' : 'bad')}`}>
                    {audit.ok ? 'verified' : 'broken'}
                  </span>
                </td>
              </tr>
              <tr>
                <th>Events in chain</th>
                <td>{fmtNumber(audit.count, 0)}</td>
              </tr>
              {audit.head ? (
                <tr>
                  <th>Chain head</th>
                  <td>
                    <code>{audit.head.slice(0, 16)}…</code>
                  </td>
                </tr>
              ) : null}
              {!audit.ok ? (
                <tr>
                  <th>Broken at</th>
                  <td data-testid="audit-broken-at">
                    {audit.broken_at ?? '—'} — {audit.reason ?? 'chain mismatch'}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        ) : (
          <div className="empty">No audit status available.</div>
        )}
      </div>

      {/* Source health */}
      <div className="card" data-testid="source-health">
        <h3>Telemetry Source Health</h3>
        {source ? (
          <table className="data">
            <tbody>
              <tr>
                <th>Status</th>
                <td>
                  <span
                    className={`status-chip ${chipClass(source.status === 'healthy' ? 'ok' : 'warn')}`}
                  >
                    {source.status}
                  </span>
                </td>
              </tr>
              <tr>
                <th>Active source</th>
                <td>{source.active_source ?? '—'}</td>
              </tr>
              <tr>
                <th>Requested source</th>
                <td>{source.requested_source ?? '—'}</td>
              </tr>
              <tr>
                <th>Fallback to synthetic</th>
                <td>{source.fallback ? `yes — ${source.fallback_reason ?? 'unknown'}` : 'no'}</td>
              </tr>
              {source.reading_count != null ? (
                <tr>
                  <th>Latest readings</th>
                  <td>{fmtNumber(source.reading_count, 0)}</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        ) : (
          <div className="empty">No source status available.</div>
        )}
      </div>

      {/* Sensor confidence */}
      <div className="card" data-testid="sensor-confidence">
        <h3>
          Sensor-Confidence Scoring
          <ProvenanceBadge provenance="preliminary" className="prov-inline" />
        </h3>
        <p className="muted">
          Per-asset trust in the instrument feed, from cross-sensor consistency, physical
          plausibility and calibration recency.
        </p>
        {confidence.length === 0 ? (
          <div className="empty">No sensor-confidence data available.</div>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Asset</th>
                <th className="cell-num">Confidence</th>
                <th>Band</th>
                <th className="cell-num">Cross-sensor</th>
                <th className="cell-num">Plausibility</th>
                <th className="cell-num">Calib. age (d)</th>
              </tr>
            </thead>
            <tbody>
              {confidence.map((row) => (
                <tr key={row.asset_id} data-testid={`confidence-row-${row.asset_id}`}>
                  <td>{row.asset_name}</td>
                  <td className="cell-num">
                    <strong>{fmtNumber(row.confidence * 100, 0)}%</strong>
                  </td>
                  <td>
                    <span className={`status-chip ${chipClass(confidenceKind(row.band))}`}>
                      {row.band}
                    </span>
                  </td>
                  <td className="cell-num">
                    {fmtNumber(row.cross_sensor_consistency * 100, 0)}%
                  </td>
                  <td className="cell-num">
                    {fmtNumber(row.physical_plausibility * 100, 0)}%
                  </td>
                  <td className="cell-num">{fmtNumber(row.calibration_days, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Cyber-physical consistency */}
      <div className="card" data-testid="cyber-physical-consistency">
        <h3>
          Cyber-Physical Consistency
          <ProvenanceBadge provenance="preliminary" className="prov-inline" />
        </h3>
        <p className="muted">
          Observed telemetry compared against the plant&apos;s hydraulic/physical design
          expectation (rated limits, clean baselines). A reading that contradicts the physical
          expectation is flagged for investigation.
        </p>
        {consistency.length === 0 ? (
          <div className="empty">No consistency data available.</div>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Asset</th>
                <th>Status</th>
                <th className="cell-num">Score</th>
                <th>Inconsistent signals</th>
              </tr>
            </thead>
            <tbody>
              {consistency.map((row) => (
                <tr key={row.asset_id} data-testid={`consistency-row-${row.asset_id}`}>
                  <td>{row.asset_name}</td>
                  <td>
                    <span className={`status-chip ${chipClass(consistencyKind(row.status))}`}>
                      {row.status}
                    </span>
                  </td>
                  <td className="cell-num">
                    <strong>{fmtNumber(row.consistency_score * 100, 0)}%</strong>
                  </td>
                  <td>
                    {row.inconsistent_metrics.length === 0
                      ? '—'
                      : row.inconsistent_metrics.map((m) => titleCase(m)).join(', ')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* SIEM export */}
      <div className="card" data-testid="siem-export">
        <div className="row row-split">
          <h3>SIEM Export</h3>
          <div className="btn-row">
            <button
              className="btn"
              data-testid="siem-export-json"
              disabled={jsonExport.isPending}
              onClick={() => jsonExport.mutate()}
            >
              {jsonExport.isPending ? 'Exporting…' : 'Export signed JSON'}
            </button>
            <button
              className="btn"
              data-testid="siem-export-cef"
              disabled={cefExport.isPending}
              onClick={() => cefExport.mutate()}
            >
              {cefExport.isPending ? 'Exporting…' : 'Export CEF'}
            </button>
          </div>
        </div>
        <p className="muted">
          Signed (HMAC-SHA256), append-only export of the immutable audit log for a SIEM. The
          detached signature lets the SIEM independently detect tampering, reordering or
          truncation. Read-only: it snapshots and signs the audit trail and writes nothing.
        </p>
        {lastExport ? (
          <table className="data" data-testid="siem-export-result">
            <tbody>
              <tr>
                <th>Records</th>
                <td>{fmtNumber(lastExport.record_count, 0)}</td>
              </tr>
              <tr>
                <th>Append-only</th>
                <td>{lastExport.append_only ? 'yes' : 'no'}</td>
              </tr>
              <tr>
                <th>Chain verified</th>
                <td>
                  <span className={`status-chip ${chipClass(lastExport.chain.verified ? 'ok' : 'bad')}`}>
                    {lastExport.chain.verified ? 'verified' : 'broken'}
                  </span>
                </td>
              </tr>
              <tr>
                <th>Signature ({lastExport.signature.alg})</th>
                <td data-testid="siem-signature">
                  <code>{lastExport.signature.value.slice(0, 24)}…</code>
                </td>
              </tr>
              <tr>
                <th>Generated</th>
                <td>{fmtTime(lastExport.generated_at)}</td>
              </tr>
            </tbody>
          </table>
        ) : (
          <div className="muted">Export the audit log to generate a signed feed.</div>
        )}
      </div>
    </div>
  );
}
