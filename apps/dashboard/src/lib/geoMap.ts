// maplibre-gl is a Phase 7 dependency that will back the geospatial/site map in
// a later phase. It is imported here (dynamically, so it is code-split and not
// shipped in the main bundle yet) to establish the integration point without
// building the map UI now.
import type { Map as MapLibreMap, MapOptions } from 'maplibre-gl';

export type { MapLibreMap };

/**
 * Lazily loads maplibre-gl and creates a map instance. Not used by any page in
 * Phase 7; the site/geo map view is wired in a later phase.
 */
export async function createGeoMap(options: MapOptions): Promise<MapLibreMap> {
  const maplibregl = await import('maplibre-gl');
  return new maplibregl.Map(options);
}
