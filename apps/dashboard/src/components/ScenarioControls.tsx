import { Trans, useTranslation } from 'react-i18next';
import { SCENARIO_IDS, useDashboardStore } from '../state/store';
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
  const { t } = useTranslation();
  const scenario = useDashboardStore((s) => s.scenario);
  const setScenario = useDashboardStore((s) => s.setScenario);
  const { runScenario: canRunScenario } = useCapabilities();

  return (
    <div className="scenario-controls" data-testid="scenario-controls">
      <div className="pill-toggle">
        {SCENARIO_IDS.map((id) => {
          const gated = id !== 'baseline' && !canRunScenario;
          return (
            <button
              key={id}
              className={id === scenario ? 'active' : ''}
              onClick={() => setScenario(id)}
              aria-pressed={id === scenario}
              disabled={gated}
              title={gated ? t('scenarios.roleGateTitle') : undefined}
              data-testid={`scenario-${id}`}
            >
              {t(`scenarios.items.${id}.label`)}
            </button>
          );
        })}
      </div>
      <div className="scenario-note">{t(`scenarios.items.${scenario}.description`)}</div>
      {!canRunScenario ? (
        <div className="scenario-note" data-testid="scenario-role-gate">
          <Trans i18nKey="scenarios.roleGate">
            Running what-if scenarios requires the <strong>engineer</strong> role.
          </Trans>
        </div>
      ) : null}
      {scenario !== 'baseline' ? (
        <div className="scenario-note" style={{ color: 'var(--warn)' }}>
          {t('scenarios.notActive')}
        </div>
      ) : null}
    </div>
  );
}
