import { useEffect, useMemo, useState } from 'react';
import { useOverview } from '../hooks';
import { useDashboardStore } from '../state/store';
import { fmtNumber, riskColor } from '../lib/format';
import type { PlantOverview } from '../api/types';

// Time (ms) each KPI view is shown before auto-advancing on the wall display.
export const CONTROL_ROOM_ROTATE_MS = 12_000;

interface BigKpi {
  label: string;
  value: string;
  unit?: string;
  sub?: string;
  accent?: string;
}

interface Slide {
  id: string;
  title: string;
  kpis: BigKpi[];
}

function buildSlides(data: PlantOverview): Slide[] {
  return [
    {
      id: 'production',
      title: 'Production & Recovery',
      kpis: [
        {
          label: 'Permeate Flow',
          value: fmtNumber(data.production.permeate_flow_m3h, 0),
          unit: 'm³/h',
        },
        {
          label: 'Product / Day',
          value: fmtNumber(data.production.product_m3_per_day, 0),
          unit: 'm³',
        },
        { label: 'Recovery', value: fmtNumber(data.recovery_pct.value, 1), unit: '%' },
        {
          label: 'Permeate Cond.',
          value: fmtNumber(data.permeate_conductivity_us_cm.value, 0),
          unit: 'µS/cm',
        },
      ],
    },
    {
      id: 'health',
      title: 'Health & Service-Continuity Risk',
      kpis: [
        {
          label: 'Plant Health',
          value: fmtNumber(data.plant_health.score, 1),
          sub: data.plant_health.band,
        },
        {
          label: 'Continuity Risk',
          value: fmtNumber(data.service_continuity_risk.score, 0),
          sub: `${data.service_continuity_risk.band} risk`,
          accent: riskColor(data.service_continuity_risk.band),
        },
        {
          label: 'HP Pump Health',
          value: fmtNumber(data.hp_pump_status.health ?? 0, 1),
          sub: data.hp_pump_status.band ?? '—',
        },
        {
          label: 'Membrane Health',
          value: fmtNumber(data.membrane_status.health ?? 0, 1),
          sub: data.membrane_status.band ?? '—',
        },
      ],
    },
    {
      id: 'energy',
      title: 'Energy & Active Signals',
      kpis: [
        { label: 'Total Power', value: fmtNumber(data.energy.total_power_kw, 0), unit: 'kW' },
        {
          label: 'Specific Energy',
          value: fmtNumber(data.energy.specific_energy_kwh_m3, 2),
          unit: 'kWh/m³',
        },
        {
          label: 'Active Alarms',
          value: fmtNumber(data.active_alarms.length, 0),
          accent: data.active_alarms.length > 0 ? 'var(--danger)' : undefined,
        },
        {
          label: 'Open Recommendations',
          value: fmtNumber(data.active_recommendations.length, 0),
        },
      ],
    },
  ];
}

interface Props {
  /** Auto-rotation interval in ms. Pass 0 to disable rotation (e.g. in tests). */
  autoRotateMs?: number;
  /** Initial slide index (for deterministic rendering/tests). */
  initialSlide?: number;
  /** Fixed clock value; when omitted the header shows a live ticking clock. */
  now?: Date;
}

/**
 * Large-format, high-contrast wall display for a control room. Shows a single
 * rotating KPI view at a time with minimal chrome so it reads at a distance.
 * All data is reused from the live overview endpoint — no new physics.
 */
export function ControlRoom({ autoRotateMs = CONTROL_ROOM_ROTATE_MS, initialSlide = 0, now }: Props) {
  const { data, isLoading, isError, error } = useOverview();
  const setDisplayMode = useDashboardStore((s) => s.setDisplayMode);

  const slides = useMemo(() => (data ? buildSlides(data) : []), [data]);
  const slideCount = slides.length;

  const [index, setIndex] = useState(initialSlide);
  const [clock, setClock] = useState<Date>(() => now ?? new Date());

  // Live clock (skipped when a fixed `now` is supplied).
  useEffect(() => {
    if (now) return;
    const id = setInterval(() => setClock(new Date()), 1000);
    return () => clearInterval(id);
  }, [now]);

  // Auto-rotate KPI views.
  useEffect(() => {
    if (autoRotateMs <= 0 || slideCount <= 1) return;
    const id = setInterval(() => setIndex((i) => (i + 1) % slideCount), autoRotateMs);
    return () => clearInterval(id);
  }, [autoRotateMs, slideCount]);

  // Keep the index in range if the number of slides changes.
  const activeIndex = slideCount === 0 ? 0 : index % slideCount;
  const slide = slides[activeIndex];

  return (
    <div className="control-room" data-testid="control-room">
      <header className="cr-header">
        <div className="cr-brand">
          <span className="cr-title">S3M-WaterTwin</span>
          <span className="cr-sub">Control Room</span>
        </div>
        <div className="cr-context">
          {data ? `${data.facility_id} · ${data.train_id}` : 'Live plant overview'}
        </div>
        <div className="cr-right">
          <time className="cr-clock" dateTime={clock.toISOString()}>
            {clock.toLocaleTimeString()}
          </time>
          <button
            className="cr-exit"
            onClick={() => setDisplayMode('standard')}
            data-testid="control-room-exit"
          >
            Exit
          </button>
        </div>
      </header>

      {isLoading ? (
        <div className="cr-message">Loading control-room overview…</div>
      ) : isError || !data || !slide ? (
        <div className="cr-message">
          {(error as Error)?.message ?? 'Control-room overview is unavailable.'}
        </div>
      ) : (
        <main className="cr-stage">
          <div className="cr-stage-title">{slide.title}</div>
          <div className="cr-grid" data-testid="control-room-slide" data-slide={slide.id}>
            {slide.kpis.map((kpi) => (
              <div key={kpi.label} className="cr-tile">
                <div className="cr-tile-label">{kpi.label}</div>
                <div className="cr-tile-value" style={kpi.accent ? { color: kpi.accent } : undefined}>
                  {kpi.value}
                  {kpi.unit ? <span className="cr-tile-unit">{kpi.unit}</span> : null}
                </div>
                {kpi.sub ? <div className="cr-tile-sub">{kpi.sub}</div> : null}
              </div>
            ))}
          </div>
          <div className="cr-dots" role="tablist" aria-label="KPI views">
            {slides.map((s, i) => (
              <button
                key={s.id}
                role="tab"
                aria-selected={i === activeIndex}
                aria-label={s.title}
                className={`cr-dot${i === activeIndex ? ' active' : ''}`}
                onClick={() => setIndex(i)}
              />
            ))}
          </div>
        </main>
      )}

      <footer className="cr-footer">
        Advisory display · figures are preliminary/estimated on synthetic data · no control write.
      </footer>
    </div>
  );
}
