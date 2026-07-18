import { useCallback, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { IngestAcceptedType } from '../../api/types';

interface Props {
  acceptedTypes: IngestAcceptedType[];
  onFileSelected: (file: File) => void;
  disabled?: boolean;
}

function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot >= 0 ? name.slice(dot).toLowerCase() : '';
}

function formatBytes(bytes: number): string {
  if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(0)} MB`;
  if (bytes >= 1_000) return `${(bytes / 1_000).toFixed(0)} KB`;
  return `${bytes} B`;
}

/**
 * Step 1 — Drop. A drop zone PLUS a standard, keyboard-operable file picker
 * (drag-and-drop alone is not accessible). Runs a client-side extension/size
 * pre-check for fast feedback only; the server always re-validates.
 */
export function DropZone({ acceptedTypes, onFileSelected, disabled = false }: Props) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const accept = acceptedTypes.map((a) => a.extension).join(',');

  const precheck = useCallback(
    (file: File): void => {
      const ext = extensionOf(file.name);
      const match = acceptedTypes.find((a) => a.extension.toLowerCase() === ext);
      if (!match) {
        setError(t('dataIntake.drop.errorType', { ext: ext || file.name }));
        return;
      }
      if (file.size > match.max_bytes) {
        setError(
          t('dataIntake.drop.errorSize', {
            size: formatBytes(file.size),
            max: formatBytes(match.max_bytes),
          }),
        );
        return;
      }
      setError(null);
      onFileSelected(file);
    },
    [acceptedTypes, onFileSelected, t],
  );

  const openPicker = () => {
    if (!disabled) inputRef.current?.click();
  };

  return (
    <div className="stack" data-testid="ingest-dropzone-step">
      <p className="context" data-testid="ingest-review-notice">
        {t('dataIntake.drop.reviewNotice')}
      </p>

      <div
        className={`card ingest-dropzone${dragging ? ' dragging' : ''}`}
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        aria-label={t('dataIntake.drop.zoneLabel')}
        data-testid="ingest-dropzone"
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            openPicker();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (disabled) return;
          const file = e.dataTransfer.files?.[0];
          if (file) precheck(file);
        }}
      >
        <p>{t('dataIntake.drop.instruction')}</p>
        <button
          type="button"
          className="btn primary"
          data-testid="ingest-file-picker"
          onClick={openPicker}
          disabled={disabled}
        >
          {t('dataIntake.drop.chooseFile')}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          aria-label={t('dataIntake.drop.inputLabel')}
          data-testid="ingest-file-input"
          className="ingest-file-input"
          disabled={disabled}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) precheck(file);
            // Allow re-selecting the same file after a correction.
            e.target.value = '';
          }}
        />
      </div>

      {error ? (
        <div className="card error" role="alert" data-testid="ingest-drop-error">
          {error}
        </div>
      ) : null}

      <table className="data" data-testid="ingest-accepted-types">
        <caption className="muted">{t('dataIntake.drop.acceptedCaption')}</caption>
        <thead>
          <tr>
            <th>{t('dataIntake.drop.colType')}</th>
            <th>{t('dataIntake.drop.colExtension')}</th>
            <th>{t('dataIntake.drop.colMaxSize')}</th>
          </tr>
        </thead>
        <tbody>
          {acceptedTypes.map((a) => (
            <tr key={a.extension} data-testid={`ingest-accepted-${a.extension}`}>
              <td>{a.label}</td>
              <td>
                <code>{a.extension}</code>
              </td>
              <td className="muted">{formatBytes(a.max_bytes)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
