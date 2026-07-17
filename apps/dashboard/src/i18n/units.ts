// Unit system support. Metric is the product default; imperial is offered as an
// opt-in conversion. All engineering data from the API is metric, so metric is a
// pass-through and imperial applies deterministic conversions.

import type { TFunction } from 'i18next';

export type UnitSystem = 'metric' | 'imperial';

export const DEFAULT_UNIT_SYSTEM: UnitSystem = 'metric';

// The physical quantities the dashboard renders. Each maps a metric base unit to
// an imperial counterpart plus a conversion factor (metric value × factor).
export type Quantity =
  | 'flow' // m³/h -> US gpm
  | 'pressure' // bar -> psi
  | 'temperature' // °C -> °F (affine, handled specially)
  | 'volumePerDay' // m³/day -> US gal/day
  | 'head' // m -> ft
  | 'specificEnergy'; // kWh/m³ -> kWh/kgal

interface QuantityConversion {
  factor: number;
  metricUnitKey: string;
  imperialUnitKey: string;
}

const CONVERSIONS: Record<Exclude<Quantity, 'temperature'>, QuantityConversion> = {
  flow: { factor: 4.402867539, metricUnitKey: 'units.flow_m3h', imperialUnitKey: 'units.flow_gpm' },
  pressure: {
    factor: 14.5037738,
    metricUnitKey: 'units.pressure_bar',
    imperialUnitKey: 'units.pressure_psi',
  },
  volumePerDay: {
    factor: 264.172052,
    metricUnitKey: 'units.productPerDay_m3',
    imperialUnitKey: 'units.productPerDay_gal',
  },
  head: { factor: 3.280839895, metricUnitKey: 'units.head_m', imperialUnitKey: 'units.head_ft' },
  specificEnergy: {
    factor: 3.785411784, // kWh/m³ -> kWh per 1000 US gal
    metricUnitKey: 'units.sec_kwh_m3',
    imperialUnitKey: 'units.sec_kwh_kgal',
  },
};

/** Convert a metric value to the requested unit system. */
export function convert(value: number, quantity: Quantity, system: UnitSystem): number {
  if (system === 'metric') return value;
  if (quantity === 'temperature') return value * 1.8 + 32;
  return value * CONVERSIONS[quantity].factor;
}

/** Resolve the display unit key for a quantity in the given unit system. */
export function unitKey(quantity: Quantity, system: UnitSystem): string {
  if (quantity === 'temperature') return system === 'metric' ? 'units.temp_c' : 'units.temp_f';
  const conv = CONVERSIONS[quantity];
  return system === 'metric' ? conv.metricUnitKey : conv.imperialUnitKey;
}

/** Translate the display unit label for a quantity in the given unit system. */
export function unitLabel(t: TFunction, quantity: Quantity, system: UnitSystem): string {
  return t(unitKey(quantity, system));
}
