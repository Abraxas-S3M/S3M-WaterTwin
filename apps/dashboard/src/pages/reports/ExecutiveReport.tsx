import { useDashboardStore } from '../../state/store';
import { useExecutiveRoi, useExecutiveValueSummary } from '../../hooks';
import { fmtMoney, fmtNumber } from '../../lib/format';
import { ReportBoundaryFooter, ReportHeader, ReportShell } from './ReportShell';

interface Props {
  generatedAt?: Date;
  onPrint?: () => void;
}

const BENEFIT_ROWS: { key: string; label: string }[] = [
  { key: 'downtime_avoided', label: 'Downtime avoided' },
  { key: 'energy_savings', label: 'Energy savings' },
  { key: 'chemical_savings', label: 'Chemical savings' },
  { key: 'water_loss_avoided', label: 'Water-loss avoided' },
  { key: 'maintenance_savings', label: 'Maintenance savings' },
  { key: 'capex_deferred', label: 'Capex deferred' },
];

/**
 * Executive value / ROI report: a clean, paginated document that reuses the
 * Executive Value summary + ROI APIs. Every figure is ESTIMATED on synthetic
 * pilot data — the disclaimer and advisory footer are always shown.
 */
export function ExecutiveReport({ generatedAt = new Date(), onPrint }: Props) {
  const closeReport = useDashboardStore((s) => s.closeReport);
  const operator = useDashboardStore((s) => s.operatorName);

  const summaryQ = useExecutiveValueSummary();
  const roiQ = useExecutiveRoi();

  const summary = summaryQ.data?.value_summary;
  const roi = roiQ.data?.roi;
  const disclaimer =
    summaryQ.data?.disclaimer ??
    roiQ.data?.disclaimer ??
    'Illustrative estimates on synthetic pilot data — not validated savings or guaranteed outcomes.';

  return (
    <ReportShell
      title="Executive Report"
      testId="executive-report"
      onClose={() => closeReport()}
      onPrint={onPrint}
    >
      <section className="report-page">
        <ReportHeader
          title="Executive Value / ROI Report"
          subtitle="Aggregated platform value (advisory, estimated)"
          facilityId={summary?.facility_id}
          trainId={summary?.train_id}
          generatedAt={generatedAt}
          operator={operator}
        />

        <div className="report-callout" data-testid="executive-report-disclaimer">
          <span className="report-callout-badge">ESTIMATED · SYNTHETIC</span>
          <span>{disclaimer}</span>
        </div>

        {roi ? (
          <>
            <h2 className="report-h2">ROI headline (estimated)</h2>
            <div className="report-kpis" data-testid="executive-report-roi">
              <div className="report-kpi">
                <div className="report-kpi-label">Pilot ROI</div>
                <div className="report-kpi-value">{fmtNumber(roi.pilot_roi_pct, 0)}%</div>
              </div>
              <div className="report-kpi">
                <div className="report-kpi-label">Annualized benefit</div>
                <div className="report-kpi-value">{fmtMoney(roi.annualized_benefit, 0)}</div>
              </div>
              <div className="report-kpi">
                <div className="report-kpi-label">Payback period</div>
                <div className="report-kpi-value">
                  {fmtNumber(roi.payback_period_months, 1)} mo
                </div>
              </div>
              <div className="report-kpi">
                <div className="report-kpi-label">Pilot investment</div>
                <div className="report-kpi-value">{fmtMoney(roi.pilot_investment, 0)}</div>
              </div>
            </div>
          </>
        ) : null}

        {summary ? (
          <>
            <h2 className="report-h2">Estimated annualized benefits</h2>
            <table className="report-table" data-testid="executive-report-benefits">
              <thead>
                <tr>
                  <th>Benefit category</th>
                  <th className="num">Annualized (est.)</th>
                </tr>
              </thead>
              <tbody>
                {BENEFIT_ROWS.map((row) => (
                  <tr key={row.key}>
                    <td>{row.label}</td>
                    <td className="num">
                      {fmtMoney(summary[row.key as keyof typeof summary] as number, 0)}
                    </td>
                  </tr>
                ))}
                <tr className="report-total">
                  <td>Total annualized benefit</td>
                  <td className="num">{fmtMoney(summary.total_annualized_benefit, 0)}</td>
                </tr>
              </tbody>
            </table>

            <h2 className="report-h2">Basis of estimates</h2>
            <ul className="report-list">
              {summary.components.map((c) => (
                <li key={c.category}>
                  <strong>{c.category.replace(/_/g, ' ')}</strong>: {c.basis} —{' '}
                  {fmtMoney(c.annualized_benefit, 0)}/yr
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="report-empty">Executive value data is unavailable.</p>
        )}

        <ReportBoundaryFooter
          note={
            'This executive report presents ESTIMATED, illustrative value on synthetic pilot ' +
            'data — not validated savings or guaranteed outcomes. It is advisory only and must ' +
            'not be used as an autonomous control action.'
          }
        />
      </section>
    </ReportShell>
  );
}
