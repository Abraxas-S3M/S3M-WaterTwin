import { useTranslation } from 'react-i18next';
import { isAuthConfigured } from './config';
import { logout } from './oidc';
import { useAuth } from './useAuth';

// Highest-privilege role first, for a compact "current role" display.
const ROLE_PRIORITY = ['admin', 'engineer', 'operator', 'auditor', 'viewer'];

function primaryRole(roles: string[]): string {
  for (const r of ROLE_PRIORITY) if (roles.includes(r)) return r;
  return roles[0] ?? 'unknown';
}

/**
 * Shell widget showing the current user + role. When OIDC is configured it also
 * offers a sign-out control; in the dev bypass (no Keycloak) it labels the
 * synthetic session so operators know auth is disabled.
 */
export function UserBadge() {
  const { t } = useTranslation();
  const { username, roles } = useAuth();
  const configured = isAuthConfigured();

  return (
    <div className="user-badge" data-testid="user-badge">
      <div className="user-line">
        <span className="user-name" data-testid="user-name">
          {username ?? t('auth.unknownUser')}
        </span>
        <span className="user-role" data-testid="user-role">
          {primaryRole(roles)}
        </span>
      </div>
      {configured ? (
        <button className="btn ghost" onClick={() => logout()} data-testid="logout-button">
          {t('auth.signOut')}
        </button>
      ) : (
        <span className="muted" data-testid="auth-dev-mode">
          {t('auth.devMode')}
        </span>
      )}
    </div>
  );
}
