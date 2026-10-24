/**
 * Reference geography for the static route map (aerodrome reference points, rounded to 0.01°).
 * Not data the engine uses: distances and bands come from the API (OurAirports, Art. 7(4)).
 */
export type AirportRef = { iata: string; icao: string; name: string; lat: number; lon: number };

const ROWS: [string, string, string, number, number][] = [
  ["DUB", "EIDW", "Dublin", 53.42, -6.27],
  ["SNN", "EINN", "Shannon", 52.7, -8.92],
  ["ORK", "EICK", "Cork", 51.84, -8.49],
  ["LHR", "EGLL", "London Heathrow", 51.47, -0.45],
  ["LGW", "EGKK", "London Gatwick", 51.15, -0.19],
  ["STN", "EGSS", "London Stansted", 51.89, 0.24],
  ["MAN", "EGCC", "Manchester", 53.35, -2.28],
  ["BHX", "EGBB", "Birmingham", 52.45, -1.75],
  ["EDI", "EGPH", "Edinburgh", 55.95, -3.37],
  ["GLA", "EGPF", "Glasgow", 55.87, -4.43],
  ["CDG", "LFPG", "Paris Charles de Gaulle", 49.01, 2.55],
  ["ORY", "LFPO", "Paris Orly", 48.73, 2.38],
  ["NCE", "LFMN", "Nice", 43.66, 7.21],
  ["AMS", "EHAM", "Amsterdam", 52.31, 4.76],
  ["BRU", "EBBR", "Brussels", 50.9, 4.48],
  ["FRA", "EDDF", "Frankfurt", 50.03, 8.56],
  ["MUC", "EDDM", "Munich", 48.35, 11.79],
  ["DUS", "EDDL", "Düsseldorf", 51.29, 6.77],
  ["HAM", "EDDH", "Hamburg", 53.63, 10.0],
  ["BER", "EDDB", "Berlin", 52.37, 13.5],
  ["ZRH", "LSZH", "Zurich", 47.46, 8.55],
  ["GVA", "LSGG", "Geneva", 46.24, 6.11],
  ["VIE", "LOWW", "Vienna", 48.11, 16.57],
  ["PRG", "LKPR", "Prague", 50.1, 14.26],
  ["WAW", "EPWA", "Warsaw", 52.17, 20.97],
  ["BUD", "LHBP", "Budapest", 47.44, 19.26],
  ["CPH", "EKCH", "Copenhagen", 55.62, 12.66],
  ["OSL", "ENGM", "Oslo", 60.19, 11.1],
  ["ARN", "ESSA", "Stockholm Arlanda", 59.65, 17.92],
  ["HEL", "EFHK", "Helsinki", 60.32, 24.96],
  ["KEF", "BIKF", "Keflavík", 63.99, -22.61],
  ["MAD", "LEMD", "Madrid", 40.47, -3.56],
  ["BCN", "LEBL", "Barcelona", 41.3, 2.08],
  ["AGP", "LEMG", "Málaga", 36.67, -4.5],
  ["ALC", "LEAL", "Alicante", 38.28, -0.56],
  ["PMI", "LEPA", "Palma de Mallorca", 39.55, 2.74],
  ["LIS", "LPPT", "Lisbon", 38.77, -9.13],
  ["OPO", "LPPR", "Porto", 41.24, -8.68],
  ["FAO", "LPFR", "Faro", 37.01, -7.97],
  ["FCO", "LIRF", "Rome Fiumicino", 41.8, 12.25],
  ["MXP", "LIMC", "Milan Malpensa", 45.63, 8.72],
  ["VCE", "LIPZ", "Venice", 45.51, 12.35],
  ["ATH", "LGAV", "Athens", 37.94, 23.94],
  ["IST", "LTFM", "Istanbul", 41.26, 28.74],
  ["JFK", "KJFK", "New York JFK", 40.64, -73.78],
  ["EWR", "KEWR", "Newark", 40.69, -74.17],
  ["BOS", "KBOS", "Boston", 42.36, -71.01],
  ["PHL", "KPHL", "Philadelphia", 39.87, -75.24],
  ["IAD", "KIAD", "Washington Dulles", 38.95, -77.46],
  ["ORD", "KORD", "Chicago O'Hare", 41.98, -87.9],
  ["ATL", "KATL", "Atlanta", 33.64, -84.43],
  ["MCO", "KMCO", "Orlando", 28.43, -81.31],
  ["MIA", "KMIA", "Miami", 25.79, -80.29],
  ["DFW", "KDFW", "Dallas/Fort Worth", 32.9, -97.04],
  ["DEN", "KDEN", "Denver", 39.86, -104.67],
  ["SEA", "KSEA", "Seattle", 47.45, -122.31],
  ["SFO", "KSFO", "San Francisco", 37.62, -122.38],
  ["LAX", "KLAX", "Los Angeles", 33.94, -118.41],
  ["YYZ", "CYYZ", "Toronto", 43.68, -79.63],
  ["YUL", "CYUL", "Montréal", 45.47, -73.74],
  ["YVR", "CYVR", "Vancouver", 49.19, -123.18],
];

export const AIRPORTS: Record<string, AirportRef> = Object.fromEntries(ROWS.map(([iata, icao, name, lat, lon]) => [iata, { iata, icao, name, lat, lon }]));
export const AIRPORTS_BY_ICAO: Record<string, AirportRef> = Object.fromEntries(ROWS.map(([iata, icao, name, lat, lon]) => [icao, { iata, icao, name, lat, lon }]));

export const airport = (code: string | null | undefined): AirportRef | undefined => (code ? (AIRPORTS[code.toUpperCase()] ?? AIRPORTS_BY_ICAO[code.toUpperCase()]) : undefined);

/** IATA for an ICAO station ("EIDW" → "DUB"), for the hub of a storm run. */
export const iataOf = (station: string) => AIRPORTS_BY_ICAO[station.toUpperCase()]?.iata ?? station;
