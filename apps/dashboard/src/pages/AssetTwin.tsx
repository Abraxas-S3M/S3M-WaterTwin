import { HealthBar } from '../components/HealthBar';
import { ContributionBreakdown } from '../components/ContributionBreakdown';
import { PumpCurve } from '../components/PumpCurve';
import { RecommendationCard } from '../components/RecommendationCard';
import { AuditTrail } from '../components/AuditTrail';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import {
  useAnomaly,
  useAsset,
  useAssets,
  useAudit,
  useAskS3M,
  useDecision,
  useHealth,
  usePumpCurve,
  useRecommendations,
  useTelemetry,
} from '../hooks';
import { useDashboardStore } from '../state/store';
import { fmtNumber, titleCase } from '../lib/format';
import type { RatedData } from '../api/types';

const RATED_LABELS: Partial<Record<keyof RatedData, [string, string]>> = {
  rated_flow_m3h: ['Rated flow', 'm³/h'],
  rated_head_m: ['Rated head', 'm'],
  rated_power_kw: ['Rated power', 'kW'],
  rated_speed_rpm: ['Rated speed', 'rpm'],
  bep_flow_m3h: ['BEP flow', 'm³/h'],
  min_flow_m3h: ['Min flow', 'm³/h'],
  max_flow_m3h: ['Max flow', 'm³/h'],
  temp_limit_c: ['Temp limit', '°C'],
  vibration_limit_mm_s: ['Vibration limit', 'mm/s'],
};

function AssetPicker() {
  const assets = useAssets();
  const openAssetTwin = useDashboardStore((s) => s.openAssetTwin);
  return (
    <div className="card">
      <h3>Select an asset</h3>
      <p className="muted">Choose an asset to open its twin, or click one from the Process Twin.</p>
      <table className="data">
        <thead>
          <tr>
            <th>Asset</th>
            <th>Type</th>
            <th>Stage</th>
            <th>Criticality</th>
          </tr>
        </thead>
        <tbody>
          {(assets.data ?? []).map((a) => (
            <tr key={a.asset_id} className="clickable" onClick={() => openAssetTwin(a.asset_id)}>
              <td>{a.name}</td>
              <td className="muted">{titleCase(a.asset_type)}</td>
              <td className="muted">{a.treatment_stage ? titleCase(a.treatment_stage) : '—'}</td>
              <td className="muted">{a.criticality}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AssetTwin() {
  const assetId = useDashboardStore((s) => s.selectedAssetId);
  const operator = useDashboardStore((s) => s.operatorName);

  const asset = useAsset(assetId);
  const health = useHealth(assetId);
  const anomaly = useAnomaly(assetId);
  const telemetry = useTelemetry(assetId);
  const pumpCurve = usePumpCurve(assetId);
  const recommendations = useRecommendations(assetId ?? undefined);
  const audit = useAudit(assetId ?? undefined);
  const askS3M = useAskS3M();
  const decision = useDecision();

  if (!assetId) return <AssetPicker />;
  if (asset.isLoading) return <div className="spinner">Loading asset twin…</div>;
  if (asset.isError || !asset.data) {
    return (
      <div className="card">
        <h3>Asset unavailable</h3>
        <div className="muted">{(asset.error as Error)?.message ?? 'Could not load asset.'}</div>
      </div>
    );
  }

  const a = asset.data;
  const ratedEntries = Object.entries(RATED_LABELS).filter(
    ([key]) => a.rated[key as keyof RatedData] != null,
  );

  const handleDecision = (recId: string, kind: 'approve' | 'reject') =>
    decision.mutate({ recId, decision: kind, body: { operator } });

  return (
    <div className="stack" data-testid="asset-twin">
      <div className="page-header">
        <div>
          <h2>{a.name}</h2>
          <div className="context">
            {a.asset_id} · {titleCase(a.asset_type)} ·{' '}
            {a.treatment_stage ? titleCase(a.treatment_stage) : 'unassigned stage'}
          </div>
        </div>
        <button
          className="btn primary"
          disabled={askS3M.isPending}
          onClick={() => askS3M.mutate(a.asset_id)}
          data-testid="ask-s3m-button"
        >
          {askS3M.isPending ? 'Asking S3M…' : 'Ask S3M'}
        </button>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h3>Identity</h3>
          <dl className="definition">
            <dt>Manufacturer</dt>
            <dd>{a.manufacturer}</dd>
            <dt>Model</dt>
            <dd>{a.model}</dd>
            <dt>Serial</dt>
            <dd>{a.serial_number}</dd>
            <dt>Facility / Train</dt>
            <dd>
              {a.facility_id} / {a.train_id}
            </dd>
            <dt>Location</dt>
            <dd>{a.location}</dd>
            <dt>Criticality</dt>
            <dd>{a.criticality}</dd>
            <dt>Installed</dt>
            <dd>{a.install_date ?? '—'}</dd>
          </dl>
        </div>

        <div className="card">
          <h3>Rated Limits</h3>
          {ratedEntries.length === 0 ? (
            <div className="empty">No rated data on record.</div>
          ) : (
            <dl className="definition">
              {ratedEntries.map(([key, meta]) => {
                const [label, unit] = meta as [string, string];
                return (
                  <div key={key} style={{ display: 'contents' }}>
                    <dt>{label}</dt>
                    <dd>
                      {fmtNumber(a.rated[key as keyof RatedData] as number, 1)} {unit}
                    </dd>
                  </div>
                );
              })}
            </dl>
          )}
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h3>Health Score</h3>
          {health.data ? (
            <>
              <HealthBar
                score={health.data.score}
                band={health.data.band}
                provenance={health.data.provenance}
              />
              <h3 style={{ marginTop: 16 }}>Contribution Breakdown</h3>
              <ContributionBreakdown contributions={health.data.contributions} />
            </>
          ) : (
            <div className="spinner">Loading health…</div>
          )}
        </div>

        <div className="card">
          <h3>
            Anomaly Score
            {anomaly.data ? <ProvenanceBadge provenance={anomaly.data.provenance} /> : null}
          </h3>
          {anomaly.data ? (
            <>
              <div className="kpi-value" style={{ marginBottom: 12 }}>
                {fmtNumber(anomaly.data.score, 3)}
                <span className="unit">/ 1.0</span>
              </div>
              <div className="card-sub" style={{ marginBottom: 4 }}>Ranked domains</div>
              <table className="data">
                <tbody>
                  {anomaly.data.ranked_domains.map(([domain, score]) => (
                    <tr key={domain}>
                      <td>{titleCase(domain)}</td>
                      <td style={{ textAlign: 'right' }}>{fmtNumber(score, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <div className="spinner">Loading anomaly…</div>
          )}
        </div>
      </div>

      <div className="card">
        <h3>Live State</h3>
        {telemetry.data && telemetry.data.length ? (
          <table className="data">
            <thead>
              <tr>
                <th>Metric</th>
                <th style={{ textAlign: 'right' }}>Value</th>
                <th>Unit</th>
                <th>Quality</th>
                <th>Provenance</th>
              </tr>
            </thead>
            <tbody>
              {telemetry.data.map((r) => (
                <tr key={r.metric}>
                  <td>{titleCase(r.metric)}</td>
                  <td style={{ textAlign: 'right' }}>{fmtNumber(r.value, 2)}</td>
                  <td className="muted">{r.unit}</td>
                  <td className="muted">{r.quality ?? '—'}</td>
                  <td>
                    <ProvenanceBadge provenance={r.provenance} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="empty">No live telemetry for this asset.</div>
        )}
      </div>

      <div className="card">
        <h3>Pump Curve</h3>
        <PumpCurve data={pumpCurve.data} loading={pumpCurve.isLoading} />
      </div>

      <div className="card">
        <h3>S3M Recommendations</h3>
        {recommendations.data && recommendations.data.length ? (
          <div className="stack">
            {recommendations.data.map((rec) => (
              <RecommendationCard
                key={rec.recommendation_id}
                rec={rec}
                busy={decision.isPending}
                onApprove={(id) => handleDecision(id, 'approve')}
                onReject={(id) => handleDecision(id, 'reject')}
              />
            ))}
          </div>
        ) : (
          <div className="empty">
            No recommendations yet. Use “Ask S3M” to request an advisory analysis.
          </div>
        )}
      </div>

      <div className="card">
        <h3>Asset Audit Trail</h3>
        <AuditTrail
          entries={audit.data?.entries ?? []}
          provenance={audit.data?.provenance}
          loading={audit.isLoading}
        />
      </div>
    </div>
  );
}
