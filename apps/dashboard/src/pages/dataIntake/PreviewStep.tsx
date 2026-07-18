import { useTranslation } from 'react-i18next';
import type { IngestPreview } from '../../api/types';

interface Props {
  preview: IngestPreview | null;
  loading?: boolean;
}

/**
 * Step 3 — Preview. Async and resumable (the user may navigate away and
 * return). Shows what we found (entity counts), what matched (with confidence),
 * what is new, what conflicts, and what could not be parsed (line numbers +
 * plain-language reason). Never renders a bare "parse failed".
 */
export function PreviewStep({ preview, loading = false }: Props) {
  const { t } = useTranslation();

  if (loading || !preview || preview.status === 'pending') {
    return (
      <div className="card" data-testid="ingest-preview-pending">
        <div className="spinner">{t('dataIntake.preview.pending')}</div>
      </div>
    );
  }

  return (
    <div className="stack" data-testid="ingest-preview-step">
      <div className="card" data-testid="ingest-entity-counts">
        <h3>{t('dataIntake.preview.foundTitle')}</h3>
        <table className="data">
          <thead>
            <tr>
              <th>{t('dataIntake.preview.colEntity')}</th>
              <th>{t('dataIntake.preview.colFound')}</th>
              <th>{t('dataIntake.preview.colMatched')}</th>
              <th>{t('dataIntake.preview.colNew')}</th>
              <th>{t('dataIntake.preview.colConflicts')}</th>
            </tr>
          </thead>
          <tbody>
            {preview.entity_counts.map((c) => (
              <tr key={c.entity} data-testid={`ingest-count-${c.entity}`}>
                <td>{c.label}</td>
                <td>{c.found}</td>
                <td>{c.matched}</td>
                <td>{c.added}</td>
                <td className={c.conflicts > 0 ? 'status-chip rejected' : undefined}>
                  {c.conflicts}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card" data-testid="ingest-unparsed">
        <h3>{t('dataIntake.preview.unparsedTitle')}</h3>
        {preview.unparsed.length === 0 ? (
          <div className="empty" data-testid="ingest-unparsed-empty">
            {t('dataIntake.preview.unparsedNone')}
          </div>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>{t('dataIntake.preview.colLine')}</th>
                <th>{t('dataIntake.preview.colSection')}</th>
                <th>{t('dataIntake.preview.colReason')}</th>
                <th>{t('dataIntake.preview.colRaw')}</th>
              </tr>
            </thead>
            <tbody>
              {preview.unparsed.map((row) => (
                <tr key={row.line} data-testid={`ingest-unparsed-row-${row.line}`}>
                  <td>{row.line}</td>
                  <td className="muted">{row.section}</td>
                  <td data-testid={`ingest-unparsed-reason-${row.line}`}>{row.reason}</td>
                  <td>
                    <code>{row.raw}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
