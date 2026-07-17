// The five advisory roles seeded in the Keycloak "watertwin" realm, mirrored on
// the client so the UI can gate role-restricted controls. This gating is a UX
// affordance only — the API independently enforces RBAC on every request.

export type Role = 'viewer' | 'operator' | 'engineer' | 'admin' | 'auditor' | 'security';

export const ALL_ROLES: Role[] = [
  'viewer',
  'operator',
  'engineer',
  'admin',
  'auditor',
  'security',
];

export function hasAny(roles: readonly string[], ...required: Role[]): boolean {
  return required.some((r) => roles.includes(r));
}

// Capability helpers derived from the RBAC matrix (admin is a superset).
export function canApprove(roles: readonly string[]): boolean {
  return hasAny(roles, 'operator', 'admin');
}

export function canRunScenario(roles: readonly string[]): boolean {
  return hasAny(roles, 'engineer', 'admin');
}

export function canReset(roles: readonly string[]): boolean {
  return hasAny(roles, 'engineer', 'admin');
}

export function canReadAudit(roles: readonly string[]): boolean {
  return hasAny(roles, 'auditor', 'admin');
}

// The Cyber-Physical Security views + signed SIEM export are gated to the
// security role (admin is a superset). This is a UX affordance only; the API
// independently enforces the same gate on every request.
export function canReadSecurity(roles: readonly string[]): boolean {
  return hasAny(roles, 'security', 'admin');
}
