import type { ProcessStage, SampleType, SamplingPoint } from '../../api/types';
import {
  CellInput,
  PanelShell,
  RemoveButton,
  removeRow,
  toNumber,
  updateRow,
} from './panelKit';

const SAMPLE_TYPES: SampleType[] = ['continuous', 'lab'];

const EMPTY_STAGE: ProcessStage = { stage_id: '', name: '', order: 0, description: '' };
const EMPTY_POINT: SamplingPoint = {
  sampling_point_id: '',
  stage: '',
  stream_id: null,
  description: '',
  sample_type: 'continuous',
};

interface Props {
  stages: ProcessStage[];
  samplingPoints: SamplingPoint[];
  readOnly: boolean;
  onStagesChange: (rows: ProcessStage[]) => void;
  onSamplingPointsChange: (rows: SamplingPoint[]) => void;
}

export function ProcessStagesPanel({
  stages,
  samplingPoints,
  readOnly,
  onStagesChange,
  onSamplingPointsChange,
}: Props) {
  return (
    <PanelShell
      testId="admin-panel-process-stages"
      title="Process Stages & Sampling Points"
      description="Treatment-stage sequence and the sampling points bound to each stage/stream."
      readOnly={readOnly}
      onAdd={() =>
        onStagesChange([...stages, { ...EMPTY_STAGE, order: stages.length + 1 }])
      }
      addLabel="Add stage"
    >
      <div className="admin-subtable" data-testid="admin-process-stages-table">
        <div className="card-sub">Process stages</div>
        <table className="data">
          <thead>
            <tr>
              <th>Order</th>
              <th>Stage ID</th>
              <th>Name</th>
              <th>Description</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {stages.length === 0 ? (
              <tr>
                <td colSpan={5} className="empty">
                  No process stages configured.
                </td>
              </tr>
            ) : (
              stages.map((s, i) => (
                <tr key={`${s.stage_id}-${i}`}>
                  <td>
                    <CellInput
                      ariaLabel={`stage-order-${i}`}
                      type="number"
                      step="any"
                      value={s.order}
                      readOnly={readOnly}
                      onChange={(v) => onStagesChange(updateRow(stages, i, { order: toNumber(v) }))}
                    />
                  </td>
                  <td>
                    <CellInput
                      ariaLabel={`stage-id-${i}`}
                      value={s.stage_id}
                      readOnly={readOnly}
                      onChange={(v) => onStagesChange(updateRow(stages, i, { stage_id: v }))}
                    />
                  </td>
                  <td>
                    <CellInput
                      ariaLabel={`stage-name-${i}`}
                      value={s.name}
                      readOnly={readOnly}
                      onChange={(v) => onStagesChange(updateRow(stages, i, { name: v }))}
                    />
                  </td>
                  <td>
                    <CellInput
                      ariaLabel={`stage-description-${i}`}
                      value={s.description}
                      readOnly={readOnly}
                      onChange={(v) => onStagesChange(updateRow(stages, i, { description: v }))}
                    />
                  </td>
                  <td>
                    <RemoveButton
                      readOnly={readOnly}
                      label={`remove-stage-${i}`}
                      onClick={() => onStagesChange(removeRow(stages, i))}
                    />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="admin-subtable" data-testid="admin-sampling-points-table">
        <div className="row admin-panel-head">
          <span className="card-sub">Sampling points</span>
          {readOnly ? null : (
            <button
              type="button"
              className="btn ghost"
              data-testid="admin-add-sampling-point"
              onClick={() => onSamplingPointsChange([...samplingPoints, { ...EMPTY_POINT }])}
            >
              Add sampling point
            </button>
          )}
        </div>
        <table className="data">
          <thead>
            <tr>
              <th>Point ID</th>
              <th>Stage</th>
              <th>Stream</th>
              <th>Type</th>
              <th>Description</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {samplingPoints.length === 0 ? (
              <tr>
                <td colSpan={6} className="empty">
                  No sampling points configured.
                </td>
              </tr>
            ) : (
              samplingPoints.map((p, i) => (
                <tr key={`${p.sampling_point_id}-${i}`}>
                  <td>
                    <CellInput
                      ariaLabel={`sp-id-${i}`}
                      value={p.sampling_point_id}
                      readOnly={readOnly}
                      onChange={(v) =>
                        onSamplingPointsChange(updateRow(samplingPoints, i, { sampling_point_id: v }))
                      }
                    />
                  </td>
                  <td>
                    <CellInput
                      ariaLabel={`sp-stage-${i}`}
                      value={p.stage}
                      readOnly={readOnly}
                      onChange={(v) =>
                        onSamplingPointsChange(updateRow(samplingPoints, i, { stage: v }))
                      }
                    />
                  </td>
                  <td>
                    <CellInput
                      ariaLabel={`sp-stream-${i}`}
                      value={p.stream_id ?? ''}
                      placeholder="—"
                      readOnly={readOnly}
                      onChange={(v) =>
                        onSamplingPointsChange(
                          updateRow(samplingPoints, i, { stream_id: v || null }),
                        )
                      }
                    />
                  </td>
                  <td>
                    <select
                      className="input admin-cell"
                      aria-label={`sp-type-${i}`}
                      value={p.sample_type}
                      disabled={readOnly}
                      onChange={(e) =>
                        onSamplingPointsChange(
                          updateRow(samplingPoints, i, { sample_type: e.target.value as SampleType }),
                        )
                      }
                    >
                      {SAMPLE_TYPES.map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <CellInput
                      ariaLabel={`sp-description-${i}`}
                      value={p.description}
                      readOnly={readOnly}
                      onChange={(v) =>
                        onSamplingPointsChange(updateRow(samplingPoints, i, { description: v }))
                      }
                    />
                  </td>
                  <td>
                    <RemoveButton
                      readOnly={readOnly}
                      label={`remove-sp-${i}`}
                      onClick={() => onSamplingPointsChange(removeRow(samplingPoints, i))}
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
