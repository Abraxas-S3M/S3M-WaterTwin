import { useEffect, useMemo } from 'react';
import { useFacilities } from '../hooks';
import { useFacilityScope } from '../auth/useAuth';
import { scopeFacilities } from '../facilities/scope';
import { useDashboardStore } from '../state/store';

/**
 * Shell facility switcher.
 *
 * Lists only the facilities the signed-in identity is entitled to (scoped by
 * tenant + role, cross-tenant rows removed client-side) and keeps the active
 * facility in the dashboard store in sync. A facility-operator scoped to a
 * single facility sees a static label rather than a dropdown.
 */
export function FacilitySwitcher() {
  const scope = useFacilityScope();
  const { data, isLoading, isError } = useFacilities();
  const activeFacilityId = useDashboardStore((s) => s.activeFacilityId);
  const setActiveFacility = useDashboardStore((s) => s.setActiveFacility);

  // Defence in depth: never trust the raw payload — filter to the identity's
  // tenant/entitlement before anything reaches the DOM.
  const facilities = useMemo(
    () => scopeFacilities(data?.facilities ?? [], scope),
    [data, scope],
  );

  // Keep the active facility valid: default to the first visible facility and
  // reset if the current selection falls outside the scoped set (e.g. after a
  // tenant/role change).
  useEffect(() => {
    if (facilities.length === 0) {
      if (activeFacilityId !== null) setActiveFacility(null);
      return;
    }
    const stillVisible = facilities.some((f) => f.facility_id === activeFacilityId);
    if (!stillVisible) setActiveFacility(facilities[0].facility_id);
  }, [facilities, activeFacilityId, setActiveFacility]);

  const tenantName = data?.facilities.find((f) => f.tenant_id === scope.tenantId)?.tenant_name;

  if (isLoading) {
    return (
      <div className="facility-switcher" data-testid="facility-switcher">
        <span className="facility-switcher-label">Facility</span>
        <span className="muted" data-testid="facility-switcher-loading">
          Loading…
        </span>
      </div>
    );
  }

  if (isError || facilities.length === 0) {
    return (
      <div className="facility-switcher" data-testid="facility-switcher">
        <span className="facility-switcher-label">Facility</span>
        <span className="muted" data-testid="facility-switcher-empty">
          No facilities
        </span>
      </div>
    );
  }

  const active = facilities.find((f) => f.facility_id === activeFacilityId) ?? facilities[0];

  return (
    <div className="facility-switcher" data-testid="facility-switcher">
      <span className="facility-switcher-label">
        {tenantName ? tenantName : 'Facility'}
      </span>
      {facilities.length === 1 ? (
        <span className="facility-switcher-single" data-testid="facility-switcher-single">
          {active.name}
        </span>
      ) : (
        <select
          className="facility-switcher-select"
          data-testid="facility-switcher-select"
          aria-label="Active facility"
          value={active.facility_id}
          onChange={(e) => setActiveFacility(e.target.value)}
        >
          {facilities.map((f) => (
            <option
              key={f.facility_id}
              value={f.facility_id}
              data-testid={`facility-option-${f.facility_id}`}
            >
              {f.name}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
