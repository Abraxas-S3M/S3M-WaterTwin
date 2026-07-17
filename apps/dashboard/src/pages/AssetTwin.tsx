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
  useEquipmentEnvelope,
  useEquipmentFailureProbability,
  useEquipmentHealth,
  useEquipmentRootCause,
  useEquipmentRul,
  useHealth,
  useMembraneHealth,
  usePumpCurve,
  useRecommendations,
  useTelemetry,
} from '../hooks';
import { useDashboardStore } from '../state/store';
import { fmtNumber, titleCase } from '../lib/format';
import type { OperatingEnvelope, RatedData } from '../api/types';

const ENVELOPE_REGIMES: [keyof OperatingEnvelope, string][] = [
  ['at_bep_fraction', 'At BEP'],
  ['low_flow_fraction', 'Low flow'],
  ['high_pressure_fraction', 'High pressure'],
  ['excess_temperature_fraction', 'Excess temperature'],
  ['cavitation_risk_fraction', 'Cavitation risk'],
];

function EnvelopeGauge({ envelope }: { envelope: OperatingEnvelope }) {
  return (
    <div data-testid="operating-envelope">
      {ENVELOPE_REGIMES.map(([key, label]) => {
        const value = (envelope[key] as number) ?? 0;
        const pct = Math.max(0, Math.min(100, value * 100));
        const danger = key !== 'at_bep_fraction';
        const color = !danger ? '#2ecc71' : pct >= 25 ? '#e67e22' : '#f1c40f';
        return (
          <div className="contrib-row" key={key}>
            <div>
              <div className="factor">{label}</div>
              <div className="detail">{fmtNumber(pct, 0)}% of observed duty</div>
            </div>
            <div className="contrib-bar">
              <div className="seg" style={{ background: color, left: 0, width: `${pct}%` }} />
            </div>
            <div className="contrib-value">{fmtNumber(pct, 0)}%</div>
          </div>
        );
      })}
    </div>
  );
}

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

  const equipmentHealth = useEquipmentHealth(assetId);
  const rul = useEquipmentRul(assetId);
  const failureProbability = useEquipmentFailureProbability(assetId);
  const envelope = useEquipmentEnvelope(assetId);
  const rootCause = useEquipmentRootCause(assetId);
  const isMembrane = asset.data?.asset_type === 'membrane_array';
  const membraneHealth = useMembraneHealth(isMembrane ? assetId : null);

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

      {equipmentHealth.data ? (
        <div className="card" data-testid="component-health">
          <h3>
            Component Health <span className="muted">(Predictive Maintenance)</span>{' '}
            <ProvenanceBadge provenance={equipmentHealth.data.health.provenance} />
          </h3>
          <HealthBar
            score={equipmentHealth.data.health.score}
            band={equipmentHealth.data.health.band}
            provenance={equipmentHealth.data.health.provenance}
          />
          <h3 style={{ marginTop: 16 }}>Contribution Breakdown</h3>
          <ContributionBreakdown contributions={equipmentHealth.data.health.contributions} />
        </div>
      ) : null}

      <div className="grid cols-2">
        <div className="card" data-testid="rul-panel">
          <h3>
            Remaining Useful Life <ProvenanceBadge provenance="preliminary" />
          </h3>
          {rul.data ? (
            <>
              <div className="kpi-value" style={{ marginBottom: 8 }}>
                {fmtNumber(rul.data.rul.rul_days, 0)}
                <span className="unit"> days</span>
              </div>
              <div className="card-sub">
                Band: {fmtNumber(rul.data.rul.lower_days, 0)}–{fmtNumber(rul.data.rul.upper_days, 0)}{' '}
                days (preliminary, not guaranteed)
              </div>
              <ul className="muted" style={{ marginTop: 8 }}>
                {rul.data.rul.basis.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            </>
          ) : (
            <div className="empty">No RUL estimate for this asset.</div>
          )}
        </div>

        <div className="card" data-testid="failure-probability-panel">
          <h3>
            Failure Probability <ProvenanceBadge provenance="preliminary" />
          </h3>
          {failureProbability.data ? (
            <>
              {failureProbability.data.failure_probability.predicted_failure_mode ? (
                <div className="card-sub" style={{ marginBottom: 8 }}>
                  Predicted mode:{' '}
                  {failureProbability.data.failure_probability.predicted_failure_mode}
                </div>
              ) : null}
              <table className="data">
                <thead>
                  <tr>
                    <th>Horizon</th>
                    <th style={{ textAlign: 'right' }}>P(failure)</th>
                  </tr>
                </thead>
                <tbody>
                  {['24h', '7d', '30d', '90d'].map((h) => (
                    <tr key={h}>
                      <td>{h}</td>
                      <td style={{ textAlign: 'right' }}>
                        {fmtNumber(
                          (failureProbability.data.failure_probability.horizons[h] ?? 0) * 100,
                          0,
                        )}
                        %
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          ) : (
            <div className="empty">No failure-probability estimate for this asset.</div>
          )}
        </div>
      </div>

      {envelope.data ? (
        <div className="card">
          <h3>
            Operating Envelope <ProvenanceBadge provenance={envelope.data.envelope.provenance} />
          </h3>
          <p className="muted">
            Fraction of observed duty ({envelope.data.envelope.samples} samples) spent in each
            regime. Time away from BEP accelerates wear.
          </p>
          <EnvelopeGauge envelope={envelope.data.envelope} />
        </div>
      ) : null}

      {rootCause.data ? (
        <div className="card" data-testid="root-cause">
          <h3>
            Root-Cause Ranking <ProvenanceBadge provenance={rootCause.data.root_cause.provenance} />
          </h3>
          <table className="data">
            <thead>
              <tr>
                <th>Cause</th>
                <th style={{ textAlign: 'right' }}>Probability</th>
                <th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {rootCause.data.root_cause.ranked_causes.map((c) => (
                <tr key={c.cause}>
                  <td>{c.cause}</td>
                  <td style={{ textAlign: 'right' }}>{fmtNumber(c.probability * 100, 0)}%</td>
                  <td className="muted">{c.evidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {isMembrane && membraneHealth.data ? (
        <div className="card" data-testid="membrane-panel">
          <h3>
            Membrane Intelligence{' '}
            <ProvenanceBadge provenance={membraneHealth.data.membrane.provenance} />
          </h3>
          <HealthBar
            score={membraneHealth.data.membrane.score}
            band={membraneHealth.data.membrane.band}
            provenance={membraneHealth.data.membrane.provenance}
          />
          <dl className="definition" style={{ marginTop: 12 }}>
            <dt>Permeate flow decline</dt>
            <dd>{fmtNumber(membraneHealth.data.membrane.normalized_permeate_flow_decline_pct, 1)}%</dd>
            <dt>Salt passage rise</dt>
            <dd>{fmtNumber(membraneHealth.data.membrane.normalized_salt_passage_rise_pct, 1)}%</dd>
            <dt>Differential pressure rise</dt>
            <dd>{fmtNumber(membraneHealth.data.membrane.normalized_dp_rise_pct, 1)}%</dd>
            <dt>Fouling (org/coll/bio)</dt>
            <dd>
              {fmtNumber(membraneHealth.data.membrane.fouling.organic * 100, 0)}% /{' '}
              {fmtNumber(membraneHealth.data.membrane.fouling.colloidal * 100, 0)}% /{' '}
              {fmtNumber(membraneHealth.data.membrane.fouling.biological * 100, 0)}%
            </dd>
            <dt>Scaling severity</dt>
            <dd>{fmtNumber(membraneHealth.data.membrane.fouling.scaling * 100, 0)}%</dd>
            <dt>CIP required</dt>
            <dd>
              {membraneHealth.data.membrane.cleaning_required
                ? `Yes — ${membraneHealth.data.membrane.cleaning_reason ?? ''}`
                : 'No'}
            </dd>
            <dt>Underperforming vessel</dt>
            <dd>{membraneHealth.data.membrane.underperforming_vessel ?? '—'}</dd>
          </dl>
        </div>
      ) : null}

      <div className="card" data-testid="maintenance-history">
        <h3>Maintenance History &amp; Degradation Basis</h3>
        {rul.data && rul.data.rul.basis.length ? (
          <ul className="muted">
            {rul.data.rul.basis.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        ) : (
          <div className="empty">No maintenance history on record.</div>
        )}
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
