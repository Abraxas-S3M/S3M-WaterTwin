import type { TagMapping } from '../../api/types';
import {
  CellInput,
  PanelShell,
  RemoveButton,
  removeRow,
  toNumber,
  updateRow,
  type PanelProps,
} from './panelKit';

const EMPTY_MAPPING: TagMapping = {
  customer_tag: '',
  asset_id: '',
  metric: '',
  unit: '',
  scale: 1,
  offset: 0,
  sampling_interval_s: 60,
  provenance: 'measured',
};

export function TagMappingPanel({ rows, readOnly, onChange }: PanelProps<TagMapping>) {
  return (
    <PanelShell
      testId="admin-panel-tag-mapping"
      title="Tag Discovery & Mapping"
      description="Map customer OT tags onto canonical asset_id.metric, with unit, scale, offset, and sampling interval (canonical = raw × scale + offset)."
      readOnly={readOnly}
      onAdd={() => onChange([...rows, { ...EMPTY_MAPPING }])}
      addLabel="Add mapping"
    >
      <table className="data">
        <thead>
          <tr>
            <th>Customer tag</th>
            <th>Canonical asset</th>
            <th>Metric</th>
            <th>Unit</th>
            <th>Scale</th>
            <th>Offset</th>
            <th>Sampling (s)</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={8} className="empty">
                No tag mappings configured.
              </td>
            </tr>
          ) : (
            rows.map((m, i) => (
              <tr key={`${m.customer_tag}-${i}`}>
                <td>
                  <CellInput
                    ariaLabel={`tag-customer-${i}`}
                    value={m.customer_tag}
                    readOnly={readOnly}
                    onChange={(v) => onChange(updateRow(rows, i, { customer_tag: v }))}
                  />
                </td>
                <td>
                  <CellInput
                    ariaLabel={`tag-asset-${i}`}
                    value={m.asset_id}
                    readOnly={readOnly}
                    onChange={(v) => onChange(updateRow(rows, i, { asset_id: v }))}
                  />
                </td>
                <td>
                  <CellInput
                    ariaLabel={`tag-metric-${i}`}
                    value={m.metric}
                    readOnly={readOnly}
                    onChange={(v) => onChange(updateRow(rows, i, { metric: v }))}
                  />
                </td>
                <td>
                  <CellInput
                    ariaLabel={`tag-unit-${i}`}
                    value={m.unit}
                    readOnly={readOnly}
                    onChange={(v) => onChange(updateRow(rows, i, { unit: v }))}
                  />
                </td>
                <td>
                  <CellInput
                    ariaLabel={`tag-scale-${i}`}
                    type="number"
                    step="any"
                    value={m.scale}
                    readOnly={readOnly}
                    onChange={(v) => onChange(updateRow(rows, i, { scale: toNumber(v) }))}
                  />
                </td>
                <td>
                  <CellInput
                    ariaLabel={`tag-offset-${i}`}
                    type="number"
                    step="any"
                    value={m.offset}
                    readOnly={readOnly}
                    onChange={(v) => onChange(updateRow(rows, i, { offset: toNumber(v) }))}
                  />
                </td>
                <td>
                  <CellInput
                    ariaLabel={`tag-sampling-${i}`}
                    type="number"
                    step="any"
                    value={m.sampling_interval_s}
                    readOnly={readOnly}
                    onChange={(v) =>
                      onChange(updateRow(rows, i, { sampling_interval_s: toNumber(v) }))
                    }
                  />
                </td>
                <td>
                  <RemoveButton
                    readOnly={readOnly}
                    label={`remove-tag-${i}`}
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
