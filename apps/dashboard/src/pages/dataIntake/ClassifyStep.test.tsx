import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ClassifyStep } from './ClassifyStep';
import type { IngestClassification } from '../../api/types';

const classification: IngestClassification = {
  upload_id: 'up-1',
  filename: 'demo.inp',
  sha256: 'a'.repeat(64),
  size_bytes: 500,
  suggested_class: 'epanet_inp',
  confidence: 0.92,
  detail: 'EPANET [TITLE]/[JUNCTIONS] sections detected.',
  supported_classes: ['epanet_inp', 'unknown'],
};

describe('ClassifyStep', () => {
  it('shows the sniffed class as a suggestion the user must confirm', async () => {
    const onConfirm = vi.fn();
    render(
      <ClassifyStep
        classification={classification}
        facilities={[{ id: 'FAC-ALPHA', name: 'SWRO Alpha' }]}
        entities={[{ id: 'asset', label: 'Asset hierarchy' }]}
        onConfirm={onConfirm}
      />,
    );

    expect(screen.getByTestId('ingest-suggested-class')).toBeInTheDocument();
    // Nothing advances until the user confirms.
    expect(onConfirm).not.toHaveBeenCalled();

    await userEvent.click(screen.getByTestId('ingest-confirm-class'));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onConfirm.mock.calls[0][0]).toBe('epanet_inp');
  });

  it('carries the chosen entity scope into the confirm callback', async () => {
    const onConfirm = vi.fn();
    render(
      <ClassifyStep
        classification={classification}
        facilities={[]}
        entities={[{ id: 'asset', label: 'Asset hierarchy' }]}
        onConfirm={onConfirm}
      />,
    );
    await userEvent.selectOptions(screen.getByTestId('ingest-entity-select'), 'asset');
    await userEvent.click(screen.getByTestId('ingest-confirm-class'));
    expect(onConfirm.mock.calls[0][1]).toEqual({ facility_id: null, entity: 'asset' });
  });
});
