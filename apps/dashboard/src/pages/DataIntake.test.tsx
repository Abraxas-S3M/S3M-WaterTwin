import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import i18n from '../i18n';
import { useAuthStore } from '../auth/store';

// The Data Intake container is driven entirely by the ingest client hooks; mock
// them so the five-state flow and role gating can be exercised deterministically.
vi.mock('../api/ingest', () => ({
  ingestApi: {
    originalDownloadUrl: (id: string) => `/api/v1/ingest/uploads/${id}/original`,
  },
  useIngestStatus: vi.fn(),
  useIngestOnboarding: vi.fn(),
  useIngestHistory: vi.fn(),
  useClassifyUpload: vi.fn(),
  useIngestPreview: vi.fn(),
  useSubmitIngest: vi.fn(),
}));

import * as ingest from '../api/ingest';
import { DataIntake } from './DataIntake';

const controlBoundary = {
  control_mode: 'advisory' as const,
  operator_approval_required: true,
  control_write_enabled: false,
};

const statusAvailable = {
  available: true,
  enabled: true,
  deployment_profile: 'full',
  accepted_types: [
    { extension: '.inp', label: 'EPANET network model', max_bytes: 1_000_000 },
  ],
  control_boundary: controlBoundary,
};

const classification = {
  upload_id: 'up-1',
  filename: 'demo.inp',
  sha256: 'a'.repeat(64),
  size_bytes: 500,
  suggested_class: 'epanet_inp' as const,
  confidence: 0.92,
  detail: 'EPANET sections detected.',
  supported_classes: ['epanet_inp' as const, 'unknown' as const],
};

const previewReady = {
  upload_id: 'up-1',
  status: 'ready' as const,
  suggested_class: 'epanet_inp' as const,
  entity_counts: [
    { entity: 'asset', label: 'Assets', found: 3, matched: 1, added: 2, conflicts: 0 },
  ],
  unparsed: [
    { line: 9, section: '[JUNCTIONS]', raw: 'J ??', reason: 'Elevation is not a number.' },
  ],
  diff: [
    {
      panel: 'asset-hierarchy' as const,
      label: 'Asset Hierarchy',
      rows: [
        {
          row_id: 'r1',
          entity: 'asset',
          config_id: 'AST-HPP-01',
          field: 'name',
          current_value: 'Pump A',
          proposed_value: 'High-Pressure Pump A',
          source_ref: '[JUNCTIONS] line 12',
          provenance: 'preliminary' as const,
          change_type: 'update' as const,
          match_confidence: 0.95,
          safety_relevant: true,
        },
      ],
    },
    {
      panel: 'tag-mapping' as const,
      label: 'Tag Mapping',
      rows: [
        {
          row_id: 'r2',
          entity: 'tag_mapping',
          config_id: 'TAG-1',
          field: 'unit',
          current_value: null,
          proposed_value: 'bar',
          source_ref: '[TAGS] line 3',
          provenance: 'measured' as const,
          change_type: 'new' as const,
          match_confidence: 1,
          safety_relevant: false,
        },
      ],
    },
  ],
};

const emptyHistory = { items: [], control_boundary: controlBoundary };
const onboardingComplete = { has_assets: true, progress: 100, checklist: [] };

const mutateAsync = vi.fn();
const submitMock = vi.fn();

function setRoles(roles: string[]) {
  useAuthStore.setState({
    status: 'authenticated',
    username: 'erin',
    roles,
    accessToken: 't',
    refreshToken: null,
    expiresAt: null,
    tenantId: 'TEN-ACME',
    facilityIds: [],
    error: null,
  });
}

function makeFile(name: string, size: number): File {
  const file = new File(['[TITLE]\n[JUNCTIONS]\n'], name, { type: 'text/plain' });
  Object.defineProperty(file, 'size', { value: size });
  return file;
}

/* eslint-disable @typescript-eslint/no-explicit-any */
beforeEach(() => {
  mutateAsync.mockReset().mockResolvedValue(classification);
  submitMock.mockReset();
  vi.mocked(ingest.useIngestStatus).mockReturnValue({
    data: statusAvailable,
    isLoading: false,
  } as any);
  vi.mocked(ingest.useIngestOnboarding).mockReturnValue({ data: onboardingComplete } as any);
  vi.mocked(ingest.useIngestHistory).mockReturnValue({ data: emptyHistory } as any);
  vi.mocked(ingest.useClassifyUpload).mockReturnValue({
    mutateAsync,
    isPending: false,
    data: classification,
  } as any);
  vi.mocked(ingest.useIngestPreview).mockReturnValue({
    data: previewReady,
    isLoading: false,
  } as any);
  vi.mocked(ingest.useSubmitIngest).mockReturnValue({
    mutate: submitMock,
    data: null,
    isPending: false,
    error: null,
  } as any);
});

async function driveToDiff() {
  await userEvent.upload(screen.getByTestId('ingest-file-input'), makeFile('demo.inp', 500));
  await waitFor(() => expect(screen.getByTestId('ingest-classify-step')).toBeInTheDocument());
  await userEvent.click(screen.getByTestId('ingest-confirm-class'));
  await waitFor(() => expect(screen.getByTestId('ingest-preview-step')).toBeInTheDocument());
  await userEvent.click(screen.getByTestId('ingest-goto-diff'));
  await waitFor(() => expect(screen.getByTestId('ingest-diff-table')).toBeInTheDocument());
}

describe('DataIntake', () => {
  describe('role gating', () => {
    it('gives engineers the full upload flow', () => {
      setRoles(['engineer']);
      render(<DataIntake />);
      expect(screen.getByTestId('data-intake')).toBeInTheDocument();
      expect(screen.getByTestId('ingest-dropzone-step')).toBeInTheDocument();
      expect(screen.queryByTestId('ingest-readonly-note')).not.toBeInTheDocument();
    });

    it('gives admins the full upload flow', () => {
      setRoles(['admin']);
      render(<DataIntake />);
      expect(screen.getByTestId('ingest-dropzone-step')).toBeInTheDocument();
    });

    it('gives operators a read-only view (history + provenance, no upload)', () => {
      setRoles(['operator']);
      render(<DataIntake />);
      expect(screen.getByTestId('ingest-readonly-note')).toBeInTheDocument();
      expect(screen.queryByTestId('ingest-dropzone-step')).not.toBeInTheDocument();
      expect(screen.getByTestId('ingest-upload-history')).toBeInTheDocument();
    });

    it('hides the page from viewers', () => {
      setRoles(['viewer']);
      render(<DataIntake />);
      expect(screen.getByTestId('ingest-no-access')).toBeInTheDocument();
    });

    it('hides the page from the security role', () => {
      setRoles(['security']);
      render(<DataIntake />);
      expect(screen.getByTestId('ingest-no-access')).toBeInTheDocument();
    });
  });

  it('shows a clear unavailable state when the ingest service is down (no crash)', () => {
    setRoles(['engineer']);
    vi.mocked(ingest.useIngestStatus).mockReturnValue({
      data: { ...statusAvailable, available: false },
      isLoading: false,
    } as any);
    render(<DataIntake />);
    expect(screen.getByTestId('ingest-unavailable')).toBeInTheDocument();
    expect(screen.queryByTestId('ingest-dropzone-step')).not.toBeInTheDocument();
  });

  it('requires the classification to be confirmed before the parse/preview', async () => {
    setRoles(['engineer']);
    render(<DataIntake />);
    await userEvent.upload(screen.getByTestId('ingest-file-input'), makeFile('demo.inp', 500));
    await waitFor(() => expect(screen.getByTestId('ingest-classify-step')).toBeInTheDocument());
    // Preview is not reachable until the user confirms the classification.
    expect(screen.queryByTestId('ingest-preview-step')).not.toBeInTheDocument();
    await userEvent.click(screen.getByTestId('ingest-confirm-class'));
    await waitFor(() => expect(screen.getByTestId('ingest-preview-step')).toBeInTheDocument());
  });

  it('submits only accepted rows', async () => {
    setRoles(['engineer']);
    render(<DataIntake />);
    await driveToDiff();
    // Accept only r1; leave r2 undecided.
    await userEvent.click(screen.getByTestId('ingest-accept-r1'));
    await userEvent.click(screen.getByTestId('ingest-goto-submit'));
    await userEvent.click(screen.getByTestId('ingest-submit-button'));

    expect(submitMock).toHaveBeenCalledTimes(1);
    const payload = submitMock.mock.calls[0][0];
    expect(payload.upload_id).toBe('up-1');
    expect(payload.actor).toBe('erin');
    expect(payload.decisions).toEqual([{ row_id: 'r1', accepted: true, reject_reason: null }]);
  });

  it('reflects a server-side self-approval block for safety-relevant entities', async () => {
    setRoles(['engineer']);
    vi.mocked(ingest.useSubmitIngest).mockReturnValue({
      mutate: submitMock,
      isPending: false,
      error: null,
      data: {
        upload_id: 'up-1',
        created_versions: [
          { entity: 'asset', config_id: 'AST-HPP-01', version: 8, version_id: 'v', status: 'submitted' },
        ],
        accepted_count: 1,
        rejected_count: 0,
        requires_separate_approver: true,
        self_approval_blocked: true,
        blocked_entities: ['asset'],
        message: 'Draft created; a separate approver is required.',
        control_boundary: controlBoundary,
      },
    } as any);

    render(<DataIntake />);
    await driveToDiff();
    await userEvent.click(screen.getByTestId('ingest-accept-r1'));
    await userEvent.click(screen.getByTestId('ingest-goto-submit'));
    expect(screen.getByTestId('ingest-sod-notice')).toBeInTheDocument();
  });

  it('lands a tenant with no assets on the onboarding checklist', () => {
    setRoles(['engineer']);
    vi.mocked(ingest.useIngestOnboarding).mockReturnValue({
      data: {
        has_assets: false,
        progress: 25,
        checklist: [
          { key: 'network_model', complete: false, count: 0 },
          { key: 'equipment_specs', complete: false, count: 0 },
          { key: 'tag_mapping', complete: false, count: 0 },
          { key: 'documents', complete: true, count: 2 },
        ],
      },
    } as any);
    render(<DataIntake />);
    expect(screen.getByTestId('ingest-onboarding')).toBeInTheDocument();
    expect(screen.getByTestId('ingest-onboarding-network_model')).toBeInTheDocument();
  });

  it('renders in Arabic (RTL) without breaking the layout', async () => {
    setRoles(['engineer']);
    await i18n.changeLanguage('ar');
    render(<DataIntake />);
    expect(screen.getByTestId('data-intake')).toBeInTheDocument();
    expect(screen.getByTestId('ingest-dropzone-step')).toBeInTheDocument();
    // Arabic strings are present (title translated, not the raw key).
    expect(screen.getByRole('heading', { name: 'استيعاب البيانات' })).toBeInTheDocument();
    await i18n.changeLanguage('en');
  });
});
/* eslint-enable @typescript-eslint/no-explicit-any */
