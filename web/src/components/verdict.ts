import type { Entitlement, FlightDecision, FlightRow } from "@/api/types";
import type { Tone } from "./chips";

/** The kind of verdict a flight carries on the map, the timeline and in chips. */
export type VerdictKind = "weather" | "notweather" | "held" | "operated" | "pending";

export function verdictOf(row: FlightRow): VerdictKind {
  if (row.flight.status === "operated") return "operated";
  const d = row.decision;
  if (!d) return "pending";
  if (d.extraordinary === "needs_legal" || d.outcome === "escalated") return "held";
  if (d.extraordinary === "not_extraordinary") return "notweather";
  return "weather";
}

export const VERDICT_TONE: Record<VerdictKind, Tone> = {
  weather: "weather",
  notweather: "notweather",
  held: "held",
  operated: "slate",
  pending: "outline",
};

/** Mono kebab-case chip text: `weather · no-compensation`, `technical · owed`, `knock-on · needs-ruling`. */
export function verdictChip(d: FlightDecision | null | undefined): { text: string; tone: Tone } {
  if (!d) return { text: "pending", tone: "outline" };
  const cause = d.cause.replace(/_/g, "-");
  if (d.extraordinary === "needs_legal" || d.outcome === "escalated") return { text: `${cause} · needs-ruling`, tone: "held" };
  if (d.extraordinary === "not_extraordinary") return { text: `${cause} · owed`, tone: "notweather" };
  return { text: `${cause} · no-compensation`, tone: "weather" };
}

/** Entitlement status → chip. */
export function entitlementChip(e: Pick<Entitlement, "status">): { text: string; tone: Tone } {
  const text = e.status.replace(/_/g, "-");
  const tone: Tone = e.status === "owed" ? "notweather" : e.status === "held" || e.status === "needs_ruling" ? "held" : e.status === "no_compensation" ? "weather" : "slate";
  return { text, tone };
}

/** CSS colour for a verdict on dark and light grounds (map arcs, timeline ticks). */
export const VERDICT_COLOR: Record<VerdictKind, string> = {
  weather: "var(--color-weather)",
  notweather: "var(--color-notweather)",
  held: "var(--color-held)",
  operated: "var(--color-slate-400)",
  pending: "var(--color-cloud-400)",
};
