import { ProvenanceBadge } from '../components/ProvenanceBadge';
import {
  useComplianceLimits,
  useComplianceReport,
  useComplianceStatus,
  useModels,
} from '../hooks';
import { fmtNumber, fmtTime } from '../lib/format';
import type { DriftStatus, LimitBound } from '../api/types';

const DRIFT_COLOR: Record<DriftStatus, string> = {
  stable: '#2ecc71',
  watch: '#f1c40f',
  drifting: '#e74c3c',
  unknown: '#8b95a5',
};

function DriftBadge({ status }: { status: DriftStatus }) {
  return (
    <span
      className="prov-badge"
      data-testid="drift-badge"
      data-drift={status}
      style={{ background: DRIFT_COLOR[status], color: '#0b1020' }}
      title={`Model drift status: ${status}`}
    >
      {status}
    </span>
  );
}

function boundPhrase(bound: LimitBound): string {
  return bound === 'max' ? '≤' : '≥';
}

export function Models() {
  const models = useModels();
  const limits = useComplianceLimits();
  const status = useComplianceStatus();
  const report = useComplianceReport();

  const rows = models.data?.models ?? [];
  const limitRows = limits.data?.limits ?? [];
  const evaluation = status.data;
  const exceedances = evaluation?.exceedances ?? [];

  return (
    <div className="stack" data-testid="models">
      <div className="page-header">
        <div>
          <h2>Models &amp; Compliance Governance</h2>
          <div className="context">
            Model registry (versions, specs, current metrics, drift) &amp; configurable regulatory
            compliance · advisory only
            <ProvenanceBadge provenance="preliminary" />
          </div>
        </div>
      </div>

      {/* Model registry (D1/D2 governance) */}
      <div className="card" data-testid="models-registry">
        <h3>Model Registry</h3>
        <p className="muted">
          Governance view of every deterministic analytical model. Metrics are{' '}
          <strong>preliminary</strong> engineering outputs on synthetic data — not validated
          production models. Drift is measured against each model&apos;s registered baseline; nothing
          here writes to plant controls.
        </p>
        {models.isLoading ? (
          <div className="spinner">Loading registry…</div>
        ) : rows.length === 0 ? (
          <div className="empty">No models registered.</div>
        ) : (
          <table className="data" data-testid="models-table">
            <thead>
              <tr>
                <th>Model</th>
                <th>Version</th>
                <th>Track</th>
                <th>Engine</th>
                <th>Drift</th>
                <th>Current metrics</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.model_id} data-testid={`model-row-${m.model_id}`}>
                  <td>
                    {m.name}
                    <div className="muted">{m.description}</div>
                  </td>
                  <td>
                    <code>{m.version}</code>
                  </td>
                  <td>{m.track}</td>
                  <td className="muted">{m.engine}</td>
                  <td>
                    <DriftBadge status={m.drift_status} />
                  </td>
                  <td className="muted">
                    {m.current_metrics.length === 0
                      ? '—'
                      : m.current_metrics.map((metric) => (
                          <div key={metric.name}>
                            {metric.name}: {fmtNumber(metric.value, 3)}
                            {metric.unit ? ` ${metric.unit}` : ''}
                            {metric.drift_pct !== null && metric.drift_pct !== undefined
                              ? ` (${metric.drift_pct >= 0 ? '+' : ''}${fmtNumber(
                                  metric.drift_pct,
                                  1,
                                )}% vs baseline)`
                              : ''}
                          </div>
                        ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Regulatory compliance (A1 config store) */}
      <div className="card" data-testid="compliance-panel">
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
          <h3>Regulatory Compliance</h3>
          {evaluation ? (
            <span
              className="prov-badge"
              data-testid="compliance-overall"
              style={{
                background: evaluation.compliant ? '#2ecc71' : '#e74c3c',
                color: '#0b1020',
              }}
            >
              {evaluation.compliant ? 'Compliant' : `${exceedances.length} exceedance(s)`}
            </span>
          ) : null}
        </div>
        <p className="muted">
          Per-parameter regulatory limits are held in the configurable A1 config store. Current
          (synthetic) values are screened against them; exceedances are flagged with their
          regulatory basis. Advisory decision support only — not a certified regulatory submission.
        </p>

        <h4>Configured limits</h4>
        {limitRows.length === 0 ? (
          <div className="empty">No limits configured.</div>
        ) : (
          <table className="data" data-testid="compliance-limits-table">
            <thead>
              <tr>
                <th>Parameter</th>
                <th>Stage</th>
                <th style={{ textAlign: 'right' }}>Limit</th>
                <th>Basis</th>
              </tr>
            </thead>
            <tbody>
              {limitRows.map((l) => (
                <tr key={l.parameter} data-testid={`limit-row-${l.parameter}`}>
                  <td>
                    {l.display_name} <code className="muted">{l.parameter}</code>
                  </td>
                  <td>{l.stage}</td>
                  <td style={{ textAlign: 'right' }}>
                    {boundPhrase(l.bound)} {fmtNumber(l.limit, 2)} {l.unit}
                  </td>
                  <td className="muted">{l.basis}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <h4 style={{ marginTop: 16 }}>Exceedances</h4>
        {exceedances.length === 0 ? (
          <div className="empty" data-testid="no-exceedances">
            No exceedances against the configured limits.
          </div>
        ) : (
          <table className="data" data-testid="compliance-exceedances-table">
            <thead>
              <tr>
                <th>Parameter</th>
                <th>Stage</th>
                <th style={{ textAlign: 'right' }}>Value</th>
                <th style={{ textAlign: 'right' }}>Limit</th>
                <th style={{ textAlign: 'right' }}>Over by</th>
                <th>Basis</th>
              </tr>
            </thead>
            <tbody>
              {exceedances.map((e) => (
                <tr key={e.parameter} data-testid={`exceedance-row-${e.parameter}`}>
                  <td>
                    <strong>{e.display_name}</strong>
                  </td>
                  <td>{e.stage}</td>
                  <td style={{ textAlign: 'right' }}>
                    {fmtNumber(e.value, 2)} {e.unit}
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    {boundPhrase(e.bound)} {fmtNumber(e.limit, 2)} {e.unit}
                  </td>
                  <td style={{ textAlign: 'right' }}>{fmtNumber(e.exceedance_pct, 1)}%</td>
                  <td className="muted">{e.basis}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="row" style={{ marginTop: 16, gap: 12, alignItems: 'center' }}>
          <button
            className="btn"
            data-testid="generate-compliance-report"
            disabled={report.isPending}
            onClick={() => report.mutate()}
          >
            {report.isPending ? 'Generating…' : 'Generate compliance report'}
          </button>
          {evaluation ? (
            <span className="muted">
              Screened {fmtTime(evaluation.generated_at)} · <ProvenanceBadge provenance="synthetic" />
            </span>
          ) : null}
        </div>
        {report.data ? (
          <pre className="report-preview" data-testid="compliance-report-preview">
            {report.data}
          </pre>
        ) : null}
      </div>
    </div>
  );
}
