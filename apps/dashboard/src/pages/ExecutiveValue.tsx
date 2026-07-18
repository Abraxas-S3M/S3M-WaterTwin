import { Trans, useTranslation } from 'react-i18next';
import { KpiCard } from '../components/KpiCard';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { useExecutiveRoi, useExecutiveValueSummary } from '../hooks';
import { fmtMoney, fmtNumber } from '../lib/format';

// Benefit categories (labels localized via `executive.benefitRows.<key>`).
const BENEFIT_ROWS: string[] = [
  'downtime_avoided',
  'energy_savings',
  'chemical_savings',
  'water_loss_avoided',
  'maintenance_savings',
  'capex_deferred',
];

export function ExecutiveValue() {
  const { t } = useTranslation();
  const summaryQ = useExecutiveValueSummary();
  const roiQ = useExecutiveRoi();

  const summary = summaryQ.data?.value_summary;
  const roi = roiQ.data?.roi;
  const disclaimer =
    summaryQ.data?.disclaimer ?? roiQ.data?.disclaimer ?? t('executive.defaultDisclaimer');

  if (summaryQ.isLoading) return <div className="spinner">{t('executive.loading')}</div>;

  return (
    <div className="stack" data-testid="executive-value">
      <div className="page-header">
        <div>
          <h2>{t('executive.title')}</h2>
          <div className="context">
            <Trans i18nKey="executive.context">
              Aggregated value across the platform layers (advisory). Every figure is{' '}
              <strong>ESTIMATED</strong> and preliminary.
            </Trans>
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
        <span className="badge-lock">{t('executive.disclaimerBadge')}</span>
        <span>{disclaimer}</span>
      </div>

      {roi ? (
        <div className="grid kpis">
          <KpiCard
            label={t('executive.kpi.pilotRoi')}
            value={fmtNumber(roi.pilot_roi_pct, 0)}
            unit={t('units.percent')}
            provenance="estimated"
            accent="var(--accent)"
          />
          <KpiCard
            label={t('executive.kpi.annualizedBenefit')}
            value={fmtMoney(roi.annualized_benefit, 0)}
            provenance="estimated"
          />
          <KpiCard
            label={t('executive.kpi.paybackPeriod')}
            value={fmtNumber(roi.payback_period_months, 1)}
            unit={t('executive.kpi.paybackUnit')}
            provenance="estimated"
          />
          <KpiCard
            label={t('executive.kpi.pilotInvestment')}
            value={fmtMoney(roi.pilot_investment, 0)}
            provenance="synthetic"
          />
        </div>
      ) : null}

      <div className="card" data-testid="value-components">
        <h3>
          {t('executive.annualizedBenefits')}
          <ProvenanceBadge provenance="estimated" className="prov-inline" />
        </h3>
        <table className="data">
          <thead>
            <tr>
              <th>{t('executive.benefitTable.category')}</th>
              <th className="cell-num">{t('executive.benefitTable.annualized')}</th>
              <th>{t('executive.benefitTable.provenance')}</th>
            </tr>
          </thead>
          <tbody>
            {summary
              ? BENEFIT_ROWS.map((key) => (
                  <tr key={key}>
                    <td>{t(`executive.benefitRows.${key}`)}</td>
                    <td className="cell-num">
                      {fmtMoney(summary[key as keyof typeof summary] as number, 0)}
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
                  <strong>{t('executive.totalBenefit')}</strong>
                </td>
                <td className="cell-num">
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
        <h3>{t('executive.basis')}</h3>
        <p className="muted">{t('executive.basisBody')}</p>
        <ul className="card-sub" style={{ paddingLeft: 18 }}>
          {(summary?.components ?? []).map((c) => (
            <li key={c.category}>
              <strong>{c.category.replace(/_/g, ' ')}</strong>: {c.basis} —{' '}
              {t('executive.basisItem', { value: fmtMoney(c.annualized_benefit, 0) })}{' '}
              <ProvenanceBadge provenance={c.provenance} />
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
