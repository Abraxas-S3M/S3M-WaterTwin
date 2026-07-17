import { ScenarioControls } from '../components/ScenarioControls';

/**
 * Page 8 — Simulation Center. Stubbed in Phase 7; the simulation services
 * (scenario engine, what-if runs) connect in Phases 8–9.
 */
export function SimulationCenter() {
  return (
    <div className="stack" data-testid="simulation-center">
      <div className="page-header">
        <div>
          <h2>Simulation Center</h2>
          <div className="context">What-if scenarios &amp; digital-twin simulation</div>
        </div>
      </div>

      <div className="card">
        <h3>Simulation services connect in a later phase</h3>
        <p className="muted">
          The Simulation Center is enabled in Phases 8–9. Scenario runs, what-if
          comparisons, and simulated outputs will appear here once the simulation
          services are wired in. Until then, the dashboard shows live baseline data
          from the WaterTwin API.
        </p>
        <p className="muted">
          You can preview the scenario selector below; selections are UI intent only
          and do not yet drive a simulation.
        </p>
        <ScenarioControls />
      </div>
    </div>
  );
}
