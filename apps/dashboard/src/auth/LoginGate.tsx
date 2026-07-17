import { SafetyBoundaryBanner } from '../components/SafetyBoundaryBanner';
import { beginLogin } from './oidc';
import { useAuth } from './useAuth';

/**
 * Full-screen login gate shown when OIDC is configured and the operator has no
 * active session. The advisory/read-only safety banner stays visible even on
 * the login screen.
 */
export function LoginGate() {
  const { error } = useAuth();

  return (
    <div className="app-shell" data-testid="login-gate">
      <SafetyBoundaryBanner />
      <div className="login-wrap">
        <div className="login-card">
          <h1>S3M-WaterTwin</h1>
          <div className="sub">Operator Console</div>
          <p className="muted">
            Sign in with your operator identity to access the advisory console.
            All actions are read-only with respect to plant control and are
            recorded in the audit trail.
          </p>
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
            Sign in with Keycloak
          </button>
        </div>
      </div>
    </div>
  );
}
