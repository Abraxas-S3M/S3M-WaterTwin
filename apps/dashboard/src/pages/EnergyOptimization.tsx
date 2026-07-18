import { Trans, useTranslation } from 'react-i18next';
import { KpiCard } from '../components/KpiCard';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { useEnergyLosses, useEnergySummary, useOptimizeEnergy } from '../hooks';
import { fmtMoney, fmtNumber } from '../lib/format';
import type { EnergyOptimizationResult } from '../api/types';

function Setpoint({
  label,
  pressure,
  recovery,
  sec,
  flow,
  accent,
}: {
  label: string;
  pressure: number;
  recovery: number;
  sec: number;
  flow: number;
  accent?: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="card" style={{ flex: 1 }}>
      <div className="card-sub" style={{ marginBottom: 6 }}>{label}</div>
      <dl className="definition">
        <dt>{t('energy.setpointFields.hpPressure')}</dt>
        <dd style={accent ? { color: accent } : undefined}>
          {fmtNumber(pressure, 1)} {t('units.pressure_bar')}
        </dd>
        <dt>{t('energy.setpointFields.recovery')}</dt>
        <dd>{fmtNumber(recovery * 100, 1)}%</dd>
        <dt>{t('energy.setpointFields.specificEnergy')}</dt>
        <dd style={accent ? { color: accent } : undefined}>
          {fmtNumber(sec, 3)} {t('units.sec_kwh_m3')}
        </dd>
        <dt>{t('energy.setpointFields.permeateFlow')}</dt>
        <dd>{fmtNumber(flow, 1)} {t('units.flow_m3h')}</dd>
      </dl>
    </div>
  );
}

export function EnergyOptimization() {
  const { t } = useTranslation();
  const summary = useEnergySummary();
  const losses = useEnergyLosses();
  const optimize = useOptimizeEnergy();

  const s = summary.data;
  const optResult: EnergyOptimizationResult | undefined = optimize.data?.optimization;

  if (summary.isLoading) return <div className="spinner">{t('energy.loading')}</div>;

  return (
    <div className="stack" data-testid="energy-optimization">
      <div className="page-header">
        <div>
          <h2>{t('energy.title')}</h2>
          <div className="context">
            <Trans i18nKey="energy.context">
              Constrained RO specific-energy optimization (advisory). Optimal setpoint and savings are{' '}
              <strong>ESTIMATED</strong> and preliminary on a synthetic basis — not validated savings.
              No control write is issued; setpoints require operator action.
            </Trans>
          </div>
        </div>
        <ProvenanceBadge provenance="estimated" />
      </div>

      {s ? (
        <div className="grid kpis">
          <KpiCard
            label={t('energy.kpi.totalPower')}
            value={fmtNumber(s.total_power_kw, 0)}
            unit={t('units.power_kw')}
            provenance="synthetic"
          />
          <KpiCard
            label={t('energy.kpi.currentSec')}
            value={fmtNumber(s.current_sec_kwh_m3, 3)}
            unit={t('units.sec_kwh_m3')}
            provenance="synthetic"
          />
          <KpiCard
            label={t('energy.kpi.optimalSec')}
            value={fmtNumber(s.optimal_sec_kwh_m3, 3)}
            unit={t('units.sec_kwh_m3')}
            provenance="estimated"
            accent="var(--accent)"
          />
          <KpiCard
            label={t('energy.kpi.secReduction')}
            value={fmtNumber(s.sec_reduction_pct, 1)}
            unit={t('units.percent')}
            provenance="estimated"
          />
          <KpiCard
            label={t('energy.kpi.estSaving')}
            value={fmtMoney(s.estimated_cost_saving_per_day, 0)}
            unit={t('energy.kpi.perDay')}
            provenance="estimated"
          />
        </div>
      ) : null}

      <div className="card" data-testid="energy-by-asset">
        <h3>
          {t('energy.byAsset')}
          <ProvenanceBadge provenance="synthetic" className="prov-inline" />
        </h3>
        <table className="data">
          <thead>
            <tr>
              <th>{t('energy.byAssetTable.asset')}</th>
              <th className="cell-num">
                {t('energy.byAssetTable.power', { unit: t('units.power_kw') })}
              </th>
            </tr>
          </thead>
          <tbody>
            {(s?.energy_by_asset ?? []).map((a) => (
              <tr key={a.asset_id}>
                <td>{a.name}</td>
                <td className="cell-num">{fmtNumber(a.power_kw, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card" data-testid="energy-setpoint">
        <div className="row row-split">
          <h3>{t('energy.setpointTitle')}</h3>
          <button
            className="btn"
            data-testid="run-optimize"
            disabled={optimize.isPending}
            onClick={() => optimize.mutate()}
          >
            {optimize.isPending ? t('energy.optimizing') : t('energy.runOptimization')}
          </button>
        </div>
        <div className="row" style={{ gap: 12, alignItems: 'stretch' }}>
          {s ? (
            <>
              <Setpoint
                label={t('energy.setpointCurrent')}
                pressure={s.current_setpoint.feed_pressure_bar}
                recovery={s.current_setpoint.recovery}
                sec={s.current_setpoint.sec_kwh_m3}
                flow={s.current_setpoint.permeate_flow_m3h}
              />
              <Setpoint
                label={t('energy.setpointOptimal')}
                pressure={s.optimal_setpoint.feed_pressure_bar}
                recovery={s.optimal_setpoint.recovery}
                sec={s.optimal_setpoint.sec_kwh_m3}
                flow={s.optimal_setpoint.permeate_flow_m3h}
                accent="var(--accent)"
              />
            </>
          ) : null}
        </div>

        {optResult ? (
          <div className="card-sub" style={{ marginTop: 10 }} data-testid="optimize-result">
            <Trans
              i18nKey="energy.optimizeResult"
              values={{
                pressure: fmtNumber(optResult.optimal_feed_pressure_bar, 1),
                recovery: fmtNumber(optResult.optimal_recovery * 100, 1),
                sec: fmtNumber(optResult.optimized_sec_kwh_m3, 3),
                baseline: fmtNumber(optResult.baseline_sec_kwh_m3, 3),
                respected: optResult.constraints_respected ? t('common.yes') : t('common.no'),
              }}
            >
              Optimizer: optimal pressure <strong>{'{{pressure}}'} bar</strong> @ recovery{' '}
              <strong>{'{{recovery}}'}%</strong> → <strong>{'{{sec}}'} kWh/m³</strong> (from{' '}
              {'{{baseline}}'}). Constraints respected: {'{{respected}}'}.
            </Trans>{' '}
            <ProvenanceBadge provenance="estimated" />
          </div>
        ) : null}
      </div>

      <div className="card" data-testid="energy-losses">
        <h3>
          {t('energy.losses')}
          <ProvenanceBadge provenance="estimated" className="prov-inline" />
        </h3>
        <table className="data">
          <thead>
            <tr>
              <th>{t('energy.lossesTable.item')}</th>
              <th className="cell-num">{t('energy.lossesTable.currentSec')}</th>
              <th className="cell-num">{t('energy.lossesTable.bestAchievable')}</th>
              <th className="cell-num">{t('energy.lossesTable.avoidable')}</th>
              <th className="cell-num">{t('energy.lossesTable.estSavingPerDay')}</th>
            </tr>
          </thead>
          <tbody>
            {(losses.data?.losses ?? []).map((loss) => (
              <tr key={loss.label}>
                <td>{loss.label}</td>
                <td className="cell-num">{fmtNumber(loss.current_sec_kwh_m3, 3)}</td>
                <td className="cell-num">
                  {fmtNumber(loss.best_achievable_sec_kwh_m3, 3)}
                </td>
                <td className="cell-num">
                  {fmtNumber(loss.avoidable_loss_kwh_m3, 3)} ({fmtNumber(loss.avoidable_loss_pct, 1)}
                  %)
                </td>
                <td className="cell-num">
                  {fmtMoney(loss.estimated_avoidable_cost_per_day, 0)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
