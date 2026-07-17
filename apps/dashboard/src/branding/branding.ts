// Customer-branding configuration. A white-label deployment can rebrand the
// dashboard (product name, logo, and accent palette) without code changes by
// setting Vite build-time env vars. All values fall back to the S3M-WaterTwin
// defaults so an unbranded build renders exactly as before.

export interface BrandingPalette {
  /** Primary accent (buttons, active nav, highlights). */
  accent: string;
  /** Stronger accent (solid button/active backgrounds). */
  accentStrong: string;
  /** Ink color used on top of the strong accent. */
  accentContrast: string;
}

export interface BrandingConfig {
  /** Product/customer name shown in the shell and login. */
  name: string;
  /** Short subtitle under the product name. */
  subtitle?: string;
  /** Optional logo image URL; when set it replaces the text wordmark. */
  logoUrl?: string;
  /** Palette overrides applied to CSS custom properties. */
  palette: BrandingPalette;
}

const DEFAULT_PALETTE: BrandingPalette = {
  accent: '#38bdf8',
  accentStrong: '#0ea5e9',
  accentContrast: '#04222f',
};

function envValue(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

/** Read branding from the build-time environment, falling back to defaults. */
export function loadBrandingConfig(): BrandingConfig {
  const env = import.meta.env;
  return {
    name: envValue(env.VITE_BRAND_NAME) ?? '',
    subtitle: envValue(env.VITE_BRAND_SUBTITLE),
    logoUrl: envValue(env.VITE_BRAND_LOGO_URL),
    palette: {
      accent: envValue(env.VITE_BRAND_ACCENT) ?? DEFAULT_PALETTE.accent,
      accentStrong: envValue(env.VITE_BRAND_ACCENT_STRONG) ?? DEFAULT_PALETTE.accentStrong,
      accentContrast: envValue(env.VITE_BRAND_ACCENT_CONTRAST) ?? DEFAULT_PALETTE.accentContrast,
    },
  };
}

/** Apply a branding palette to the document's CSS custom properties. */
export function applyBrandingPalette(
  palette: BrandingPalette,
  target: HTMLElement | null = typeof document !== 'undefined' ? document.documentElement : null,
): void {
  if (!target) return;
  target.style.setProperty('--accent', palette.accent);
  target.style.setProperty('--accent-strong', palette.accentStrong);
  target.style.setProperty('--accent-contrast', palette.accentContrast);
}
