// React hook exposing the current session + role-derived capabilities.

import { useAuthStore } from './store';
import { canApprove, canReadAudit, canReadSecurity, canReset, canRunScenario } from './roles';
import {
  canApprove,
  canManageFacilities,
  canReadAudit,
  canReset,
  canRunScenario,
} from './roles';
import type { FacilityScope } from '../facilities/scope';

export interface Capabilities {
  approve: boolean;
  runScenario: boolean;
  reset: boolean;
  readAudit: boolean;
  readSecurity: boolean;
  manageFacilities: boolean;
}

function capsFor(roles: readonly string[]): Capabilities {
  return {
    approve: canApprove(roles),
    runScenario: canRunScenario(roles),
    reset: canReset(roles),
    readAudit: canReadAudit(roles),
    readSecurity: canReadSecurity(roles),
    manageFacilities: canManageFacilities(roles),
  };
}

export function useAuth() {
  const status = useAuthStore((s) => s.status);
  const username = useAuthStore((s) => s.username);
  const roles = useAuthStore((s) => s.roles);
  const tenantId = useAuthStore((s) => s.tenantId);
  const facilityIds = useAuthStore((s) => s.facilityIds);
  const error = useAuthStore((s) => s.error);

  return {
    status,
    username,
    roles,
    tenantId,
    facilityIds,
    error,
    isAuthenticated: status === 'authenticated',
    capabilities: capsFor(roles),
  };
}

// Convenience selector for components that only need capabilities.
export function useCapabilities(): Capabilities {
  const roles = useAuthStore((s) => s.roles);
  return {
    approve: canApprove(roles),
    runScenario: canRunScenario(roles),
    reset: canReset(roles),
    readAudit: canReadAudit(roles),
    readSecurity: canReadSecurity(roles),
  };
  return capsFor(roles);
}

// The identity's tenant/facility scope, used to defensively filter facility
// data client-side so cross-tenant rows never render.
export function useFacilityScope(): FacilityScope {
  const roles = useAuthStore((s) => s.roles);
  const tenantId = useAuthStore((s) => s.tenantId);
  const facilityIds = useAuthStore((s) => s.facilityIds);
  return { tenantId, facilityIds, roles };
}
