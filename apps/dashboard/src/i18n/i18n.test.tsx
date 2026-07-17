import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { act, renderHook, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// echarts renders to a canvas jsdom does not implement; mock it so the full app
// shell (which imports the pump-curve chart) can render in the RTL snapshot test.
vi.mock('echarts-for-react', () => ({
  default: () => <div data-testid="echarts-mock" />,
}));

import App from '../App';
import i18n from './index';
import { useUnits } from './useUnits';
import { convert, DEFAULT_UNIT_SYSTEM, unitKey } from './units';
import { DEFAULT_LANGUAGE, directionFor, isRtl } from './config';
import { useDashboardStore } from '../state/store';
import { installFetchMock, renderWithProviders } from '../test/utils';

describe('i18n configuration', () => {
  it('defaults to English (LTR)', () => {
    expect(DEFAULT_LANGUAGE).toBe('en');
    expect(directionFor('en')).toBe('ltr');
    expect(isRtl('en')).toBe(false);
    expect(i18n.resolvedLanguage).toBe('en');
  });

  it('marks Arabic as a right-to-left language', () => {
    expect(directionFor('ar')).toBe('rtl');
    expect(isRtl('ar')).toBe(true);
  });
});

describe('metric units (default)', () => {
  it('defaults the dashboard unit system to metric', () => {
    expect(DEFAULT_UNIT_SYSTEM).toBe('metric');
    expect(useDashboardStore.getState().unitSystem).toBe('metric');
  });

  it('treats metric as a pass-through and converts to imperial on request', () => {
    // Metric is a no-op; imperial applies the conversion factor.
    expect(convert(100, 'flow', 'metric')).toBe(100);
    expect(convert(1, 'pressure', 'imperial')).toBeCloseTo(14.5037738, 4);
    expect(convert(0, 'temperature', 'imperial')).toBe(32);
  });

  it('exposes metric unit labels by default via useUnits', () => {
    const { result } = renderHook(() => useUnits());
    expect(result.current.system).toBe('metric');
    expect(result.current.unit('flow')).toBe('m³/h');
    expect(result.current.unit('pressure')).toBe('bar');
    expect(unitKey('flow', 'metric')).toBe('units.flow_m3h');
  });
});

describe('Arabic locale', () => {
  afterEach(async () => {
    await act(async () => {
      await i18n.changeLanguage('en');
    });
  });

  it('loads the Arabic bundle and renders Arabic strings', async () => {
    await act(async () => {
      await i18n.changeLanguage('ar');
    });
    // Bundle is available and resolves to Arabic, not the raw key.
    expect(i18n.getResource('ar', 'translation', 'nav.items.command')).toBe(
      'نظرة عامة على القيادة',
    );
    expect(i18n.t('nav.items.command')).toBe('نظرة عامة على القيادة');
  });
});

describe('RTL layout', () => {
  let mock: ReturnType<typeof installFetchMock>;

  beforeEach(() => {
    mock = installFetchMock();
  });

  afterEach(async () => {
    mock?.restore();
    await act(async () => {
      await i18n.changeLanguage('en');
    });
    useDashboardStore.setState({ page: 'command' });
  });

  it('switches the document direction to RTL and mirrors the shell for Arabic', async () => {
    const { container } = renderWithProviders(<App />);

    // Starts English / LTR.
    await waitFor(() =>
      expect(document.documentElement.getAttribute('dir')).toBe('ltr'),
    );

    await act(async () => {
      await i18n.changeLanguage('ar');
    });

    await waitFor(() => {
      expect(document.documentElement.getAttribute('dir')).toBe('rtl');
      expect(document.documentElement.getAttribute('lang')).toBe('ar');
    });

    // Nav renders Arabic labels.
    expect(screen.getByRole('button', { name: 'نظرة عامة على القيادة' })).toBeInTheDocument();

    // Snapshot the mirrored navigation shell.
    expect(container.querySelector('.app-nav')).toMatchSnapshot();
  });

  it('lets the user switch language from the shell control', async () => {
    renderWithProviders(<App />);

    const select = await screen.findByTestId('language-select');
    expect((select as HTMLSelectElement).value).toBe('en');

    await userEvent.selectOptions(select, 'ar');

    await waitFor(() =>
      expect(document.documentElement.getAttribute('dir')).toBe('rtl'),
    );
  });
});
