import { useState } from 'react';
import { KpiCard } from '../components/KpiCard';
import {
  useBillingExport,
  useEntitlements,
  useSupportBundle,
  useUpdateChannel,
  useUsage,
} from '../hooks';
import { useAuth } from '../auth/useAuth';
import { titleCase } from '../lib/format';

function fmtLimit(limit: number): string {
  return limit < 0 ? 'Unlimited' : limit.toLocaleString();
}

export function Administration() {
  const { capabilities } = useAuth();
  const entitlements = useEntitlements();
  const usage = useUsage();
  const billing = useBillingExport();
  const channel = useUpdateChannel();
  const bundle = useSupportBundle();
  const [bundleMsg, setBundleMsg] = useState<string | null>(null);

  const ent = entitlements.data?.entitlements;
  const usageSnap = usage.data?.usage;
  const limitsStatus = entitlements.data?.limits_status ?? [];
  const info = channel.data?.update_channel;

  const handleGenerateBundle = () => {
    setBundleMsg(null);
    bundle.mutate(undefined, {
      onSuccess: (blob) => {
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `watertwin-support-bundle-${Date.now()}.zip`;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(url);
        setBundleMsg('Support bundle generated (logs + SBOM + config, secrets redacted).');
      },
      onError: (err) => setBundleMsg((err as Error).message),
    });
  };

  if (!capabilities.administer) {
    return (
      <div className="stack" data-testid="administration">
        <div className="page-header">
          <h2>Administration</h2>
        </div>
        <div className="card">
          <div className="empty" data-testid="admin-forbidden">
            Administration requires the <strong>admin</strong> role. Your account does not have it.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="stack" data-testid="administration">
      <div className="page-header">
        <div>
          <h2>Administration</h2>
          <div className="context">
            Licensing &amp; entitlements, usage metering, the signed-update channel, and support
            bundles. Feature-gating is a commercial/packaging concern only — it never changes the
            advisory / read-only safety boundary.
          </div>
        </div>
      </div>

      {/* Licensing / entitlements */}
      <div className="card" data-testid="admin-entitlements">
        <h3>Licensing &amp; Entitlements</h3>
        {ent ? (
          <>
            <div className="context" style={{ marginBottom: 8 }}>
              Tenant <strong>{ent.tenant_id}</strong> · plan{' '}
              <span className="status-chip approved">{ent.plan}</span>
              {entitlements.data?.safety_invariant_intact ? (
                <span
                  className="status-chip approved"
                  style={{ marginLeft: 8 }}
                  data-testid="safety-invariant-chip"
                  title="Feature-gating never touches the advisory/read-only safety invariant."
                >
                  safety invariant intact
                </span>
              ) : null}
            </div>
            <table className="data">
              <thead>
                <tr>
                  <th>Feature</th>
                  <th>Included in plan</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(ent.features).map(([key, feature]) => (
                  <tr key={key}>
                    <td>{feature.label}</td>
                    <td>
                      {feature.enabled ? (
                        <span className="status-chip approved">included</span>
                      ) : (
                        <span className="status-chip rejected" title="Upgrade the plan to enable">
                          not in plan
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <div className="spinner">Loading entitlements…</div>
        )}
      </div>

      {/* Usage metering */}
      <div className="card" data-testid="admin-usage">
        <h3>Usage Metering</h3>
        <div className="context" style={{ marginBottom: 8 }}>
          Billing period <strong>{usageSnap?.period ?? '—'}</strong>. Advisory bookkeeping only.
        </div>
        <div className="grid kpis">
          <KpiCard label="Facilities" value={usageSnap?.facilities ?? 0} />
          <KpiCard label="Assets" value={usageSnap?.assets ?? 0} />
          <KpiCard label="Ingest volume" value={usageSnap?.ingest_events ?? 0} unit="readings" />
        </div>
        {limitsStatus.length > 0 ? (
          <table className="data" style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th>Metric</th>
                <th>Used</th>
                <th>Plan limit</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {limitsStatus.map((row) => (
                <tr key={row.metric}>
                  <td>{titleCase(row.metric)}</td>
                  <td>{row.used.toLocaleString()}</td>
                  <td className="muted">{fmtLimit(row.limit)}</td>
                  <td>
                    {row.within_limit ? (
                      <span className="status-chip approved">within limit</span>
                    ) : (
                      <span className="status-chip rejected">over limit</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </div>

      {/* Billing export */}
      <div className="card" data-testid="admin-billing">
        <h3>Billing Export</h3>
        <table className="data">
          <thead>
            <tr>
              <th>Metric</th>
              <th>Quantity</th>
              <th>Unit</th>
              <th>Limit</th>
            </tr>
          </thead>
          <tbody>
            {(billing.data?.billing_export.metrics ?? []).map((m) => (
              <tr key={m.metric}>
                <td>{titleCase(m.metric)}</td>
                <td>
                  <strong>{m.quantity.toLocaleString()}</strong>
                </td>
                <td className="muted">{m.unit}</td>
                <td className="muted">{fmtLimit(m.limit)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Signed-update channel */}
      <div className="card" data-testid="admin-update-channel">
        <h3>Signed-Update Channel</h3>
        {info ? (
          <>
            <div className="grid kpis">
              <KpiCard label="Current version" value={info.current_version} />
              <KpiCard label="Channel" value={titleCase(info.channel)} />
              <KpiCard
                label="Auto-update"
                value={info.auto_update_enabled ? 'Enabled' : 'Disabled'}
                accent={info.auto_update_enabled ? 'var(--danger)' : 'var(--ok, #16a34a)'}
              />
            </div>
            <table className="data" style={{ marginTop: 12 }}>
              <tbody>
                <tr>
                  <td>Signature algorithm</td>
                  <td>{info.signature_algorithm}</td>
                </tr>
                <tr>
                  <td>Verify before apply</td>
                  <td>{info.verify_before_apply ? 'Yes' : 'No'}</td>
                </tr>
                <tr>
                  <td>Release public key</td>
                  <td className="muted">
                    {info.public_key_configured
                      ? (info.public_key_fingerprint ?? 'configured')
                      : 'not configured'}
                  </td>
                </tr>
              </tbody>
            </table>
            <p className="muted" style={{ marginTop: 8 }} data-testid="update-policy">
              {info.policy}
            </p>
          </>
        ) : (
          <div className="spinner">Loading update channel…</div>
        )}
      </div>

      {/* Support bundle */}
      <div className="card" data-testid="admin-support">
        <h3>Support Bundle</h3>
        <div className="context" style={{ marginBottom: 8 }}>
          Package recent logs, the SBOM, and a configuration snapshot into a single archive for
          support. <strong>Secrets are redacted</strong> — credentials never leave the platform.
        </div>
        <button
          type="button"
          className="btn primary"
          data-testid="generate-bundle"
          onClick={handleGenerateBundle}
          disabled={bundle.isPending}
        >
          {bundle.isPending ? 'Generating…' : 'Generate support bundle'}
        </button>
        {bundleMsg ? (
          <div className="context" style={{ marginTop: 8 }} data-testid="bundle-status">
            {bundleMsg}
          </div>
        ) : null}
      </div>
    </div>
  );
}
