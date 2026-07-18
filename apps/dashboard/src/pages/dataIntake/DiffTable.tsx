import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ProvenanceBadge } from '../../components/ProvenanceBadge';
import type { IngestDiffGroup, IngestDiffRow } from '../../api/types';

export interface DiffDecision {
  accepted: boolean;
  rejectReason: string | null;
}

interface Props {
  groups: IngestDiffGroup[];
  decisions: Record<string, DiffDecision>;
  readOnly?: boolean;
  onAccept: (rowId: string) => void;
  onReject: (rowId: string, reason: string) => void;
  onBulkAccept: (rowIds: string[]) => void;
}

function decisionState(d: DiffDecision | undefined): 'accepted' | 'rejected' | 'undecided' {
  if (!d) return 'undecided';
  return d.accepted ? 'accepted' : 'rejected';
}

/**
 * Step 4 — Diff. Field-level table GROUPED BY WORKBENCH PANEL so the shape is
 * familiar. Columns: current value, proposed value, source ref, provenance
 * badge, accept/reject toggle. Bulk accept per group. Rejecting requires a
 * reason, which is recorded. Nothing is pre-accepted.
 */
export function DiffTable({
  groups,
  decisions,
  readOnly = false,
  onAccept,
  onReject,
  onBulkAccept,
}: Props) {
  const { t } = useTranslation();
  const [rejecting, setRejecting] = useState<string | null>(null);
  const [reasonText, setReasonText] = useState('');

  const startReject = (rowId: string) => {
    setRejecting(rowId);
    setReasonText('');
  };

  const confirmReject = (rowId: string) => {
    const reason = reasonText.trim();
    if (!reason) return; // reason is required — nothing recorded without it
    onReject(rowId, reason);
    setRejecting(null);
    setReasonText('');
  };

  if (groups.length === 0) {
    return (
      <div className="empty" data-testid="ingest-diff-empty">
        {t('dataIntake.diff.empty')}
      </div>
    );
  }

  return (
    <div className="stack" data-testid="ingest-diff-table">
      {groups.map((group) => (
        <div
          className="card"
          key={group.panel}
          data-testid={`ingest-diff-group-${group.panel}`}
        >
          <div className="page-header">
            <h3>{group.label}</h3>
            {!readOnly ? (
              <button
                type="button"
                className="btn"
                data-testid={`ingest-bulk-accept-${group.panel}`}
                onClick={() => onBulkAccept(group.rows.map((r) => r.row_id))}
              >
                {t('dataIntake.diff.bulkAccept')}
              </button>
            ) : null}
          </div>
          <table className="data">
            <thead>
              <tr>
                <th>{t('dataIntake.diff.colField')}</th>
                <th>{t('dataIntake.diff.colCurrent')}</th>
                <th>{t('dataIntake.diff.colProposed')}</th>
                <th>{t('dataIntake.diff.colSource')}</th>
                <th>{t('dataIntake.diff.colProvenance')}</th>
                <th>{t('dataIntake.diff.colDecision')}</th>
              </tr>
            </thead>
            <tbody>
              {group.rows.map((row: IngestDiffRow) => {
                const d = decisions[row.row_id];
                const state = decisionState(d);
                return (
                  <tr key={row.row_id} data-testid={`ingest-diff-row-${row.row_id}`}>
                    <td>
                      <div>{row.field}</div>
                      <div className="muted">{row.config_id}</div>
                      {row.safety_relevant ? (
                        <span
                          className="status-chip rejected"
                          data-testid={`ingest-safety-flag-${row.row_id}`}
                          title={t('dataIntake.diff.safetyTitle')}
                        >
                          {t('dataIntake.diff.safety')}
                        </span>
                      ) : null}
                    </td>
                    <td className="muted">{row.current_value ?? '—'}</td>
                    <td>
                      <strong>{row.proposed_value}</strong>
                    </td>
                    <td className="muted">
                      <code>{row.source_ref}</code>
                    </td>
                    <td>
                      <ProvenanceBadge provenance={row.provenance} />
                    </td>
                    <td>
                      {readOnly ? (
                        <span className="muted" data-testid={`ingest-decision-${row.row_id}`}>
                          {t(`dataIntake.diff.state.${state}`)}
                        </span>
                      ) : (
                        <div className="stack">
                          <label>
                            <input
                              type="checkbox"
                              data-testid={`ingest-accept-${row.row_id}`}
                              checked={state === 'accepted'}
                              onChange={() => onAccept(row.row_id)}
                            />{' '}
                            {t('dataIntake.diff.accept')}
                          </label>
                          {state === 'rejected' ? (
                            <span
                              className="status-chip rejected"
                              data-testid={`ingest-rejected-${row.row_id}`}
                              title={d?.rejectReason ?? ''}
                            >
                              {t('dataIntake.diff.rejectedWithReason')}
                            </span>
                          ) : rejecting === row.row_id ? (
                            <div className="stack">
                              <input
                                type="text"
                                data-testid={`ingest-reject-reason-${row.row_id}`}
                                aria-label={t('dataIntake.diff.reasonLabel')}
                                placeholder={t('dataIntake.diff.reasonPlaceholder')}
                                value={reasonText}
                                onChange={(e) => setReasonText(e.target.value)}
                              />
                              <button
                                type="button"
                                className="btn"
                                data-testid={`ingest-reject-confirm-${row.row_id}`}
                                disabled={reasonText.trim().length === 0}
                                onClick={() => confirmReject(row.row_id)}
                              >
                                {t('dataIntake.diff.rejectConfirm')}
                              </button>
                            </div>
                          ) : (
                            <button
                              type="button"
                              className="btn"
                              data-testid={`ingest-reject-${row.row_id}`}
                              onClick={() => startReject(row.row_id)}
                            >
                              {t('dataIntake.diff.reject')}
                            </button>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
