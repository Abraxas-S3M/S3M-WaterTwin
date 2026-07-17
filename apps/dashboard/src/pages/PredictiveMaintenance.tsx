import { useState } from 'react';
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
          <h2>Predictive Maintenance</h2>
          <div className="context">
            Risk-ranked equipment & membrane intelligence · advisory only
            <ProvenanceBadge provenance="preliminary" />
          </div>
        </div>
      </div>

      <div className="card">
        <h3>Risk-Ranked Assets</h3>
        <p className="muted">
          Remaining-useful-life, failure probability and avoided-cost are{' '}
          <strong>preliminary</strong> engineering estimates with uncertainty — not validated or
          guaranteed. All actions require operator approval; no control write is issued.
        </p>
        {ranking.isLoading ? (
          <div className="spinner">Loading ranking…</div>
        ) : rows.length === 0 ? (
          <div className="empty">No assets ranked.</div>
        ) : (
          <table className="data" data-testid="pdm-ranking-table">
            <thead>
              <tr>
                <th>Asset</th>
                <th>Health</th>
                <th>Predicted failure mode</th>
                <th style={{ textAlign: 'right' }}>Fail prob (30d)</th>
                <th style={{ textAlign: 'right' }}>RUL (d)</th>
                <th style={{ textAlign: 'right' }}>Time-to-interv. (d)</th>
                <th>Window</th>
                <th>Spares</th>
                <th style={{ textAlign: 'right' }}>Downtime (h)</th>
                <th style={{ textAlign: 'right' }}>Maint. cost</th>
                <th style={{ textAlign: 'right' }}>Avoided cost</th>
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
                    <td style={{ textAlign: 'right' }}>{fmtPct(r.failure_probability_30d)}</td>
                    <td style={{ textAlign: 'right' }}>
                      {fmtNumber(r.rul_days, 0)}
                      <span className="muted">
                        {' '}
                        ({fmtNumber(r.rul_lower_days, 0)}–{fmtNumber(r.rul_upper_days, 0)})
                      </span>
                    </td>
                    <td style={{ textAlign: 'right' }}>{fmtNumber(r.time_to_intervention_days, 0)}</td>
                    <td className="muted">{r.recommended_window}</td>
                    <td className="muted">
                      {r.spares_required.length ? r.spares_required.join(', ') : '—'}
                    </td>
                    <td style={{ textAlign: 'right' }}>{fmtNumber(r.expected_downtime_hours, 0)}</td>
                    <td style={{ textAlign: 'right' }}>{fmtMoney(r.maintenance_cost)}</td>
                    <td style={{ textAlign: 'right' }}>{fmtMoney(r.avoided_failure_cost)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {selectedRec ? (
        <div className="card" data-testid="pdm-detail">
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
            <h3>{selectedRec.asset_name ?? selectedRec.asset_id}</h3>
            <button className="btn" onClick={() => openAssetTwin(selectedRec.asset_id)}>
              Open Asset Twin
            </button>
          </div>
          <dl className="definition">
            <dt>Predicted failure mode</dt>
            <dd>{selectedRec.predicted_failure_mode}</dd>
            <dt>Failure probability (30d)</dt>
            <dd>
              {fmtPct(selectedRec.failure_probability_30d)} <ProvenanceBadge provenance="preliminary" />
            </dd>
            <dt>Preliminary RUL</dt>
            <dd>
              {fmtNumber(selectedRec.rul_days, 0)} d ({fmtNumber(selectedRec.rul_lower_days, 0)}–
              {fmtNumber(selectedRec.rul_upper_days, 0)} d){' '}
              <ProvenanceBadge provenance="preliminary" />
            </dd>
            <dt>Time to intervention</dt>
            <dd>{fmtNumber(selectedRec.time_to_intervention_days, 0)} d</dd>
            <dt>Recommended window</dt>
            <dd>{selectedRec.recommended_window}</dd>
            <dt>Spares required</dt>
            <dd>
              {selectedRec.spares_required.length ? selectedRec.spares_required.join(', ') : 'None'}
            </dd>
            <dt>Expected downtime</dt>
            <dd>{fmtNumber(selectedRec.expected_downtime_hours, 0)} h</dd>
            <dt>Maintenance cost</dt>
            <dd>{fmtMoney(selectedRec.maintenance_cost)} (preliminary)</dd>
            <dt>Avoided-failure cost</dt>
            <dd>{fmtMoney(selectedRec.avoided_failure_cost)} (preliminary)</dd>
          </dl>

          <h3 style={{ marginTop: 16 }}>Advisory Recommendation</h3>
          {selectedCard ? (
            <RecommendationCard
              rec={selectedCard}
              busy={decision.isPending}
              onApprove={(id) => handleDecision(id, 'approve')}
              onReject={(id) => handleDecision(id, 'reject')}
            />
          ) : (
            <div className="empty">No routed recommendation card for this asset yet.</div>
          )}
        </div>
      ) : (
        <div className="card">
          <div className="empty">Select an asset row to see its PdM detail and recommendation.</div>
        </div>
      )}
    </div>
  );
}
