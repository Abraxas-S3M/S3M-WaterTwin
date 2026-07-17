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
          <h2>Resilience Command</h2>
          <div className="context">
            Grid-outage resilience & generator command (advisory). Generator start probability, fuel
            endurance and service-continuity duration are <strong>preliminary</strong> estimates on
            synthetic data — not guaranteed availability or run-time. Any recommendation requires
            operator approval; no control write is issued.
          </div>
        </div>
        <ProvenanceBadge provenance="preliminary" />
      </div>

      <div className="card">
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
          <h3>Grid-Outage Scenario</h3>
          <button
            className="btn"
            data-testid="run-grid-outage"
            disabled={gridOutage.isPending}
            onClick={() => gridOutage.mutate()}
          >
            {gridOutage.isPending ? 'Assessing…' : 'Run grid-outage scenario'}
          </button>
        </div>
        <p className="muted">
          Assess generator readiness, load-shed order, service continuity and asset criticality
          under a total grid loss. Read-only what-if only.
        </p>
      </div>

      {gen ? (
        <div className="grid kpis" data-testid="generator-status">
          <KpiCard
            label="Generator Start Probability"
            value={fmtNumber(gen.start_probability * 100, 0)}
            unit="%"
            provenance="preliminary"
          />
          <KpiCard
            label="Fuel Endurance"
            value={fmtNumber(gen.fuel_endurance_hours, 1)}
            unit="h"
            provenance="preliminary"
          />
          <KpiCard
            label="Fuel Level"
            value={fmtNumber(gen.fuel_level_fraction * 100, 0)}
            unit="%"
            provenance="synthetic"
          />
          <KpiCard
            label="Load Fraction"
            value={fmtNumber(gen.load_fraction * 100, 0)}
            unit="%"
            provenance="preliminary"
          />
          {continuity ? (
            <KpiCard
              label="Service Continuity"
              value={fmtNumber(continuity.service_continuity_hours, 1)}
              unit="h"
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
            Load-Shed Priority
            <ProvenanceBadge provenance="preliminary" className="prov-inline" />
          </h3>
          <p className="muted">
            Loads are shed lowest-priority first so the HP pump + essential loads are kept last.
            Retained load {fmtNumber(plan.retained_load_kw, 0)} kW of {fmtNumber(plan.total_load_kw, 0)}{' '}
            kW; critical loads sustained: {plan.critical_loads_sustained ? 'yes' : 'no'}.
          </p>
          <table className="data">
            <thead>
              <tr>
                <th>Shed order</th>
                <th>Asset</th>
                <th>Priority</th>
                <th style={{ textAlign: 'right' }}>Load (kW)</th>
                <th>Status</th>
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
                      {item.retained ? 'retained' : 'shed'}
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
          Asset Criticality Ranking
          <ProvenanceBadge provenance="preliminary" className="prov-inline" />
        </h3>
        {ranking.length === 0 ? (
          <div className="empty">No criticality ranking available.</div>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Rank</th>
                <th>Asset</th>
                <th style={{ textAlign: 'right' }}>Score</th>
                <th style={{ textAlign: 'right' }}>Impact</th>
                <th style={{ textAlign: 'right' }}>Failure prob</th>
                <th style={{ textAlign: 'right' }}>Recovery (h)</th>
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
          <h3>Recommended Generator Priority</h3>
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
