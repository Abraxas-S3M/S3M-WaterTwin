// Minimal OIDC Authorization-Code + PKCE client for Keycloak.
//
// Tokens are held in memory only (see store.ts). The only browser storage used
// is a short-lived sessionStorage entry for the PKCE code_verifier + state,
// which is required to survive the redirect to Keycloak and is deleted the
// moment the authorization code is exchanged. No token is ever persisted.

import {
  authorizeEndpoint,
  keycloakConfig,
  logoutEndpoint,
  tokenEndpoint,
} from './config';
import { useAuthStore } from './store';

const PKCE_KEY = 'watertwin.oidc.pkce';

interface PkceHandshake {
  verifier: string;
  state: string;
  redirectUri: string;
}

function base64UrlEncode(bytes: Uint8Array): string {
  let str = '';
  for (const b of bytes) str += String.fromCharCode(b);
  return btoa(str).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function randomString(byteLength = 32): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return base64UrlEncode(bytes);
}

async function sha256Challenge(verifier: string): Promise<string> {
  const data = new TextEncoder().encode(verifier);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return base64UrlEncode(new Uint8Array(digest));
}

function redirectUri(): string {
  // Return to the app origin; the callback (?code&state) is handled on load.
  return `${window.location.origin}${window.location.pathname}`;
}

interface DecodedToken {
  preferred_username?: string;
  email?: string;
  sub?: string;
  exp?: number;
  realm_access?: { roles?: string[] };
  resource_access?: Record<string, { roles?: string[] }>;
}

export function decodeJwt(token: string): DecodedToken {
  const payload = token.split('.')[1];
  if (!payload) return {};
  const normalized = payload.replace(/-/g, '+').replace(/_/g, '/');
  try {
    return JSON.parse(atob(normalized)) as DecodedToken;
  } catch {
    return {};
  }
}

export function rolesFromToken(token: string): string[] {
  const decoded = decodeJwt(token);
  const roles = new Set<string>(decoded.realm_access?.roles ?? []);
  for (const entry of Object.values(decoded.resource_access ?? {})) {
    for (const r of entry.roles ?? []) roles.add(r);
  }
  return [...roles];
}

function applyTokens(access: string, refresh: string | null): void {
  const decoded = decodeJwt(access);
  useAuthStore.getState().setSession({
    status: 'authenticated',
    accessToken: access,
    refreshToken: refresh,
    expiresAt: decoded.exp ? decoded.exp * 1000 : null,
    username: decoded.preferred_username ?? decoded.email ?? decoded.sub ?? 'user',
    roles: rolesFromToken(access),
    error: null,
  });
}

export async function beginLogin(): Promise<void> {
  const verifier = randomString();
  const state = randomString(16);
  const challenge = await sha256Challenge(verifier);
  const uri = redirectUri();

  const handshake: PkceHandshake = { verifier, state, redirectUri: uri };
  sessionStorage.setItem(PKCE_KEY, JSON.stringify(handshake));

  const params = new URLSearchParams({
    client_id: keycloakConfig.clientId,
    redirect_uri: uri,
    response_type: 'code',
    scope: 'openid profile email',
    state,
    code_challenge: challenge,
    code_challenge_method: 'S256',
  });
  window.location.assign(`${authorizeEndpoint()}?${params.toString()}`);
}

async function exchangeCode(code: string, handshake: PkceHandshake): Promise<void> {
  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: keycloakConfig.clientId,
    code,
    redirect_uri: handshake.redirectUri,
    code_verifier: handshake.verifier,
  });
  const res = await fetch(tokenEndpoint(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  if (!res.ok) {
    throw new Error(`token exchange failed (${res.status})`);
  }
  const data = (await res.json()) as { access_token: string; refresh_token?: string };
  applyTokens(data.access_token, data.refresh_token ?? null);
}

/**
 * If the current URL is an OIDC redirect callback (?code&state), complete the
 * login and strip the query params. Returns true when a callback was handled.
 */
export async function completeLoginIfCallback(): Promise<boolean> {
  const params = new URLSearchParams(window.location.search);
  const code = params.get('code');
  const state = params.get('state');
  if (!code || !state) return false;

  const raw = sessionStorage.getItem(PKCE_KEY);
  sessionStorage.removeItem(PKCE_KEY);
  const cleanUrl = `${window.location.origin}${window.location.pathname}`;

  try {
    if (!raw) throw new Error('missing PKCE handshake');
    const handshake = JSON.parse(raw) as PkceHandshake;
    if (handshake.state !== state) throw new Error('state mismatch');
    await exchangeCode(code, handshake);
  } catch (err) {
    useAuthStore.getState().clearSession(
      err instanceof Error ? err.message : 'login failed',
    );
  } finally {
    window.history.replaceState({}, document.title, cleanUrl);
  }
  return true;
}

export async function refreshTokens(): Promise<boolean> {
  const { refreshToken } = useAuthStore.getState();
  if (!refreshToken) return false;
  const body = new URLSearchParams({
    grant_type: 'refresh_token',
    client_id: keycloakConfig.clientId,
    refresh_token: refreshToken,
  });
  try {
    const res = await fetch(tokenEndpoint(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body,
    });
    if (!res.ok) throw new Error(`refresh failed (${res.status})`);
    const data = (await res.json()) as { access_token: string; refresh_token?: string };
    applyTokens(data.access_token, data.refresh_token ?? refreshToken);
    return true;
  } catch {
    useAuthStore.getState().clearSession('session expired — please sign in again');
    return false;
  }
}

export function logout(): void {
  const { refreshToken } = useAuthStore.getState();
  const redirect = `${window.location.origin}${window.location.pathname}`;
  useAuthStore.getState().clearSession();

  const params = new URLSearchParams({
    client_id: keycloakConfig.clientId,
    post_logout_redirect_uri: redirect,
  });
  if (refreshToken) {
    // Best-effort backchannel logout so the Keycloak session ends too.
    void fetch(logoutEndpoint(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        client_id: keycloakConfig.clientId,
        refresh_token: refreshToken,
      }),
    }).catch(() => undefined);
  }
  window.location.assign(`${logoutEndpoint()}?${params.toString()}`);
}
