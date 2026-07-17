// Hook exposing the active unit system plus helpers to convert and label
// physical quantities. Metric is the default; components read this instead of
// hard-coding unit strings so an imperial toggle is a single source of truth.

import { useTranslation } from 'react-i18next';
import { useDashboardStore } from '../state/store';
import { fmtNumber } from '../lib/format';
import { convert, unitLabel, type Quantity, type UnitSystem } from './units';

export interface UnitsApi {
  system: UnitSystem;
  setSystem: (system: UnitSystem) => void;
  /** Convert a metric value into the active unit system. */
  convert: (value: number, quantity: Quantity) => number;
  /** Localized unit label for a quantity in the active unit system. */
  unit: (quantity: Quantity) => string;
  /** Format a metric value (converted + rounded) for the active unit system. */
  value: (value: number | null | undefined, quantity: Quantity, digits?: number) => string;
}

export function useUnits(): UnitsApi {
  const { t } = useTranslation();
  const system = useDashboardStore((s) => s.unitSystem);
  const setSystem = useDashboardStore((s) => s.setUnitSystem);

  return {
    system,
    setSystem,
    convert: (value, quantity) => convert(value, quantity, system),
    unit: (quantity) => unitLabel(t, quantity, system),
    value: (value, quantity, digits = 1) => {
      if (value === null || value === undefined || Number.isNaN(value)) return t('common.dash');
      return fmtNumber(convert(value, quantity, system), digits);
    },
  };
}
