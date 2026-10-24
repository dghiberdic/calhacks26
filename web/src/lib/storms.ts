/** Met Éireann storm names for the station-days in the demo world (names only; every number comes from the API). */
const NAMES: Record<string, string> = {
  "EIDW@2025-01-24": "Storm Éowyn",
  "EIDW@2025-01-26": "Storm Herminia",
  "EIDW@2024-01-21": "Storm Isha",
  "EIDW@2023-11-02": "Storm Ciarán",
  "EIDW@2023-11-12": "Storm Debi",
  "EIDW@2024-01-23": "Storm Jocelyn",
  "EIDW@2024-04-10": "Storm Kathleen",
  "EIDW@2024-09-27": "Storm Ashley",
  "EIDW@2024-12-07": "Storm Darragh",
};

export const stormName = (id: string | null | undefined) => (id ? (NAMES[id] ?? null) : null);

/** The hero storm when the URL doesn't name one. */
export const HERO_STORM = "EIDW@2025-01-24";
