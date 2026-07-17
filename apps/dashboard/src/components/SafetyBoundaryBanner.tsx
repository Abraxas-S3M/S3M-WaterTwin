import { useControlBoundary } from '../hooks';

/**
 * Always-visible advisory/no-write banner. Reflects the live control boundary
 * from the API. If control writes were ever enabled (they must not be in this
 * system), the banner switches to an error state.
 */
export function SafetyBoundaryBanner() {
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
      <span className="badge-lock">{writeEnabled ? 'WRITE ENABLED' : 'NO CONTROL WRITE'}</span>
      <span>
        {writeEnabled
          ? 'Warning: control write is enabled — this violates the advisory boundary.'
          : `Advisory mode (${mode}). This system does not write to plant controls; all actions require operator approval and are recorded for audit.`}
      </span>
    </div>
  );
}
