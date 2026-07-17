import { useMemo } from 'react';
import { useAssets, useHealthScores, useStreams } from '../hooks';
import { useDashboardStore } from '../state/store';
import { bandColor, titleCase } from '../lib/format';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import type { Asset, HealthScore, TreatmentStage } from '../api/types';

// Main product train, in flow order intake -> ... -> product handoff.
const MAIN_LINE: TreatmentStage[] = [
  'intake',
  'cartridge_filtration',
  'dosing',
  'high_pressure_pumping',
  'ro_stage_1',
  'permeate',
  'distribution_handoff',
];

// Concentrate branch: RO reject -> energy recovery -> brine discharge.
const CONCENTRATE_LINE: TreatmentStage[] = ['ro_stage_1', 'concentrate_discharge'];

function StageBox({
  stage,
  assets,
  healthById,
  selected,
  onSelectStage,
  onOpenAsset,
}: {
  stage: TreatmentStage;
  assets: Asset[];
  healthById: Record<string, HealthScore>;
  selected: boolean;
  onSelectStage: (stage: TreatmentStage) => void;
  onOpenAsset: (assetId: string) => void;
}) {
  return (
    <div
      className={`flow-stage${selected ? ' selected' : ''}`}
      onClick={() => onSelectStage(stage)}
      data-testid={`stage-${stage}`}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onSelectStage(stage);
      }}
    >
      <div className="stage-name">{titleCase(stage)}</div>
      {assets.length === 0 ? (
        <div className="card-sub">No instrumented asset</div>
      ) : (
        assets.map((a) => {
          const h = healthById[a.asset_id];
          const color = h ? bandColor[h.band] : 'var(--text-dim)';
          return (
            <div
              key={a.asset_id}
              className="asset-pill"
              title={`Open ${a.name} twin`}
              onClick={(e) => {
                e.stopPropagation();
                onOpenAsset(a.asset_id);
              }}
              data-testid={`asset-pill-${a.asset_id}`}
            >
              <span>{a.name}</span>
              <span style={{ width: 10, height: 10, borderRadius: '50%', background: color }} />
            </div>
          );
        })
      )}
    </div>
  );
}

export function ProcessTwin() {
  const assets = useAssets();
  const streams = useStreams();
  const health = useHealthScores();
  const selectedStage = useDashboardStore((s) => s.selectedStage);
  const setSelectedStage = useDashboardStore((s) => s.setSelectedStage);
  const openAssetTwin = useDashboardStore((s) => s.openAssetTwin);

  const byStage = useMemo(() => {
    const map: Record<string, Asset[]> = {};
    for (const a of assets.data ?? []) {
      const key = a.treatment_stage ?? 'unassigned';
      (map[key] ??= []).push(a);
    }
    return map;
  }, [assets.data]);

  const healthById = useMemo(() => {
    const map: Record<string, HealthScore> = {};
    for (const h of health.data ?? []) map[h.asset_id] = h;
    return map;
  }, [health.data]);

  if (assets.isLoading) return <div className="spinner">Loading process twin…</div>;

  const renderLine = (stages: TreatmentStage[], testid: string) => (
    <div className="flow" data-testid={testid}>
      {stages.map((stage, i) => (
        <div key={stage} style={{ display: 'contents' }}>
          <StageBox
            stage={stage}
            assets={byStage[stage] ?? []}
            healthById={healthById}
            selected={selectedStage === stage}
            onSelectStage={setSelectedStage}
            onOpenAsset={openAssetTwin}
          />
          {i < stages.length - 1 ? <span className="flow-arrow">→</span> : null}
        </div>
      ))}
    </div>
  );

  const selectedAssets = selectedStage ? byStage[selectedStage] ?? [] : [];

  return (
    <div className="stack" data-testid="process-twin">
      <div className="page-header">
        <div>
          <h2>Process Twin</h2>
          <div className="context">
            Select a stage to inspect; click an asset to open its twin.
          </div>
        </div>
        <ProvenanceBadge provenance="synthetic" />
      </div>

      <div className="card">
        <h3>Product Train — intake → product</h3>
        {renderLine(MAIN_LINE, 'main-line')}
        <h3 style={{ marginTop: 20 }}>Concentrate — RO reject → ERD → brine</h3>
        {renderLine(CONCENTRATE_LINE, 'concentrate-line')}
        <div className="flow-legend">
          {(['Healthy', 'Monitor', 'Degraded', 'HighRisk', 'Critical'] as const).map((b) => (
            <span key={b}>
              <span className="legend-swatch" style={{ background: bandColor[b] }} />
              {b}
            </span>
          ))}
        </div>
      </div>

      {selectedStage ? (
        <div className="card">
          <h3>{titleCase(selectedStage)} — assets</h3>
          {selectedAssets.length === 0 ? (
            <div className="empty">No instrumented assets at this stage.</div>
          ) : (
            <table className="data">
              <thead>
                <tr>
                  <th>Asset</th>
                  <th>Type</th>
                  <th>Criticality</th>
                  <th>Health</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {selectedAssets.map((a) => {
                  const h = healthById[a.asset_id];
                  return (
                    <tr
                      key={a.asset_id}
                      className="clickable"
                      onClick={() => openAssetTwin(a.asset_id)}
                    >
                      <td>{a.name}</td>
                      <td className="muted">{titleCase(a.asset_type)}</td>
                      <td className="muted">{a.criticality}</td>
                      <td style={{ color: h ? bandColor[h.band] : undefined }}>
                        {h ? `${h.score.toFixed(1)} (${h.band})` : '—'}
                      </td>
                      <td>
                        <button className="btn" onClick={() => openAssetTwin(a.asset_id)}>
                          Open twin →
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      ) : null}

      <div className="card">
        <h3>Streams</h3>
        <table className="data">
          <thead>
            <tr>
              <th>Stream</th>
              <th>Type</th>
              <th>From</th>
              <th>To</th>
              <th>Description</th>
            </tr>
          </thead>
          <tbody>
            {(streams.data ?? []).map((s) => (
              <tr key={s.stream_id}>
                <td>{s.stream_id}</td>
                <td className="muted">{titleCase(s.stream_type)}</td>
                <td className="muted">{titleCase(s.from_stage)}</td>
                <td className="muted">{titleCase(s.to_stage)}</td>
                <td className="muted">{s.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
