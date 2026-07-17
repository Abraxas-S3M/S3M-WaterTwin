import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { WorkflowStrip } from './WorkflowStrip';
import { configVersions } from '../../test/fixtures';

const baseProps = {
  status: 'submitted' as const,
  version: 7,
  updatedBy: 'config-admin',
  updatedAt: '2026-07-17T06:30:00Z',
  dirty: false,
  busy: false,
  versions: configVersions.versions,
  onSaveDraft: () => {},
  onSubmit: () => {},
  onApprove: () => {},
  onReject: () => {},
};

describe('WorkflowStrip', () => {
  it('renders status, version and version history', () => {
    render(<WorkflowStrip {...baseProps} canEdit canApprove />);
    expect(screen.getByTestId('admin-workflow-strip')).toBeInTheDocument();
    expect(screen.getByTestId('admin-config-status')).toHaveTextContent('Submitted');
    expect(screen.getByTestId('admin-config-version')).toHaveTextContent('v7');
    expect(screen.getByTestId('admin-version-history')).toBeInTheDocument();
    expect(screen.getByText(/Add boron ICP-OES method/)).toBeInTheDocument();
  });

  it('gates approve behind admin: enabled approve button for approvers on a submitted version', async () => {
    const onApprove = vi.fn();
    render(<WorkflowStrip {...baseProps} canEdit canApprove onApprove={onApprove} />);
    const approve = screen.getByTestId('admin-approve-button');
    expect(approve).toBeEnabled();
    expect(screen.queryByTestId('admin-approve-role-gate')).not.toBeInTheDocument();
    await userEvent.click(approve);
    expect(onApprove).toHaveBeenCalledTimes(1);
  });

  it('hides approve and shows a role gate for non-admin roles', () => {
    render(<WorkflowStrip {...baseProps} canEdit={false} canApprove={false} />);
    expect(screen.queryByTestId('admin-approve-button')).not.toBeInTheDocument();
    expect(screen.getByTestId('admin-approve-role-gate')).toBeInTheDocument();
    expect(screen.getByTestId('admin-readonly-note')).toBeInTheDocument();
  });

  it('disables approve when the version is not submitted', () => {
    render(<WorkflowStrip {...baseProps} status="draft" canEdit canApprove />);
    expect(screen.getByTestId('admin-approve-button')).toBeDisabled();
  });
});
