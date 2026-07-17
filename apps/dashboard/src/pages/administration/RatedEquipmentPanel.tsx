import type {
  RatedEquipment,
  RatedEquipmentType,
  RatedMembraneModel,
  RatedPumpCurvePoint,
} from '../../api/types';
import {
  CellInput,
  PanelShell,
  RemoveButton,
  removeRow,
  toNumber,
  updateRow,
  type PanelProps,
} from './panelKit';

const EMPTY_MEMBRANE: RatedMembraneModel = {
  model: '',
  element_area_m2: 37,
  elements_per_vessel: 7,
  nominal_salt_rejection_pct: 99.7,
  max_feed_pressure_bar: 83,
};

const EMPTY_EQUIPMENT: RatedEquipment = {
  asset_id: '',
  name: '',
  equipment_type: 'pump',
  pump_curve: [{ flow_m3h: 0, head_m: 0, efficiency_pct: 0 }],
  membrane_model: null,
};

function PumpCurveEditor({
  curve,
  readOnly,
  onChange,
  keyPrefix,
}: {
  curve: RatedPumpCurvePoint[];
  readOnly: boolean;
  onChange: (curve: RatedPumpCurvePoint[]) => void;
  keyPrefix: string;
}) {
  return (
    <div className="admin-subtable" data-testid={`${keyPrefix}-pump-curve`}>
      <div className="row admin-panel-head">
        <span className="card-sub">Pump curve (flow · head · efficiency)</span>
        {readOnly ? null : (
          <button
            type="button"
            className="btn ghost"
            aria-label={`${keyPrefix}-add-point`}
            onClick={() => onChange([...curve, { flow_m3h: 0, head_m: 0, efficiency_pct: 0 }])}
          >
            Add point
          </button>
        )}
      </div>
      <table className="data">
        <thead>
          <tr>
            <th>Flow (m³/h)</th>
            <th>Head (m)</th>
            <th>Efficiency (%)</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {curve.map((p, i) => (
            <tr key={i}>
              <td>
                <CellInput
                  ariaLabel={`${keyPrefix}-flow-${i}`}
                  type="number"
                  step="any"
                  value={p.flow_m3h}
                  readOnly={readOnly}
                  onChange={(v) => onChange(updateRow(curve, i, { flow_m3h: toNumber(v) }))}
                />
              </td>
              <td>
                <CellInput
                  ariaLabel={`${keyPrefix}-head-${i}`}
                  type="number"
                  step="any"
                  value={p.head_m}
                  readOnly={readOnly}
                  onChange={(v) => onChange(updateRow(curve, i, { head_m: toNumber(v) }))}
                />
              </td>
              <td>
                <CellInput
                  ariaLabel={`${keyPrefix}-eff-${i}`}
                  type="number"
                  step="any"
                  value={p.efficiency_pct}
                  readOnly={readOnly}
                  onChange={(v) => onChange(updateRow(curve, i, { efficiency_pct: toNumber(v) }))}
                />
              </td>
              <td>
                <RemoveButton
                  readOnly={readOnly}
                  label={`${keyPrefix}-remove-point-${i}`}
                  onClick={() => onChange(removeRow(curve, i))}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MembraneEditor({
  model,
  readOnly,
  onChange,
  keyPrefix,
}: {
  model: RatedMembraneModel;
  readOnly: boolean;
  onChange: (model: RatedMembraneModel) => void;
  keyPrefix: string;
}) {
  return (
    <div className="admin-subtable" data-testid={`${keyPrefix}-membrane-model`}>
      <div className="card-sub">Membrane model</div>
      <div className="grid cols-2">
        <label className="admin-field">
          <span>Model</span>
          <CellInput
            ariaLabel={`${keyPrefix}-membrane-model-name`}
            value={model.model}
            readOnly={readOnly}
            onChange={(v) => onChange({ ...model, model: v })}
          />
        </label>
        <label className="admin-field">
          <span>Element area (m²)</span>
          <CellInput
            ariaLabel={`${keyPrefix}-membrane-area`}
            type="number"
            step="any"
            value={model.element_area_m2}
            readOnly={readOnly}
            onChange={(v) => onChange({ ...model, element_area_m2: toNumber(v) })}
          />
        </label>
        <label className="admin-field">
          <span>Elements / vessel</span>
          <CellInput
            ariaLabel={`${keyPrefix}-membrane-elements`}
            type="number"
            step="any"
            value={model.elements_per_vessel}
            readOnly={readOnly}
            onChange={(v) => onChange({ ...model, elements_per_vessel: toNumber(v) })}
          />
        </label>
        <label className="admin-field">
          <span>Nominal salt rejection (%)</span>
          <CellInput
            ariaLabel={`${keyPrefix}-membrane-rejection`}
            type="number"
            step="any"
            value={model.nominal_salt_rejection_pct}
            readOnly={readOnly}
            onChange={(v) => onChange({ ...model, nominal_salt_rejection_pct: toNumber(v) })}
          />
        </label>
        <label className="admin-field">
          <span>Max feed pressure (bar)</span>
          <CellInput
            ariaLabel={`${keyPrefix}-membrane-pressure`}
            type="number"
            step="any"
            value={model.max_feed_pressure_bar}
            readOnly={readOnly}
            onChange={(v) => onChange({ ...model, max_feed_pressure_bar: toNumber(v) })}
          />
        </label>
      </div>
    </div>
  );
}

export function RatedEquipmentPanel({ rows, readOnly, onChange }: PanelProps<RatedEquipment>) {
  const setType = (i: number, type: RatedEquipmentType) => {
    const patch: Partial<RatedEquipment> =
      type === 'pump'
        ? { equipment_type: 'pump', membrane_model: null, pump_curve: rows[i].pump_curve ?? [] }
        : { equipment_type: 'membrane', pump_curve: null, membrane_model: rows[i].membrane_model ?? { ...EMPTY_MEMBRANE } };
    onChange(updateRow(rows, i, patch));
  };

  return (
    <PanelShell
      testId="admin-panel-rated-equipment"
      title="Rated Equipment"
      description="Design references used by the twin: pump curves and membrane element models."
      readOnly={readOnly}
      onAdd={() => onChange([...rows, { ...EMPTY_EQUIPMENT, pump_curve: [{ flow_m3h: 0, head_m: 0, efficiency_pct: 0 }] }])}
      addLabel="Add equipment"
    >
      {rows.length === 0 ? (
        <div className="empty">No rated equipment configured.</div>
      ) : (
        <div className="stack">
          {rows.map((eq, i) => {
            const keyPrefix = `rated-${i}`;
            return (
              <div key={`${eq.asset_id}-${i}`} className="admin-equipment" data-testid={keyPrefix}>
                <div className="grid cols-2">
                  <label className="admin-field">
                    <span>Asset ID</span>
                    <CellInput
                      ariaLabel={`${keyPrefix}-asset`}
                      value={eq.asset_id}
                      readOnly={readOnly}
                      onChange={(v) => onChange(updateRow(rows, i, { asset_id: v }))}
                    />
                  </label>
                  <label className="admin-field">
                    <span>Name</span>
                    <CellInput
                      ariaLabel={`${keyPrefix}-name`}
                      value={eq.name}
                      readOnly={readOnly}
                      onChange={(v) => onChange(updateRow(rows, i, { name: v }))}
                    />
                  </label>
                  <label className="admin-field">
                    <span>Type</span>
                    <select
                      className="input admin-cell"
                      aria-label={`${keyPrefix}-type`}
                      value={eq.equipment_type}
                      disabled={readOnly}
                      onChange={(e) => setType(i, e.target.value as RatedEquipmentType)}
                    >
                      <option value="pump">pump</option>
                      <option value="membrane">membrane</option>
                    </select>
                  </label>
                  <div className="admin-field" style={{ justifyContent: 'flex-end' }}>
                    <RemoveButton
                      readOnly={readOnly}
                      label={`${keyPrefix}-remove`}
                      onClick={() => onChange(removeRow(rows, i))}
                    />
                  </div>
                </div>

                {eq.equipment_type === 'pump' ? (
                  <PumpCurveEditor
                    keyPrefix={keyPrefix}
                    readOnly={readOnly}
                    curve={eq.pump_curve ?? []}
                    onChange={(curve) => onChange(updateRow(rows, i, { pump_curve: curve }))}
                  />
                ) : (
                  <MembraneEditor
                    keyPrefix={keyPrefix}
                    readOnly={readOnly}
                    model={eq.membrane_model ?? { ...EMPTY_MEMBRANE }}
                    onChange={(model) => onChange(updateRow(rows, i, { membrane_model: model }))}
                  />
                )}
              </div>
            );
          })}
        </div>
      )}
    </PanelShell>
  );
}
