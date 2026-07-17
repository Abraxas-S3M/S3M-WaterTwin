// In-memory authentication session store.
//
// SECURITY: the access/refresh tokens live ONLY in this in-memory zustand store
// for the lifetime of the tab. They are never written to localStorage,
// sessionStorage, or cookies. A full page reload therefore requires a fresh
// (silent or interactive) login — an intentional trade-off that keeps tokens
// out of browser storage.

import { create } from 'zustand';
import { ALL_ROLES, type Role } from './roles';
import { isAuthConfigured } from './config';

export interface AuthSession {
  status: 'anonymous' | 'authenticated';
  accessToken: string | null;
  refreshToken: string | null;
  expiresAt: number | null;
  username: string | null;
  roles: string[];
  // Multi-tenant / multi-facility scope carried by the identity token. The
  // client uses these to defensively scope facility data so cross-tenant rows
  // never render, even if an upstream response were to over-return (the API is
  // the authoritative enforcer; this is client-side defence in depth).
  tenantId: string | null;
  // Facilities this identity is explicitly entitled to. Empty means "all
  // facilities within the tenant" for tenant-admins/admins; for a
  // facility-operator it is the single facility (or facilities) they may see.
  facilityIds: string[];
  error: string | null;
}

interface AuthState extends AuthSession {
  setSession: (s: Partial<AuthSession>) => void;
  clearSession: (error?: string | null) => void;
  setError: (error: string | null) => void;
}

// When auth is not configured, run as a dev "admin" carrying every role so the
// console is fully usable without Keycloak (mirrors the API dev bypass). The
// dev identity is scoped to a demo tenant so the multi-facility surfaces work
// end-to-end locally.
export const DEV_TENANT_ID = 'TEN-ACME';

const devDefault: AuthSession = {
  status: 'authenticated',
  accessToken: null,
  refreshToken: null,
  expiresAt: null,
  username: 'dev-admin',
  roles: [...ALL_ROLES] as Role[],
  tenantId: DEV_TENANT_ID,
  facilityIds: [],
  error: null,
};

const anonymousDefault: AuthSession = {
  status: 'anonymous',
  accessToken: null,
  refreshToken: null,
  expiresAt: null,
  username: null,
  roles: [],
  tenantId: null,
  facilityIds: [],
  error: null,
};

const initial: AuthSession = isAuthConfigured() ? anonymousDefault : devDefault;

export const useAuthStore = create<AuthState>((set) => ({
  ...initial,
  setSession: (s) => set((prev) => ({ ...prev, ...s })),
  clearSession: (error = null) => set({ ...anonymousDefault, error }),
  setError: (error) => set({ error }),
}));

// Plain (non-hook) accessor so the fetch layer can read the current token
// without subscribing to React.
export function getAccessToken(): string | null {
  return useAuthStore.getState().accessToken;
}
