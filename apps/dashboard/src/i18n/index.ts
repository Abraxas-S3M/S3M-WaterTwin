// react-i18next bootstrap for the dashboard.
//
// English is the default and fallback language; Arabic (RTL) is fully supported.
// Locale resources are bundled at build time (small, two-locale app) so there is
// no async load flash. A language preference is remembered in localStorage as a
// UI-only setting (no application data is persisted).

import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import {
  DEFAULT_LANGUAGE,
  LANGUAGE_STORAGE_KEY,
  SUPPORTED_LANGUAGES,
} from './config';
import en from './locales/en.json';
import ar from './locales/ar.json';

export const resources = {
  en: { translation: en },
  ar: { translation: ar },
} as const;

if (!i18n.isInitialized) {
  void i18n
    .use(LanguageDetector)
    .use(initReactI18next)
    .init({
      resources,
      supportedLngs: Object.keys(SUPPORTED_LANGUAGES),
      fallbackLng: DEFAULT_LANGUAGE,
      // Metric-first, English-first defaults: when detection yields an
      // unsupported language we fall back to English.
      nonExplicitSupportedLngs: true,
      load: 'languageOnly',
      interpolation: {
        // React already escapes rendered values.
        escapeValue: false,
      },
      detection: {
        order: ['localStorage', 'navigator', 'htmlTag'],
        lookupLocalStorage: LANGUAGE_STORAGE_KEY,
        caches: ['localStorage'],
      },
      react: {
        useSuspense: false,
      },
    });
}

export default i18n;
