import { KpiCard } from '../components/KpiCard';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { useEnergyLosses, useEnergySummary, useOptimizeEnergy } from '../hooks';
import { fmtMoney, fmtNumber } from '../lib/format';
import type { EnergyOptimizationResult } from '../api/types';

function Setpoint({
  label,
  pressure,
  recovery,
  sec,
  flow,
  accent,
}: {
  label: string;
  pressure: number;
  recovery: number;
  sec: number;
  flow: number;
  accent?: string;
}) {
  return (
    <div className="card" style={{ flex: 1 }}>
      <div className="card-sub" style={{ marginBottom: 6 }}>{label}</div>
      <dl className="definition">
        <dt>HP-pump pressure</dt>
        <dd style={accent ? { color: accent } : undefined}>{fmtNumber(pressure, 1)} bar</dd>
        <dt>Recovery</dt>
        <dd>{fmtNumber(recovery * 100, 1)}%</dd>
        <dt>Specific energy</dt>
        <dd style={accent ? { color: accent } : undefined}>{fmtNumber(sec, 3)} kWh/m³</dd>
        <dt>Permeate flow</dt>
        <dd>{fmtNumber(flow, 1)} m³/h</dd>
      </dl>
    </div>
  );
}

export function EnergyOptimization() {
  const summary = useEnergySummary();
  const losses = useEnergyLosses();
  const optimize = useOptimizeEnergy();

  const s = summary.data;
  const optResult: EnergyOptimizationResult | undefined = optimize.data?.optimization;

  if (summary.isLoading) return <div className="spinner">Loading energy optimization…</div>;

  return (
    <div className="stack" data-testid="energy-optimization">
      <div className="page-header">
        <div>
          <h2>Energy Optimization</h2>
          <div className="context">
            Constrained RO specific-energy optimization (advisory). Optimal setpoint and savings are{' '}
            <strong>ESTIMATED</strong> and preliminary on a synthetic basis — not validated savings.
            No control write is issued; setpoints require operator action.
          </div>
        </div>
        <ProvenanceBadge provenance="estimated" />
      </div>

      {s ? (
        <div className="grid kpis">
          <KpiCard
            label="Total Power"
            value={fmtNumber(s.total_power_kw, 0)}
            unit="kW"
            provenance="synthetic"
          />
          <KpiCard
            label="Current SEC"
            value={fmtNumber(s.current_sec_kwh_m3, 3)}
            unit="kWh/m³"
            provenance="synthetic"
          />
          <KpiCard
            label="Optimal SEC"
            value={fmtNumber(s.optimal_sec_kwh_m3, 3)}
            unit="kWh/m³"
            provenance="estimated"
            accent="var(--accent)"
          />
          <KpiCard
            label="SEC Reduction"
            value={fmtNumber(s.sec_reduction_pct, 1)}
            unit="%"
            provenance="estimated"
          />
          <KpiCard
            label="Est. Saving"
            value={fmtMoney(s.estimated_cost_saving_per_day, 0)}
            unit="/day"
            provenance="estimated"
          />
        </div>
      ) : null}

      <div className="card" data-testid="energy-by-asset">
        <h3>
          Energy by Asset
          <ProvenanceBadge provenance="synthetic" className="prov-inline" />
        </h3>
        <table className="data">
          <thead>
            <tr>
              <th>Asset</th>
              <th style={{ textAlign: 'right' }}>Power (kW)</th>
            </tr>
          </thead>
          <tbody>
            {(s?.energy_by_asset ?? []).map((a) => (
              <tr key={a.asset_id}>
                <td>{a.name}</td>
                <td style={{ textAlign: 'right' }}>{fmtNumber(a.power_kw, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card" data-testid="energy-setpoint">
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
          <h3>Current vs Optimal Setpoint</h3>
          <button
            className="btn"
            data-testid="run-optimize"
            disabled={optimize.isPending}
            onClick={() => optimize.mutate()}
          >
            {optimize.isPending ? 'Optimizing…' : 'Run optimization'}
          </button>
        </div>
        <div className="row" style={{ gap: 12, alignItems: 'stretch' }}>
          {s ? (
            <>
              <Setpoint
                label="Current (baseline)"
                pressure={s.current_setpoint.feed_pressure_bar}
                recovery={s.current_setpoint.recovery}
                sec={s.current_setpoint.sec_kwh_m3}
                flow={s.current_setpoint.permeate_flow_m3h}
              />
              <Setpoint
                label="Optimal (estimated)"
                pressure={s.optimal_setpoint.feed_pressure_bar}
                recovery={s.optimal_setpoint.recovery}
                sec={s.optimal_setpoint.sec_kwh_m3}
                flow={s.optimal_setpoint.permeate_flow_m3h}
                accent="var(--accent)"
              />
            </>
          ) : null}
        </div>

        {optResult ? (
          <div className="card-sub" style={{ marginTop: 10 }} data-testid="optimize-result">
            Optimizer: optimal pressure{' '}
            <strong>{fmtNumber(optResult.optimal_feed_pressure_bar, 1)} bar</strong> @ recovery{' '}
            <strong>{fmtNumber(optResult.optimal_recovery * 100, 1)}%</strong> →{' '}
            <strong>{fmtNumber(optResult.optimized_sec_kwh_m3, 3)} kWh/m³</strong>{' '}
            (from {fmtNumber(optResult.baseline_sec_kwh_m3, 3)}).{' '}
            Constraints respected: {optResult.constraints_respected ? 'yes' : 'no'}.{' '}
            <ProvenanceBadge provenance="estimated" />
          </div>
        ) : null}
      </div>

      <div className="card" data-testid="energy-losses">
        <h3>
          Avoidable Energy Loss
          <ProvenanceBadge provenance="estimated" className="prov-inline" />
        </h3>
        <table className="data">
          <thead>
            <tr>
              <th>Item</th>
              <th style={{ textAlign: 'right' }}>Current SEC</th>
              <th style={{ textAlign: 'right' }}>Best achievable</th>
              <th style={{ textAlign: 'right' }}>Avoidable</th>
              <th style={{ textAlign: 'right' }}>Est. saving/day</th>
            </tr>
          </thead>
          <tbody>
            {(losses.data?.losses ?? []).map((loss) => (
              <tr key={loss.label}>
                <td>{loss.label}</td>
                <td style={{ textAlign: 'right' }}>{fmtNumber(loss.current_sec_kwh_m3, 3)}</td>
                <td style={{ textAlign: 'right' }}>
                  {fmtNumber(loss.best_achievable_sec_kwh_m3, 3)}
                </td>
                <td style={{ textAlign: 'right' }}>
                  {fmtNumber(loss.avoidable_loss_kwh_m3, 3)} ({fmtNumber(loss.avoidable_loss_pct, 1)}
                  %)
                </td>
                <td style={{ textAlign: 'right' }}>
                  {fmtMoney(loss.estimated_avoidable_cost_per_day, 0)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
