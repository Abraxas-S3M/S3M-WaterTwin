import { useTranslation } from 'react-i18next';
import { SafetyBoundaryBanner } from '../components/SafetyBoundaryBanner';
import { useBranding } from '../branding/useBranding';
import { beginLogin } from './oidc';
import { useAuth } from './useAuth';

/**
 * Full-screen login gate shown when OIDC is configured and the operator has no
 * active session. The advisory/read-only safety banner stays visible even on
 * the login screen.
 */
export function LoginGate() {
  const { t } = useTranslation();
  const { error } = useAuth();
  const { displayName, displaySubtitle } = useBranding();

  return (
    <div className="app-shell" data-testid="login-gate">
      <SafetyBoundaryBanner />
      <div className="login-wrap">
        <div className="login-card">
          <h1>{displayName}</h1>
          <div className="sub">{displaySubtitle}</div>
          <p className="muted">{t('auth.loginPrompt')}</p>
          {error ? (
            <div className="login-error" role="alert" data-testid="login-error">
              {error}
            </div>
          ) : null}
          <button
            className="btn approve"
            onClick={() => void beginLogin()}
            data-testid="login-button"
          >
            {t('auth.signInKeycloak')}
          </button>
        </div>
      </div>
    </div>
  );
}
