import type { AssetHierarchyNode, Criticality } from '../../api/types';
import {
  CellInput,
  PanelShell,
  RemoveButton,
  removeRow,
  updateRow,
  type PanelProps,
} from './panelKit';

const CRITICALITIES: Criticality[] = ['low', 'medium', 'high', 'critical'];

const EMPTY_NODE: AssetHierarchyNode = {
  asset_id: '',
  name: '',
  asset_type: 'sensor',
  parent_id: null,
  treatment_stage: null,
  criticality: 'medium',
};

export function AssetHierarchyPanel({ rows, readOnly, onChange }: PanelProps<AssetHierarchyNode>) {
  return (
    <PanelShell
      testId="admin-panel-asset-hierarchy"
      title="Asset Hierarchy"
      description="Canonical asset tree: identifiers, parent linkage, treatment stage, and criticality."
      readOnly={readOnly}
      onAdd={() => onChange([...rows, { ...EMPTY_NODE }])}
      addLabel="Add asset"
    >
      <table className="data">
        <thead>
          <tr>
            <th>Asset ID</th>
            <th>Name</th>
            <th>Type</th>
            <th>Parent</th>
            <th>Stage</th>
            <th>Criticality</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={7} className="empty">
                No assets configured.
              </td>
            </tr>
          ) : (
            rows.map((node, i) => (
              <tr key={`${node.asset_id}-${i}`}>
                <td>
                  <CellInput
                    ariaLabel={`asset-id-${i}`}
                    value={node.asset_id}
                    readOnly={readOnly}
                    onChange={(v) => onChange(updateRow(rows, i, { asset_id: v }))}
                  />
                </td>
                <td>
                  <CellInput
                    ariaLabel={`asset-name-${i}`}
                    value={node.name}
                    readOnly={readOnly}
                    onChange={(v) => onChange(updateRow(rows, i, { name: v }))}
                  />
                </td>
                <td>
                  <CellInput
                    ariaLabel={`asset-type-${i}`}
                    value={node.asset_type}
                    readOnly={readOnly}
                    onChange={(v) =>
                      onChange(updateRow(rows, i, { asset_type: v as AssetHierarchyNode['asset_type'] }))
                    }
                  />
                </td>
                <td>
                  <CellInput
                    ariaLabel={`asset-parent-${i}`}
                    value={node.parent_id ?? ''}
                    placeholder="(root)"
                    readOnly={readOnly}
                    onChange={(v) => onChange(updateRow(rows, i, { parent_id: v || null }))}
                  />
                </td>
                <td>
                  <CellInput
                    ariaLabel={`asset-stage-${i}`}
                    value={node.treatment_stage ?? ''}
                    placeholder="—"
                    readOnly={readOnly}
                    onChange={(v) =>
                      onChange(
                        updateRow(rows, i, {
                          treatment_stage: (v || null) as AssetHierarchyNode['treatment_stage'],
                        }),
                      )
                    }
                  />
                </td>
                <td>
                  <select
                    className="input admin-cell"
                    aria-label={`asset-criticality-${i}`}
                    value={node.criticality}
                    disabled={readOnly}
                    onChange={(e) =>
                      onChange(updateRow(rows, i, { criticality: e.target.value as Criticality }))
                    }
                  >
                    {CRITICALITIES.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <RemoveButton
                    readOnly={readOnly}
                    label={`remove-asset-${i}`}
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
