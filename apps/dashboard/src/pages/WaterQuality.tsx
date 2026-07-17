import { useMemo } from 'react';
import { Trans, useTranslation } from 'react-i18next';
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

// Matrix stage columns (labels localized via `waterQuality.matrixColumns.<key>`).
const MATRIX_COLUMNS: (keyof ContaminantMatrixRow)[] = [
  'intake',
  'post_pretreatment',
  'ro_feed',
  'permeate',
  'finished',
  'brine',
];

// The four forecast families surfaced on this page (labels localized via
// `waterQuality.forecastFamilies.<prefix>`).
const FORECAST_FAMILIES: string[] = [
  'permeate_salinity',
  'permeate_boron',
  'scaling_time_to_critical',
  'fouling_risk',
];

function groupForecasts(forecasts: WaterQualityForecast[]) {
  return FORECAST_FAMILIES.map((prefix) => ({
    prefix,
    rows: forecasts.filter((f) => f.target.startsWith(prefix)),
  })).filter((g) => g.rows.length > 0);
}

export function WaterQuality() {
  const { t } = useTranslation();
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

  if (status.isLoading) return <div className="spinner">{t('waterQuality.loading')}</div>;

  const summary = status.data?.summary;

  return (
    <div className="stack" data-testid="water-quality">
      <div className="page-header">
        <div>
          <h2>{t('waterQuality.title')}</h2>
          <div className="context">
            <Trans i18nKey="waterQuality.context">
              Advisory water-quality analytics. Forecasts and scaling/fouling/boron risks are{' '}
              <strong>preliminary</strong> engineering estimates with uncertainty — not validated
              production predictions or guaranteed compliance.
            </Trans>
          </div>
        </div>
        <ProvenanceBadge provenance="preliminary" />
      </div>

      {/* Summary KPIs */}
      {summary ? (
        <div className="grid kpis">
          <KpiCard
            label={t('waterQuality.kpi.recovery')}
            value={fmtNumber(summary.recovery * 100, 1)}
            unit={t('units.percent')}
            provenance="synthetic"
          />
          <KpiCard
            label={t('waterQuality.kpi.saltRejection')}
            value={fmtNumber(summary.salt_rejection * 100, 2)}
            unit={t('units.percent')}
            provenance="synthetic"
          />
          <KpiCard
            label={t('waterQuality.kpi.permeateTds')}
            value={fmtNumber(summary.permeate_tds_mg_l, 0)}
            unit={t('units.concentration_mg_l')}
            provenance="synthetic"
          />
          <KpiCard
            label={t('waterQuality.kpi.permeateBoron')}
            value={fmtNumber(summary.permeate_boron_mg_l, 2)}
            unit={t('units.concentration_mg_l')}
            provenance="preliminary"
          />
          <KpiCard
            label={t('waterQuality.kpi.normSaltPassage')}
            value={fmtNumber(summary.normalized_salt_passage * 100, 2)}
            unit={t('units.percent')}
            provenance="preliminary"
          />
          <KpiCard
            label={t('waterQuality.kpi.normDp')}
            value={fmtNumber(summary.normalized_dp_bar, 2)}
            unit={t('units.pressure_bar')}
            provenance="preliminary"
          />
        </div>
      ) : null}

      {/* Live WQ status by stage */}
      <div className="card" data-testid="wq-status">
        <h3>
          {t('waterQuality.liveByStage')}
          <ProvenanceBadge provenance="synthetic" className="prov-inline" />
        </h3>
        <table className="data">
          <thead>
            <tr>
              <th>{t('waterQuality.stageTable.stage')}</th>
              <th>{t('waterQuality.stageTable.compliance')}</th>
              <th>{t('waterQuality.stageTable.recovery')}</th>
              <th>{t('waterQuality.stageTable.saltRejection')}</th>
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
                      <span className="muted">{t('common.dash')}</span>
                    ) : breaches.length === 0 ? (
                      <span className="status-chip approved">{t('waterQuality.withinLimits')}</span>
                    ) : (
                      <span
                        className="status-chip rejected"
                        title={breaches.map((b) => b.variable).join(', ')}
                      >
                        {t('waterQuality.overLimit', { count: breaches.length })}
                      </span>
                    )}
                  </td>
                  <td className="muted">
                    {s.recovery != null ? `${fmtNumber(s.recovery * 100, 1)}%` : t('common.dash')}
                  </td>
                  <td className="muted">
                    {s.salt_rejection != null
                      ? `${fmtNumber(s.salt_rejection * 100, 2)}%`
                      : t('common.dash')}
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
          {t('waterQuality.contaminantMatrix')}
          <ProvenanceBadge provenance="synthetic" className="prov-inline" />
        </h3>
        <table className="data">
          <thead>
            <tr>
              <th>{t('waterQuality.matrixTable.contaminant')}</th>
              <th>{t('waterQuality.matrixTable.unit')}</th>
              {MATRIX_COLUMNS.map((key) => (
                <th key={key}>{t(`waterQuality.matrixColumns.${key}`)}</th>
              ))}
              <th>{t('waterQuality.matrixTable.removalPct')}</th>
            </tr>
          </thead>
          <tbody>
            {(matrix.data?.rows ?? []).map((row) => (
              <tr key={row.contaminant}>
                <td>{row.contaminant}</td>
                <td className="muted">{row.unit}</td>
                {MATRIX_COLUMNS.map((key) => (
                  <td key={key} className="muted">
                    {fmtNumber(row[key] as number | null | undefined, 2)}
                  </td>
                ))}
                <td>
                  <strong>
                    {row.removal_pct != null ? `${fmtNumber(row.removal_pct, 1)}%` : t('common.dash')}
                  </strong>
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
            {t('waterQuality.treatmentRemoval')}
            <ProvenanceBadge provenance="preliminary" className="prov-inline" />
          </h3>
          <table className="data">
            <thead>
              <tr>
                <th>{t('waterQuality.removalTable.contaminant')}</th>
                <th>{t('waterQuality.removalTable.current')}</th>
                <th>{t('waterQuality.removalTable.design')}</th>
                <th>{t('waterQuality.removalTable.predicted')}</th>
                <th>{t('waterQuality.removalTable.confidence')}</th>
              </tr>
            </thead>
            <tbody>
              {(removal.data?.removal ?? []).map((r) => (
                <tr key={r.contaminant}>
                  <td>{r.contaminant}</td>
                  <td>{r.current_pct != null ? `${fmtNumber(r.current_pct, 1)}%` : t('common.dash')}</td>
                  <td className="muted">{fmtNumber(r.design_pct, 1)}%</td>
                  <td>
                    {r.predicted_pct != null ? `${fmtNumber(r.predicted_pct, 1)}%` : t('common.dash')}
                  </td>
                  <td className="muted">{fmtNumber(r.confidence * 100, 0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Scaling risk */}
        <div className="card" data-testid="wq-scaling">
          <h3>
            {t('waterQuality.scalingRisk')}
            <ProvenanceBadge provenance="preliminary" className="prov-inline" />
          </h3>
          <table className="data">
            <thead>
              <tr>
                <th>{t('waterQuality.scalingTable.compound')}</th>
                <th>{t('waterQuality.scalingTable.saturation')}</th>
                <th>{t('waterQuality.scalingTable.probability')}</th>
                <th>{t('waterQuality.scalingTable.maxSafeRecovery')}</th>
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
                      : t('common.dash')}
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
          {t('waterQuality.forecasts')}
          <ProvenanceBadge provenance="preliminary" className="prov-inline" />
        </h3>
        <div className="context" style={{ marginBottom: 8 }}>
          {t('waterQuality.forecastsHelp')}
        </div>
        {forecastGroups.map((group) => (
          <div key={group.prefix} style={{ marginBottom: 14 }}>
            <div className="card-sub" style={{ marginBottom: 4 }}>
              {t(`waterQuality.forecastFamilies.${group.prefix}`)}
            </div>
            <table className="data">
              <thead>
                <tr>
                  <th>{t('waterQuality.forecastTable.horizon')}</th>
                  <th>{t('waterQuality.forecastTable.predicted')}</th>
                  <th>{t('waterQuality.forecastTable.range')}</th>
                  <th>{t('waterQuality.forecastTable.unit')}</th>
                  <th>{t('waterQuality.forecastTable.confidence')}</th>
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
          {t('waterQuality.alerts')}
          <span className="prov-badge">{alerts.data?.alerts.length ?? 0}</span>
        </h3>
        <div className="context" style={{ marginBottom: 8 }}>
          {t('waterQuality.alertsHelp')}
        </div>
        {(alerts.data?.recommendations ?? []).length === 0 ? (
          <div className="empty">{t('waterQuality.noAlerts')}</div>
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
