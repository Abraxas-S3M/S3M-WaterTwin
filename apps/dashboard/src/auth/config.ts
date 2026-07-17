// OIDC / Keycloak configuration, baked into the SPA build via Vite env.
//
// When these are unset (e.g. the component test-suite, or a local dev run
// without Keycloak) the dashboard renders without a login gate and behaves as a
// dev "admin" — mirroring the API's WATERTWIN_AUTH_DISABLED bypass. When set,
// the dashboard requires an OIDC login before showing the console.

export interface KeycloakConfig {
  url: string;
  realm: string;
  clientId: string;
}

export const keycloakConfig: KeycloakConfig = {
  url: (import.meta.env.VITE_KEYCLOAK_URL ?? '').replace(/\/$/, ''),
  realm: import.meta.env.VITE_KEYCLOAK_REALM ?? '',
  clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? '',
};

export function isAuthConfigured(): boolean {
  return Boolean(keycloakConfig.url && keycloakConfig.realm && keycloakConfig.clientId);
}

export function realmBase(): string {
  return `${keycloakConfig.url}/realms/${keycloakConfig.realm}`;
}

export function authorizeEndpoint(): string {
  return `${realmBase()}/protocol/openid-connect/auth`;
}

export function tokenEndpoint(): string {
  return `${realmBase()}/protocol/openid-connect/token`;
}

export function logoutEndpoint(): string {
  return `${realmBase()}/protocol/openid-connect/logout`;
}
