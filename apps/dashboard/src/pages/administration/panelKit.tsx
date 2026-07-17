// Shared building blocks for the Configuration Workbench panels. Each panel
// edits one slice of the config draft. In read-only mode (non-admin roles)
// every input is disabled and the add/remove affordances are hidden.

import type { ChangeEvent, ReactNode } from 'react';

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
  return (
    <div className="card admin-panel" data-testid={testId}>
      <div className="admin-panel-head">
        <div>
          <h3>{title}</h3>
          <div className="card-sub">{description}</div>
        </div>
        {onAdd && !readOnly ? (
          <button type="button" className="btn primary" onClick={onAdd} data-testid={`${testId}-add`}>
            {addLabel}
          </button>
        ) : null}
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
