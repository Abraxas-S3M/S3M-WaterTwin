import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../auth/useAuth';
import { useDashboardStore } from '../state/store';
import {
  ingestApi,
  useClassifyUpload,
  useIngestHistory,
  useIngestOnboarding,
  useIngestPreview,
  useIngestStatus,
  useSubmitIngest,
} from '../api/ingest';
import type {
  IngestClass,
  IngestClassification,
  IngestDiffRow,
  IngestScope,
} from '../api/types';
import { DropZone } from './dataIntake/DropZone';
import { ClassifyStep } from './dataIntake/ClassifyStep';
import { PreviewStep } from './dataIntake/PreviewStep';
import { DiffTable, type DiffDecision } from './dataIntake/DiffTable';
import { SubmitStep } from './dataIntake/SubmitStep';
import { UploadHistory } from './dataIntake/UploadHistory';

type Step = 'drop' | 'classify' | 'preview' | 'diff' | 'submit';

const STEP_ORDER: Step[] = ['drop', 'classify', 'preview', 'diff', 'submit'];

const ENTITY_OPTIONS: { id: string; labelKey: string }[] = [
  { id: 'asset', labelKey: 'asset' },
  { id: 'tag_mapping', labelKey: 'tag_mapping' },
  { id: 'alarm_threshold', labelKey: 'alarm_threshold' },
  { id: 'rated_equipment', labelKey: 'rated_equipment' },
];

export function DataIntake() {
  const { t } = useTranslation();
  const { roles, username } = useAuth();
  const status = useIngestStatus();
  const entityScope = useDashboardStore((s) => s.ingestEntityScope);

  const isEngineerOrAdmin = roles.some((r) => r === 'engineer' || r === 'admin');
  const isOperator = roles.some((r) => r === 'operator');
  const isAdmin = roles.some((r) => r === 'admin');
  const hasAccess = isEngineerOrAdmin || isOperator;
  // Operators get a read-only history/provenance view and cannot upload.
  const readOnly = !isEngineerOrAdmin;

  const available = status.data?.available ?? false;
  const onboarding = useIngestOnboarding(hasAccess && available);
  const history = useIngestHistory(hasAccess && available);

  const [step, setStep] = useState<Step>('drop');
  const [classification, setClassification] = useState<IngestClassification | null>(null);
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [decisions, setDecisions] = useState<Record<string, DiffDecision>>({});

  const classify = useClassifyUpload();
  const preview = useIngestPreview(step === 'preview' || step === 'diff' ? uploadId : null);
  const submit = useSubmitIngest();

  const acceptedTypes = status.data?.accepted_types ?? [];

  const diffGroups = preview.data?.diff ?? [];
  const allRows = useMemo(
    () => diffGroups.flatMap((g) => g.rows),
    [diffGroups],
  );
  const acceptedRows: IngestDiffRow[] = useMemo(
    () => allRows.filter((r) => decisions[r.row_id]?.accepted),
    [allRows, decisions],
  );
  const rejectedCount = useMemo(
    () => allRows.filter((r) => decisions[r.row_id]?.accepted === false).length,
    [allRows, decisions],
  );

  // --- gating ---------------------------------------------------------------

  if (!hasAccess) {
    return (
      <div className="stack" data-testid="data-intake">
        <div className="page-header">
          <h2>{t('dataIntake.title')}</h2>
        </div>
        <div className="card">
          <div className="empty" data-testid="ingest-no-access">
            {t('dataIntake.noAccess')}
          </div>
        </div>
      </div>
    );
  }

  if (status.isLoading) {
    return (
      <div className="stack" data-testid="data-intake">
        <div className="spinner">{t('dataIntake.loading')}</div>
      </div>
    );
  }

  if (!available) {
    return (
      <div className="stack" data-testid="data-intake">
        <div className="page-header">
          <h2>{t('dataIntake.title')}</h2>
        </div>
        <div className="card" data-testid="ingest-unavailable">
          <h3>{t('dataIntake.unavailableTitle')}</h3>
          <p className="context">{t('dataIntake.unavailableBody')}</p>
        </div>
      </div>
    );
  }

  // --- handlers -------------------------------------------------------------

  const handleFile = async (file: File) => {
    const content = await file.text();
    const scope: IngestScope = { facility_id: null, entity: entityScope };
    const res = await classify.mutateAsync({
      filename: file.name,
      size_bytes: file.size,
      content,
      scope,
    });
    setClassification(res);
    setUploadId(res.upload_id);
    setDecisions({});
    setStep('classify');
  };

  const handleConfirmClass = (_confirmedClass: IngestClass, _scope: IngestScope) => {
    // Confirming the classification is the only way to reach the parse/preview.
    setStep('preview');
  };

  const acceptRow = (rowId: string) => {
    setDecisions((prev) => {
      const current = prev[rowId];
      // Toggle accept on/off; toggling accept clears any prior rejection.
      if (current?.accepted) {
        const next = { ...prev };
        delete next[rowId];
        return next;
      }
      return { ...prev, [rowId]: { accepted: true, rejectReason: null } };
    });
  };

  const rejectRow = (rowId: string, reason: string) => {
    setDecisions((prev) => ({ ...prev, [rowId]: { accepted: false, rejectReason: reason } }));
  };

  const bulkAccept = (rowIds: string[]) => {
    setDecisions((prev) => {
      const next = { ...prev };
      for (const id of rowIds) next[id] = { accepted: true, rejectReason: null };
      return next;
    });
  };

  const handleSubmit = () => {
    if (!uploadId) return;
    // Send every explicit decision. The server creates drafts ONLY for accepted
    // rows; recorded rejections carry their reason for the audit trail.
    const decisionList = Object.entries(decisions).map(([row_id, d]) => ({
      row_id,
      accepted: d.accepted,
      reject_reason: d.rejectReason,
    }));
    submit.mutate({ upload_id: uploadId, actor: username ?? 'operator', decisions: decisionList });
  };

  const downloadOriginal = (id: string) => {
    const anchor = document.createElement('a');
    anchor.href = ingestApi.originalDownloadUrl(id);
    anchor.download = '';
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  };

  const previewReady = preview.data?.status === 'ready';

  // --- render ---------------------------------------------------------------

  const showOnboarding = onboarding.data && !onboarding.data.has_assets;

  return (
    <div className="stack" data-testid="data-intake">
      <div className="page-header">
        <div>
          <h2>{t('dataIntake.title')}</h2>
          <div className="context">{t('dataIntake.subtitle')}</div>
        </div>
      </div>

      {showOnboarding ? (
        <div className="card" data-testid="ingest-onboarding">
          <h3>{t('dataIntake.onboarding.title')}</h3>
          <p className="context">{t('dataIntake.onboarding.body')}</p>
          <div
            className="onboarding-progress"
            data-testid="ingest-onboarding-progress"
            role="progressbar"
            aria-valuenow={onboarding.data?.progress ?? 0}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            {onboarding.data?.progress ?? 0}%
          </div>
          <ul>
            {(onboarding.data?.checklist ?? []).map((c) => (
              <li key={c.key} data-testid={`ingest-onboarding-${c.key}`}>
                <span className={`status-chip ${c.complete ? 'approved' : 'rejected'}`}>
                  {c.complete ? t('dataIntake.onboarding.done') : t('dataIntake.onboarding.todo')}
                </span>{' '}
                {t(`dataIntake.onboarding.items.${c.key}`)} ({c.count})
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {readOnly ? (
        <div className="card" data-testid="ingest-readonly-note">
          {t('dataIntake.readOnlyNote')}
        </div>
      ) : (
        <>
          <nav className="admin-tabs" aria-label={t('dataIntake.stepperLabel')}>
            {STEP_ORDER.map((s, idx) => (
              <span
                key={s}
                className={`chip${step === s ? ' active' : ''}`}
                data-testid={`ingest-step-${s}`}
                aria-current={step === s ? 'step' : undefined}
              >
                {idx + 1}. {t(`dataIntake.steps.${s}`)}
              </span>
            ))}
          </nav>

          {step === 'drop' ? (
            <DropZone
              acceptedTypes={acceptedTypes}
              onFileSelected={handleFile}
              disabled={classify.isPending}
            />
          ) : null}

          {step === 'classify' && classification ? (
            <ClassifyStep
              classification={classification}
              facilities={[]}
              entities={ENTITY_OPTIONS.map((e) => ({
                id: e.id,
                label: t(`dataIntake.entities.${e.labelKey}`),
              }))}
              initialScope={{ facility_id: null, entity: entityScope }}
              onConfirm={handleConfirmClass}
            />
          ) : null}

          {step === 'preview' ? (
            <div className="stack">
              <PreviewStep preview={preview.data ?? null} loading={preview.isLoading} />
              {previewReady ? (
                <div className="btn-row">
                  <button
                    type="button"
                    className="btn primary"
                    data-testid="ingest-goto-diff"
                    onClick={() => setStep('diff')}
                  >
                    {t('dataIntake.preview.continue')}
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}

          {step === 'diff' ? (
            <div className="stack">
              <DiffTable
                groups={diffGroups}
                decisions={decisions}
                onAccept={acceptRow}
                onReject={rejectRow}
                onBulkAccept={bulkAccept}
              />
              <div className="btn-row">
                <button
                  type="button"
                  className="btn primary"
                  data-testid="ingest-goto-submit"
                  onClick={() => setStep('submit')}
                >
                  {t('dataIntake.diff.continue')}
                </button>
              </div>
            </div>
          ) : null}

          {step === 'submit' ? (
            <SubmitStep
              acceptedRows={acceptedRows}
              rejectedCount={rejectedCount}
              result={submit.data ?? null}
              submitting={submit.isPending}
              error={submit.error ? (submit.error as Error).message : null}
              onSubmit={handleSubmit}
            />
          ) : null}
        </>
      )}

      <UploadHistory
        items={history.data?.items ?? []}
        canDownloadOriginal={isAdmin}
        onDownloadOriginal={downloadOriginal}
      />
    </div>
  );
}
