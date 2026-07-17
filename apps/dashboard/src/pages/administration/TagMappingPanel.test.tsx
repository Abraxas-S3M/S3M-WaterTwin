import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TagMappingPanel } from './TagMappingPanel';
import { configDocument } from '../../test/fixtures';

describe('TagMappingPanel', () => {
  it('renders customer-tag -> canonical mappings with scale/offset/sampling', () => {
    render(
      <TagMappingPanel rows={configDocument.tag_mappings} readOnly={false} onChange={() => {}} />,
    );
    expect(screen.getByTestId('admin-panel-tag-mapping')).toBeInTheDocument();
    expect(screen.getByLabelText('tag-customer-0')).toHaveValue('PLC1.HPP01.WINDING_TEMP');
    expect(screen.getByLabelText('tag-metric-0')).toHaveValue('winding_temp_c');
    expect(screen.getByLabelText('tag-scale-1')).toHaveValue(0.1);
    expect(screen.getByLabelText('tag-sampling-0')).toHaveValue(5);
  });

  it('edits the scale factor', async () => {
    const onChange = vi.fn();
    render(<TagMappingPanel rows={configDocument.tag_mappings} readOnly={false} onChange={onChange} />);
    await userEvent.type(screen.getByLabelText('tag-offset-0'), '2');
    expect(onChange).toHaveBeenCalled();
  });

  it('is read-only for non-admin roles', () => {
    render(<TagMappingPanel rows={configDocument.tag_mappings} readOnly onChange={() => {}} />);
    expect(screen.getByLabelText('tag-customer-0')).toBeDisabled();
    expect(screen.queryByTestId('admin-panel-tag-mapping-add')).not.toBeInTheDocument();
  });
});
