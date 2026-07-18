import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { UploadHistory } from './UploadHistory';
import type { IngestHistoryItem } from '../../api/types';

const items: IngestHistoryItem[] = [
  {
    upload_id: 'up-1',
    filename: 'network.inp',
    sha256: 'a'.repeat(64),
    uploader: 'erin-engineer',
    timestamp: '2026-07-18T08:00:00Z',
    upload_class: 'epanet_inp',
    status: 'approved',
    config_version: 8,
    approver: 'ada-admin',
  },
  {
    upload_id: 'up-2',
    filename: 'draft.inp',
    sha256: 'b'.repeat(64),
    uploader: 'sam-operator',
    timestamp: '2026-07-18T09:00:00Z',
    upload_class: 'epanet_inp',
    status: 'submitted',
    config_version: null,
    approver: null,
  },
];

describe('UploadHistory', () => {
  beforeEach(() => {
    Object.assign(navigator, { clipboard: { writeText: vi.fn() } });
  });

  it('renders each upload with a truncated, copyable sha and no download for non-admin', () => {
    render(<UploadHistory items={items} canDownloadOriginal={false} />);
    expect(screen.getByTestId('ingest-history-row-up-1')).toBeInTheDocument();
    expect(screen.getByTestId('ingest-history-row-up-2')).toBeInTheDocument();
    expect(screen.getByTestId('ingest-copy-sha-up-1')).toBeInTheDocument();
    expect(screen.queryByTestId('ingest-download-original-up-1')).not.toBeInTheDocument();
  });

  it('shows original download only for admins and calls back', async () => {
    const onDownloadOriginal = vi.fn();
    render(
      <UploadHistory
        items={items}
        canDownloadOriginal
        onDownloadOriginal={onDownloadOriginal}
      />,
    );
    await userEvent.click(screen.getByTestId('ingest-download-original-up-1'));
    expect(onDownloadOriginal).toHaveBeenCalledWith('up-1');
  });

  it('filters the list', async () => {
    render(<UploadHistory items={items} canDownloadOriginal={false} />);
    await userEvent.type(screen.getByTestId('ingest-history-filter'), 'sam-operator');
    expect(screen.queryByTestId('ingest-history-row-up-1')).not.toBeInTheDocument();
    expect(screen.getByTestId('ingest-history-row-up-2')).toBeInTheDocument();
  });
});
