import { SCENARIOS, useDashboardStore } from '../state/store';
import { useCapabilities } from '../auth/useAuth';

/**
 * Scenario selector for the operator. Selecting a non-baseline scenario is a UI
 * intent only in Phase 7 — the simulation services that drive scenarios connect
 * in Phases 8–9, so we clearly label it as not yet active.
 *
 * Running a what-if scenario is an engineer/admin action, so non-baseline
 * selections are gated by role (the API independently enforces the same rule).
 */
export function ScenarioControls() {
  const scenario = useDashboardStore((s) => s.scenario);
  const setScenario = useDashboardStore((s) => s.setScenario);
  const current = SCENARIOS.find((s) => s.id === scenario) ?? SCENARIOS[0];
  const { runScenario: canRunScenario } = useCapabilities();

  return (
    <div className="scenario-controls" data-testid="scenario-controls">
      <div className="pill-toggle">
        {SCENARIOS.map((s) => {
          const gated = s.id !== 'baseline' && !canRunScenario;
          return (
            <button
              key={s.id}
              className={s.id === scenario ? 'active' : ''}
              onClick={() => setScenario(s.id)}
              aria-pressed={s.id === scenario}
              disabled={gated}
              title={gated ? 'Requires the engineer role to run what-if scenarios' : undefined}
              data-testid={`scenario-${s.id}`}
            >
              {s.label}
            </button>
          );
        })}
      </div>
      <div className="scenario-note">{current.description}</div>
      {!canRunScenario ? (
        <div className="scenario-note" data-testid="scenario-role-gate">
          Running what-if scenarios requires the <strong>engineer</strong> role.
        </div>
      ) : null}
      {scenario !== 'baseline' ? (
        <div className="scenario-note" style={{ color: 'var(--warn)' }}>
          Simulation services connect in a later phase; showing baseline live data.
        </div>
      ) : null}
    </div>
  );
}
