import { useState } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { HealthBar } from '../components/HealthBar';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { RecommendationCard } from '../components/RecommendationCard';
import {
  useDecision,
  useMaintenanceRanking,
  useMaintenanceRecommendations,
} from '../hooks';
import { useDashboardStore } from '../state/store';
import { fmtNumber } from '../lib/format';
import type { HealthBand, PdMRecommendation } from '../api/types';

function fmtMoney(value: number): string {
  return `$${fmtNumber(value, 0)}`;
}

function fmtPct(value: number): string {
  return `${fmtNumber(value * 100, 0)}%`;
}

function bandFromScore(score: number): HealthBand {
  if (score >= 90) return 'Healthy';
  if (score >= 75) return 'Monitor';
  if (score >= 60) return 'Degraded';
  if (score >= 40) return 'HighRisk';
  return 'Critical';
}

export function PredictiveMaintenance() {
  const { t } = useTranslation();
  const operator = useDashboardStore((s) => s.operatorName);
  const openAssetTwin = useDashboardStore((s) => s.openAssetTwin);
  const ranking = useMaintenanceRanking();
  const recommendations = useMaintenanceRecommendations();
  const decision = useDecision();
  const [selected, setSelected] = useState<string | null>(null);

  const rows = ranking.data?.ranking ?? [];
  const cards = recommendations.data?.cards ?? [];
  const selectedRec: PdMRecommendation | undefined = rows.find((r) => r.asset_id === selected);
  const selectedCard = cards.find(
    (c) => c.asset_id === selected || c.recommendation_id === selectedRec?.recommendation_id,
  );

  const handleDecision = (recId: string, kind: 'approve' | 'reject') =>
    decision.mutate({ recId, decision: kind, body: { operator } });

  return (
    <div className="stack" data-testid="predictive-maintenance">
      <div className="page-header">
        <div>
          <h2>{t('predictiveMaintenance.title')}</h2>
          <div className="context">
            {t('predictiveMaintenance.context')}
            <ProvenanceBadge provenance="preliminary" />
          </div>
        </div>
      </div>

      <div className="card">
        <h3>{t('predictiveMaintenance.riskRankedAssets')}</h3>
        <p className="muted">
          <Trans i18nKey="predictiveMaintenance.disclaimer">
            Remaining-useful-life, failure probability and avoided-cost are{' '}
            <strong>preliminary</strong> engineering estimates with uncertainty — not validated or
            guaranteed. All actions require operator approval; no control write is issued.
          </Trans>
        </p>
        {ranking.isLoading ? (
          <div className="spinner">{t('predictiveMaintenance.loadingRanking')}</div>
        ) : rows.length === 0 ? (
          <div className="empty">{t('predictiveMaintenance.noAssetsRanked')}</div>
        ) : (
          <table className="data" data-testid="pdm-ranking-table">
            <thead>
              <tr>
                <th>{t('predictiveMaintenance.table.asset')}</th>
                <th>{t('predictiveMaintenance.table.health')}</th>
                <th>{t('predictiveMaintenance.table.predictedFailureMode')}</th>
                <th className="cell-num">{t('predictiveMaintenance.table.failProb30d')}</th>
                <th className="cell-num">{t('predictiveMaintenance.table.rulD')}</th>
                <th className="cell-num">{t('predictiveMaintenance.table.timeToInterv')}</th>
                <th>{t('predictiveMaintenance.table.window')}</th>
                <th>{t('predictiveMaintenance.table.spares')}</th>
                <th className="cell-num">{t('predictiveMaintenance.table.downtimeH')}</th>
                <th className="cell-num">{t('predictiveMaintenance.table.maintCost')}</th>
                <th className="cell-num">{t('predictiveMaintenance.table.avoidedCost')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const score = Math.max(0, Math.min(100, 100 - r.failure_probability_30d * 100));
                return (
                  <tr
                    key={r.asset_id}
                    className={`clickable${selected === r.asset_id ? ' active' : ''}`}
                    data-testid={`pdm-row-${r.asset_id}`}
                    onClick={() => setSelected(r.asset_id)}
                  >
                    <td>{r.asset_name ?? r.asset_id}</td>
                    <td style={{ minWidth: 120 }}>
                      <HealthBar score={score} band={bandFromScore(score)} compact />
                    </td>
                    <td className="muted">{r.predicted_failure_mode}</td>
                    <td className="cell-num">{fmtPct(r.failure_probability_30d)}</td>
                    <td className="cell-num">
                      {fmtNumber(r.rul_days, 0)}
                      <span className="muted">
                        {' '}
                        ({fmtNumber(r.rul_lower_days, 0)}–{fmtNumber(r.rul_upper_days, 0)})
                      </span>
                    </td>
                    <td className="cell-num">{fmtNumber(r.time_to_intervention_days, 0)}</td>
                    <td className="muted">{r.recommended_window}</td>
                    <td className="muted">
                      {r.spares_required.length ? r.spares_required.join(', ') : t('common.dash')}
                    </td>
                    <td className="cell-num">{fmtNumber(r.expected_downtime_hours, 0)}</td>
                    <td className="cell-num">{fmtMoney(r.maintenance_cost)}</td>
                    <td className="cell-num">{fmtMoney(r.avoided_failure_cost)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {selectedRec ? (
        <div className="card" data-testid="pdm-detail">
          <div className="row row-split">
            <h3>{selectedRec.asset_name ?? selectedRec.asset_id}</h3>
            <button className="btn" onClick={() => openAssetTwin(selectedRec.asset_id)}>
              {t('predictiveMaintenance.openAssetTwin')}
            </button>
          </div>
          <dl className="definition">
            <dt>{t('predictiveMaintenance.detail.predictedFailureMode')}</dt>
            <dd>{selectedRec.predicted_failure_mode}</dd>
            <dt>{t('predictiveMaintenance.detail.failureProbability30d')}</dt>
            <dd>
              {fmtPct(selectedRec.failure_probability_30d)} <ProvenanceBadge provenance="preliminary" />
            </dd>
            <dt>{t('predictiveMaintenance.detail.preliminaryRul')}</dt>
            <dd>
              {t('predictiveMaintenance.detail.rulValue', {
                value: fmtNumber(selectedRec.rul_days, 0),
                lower: fmtNumber(selectedRec.rul_lower_days, 0),
                upper: fmtNumber(selectedRec.rul_upper_days, 0),
              })}{' '}
              <ProvenanceBadge provenance="preliminary" />
            </dd>
            <dt>{t('predictiveMaintenance.detail.timeToIntervention')}</dt>
            <dd>
              {t('predictiveMaintenance.detail.timeToInterventionValue', {
                value: fmtNumber(selectedRec.time_to_intervention_days, 0),
              })}
            </dd>
            <dt>{t('predictiveMaintenance.detail.recommendedWindow')}</dt>
            <dd>{selectedRec.recommended_window}</dd>
            <dt>{t('predictiveMaintenance.detail.sparesRequired')}</dt>
            <dd>
              {selectedRec.spares_required.length
                ? selectedRec.spares_required.join(', ')
                : t('common.noneCap')}
            </dd>
            <dt>{t('predictiveMaintenance.detail.expectedDowntime')}</dt>
            <dd>
              {t('predictiveMaintenance.detail.expectedDowntimeValue', {
                value: fmtNumber(selectedRec.expected_downtime_hours, 0),
              })}
            </dd>
            <dt>{t('predictiveMaintenance.detail.maintenanceCost')}</dt>
            <dd>
              {t('predictiveMaintenance.detail.maintenanceCostValue', {
                value: fmtMoney(selectedRec.maintenance_cost),
              })}
            </dd>
            <dt>{t('predictiveMaintenance.detail.avoidedFailureCost')}</dt>
            <dd>
              {t('predictiveMaintenance.detail.avoidedFailureCostValue', {
                value: fmtMoney(selectedRec.avoided_failure_cost),
              })}
            </dd>
          </dl>

          <h3 style={{ marginTop: 16 }}>{t('predictiveMaintenance.advisoryRecommendation')}</h3>
          {selectedCard ? (
            <RecommendationCard
              rec={selectedCard}
              busy={decision.isPending}
              onApprove={(id) => handleDecision(id, 'approve')}
              onReject={(id) => handleDecision(id, 'reject')}
            />
          ) : (
            <div className="empty">{t('predictiveMaintenance.noRoutedCard')}</div>
          )}
        </div>
      ) : (
        <div className="card">
          <div className="empty">{t('predictiveMaintenance.selectRow')}</div>
        </div>
      )}
    </div>
  );
}
