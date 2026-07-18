// The advisory roles seeded in the Keycloak "watertwin" realm, mirrored on the
// client so the UI can gate role-restricted controls. This gating is a UX
// affordance only — the API independently enforces RBAC (and tenant/facility
// scoping) on every request.
//
// Multi-facility roles:
//   - `tenant-admin`     manages every facility within its tenant.
//   - `facility-operator` is scoped to the specific facility (or facilities)
//                         assigned to it and never sees the rest of the fleet.

export type Role =
  | 'viewer'
  | 'operator'
  | 'engineer'
  | 'admin'
  | 'auditor'
  | 'security'
  | 'tenant-admin'
  | 'facility-operator';

export const ALL_ROLES: Role[] = [
  'viewer',
  'operator',
  'engineer',
  'admin',
  'auditor',
  'security',
  'tenant-admin',
  'facility-operator',
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

export function canAdminister(roles: readonly string[]): boolean {
  return hasAny(roles, 'admin');
}
// Configuration Workbench: editing the config draft and approving a submitted
// version are both administrator-only. Every other role gets a read-only view.
export function canAdministerConfig(roles: readonly string[]): boolean {
  return hasAny(roles, 'admin');
}

export function canApproveConfig(roles: readonly string[]): boolean {
  return hasAny(roles, 'admin');
}
// The Cyber-Physical Security views + signed SIEM export are gated to the
// security role (admin is a superset). This is a UX affordance only; the API
// independently enforces the same gate on every request.
export function canReadSecurity(roles: readonly string[]): boolean {
  return hasAny(roles, 'security', 'admin');
}
// Multi-facility administration: a tenant-admin (or platform admin) may view and
// manage every facility in the tenant. A facility-operator is scoped to its own
// facility and must not reach the fleet-wide administration surface.
export function canManageFacilities(roles: readonly string[]): boolean {
  return hasAny(roles, 'tenant-admin', 'admin');
}
