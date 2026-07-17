import { useTranslation } from 'react-i18next';
import { ScenarioControls } from '../components/ScenarioControls';

/**
 * Page 8 — Simulation Center. Stubbed in Phase 7; the simulation services
 * (scenario engine, what-if runs) connect in Phases 8–9.
 */
export function SimulationCenter() {
  const { t } = useTranslation();
  return (
    <div className="stack" data-testid="simulation-center">
      <div className="page-header">
        <div>
          <h2>{t('simulation.title')}</h2>
          <div className="context">{t('simulation.context')}</div>
        </div>
      </div>

      <div className="card">
        <h3>{t('simulation.cardTitle')}</h3>
        <p className="muted">{t('simulation.body1')}</p>
        <p className="muted">{t('simulation.body2')}</p>
        <ScenarioControls />
      </div>
    </div>
  );
}
