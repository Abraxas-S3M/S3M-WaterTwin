import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import ReactECharts from 'echarts-for-react';
import type { EChartsOption } from 'echarts';
import type { PumpCurve as PumpCurveData } from '../api/types';
import { readCssVar } from '../lib/cssVar';
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

    // ECharts paints to a canvas and cannot resolve `var()`; resolve each token
    // to a concrete value here. Fallbacks equal the literal each token replaced,
    // so the chart is unchanged even in jsdom where custom properties do not
    // resolve from stylesheets.
    const c = {
      bg:         readCssVar('--chart-bg', '#131a24'),
      border:     readCssVar('--chart-border', '#26303f'),
      text:       readCssVar('--chart-text', '#e6edf3'),
      textDim:    readCssVar('--chart-text-dim', '#8b95a5'),
      axis:       readCssVar('--chart-axis', '#26303f'),
      grid:       readCssVar('--chart-grid', '#1a2330'),
      series:     readCssVar('--chart-series', '#38bdf8'),
      pointOk:    readCssVar('--chart-point-ok', '#2ecc71'),
      pointWatch: readCssVar('--chart-point-watch', '#f1c40f'),
      pointEdge:  readCssVar('--chart-point-edge', '#ffffff'),
    };

    return {
      backgroundColor: 'transparent',
      grid: { left: 52, right: 20, top: 32, bottom: 44 },
      tooltip: {
        trigger: 'item',
        backgroundColor: c.bg,
        borderColor: c.border,
        textStyle: { color: c.text },
      },
      legend: {
        top: 0,
        textStyle: { color: c.textDim },
        data: [t('pumpCurve.hqCurve'), t('pumpCurve.bep'), t('pumpCurve.operatingPoint')],
      },
      xAxis: {
        type: 'value',
        name: t('pumpCurve.flowAxis', { unit: t('units.flow_m3h') }),
        nameLocation: 'middle',
        nameGap: 26,
        nameTextStyle: { color: c.textDim },
        axisLine: { lineStyle: { color: c.axis } },
        axisLabel: { color: c.textDim },
        splitLine: { lineStyle: { color: c.grid } },
      },
      yAxis: {
        type: 'value',
        name: t('pumpCurve.headAxis', { unit: t('units.head_m') }),
        nameTextStyle: { color: c.textDim },
        axisLine: { lineStyle: { color: c.axis } },
        axisLabel: { color: c.textDim },
        splitLine: { lineStyle: { color: c.grid } },
      },
      series: [
        {
          name: t('pumpCurve.hqCurve'),
          type: 'line',
          smooth: true,
          showSymbol: false,
          data: curvePoints,
          lineStyle: { color: c.series, width: 2 },
          areaStyle: { color: 'rgba(56,189,248,0.08)' },
        },
        {
          name: t('pumpCurve.bep'),
          type: 'scatter',
          symbol: 'diamond',
          symbolSize: 14,
          data: bep,
          itemStyle: { color: c.pointOk },
        },
        {
          name: t('pumpCurve.operatingPoint'),
          type: 'scatter',
          symbolSize: 16,
          data: op,
          itemStyle: { color: c.pointWatch, borderColor: c.pointEdge, borderWidth: 1 },
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
