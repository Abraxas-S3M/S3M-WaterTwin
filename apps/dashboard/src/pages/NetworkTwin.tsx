import { useEffect, useMemo, useRef, useState } from 'react';
import maplibregl from 'maplibre-gl';
import type { FeatureCollection } from 'geojson';
import { useHealthScores, useLeakLocalization, useNetwork } from '../hooks';
import { useDashboardStore } from '../state/store';
import { bandColor, fmtNumber, titleCase } from '../lib/format';
import { readCssVar } from '../lib/cssVar';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import type {
  GeoFeatureCollection,
  HealthBand,
  HealthScore,
  LeakCandidateZoneFeature,
  NetworkElementType,
  NetworkFeature,
  NetworkLinkFeature,
  NetworkNodeFeature,
} from '../api/types';

// A blank, offline style: a network schematic overlay does not need basemap
// tiles (which would require an external provider / API key). Assets and pipes
// are drawn as GeoJSON layers on a flat background.
//
// MapLibre paints to a WebGL canvas that cannot resolve `var()`, so the map's
// colours are resolved from CSS custom properties to concrete values at
// render/init time via readCssVar (the same mechanism the pump-curve chart uses).
function blankStyle(): maplibregl.StyleSpecification {
  return {
    version: 8,
    sources: {},
    layers: [
      {
        id: 'background',
        type: 'background',
        paint: { 'background-color': readCssVar('--map-bg', '') },
      },
    ],
  };
}

// The health band shown for an asset with no score. DOM-applied (legend swatch,
// table cell), so it can reference the token directly.
const UNKNOWN_HEALTH_COLOR = 'var(--band-unknown)';

const NODE_ELEMENT_TYPES: NetworkElementType[] = ['junction', 'valve', 'pump', 'tank', 'reservoir'];

function isNode(feature: NetworkFeature): feature is NetworkNodeFeature {
  return feature.geometry.type === 'Point';
}

function isLink(feature: NetworkFeature): feature is NetworkLinkFeature {
  return feature.geometry.type === 'LineString';
}

interface DecoratedProps {
  element_id: string;
  element_type: NetworkElementType;
  label: string;
  asset_id: string | null;
  band: HealthBand | 'Unknown';
  color: string;
  health_score: number | null;
}

// Merge asset-health analytics onto a topology feature so MapLibre can style by
// band and the side panel can show the same colour/score.
function decorate(feature: NetworkFeature, healthById: Record<string, HealthScore>): DecoratedProps {
  const assetId = feature.properties.asset_id ?? null;
  const health = assetId ? healthById[assetId] : undefined;
  return {
    element_id: feature.properties.element_id,
    element_type: feature.properties.element_type,
    label: feature.properties.label,
    asset_id: assetId,
    band: health ? health.band : 'Unknown',
    color: health ? bandColor[health.band] : UNKNOWN_HEALTH_COLOR,
    health_score: health ? health.score : null,
  };
}

const HEALTH_BANDS: HealthBand[] = ['Healthy', 'Monitor', 'Degraded', 'HighRisk', 'Critical'];

export function NetworkTwin() {
  const network = useNetwork();
  const health = useHealthScores();
  const leaks = useLeakLocalization();
  const openAssetTwin = useDashboardStore((s) => s.openAssetTwin);

  const mapContainer = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [mapReady, setMapReady] = useState(false);

  const healthById = useMemo(() => {
    const map: Record<string, HealthScore> = {};
    for (const h of health.data ?? []) map[h.asset_id] = h;
    return map;
  }, [health.data]);

  const features = network.data?.features ?? [];

  const decorated = useMemo(
    () => features.map((f) => ({ feature: f, props: decorate(f, healthById) })),
    [features, healthById],
  );

  const nodeCollection = useMemo<GeoFeatureCollection<NetworkFeature>>(
    () => ({
      type: 'FeatureCollection',
      features: decorated
        .filter(({ feature }) => isNode(feature))
        .map(({ feature, props }) => ({ ...feature, properties: { ...feature.properties, ...props } })),
    }),
    [decorated],
  );

  const linkCollection = useMemo<GeoFeatureCollection<NetworkFeature>>(
    () => ({
      type: 'FeatureCollection',
      features: decorated
        .filter(({ feature }) => isLink(feature))
        .map(({ feature, props }) => ({ ...feature, properties: { ...feature.properties, ...props } })),
    }),
    [decorated],
  );

  const leakCollection = useMemo<GeoFeatureCollection<LeakCandidateZoneFeature>>(
    () => ({
      type: 'FeatureCollection',
      features: leaks.data?.candidate_zones ?? [],
    }),
    [leaks.data],
  );

  // Initialise the map once.
  useEffect(() => {
    if (!mapContainer.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: mapContainer.current,
      style: blankStyle(),
      center: [0, 0],
      zoom: 13,
      attributionControl: false,
    });
    mapRef.current = map;
    map.on('load', () => setMapReady(true));
    return () => {
      map.remove();
      mapRef.current = null;
      setMapReady(false);
    };
  }, []);

  // (Re)draw sources + layers whenever data changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    // Resolve the map's tokens to concrete values: MapLibre's WebGL canvas
    // cannot resolve var(). Band colours are applied per-feature via a `match`
    // on the `band` property so the map matches the DOM legend and table.
    const leakZone = readCssVar('--leak-zone', '');
    const nodeStroke = readCssVar('--map-node-stroke', '');
    const bHealthy = readCssVar('--band-healthy', '');
    const bMonitor = readCssVar('--band-monitor', '');
    const bDegraded = readCssVar('--band-degraded', '');
    const bHighRisk = readCssVar('--band-highrisk', '');
    const bCritical = readCssVar('--band-critical', '');
    const bUnknown = readCssVar('--band-unknown', '');

    const upsertSource = (id: string, data: GeoFeatureCollection<unknown> | unknown) => {
      const existing = map.getSource(id) as maplibregl.GeoJSONSource | undefined;
      if (existing) {
        existing.setData(data as FeatureCollection);
      } else {
        map.addSource(id, { type: 'geojson', data: data as FeatureCollection });
      }
    };

    upsertSource('network-links', linkCollection);
    upsertSource('network-nodes', nodeCollection);
    upsertSource('leak-zones', leakCollection);

    if (!map.getLayer('leak-zones-fill')) {
      map.addLayer({
        id: 'leak-zones-fill',
        type: 'fill',
        source: 'leak-zones',
        paint: {
          'fill-color': leakZone,
          'fill-opacity': ['interpolate', ['linear'], ['get', 'likelihood'], 0, 0.08, 1, 0.4],
        },
      });
    }
    if (!map.getLayer('leak-zones-outline')) {
      map.addLayer({
        id: 'leak-zones-outline',
        type: 'line',
        source: 'leak-zones',
        paint: { 'line-color': leakZone, 'line-dasharray': [2, 2], 'line-width': 1.5 },
      });
    }
    if (!map.getLayer('network-links-line')) {
      map.addLayer({
        id: 'network-links-line',
        type: 'line',
        source: 'network-links',
        paint: {
          'line-color': [
            'match',
            ['get', 'band'],
            'Healthy', bHealthy,
            'Monitor', bMonitor,
            'Degraded', bDegraded,
            'HighRisk', bHighRisk,
            'Critical', bCritical,
            bUnknown,
          ],
          'line-width': ['match', ['get', 'element_type'], 'valve', 5, 3],
        },
      });
    }
    if (!map.getLayer('network-nodes-circle')) {
      map.addLayer({
        id: 'network-nodes-circle',
        type: 'circle',
        source: 'network-nodes',
        paint: {
          'circle-radius': ['match', ['get', 'element_type'], 'pump', 9, 'valve', 8, 6],
          'circle-color': [
            'match',
            ['get', 'band'],
            'Healthy', bHealthy,
            'Monitor', bMonitor,
            'Degraded', bDegraded,
            'HighRisk', bHighRisk,
            'Critical', bCritical,
            bUnknown,
          ],
          'circle-stroke-color': nodeStroke,
          'circle-stroke-width': 1.5,
        },
      });

      // Click-through: any node bound to a canonical asset opens its Asset Twin.
      map.on('click', 'network-nodes-circle', (e) => {
        const feature = e.features?.[0];
        const assetId = feature?.properties?.asset_id as string | undefined;
        if (assetId) openAssetTwin(assetId);
      });
      map.on('mouseenter', 'network-nodes-circle', () => {
        map.getCanvas().style.cursor = 'pointer';
      });
      map.on('mouseleave', 'network-nodes-circle', () => {
        map.getCanvas().style.cursor = '';
      });
    }
  }, [mapReady, nodeCollection, linkCollection, leakCollection, openAssetTwin]);

  const nodeRows = decorated.filter(({ feature }) => isNode(feature));
  const candidateZones = leaks.data?.candidate_zones ?? [];

  return (
    <div className="stack" data-testid="network-twin">
      <div className="page-header">
        <div>
          <h2>Network Twin</h2>
          <div className="context">
            Product-water network topology coloured by asset health. Click any asset to open its
            twin.
          </div>
        </div>
        <ProvenanceBadge provenance={network.data?.provenance ?? 'synthetic'} />
      </div>

      {network.isError ? (
        <div className="card">
          <h3>Network unavailable</h3>
          <div className="muted">
            {(network.error as Error)?.message ?? 'Could not load the network topology.'}
          </div>
        </div>
      ) : null}

      <div className="card">
        <div className="map-toolbar">
          <h3>Topology</h3>
          <div className="flow-legend" data-testid="network-legend">
            {HEALTH_BANDS.map((b) => (
              <span key={b}>
                <span className="legend-swatch" style={{ background: bandColor[b] }} />
                {b}
              </span>
            ))}
            <span>
              <span className="legend-swatch" style={{ background: UNKNOWN_HEALTH_COLOR }} />
              Unknown
            </span>
            <span>
              <span className="legend-swatch leak-swatch" />
              Leak candidate
            </span>
          </div>
        </div>
        <div ref={mapContainer} className="network-map" data-testid="network-map" />
        {network.isLoading ? <div className="spinner">Loading network…</div> : null}
      </div>

      <div className="card" data-testid="leak-localization">
        <h3>
          Leak-Localization Candidate Zones{' '}
          <span className="muted">(C1)</span>{' '}
          <ProvenanceBadge provenance={leaks.data?.provenance ?? 'preliminary'} />
          <span className="prov-badge unvalidated" data-testid="leak-preliminary-badge">
            Preliminary / Synthetic
          </span>
        </h3>
        <p className="muted">
          Candidate zones are a preliminary, synthetic estimate from the C1 leak-localization
          engine — not a confirmed leak location. Advisory only.
        </p>
        {candidateZones.length === 0 ? (
          <div className="empty">No leak-localization candidates at this time.</div>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Rank</th>
                <th>Zone</th>
                <th>Suspected node</th>
                <th className="cell-num">Likelihood</th>
                <th className="cell-num">Residual pressure</th>
              </tr>
            </thead>
            <tbody>
              {[...candidateZones]
                .sort((a, b) => a.properties.rank - b.properties.rank)
                .map((z) => (
                  <tr key={z.properties.zone_id} data-testid={`leak-zone-${z.properties.zone_id}`}>
                    <td>{z.properties.rank}</td>
                    <td>{z.properties.zone_id}</td>
                    <td className="muted">{z.properties.suspected_node_id}</td>
                    <td className="cell-num">
                      {fmtNumber(z.properties.likelihood * 100, 0)}%
                    </td>
                    <td className="cell-num">
                      {fmtNumber(z.properties.residual_pressure_m, 2)} m
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h3>Assets on the network</h3>
        {nodeRows.length === 0 ? (
          <div className="empty">No network assets to display.</div>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Element</th>
                <th>Type</th>
                <th>Health</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {nodeRows.map(({ feature, props }) => {
                const clickable = !!props.asset_id;
                return (
                  <tr
                    key={props.element_id}
                    className={clickable ? 'clickable' : undefined}
                    onClick={clickable ? () => openAssetTwin(props.asset_id as string) : undefined}
                    data-testid={`network-row-${props.element_id}`}
                  >
                    <td>{props.label}</td>
                    <td className="muted">{titleCase(feature.properties.element_type)}</td>
                    <td style={{ color: props.color }}>
                      {props.health_score != null
                        ? `${fmtNumber(props.health_score, 1)} (${props.band})`
                        : '—'}
                    </td>
                    <td>
                      {clickable ? (
                        <button
                          className="btn"
                          onClick={(e) => {
                            e.stopPropagation();
                            openAssetTwin(props.asset_id as string);
                          }}
                          data-testid={`open-twin-${props.element_id}`}
                        >
                          Open twin →
                        </button>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export const NETWORK_NODE_TYPES = NODE_ELEMENT_TYPES;
