import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DiffTable, type DiffDecision } from './DiffTable';
import type { IngestDiffGroup } from '../../api/types';

const groups: IngestDiffGroup[] = [
  {
    panel: 'asset-hierarchy',
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
        provenance: 'preliminary',
        change_type: 'update',
        match_confidence: 0.95,
        safety_relevant: true,
      },
    ],
  },
  {
    panel: 'tag-mapping',
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
        provenance: 'measured',
        change_type: 'new',
        match_confidence: 1,
        safety_relevant: false,
      },
    ],
  },
];

function renderTable(
  decisions: Record<string, DiffDecision> = {},
  handlers: Partial<Parameters<typeof DiffTable>[0]> = {},
) {
  return render(
    <DiffTable
      groups={groups}
      decisions={decisions}
      onAccept={handlers.onAccept ?? vi.fn()}
      onReject={handlers.onReject ?? vi.fn()}
      onBulkAccept={handlers.onBulkAccept ?? vi.fn()}
    />,
  );
}

describe('DiffTable', () => {
  it('renders rows grouped by workbench panel with nothing pre-accepted', () => {
    renderTable();
    expect(screen.getByTestId('ingest-diff-group-asset-hierarchy')).toBeInTheDocument();
    expect(screen.getByTestId('ingest-diff-group-tag-mapping')).toBeInTheDocument();
    // Nothing is pre-accepted.
    expect(screen.getByTestId('ingest-accept-r1')).not.toBeChecked();
    expect(screen.getByTestId('ingest-accept-r2')).not.toBeChecked();
    // Safety-relevant rows are flagged.
    expect(screen.getByTestId('ingest-safety-flag-r1')).toBeInTheDocument();
  });

  it('accepts a row and bulk-accepts a group', async () => {
    const onAccept = vi.fn();
    const onBulkAccept = vi.fn();
    renderTable({}, { onAccept, onBulkAccept });
    await userEvent.click(screen.getByTestId('ingest-accept-r1'));
    expect(onAccept).toHaveBeenCalledWith('r1');
    await userEvent.click(screen.getByTestId('ingest-bulk-accept-tag-mapping'));
    expect(onBulkAccept).toHaveBeenCalledWith(['r2']);
  });

  it('requires a reason before a rejection is recorded', async () => {
    const onReject = vi.fn();
    renderTable({}, { onReject });
    await userEvent.click(screen.getByTestId('ingest-reject-r1'));

    // Confirm is disabled until a reason is entered — nothing recorded yet.
    const confirm = screen.getByTestId('ingest-reject-confirm-r1');
    expect(confirm).toBeDisabled();
    await userEvent.click(confirm);
    expect(onReject).not.toHaveBeenCalled();

    await userEvent.type(screen.getByTestId('ingest-reject-reason-r1'), 'wrong asset');
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    expect(onReject).toHaveBeenCalledWith('r1', 'wrong asset');
  });

  it('matches the grouped diff snapshot', () => {
    const { container } = renderTable();
    expect(container).toMatchSnapshot();
  });
});
