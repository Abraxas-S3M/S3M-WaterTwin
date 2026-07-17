// Applies the current language's text direction to the document and exposes a
// small language API. Switching to Arabic flips <html dir="rtl"> so the entire
// layout mirrors via CSS logical properties and [dir="rtl"] rules.

import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import {
  directionFor,
  SUPPORTED_LANGUAGES,
  type LanguageCode,
} from './config';

export interface LanguageApi {
  language: string;
  dir: 'ltr' | 'rtl';
  isRtl: boolean;
  setLanguage: (code: LanguageCode) => void;
  available: LanguageCode[];
}

export function useDirection(): LanguageApi {
  const { i18n } = useTranslation();
  const language = i18n.resolvedLanguage ?? i18n.language;
  const dir = directionFor(language);

  useEffect(() => {
    if (typeof document === 'undefined') return;
    const root = document.documentElement;
    root.setAttribute('dir', dir);
    root.setAttribute('lang', language);
  }, [dir, language]);

  return {
    language,
    dir,
    isRtl: dir === 'rtl',
    setLanguage: (code) => {
      void i18n.changeLanguage(code);
    },
    available: Object.keys(SUPPORTED_LANGUAGES) as LanguageCode[],
  };
}
