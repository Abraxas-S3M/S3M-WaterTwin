import type { UserRoleAssignment } from '../../api/types';
import { ALL_ROLES } from '../../auth/roles';
import { CellInput, PanelShell, RemoveButton, removeRow, updateRow, type PanelProps } from './panelKit';

const EMPTY_ASSIGNMENT: UserRoleAssignment = { username: '', roles: [] };

export function UserRolesPanel({ rows, readOnly, onChange }: PanelProps<UserRoleAssignment>) {
  const toggleRole = (i: number, role: string, checked: boolean) => {
    const current = new Set(rows[i].roles);
    if (checked) current.add(role);
    else current.delete(role);
    onChange(updateRow(rows, i, { roles: ALL_ROLES.filter((r) => current.has(r)) }));
  };

  return (
    <PanelShell
      testId="admin-panel-user-roles"
      title="User Roles"
      description="Role assignments mirrored on the client for UX gating. The API independently enforces RBAC on every request."
      readOnly={readOnly}
      onAdd={() => onChange([...rows, { ...EMPTY_ASSIGNMENT }])}
      addLabel="Add user"
    >
      <table className="data">
        <thead>
          <tr>
            <th>Username</th>
            {ALL_ROLES.map((r) => (
              <th key={r}>{r}</th>
            ))}
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={ALL_ROLES.length + 2} className="empty">
                No user role assignments configured.
              </td>
            </tr>
          ) : (
            rows.map((u, i) => (
              <tr key={`${u.username}-${i}`}>
                <td>
                  <CellInput
                    ariaLabel={`user-name-${i}`}
                    value={u.username}
                    readOnly={readOnly}
                    onChange={(v) => onChange(updateRow(rows, i, { username: v }))}
                  />
                </td>
                {ALL_ROLES.map((r) => (
                  <td key={r} style={{ textAlign: 'center' }}>
                    <input
                      type="checkbox"
                      aria-label={`user-${i}-role-${r}`}
                      checked={u.roles.includes(r)}
                      disabled={readOnly}
                      onChange={(e) => toggleRole(i, r, e.target.checked)}
                    />
                  </td>
                ))}
                <td>
                  <RemoveButton
                    readOnly={readOnly}
                    label={`remove-user-${i}`}
                    onClick={() => onChange(removeRow(rows, i))}
                  />
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </PanelShell>
  );
}
