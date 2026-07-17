import { useTranslation } from 'react-i18next';
import { useControlBoundary } from '../hooks';

/**
 * Always-visible advisory/no-write banner. Reflects the live control boundary
 * from the API. If control writes were ever enabled (they must not be in this
 * system), the banner switches to an error state.
 */
export function SafetyBoundaryBanner() {
  const { t } = useTranslation();
  const { data } = useControlBoundary();
  const writeEnabled = data?.control_write_enabled ?? false;
  const mode = data?.control_mode ?? 'advisory';

  return (
    <div
      className={`safety-banner${writeEnabled ? ' error' : ''}`}
      role="status"
      aria-live="polite"
      data-testid="safety-boundary-banner"
    >
      <span className="badge-lock">
        {writeEnabled ? t('safety.writeEnabledBadge') : t('safety.noWriteBadge')}
      </span>
      <span>
        {writeEnabled
          ? t('safety.writeEnabledMessage')
          : t('safety.advisoryMessage', { mode })}
      </span>
    </div>
  );
}
