import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { IngestHistoryItem } from '../../api/types';

interface Props {
  items: IngestHistoryItem[];
  canDownloadOriginal: boolean;
  onDownloadOriginal?: (uploadId: string) => void;
}

function shortSha(sha: string): string {
  return sha.length > 12 ? `${sha.slice(0, 12)}…` : sha;
}

/**
 * History — a permanent, filterable list of every upload: filename, sha256
 * (truncated + copyable), uploader, timestamp, class, status, resulting config
 * version and approver. Original-file download is admin-only (enforced server
 * side; the button is only shown to admins here).
 */
export function UploadHistory({ items, canDownloadOriginal, onDownloadOriginal }: Props) {
  const { t } = useTranslation();
  const [filter, setFilter] = useState('');
  const [copied, setCopied] = useState<string | null>(null);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return items;
    return items.filter((i) =>
      [i.filename, i.uploader, i.status, i.upload_class, i.sha256]
        .join(' ')
        .toLowerCase()
        .includes(q),
    );
  }, [items, filter]);

  const copySha = (sha: string) => {
    void navigator.clipboard?.writeText(sha);
    setCopied(sha);
  };

  return (
    <div className="card" data-testid="ingest-upload-history">
      <div className="page-header">
        <h3>{t('dataIntake.history.title')}</h3>
        <input
          type="search"
          className="ingest-history-filter"
          data-testid="ingest-history-filter"
          aria-label={t('dataIntake.history.filterLabel')}
          placeholder={t('dataIntake.history.filterPlaceholder')}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>

      {filtered.length === 0 ? (
        <div className="empty" data-testid="ingest-history-empty">
          {t('dataIntake.history.empty')}
        </div>
      ) : (
        <table className="data">
          <thead>
            <tr>
              <th>{t('dataIntake.history.colFile')}</th>
              <th>{t('dataIntake.history.colSha')}</th>
              <th>{t('dataIntake.history.colUploader')}</th>
              <th>{t('dataIntake.history.colTime')}</th>
              <th>{t('dataIntake.history.colClass')}</th>
              <th>{t('dataIntake.history.colStatus')}</th>
              <th>{t('dataIntake.history.colVersion')}</th>
              <th>{t('dataIntake.history.colApprover')}</th>
              {canDownloadOriginal ? <th>{t('dataIntake.history.colOriginal')}</th> : null}
            </tr>
          </thead>
          <tbody>
            {filtered.map((i) => (
              <tr key={i.upload_id} data-testid={`ingest-history-row-${i.upload_id}`}>
                <td>{i.filename}</td>
                <td>
                  <code>{shortSha(i.sha256)}</code>{' '}
                  <button
                    type="button"
                    className="btn"
                    data-testid={`ingest-copy-sha-${i.upload_id}`}
                    aria-label={t('dataIntake.history.copySha')}
                    onClick={() => copySha(i.sha256)}
                  >
                    {copied === i.sha256
                      ? t('dataIntake.history.copied')
                      : t('dataIntake.history.copy')}
                  </button>
                </td>
                <td>{i.uploader}</td>
                <td className="muted">{i.timestamp}</td>
                <td>{t(`dataIntake.classes.${i.upload_class}`)}</td>
                <td>
                  <span className="status-chip" data-testid={`ingest-history-status-${i.upload_id}`}>
                    {t(`dataIntake.status.${i.status}`)}
                  </span>
                </td>
                <td>{i.config_version != null ? `v${i.config_version}` : '—'}</td>
                <td className="muted">{i.approver ?? '—'}</td>
                {canDownloadOriginal ? (
                  <td>
                    <button
                      type="button"
                      className="btn"
                      data-testid={`ingest-download-original-${i.upload_id}`}
                      onClick={() => onDownloadOriginal?.(i.upload_id)}
                    >
                      {t('dataIntake.history.download')}
                    </button>
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
