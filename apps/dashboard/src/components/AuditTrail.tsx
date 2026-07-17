import type { AuditEntry, DataProvenance } from '../api/types';
import { fmtTime, titleCase } from '../lib/format';
import { ProvenanceBadge } from './ProvenanceBadge';

interface Props {
  entries: AuditEntry[];
  provenance?: DataProvenance;
  loading?: boolean;
}

const actionColor: Record<string, string> = {
  recommendation_created: '#38bdf8',
  recommendation_approved: '#2ecc71',
  recommendation_rejected: '#e74c3c',
};

export function AuditTrail({ entries, provenance, loading }: Props) {
  return (
    <div data-testid="audit-trail">
      {provenance ? (
        <div className="spread" style={{ marginBottom: 8 }}>
          <span className="card-sub">Immutable record of advisory decisions</span>
          <ProvenanceBadge provenance={provenance} />
        </div>
      ) : null}
      {loading ? (
        <div className="spinner">Loading audit trail…</div>
      ) : entries.length === 0 ? (
        <div className="empty">No audit entries yet.</div>
      ) : (
        <div className="audit-list">
          {entries.map((e) => (
            <div className="audit-entry" key={e.id}>
              <span
                className="dot"
                style={{ background: actionColor[e.action] ?? '#8b95a5' }}
              />
              <div>
                <div className="spread">
                  <span className="action">{titleCase(e.action)}</span>
                  <span className="meta">{fmtTime(e.timestamp)}</span>
                </div>
                <div className="meta">
                  {e.actor ? `${e.actor} · ` : ''}
                  {e.asset_id ? `${e.asset_id} · ` : ''}
                  {e.recommendation_id ?? ''}
                </div>
                {e.detail ? <div>{e.detail}</div> : null}
                {e.note ? <div className="meta">Note: {e.note}</div> : null}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
