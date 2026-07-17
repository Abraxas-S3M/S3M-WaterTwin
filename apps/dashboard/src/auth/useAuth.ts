// React hook exposing the current session + role-derived capabilities.

import { useAuthStore } from './store';
import { canApprove, canReadAudit, canReadSecurity, canReset, canRunScenario } from './roles';

export interface Capabilities {
  approve: boolean;
  runScenario: boolean;
  reset: boolean;
  readAudit: boolean;
  readSecurity: boolean;
}

export function useAuth() {
  const status = useAuthStore((s) => s.status);
  const username = useAuthStore((s) => s.username);
  const roles = useAuthStore((s) => s.roles);
  const error = useAuthStore((s) => s.error);

  const capabilities: Capabilities = {
    approve: canApprove(roles),
    runScenario: canRunScenario(roles),
    reset: canReset(roles),
    readAudit: canReadAudit(roles),
    readSecurity: canReadSecurity(roles),
  };

  return {
    status,
    username,
    roles,
    error,
    isAuthenticated: status === 'authenticated',
    capabilities,
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
}
