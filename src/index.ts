import type { PlzResult, BundestagEntry, LandtagEntry } from "./types";
import rawData from "./data.json";

export type { Wahlkreis, BundestagEntry, LandtagEntry, PlzResult } from "./types";

const data = rawData as Record<
  string,
  { bundestag: BundestagEntry | null; landtage: LandtagEntry[] }
>;

/**
 * Get all constituency data for a PLZ (Bundestag + Landtag).
 * Returns null if the PLZ is not found.
 */
export function getConstituencies(plz: string): PlzResult | null {
  const entry = data[plz];
  if (!entry) return null;
  return { plz, ...entry };
}

/**
 * Get the Bundestag constituency for a PLZ.
 * Returns null if the PLZ is not found or has no Bundestag data.
 */
export function getBundestagWahlkreis(plz: string): BundestagEntry | null {
  return data[plz]?.bundestag ?? null;
}

/**
 * Get Landtag constituencies for a PLZ.
 * Optionally filter by state slug (e.g. "bayern", "nrw").
 * Returns an empty array if the PLZ is not found.
 */
export function getLandtagWahlkreise(
  plz: string,
  state?: string
): LandtagEntry[] {
  const entries = data[plz]?.landtage ?? [];
  if (state) return entries.filter((e) => e.state === state);
  return entries;
}
