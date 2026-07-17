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
import { useTranslation } from 'react-i18next';
import { useDashboardStore } from '../state/store';
import { fmtNumber, titleCase } from '../lib/format';
import type { OperatingEnvelope, RatedData } from '../api/types';

const ENVELOPE_REGIMES: (keyof OperatingEnvelope)[] = [
  'at_bep_fraction',
  'low_flow_fraction',
  'high_pressure_fraction',
  'excess_temperature_fraction',
  'cavitation_risk_fraction',
];

function EnvelopeGauge({ envelope }: { envelope: OperatingEnvelope }) {
  const { t } = useTranslation();
  return (
    <div data-testid="operating-envelope">
      {ENVELOPE_REGIMES.map((key) => {
        const value = (envelope[key] as number) ?? 0;
        const pct = Math.max(0, Math.min(100, value * 100));
        const danger = key !== 'at_bep_fraction';
        const color = !danger ? '#2ecc71' : pct >= 25 ? '#e67e22' : '#f1c40f';
        return (
          <div className="contrib-row" key={key}>
            <div>
              <div className="factor">{t(`asset.envelopeRegimes.${key}`)}</div>
              <div className="detail">{t('asset.observedDuty', { pct: fmtNumber(pct, 0) })}</div>
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

// Rated-limit rows: key -> unit label. Human-readable field labels are localized
// via the `asset.rated.<key>` keys.
const RATED_UNITS: Partial<Record<keyof RatedData, string>> = {
  rated_flow_m3h: 'm³/h',
  rated_head_m: 'm',
  rated_power_kw: 'kW',
  rated_speed_rpm: 'rpm',
  bep_flow_m3h: 'm³/h',
  min_flow_m3h: 'm³/h',
  max_flow_m3h: 'm³/h',
  temp_limit_c: '°C',
  vibration_limit_mm_s: 'mm/s',
};

function AssetPicker() {
  const { t } = useTranslation();
  const assets = useAssets();
  const openAssetTwin = useDashboardStore((s) => s.openAssetTwin);
  return (
    <div className="card">
      <h3>{t('asset.picker.title')}</h3>
      <p className="muted">{t('asset.picker.help')}</p>
      <table className="data">
        <thead>
          <tr>
            <th>{t('asset.picker.asset')}</th>
            <th>{t('asset.picker.type')}</th>
            <th>{t('asset.picker.stage')}</th>
            <th>{t('asset.picker.criticality')}</th>
          </tr>
        </thead>
        <tbody>
          {(assets.data ?? []).map((a) => (
            <tr key={a.asset_id} className="clickable" onClick={() => openAssetTwin(a.asset_id)}>
              <td>{a.name}</td>
              <td className="muted">{titleCase(a.asset_type)}</td>
              <td className="muted">
                {a.treatment_stage ? titleCase(a.treatment_stage) : t('common.dash')}
              </td>
              <td className="muted">{a.criticality}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AssetTwin() {
  const { t } = useTranslation();
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
  if (asset.isLoading) return <div className="spinner">{t('asset.loading')}</div>;
  if (asset.isError || !asset.data) {
    return (
      <div className="card">
        <h3>{t('asset.unavailableTitle')}</h3>
        <div className="muted">{(asset.error as Error)?.message ?? t('asset.unavailableBody')}</div>
      </div>
    );
  }

  const a = asset.data;
  const ratedEntries = Object.entries(RATED_UNITS).filter(
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
            {a.treatment_stage ? titleCase(a.treatment_stage) : t('asset.unassignedStage')}
          </div>
        </div>
        <button
          className="btn primary"
          disabled={askS3M.isPending}
          onClick={() => askS3M.mutate(a.asset_id)}
          data-testid="ask-s3m-button"
        >
          {askS3M.isPending ? t('asset.askingS3M') : t('asset.askS3M')}
        </button>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h3>{t('asset.identity')}</h3>
          <dl className="definition">
            <dt>{t('asset.identityFields.manufacturer')}</dt>
            <dd>{a.manufacturer}</dd>
            <dt>{t('asset.identityFields.model')}</dt>
            <dd>{a.model}</dd>
            <dt>{t('asset.identityFields.serial')}</dt>
            <dd>{a.serial_number}</dd>
            <dt>{t('asset.identityFields.facilityTrain')}</dt>
            <dd>
              {a.facility_id} / {a.train_id}
            </dd>
            <dt>{t('asset.identityFields.location')}</dt>
            <dd>{a.location}</dd>
            <dt>{t('asset.identityFields.criticality')}</dt>
            <dd>{a.criticality}</dd>
            <dt>{t('asset.identityFields.installed')}</dt>
            <dd>{a.install_date ?? t('common.dash')}</dd>
          </dl>
        </div>

        <div className="card">
          <h3>{t('asset.ratedLimits')}</h3>
          {ratedEntries.length === 0 ? (
            <div className="empty">{t('asset.noRatedData')}</div>
          ) : (
            <dl className="definition">
              {ratedEntries.map(([key, unit]) => (
                <div key={key} style={{ display: 'contents' }}>
                  <dt>{t(`asset.rated.${key}`)}</dt>
                  <dd>
                    {fmtNumber(a.rated[key as keyof RatedData] as number, 1)} {unit}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <h3>{t('asset.healthScore')}</h3>
          {health.data ? (
            <>
              <HealthBar
                score={health.data.score}
                band={health.data.band}
                provenance={health.data.provenance}
              />
              <h3 style={{ marginTop: 16 }}>{t('asset.contributionBreakdown')}</h3>
              <ContributionBreakdown contributions={health.data.contributions} />
            </>
          ) : (
            <div className="spinner">{t('asset.loadingHealth')}</div>
          )}
        </div>

        <div className="card">
          <h3>
            {t('asset.anomalyScore')}
            {anomaly.data ? <ProvenanceBadge provenance={anomaly.data.provenance} /> : null}
          </h3>
          {anomaly.data ? (
            <>
              <div className="kpi-value" style={{ marginBottom: 12 }}>
                {fmtNumber(anomaly.data.score, 3)}
                <span className="unit">{t('asset.outOf1')}</span>
              </div>
              <div className="card-sub" style={{ marginBottom: 4 }}>{t('asset.rankedDomains')}</div>
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
            <div className="spinner">{t('asset.loadingAnomaly')}</div>
          )}
        </div>
      </div>

      <div className="card">
        <h3>{t('asset.liveState')}</h3>
        {telemetry.data && telemetry.data.length ? (
          <table className="data">
            <thead>
              <tr>
                <th>{t('asset.telemetryTable.metric')}</th>
                <th style={{ textAlign: 'right' }}>{t('asset.telemetryTable.value')}</th>
                <th>{t('asset.telemetryTable.unit')}</th>
                <th>{t('asset.telemetryTable.quality')}</th>
                <th>{t('asset.telemetryTable.provenance')}</th>
              </tr>
            </thead>
            <tbody>
              {telemetry.data.map((r) => (
                <tr key={r.metric}>
                  <td>{titleCase(r.metric)}</td>
                  <td style={{ textAlign: 'right' }}>{fmtNumber(r.value, 2)}</td>
                  <td className="muted">{r.unit}</td>
                  <td className="muted">{r.quality ?? t('common.dash')}</td>
                  <td>
                    <ProvenanceBadge provenance={r.provenance} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="empty">{t('asset.noTelemetry')}</div>
        )}
      </div>

      <div className="card">
        <h3>{t('asset.pumpCurve')}</h3>
        <PumpCurve data={pumpCurve.data} loading={pumpCurve.isLoading} />
      </div>

      {equipmentHealth.data ? (
        <div className="card" data-testid="component-health">
          <h3>
            {t('asset.componentHealth')}{' '}
            <span className="muted">{t('asset.componentHealthTag')}</span>{' '}
            <ProvenanceBadge provenance={equipmentHealth.data.health.provenance} />
          </h3>
          <HealthBar
            score={equipmentHealth.data.health.score}
            band={equipmentHealth.data.health.band}
            provenance={equipmentHealth.data.health.provenance}
          />
          <h3 style={{ marginTop: 16 }}>{t('asset.contributionBreakdown')}</h3>
          <ContributionBreakdown contributions={equipmentHealth.data.health.contributions} />
        </div>
      ) : null}

      <div className="grid cols-2">
        <div className="card" data-testid="rul-panel">
          <h3>
            {t('asset.rul')} <ProvenanceBadge provenance="preliminary" />
          </h3>
          {rul.data ? (
            <>
              <div className="kpi-value" style={{ marginBottom: 8 }}>
                {fmtNumber(rul.data.rul.rul_days, 0)}
                <span className="unit">{t('asset.rulDays')}</span>
              </div>
              <div className="card-sub">
                {t('asset.rulBand', {
                  lower: fmtNumber(rul.data.rul.lower_days, 0),
                  upper: fmtNumber(rul.data.rul.upper_days, 0),
                })}
              </div>
              <ul className="muted" style={{ marginTop: 8 }}>
                {rul.data.rul.basis.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            </>
          ) : (
            <div className="empty">{t('asset.noRul')}</div>
          )}
        </div>

        <div className="card" data-testid="failure-probability-panel">
          <h3>
            {t('asset.failureProbability')} <ProvenanceBadge provenance="preliminary" />
          </h3>
          {failureProbability.data ? (
            <>
              {failureProbability.data.failure_probability.predicted_failure_mode ? (
                <div className="card-sub" style={{ marginBottom: 8 }}>
                  {t('asset.predictedMode', {
                    mode: failureProbability.data.failure_probability.predicted_failure_mode,
                  })}
                </div>
              ) : null}
              <table className="data">
                <thead>
                  <tr>
                    <th>{t('asset.horizon')}</th>
                    <th style={{ textAlign: 'right' }}>{t('asset.pFailure')}</th>
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
            <div className="empty">{t('asset.noFailureProbability')}</div>
          )}
        </div>
      </div>

      {envelope.data ? (
        <div className="card">
          <h3>
            {t('asset.operatingEnvelope')}{' '}
            <ProvenanceBadge provenance={envelope.data.envelope.provenance} />
          </h3>
          <p className="muted">
            {t('asset.envelopeHelp', { samples: envelope.data.envelope.samples })}
          </p>
          <EnvelopeGauge envelope={envelope.data.envelope} />
        </div>
      ) : null}

      {rootCause.data ? (
        <div className="card" data-testid="root-cause">
          <h3>
            {t('asset.rootCause')}{' '}
            <ProvenanceBadge provenance={rootCause.data.root_cause.provenance} />
          </h3>
          <table className="data">
            <thead>
              <tr>
                <th>{t('asset.rootCauseTable.cause')}</th>
                <th style={{ textAlign: 'right' }}>{t('asset.rootCauseTable.probability')}</th>
                <th>{t('asset.rootCauseTable.evidence')}</th>
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
            {t('asset.membrane')}{' '}
            <ProvenanceBadge provenance={membraneHealth.data.membrane.provenance} />
          </h3>
          <HealthBar
            score={membraneHealth.data.membrane.score}
            band={membraneHealth.data.membrane.band}
            provenance={membraneHealth.data.membrane.provenance}
          />
          <dl className="definition" style={{ marginTop: 12 }}>
            <dt>{t('asset.membraneFields.permeateFlowDecline')}</dt>
            <dd>{fmtNumber(membraneHealth.data.membrane.normalized_permeate_flow_decline_pct, 1)}%</dd>
            <dt>{t('asset.membraneFields.saltPassageRise')}</dt>
            <dd>{fmtNumber(membraneHealth.data.membrane.normalized_salt_passage_rise_pct, 1)}%</dd>
            <dt>{t('asset.membraneFields.dpRise')}</dt>
            <dd>{fmtNumber(membraneHealth.data.membrane.normalized_dp_rise_pct, 1)}%</dd>
            <dt>{t('asset.membraneFields.fouling')}</dt>
            <dd>
              {fmtNumber(membraneHealth.data.membrane.fouling.organic * 100, 0)}% /{' '}
              {fmtNumber(membraneHealth.data.membrane.fouling.colloidal * 100, 0)}% /{' '}
              {fmtNumber(membraneHealth.data.membrane.fouling.biological * 100, 0)}%
            </dd>
            <dt>{t('asset.membraneFields.scalingSeverity')}</dt>
            <dd>{fmtNumber(membraneHealth.data.membrane.fouling.scaling * 100, 0)}%</dd>
            <dt>{t('asset.membraneFields.cipRequired')}</dt>
            <dd>
              {membraneHealth.data.membrane.cleaning_required
                ? t('asset.cipYes', { reason: membraneHealth.data.membrane.cleaning_reason ?? '' })
                : t('asset.cipNo')}
            </dd>
            <dt>{t('asset.membraneFields.underperformingVessel')}</dt>
            <dd>{membraneHealth.data.membrane.underperforming_vessel ?? t('common.dash')}</dd>
          </dl>
        </div>
      ) : null}

      <div className="card" data-testid="maintenance-history">
        <h3>{t('asset.maintenanceHistory')}</h3>
        {rul.data && rul.data.rul.basis.length ? (
          <ul className="muted">
            {rul.data.rul.basis.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        ) : (
          <div className="empty">{t('asset.noMaintenanceHistory')}</div>
        )}
      </div>

      <div className="card">
        <h3>{t('asset.recommendations')}</h3>
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
          <div className="empty">{t('asset.noRecommendations')}</div>
        )}
      </div>

      <div className="card">
        <h3>{t('asset.auditTrail')}</h3>
        <AuditTrail
          entries={audit.data?.entries ?? []}
          provenance={audit.data?.provenance}
          loading={audit.isLoading}
        />
      </div>
    </div>
  );
}
