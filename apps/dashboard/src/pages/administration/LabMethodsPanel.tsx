import type { ComplianceLimit, LabMethod } from '../../api/types';
import {
  CellInput,
  PanelShell,
  RemoveButton,
  removeRow,
  toNumber,
  updateRow,
} from './panelKit';

const EMPTY_METHOD: LabMethod = {
  method_id: '',
  name: '',
  analyte: '',
  technique: '',
  detection_limit: 0,
  unit: '',
};

const EMPTY_LIMIT: ComplianceLimit = {
  id: '',
  analyte: '',
  limit: 0,
  unit: '',
  basis: '',
  stage: null,
};

interface Props {
  labMethods: LabMethod[];
  complianceLimits: ComplianceLimit[];
  readOnly: boolean;
  onLabMethodsChange: (rows: LabMethod[]) => void;
  onComplianceLimitsChange: (rows: ComplianceLimit[]) => void;
}

export function LabMethodsPanel({
  labMethods,
  complianceLimits,
  readOnly,
  onLabMethodsChange,
  onComplianceLimitsChange,
}: Props) {
  return (
    <PanelShell
      testId="admin-panel-lab-methods"
      title="Lab Methods & Compliance Limits"
      description="Analytical methods (with detection limits) and the regulatory/compliance limits they are assessed against."
      readOnly={readOnly}
      onAdd={() => onLabMethodsChange([...labMethods, { ...EMPTY_METHOD }])}
      addLabel="Add method"
    >
      <div className="admin-subtable" data-testid="admin-lab-methods-table">
        <div className="card-sub">Lab methods</div>
        <table className="data">
          <thead>
            <tr>
              <th>Method ID</th>
              <th>Name</th>
              <th>Analyte</th>
              <th>Technique</th>
              <th>Detection limit</th>
              <th>Unit</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {labMethods.length === 0 ? (
              <tr>
                <td colSpan={7} className="empty">
                  No lab methods configured.
                </td>
              </tr>
            ) : (
              labMethods.map((m, i) => (
                <tr key={`${m.method_id}-${i}`}>
                  <td>
                    <CellInput
                      ariaLabel={`method-id-${i}`}
                      value={m.method_id}
                      readOnly={readOnly}
                      onChange={(v) => onLabMethodsChange(updateRow(labMethods, i, { method_id: v }))}
                    />
                  </td>
                  <td>
                    <CellInput
                      ariaLabel={`method-name-${i}`}
                      value={m.name}
                      readOnly={readOnly}
                      onChange={(v) => onLabMethodsChange(updateRow(labMethods, i, { name: v }))}
                    />
                  </td>
                  <td>
                    <CellInput
                      ariaLabel={`method-analyte-${i}`}
                      value={m.analyte}
                      readOnly={readOnly}
                      onChange={(v) => onLabMethodsChange(updateRow(labMethods, i, { analyte: v }))}
                    />
                  </td>
                  <td>
                    <CellInput
                      ariaLabel={`method-technique-${i}`}
                      value={m.technique}
                      readOnly={readOnly}
                      onChange={(v) => onLabMethodsChange(updateRow(labMethods, i, { technique: v }))}
                    />
                  </td>
                  <td>
                    <CellInput
                      ariaLabel={`method-detection-${i}`}
                      type="number"
                      step="any"
                      value={m.detection_limit}
                      readOnly={readOnly}
                      onChange={(v) =>
                        onLabMethodsChange(updateRow(labMethods, i, { detection_limit: toNumber(v) }))
                      }
                    />
                  </td>
                  <td>
                    <CellInput
                      ariaLabel={`method-unit-${i}`}
                      value={m.unit}
                      readOnly={readOnly}
                      onChange={(v) => onLabMethodsChange(updateRow(labMethods, i, { unit: v }))}
                    />
                  </td>
                  <td>
                    <RemoveButton
                      readOnly={readOnly}
                      label={`remove-method-${i}`}
                      onClick={() => onLabMethodsChange(removeRow(labMethods, i))}
                    />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="admin-subtable" data-testid="admin-compliance-limits-table">
        <div className="row admin-panel-head">
          <span className="card-sub">Compliance limits</span>
          {readOnly ? null : (
            <button
              type="button"
              className="btn ghost"
              data-testid="admin-add-compliance-limit"
              onClick={() => onComplianceLimitsChange([...complianceLimits, { ...EMPTY_LIMIT }])}
            >
              Add limit
            </button>
          )}
        </div>
        <table className="data">
          <thead>
            <tr>
              <th>ID</th>
              <th>Analyte</th>
              <th>Limit</th>
              <th>Unit</th>
              <th>Basis</th>
              <th>Stage</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {complianceLimits.length === 0 ? (
              <tr>
                <td colSpan={7} className="empty">
                  No compliance limits configured.
                </td>
              </tr>
            ) : (
              complianceLimits.map((c, i) => (
                <tr key={`${c.id}-${i}`}>
                  <td>
                    <CellInput
                      ariaLabel={`limit-id-${i}`}
                      value={c.id}
                      readOnly={readOnly}
                      onChange={(v) => onComplianceLimitsChange(updateRow(complianceLimits, i, { id: v }))}
                    />
                  </td>
                  <td>
                    <CellInput
                      ariaLabel={`limit-analyte-${i}`}
                      value={c.analyte}
                      readOnly={readOnly}
                      onChange={(v) =>
                        onComplianceLimitsChange(updateRow(complianceLimits, i, { analyte: v }))
                      }
                    />
                  </td>
                  <td>
                    <CellInput
                      ariaLabel={`limit-value-${i}`}
                      type="number"
                      step="any"
                      value={c.limit}
                      readOnly={readOnly}
                      onChange={(v) =>
                        onComplianceLimitsChange(updateRow(complianceLimits, i, { limit: toNumber(v) }))
                      }
                    />
                  </td>
                  <td>
                    <CellInput
                      ariaLabel={`limit-unit-${i}`}
                      value={c.unit}
                      readOnly={readOnly}
                      onChange={(v) =>
                        onComplianceLimitsChange(updateRow(complianceLimits, i, { unit: v }))
                      }
                    />
                  </td>
                  <td>
                    <CellInput
                      ariaLabel={`limit-basis-${i}`}
                      value={c.basis}
                      readOnly={readOnly}
                      onChange={(v) =>
                        onComplianceLimitsChange(updateRow(complianceLimits, i, { basis: v }))
                      }
                    />
                  </td>
                  <td>
                    <CellInput
                      ariaLabel={`limit-stage-${i}`}
                      value={c.stage ?? ''}
                      placeholder="—"
                      readOnly={readOnly}
                      onChange={(v) =>
                        onComplianceLimitsChange(
                          updateRow(complianceLimits, i, { stage: v || null }),
                        )
                      }
                    />
                  </td>
                  <td>
                    <RemoveButton
                      readOnly={readOnly}
                      label={`remove-limit-${i}`}
                      onClick={() => onComplianceLimitsChange(removeRow(complianceLimits, i))}
                    />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </PanelShell>
  );
}
