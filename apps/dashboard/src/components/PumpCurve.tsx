import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import type { PumpCurve as PumpCurveData } from '../api/types';
import { ProvenanceBadge } from './ProvenanceBadge';

interface Props {
  data: PumpCurveData | undefined;
  loading?: boolean;
}

/**
 * Pump head/flow curve (line) with best-efficiency point and the current
 * operating point (scatter). Lets an operator see how far the machine is
 * running from its BEP.
 */
export function PumpCurve({ data, loading }: Props) {
  const { t } = useTranslation();
  const option = useMemo<EChartsOption | null>(() => {
    if (!data || !data.supported || !data.curve) return null;
    const curvePoints = data.curve.map((p) => [p.flow_m3h, p.head_m]);
    const bep = data.bep ? [[data.bep.flow_m3h, data.bep.head_m]] : [];
    const op = data.operating_point
      ? [[data.operating_point.flow_m3h, data.operating_point.head_m]]
      : [];

    return {
      backgroundColor: 'transparent',
      grid: { left: 52, right: 20, top: 32, bottom: 44 },
      tooltip: {
        trigger: 'item',
        backgroundColor: '#131a24',
        borderColor: '#26303f',
        textStyle: { color: '#e6edf3' },
      },
      legend: {
        top: 0,
        textStyle: { color: '#8b95a5' },
        data: [t('pumpCurve.hqCurve'), t('pumpCurve.bep'), t('pumpCurve.operatingPoint')],
      },
      xAxis: {
        type: 'value',
        name: t('pumpCurve.flowAxis', { unit: t('units.flow_m3h') }),
        nameLocation: 'middle',
        nameGap: 26,
        nameTextStyle: { color: '#8b95a5' },
        axisLine: { lineStyle: { color: '#26303f' } },
        axisLabel: { color: '#8b95a5' },
        splitLine: { lineStyle: { color: '#1a2330' } },
      },
      yAxis: {
        type: 'value',
        name: t('pumpCurve.headAxis', { unit: t('units.head_m') }),
        nameTextStyle: { color: '#8b95a5' },
        axisLine: { lineStyle: { color: '#26303f' } },
        axisLabel: { color: '#8b95a5' },
        splitLine: { lineStyle: { color: '#1a2330' } },
      },
      series: [
        {
          name: t('pumpCurve.hqCurve'),
          type: 'line',
          smooth: true,
          showSymbol: false,
          data: curvePoints,
          lineStyle: { color: '#38bdf8', width: 2 },
          areaStyle: { color: 'rgba(56,189,248,0.08)' },
        },
        {
          name: t('pumpCurve.bep'),
          type: 'scatter',
          symbol: 'diamond',
          symbolSize: 14,
          data: bep,
          itemStyle: { color: '#2ecc71' },
        },
        {
          name: t('pumpCurve.operatingPoint'),
          type: 'scatter',
          symbolSize: 16,
          data: op,
          itemStyle: { color: '#f1c40f', borderColor: '#fff', borderWidth: 1 },
        },
      ],
    };
  }, [data, t]);

  if (loading) return <div className="spinner">{t('pumpCurve.loading')}</div>;
  if (!data || !data.supported || !option) {
    return <div className="empty">{t('pumpCurve.unavailable')}</div>;
  }

  return (
    <div data-testid="pump-curve">
      <div className="spread" style={{ marginBottom: 8 }}>
        <span className="card-sub">{t('pumpCurve.caption')}</span>
        <ProvenanceBadge provenance={data.provenance} />
      </div>
      <ReactECharts
        option={option}
        style={{ height: 300, width: '100%' }}
        notMerge
        opts={{ renderer: 'canvas' }}
      />
    </div>
  );
}
