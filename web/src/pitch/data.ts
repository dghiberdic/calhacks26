import { useCfo, useEvalReport, useStormRun, useStorms } from "@/api/queries";
import type { CfoMetrics, EvalReport, FlightRow, Question, StormRun, StormSummary } from "@/api/types";
import { HERO_STORM } from "@/lib/storms";

/**
 * Everything the deck reads, fetched once when it opens so moving between slides never waits.
 * Every number on a slide comes from here; a slide shows a quiet placeholder until it arrives.
 */
export type PitchData = {
  run?: StormRun;
  /** The next storm at the same station (Herminia), where the Claims Lead's ruling is reused. */
  next?: StormRun;
  cfo?: CfoMetrics;
  evalReport?: EvalReport;
};

/** The first storm after the hero one at the same station. */
export function nextStormId(storms: StormSummary[] | undefined, heroId = HERO_STORM): string | undefined {
  const hero = storms?.find((s) => s.id === heroId);
  if (!storms || !hero) return undefined;
  return storms
    .filter((s) => s.station === hero.station && s.date > hero.date)
    .sort((a, b) => a.date.localeCompare(b.date))[0]?.id;
}

export function usePitchData(): PitchData {
  const storms = useStorms();
  const run = useStormRun(HERO_STORM);
  const next = useStormRun(nextStormId(storms.data));
  const cfo = useCfo();
  const evalReport = useEvalReport();
  return { run: run.data, next: next.data, cfo: cfo.data, evalReport: evalReport.data };
}

// ---------- selectors (pure, tested) ----------

export const passengers = (run?: StormRun) => run?.counters?.passengers;

/** The cancellation the engine recoded: NS31, "71 → 41". */
export const recodedRow = (run?: StormRun): FlightRow | undefined => run?.flights.find((r) => r.decision?.recoded);

/** "172 payouts drafted, pending Claims Lead approval". */
export const payoutsDrafted = (run?: StormRun) => run?.counters?.drafted ?? recodedRow(run)?.flight.pax;

/** Q1: the service-desk voucher in lieu, routed to the Claims Lead. */
export function voucherQuestion(run?: StormRun): Question | undefined {
  const qs = run?.questions ?? [];
  return qs.find((q) => q.pattern === "voucher_in_lieu_unsigned") ?? qs.find((q) => q.routed_to === "claims_lead");
}

/** Cases the next storm settled by citing a ruling ("31 voucher cases settled, ruling cited"); none before the ruling. */
export const citedNextStorm = (next?: StormRun) => {
  const n = next?.counters?.rules_cited;
  return n && n > 0 ? n : undefined;
};

/** Drafted liability as a share of the full entitlement: the expected ultimate claim rate it applied. */
export const claimRate = (cfo?: CfoMetrics) => (cfo && cfo.full_entitlement_cents > 0 ? cfo.drafted_liability_cents / cfo.full_entitlement_cents : undefined);

export type Proof = {
  /** Plain Claude on the same raw documents, in euros (CONTRACTS: `liability_eur`). */
  baselineEur: number[];
  baselineSameHash: boolean;
  stormcheckEur: number[];
  stormcheckSameHash: boolean;
  straightThrough?: number;
  miscodes?: { caught: number; total: number };
  repeatQuestions?: number;
  /** "2023-07..2024-12" style ranges, as the eval reports them. */
  learn?: string;
  score?: string;
  label?: string;
};

const euros = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is number => typeof x === "number" && Number.isFinite(x)) : []);

export function proofOf(r?: EvalReport): Proof | undefined {
  if (!r) return undefined;
  const split = r.split ?? {};
  return {
    baselineEur: euros(r.baseline?.liability_eur),
    baselineSameHash: r.baseline?.hash_identical === true,
    stormcheckEur: euros(r.stormcheck_runs?.liability_eur),
    stormcheckSameHash: r.stormcheck_runs?.hash_identical === true,
    straightThrough: r.straight_through_pct,
    miscodes: Number.isFinite(r.miscodes_total) && r.miscodes_total > 0 ? { caught: r.miscodes_caught, total: r.miscodes_total } : undefined,
    repeatQuestions: r.repeat_questions,
    learn: split.learn ?? split.train,
    score: split.score ?? split.test,
    label: r.label,
  };
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2023-07..2024-12" → "Jul 2023 – Dec 2024"; anything else is shown as it came. */
export function monthRange(range: string | undefined): string | undefined {
  if (!range) return undefined;
  const m = range.match(/^(\d{4})-(\d{2})(?:-\d{2})?\s*(?:\.\.|–|-|\/|to)\s*(\d{4})-(\d{2})(?:-\d{2})?$/);
  if (!m) return range;
  const [, y0, m0, y1, m1] = m;
  return `${MONTHS[Number(m0) - 1]} ${y0} – ${MONTHS[Number(m1) - 1]} ${y1}`;
}
