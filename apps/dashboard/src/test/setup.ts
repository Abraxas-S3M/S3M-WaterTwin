import '@testing-library/jest-dom/vitest';
import { afterEach, beforeEach } from 'vitest';
import { cleanup } from '@testing-library/react';
import i18n from '../i18n';
import { useDashboardStore } from '../state/store';

// Tests assert on English UI strings and the metric default. Reset the language
// and unit system before each test so a prior test (or persisted preference)
// cannot leak in.
beforeEach(() => {
  localStorage.clear();
  if (i18n.language !== 'en') void i18n.changeLanguage('en');
  useDashboardStore.setState({ unitSystem: 'metric' });
});

afterEach(() => {
  cleanup();
});
