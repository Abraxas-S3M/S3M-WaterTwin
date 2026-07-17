import { useTranslation } from 'react-i18next';
import { useDirection } from '../i18n/useDirection';
import { useUnits } from '../i18n/useUnits';
import type { LanguageCode } from '../i18n/config';
import type { UnitSystem } from '../i18n/units';

const UNIT_SYSTEMS: UnitSystem[] = ['metric', 'imperial'];

/**
 * Compact language + units selectors for the app shell. Language selection drives
 * document direction (RTL for Arabic); units default to metric.
 */
export function ShellControls() {
  const { t } = useTranslation();
  const { language, available, setLanguage } = useDirection();
  const { system, setSystem } = useUnits();

  return (
    <div className="shell-controls" data-testid="shell-controls">
      <label className="shell-control">
        <span className="shell-control-label">{t('settings.language')}</span>
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value as LanguageCode)}
          data-testid="language-select"
          aria-label={t('settings.language')}
        >
          {available.map((code) => (
            <option key={code} value={code}>
              {t(`settings.languageNames.${code}`)}
            </option>
          ))}
        </select>
      </label>
      <label className="shell-control">
        <span className="shell-control-label">{t('settings.units')}</span>
        <select
          value={system}
          onChange={(e) => setSystem(e.target.value as UnitSystem)}
          data-testid="units-select"
          aria-label={t('settings.units')}
        >
          {UNIT_SYSTEMS.map((sys) => (
            <option key={sys} value={sys}>
              {t(`settings.unitNames.${sys}`)}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
