import { useMemo, useState } from 'react';
import { useFacilities } from '../hooks';
import { useAuth, useFacilityScope } from '../auth/useAuth';
import { scopeFacilities } from '../facilities/scope';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { fmtNumber, fmtTime, titleCase } from '../lib/format';

/**
 * Multi-Facility Administration (Administration section).
 *
 * Tenant-admins manage every facility in their tenant: this panel lists those
 * facilities, their per-facility configuration and the role assignments scoped
 * to each. Facility-operators do not reach this surface — the API scopes them to
 * their own facility and the client gates the panel behind `manageFacilities`.
 */
export function MultiFacilityAdmin() {
  const { capabilities } = useAuth();
  const scope = useFacilityScope();
  const { data, isLoading, isError, error } = useFacilities();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Client-side tenant/entitlement scoping (defence in depth over the API).
  const facilities = useMemo(
    () => scopeFacilities(data?.facilities ?? [], scope),
    [data, scope],
  );

  if (!capabilities.manageFacilities) {
    return (
      <div className="card" data-testid="admin-facilities-forbidden">
        <h3>Multi-Facility Administration</h3>
        <div className="muted">
          Your role does not permit facility administration. Facility operators are
          scoped to their assigned facility.
        </div>
      </div>
    );
  }

  if (isLoading) {
    return <div className="spinner">Loading facilities…</div>;
  }

  if (isError) {
    return (
      <div className="card error" data-testid="admin-facilities-error">
        <h3>Facilities unavailable</h3>
        <div className="muted">
          {(error as Error)?.message ?? 'Could not load facilities.'}
        </div>
      </div>
    );
  }

  const tenantName = facilities[0]?.tenant_name ?? scope.tenantId ?? '—';
  const selected =
    facilities.find((f) => f.facility_id === selectedId) ?? facilities[0] ?? null;

  return (
    <div className="stack" data-testid="multi-facility-admin">
      <div className="page-header">
        <div>
          <h2>Multi-Facility Administration</h2>
          <div className="context">
            {tenantName} · {facilities.length} facilities · tenant {scope.tenantId ?? '—'}
          </div>
        </div>
        {data ? <ProvenanceBadge provenance={data.provenance} /> : null}
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h3>
            Facilities
            <span className="prov-badge">{facilities.length}</span>
          </h3>
          {facilities.length === 0 ? (
            <div className="empty">No facilities in this tenant.</div>
          ) : (
            <table className="data" data-testid="admin-facilities-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Region</th>
                  <th>Status</th>
                  <th>Trains</th>
                  <th>Capacity (m³/day)</th>
                </tr>
              </thead>
              <tbody>
                {facilities.map((f) => (
                  <tr
                    key={f.facility_id}
                    className={`clickable${
                      selected?.facility_id === f.facility_id ? ' active-row' : ''
                    }`}
                    data-testid={`admin-facility-row-${f.facility_id}`}
                    onClick={() => setSelectedId(f.facility_id)}
                  >
                    <td>{f.name}</td>
                    <td>{f.region}</td>
                    <td style={{ textTransform: 'capitalize' }}>{f.status}</td>
                    <td>{f.config.train_count}</td>
                    <td>{fmtNumber(f.config.capacity_m3_day, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {selected ? (
          <div className="card" data-testid="admin-facility-detail">
            <h3>{selected.name}</h3>
            <dl className="definition">
              <dt>Facility ID</dt>
              <dd>{selected.facility_id}</dd>
              <dt>Tenant</dt>
              <dd>
                {selected.tenant_name} ({selected.tenant_id})
              </dd>
              <dt>Region</dt>
              <dd>{selected.region}</dd>
              <dt>Status</dt>
              <dd style={{ textTransform: 'capitalize' }}>{selected.status}</dd>
              <dt>Trains</dt>
              <dd>{selected.config.train_count}</dd>
              <dt>Capacity</dt>
              <dd>{fmtNumber(selected.config.capacity_m3_day, 0)} m³/day</dd>
              <dt>Currency</dt>
              <dd>{selected.config.currency}</dd>
              <dt>Timezone</dt>
              <dd>{selected.config.timezone}</dd>
              <dt>Commissioned</dt>
              <dd>{fmtTime(selected.config.commissioned)}</dd>
            </dl>

            <h3 style={{ marginTop: 16 }}>
              Role Assignments
              <span className="prov-badge">{selected.roles.length}</span>
            </h3>
            {selected.roles.length === 0 ? (
              <div className="empty">No role assignments.</div>
            ) : (
              <table className="data" data-testid="admin-facility-roles">
                <thead>
                  <tr>
                    <th>User</th>
                    <th>Role</th>
                    <th>Subject</th>
                  </tr>
                </thead>
                <tbody>
                  {selected.roles.map((r) => (
                    <tr key={`${r.subject}-${r.role}`}>
                      <td>{r.display_name}</td>
                      <td>{titleCase(r.role)}</td>
                      <td className="muted">{r.subject}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
