import type { Cents, Commit, CurveSegment, MonthEndResponse, Role, Rollforward, RollforwardRow, TraceEvent } from "@/api/types";

// ---------- the 2140 rollforward, read the way an IFRS liability note reads ----------

export type MovementKey =
  | "new_cents"
  | "claims_approved_cents"
  | "settled_in_kind_cents"
  | "change_in_estimate_cents"
  | "recode_cents"
  | "out_of_period_cents"
  | "derecognised_cents";

/**
 * Movements between opening and closing, in note order. `out` lines only ever reduce 2140, so they are
 * shown negative whatever sign the API stores them with; `signed` lines keep the API's sign.
 */
export const MOVEMENTS: { key: MovementKey; label: string; note?: string; direction: "in" | "out" | "signed" }[] = [
  { key: "new_cents", label: "New cohorts", note: "day-1 estimate", direction: "in" },
  { key: "claims_approved_cents", label: "Claims approved", note: "to 2141, at face value", direction: "out" },
  { key: "settled_in_kind_cents", label: "Settled in kind", note: "signed vouchers, to 2132", direction: "out" },
  { key: "change_in_estimate_cents", label: "Change in estimate (IAS 8.36)", direction: "signed" },
  { key: "recode_cents", label: "Recodes", note: "cause corrected", direction: "signed" },
  { key: "out_of_period_cents", label: "Prior-period error, corrected in current period (immaterial)", direction: "signed" },
  { key: "derecognised_cents", label: "Derecognised at limitation", direction: "out" },
];

const DIRECTION = Object.fromEntries(MOVEMENTS.map((m) => [m.key, m.direction])) as Record<MovementKey, "in" | "out" | "signed">;

/** A movement as it moves 2140: reductions negative. */
export function movementCents(row: RollforwardRow, key: MovementKey): Cents {
  const v = row[key] ?? 0;
  const d = DIRECTION[key];
  if (d === "out") return -Math.abs(v);
  if (d === "in") return Math.abs(v);
  return v;
}

/** Opening + movements = closing? The difference is closing minus what the movements give. */
export function footRow(row: RollforwardRow) {
  const computed = MOVEMENTS.reduce((s, m) => s + movementCents(row, m.key), row.opening_cents);
  return { foots: computed === row.closing_cents, computed, difference: row.closing_cents - computed };
}

export function rollforwardTotals(rf: Rollforward) {
  const movements = Object.fromEntries(MOVEMENTS.map((m) => [m.key, rf.rows.reduce((s, r) => s + movementCents(r, m.key), 0)])) as Record<MovementKey, Cents>;
  const closing = rf.rows.reduce((s, r) => s + r.closing_cents, 0);
  return {
    opening: rf.rows.reduce((s, r) => s + r.opening_cents, 0),
    movements,
    closing,
    unclaimed: rf.rows.reduce((s, r) => s + r.unclaimed_entitlement_cents, 0),
    everyRowFoots: rf.rows.every((r) => footRow(r).foots),
    crossFoots: closing === rf.closing_total_cents,
  };
}

/** True when a movement line is nil in every cohort (shown, but quietly). */
export const isNilLine = (rf: Rollforward, key: MovementKey) => rf.rows.every((r) => !r[key]);

/** IAS 8 classes in the wording table's words. */
export const IAS8_LABEL: Record<string, string> = {
  change_in_estimate: "change in estimate (IAS 8.36)",
  prior_period_error: "prior-period error, corrected in current period (immaterial)",
};

// ---------- claim-curve segments (EU261 Art. 7 distance bands) ----------

export const SEGMENTS: { id: CurveSegment; name: string; band: string }[] = [
  { id: "long_haul_gt3500", name: "Long haul", band: "over 3,500 km" },
  { id: "medium_1500_3500", name: "Medium haul", band: "1,500–3,500 km" },
  { id: "short_le1500", name: "Short haul", band: "up to 1,500 km" },
];

export const isSegment = (s: string | null | undefined): s is CurveSegment => SEGMENTS.some((x) => x.id === s);
export const segmentName = (s: string) => SEGMENTS.find((x) => x.id === s)?.name ?? s.replace(/_/g, " ");

// ---------- periods ----------

/** "2025-02" → first and last calendar day, for "At 1 Feb 2025" / "At 28 Feb 2025". */
export function monthBounds(period: string) {
  const [y, m] = period.split("-").map(Number);
  if (!y || !m) return { first: period, last: period };
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const mm = String(m).padStart(2, "0");
  return { first: `${y}-${mm}-01`, last: `${y}-${mm}-${String(last).padStart(2, "0")}` };
}

const PERIOD = /\b(20\d{2}-(?:0[1-9]|1[0-2]))\b/;

/**
 * Locked periods. The contract has no "locked" field on a period (requested), so this reads the record:
 * LOCKED trace events, `period_lock` commits, and locks made in this session.
 */
export function lockedPeriods(events: TraceEvent[] | undefined, commits: Commit[] | undefined, local: string[]): Set<string> {
  const out = new Set(local);
  for (const e of events ?? []) {
    if (e.chip !== "LOCKED") continue;
    const hit = (e.ref ?? "").match(PERIOD) ?? e.summary.match(PERIOD);
    if (hit) out.add(hit[1]);
  }
  for (const c of commits ?? []) {
    if (c.kind !== "period_lock") continue;
    const hit = c.payload_ref.match(PERIOD) ?? c.message.match(PERIOD);
    if (hit) out.add(hit[1]);
  }
  return out;
}

// ---------- people ----------

const SEATS: Role[] = ["claims_lead", "controller", "legal", "cfo", "ops", "judge"];
const AGENTS: Role[] = ["agent.reader", "agent.drafter", "agent.engine", "agent.crm_bot"];

/** "user:controller:Controller" → controller; "Claims Lead" → claims_lead; "agent.engine" → agent.engine. */
export function preparerRole(principal: string | null | undefined): Role | null {
  if (!principal) return null;
  const s = principal.toLowerCase();
  for (const a of AGENTS) if (s.includes(a)) return a;
  // Words, with "claims lead" / "claims-lead" / "claims_lead" all becoming ["claims", "lead"].
  const words = s.split(/[^a-z0-9]+/).filter(Boolean);
  for (const seat of SEATS) {
    const parts = seat.split("_");
    for (let i = 0; i + parts.length <= words.length; i++) if (parts.every((p, j) => words[i + j] === p)) return seat;
  }
  return null;
}

// ---------- month-end ----------

/**
 * The change in estimate the month-end drafted, as it moves 2140 (credit = the liability goes up):
 * read off the returned change-in-estimate entries, else off the returned rollforward.
 */
export function liabilityChange(res: Pick<MonthEndResponse, "entries"> & Partial<Pick<MonthEndResponse, "rollforward">>, account = "2140"): Cents {
  const cie = (res.entries ?? []).filter((e) => e.kind === "change_in_estimate" || e.ias8_class === "change_in_estimate");
  if (cie.length) {
    return cie.reduce((s, e) => s + e.lines.filter((l) => l.account === account).reduce((t, l) => t + (l.cr_cents ?? 0) - (l.dr_cents ?? 0), 0), 0);
  }
  return (res.rollforward?.rows ?? []).reduce((s, r) => s + (r.change_in_estimate_cents ?? 0), 0);
}

/** The contract's `*_pct` floats: read 0–1 as a fraction and anything above 1 as a percentage. */
export const asFraction = (x: number | null | undefined) => (x === null || x === undefined || Number.isNaN(x) ? null : x > 1 ? x / 100 : x);

// ---------- the CFO bridge ----------

/** One axis from €0 to the full entitlement: where cash basis, drafted ± sensitivity and the method range sit. */
export function bridgeScale({ cash, drafted, full, sensitivity, range }: { cash: Cents; drafted: Cents; full: Cents; sensitivity: Cents; range: [Cents, Cents] | null | undefined }) {
  const band: [Cents, Cents] = [Math.max(0, drafted - Math.abs(sensitivity)), drafted + Math.abs(sensitivity)];
  const r = range && range[1] > range[0] ? ([Math.max(0, range[0]), range[1]] as [Cents, Cents]) : null;
  const max = Math.max(full, cash, band[1], r?.[1] ?? 0, 1);
  const at = (v: Cents) => Math.max(0, Math.min(1, v / max));
  return { max, at, band, range: r };
}
