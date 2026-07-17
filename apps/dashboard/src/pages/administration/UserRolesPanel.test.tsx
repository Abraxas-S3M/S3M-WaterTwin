import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { UserRolesPanel } from './UserRolesPanel';
import { configDocument } from '../../test/fixtures';

describe('UserRolesPanel', () => {
  it('renders user role assignments', () => {
    render(
      <UserRolesPanel rows={configDocument.user_roles} readOnly={false} onChange={() => {}} />,
    );
    expect(screen.getByTestId('admin-panel-user-roles')).toBeInTheDocument();
    expect(screen.getByLabelText('user-name-0')).toHaveValue('alice');
    expect(screen.getByLabelText('user-0-role-admin')).toBeChecked();
    expect(screen.getByLabelText('user-2-role-viewer')).toBeChecked();
    expect(screen.getByLabelText('user-2-role-admin')).not.toBeChecked();
  });

  it('toggles a role when editable', async () => {
    const onChange = vi.fn();
    render(<UserRolesPanel rows={configDocument.user_roles} readOnly={false} onChange={onChange} />);
    await userEvent.click(screen.getByLabelText('user-2-role-operator'));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0][2].roles).toContain('operator');
  });

  it('is read-only for non-admin roles', () => {
    render(<UserRolesPanel rows={configDocument.user_roles} readOnly onChange={() => {}} />);
    expect(screen.getByLabelText('user-name-0')).toBeDisabled();
    expect(screen.getByLabelText('user-0-role-admin')).toBeDisabled();
    expect(screen.queryByTestId('admin-panel-user-roles-add')).not.toBeInTheDocument();
  });
});
