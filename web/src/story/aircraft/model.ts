import manifest from "../data/aircraftModel.json";
import { asset } from "../data/assets";

/** Shared by SVG projections, the animated model, stills and fallback images. */
export const AIRCRAFT = manifest;
export const MODEL_URL = asset(`${manifest.model}?v=${manifest.revision}`);
export const POSTER_SMALL = asset(
  `${manifest.posters.small}?v=${manifest.revision}`,
);
export const POSTER_LARGE = asset(
  `${manifest.posters.large}?v=${manifest.revision}`,
);
