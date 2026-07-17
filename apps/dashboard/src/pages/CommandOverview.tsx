import { KpiCard } from '../components/KpiCard';
import { HealthBar } from '../components/HealthBar';
import { RecommendationCard } from '../components/RecommendationCard';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { FleetRollup } from '../components/FleetRollup';
import { useOverview, useDecision } from '../hooks';
import { useDashboardStore } from '../state/store';
import { fmtNumber, riskColor } from '../lib/format';
import type { HealthBand } from '../api/types';

export function CommandOverview() {
  const { data, isLoading, isError, error } = useOverview();
  const decision = useDecision();
  const operator = useDashboardStore((s) => s.operatorName);

  if (isLoading) return <div className="spinner">Loading command overview…</div>;
  if (isError || !data) {
    return (
      <div className="card">
        <h3>Command overview unavailable</h3>
        <div className="muted">{(error as Error)?.message ?? 'Could not load overview data.'}</div>
      </div>
    );
  }

  const handle = (recId: string, kind: 'approve' | 'reject') =>
    decision.mutate({ recId, decision: kind, body: { operator } });

  return (
    <div className="stack" data-testid="command-overview">
      <div className="page-header">
        <div>
          <h2>Command Overview</h2>
          <div className="context">
            {data.facility_id} · {data.train_id}
          </div>
        </div>
        <ProvenanceBadge provenance={data.provenance} />
      </div>

      <FleetRollup />

      <div className="grid kpis">
        <KpiCard
          label="Plant Health"
          value={fmtNumber(data.plant_health.score, 1)}
          provenance={data.plant_health.provenance}
          footer={<span>{data.plant_health.band}</span>}
        />
        <KpiCard
          label="Production"
          value={fmtNumber(data.production.permeate_flow_m3h, 0)}
          unit="m³/h"
          provenance={data.production.provenance}
          footer={`${fmtNumber(data.production.product_m3_per_day, 0)} m³/day product`}
        />
        <KpiCard
          label="Recovery"
          value={fmtNumber(data.recovery_pct.value, 1)}
          unit="%"
          provenance={data.recovery_pct.provenance}
        />
        <KpiCard
          label="Permeate Conductivity"
          value={fmtNumber(data.permeate_conductivity_us_cm.value, 0)}
          unit="µS/cm"
          provenance={data.permeate_conductivity_us_cm.provenance}
        />
        <KpiCard
          label="Energy"
          value={fmtNumber(data.energy.total_power_kw, 0)}
          unit="kW"
          provenance={data.energy.provenance}
          footer={`Specific energy ${fmtNumber(data.energy.specific_energy_kwh_m3, 2)} kWh/m³`}
        />
        <KpiCard
          label="Service-Continuity Risk"
          value={fmtNumber(data.service_continuity_risk.score, 0)}
          provenance={data.service_continuity_risk.provenance}
          accent={riskColor(data.service_continuity_risk.band)}
          footer={<span style={{ textTransform: 'capitalize' }}>{data.service_continuity_risk.band} risk</span>}
        />
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h3>HP-Pump Status</h3>
          {data.hp_pump_status.band ? (
            <HealthBar
              score={data.hp_pump_status.health ?? 0}
              band={data.hp_pump_status.band as HealthBand}
              provenance={data.hp_pump_status.provenance}
            />
          ) : (
            <div className="empty">No status.</div>
          )}
          <div className="row" style={{ marginTop: 10 }}>
            <span className="card-sub">
              Anomaly score: <strong>{fmtNumber(data.hp_pump_status.anomaly ?? 0, 2)}</strong>
            </span>
            <span className="card-sub">{data.hp_pump_status.asset_id}</span>
          </div>
        </div>

        <div className="card">
          <h3>Membrane Status</h3>
          {data.membrane_status.band ? (
            <HealthBar
              score={data.membrane_status.health ?? 0}
              band={data.membrane_status.band as HealthBand}
              provenance={data.membrane_status.provenance}
            />
          ) : (
            <div className="empty">No status.</div>
          )}
          <div className="row" style={{ marginTop: 10 }}>
            <span className="card-sub">
              Norm. salt passage:{' '}
              <strong>{fmtNumber(data.membrane_status.normalized_salt_passage_pct ?? 0, 2)}%</strong>
            </span>
            <span className="card-sub">{data.membrane_status.asset_id}</span>
          </div>
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h3>
            Active Alarms
            <span className="prov-badge">{data.active_alarms.length}</span>
          </h3>
          {data.active_alarms.length === 0 ? (
            <div className="empty">No active alarms.</div>
          ) : (
            <table className="data">
              <thead>
                <tr>
                  <th>Severity</th>
                  <th>Asset</th>
                  <th>Message</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.active_alarms.map((a) => (
                  <tr key={`${a.asset_id}-${a.message}`}>
                    <td style={{ color: a.severity === 'high' ? 'var(--danger)' : 'var(--warn)' }}>
                      {a.severity}
                    </td>
                    <td>{a.asset_name}</td>
                    <td className="muted">{a.message}</td>
                    <td>
                      <ProvenanceBadge provenance={a.provenance} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <h3>
            Active Recommendations
            <span className="prov-badge">{data.active_recommendations.length}</span>
          </h3>
          {data.active_recommendations.length === 0 ? (
            <div className="empty">No pending recommendations.</div>
          ) : (
            <div className="stack">
              {data.active_recommendations.map((rec) => (
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
    </div>
  );
}
