// Shared building blocks for the Configuration Workbench panels. Each panel
// edits one slice of the config draft. In read-only mode (non-admin roles)
// every input is disabled and the add/remove affordances are hidden.

import type { ChangeEvent, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useDashboardStore } from '../../state/store';

// Maps each panel to the configuration entity its "Import from file" deep link
// pre-scopes Data Intake to. One pipeline, several doors.
const IMPORT_ENTITY_BY_TESTID: Record<string, string> = {
  'admin-panel-asset-hierarchy': 'asset',
  'admin-panel-tag-mapping': 'tag_mapping',
  'admin-panel-alarm-thresholds': 'alarm_threshold',
  'admin-panel-rated-equipment': 'rated_equipment',
  'admin-panel-process-stages': 'process_stage',
  'admin-panel-lab-methods': 'lab_method',
  'admin-panel-user-roles': 'user_role_assignment',
};

export interface PanelProps<T> {
  rows: T[];
  readOnly: boolean;
  onChange: (rows: T[]) => void;
}

interface CellInputProps {
  value: string | number;
  readOnly: boolean;
  onChange: (value: string) => void;
  type?: 'text' | 'number';
  ariaLabel: string;
  placeholder?: string;
  step?: string;
}

export function CellInput({
  value,
  readOnly,
  onChange,
  type = 'text',
  ariaLabel,
  placeholder,
  step,
}: CellInputProps) {
  return (
    <input
      className="input admin-cell"
      type={type}
      step={step}
      value={value}
      placeholder={placeholder}
      aria-label={ariaLabel}
      disabled={readOnly}
      onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
    />
  );
}

interface RemoveButtonProps {
  readOnly: boolean;
  onClick: () => void;
  label: string;
}

export function RemoveButton({ readOnly, onClick, label }: RemoveButtonProps) {
  if (readOnly) return <span className="muted">—</span>;
  return (
    <button
      type="button"
      className="btn ghost admin-remove"
      onClick={onClick}
      aria-label={label}
    >
      Remove
    </button>
  );
}

interface PanelShellProps {
  testId: string;
  title: string;
  description: string;
  readOnly: boolean;
  onAdd?: () => void;
  addLabel?: string;
  children: ReactNode;
}

export function PanelShell({
  testId,
  title,
  description,
  readOnly,
  onAdd,
  addLabel = 'Add row',
  children,
}: PanelShellProps) {
  const { t } = useTranslation();
  const openDataIntake = useDashboardStore((s) => s.openDataIntake);
  const importEntity = IMPORT_ENTITY_BY_TESTID[testId];
  return (
    <div className="card admin-panel" data-testid={testId}>
      <div className="admin-panel-head">
        <div>
          <h3>{title}</h3>
          <div className="card-sub">{description}</div>
        </div>
        <div className="btn-row">
          {importEntity && !readOnly ? (
            <button
              type="button"
              className="btn"
              onClick={() => openDataIntake(importEntity)}
              data-testid={`${testId}-import`}
            >
              {t('dataIntake.importFromFile')}
            </button>
          ) : null}
          {onAdd && !readOnly ? (
            <button
              type="button"
              className="btn primary"
              onClick={onAdd}
              data-testid={`${testId}-add`}
            >
              {addLabel}
            </button>
          ) : null}
        </div>
      </div>
      {children}
    </div>
  );
}

// Convenience helpers to update one row in an immutable array of records.
export function updateRow<T>(rows: T[], index: number, patch: Partial<T>): T[] {
  return rows.map((row, i) => (i === index ? { ...row, ...patch } : row));
}

export function removeRow<T>(rows: T[], index: number): T[] {
  return rows.filter((_, i) => i !== index);
}

export function toNumber(value: string): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}
