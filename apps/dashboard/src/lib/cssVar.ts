/**
 * Read a CSS custom property from the document root.
 *
 * Canvas-rendered charts (ECharts) cannot resolve `var()`, so chart themes must
 * resolve tokens to concrete values at render time. Reading from the computed
 * style — rather than importing a constant — means charts also pick up the
 * customer branding overrides applied by `applyBrandingPalette`.
 *
 * Returns `fallback` when there is no document (SSR) or the property is unset
 * (jsdom under test does not resolve custom properties from stylesheets).
 */
export function readCssVar(name: string, fallback: string): string {
  if (typeof document === 'undefined') return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}
