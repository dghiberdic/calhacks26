// Airport records for the mock world: every airport in the demo plus common European and North American
// airports a judge might try at the desk. Coordinates are aerodrome reference points (OurAirports),
// rounded; `eu` = EU261 territory (EU27 + EEA + CH); `tz` is IANA.
import type { Airport } from "@/api/types";

type Row = [icao: string, iata: string, name: string, lat: number, lon: number, country: string, eu: boolean, tz: string];

const ROWS: Row[] = [
  // Demo network (plan §1.2)
  ["EIDW", "DUB", "Dublin", 53.4213, -6.2701, "IE", true, "Europe/Dublin"],
  ["EGLL", "LHR", "London Heathrow", 51.4706, -0.4619, "GB", false, "Europe/London"],
  ["LFPG", "CDG", "Paris Charles de Gaulle", 49.0128, 2.55, "FR", true, "Europe/Paris"],
  ["EHAM", "AMS", "Amsterdam Schiphol", 52.3086, 4.7639, "NL", true, "Europe/Amsterdam"],
  ["EDDF", "FRA", "Frankfurt", 50.0333, 8.5706, "DE", true, "Europe/Berlin"],
  ["LEBL", "BCN", "Barcelona El Prat", 41.2971, 2.0785, "ES", true, "Europe/Madrid"],
  ["LEMD", "MAD", "Madrid Barajas", 40.4719, -3.5626, "ES", true, "Europe/Madrid"],
  ["LPPT", "LIS", "Lisbon Humberto Delgado", 38.7813, -9.1359, "PT", true, "Europe/Lisbon"],
  ["LIRF", "FCO", "Rome Fiumicino", 41.8003, 12.2389, "IT", true, "Europe/Rome"],
  ["EDDM", "MUC", "Munich", 48.3538, 11.7861, "DE", true, "Europe/Berlin"],
  ["LGAV", "ATH", "Athens", 37.9364, 23.9445, "GR", true, "Europe/Athens"],
  ["KJFK", "JFK", "New York JFK", 40.6398, -73.7789, "US", false, "America/New_York"],
  ["KORD", "ORD", "Chicago O'Hare", 41.9786, -87.9048, "US", false, "America/Chicago"],
  ["CYYZ", "YYZ", "Toronto Pearson", 43.6772, -79.6306, "CA", false, "America/Toronto"],
  ["KBOS", "BOS", "Boston Logan", 42.3643, -71.0052, "US", false, "America/New_York"],
  // Afternoon wave that operated on 24 Jan
  ["EBBR", "BRU", "Brussels", 50.9014, 4.4844, "BE", true, "Europe/Brussels"],
  ["EGCC", "MAN", "Manchester", 53.3537, -2.275, "GB", false, "Europe/London"],
  ["EGPH", "EDI", "Edinburgh", 55.95, -3.3725, "GB", false, "Europe/London"],
  ["LSZH", "ZRH", "Zurich", 47.4647, 8.5492, "CH", true, "Europe/Zurich"],
  ["EKCH", "CPH", "Copenhagen", 55.6179, 12.656, "DK", true, "Europe/Copenhagen"],
  ["LPFR", "FAO", "Faro", 37.0144, -7.9659, "PT", true, "Europe/Lisbon"],
  ["LEMG", "AGP", "Málaga", 36.6749, -4.4991, "ES", true, "Europe/Madrid"],
  // Ireland and the UK
  ["EINN", "SNN", "Shannon", 52.702, -8.9248, "IE", true, "Europe/Dublin"],
  ["EICK", "ORK", "Cork", 51.8413, -8.4911, "IE", true, "Europe/Dublin"],
  ["EGKK", "LGW", "London Gatwick", 51.1481, -0.1903, "GB", false, "Europe/London"],
  ["EGPF", "GLA", "Glasgow", 55.8719, -4.4331, "GB", false, "Europe/London"],
  ["EGBB", "BHX", "Birmingham", 52.4539, -1.748, "GB", false, "Europe/London"],
  ["EGAA", "BFS", "Belfast International", 54.6575, -6.2158, "GB", false, "Europe/London"],
  // Continental Europe
  ["LFPO", "ORY", "Paris Orly", 48.7233, 2.3794, "FR", true, "Europe/Paris"],
  ["LFMN", "NCE", "Nice Côte d'Azur", 43.6584, 7.2159, "FR", true, "Europe/Paris"],
  ["LFLL", "LYS", "Lyon Saint-Exupéry", 45.7264, 5.0908, "FR", true, "Europe/Paris"],
  ["EDDB", "BER", "Berlin Brandenburg", 52.3514, 13.4939, "DE", true, "Europe/Berlin"],
  ["EDDH", "HAM", "Hamburg", 53.6304, 9.9882, "DE", true, "Europe/Berlin"],
  ["EDDL", "DUS", "Düsseldorf", 51.2895, 6.7668, "DE", true, "Europe/Berlin"],
  ["LEPA", "PMI", "Palma de Mallorca", 39.5517, 2.7388, "ES", true, "Europe/Madrid"],
  ["GCLP", "LPA", "Gran Canaria", 27.9319, -15.3866, "ES", true, "Atlantic/Canary"],
  ["LIMC", "MXP", "Milan Malpensa", 45.6306, 8.7281, "IT", true, "Europe/Rome"],
  ["LIPZ", "VCE", "Venice Marco Polo", 45.5053, 12.3519, "IT", true, "Europe/Rome"],
  ["LSGG", "GVA", "Geneva", 46.2381, 6.109, "CH", true, "Europe/Zurich"],
  ["LOWW", "VIE", "Vienna", 48.1103, 16.5697, "AT", true, "Europe/Vienna"],
  ["ENGM", "OSL", "Oslo Gardermoen", 60.1939, 11.1004, "NO", true, "Europe/Oslo"],
  ["ESSA", "ARN", "Stockholm Arlanda", 59.6519, 17.9186, "SE", true, "Europe/Stockholm"],
  ["EFHK", "HEL", "Helsinki", 60.3172, 24.9633, "FI", true, "Europe/Helsinki"],
  ["BIKF", "KEF", "Keflavík", 63.985, -22.6056, "IS", true, "Atlantic/Reykjavik"],
  ["EPWA", "WAW", "Warsaw Chopin", 52.1658, 20.9672, "PL", true, "Europe/Warsaw"],
  ["LKPR", "PRG", "Prague", 50.1008, 14.26, "CZ", true, "Europe/Prague"],
  ["LHBP", "BUD", "Budapest", 47.4369, 19.2556, "HU", true, "Europe/Budapest"],
  ["LTFM", "IST", "Istanbul", 41.2622, 28.7278, "TR", false, "Europe/Istanbul"],
  // North America
  ["KEWR", "EWR", "Newark Liberty", 40.6925, -74.1687, "US", false, "America/New_York"],
  ["KIAD", "IAD", "Washington Dulles", 38.9445, -77.4558, "US", false, "America/New_York"],
  ["KPHL", "PHL", "Philadelphia", 39.8719, -75.2411, "US", false, "America/New_York"],
  ["KCLT", "CLT", "Charlotte Douglas", 35.214, -80.9431, "US", false, "America/New_York"],
  ["KATL", "ATL", "Atlanta Hartsfield-Jackson", 33.6367, -84.4281, "US", false, "America/New_York"],
  ["KMCO", "MCO", "Orlando", 28.4294, -81.309, "US", false, "America/New_York"],
  ["KMIA", "MIA", "Miami", 25.7932, -80.2906, "US", false, "America/New_York"],
  ["KDTW", "DTW", "Detroit Metro", 42.2124, -83.3534, "US", false, "America/Detroit"],
  ["KMSP", "MSP", "Minneapolis–Saint Paul", 44.882, -93.2218, "US", false, "America/Chicago"],
  ["KDFW", "DFW", "Dallas/Fort Worth", 32.8968, -97.038, "US", false, "America/Chicago"],
  ["KDEN", "DEN", "Denver", 39.8617, -104.6732, "US", false, "America/Denver"],
  ["KSEA", "SEA", "Seattle–Tacoma", 47.449, -122.3093, "US", false, "America/Los_Angeles"],
  ["KSFO", "SFO", "San Francisco", 37.619, -122.3749, "US", false, "America/Los_Angeles"],
  ["KLAX", "LAX", "Los Angeles", 33.9425, -118.4081, "US", false, "America/Los_Angeles"],
  ["KLAS", "LAS", "Las Vegas Harry Reid", 36.0801, -115.1523, "US", false, "America/Los_Angeles"],
  ["CYUL", "YUL", "Montréal–Trudeau", 45.4706, -73.7408, "CA", false, "America/Toronto"],
  ["CYVR", "YVR", "Vancouver", 49.1939, -123.1844, "CA", false, "America/Vancouver"],
  ["CYYC", "YYC", "Calgary", 51.1139, -114.0203, "CA", false, "America/Edmonton"],
  ["CYHZ", "YHZ", "Halifax Stanfield", 44.8808, -63.5086, "CA", false, "America/Halifax"],
];

export const AIRPORTS: Airport[] = ROWS.map(([icao, iata, name, lat, lon, country, eu, tz]) => ({ icao, iata, name, lat, lon, country, eu, tz }));

const BY_ICAO = new Map(AIRPORTS.map((a) => [a.icao, a]));
const BY_IATA = new Map(AIRPORTS.map((a) => [a.iata, a]));

/** Look an airport up by ICAO or IATA code (case-insensitive). */
export function findAirport(code: string): Airport | undefined {
  const c = code.trim().toUpperCase();
  return BY_ICAO.get(c) ?? BY_IATA.get(c);
}

/** IATA → Airport; throws for codes outside the table (programming error in fixtures). */
export function airport(iata: string): Airport {
  const a = BY_IATA.get(iata);
  if (!a) throw new Error(`mock airport ${iata} missing`);
  return a;
}

/** Plan §1.1 distances from DUB (OurAirports, great circle, R = 6,371 km). Binding: tests and copy use these. */
const PLAN_KM_FROM_DUB: Record<string, number> = {
  BOS: 4804, JFK: 5103, ORD: 5896, YYZ: 5261, CDG: 786, FRA: 1086, BCN: 1486, MAD: 1452, LIS: 1643, FCO: 1886, ATH: 2876, MUC: 1381, AMS: 750, LHR: 449,
};

/** Great-circle distance in whole km (Art. 7(4)), with the plan's binding values for the demo routes. */
export function distanceKm(aIata: string, bIata: string): number {
  if (aIata === "DUB" && PLAN_KM_FROM_DUB[bIata]) return PLAN_KM_FROM_DUB[bIata];
  if (bIata === "DUB" && PLAN_KM_FROM_DUB[aIata]) return PLAN_KM_FROM_DUB[aIata];
  const a = airport(aIata);
  const b = airport(bIata);
  const rad = (d: number) => (d * Math.PI) / 180;
  const dLat = rad(b.lat - a.lat);
  const dLon = rad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return Math.round(2 * 6371 * Math.asin(Math.sqrt(h)));
}

export type Band = { band_eur: 250 | 400 | 600; band_margin_km: number; label: string; article: string; segment: "long_haul_gt3500" | "medium_1500_3500" | "short_le1500" };

/**
 * Art. 7(1) band: ≤1,500 km €250; intra-EU >1,500 km and other 1,500–3,500 km €400; otherwise €600.
 * `band_margin_km` is the distance to the nearest band boundary that could change the band.
 */
export function bandFor(origin: string, dest: string): Band & { distance_km: number } {
  const d = distanceKm(origin, dest);
  const intraEu = airport(origin).eu && airport(dest).eu;
  const fmt = (n: number) => n.toLocaleString("en-US");
  const segment = d > 3500 ? "long_haul_gt3500" : d > 1500 ? "medium_1500_3500" : "short_le1500";
  if (d <= 1500) return { distance_km: d, band_eur: 250, band_margin_km: 1500 - d, label: `${fmt(d)} km · ${fmt(1500 - d)} km under the €400 band`, article: "Art. 7(1)(a)", segment };
  if (intraEu || d <= 3500) {
    const toUpper = intraEu ? Infinity : 3500 - d;
    const toLower = d - 1500;
    const label = toUpper < toLower ? `${fmt(d)} km · ${fmt(toUpper)} km under the €600 band` : `${fmt(d)} km · ${fmt(toLower)} km into the €400 band`;
    return { distance_km: d, band_eur: 400, band_margin_km: Math.min(toUpper, toLower), label, article: "Art. 7(1)(b)", segment: d > 3500 ? "long_haul_gt3500" : "medium_1500_3500" };
  }
  return { distance_km: d, band_eur: 600, band_margin_km: d - 3500, label: `${fmt(d)} km · ${fmt(d - 3500)} km into the €600 band`, article: "Art. 7(1)(c)", segment };
}
