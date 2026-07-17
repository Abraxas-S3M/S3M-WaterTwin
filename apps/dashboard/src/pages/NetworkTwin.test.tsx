import { describe, it, expect, afterEach, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// MapLibre GL renders to a WebGL canvas that jsdom does not implement; mock the
// module so the page can mount and we can assert on the (non-map) DOM overlay.
vi.mock('maplibre-gl', () => {
  class FakeMap {
    private sources = new Map<string, { setData: (d: unknown) => void }>();
    private layers = new Set<string>();
    constructor(_opts: unknown) {}
    on(event: string, layerOrCb: unknown, cb?: unknown) {
      const handler = (typeof layerOrCb === 'function' ? layerOrCb : cb) as
        | ((e?: unknown) => void)
        | undefined;
      // Fire 'load' immediately so the data-draw effect runs during the test.
      if (event === 'load' && handler) handler();
    }
    getSource(id: string) {
      return this.sources.get(id);
    }
    addSource(id: string) {
      this.sources.set(id, { setData: () => {} });
    }
    getLayer(id: string) {
      return this.layers.has(id) ? { id } : undefined;
    }
    addLayer(layer: { id: string }) {
      this.layers.add(layer.id);
    }
    getCanvas() {
      return { style: {} as CSSStyleDeclaration };
    }
    remove() {}
  }
  return { default: { Map: FakeMap } };
});

import { NetworkTwin } from './NetworkTwin';
import { installFetchMock, renderWithProviders } from '../test/utils';
import { useDashboardStore } from '../state/store';
import { bandColor } from '../lib/format';

describe('NetworkTwin', () => {
  let mock: ReturnType<typeof installFetchMock>;

  afterEach(() => {
    mock?.restore();
    useDashboardStore.setState({ page: 'command', selectedAssetId: null });
  });

  it('renders the map container, legend and network assets coloured by health', async () => {
    mock = installFetchMock();
    renderWithProviders(<NetworkTwin />);

    await waitFor(() => expect(screen.getByTestId('network-twin')).toBeInTheDocument());

    // Map container and health legend are present.
    expect(screen.getByTestId('network-map')).toBeInTheDocument();
    expect(screen.getByTestId('network-legend')).toBeInTheDocument();

    // Topology elements from the mocked GeoJSON fixture are listed.
    await waitFor(() =>
      expect(screen.getByTestId('network-row-PU-PROD-1')).toBeInTheDocument(),
    );
    const pumpRow = screen.getByTestId('network-row-PU-PROD-1');
    expect(within(pumpRow).getByText('Product Transfer Pump 1')).toBeInTheDocument();

    // AST-HPP-01 health (63.2, Degraded) is reused to colour the linked asset.
    expect(within(pumpRow).getByText(/63\.2 \(Degraded\)/)).toBeInTheDocument();
    const scoreCell = within(pumpRow).getByText(/63\.2 \(Degraded\)/);
    expect(scoreCell).toHaveStyle({ color: bandColor.Degraded });
  });

  it('overlays C1 leak-localization candidate zones with a preliminary/synthetic badge', async () => {
    mock = installFetchMock();
    renderWithProviders(<NetworkTwin />);

    const panel = await screen.findByTestId('leak-localization');
    expect(within(panel).getByText('(C1)')).toBeInTheDocument();

    // Preliminary/synthetic labelling is explicit.
    expect(screen.getByTestId('leak-preliminary-badge')).toHaveTextContent(
      /Preliminary \/ Synthetic/i,
    );

    // Candidate zones from the mocked fixture, ordered by rank.
    await waitFor(() => expect(screen.getByTestId('leak-zone-LEAK-Z1')).toBeInTheDocument());
    expect(screen.getByTestId('leak-zone-LEAK-Z2')).toBeInTheDocument();
    const rows = within(panel).getAllByRole('row').slice(1); // drop header row
    expect(rows[0]).toHaveTextContent('LEAK-Z1');
    expect(rows[1]).toHaveTextContent('LEAK-Z2');
  });

  it('clicks through to the Asset Twin for an asset-bound element', async () => {
    mock = installFetchMock();
    renderWithProviders(<NetworkTwin />);

    await waitFor(() => expect(screen.getByTestId('open-twin-PU-PROD-1')).toBeInTheDocument());
    await userEvent.click(screen.getByTestId('open-twin-PU-PROD-1'));

    const state = useDashboardStore.getState();
    expect(state.selectedAssetId).toBe('AST-HPP-01');
    expect(state.page).toBe('asset');
  });
});
