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
  error: string | null;
}

interface AuthState extends AuthSession {
  setSession: (s: Partial<AuthSession>) => void;
  clearSession: (error?: string | null) => void;
  setError: (error: string | null) => void;
}

// When auth is not configured, run as a dev "admin" carrying every role so the
// console is fully usable without Keycloak (mirrors the API dev bypass).
const devDefault: AuthSession = {
  status: 'authenticated',
  accessToken: null,
  refreshToken: null,
  expiresAt: null,
  username: 'dev-admin',
  roles: [...ALL_ROLES] as Role[],
  error: null,
};

const anonymousDefault: AuthSession = {
  status: 'anonymous',
  accessToken: null,
  refreshToken: null,
  expiresAt: null,
  username: null,
  roles: [],
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
