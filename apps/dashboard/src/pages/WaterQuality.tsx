import { useMemo } from 'react';
import { KpiCard } from '../components/KpiCard';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { RecommendationCard } from '../components/RecommendationCard';
import {
  useDecision,
  useWaterQualityAlerts,
  useWaterQualityContaminantMatrix,
  useWaterQualityForecast,
  useWaterQualityRemoval,
  useWaterQualityScaling,
  useWaterQualityStatus,
} from '../hooks';
import { useDashboardStore } from '../state/store';
import { fmtNumber, titleCase } from '../lib/format';
import type { ContaminantMatrixRow, WaterQualityForecast } from '../api/types';

const MATRIX_COLUMNS: { key: keyof ContaminantMatrixRow; label: string }[] = [
  { key: 'intake', label: 'Intake' },
  { key: 'post_pretreatment', label: 'Post-pretreat' },
  { key: 'ro_feed', label: 'RO feed' },
  { key: 'permeate', label: 'Permeate' },
  { key: 'finished', label: 'Finished' },
  { key: 'brine', label: 'Brine' },
];

// The four forecast families surfaced on this page.
const FORECAST_FAMILIES: { prefix: string; label: string }[] = [
  { prefix: 'permeate_salinity', label: 'Permeate salinity' },
  { prefix: 'permeate_boron', label: 'Boron breakthrough' },
  { prefix: 'scaling_time_to_critical', label: 'Scaling time-to-critical' },
  { prefix: 'fouling_risk', label: 'Organic/colloidal/biofouling risk' },
];

function groupForecasts(forecasts: WaterQualityForecast[]) {
  return FORECAST_FAMILIES.map((fam) => ({
    ...fam,
    rows: forecasts.filter((f) => f.target.startsWith(fam.prefix)),
  })).filter((g) => g.rows.length > 0);
}

export function WaterQuality() {
  const status = useWaterQualityStatus();
  const matrix = useWaterQualityContaminantMatrix();
  const removal = useWaterQualityRemoval();
  const scaling = useWaterQualityScaling();
  const forecast = useWaterQualityForecast();
  const alerts = useWaterQualityAlerts();
  const decision = useDecision();
  const operator = useDashboardStore((s) => s.operatorName);

  const forecastGroups = useMemo(
    () => groupForecasts(forecast.data?.forecasts ?? []),
    [forecast.data],
  );

  const handle = (recId: string, kind: 'approve' | 'reject') =>
    decision.mutate({ recId, decision: kind, body: { operator } });

  if (status.isLoading) return <div className="spinner">Loading water quality…</div>;

  const summary = status.data?.summary;

  return (
    <div className="stack" data-testid="water-quality">
      <div className="page-header">
        <div>
          <h2>Water Quality Intelligence</h2>
          <div className="context">
            Advisory water-quality analytics. Forecasts and scaling/fouling/boron risks are{' '}
            <strong>preliminary</strong> engineering estimates with uncertainty — not validated
            production predictions or guaranteed compliance.
          </div>
        </div>
        <ProvenanceBadge provenance="preliminary" />
      </div>

      {/* Summary KPIs */}
      {summary ? (
        <div className="grid kpis">
          <KpiCard
            label="Recovery"
            value={fmtNumber(summary.recovery * 100, 1)}
            unit="%"
            provenance="synthetic"
          />
          <KpiCard
            label="Salt Rejection"
            value={fmtNumber(summary.salt_rejection * 100, 2)}
            unit="%"
            provenance="synthetic"
          />
          <KpiCard
            label="Permeate TDS"
            value={fmtNumber(summary.permeate_tds_mg_l, 0)}
            unit="mg/L"
            provenance="synthetic"
          />
          <KpiCard
            label="Permeate Boron"
            value={fmtNumber(summary.permeate_boron_mg_l, 2)}
            unit="mg/L"
            provenance="preliminary"
          />
          <KpiCard
            label="Norm. Salt Passage"
            value={fmtNumber(summary.normalized_salt_passage * 100, 2)}
            unit="%"
            provenance="preliminary"
          />
          <KpiCard
            label="Norm. Differential Pressure"
            value={fmtNumber(summary.normalized_dp_bar, 2)}
            unit="bar"
            provenance="preliminary"
          />
        </div>
      ) : null}

      {/* Live WQ status by stage */}
      <div className="card" data-testid="wq-status">
        <h3>
          Live Water Quality by Stage
          <ProvenanceBadge provenance="synthetic" className="prov-inline" />
        </h3>
        <table className="data">
          <thead>
            <tr>
              <th>Stage</th>
              <th>Compliance</th>
              <th>Recovery</th>
              <th>Salt rejection</th>
            </tr>
          </thead>
          <tbody>
            {(status.data?.stage_status ?? []).map((s) => {
              const breaches = s.compliance.filter((c) => !c.within_limit);
              return (
                <tr key={s.stage}>
                  <td>{titleCase(s.stage)}</td>
                  <td>
                    {s.compliance.length === 0 ? (
                      <span className="muted">—</span>
                    ) : breaches.length === 0 ? (
                      <span className="status-chip approved">within limits</span>
                    ) : (
                      <span
                        className="status-chip rejected"
                        title={breaches.map((b) => b.variable).join(', ')}
                      >
                        {breaches.length} over limit
                      </span>
                    )}
                  </td>
                  <td className="muted">
                    {s.recovery != null ? `${fmtNumber(s.recovery * 100, 1)}%` : '—'}
                  </td>
                  <td className="muted">
                    {s.salt_rejection != null ? `${fmtNumber(s.salt_rejection * 100, 2)}%` : '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Contaminant matrix */}
      <div className="card" data-testid="wq-contaminant-matrix">
        <h3>
          Contaminant Matrix — intake → brine
          <ProvenanceBadge provenance="synthetic" className="prov-inline" />
        </h3>
        <table className="data">
          <thead>
            <tr>
              <th>Contaminant</th>
              <th>Unit</th>
              {MATRIX_COLUMNS.map((c) => (
                <th key={c.key}>{c.label}</th>
              ))}
              <th>Removal %</th>
            </tr>
          </thead>
          <tbody>
            {(matrix.data?.rows ?? []).map((row) => (
              <tr key={row.contaminant}>
                <td>{row.contaminant}</td>
                <td className="muted">{row.unit}</td>
                {MATRIX_COLUMNS.map((c) => (
                  <td key={c.key} className="muted">
                    {fmtNumber(row[c.key] as number | null | undefined, 2)}
                  </td>
                ))}
                <td>
                  <strong>{row.removal_pct != null ? `${fmtNumber(row.removal_pct, 1)}%` : '—'}</strong>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid cols-2">
        {/* Treatment removal */}
        <div className="card" data-testid="wq-removal">
          <h3>
            Treatment Removal — current vs design vs predicted
            <ProvenanceBadge provenance="preliminary" className="prov-inline" />
          </h3>
          <table className="data">
            <thead>
              <tr>
                <th>Contaminant</th>
                <th>Current</th>
                <th>Design</th>
                <th>Predicted</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {(removal.data?.removal ?? []).map((r) => (
                <tr key={r.contaminant}>
                  <td>{r.contaminant}</td>
                  <td>{r.current_pct != null ? `${fmtNumber(r.current_pct, 1)}%` : '—'}</td>
                  <td className="muted">{fmtNumber(r.design_pct, 1)}%</td>
                  <td>{r.predicted_pct != null ? `${fmtNumber(r.predicted_pct, 1)}%` : '—'}</td>
                  <td className="muted">{fmtNumber(r.confidence * 100, 0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Scaling risk */}
        <div className="card" data-testid="wq-scaling">
          <h3>
            Scaling Risk (per compound)
            <ProvenanceBadge provenance="preliminary" className="prov-inline" />
          </h3>
          <table className="data">
            <thead>
              <tr>
                <th>Compound</th>
                <th>Saturation</th>
                <th>Probability</th>
                <th>Max safe recovery</th>
              </tr>
            </thead>
            <tbody>
              {(scaling.data?.scaling ?? []).map((r) => (
                <tr key={r.compound}>
                  <td>{r.compound}</td>
                  <td className="muted">{fmtNumber(r.saturation, 2)}</td>
                  <td
                    style={{
                      color: r.probability >= 0.5 ? 'var(--danger)' : undefined,
                    }}
                  >
                    {fmtNumber(r.probability * 100, 0)}%
                  </td>
                  <td className="muted">
                    {r.max_safe_recovery != null
                      ? `${fmtNumber(r.max_safe_recovery * 100, 0)}%`
                      : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Forecasts */}
      <div className="card" data-testid="wq-forecast">
        <h3>
          Forecasts — salinity · boron · scaling · fouling
          <ProvenanceBadge provenance="preliminary" className="prov-inline" />
        </h3>
        <div className="context" style={{ marginBottom: 8 }}>
          Preliminary physics/trend estimates with uncertainty bounds (lower–upper). Horizons:
          1h · shift · 24h · 7d.
        </div>
        {forecastGroups.map((group) => (
          <div key={group.prefix} style={{ marginBottom: 14 }}>
            <div className="card-sub" style={{ marginBottom: 4 }}>{group.label}</div>
            <table className="data">
              <thead>
                <tr>
                  <th>Horizon</th>
                  <th>Predicted</th>
                  <th>Range (lower–upper)</th>
                  <th>Unit</th>
                  <th>Confidence</th>
                </tr>
              </thead>
              <tbody>
                {group.rows.map((f) => (
                  <tr key={`${f.target}-${f.horizon}`}>
                    <td>{f.horizon}</td>
                    <td>
                      <strong>{fmtNumber(f.predicted_value, 3)}</strong>
                    </td>
                    <td className="muted">
                      {fmtNumber(f.lower, 3)} – {fmtNumber(f.upper, 3)}
                    </td>
                    <td className="muted">{f.unit}</td>
                    <td className="muted">{fmtNumber(f.confidence * 100, 0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>

      {/* Alerts routed through the recommendation flow */}
      <div className="card" data-testid="wq-alerts">
        <h3>
          Water Quality Alerts
          <span className="prov-badge">{alerts.data?.alerts.length ?? 0}</span>
        </h3>
        <div className="context" style={{ marginBottom: 8 }}>
          Every alert requires operator approval and issues no control write.
        </div>
        {(alerts.data?.recommendations ?? []).length === 0 ? (
          <div className="empty">No active water-quality alerts.</div>
        ) : (
          <div className="stack">
            {(alerts.data?.recommendations ?? []).map((rec) => (
              <RecommendationCard
                key={rec.recommendation_id}
                rec={rec}
                busy={decision.isPending}
                onApprove={(id) => handle(id, 'approve')}
                onReject={(id) => handle(id, 'reject')}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
