import { useDashboardStore } from '../../state/store';
import {
  useEnergySummary,
  useMaintenanceRanking,
  useOverview,
  useResilienceGenerator,
} from '../../hooks';
import { fmtMoney, fmtNumber } from '../../lib/format';
import { ReportBoundaryFooter, ReportHeader, ReportShell } from './ReportShell';

interface Props {
  generatedAt?: Date;
  onPrint?: () => void;
}

/**
 * Shift handover report: a clean, paginated summary of the plant state for the
 * current shift. Reuses the overview, energy, maintenance and resilience APIs —
 * no new data or physics is introduced.
 */
export function ShiftReport({ generatedAt = new Date(), onPrint }: Props) {
  const closeReport = useDashboardStore((s) => s.closeReport);
  const operator = useDashboardStore((s) => s.operatorName);

  const overviewQ = useOverview();
  const energyQ = useEnergySummary();
  const maintenanceQ = useMaintenanceRanking();
  const generatorQ = useResilienceGenerator();

  const overview = overviewQ.data;
  const energy = energyQ.data;
  const ranking = maintenanceQ.data?.ranking ?? [];
  const generator = generatorQ.data?.generator;

  return (
    <ReportShell
      title="Shift Report"
      testId="shift-report"
      onClose={() => closeReport()}
      onPrint={onPrint}
    >
      <section className="report-page">
        <ReportHeader
          title="Shift Report"
          subtitle="Operational handover summary"
          facilityId={overview?.facility_id}
          trainId={overview?.train_id}
          generatedAt={generatedAt}
          operator={operator}
        />

        {overview ? (
          <>
            <h2 className="report-h2">Key performance indicators</h2>
            <table className="report-table" data-testid="shift-kpis">
              <thead>
                <tr>
                  <th>Metric</th>
                  <th className="num">Value</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Plant health</td>
                  <td className="num">{fmtNumber(overview.plant_health.score, 1)}</td>
                  <td>{overview.plant_health.band}</td>
                </tr>
                <tr>
                  <td>Permeate flow (m³/h)</td>
                  <td className="num">{fmtNumber(overview.production.permeate_flow_m3h, 0)}</td>
                  <td>{fmtNumber(overview.production.product_m3_per_day, 0)} m³/day</td>
                </tr>
                <tr>
                  <td>Recovery (%)</td>
                  <td className="num">{fmtNumber(overview.recovery_pct.value, 1)}</td>
                  <td>—</td>
                </tr>
                <tr>
                  <td>Permeate conductivity (µS/cm)</td>
                  <td className="num">
                    {fmtNumber(overview.permeate_conductivity_us_cm.value, 0)}
                  </td>
                  <td>—</td>
                </tr>
                <tr>
                  <td>Total power (kW)</td>
                  <td className="num">{fmtNumber(overview.energy.total_power_kw, 0)}</td>
                  <td>{fmtNumber(overview.energy.specific_energy_kwh_m3, 2)} kWh/m³</td>
                </tr>
                <tr>
                  <td>Service-continuity risk</td>
                  <td className="num">{fmtNumber(overview.service_continuity_risk.score, 0)}</td>
                  <td>{overview.service_continuity_risk.band} risk</td>
                </tr>
              </tbody>
            </table>

            <h2 className="report-h2">Active alarms ({overview.active_alarms.length})</h2>
            {overview.active_alarms.length === 0 ? (
              <p className="report-empty">No active alarms this shift.</p>
            ) : (
              <table className="report-table" data-testid="shift-alarms">
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>Asset</th>
                    <th>Message</th>
                  </tr>
                </thead>
                <tbody>
                  {overview.active_alarms.map((a) => (
                    <tr key={`${a.asset_id}-${a.message}`}>
                      <td>{a.severity}</td>
                      <td>{a.asset_name}</td>
                      <td>{a.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        ) : (
          <p className="report-empty">Overview data is unavailable.</p>
        )}
      </section>

      <section className="report-page">
        <h2 className="report-h2">Open recommendations ({overview?.active_recommendations.length ?? 0})</h2>
        {overview && overview.active_recommendations.length > 0 ? (
          <ul className="report-list" data-testid="shift-recommendations">
            {overview.active_recommendations.map((rec) => (
              <li key={rec.recommendation_id}>
                <strong>{rec.summary}</strong>
                <div className="report-muted">
                  {rec.recommended_action} · status: {rec.approval_status}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="report-empty">No pending recommendations.</p>
        )}

        {energy ? (
          <>
            <h2 className="report-h2">Energy (estimated)</h2>
            <table className="report-table" data-testid="shift-energy">
              <tbody>
                <tr>
                  <td>Current specific energy</td>
                  <td className="num">{fmtNumber(energy.current_sec_kwh_m3, 2)} kWh/m³</td>
                </tr>
                <tr>
                  <td>Best achievable specific energy</td>
                  <td className="num">{fmtNumber(energy.optimal_sec_kwh_m3, 2)} kWh/m³</td>
                </tr>
                <tr>
                  <td>Estimated avoidable cost / day</td>
                  <td className="num">{fmtMoney(energy.estimated_cost_saving_per_day, 0)}</td>
                </tr>
              </tbody>
            </table>
          </>
        ) : null}

        {generator ? (
          <>
            <h2 className="report-h2">Standby power readiness (preliminary)</h2>
            <table className="report-table" data-testid="shift-generator">
              <tbody>
                <tr>
                  <td>Generator start probability</td>
                  <td className="num">{fmtNumber(generator.start_probability * 100, 0)}%</td>
                </tr>
                <tr>
                  <td>Fuel endurance</td>
                  <td className="num">{fmtNumber(generator.fuel_endurance_hours, 1)} h</td>
                </tr>
                <tr>
                  <td>Days since last test</td>
                  <td className="num">{fmtNumber(generator.days_since_last_test, 0)}</td>
                </tr>
              </tbody>
            </table>
          </>
        ) : null}

        {ranking.length > 0 ? (
          <>
            <h2 className="report-h2">Upcoming maintenance priorities</h2>
            <table className="report-table" data-testid="shift-maintenance">
              <thead>
                <tr>
                  <th>Asset</th>
                  <th>Predicted failure mode</th>
                  <th className="num">Intervene in</th>
                </tr>
              </thead>
              <tbody>
                {ranking.map((r) => (
                  <tr key={r.asset_id}>
                    <td>{r.asset_name ?? r.asset_id}</td>
                    <td>{r.predicted_failure_mode}</td>
                    <td className="num">{fmtNumber(r.time_to_intervention_days, 0)} d</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : null}

        <div className="report-signoff">
          <div className="report-signoff-cell">
            <span className="report-signoff-line" />
            Outgoing operator
          </div>
          <div className="report-signoff-cell">
            <span className="report-signoff-line" />
            Incoming operator
          </div>
        </div>

        <ReportBoundaryFooter />
      </section>
    </ReportShell>
  );
}
