import { geoInterpolate } from "d3-geo";

// Map space for the hero: equidistant cylindrical with Dublin's latitude as the standard parallel.
// X = lon·cos(φ0), Y = −lat (SVG y grows down). Plate-carrée imagery (NASA GIBS) and lat/lon grids
// (ERA5) map onto it linearly, so the satellite, the isobars and the wind share one coordinate system.
export const PHI0 = 53.42;
export const K = Math.cos((PHI0 * Math.PI) / 180);

export type LonLat = { lon: number; lat: number };
export type Box = [x0: number, y0: number, x1: number, y1: number];
/** A view is a centre and a width in map units; its height follows the screen. */
export type View = { cx: number; cy: number; w: number };

export const toMap = (lon: number, lat: number): [number, number] => [lon * K, -lat];

/** Great-circle route as a map-space polyline. */
export function greatCircle(a: LonLat, b: LonLat, n = 72): [number, number][] {
  const interp = geoInterpolate([a.lon, a.lat], [b.lon, b.lat]);
  return Array.from({ length: n + 1 }, (_, i) => {
    const [lon, lat] = interp(i / n);
    return toMap(lon, lat);
  });
}

export const pathOf = (pts: [number, number][]) => pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(3)},${p[1].toFixed(3)}`).join("");

/** The smallest view that contains a lon/lat box on a screen of this aspect (width / height). */
export function viewFor(lonMin: number, lonMax: number, latMin: number, latMax: number, aspect: number): View {
  const [x0, y0] = toMap(lonMin, latMax);
  const [x1, y1] = toMap(lonMax, latMin);
  return { cx: (x0 + x1) / 2, cy: (y0 + y1) / 2, w: Math.max(x1 - x0, (y1 - y0) * aspect) };
}

/** The map-space box a view covers on a W×H screen. */
export function boxOf(v: View, W: number, H: number): Box {
  const h = v.w * (H / Math.max(W, 1));
  return [v.cx - v.w / 2, v.cy - h / 2, v.cx + v.w / 2, v.cy + h / 2];
}
