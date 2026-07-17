// Central i18n configuration constants shared across the app and tests.

export type LanguageCode = 'en' | 'ar';

export interface LanguageMeta {
  code: LanguageCode;
  /** Text direction for this language. */
  dir: 'ltr' | 'rtl';
}

export const SUPPORTED_LANGUAGES: Record<LanguageCode, LanguageMeta> = {
  en: { code: 'en', dir: 'ltr' },
  ar: { code: 'ar', dir: 'rtl' },
};

export const DEFAULT_LANGUAGE: LanguageCode = 'en';

// Persisted preference key. Language selection is a UI-only preference, mirroring
// the existing store convention of keeping ephemeral selection out of app data.
export const LANGUAGE_STORAGE_KEY = 'watertwin.lang';

/** Resolve the text direction for a language code (defaults to LTR). */
export function directionFor(code: string | undefined): 'ltr' | 'rtl' {
  if (!code) return 'ltr';
  const base = code.split('-')[0] as LanguageCode;
  return SUPPORTED_LANGUAGES[base]?.dir ?? 'ltr';
}

/** Whether a language code renders right-to-left. */
export function isRtl(code: string | undefined): boolean {
  return directionFor(code) === 'rtl';
}
