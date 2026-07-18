import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SubmitStep } from './SubmitStep';
import type { IngestDiffRow, IngestSubmitResult } from '../../api/types';

const acceptedRow: IngestDiffRow = {
  row_id: 'r1',
  entity: 'asset',
  config_id: 'AST-HPP-01',
  field: 'name',
  current_value: 'Pump A',
  proposed_value: 'High-Pressure Pump A',
  source_ref: '[JUNCTIONS] line 12',
  provenance: 'preliminary',
  change_type: 'update',
  match_confidence: 0.95,
  safety_relevant: true,
};

describe('SubmitStep', () => {
  it('disables submit when nothing is accepted and enables it otherwise', async () => {
    const onSubmit = vi.fn();
    const { rerender } = render(
      <SubmitStep
        acceptedRows={[]}
        rejectedCount={0}
        result={null}
        submitting={false}
        onSubmit={onSubmit}
      />,
    );
    expect(screen.getByTestId('ingest-submit-button')).toBeDisabled();

    rerender(
      <SubmitStep
        acceptedRows={[acceptedRow]}
        rejectedCount={1}
        result={null}
        submitting={false}
        onSubmit={onSubmit}
      />,
    );
    const button = screen.getByTestId('ingest-submit-button');
    expect(button).toBeEnabled();
    await userEvent.click(button);
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it('reflects a server-side separation-of-duties block after submission', () => {
    const result: IngestSubmitResult = {
      upload_id: 'up-1',
      created_versions: [
        {
          entity: 'asset',
          config_id: 'AST-HPP-01',
          version: 8,
          version_id: 'v-1',
          status: 'submitted',
        },
      ],
      accepted_count: 1,
      rejected_count: 0,
      requires_separate_approver: true,
      self_approval_blocked: true,
      blocked_entities: ['asset'],
      message: 'Draft created; a separate approver is required.',
      control_boundary: {
        control_mode: 'advisory',
        operator_approval_required: true,
        control_write_enabled: false,
      } as IngestSubmitResult['control_boundary'],
    };
    render(
      <SubmitStep
        acceptedRows={[acceptedRow]}
        rejectedCount={0}
        result={result}
        submitting={false}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByTestId('ingest-submit-result')).toBeInTheDocument();
    expect(screen.getByTestId('ingest-sod-notice')).toBeInTheDocument();
    expect(screen.getByTestId('ingest-created-asset-AST-HPP-01')).toBeInTheDocument();
  });
});
