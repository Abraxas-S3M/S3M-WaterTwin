// Hook exposing the resolved customer branding and applying its palette to the
// document. The product name/subtitle fall back to the localized defaults so an
// unbranded build reads from the active locale.

import { useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  applyBrandingPalette,
  loadBrandingConfig,
  type BrandingConfig,
} from './branding';

export interface Branding extends BrandingConfig {
  /** Resolved display name (branded name or localized product title). */
  displayName: string;
  /** Resolved display subtitle (branded subtitle or localized default). */
  displaySubtitle: string;
}

export function useBranding(): Branding {
  const { t } = useTranslation();
  const config = useMemo(() => loadBrandingConfig(), []);

  useEffect(() => {
    applyBrandingPalette(config.palette);
  }, [config.palette]);

  return {
    ...config,
    displayName: config.name || t('app.title'),
    displaySubtitle: config.subtitle ?? t('app.subtitle'),
  };
}
