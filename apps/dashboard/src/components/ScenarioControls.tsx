import { SCENARIOS, useDashboardStore } from '../state/store';

/**
 * Scenario selector for the operator. Selecting a non-baseline scenario is a UI
 * intent only in Phase 7 — the simulation services that drive scenarios connect
 * in Phases 8–9, so we clearly label it as not yet active.
 */
export function ScenarioControls() {
  const scenario = useDashboardStore((s) => s.scenario);
  const setScenario = useDashboardStore((s) => s.setScenario);
  const current = SCENARIOS.find((s) => s.id === scenario) ?? SCENARIOS[0];

  return (
    <div className="scenario-controls" data-testid="scenario-controls">
      <div className="pill-toggle">
        {SCENARIOS.map((s) => (
          <button
            key={s.id}
            className={s.id === scenario ? 'active' : ''}
            onClick={() => setScenario(s.id)}
            aria-pressed={s.id === scenario}
          >
            {s.label}
          </button>
        ))}
      </div>
      <div className="scenario-note">{current.description}</div>
      {scenario !== 'baseline' ? (
        <div className="scenario-note" style={{ color: 'var(--warn)' }}>
          Simulation services connect in a later phase; showing baseline live data.
        </div>
      ) : null}
    </div>
  );
}
