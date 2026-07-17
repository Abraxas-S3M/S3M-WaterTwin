import { KpiCard } from '../components/KpiCard';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { useExecutiveRoi, useExecutiveValueSummary } from '../hooks';
import { fmtMoney, fmtNumber } from '../lib/format';

const BENEFIT_ROWS: { key: string; label: string }[] = [
  { key: 'downtime_avoided', label: 'Downtime avoided' },
  { key: 'energy_savings', label: 'Energy savings' },
  { key: 'chemical_savings', label: 'Chemical savings' },
  { key: 'water_loss_avoided', label: 'Water-loss avoided' },
  { key: 'maintenance_savings', label: 'Maintenance savings' },
  { key: 'capex_deferred', label: 'Capex deferred' },
];

export function ExecutiveValue() {
  const summaryQ = useExecutiveValueSummary();
  const roiQ = useExecutiveRoi();

  const summary = summaryQ.data?.value_summary;
  const roi = roiQ.data?.roi;
  const disclaimer =
    summaryQ.data?.disclaimer ??
    roiQ.data?.disclaimer ??
    'Illustrative estimates on synthetic pilot data — not validated savings or guaranteed outcomes.';

  if (summaryQ.isLoading) return <div className="spinner">Loading executive value…</div>;

  return (
    <div className="stack" data-testid="executive-value">
      <div className="page-header">
        <div>
          <h2>Executive Value / ROI</h2>
          <div className="context">
            Aggregated value across the platform layers (advisory). Every figure is{' '}
            <strong>ESTIMATED</strong> and preliminary.
          </div>
        </div>
        <ProvenanceBadge provenance="estimated" />
      </div>

      {/* Mandatory, visible disclaimer banner. */}
      <div
        className="safety-banner error"
        role="status"
        aria-live="polite"
        data-testid="executive-disclaimer"
      >
        <span className="badge-lock">ESTIMATED · SYNTHETIC</span>
        <span>{disclaimer}</span>
      </div>

      {roi ? (
        <div className="grid kpis">
          <KpiCard
            label="Pilot ROI"
            value={fmtNumber(roi.pilot_roi_pct, 0)}
            unit="%"
            provenance="estimated"
            accent="var(--accent)"
          />
          <KpiCard
            label="Annualized Benefit"
            value={fmtMoney(roi.annualized_benefit, 0)}
            provenance="estimated"
          />
          <KpiCard
            label="Payback Period"
            value={fmtNumber(roi.payback_period_months, 1)}
            unit="months"
            provenance="estimated"
          />
          <KpiCard
            label="Pilot Investment"
            value={fmtMoney(roi.pilot_investment, 0)}
            provenance="synthetic"
          />
        </div>
      ) : null}

      <div className="card" data-testid="value-components">
        <h3>
          Estimated Annualized Benefits
          <ProvenanceBadge provenance="estimated" className="prov-inline" />
        </h3>
        <table className="data">
          <thead>
            <tr>
              <th>Benefit category</th>
              <th style={{ textAlign: 'right' }}>Annualized (est.)</th>
              <th>Provenance</th>
            </tr>
          </thead>
          <tbody>
            {summary
              ? BENEFIT_ROWS.map((row) => (
                  <tr key={row.key}>
                    <td>{row.label}</td>
                    <td style={{ textAlign: 'right' }}>
                      {fmtMoney(summary[row.key as keyof typeof summary] as number, 0)}
                    </td>
                    <td>
                      <ProvenanceBadge provenance="estimated" />
                    </td>
                  </tr>
                ))
              : null}
            {summary ? (
              <tr>
                <td>
                  <strong>Total annualized benefit</strong>
                </td>
                <td style={{ textAlign: 'right' }}>
                  <strong>{fmtMoney(summary.total_annualized_benefit, 0)}</strong>
                </td>
                <td>
                  <ProvenanceBadge provenance="estimated" />
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="card" data-testid="value-basis">
        <h3>Basis of Estimates</h3>
        <p className="muted">
          Each benefit aggregates ESTIMATED outputs from an existing layer; no new physics is
          introduced. These are illustrative figures on synthetic pilot data, not validated savings.
        </p>
        <ul className="card-sub" style={{ paddingLeft: 18 }}>
          {(summary?.components ?? []).map((c) => (
            <li key={c.category}>
              <strong>{c.category.replace(/_/g, ' ')}</strong>: {c.basis} —{' '}
              {fmtMoney(c.annualized_benefit, 0)}/yr <ProvenanceBadge provenance={c.provenance} />
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
