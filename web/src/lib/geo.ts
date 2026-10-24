// Map space for every storm visual: equidistant cylindrical with Dublin's latitude as the
// standard parallel. X = lon·cos(φ0), Y = −lat (SVG y grows down). Plate-carrée imagery
// (NASA GIBS) and lat/lon grids (ERA5) map onto it linearly.

import { geoInterpolate } from "d3-geo";

export const PHI0 = 53.42;
export const K = Math.cos((PHI0 * Math.PI) / 180);

export const toMap = (lon: number, lat: number): [number, number] => [lon * K, -lat];
export const fromMap = (x: number, y: number): [number, number] => [x / K, -y];

export type Airport = { code: string; city: string; lon: number; lat: number };

export const AIRPORTS: Record<string, Airport> = {
  DUB: { code: "DUB", city: "Dublin", lon: -6.27, lat: 53.421 },
  BOS: { code: "BOS", city: "Boston", lon: -71.005, lat: 42.364 },
  JFK: { code: "JFK", city: "New York", lon: -73.779, lat: 40.641 },
  EWR: { code: "EWR", city: "Newark", lon: -74.175, lat: 40.69 },
  ORD: { code: "ORD", city: "Chicago", lon: -87.904, lat: 41.978 },
  IAD: { code: "IAD", city: "Washington", lon: -77.456, lat: 38.951 },
  PHL: { code: "PHL", city: "Philadelphia", lon: -75.241, lat: 39.874 },
  YYZ: { code: "YYZ", city: "Toronto", lon: -79.63, lat: 43.677 },
  MCO: { code: "MCO", city: "Orlando", lon: -81.309, lat: 28.431 },
  SEA: { code: "SEA", city: "Seattle", lon: -122.309, lat: 47.449 },
  LHR: { code: "LHR", city: "London", lon: -0.454, lat: 51.47 },
  CDG: { code: "CDG", city: "Paris", lon: 2.55, lat: 49.01 },
  AMS: { code: "AMS", city: "Amsterdam", lon: 4.764, lat: 52.31 },
};

/** Great-circle route as a map-space polyline path. */
export function greatCircle(a: Airport, b: Airport, n = 96) {
  const interp = geoInterpolate([a.lon, a.lat], [b.lon, b.lat]);
  const pts: [number, number][] = [];
  for (let i = 0; i <= n; i++) {
    const [lon, lat] = interp(i / n);
    pts.push(toMap(lon, lat));
  }
  return pts;
}

export const pathOf = (pts: [number, number][]) =>
  pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(3)},${p[1].toFixed(3)}`).join("");

export type View = { cx: number; cy: number; w: number };

/** A lon/lat box → a map-space view centred on it. */
export function viewFor(lonMin: number, lonMax: number, latMin: number, latMax: number, aspect: number): View {
  const [x0, y0] = toMap(lonMin, latMax);
  const [x1, y1] = toMap(lonMax, latMin);
  const w = Math.max(x1 - x0, (y1 - y0) * aspect);
  return { cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, w };
}
