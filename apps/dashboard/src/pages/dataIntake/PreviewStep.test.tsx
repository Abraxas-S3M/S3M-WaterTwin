import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PreviewStep } from './PreviewStep';
import type { IngestPreview } from '../../api/types';

const preview: IngestPreview = {
  upload_id: 'up-1',
  status: 'ready',
  suggested_class: 'epanet_inp',
  entity_counts: [
    { entity: 'asset', label: 'Assets', found: 12, matched: 8, added: 3, conflicts: 1 },
    { entity: 'tag_mapping', label: 'Tag mappings', found: 5, matched: 5, added: 0, conflicts: 0 },
  ],
  unparsed: [
    {
      line: 42,
      section: '[JUNCTIONS]',
      raw: 'J-BAD  ??? garbage',
      reason: 'Elevation is not a number; expected a numeric value in metres.',
    },
  ],
  diff: [],
};

describe('PreviewStep', () => {
  it('shows a pending state while the parse is running', () => {
    render(<PreviewStep preview={null} loading />);
    expect(screen.getByTestId('ingest-preview-pending')).toBeInTheDocument();
    expect(screen.queryByTestId('ingest-preview-step')).not.toBeInTheDocument();
  });

  it('renders entity counts, matches, new, conflicts and unparsed rows with reasons', () => {
    render(<PreviewStep preview={preview} />);
    expect(screen.getByTestId('ingest-count-asset')).toBeInTheDocument();
    expect(screen.getByTestId('ingest-count-tag_mapping')).toBeInTheDocument();

    // Unparsed rows carry a line number and a plain-language reason (never a
    // bare "parse failed").
    const unparsed = screen.getByTestId('ingest-unparsed-row-42');
    expect(unparsed).toHaveTextContent('42');
    expect(screen.getByTestId('ingest-unparsed-reason-42')).toHaveTextContent(
      /not a number/i,
    );
    expect(screen.queryByText(/^parse failed$/i)).not.toBeInTheDocument();
  });
});
