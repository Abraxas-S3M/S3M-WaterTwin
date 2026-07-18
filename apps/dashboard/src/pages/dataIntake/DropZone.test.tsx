import { describe, it, expect, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DropZone } from './DropZone';
import type { IngestAcceptedType } from '../../api/types';

const accepted: IngestAcceptedType[] = [
  { extension: '.inp', label: 'EPANET network model', max_bytes: 1_000_000 },
];

function makeFile(name: string, size: number, type = 'text/plain'): File {
  const file = new File(['x'], name, { type });
  Object.defineProperty(file, 'size', { value: size });
  return file;
}

describe('DropZone', () => {
  it('states the review notice plainly and lists accepted types', () => {
    render(<DropZone acceptedTypes={accepted} onFileSelected={vi.fn()} />);
    expect(screen.getByTestId('ingest-review-notice')).toHaveTextContent(
      /Files are reviewed before anything changes\. Nothing is applied automatically\./i,
    );
    expect(screen.getByTestId('ingest-accepted-.inp')).toBeInTheDocument();
  });

  it('accepts a valid file via the keyboard-operable file picker', async () => {
    const onFileSelected = vi.fn();
    render(<DropZone acceptedTypes={accepted} onFileSelected={onFileSelected} />);

    // The picker is a real, focusable button (keyboard operable).
    const picker = screen.getByTestId('ingest-file-picker');
    expect(picker.tagName).toBe('BUTTON');
    picker.focus();
    expect(picker).toHaveFocus();

    const input = screen.getByTestId('ingest-file-input') as HTMLInputElement;
    await userEvent.upload(input, makeFile('demo.inp', 500));
    expect(onFileSelected).toHaveBeenCalledTimes(1);
    expect(onFileSelected.mock.calls[0][0].name).toBe('demo.inp');
  });

  it('accepts a valid file via drag-and-drop', () => {
    const onFileSelected = vi.fn();
    render(<DropZone acceptedTypes={accepted} onFileSelected={onFileSelected} />);
    const zone = screen.getByTestId('ingest-dropzone');
    fireEvent.drop(zone, { dataTransfer: { files: [makeFile('demo.inp', 500)] } });
    expect(onFileSelected).toHaveBeenCalledTimes(1);
  });

  it('rejects an unsupported extension client-side without calling back', () => {
    const onFileSelected = vi.fn();
    render(<DropZone acceptedTypes={accepted} onFileSelected={onFileSelected} />);
    // Drag-and-drop bypasses the input's `accept` filter, exercising the
    // client-side pre-check directly.
    const zone = screen.getByTestId('ingest-dropzone');
    fireEvent.drop(zone, { dataTransfer: { files: [makeFile('notes.txt', 100)] } });
    expect(onFileSelected).not.toHaveBeenCalled();
    expect(screen.getByTestId('ingest-drop-error')).toBeInTheDocument();
  });

  it('rejects an oversized file client-side', () => {
    const onFileSelected = vi.fn();
    render(<DropZone acceptedTypes={accepted} onFileSelected={onFileSelected} />);
    const zone = screen.getByTestId('ingest-dropzone');
    fireEvent.drop(zone, { dataTransfer: { files: [makeFile('big.inp', 5_000_000)] } });
    expect(onFileSelected).not.toHaveBeenCalled();
    expect(screen.getByTestId('ingest-drop-error')).toBeInTheDocument();
  });
});
