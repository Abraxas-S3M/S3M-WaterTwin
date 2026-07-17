import type { AlarmThreshold } from '../../api/types';
import {
  CellInput,
  PanelShell,
  RemoveButton,
  removeRow,
  toNumber,
  updateRow,
  type PanelProps,
} from './panelKit';

const EMPTY_THRESHOLD: AlarmThreshold = {
  id: '',
  asset_id: '',
  metric: '',
  unit: '',
  warn_low: null,
  warn_high: null,
  alarm_low: null,
  alarm_high: null,
  enabled: true,
};

function numOrNull(v: string): number | null {
  return v.trim() === '' ? null : toNumber(v);
}

export function AlarmThresholdsPanel({ rows, readOnly, onChange }: PanelProps<AlarmThreshold>) {
  return (
    <PanelShell
      testId="admin-panel-alarm-thresholds"
      title="Alarm Thresholds"
      description="Per-metric warning and alarm bands. Advisory only — the platform issues no control writes."
      readOnly={readOnly}
      onAdd={() => onChange([...rows, { ...EMPTY_THRESHOLD, id: `THR-${rows.length + 1}` }])}
      addLabel="Add threshold"
    >
      <table className="data">
        <thead>
          <tr>
            <th>Asset</th>
            <th>Metric</th>
            <th>Unit</th>
            <th>Warn low</th>
            <th>Warn high</th>
            <th>Alarm low</th>
            <th>Alarm high</th>
            <th>Enabled</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={9} className="empty">
                No alarm thresholds configured.
              </td>
            </tr>
          ) : (
            rows.map((t, i) => (
              <tr key={`${t.id}-${i}`}>
                <td>
                  <CellInput
                    ariaLabel={`alarm-asset-${i}`}
                    value={t.asset_id}
                    readOnly={readOnly}
                    onChange={(v) => onChange(updateRow(rows, i, { asset_id: v }))}
                  />
                </td>
                <td>
                  <CellInput
                    ariaLabel={`alarm-metric-${i}`}
                    value={t.metric}
                    readOnly={readOnly}
                    onChange={(v) => onChange(updateRow(rows, i, { metric: v }))}
                  />
                </td>
                <td>
                  <CellInput
                    ariaLabel={`alarm-unit-${i}`}
                    value={t.unit}
                    readOnly={readOnly}
                    onChange={(v) => onChange(updateRow(rows, i, { unit: v }))}
                  />
                </td>
                <td>
                  <CellInput
                    ariaLabel={`alarm-warn-low-${i}`}
                    type="number"
                    step="any"
                    value={t.warn_low ?? ''}
                    readOnly={readOnly}
                    onChange={(v) => onChange(updateRow(rows, i, { warn_low: numOrNull(v) }))}
                  />
                </td>
                <td>
                  <CellInput
                    ariaLabel={`alarm-warn-high-${i}`}
                    type="number"
                    step="any"
                    value={t.warn_high ?? ''}
                    readOnly={readOnly}
                    onChange={(v) => onChange(updateRow(rows, i, { warn_high: numOrNull(v) }))}
                  />
                </td>
                <td>
                  <CellInput
                    ariaLabel={`alarm-alarm-low-${i}`}
                    type="number"
                    step="any"
                    value={t.alarm_low ?? ''}
                    readOnly={readOnly}
                    onChange={(v) => onChange(updateRow(rows, i, { alarm_low: numOrNull(v) }))}
                  />
                </td>
                <td>
                  <CellInput
                    ariaLabel={`alarm-alarm-high-${i}`}
                    type="number"
                    step="any"
                    value={t.alarm_high ?? ''}
                    readOnly={readOnly}
                    onChange={(v) => onChange(updateRow(rows, i, { alarm_high: numOrNull(v) }))}
                  />
                </td>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`alarm-enabled-${i}`}
                    checked={t.enabled}
                    disabled={readOnly}
                    onChange={(e) => onChange(updateRow(rows, i, { enabled: e.target.checked }))}
                  />
                </td>
                <td>
                  <RemoveButton
                    readOnly={readOnly}
                    label={`remove-alarm-${i}`}
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
