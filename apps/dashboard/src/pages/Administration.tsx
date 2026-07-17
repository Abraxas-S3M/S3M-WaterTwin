import { useEffect, useMemo, useRef, useState } from 'react';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { useCapabilities } from '../auth/useAuth';
import {
  useApproveConfig,
  useConfig,
  useConfigVersions,
  useRejectConfig,
  useSaveConfigDraft,
  useSubmitConfig,
} from '../hooks';
import { useDashboardStore } from '../state/store';
import type { ConfigDocument, ConfigDraftPayload } from '../api/types';
import { AssetHierarchyPanel } from './administration/AssetHierarchyPanel';
import { TagMappingPanel } from './administration/TagMappingPanel';
import { AlarmThresholdsPanel } from './administration/AlarmThresholdsPanel';
import { RatedEquipmentPanel } from './administration/RatedEquipmentPanel';
import { ProcessStagesPanel } from './administration/ProcessStagesPanel';
import { LabMethodsPanel } from './administration/LabMethodsPanel';
import { UserRolesPanel } from './administration/UserRolesPanel';
import { WorkflowStrip } from './administration/WorkflowStrip';

type TabId =
  | 'asset-hierarchy'
  | 'tag-mapping'
  | 'alarm-thresholds'
  | 'rated-equipment'
  | 'process-stages'
  | 'lab-methods'
  | 'user-roles';

const TABS: { id: TabId; label: string }[] = [
  { id: 'asset-hierarchy', label: 'Asset Hierarchy' },
  { id: 'tag-mapping', label: 'Tag Discovery & Mapping' },
  { id: 'alarm-thresholds', label: 'Alarm Thresholds' },
  { id: 'rated-equipment', label: 'Rated Equipment' },
  { id: 'process-stages', label: 'Process Stages & Sampling' },
  { id: 'lab-methods', label: 'Lab Methods & Compliance' },
  { id: 'user-roles', label: 'User Roles' },
];

function toDraft(config: ConfigDocument): ConfigDraftPayload {
  return {
    asset_hierarchy: config.asset_hierarchy,
    tag_mappings: config.tag_mappings,
    alarm_thresholds: config.alarm_thresholds,
    rated_equipment: config.rated_equipment,
    process_stages: config.process_stages,
    sampling_points: config.sampling_points,
    lab_methods: config.lab_methods,
    compliance_limits: config.compliance_limits,
    user_roles: config.user_roles,
  };
}

export function Administration() {
  const config = useConfig();
  const versions = useConfigVersions();
  const { administerConfig, approveConfig } = useCapabilities();
  const operator = useDashboardStore((s) => s.operatorName);

  const saveDraft = useSaveConfigDraft();
  const submit = useSubmitConfig();
  const approve = useApproveConfig();
  const reject = useRejectConfig();

  const [tab, setTab] = useState<TabId>('asset-hierarchy');
  const [draft, setDraft] = useState<ConfigDraftPayload | null>(null);
  const seededKey = useRef<string | null>(null);

  // Reseed the working draft whenever the server document changes (initial load
  // or after a save/submit/approve round-trip), but never clobber in-flight edits
  // for the same server revision.
  useEffect(() => {
    if (!config.data) return;
    const key = `${config.data.version}:${config.data.updated_at}:${config.data.status}`;
    if (seededKey.current === key) return;
    seededKey.current = key;
    setDraft(toDraft(config.data));
  }, [config.data]);

  const readOnly = !administerConfig;
  const busy =
    saveDraft.isPending || submit.isPending || approve.isPending || reject.isPending;

  const dirty = useMemo(() => {
    if (!draft || !config.data) return false;
    return JSON.stringify(draft) !== JSON.stringify(toDraft(config.data));
  }, [draft, config.data]);

  const mutationError =
    saveDraft.error || submit.error || approve.error || reject.error || null;

  if (config.isLoading || !draft || !config.data) {
    return <div className="spinner">Loading configuration…</div>;
  }

  if (config.isError) {
    return (
      <div className="card error" data-testid="admin-load-error">
        Failed to load configuration: {(config.error as Error)?.message ?? 'unknown error'}
      </div>
    );
  }

  const doc = config.data;
  const patch = <K extends keyof ConfigDraftPayload>(key: K, value: ConfigDraftPayload[K]) =>
    setDraft((prev) => (prev ? { ...prev, [key]: value } : prev));

  return (
    <div className="stack" data-testid="administration">
      <div className="page-header">
        <div>
          <h2>Administration / Configuration Workbench</h2>
          <div className="context">
            Central configuration for the digital twin. Non-admin roles have a{' '}
            <strong>read-only</strong> view; edits move through a draft → submit → approve change
            control workflow.
          </div>
        </div>
        <ProvenanceBadge provenance={doc.provenance} />
      </div>

      <WorkflowStrip
        status={doc.status}
        version={doc.version}
        updatedBy={doc.updated_by}
        updatedAt={doc.updated_at}
        dirty={dirty}
        busy={busy}
        canEdit={administerConfig}
        canApprove={approveConfig}
        versions={versions.data?.versions ?? []}
        onSaveDraft={() => saveDraft.mutate(draft)}
        onSubmit={() => submit.mutate({ actor: operator })}
        onApprove={() => approve.mutate({ actor: operator })}
        onReject={() => reject.mutate({ actor: operator })}
      />

      {mutationError ? (
        <div className="card error" data-testid="admin-action-error">
          {(mutationError as Error).message}
        </div>
      ) : null}

      <nav className="admin-tabs" aria-label="Configuration panels">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={`chip${tab === t.id ? ' active' : ''}`}
            aria-current={tab === t.id ? 'true' : undefined}
            data-testid={`admin-tab-${t.id}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === 'asset-hierarchy' && (
        <AssetHierarchyPanel
          rows={draft.asset_hierarchy}
          readOnly={readOnly}
          onChange={(rows) => patch('asset_hierarchy', rows)}
        />
      )}
      {tab === 'tag-mapping' && (
        <TagMappingPanel
          rows={draft.tag_mappings}
          readOnly={readOnly}
          onChange={(rows) => patch('tag_mappings', rows)}
        />
      )}
      {tab === 'alarm-thresholds' && (
        <AlarmThresholdsPanel
          rows={draft.alarm_thresholds}
          readOnly={readOnly}
          onChange={(rows) => patch('alarm_thresholds', rows)}
        />
      )}
      {tab === 'rated-equipment' && (
        <RatedEquipmentPanel
          rows={draft.rated_equipment}
          readOnly={readOnly}
          onChange={(rows) => patch('rated_equipment', rows)}
        />
      )}
      {tab === 'process-stages' && (
        <ProcessStagesPanel
          stages={draft.process_stages}
          samplingPoints={draft.sampling_points}
          readOnly={readOnly}
          onStagesChange={(rows) => patch('process_stages', rows)}
          onSamplingPointsChange={(rows) => patch('sampling_points', rows)}
        />
      )}
      {tab === 'lab-methods' && (
        <LabMethodsPanel
          labMethods={draft.lab_methods}
          complianceLimits={draft.compliance_limits}
          readOnly={readOnly}
          onLabMethodsChange={(rows) => patch('lab_methods', rows)}
          onComplianceLimitsChange={(rows) => patch('compliance_limits', rows)}
        />
      )}
      {tab === 'user-roles' && (
        <UserRolesPanel
          rows={draft.user_roles}
          readOnly={readOnly}
          onChange={(rows) => patch('user_roles', rows)}
        />
      )}
    </div>
  );
}
