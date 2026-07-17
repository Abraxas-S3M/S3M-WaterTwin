import { useMemo } from 'react';
import { useFleetOverview } from '../hooks';
import { useFacilityScope } from '../auth/useAuth';
import { scopeFleet } from '../facilities/scope';
import { useDashboardStore } from '../state/store';
import { KpiCard } from './KpiCard';
import { HealthBar } from './HealthBar';
import { ProvenanceBadge } from './ProvenanceBadge';
import { fmtNumber } from '../lib/format';

/**
 * Fleet overview roll-up for Command Overview: health, energy and alerts rolled
 * up across every facility the identity can see. The raw response is scoped
 * client-side (cross-tenant rows removed, totals recomputed) before rendering.
 */
export function FleetRollup() {
  const scope = useFacilityScope();
  const { data, isLoading, isError } = useFleetOverview();
  const activeFacilityId = useDashboardStore((s) => s.activeFacilityId);
  const setActiveFacility = useDashboardStore((s) => s.setActiveFacility);

  const fleet = useMemo(() => (data ? scopeFleet(data, scope) : null), [data, scope]);

  if (isLoading || !fleet) {
    if (isError) return null;
    return (
      <div className="card" data-testid="fleet-rollup-loading">
        <h3>Fleet Overview</h3>
        <div className="spinner">Loading fleet roll-up…</div>
      </div>
    );
  }

  if (fleet.facilities.length === 0) return null;

  const { totals } = fleet;

  return (
    <div className="card" data-testid="fleet-overview">
      <h3>
        Fleet Overview
        <span className="prov-badge">{totals.facility_count} facilities</span>
        <ProvenanceBadge provenance={fleet.provenance} className="prov-inline" />
      </h3>

      <div className="grid kpis" style={{ marginBottom: 16 }}>
        <KpiCard
          label="Facilities Online"
          value={`${totals.online_count} / ${totals.facility_count}`}
          provenance={fleet.provenance}
        />
        <KpiCard
          label="Fleet Avg Health"
          value={fmtNumber(totals.avg_health, 1)}
          provenance={fleet.provenance}
          footer={<span>Worst band: {totals.worst_band}</span>}
        />
        <KpiCard
          label="Fleet Power"
          value={fmtNumber(totals.total_power_kw, 0)}
          unit="kW"
          provenance={fleet.provenance}
        />
        <KpiCard
          label="Fleet Production"
          value={fmtNumber(totals.total_production_m3_day, 0)}
          unit="m³/day"
          provenance={fleet.provenance}
        />
        <KpiCard
          label="Fleet Active Alarms"
          value={fmtNumber(totals.total_active_alarms, 0)}
          provenance={fleet.provenance}
          accent={totals.total_active_alarms > 0 ? 'var(--danger)' : undefined}
        />
      </div>

      <table className="data" data-testid="fleet-table">
        <thead>
          <tr>
            <th>Facility</th>
            <th>Status</th>
            <th>Health</th>
            <th>Power (kW)</th>
            <th>SEC (kWh/m³)</th>
            <th>Production (m³/day)</th>
            <th>Alarms</th>
          </tr>
        </thead>
        <tbody>
          {fleet.facilities.map((f) => (
            <tr
              key={f.facility_id}
              className={`clickable${f.facility_id === activeFacilityId ? ' active-row' : ''}`}
              data-testid={`fleet-row-${f.facility_id}`}
              onClick={() => setActiveFacility(f.facility_id)}
            >
              <td>{f.name}</td>
              <td style={{ textTransform: 'capitalize' }}>{f.status}</td>
              <td style={{ minWidth: 160 }}>
                <HealthBar score={f.health.score} band={f.health.band} compact />
                <span className="muted">
                  {fmtNumber(f.health.score, 1)} · {f.health.band}
                </span>
              </td>
              <td>{fmtNumber(f.energy.total_power_kw, 0)}</td>
              <td>{fmtNumber(f.energy.specific_energy_kwh_m3, 2)}</td>
              <td>{fmtNumber(f.production_m3_day, 0)}</td>
              <td style={{ color: f.active_alarms > 0 ? 'var(--danger)' : undefined }}>
                {f.active_alarms}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
