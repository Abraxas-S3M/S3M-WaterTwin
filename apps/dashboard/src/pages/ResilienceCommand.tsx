import { Trans, useTranslation } from 'react-i18next';
import { KpiCard } from '../components/KpiCard';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { RecommendationCard } from '../components/RecommendationCard';
import {
  useDecision,
  useResilienceCriticality,
  useResilienceGenerator,
  useRunGridOutage,
} from '../hooks';
import { useDashboardStore } from '../state/store';
import { fmtNumber } from '../lib/format';

export function ResilienceCommand() {
  const { t } = useTranslation();
  const generator = useResilienceGenerator();
  const criticality = useResilienceCriticality();
  const gridOutage = useRunGridOutage();
  const decision = useDecision();
  const operator = useDashboardStore((s) => s.operatorName);

  const gen = gridOutage.data?.generator ?? generator.data?.generator;
  const plan = gridOutage.data?.load_shed_plan;
  const continuity = gridOutage.data?.service_continuity;
  const ranking = gridOutage.data?.criticality ?? criticality.data?.criticality ?? [];
  const recommendation = gridOutage.data?.recommendation;

  const handle = (recId: string, kind: 'approve' | 'reject') =>
    decision.mutate({ recId, decision: kind, body: { operator } });

  return (
    <div className="stack" data-testid="resilience-command">
      <div className="page-header">
        <div>
          <h2>{t('resilience.title')}</h2>
          <div className="context">
            <Trans i18nKey="resilience.context">
              Grid-outage resilience & generator command (advisory). Generator start probability, fuel
              endurance and service-continuity duration are <strong>preliminary</strong> estimates on
              synthetic data — not guaranteed availability or run-time. Any recommendation requires
              operator approval; no control write is issued.
            </Trans>
          </div>
        </div>
        <ProvenanceBadge provenance="preliminary" />
      </div>

      <div className="card">
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
          <h3>{t('resilience.scenarioTitle')}</h3>
          <button
            className="btn"
            data-testid="run-grid-outage"
            disabled={gridOutage.isPending}
            onClick={() => gridOutage.mutate()}
          >
            {gridOutage.isPending ? t('resilience.assessing') : t('resilience.runScenario')}
          </button>
        </div>
        <p className="muted">{t('resilience.scenarioBody')}</p>
      </div>

      {gen ? (
        <div className="grid kpis" data-testid="generator-status">
          <KpiCard
            label={t('resilience.kpi.startProbability')}
            value={fmtNumber(gen.start_probability * 100, 0)}
            unit={t('units.percent')}
            provenance="preliminary"
          />
          <KpiCard
            label={t('resilience.kpi.fuelEndurance')}
            value={fmtNumber(gen.fuel_endurance_hours, 1)}
            unit={t('units.hoursShort')}
            provenance="preliminary"
          />
          <KpiCard
            label={t('resilience.kpi.fuelLevel')}
            value={fmtNumber(gen.fuel_level_fraction * 100, 0)}
            unit={t('units.percent')}
            provenance="synthetic"
          />
          <KpiCard
            label={t('resilience.kpi.loadFraction')}
            value={fmtNumber(gen.load_fraction * 100, 0)}
            unit={t('units.percent')}
            provenance="preliminary"
          />
          {continuity ? (
            <KpiCard
              label={t('resilience.kpi.serviceContinuity')}
              value={fmtNumber(continuity.service_continuity_hours, 1)}
              unit={t('units.hoursShort')}
              provenance="preliminary"
              accent="var(--accent)"
              footer={continuity.limiting_factor}
            />
          ) : null}
        </div>
      ) : null}

      {plan ? (
        <div className="card" data-testid="load-shed-plan">
          <h3>
            {t('resilience.loadShed')}
            <ProvenanceBadge provenance="preliminary" className="prov-inline" />
          </h3>
          <p className="muted">
            {t('resilience.loadShedBody', {
              retained: fmtNumber(plan.retained_load_kw, 0),
              total: fmtNumber(plan.total_load_kw, 0),
              sustained: plan.critical_loads_sustained ? t('common.yes') : t('common.no'),
            })}
          </p>
          <table className="data">
            <thead>
              <tr>
                <th>{t('resilience.loadShedTable.shedOrder')}</th>
                <th>{t('resilience.loadShedTable.asset')}</th>
                <th>{t('resilience.loadShedTable.priority')}</th>
                <th style={{ textAlign: 'right' }}>
                  {t('resilience.loadShedTable.load', { unit: t('units.power_kw') })}
                </th>
                <th>{t('resilience.loadShedTable.status')}</th>
              </tr>
            </thead>
            <tbody>
              {plan.items.map((item) => (
                <tr key={item.asset_id} data-testid={`shed-row-${item.asset_id}`}>
                  <td>{item.shed_order}</td>
                  <td>{item.asset_name ?? item.asset_id}</td>
                  <td className="muted">{item.priority}</td>
                  <td style={{ textAlign: 'right' }}>{fmtNumber(item.load_kw, 0)}</td>
                  <td>
                    <span className={`status-chip ${item.retained ? 'approved' : 'rejected'}`}>
                      {item.retained ? t('resilience.retained') : t('resilience.shed')}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <div className="card" data-testid="criticality-ranking">
        <h3>
          {t('resilience.criticality')}
          <ProvenanceBadge provenance="preliminary" className="prov-inline" />
        </h3>
        {ranking.length === 0 ? (
          <div className="empty">{t('resilience.noCriticality')}</div>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>{t('resilience.criticalityTable.rank')}</th>
                <th>{t('resilience.criticalityTable.asset')}</th>
                <th style={{ textAlign: 'right' }}>{t('resilience.criticalityTable.score')}</th>
                <th style={{ textAlign: 'right' }}>{t('resilience.criticalityTable.impact')}</th>
                <th style={{ textAlign: 'right' }}>{t('resilience.criticalityTable.failureProb')}</th>
                <th style={{ textAlign: 'right' }}>
                  {t('resilience.criticalityTable.recovery', { unit: t('units.hoursShort') })}
                </th>
              </tr>
            </thead>
            <tbody>
              {ranking.map((c, i) => (
                <tr key={c.asset_id}>
                  <td>{c.rank ?? i + 1}</td>
                  <td>{c.asset_name ?? c.asset_id}</td>
                  <td style={{ textAlign: 'right' }}>
                    <strong>{fmtNumber(c.criticality_score, 0)}</strong>
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    {fmtNumber(c.customer_or_production_impact * 100, 0)}%
                  </td>
                  <td style={{ textAlign: 'right' }}>
                    {fmtNumber(c.failure_probability * 100, 0)}%
                  </td>
                  <td style={{ textAlign: 'right' }}>{fmtNumber(c.recovery_time_hours, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {recommendation ? (
        <div className="card" data-testid="resilience-recommendation">
          <h3>{t('resilience.recommendedPriority')}</h3>
          <RecommendationCard
            rec={recommendation}
            busy={decision.isPending}
            onApprove={(id) => handle(id, 'approve')}
            onReject={(id) => handle(id, 'reject')}
          />
        </div>
      ) : null}
    </div>
  );
}
