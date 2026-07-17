import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AssetHierarchyPanel } from './AssetHierarchyPanel';
import { configDocument } from '../../test/fixtures';

describe('AssetHierarchyPanel', () => {
  it('renders the asset hierarchy rows', () => {
    render(
      <AssetHierarchyPanel
        rows={configDocument.asset_hierarchy}
        readOnly={false}
        onChange={() => {}}
      />,
    );
    expect(screen.getByTestId('admin-panel-asset-hierarchy')).toBeInTheDocument();
    expect(screen.getByLabelText('asset-id-0')).toHaveValue('AST-HPP-01');
    expect(screen.getByLabelText('asset-name-1')).toHaveValue('RO Membrane Array (Train 1)');
  });

  it('adds a row when editable', async () => {
    const onChange = vi.fn();
    render(
      <AssetHierarchyPanel
        rows={configDocument.asset_hierarchy}
        readOnly={false}
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByTestId('admin-panel-asset-hierarchy-add'));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toHaveLength(configDocument.asset_hierarchy.length + 1);
  });

  it('is read-only for non-admin roles', () => {
    render(
      <AssetHierarchyPanel rows={configDocument.asset_hierarchy} readOnly onChange={() => {}} />,
    );
    expect(screen.getByLabelText('asset-id-0')).toBeDisabled();
    expect(screen.queryByTestId('admin-panel-asset-hierarchy-add')).not.toBeInTheDocument();
  });
});
