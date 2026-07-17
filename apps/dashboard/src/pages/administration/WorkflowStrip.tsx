import type { ConfigStatus, ConfigVersionEntry } from '../../api/types';
import { fmtTime, titleCase } from '../../lib/format';

interface Props {
  status: ConfigStatus;
  version: number;
  updatedBy: string;
  updatedAt: string;
  dirty: boolean;
  busy: boolean;
  canEdit: boolean;
  canApprove: boolean;
  versions: ConfigVersionEntry[];
  onSaveDraft: () => void;
  onSubmit: () => void;
  onApprove: () => void;
  onReject: () => void;
}

const statusChipClass: Record<ConfigStatus, string> = {
  draft: 'pending',
  submitted: 'pending',
  approved: 'approved',
  rejected: 'rejected',
};

export function WorkflowStrip({
  status,
  version,
  updatedBy,
  updatedAt,
  dirty,
  busy,
  canEdit,
  canApprove,
  versions,
  onSaveDraft,
  onSubmit,
  onApprove,
  onReject,
}: Props) {
  const submitted = status === 'submitted';

  return (
    <div className="card admin-workflow" data-testid="admin-workflow-strip">
      <div className="admin-panel-head">
        <div>
          <h3>Change Control</h3>
          <div className="card-sub">
            Draft → Submit → Approve. Changes are advisory configuration only; the API enforces RBAC.
          </div>
        </div>
        <div className="row" style={{ gap: 8, alignItems: 'center' }}>
          <span className={`status-chip ${statusChipClass[status]}`} data-testid="admin-config-status">
            {titleCase(status)}
          </span>
          <span className="card-sub" data-testid="admin-config-version">
            v{version}
          </span>
          {dirty ? (
            <span className="status-chip pending" data-testid="admin-config-dirty">
              Unsaved changes
            </span>
          ) : null}
        </div>
      </div>

      <div className="card-sub" data-testid="admin-config-meta">
        Last updated {fmtTime(updatedAt)} by {updatedBy}
      </div>

      <div className="btn-row" style={{ flexWrap: 'wrap' }}>
        {canEdit ? (
          <>
            <button
              type="button"
              className="btn primary"
              data-testid="admin-save-draft-button"
              disabled={busy || !dirty}
              onClick={onSaveDraft}
            >
              Save draft
            </button>
            <button
              type="button"
              className="btn"
              data-testid="admin-submit-button"
              disabled={busy || dirty || status !== 'draft'}
              onClick={onSubmit}
            >
              Submit for approval
            </button>
          </>
        ) : (
          <span className="muted" data-testid="admin-readonly-note">
            Your role has read-only access. Editing the configuration requires the{' '}
            <strong>admin</strong> role.
          </span>
        )}

        {canApprove ? (
          <>
            <button
              type="button"
              className="btn approve"
              data-testid="admin-approve-button"
              disabled={busy || !submitted}
              onClick={onApprove}
            >
              Approve
            </button>
            <button
              type="button"
              className="btn reject"
              data-testid="admin-reject-button"
              disabled={busy || !submitted}
              onClick={onReject}
            >
              Reject
            </button>
          </>
        ) : (
          <span className="muted" data-testid="admin-approve-role-gate">
            Approving a submitted version requires the <strong>admin</strong> role.
          </span>
        )}
      </div>

      <div className="admin-subtable" data-testid="admin-version-history">
        <div className="card-sub">Version history</div>
        {versions.length === 0 ? (
          <div className="empty">No version history yet.</div>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Version</th>
                <th>Status</th>
                <th>Author</th>
                <th>Approved by</th>
                <th>When</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {versions.map((v) => (
                <tr key={v.version}>
                  <td>v{v.version}</td>
                  <td>
                    <span className={`status-chip ${statusChipClass[v.status]}`}>
                      {titleCase(v.status)}
                    </span>
                  </td>
                  <td className="muted">{v.author}</td>
                  <td className="muted">{v.approved_by ?? '—'}</td>
                  <td className="muted">{fmtTime(v.created_at)}</td>
                  <td className="muted">{v.note ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
