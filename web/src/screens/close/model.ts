import type { Cents, Commit, CurveSegment, InvariantResult, JournalEntry, MonthEndResponse, Role, Rollforward, RollforwardRow, TraceEvent } from "@/api/types";
import { eur } from "@/lib/format";
import { plainIds } from "@/lib/plain";

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
 * shown negative whatever sign the API stores them with; `signed` lines keep the API's sign. `plain` says
 * what the line means in words (the summary); `note` gives its accounts (the detail).
 */
export const MOVEMENTS: { key: MovementKey; label: string; plain: string; note?: string; direction: "in" | "out" | "signed" }[] = [
  { key: "new_cents", label: "New storms", plain: "first estimate of what passengers will claim", note: "day-1 estimate · Dr 4090 / Cr 2140", direction: "in" },
  { key: "claims_approved_cents", label: "Claims approved", plain: "moved out to claims payable, at face value", note: "Dr 2140 / Cr 2141, at face value", direction: "out" },
  { key: "settled_in_kind_cents", label: "Settled in kind", plain: "the passenger signed for a voucher instead", note: "signed vouchers · Dr 2140 / Cr 2132", direction: "out" },
  { key: "change_in_estimate_cents", label: "Change in estimate (IAS 8.36)", plain: "re-estimated as claims came in; applies from this month on", note: "BF true-up, prospective · 4090 ↔ 2140", direction: "signed" },
  { key: "recode_cents", label: "Recodes", plain: "a flight's cause was corrected", note: "cause corrected · change in estimate (IAS 8.36)", direction: "signed" },
  { key: "out_of_period_cents", label: "Prior-period error, corrected in current period (immaterial)", plain: "a miss fixed this month; the locked month is untouched", note: "IAS 8.42 · locked period untouched", direction: "signed" },
  { key: "derecognised_cents", label: "Derecognised at limitation", plain: "the six-year window to claim has closed", note: "6-year limitation · Dr 2140 / Cr 4090", direction: "out" },
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

/** Which journal kinds make up each movement of 2140. */
const KIND_MOVEMENT: Partial<Record<JournalEntry["kind"], MovementKey>> = {
  compensation_estimate: "new_cents",
  claim_approved: "claims_approved_cents",
  voucher_in_lieu: "settled_in_kind_cents",
  change_in_estimate: "change_in_estimate_cents",
  recode: "recode_cents",
  out_of_period_adjustment: "out_of_period_cents",
  derecognition: "derecognised_cents",
};

/** An entry's effect on the liability: credits to 2140 raise it, debits lower it. */
export const effectOn2140 = (je: JournalEntry, account = "2140") => je.lines.filter((l) => l.account === account).reduce((s, l) => s + (l.cr_cents ?? 0) - (l.dr_cents ?? 0), 0);

/** A drafted release proposal ("reduce to nil at M12"): gated, so it moves 2140 only once the Controller approves it. */
export const isReleaseProposal = (je: Pick<JournalEntry, "status" | "estimate_ref">) => je.status === "draft" && !!je.estimate_ref?.startsWith("release:");
export const releaseProposals = (entries: JournalEntry[] | undefined) => (entries ?? []).filter(isReleaseProposal);

/**
 * Tick and tie: for each movement, the period's journals of that kind and whether their effect on 2140
 * agrees with the movement's total. Only entries that touch 2140 count.
 */
export function journalTies(rf: Rollforward, entries: JournalEntry[]) {
  const totals = rollforwardTotals(rf).movements;
  const out: Partial<Record<MovementKey, { ids: string[]; cents: Cents; agrees: boolean }>> = {};
  for (const je of entries) {
    const key = KIND_MOVEMENT[je.kind];
    if (!key || je.period !== rf.period || isReleaseProposal(je)) continue;
    const effect = effectOn2140(je);
    if (!effect) continue;
    const t = (out[key] ??= { ids: [], cents: 0, agrees: false });
    t.ids.push(je.id);
    t.cents += effect;
  }
  for (const [key, t] of Object.entries(out) as [MovementKey, { ids: string[]; cents: Cents; agrees: boolean }][]) t.agrees = t.cents === totals[key];
  return out;
}

/** The note as CSV for the workpapers: movements down, cohorts across, total last; euros, negatives signed. */
export function rollforwardCsv(rf: Rollforward) {
  const t = rollforwardTotals(rf);
  const e = (c: Cents) => (c / 100).toFixed(2);
  const lines = [["Movement", ...rf.rows.map((r) => r.cohort), "Total"]];
  lines.push(["Opening", ...rf.rows.map((r) => e(r.opening_cents)), e(t.opening)]);
  for (const m of MOVEMENTS) lines.push([m.label, ...rf.rows.map((r) => e(movementCents(r, m.key))), e(t.movements[m.key])]);
  lines.push(["Closing", ...rf.rows.map((r) => e(r.closing_cents)), e(rf.closing_total_cents)]);
  lines.push(["GL 2140 balance", ...rf.rows.map(() => ""), e(rf.gl_balance_cents)]);
  lines.push(["Memo: unclaimed entitlement", ...rf.rows.map((r) => e(r.unclaimed_entitlement_cents)), e(t.unclaimed)]);
  const cell = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  return lines.map((l) => l.map(cell).join(",")).join("\n");
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

/** "EIDW@2025-01-24:medium_1500_3500" → station, date and the segment the cohort is split by (if any). */
export function cohortParts(cohort: string) {
  const [base, suffix] = cohort.split(":");
  const [station, rest = ""] = base.split("@");
  return { base, station, date: rest.slice(0, 10), segment: isSegment(suffix) ? suffix : null };
}
export const segmentName = (s: string) => SEGMENTS.find((x) => x.id === s)?.name ?? s.replace(/_/g, " ");

/** "Storm Éowyn · medium haul" / "Storm Isha" / the id when the storm has no name. */
export function cohortName(cohort: string, segment?: string | null, name: (base: string) => string | null = () => null) {
  const p = cohortParts(cohort);
  const seg = p.segment ?? segment ?? null;
  return `${name(p.base) ?? p.base}${seg ? ` · ${segmentName(seg).toLowerCase()}` : ""}`;
}

// ---------- periods ----------

/** The close periods: the demo's January and February, plus any later month the journal has entries in (a scenario run). */
export function closePeriods(entries: { period: string }[] | undefined, base: readonly string[] = ["2025-01", "2025-02"]): string[] {
  const out = new Set(base);
  for (const e of entries ?? []) if (/^20\d{2}-(0[1-9]|1[0-2])$/.test(e.period) && e.period >= base[0]) out.add(e.period);
  return [...out].sort();
}

/**
 * A cohort's name in words: the storm's ("Storm Éowyn"), the Iberian blackout for 28 Apr 2025 (a grid
 * outage, not a storm), else its place and date ("Lisbon, 28 Apr 2025"). Names only; every figure is the API's.
 */
export function cohortTitle(base: string, name: (base: string) => string | null): string {
  if (/@2025-04-28$/.test(base)) return "Iberian blackout";
  return name(base) ?? plainIds(base);
}

/** "2025-02" → first and last calendar day, for "At 1 Feb 2025" / "At 28 Feb 2025". */
export function monthBounds(period: string) {
  const [y, m] = period.split("-").map(Number);
  if (!y || !m) return { first: period, last: period };
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const mm = String(m).padStart(2, "0");
  return { first: `${y}-${mm}-01`, last: `${y}-${mm}-${String(last).padStart(2, "0")}` };
}

const PERIOD = /\b(20\d{2}-(?:0[1-9]|1[0-2]))\b/;

const PERIODS_G = /\b(20\d{2}-(?:0[1-9]|1[0-2]))\b/g;

/**
 * Locked periods. The contract has no "locked" field on a period (requested), so this reads the record:
 * LOCKED trace events, `period_lock` commits, the locked-period invariant's detail ("2025-01 locked,
 * untouched"), and locks made in this session.
 */
export function lockedPeriods(events: TraceEvent[] | undefined, commits: Commit[] | undefined, local: string[], invariants?: InvariantResult[]): Set<string> {
  const out = new Set(local);
  for (const inv of invariants ?? []) {
    if (!/locked period/i.test(inv.description) || !/\blocked\b/i.test(inv.detail ?? "")) continue;
    for (const m of (inv.detail ?? "").matchAll(PERIODS_G)) out.add(m[1]);
  }
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
export function liabilityChange(res: MonthEndParts, account = "2140"): Cents {
  return changeByCohort(res, null, account).reduce((s, c) => s + c.cents, 0);
}

type MonthEndParts = Pick<MonthEndResponse, "entries"> & Partial<Pick<MonthEndResponse, "rollforward">>;

/** One storm's change in estimate, as it moves 2140 (its segments summed). */
export type CohortChange = { cohort: string; cents: Cents };

/**
 * The change in estimate storm by storm, read the way liabilityChange reads it (the drafted change-in-estimate
 * entries, else the rollforward). The estimate's own storm (`primary`) comes first, then the largest move.
 */
export function changeByCohort(res: MonthEndParts, primary?: string | null, account = "2140"): CohortChange[] {
  const by = new Map<string, Cents>();
  const add = (cohort: string, cents: Cents) => {
    const base = cohortParts(cohort).base;
    by.set(base, (by.get(base) ?? 0) + cents);
  };
  const cie = (res.entries ?? []).filter((e) => (e.kind === "change_in_estimate" || e.ias8_class === "change_in_estimate") && !isReleaseProposal(e));
  if (cie.length) {
    for (const e of cie) {
      // "BF:EIDW@2025-01-24:long_haul_gt3500@2025-02" names the cohort when a line carries no cohort dim
      const fromRef = e.estimate_ref?.split(":")[1] ?? "";
      for (const l of e.lines) if (l.account === account) add(l.dims?.cohort ?? fromRef, (l.cr_cents ?? 0) - (l.dr_cents ?? 0));
    }
  } else {
    for (const r of res.rollforward?.rows ?? []) add(r.cohort, r.change_in_estimate_cents ?? 0);
  }
  const first = primary ? cohortParts(primary).base : null;
  return [...by]
    .filter(([, cents]) => cents !== 0)
    .map(([cohort, cents]) => ({ cohort, cents }))
    .sort((a, b) => Number(b.cohort === first) - Number(a.cohort === first) || Math.abs(b.cents) - Math.abs(a.cents) || a.cohort.localeCompare(b.cohort));
}

/** +€3,990 / −€13,929: a change in words, with a real minus sign (the tables keep the accounting brackets). */
export const signedEur = (cents: Cents) => (cents < 0 ? `−${eur(-cents)}` : eur(cents, { signed: true }));

/** "Storm Éowyn: +€3,990 change in estimate: claims came in faster than expected". */
export function cohortChangeLine(name: string, cents: Cents) {
  const why = cents > 0 ? "claims came in faster than expected" : "fewer claims than expected so far";
  return `${name}: ${signedEur(cents)} change in estimate: ${why}`;
}

/** The three estimate methods, by EstimateCard.selected. */
export const METHOD_NAME: Record<string, string> = { expected_loss: "Expected loss", bf: "Bornhuetter-Ferguson", chain_ladder: "Chain ladder" };

/** Why the estimate moved, in words: claims against the curve, then the direction; "so" only when the two agree. */
export function monthEndReason(ae: number | null | undefined, change: Cents) {
  const dir = change > 0 ? "goes up" : change < 0 ? "comes down" : "holds";
  if (ae === null || ae === undefined) return `The estimate ${dir}.`;
  const pace = ae > 1.005 ? "faster than" : ae < 0.995 ? "slower than" : "in line with";
  const agrees = (pace === "faster than" && change > 0) || (pace === "slower than" && change < 0) || (pace === "in line with" && change === 0);
  return `Claims came in ${pace} the curve expected (${ae.toFixed(2)}×)${agrees ? `, so the estimate ${dir}` : `. The estimate ${dir}`}.`;
}

/** "All 17 hold" / "2 of 17 failing", for the Controls checks header. */
export function invariantsSummary(items: InvariantResult[] | undefined) {
  if (!items?.length) return null;
  const failing = items.filter((i) => !i.ok).length;
  return failing ? `${failing} of ${items.length} failing` : `All ${items.length} hold`;
}

/** The contract's `*_pct` floats: read 0–1 as a fraction and anything above 1 as a percentage. */
export const asFraction = (x: number | null | undefined) => (x === null || x === undefined || Number.isNaN(x) ? null : x > 1 ? x / 100 : x);

// ---------- the CFO bridge ----------

/** One axis from €0 to the full entitlement: where cash basis and drafted ± sensitivity sit. */
export function bridgeScale({ cash, drafted, full, sensitivity }: { cash: Cents; drafted: Cents; full: Cents; sensitivity: Cents }) {
  const band: [Cents, Cents] = [Math.max(0, drafted - Math.abs(sensitivity)), drafted + Math.abs(sensitivity)];
  const max = Math.max(full, cash, band[1], 1);
  const at = (v: Cents) => Math.max(0, Math.min(1, v / max));
  return { max, at, band };
}

/**
 * The CFO bridge's tie-out to GL 2140 at its as-of: drafted (owed) + held for Legal (IFRS 15.56) + every other
 * cohort's balance = Σ cohort closing. Null when the bridge has no cohorts or the parts don't add up.
 */
export function bridgeToGl(m: { drafted_liability_cents: Cents; held_for_legal_cents: Cents; liability_bridge?: RollforwardRow[] | null }) {
  const rows = m.liability_bridge ?? [];
  if (!rows.length) return null;
  const total = rows.reduce((s, r) => s + r.closing_cents, 0);
  const other = total - m.drafted_liability_cents - m.held_for_legal_cents;
  if (other < 0) return null;
  // Cohorts carried in from before (opening balances, no new estimate) explain the rest, when some cohort is
  // new this period; when none is, every cohort is carried in and the rest has no single name.
  const someNew = rows.some((r) => r.new_cents);
  const earlier = someNew ? rows.filter((r) => !r.new_cents && r.closing_cents).map((r) => r.cohort) : [];
  return { total, drafted: m.drafted_liability_cents, held: m.held_for_legal_cents, other, earlier };
}

/** The storms with a new estimate in the bridge, named once each ("Storm Éowyn"), for "What we owe after …". */
export function newStorms(rows: RollforwardRow[] | null | undefined, name: (base: string) => string | null): string[] {
  const out: string[] = [];
  for (const r of rows ?? []) {
    if (!r.new_cents) continue;
    const base = cohortParts(r.cohort).base;
    const label = name(base) ?? base;
    if (!out.includes(label)) out.push(label);
  }
  return out;
}

/** Is the drafted liability exactly rate × entitlement (to the euro)? Then the bridge can say "35% × €99,000". */
export const isRateTimesEntitlement = (drafted: Cents, full: Cents, rate: number | null | undefined) =>
  rate !== null && rate !== undefined && full > 0 && Math.abs(Math.round(rate * full) - drafted) < 100;

// ---------- journal groups ----------

/** The order a controller reads a period's journals in: what moves 2140 first, then everything around it. */
const KIND_ORDER: JournalEntry["kind"][] = ["change_in_estimate", "compensation_estimate", "recode", "out_of_period_adjustment", "claim_approved", "derecognition", "voucher_in_lieu", "voucher_void"];
export const kindRank = (k: JournalEntry["kind"]) => {
  const i = KIND_ORDER.indexOf(k);
  return i < 0 ? KIND_ORDER.length : i;
};

export type JournalGroup = { kind: JournalEntry["kind"]; entries: JournalEntry[]; cents: Cents; moves2140: boolean; net2140: Cents };

/**
 * Entries grouped by kind, each with its count, its total (Σ debits) and its net effect on 2140 (a release
 * proposal left out until approved, as the rollforward leaves it out); the groups that move 2140 come first.
 */
export function journalGroups(entries: JournalEntry[]): JournalGroup[] {
  const by = new Map<JournalEntry["kind"], JournalGroup>();
  for (const je of entries) {
    const g = by.get(je.kind) ?? { kind: je.kind, entries: [], cents: 0, moves2140: false, net2140: 0 };
    g.entries.push(je);
    g.cents += je.lines.reduce((t, l) => t + (l.dr_cents ?? 0), 0);
    g.moves2140 ||= effectOn2140(je) !== 0;
    if (!isReleaseProposal(je)) g.net2140 += effectOn2140(je);
    by.set(je.kind, g);
  }
  return [...by.values()].sort((a, b) => Number(b.moves2140) - Number(a.moves2140) || kindRank(a.kind) - kindRank(b.kind) || a.kind.localeCompare(b.kind));
}
