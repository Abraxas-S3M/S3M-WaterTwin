import { useTranslation } from 'react-i18next';
import type { IngestDiffRow, IngestSubmitResult } from '../../api/types';

interface Props {
  acceptedRows: IngestDiffRow[];
  rejectedCount: number;
  result: IngestSubmitResult | null;
  submitting: boolean;
  error?: string | null;
  onSubmit: () => void;
}

/**
 * Step 5 — Submit. Accepted rows POST to the ingest submit endpoint, which
 * creates a draft via watertwin-api's EXISTING configuration lifecycle. This
 * component never approves anything: separation of duties is enforced
 * server-side and merely reflected here.
 */
export function SubmitStep({
  acceptedRows,
  rejectedCount,
  result,
  submitting,
  error,
  onSubmit,
}: Props) {
  const { t } = useTranslation();

  if (result) {
    return (
      <div className="stack" data-testid="ingest-submit-result">
        <div className="card">
          <h3>{t('dataIntake.submit.submittedTitle')}</h3>
          <p className="context">{result.message}</p>
          <table className="data">
            <thead>
              <tr>
                <th>{t('dataIntake.submit.colEntity')}</th>
                <th>{t('dataIntake.submit.colConfigId')}</th>
                <th>{t('dataIntake.submit.colVersion')}</th>
                <th>{t('dataIntake.submit.colStatus')}</th>
              </tr>
            </thead>
            <tbody>
              {result.created_versions.map((v) => (
                <tr key={v.version_id} data-testid={`ingest-created-${v.entity}-${v.config_id}`}>
                  <td>{v.entity}</td>
                  <td>{v.config_id}</td>
                  <td>v{v.version}</td>
                  <td>
                    <span className="status-chip">{v.status}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {result.requires_separate_approver ? (
          <div className="card" role="status" data-testid="ingest-sod-notice">
            <h3>{t('dataIntake.submit.sodTitle')}</h3>
            <p>{t('dataIntake.submit.sodBody')}</p>
            {result.blocked_entities.length > 0 ? (
              <p className="muted" data-testid="ingest-sod-entities">
                {result.blocked_entities.join(', ')}
              </p>
            ) : null}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="stack" data-testid="ingest-submit-step">
      <div className="card">
        <h3>{t('dataIntake.submit.reviewTitle')}</h3>
        <p className="context" data-testid="ingest-submit-summary">
          {t('dataIntake.submit.summary', {
            accepted: acceptedRows.length,
            rejected: rejectedCount,
          })}
        </p>
        {acceptedRows.length === 0 ? (
          <div className="empty" data-testid="ingest-submit-empty">
            {t('dataIntake.submit.nothingAccepted')}
          </div>
        ) : (
          <ul data-testid="ingest-submit-list">
            {acceptedRows.map((r) => (
              <li key={r.row_id} data-testid={`ingest-submit-accepted-${r.row_id}`}>
                {r.entity} · {r.config_id} · {r.field} → <strong>{r.proposed_value}</strong>
              </li>
            ))}
          </ul>
        )}
      </div>

      {error ? (
        <div className="card error" role="alert" data-testid="ingest-submit-error">
          {error}
        </div>
      ) : null}

      <div className="btn-row">
        <button
          type="button"
          className="btn primary"
          data-testid="ingest-submit-button"
          disabled={submitting || acceptedRows.length === 0}
          onClick={onSubmit}
        >
          {submitting ? t('dataIntake.submit.submitting') : t('dataIntake.submit.submit')}
        </button>
      </div>
    </div>
  );
}
