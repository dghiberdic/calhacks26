// Major airports a judge is likely to try at the desk (ICAO → name, lat, lon). Coordinates from
// published aerodrome reference points, rounded to 0.01°.
export const AIRPORT_COORDS: Record<string, { name: string; lat: number; lon: number }> = {
  EIDW: { name: "Dublin", lat: 53.42, lon: -6.27 },
  EINN: { name: "Shannon", lat: 52.7, lon: -8.92 },
  EICK: { name: "Cork", lat: 51.84, lon: -8.49 },
  EGLL: { name: "London Heathrow", lat: 51.47, lon: -0.45 },
  EGKK: { name: "London Gatwick", lat: 51.15, lon: -0.19 },
  EGCC: { name: "Manchester", lat: 53.35, lon: -2.28 },
  EGPH: { name: "Edinburgh", lat: 55.95, lon: -3.37 },
  EGPF: { name: "Glasgow", lat: 55.87, lon: -4.43 },
  EHAM: { name: "Amsterdam", lat: 52.31, lon: 4.76 },
  LFPG: { name: "Paris CDG", lat: 49.01, lon: 2.55 },
  EDDF: { name: "Frankfurt", lat: 50.03, lon: 8.56 },
  EDDM: { name: "Munich", lat: 48.35, lon: 11.79 },
  LEMD: { name: "Madrid", lat: 40.47, lon: -3.56 },
  LEBL: { name: "Barcelona", lat: 41.3, lon: 2.08 },
  LIRF: { name: "Rome Fiumicino", lat: 41.8, lon: 12.25 },
  LSZH: { name: "Zurich", lat: 47.46, lon: 8.55 },
  LOWW: { name: "Vienna", lat: 48.11, lon: 16.57 },
  EKCH: { name: "Copenhagen", lat: 55.62, lon: 12.66 },
  ENGM: { name: "Oslo", lat: 60.19, lon: 11.1 },
  ESSA: { name: "Stockholm", lat: 59.65, lon: 17.92 },
  EFHK: { name: "Helsinki", lat: 60.32, lon: 24.96 },
  BIKF: { name: "Keflavík", lat: 63.99, lon: -22.61 },
  LPPT: { name: "Lisbon", lat: 38.77, lon: -9.13 },
  LTFM: { name: "Istanbul", lat: 41.26, lon: 28.74 },
  KBOS: { name: "Boston", lat: 42.36, lon: -71.01 },
  KJFK: { name: "New York JFK", lat: 40.64, lon: -73.78 },
  KEWR: { name: "Newark", lat: 40.69, lon: -74.17 },
  KLGA: { name: "LaGuardia", lat: 40.78, lon: -73.87 },
  KPHL: { name: "Philadelphia", lat: 39.87, lon: -75.24 },
  KIAD: { name: "Washington Dulles", lat: 38.95, lon: -77.46 },
  KATL: { name: "Atlanta", lat: 33.64, lon: -84.43 },
  KMCO: { name: "Orlando", lat: 28.43, lon: -81.31 },
  KMIA: { name: "Miami", lat: 25.79, lon: -80.29 },
  KORD: { name: "Chicago O'Hare", lat: 41.98, lon: -87.9 },
  KDFW: { name: "Dallas/Fort Worth", lat: 32.9, lon: -97.04 },
  KDEN: { name: "Denver", lat: 39.86, lon: -104.67 },
  KSEA: { name: "Seattle", lat: 47.45, lon: -122.31 },
  KSFO: { name: "San Francisco", lat: 37.62, lon: -122.38 },
  KOAK: { name: "Oakland", lat: 37.72, lon: -122.22 },
  KSJC: { name: "San José", lat: 37.36, lon: -121.93 },
  KLAX: { name: "Los Angeles", lat: 33.94, lon: -118.41 },
  KLAS: { name: "Las Vegas", lat: 36.08, lon: -115.15 },
  KPHX: { name: "Phoenix", lat: 33.43, lon: -112.01 },
  KMSP: { name: "Minneapolis", lat: 44.88, lon: -93.22 },
  KDTW: { name: "Detroit", lat: 42.21, lon: -83.35 },
  KIAH: { name: "Houston", lat: 29.98, lon: -95.34 },
  CYYZ: { name: "Toronto", lat: 43.68, lon: -79.63 },
  CYVR: { name: "Vancouver", lat: 49.19, lon: -123.18 },
  CYUL: { name: "Montréal", lat: 45.47, lon: -73.74 },
  RJTT: { name: "Tokyo Haneda", lat: 35.55, lon: 139.78 },
  RKSI: { name: "Seoul Incheon", lat: 37.46, lon: 126.44 },
  VHHH: { name: "Hong Kong", lat: 22.31, lon: 113.92 },
  WSSS: { name: "Singapore", lat: 1.36, lon: 103.99 },
  YSSY: { name: "Sydney", lat: -33.95, lon: 151.18 },
  OMDB: { name: "Dubai", lat: 25.25, lon: 55.36 },
  SBGR: { name: "São Paulo", lat: -23.43, lon: -46.47 },
  MMMX: { name: "Mexico City", lat: 19.44, lon: -99.07 },
};

/** NASA GIBS true-colour frame for a day, centred on the airport (public domain, CORS-enabled). */
export function gibsImage(icao: string, date: string, halfLat = 4, aspect = 16 / 10, width = 960) {
  const a = AIRPORT_COORDS[icao];
  if (!a || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
  // plate carrée: stretch longitude by 1/cos(lat) so the picture keeps true shape at this latitude
  const k = Math.max(Math.cos((a.lat * Math.PI) / 180), 0.3);
  const halfLon = (halfLat * aspect) / k;
  const bbox = [a.lat - halfLat, a.lon - halfLon, a.lat + halfLat, a.lon + halfLon].map((n) => n.toFixed(3)).join(",");
  const params = new URLSearchParams({
    SERVICE: "WMS",
    REQUEST: "GetMap",
    VERSION: "1.3.0",
    LAYERS: "MODIS_Terra_CorrectedReflectance_TrueColor",
    STYLES: "",
    FORMAT: "image/jpeg",
    CRS: "EPSG:4326",
    BBOX: bbox,
    WIDTH: String(width),
    HEIGHT: String(Math.round(width / aspect)),
    TIME: date,
  });
  return { url: `https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi?${params}`, airport: a };
}
