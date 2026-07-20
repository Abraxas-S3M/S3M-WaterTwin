import { useTranslation } from 'react-i18next';
import type { AuditEntry, DataProvenance } from '../api/types';
import { fmtTime, titleCase } from '../lib/format';
import { ProvenanceBadge } from './ProvenanceBadge';

interface Props {
  entries: AuditEntry[];
  provenance?: DataProvenance;
  loading?: boolean;
}

const actionColor: Record<string, string> = {
  recommendation_created: 'var(--audit-created)',
  recommendation_approved: 'var(--audit-approved)',
  recommendation_rejected: 'var(--audit-rejected)',
};

export function AuditTrail({ entries, provenance, loading }: Props) {
  const { t } = useTranslation();
  return (
    <div data-testid="audit-trail">
      {provenance ? (
        <div className="spread" style={{ marginBottom: 8 }}>
          <span className="card-sub">{t('audit.immutableRecord')}</span>
          <ProvenanceBadge provenance={provenance} />
        </div>
      ) : null}
      {loading ? (
        <div className="spinner">{t('audit.loading')}</div>
      ) : entries.length === 0 ? (
        <div className="empty">{t('audit.empty')}</div>
      ) : (
        <div className="audit-list">
          {entries.map((e) => (
            <div className="audit-entry" key={e.id}>
              <span
                className="dot"
                style={{ background: actionColor[e.action] ?? 'var(--audit-default)' }}
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
                {e.note ? <div className="meta">{t('audit.note', { note: e.note })}</div> : null}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
