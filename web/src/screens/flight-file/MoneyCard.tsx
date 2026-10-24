import type { ReactNode } from "react";
import { Link } from "react-router";
import type { FlightFile } from "@/api/types";
import { MicroLabel } from "@/components/chips";
import { Money } from "@/components/kit";
import type { VerdictKind } from "@/components/verdict";
import { pct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { bandMarginText, draftedLiability } from "./lib";

const ENTITLEMENT_KEYS = ["full_entitlement_cents", "entitlement_cents", "compensation_cents", "full_art7_cents"];
const RATE_KEYS = ["expected_claim_rate", "claim_rate", "ultimate_claim_rate", "expected_ultimate_claim_rate"];
const REFUND_KEYS = ["refund_due_cents", "refunds_due_cents", "refunds_cents"];

function pick(summary: Record<string, unknown>, keys: string[]): number | null {
  for (const k of keys) {
    const v = summary[k];
    if (typeof v === "number" && Number.isFinite(v)) return v;
  }
  return null;
}

/**
 * What the verdict costs, in the plan's words: the EU261 compensation liability drafted (not €0, not the
 * full entitlement), the full Art. 7 entitlement if every passenger claims, the expected ultimate claim
 * rate, and the distance band margin. Every figure comes from the flight file.
 */
export function MoneyCard({ file, kind, className }: { file: FlightFile; kind: VerdictKind; className?: string }) {
  const summary = file.entitlements_summary ?? {};
  const liability = draftedLiability(file.journal_preview ?? []) ?? pick(summary, ["drafted_liability_cents", "liability_drafted_cents", "liability_cents"]);
  const entitlement = pick(summary, ENTITLEMENT_KEYS);
  const rate = pick(summary, RATE_KEYS);
  const refunds = pick(summary, REFUND_KEYS);
  const sample = file.sample_entitlements?.[0];
  const estimate = file.journal_preview?.find((j) => j.kind === "compensation_estimate");

  const headline =
    kind === "weather"
      ? { label: "No compensation", note: "no compensation; refunds and care still due" }
      : kind === "held"
        ? { label: "Accrued, held for a ruling", note: "under the IFRS 15.56 constraint, at the segment's claim rate" }
        : { label: "EU261 compensation liability", note: "drafted, pending approval" };

  return (
    <section aria-labelledby="money-title" className={cn("rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]", className)}>
      <div className="p-5">
        <h2 id="money-title">
          <MicroLabel>{headline.label}</MicroLabel>
        </h2>
        {kind !== "weather" && liability !== null ? (
          <p className="display-tight mt-2 text-[34px] leading-none text-navy-900" data-testid="liability">
            <Money cents={liability} />
          </p>
        ) : null}
        <p className={cn("text-[13px] text-slate-500", kind !== "weather" && liability !== null ? "mt-2" : "mt-2 text-[14px] text-navy-900")}>{headline.note}</p>
        {rate !== null && kind !== "weather" ? (
          <p className="mt-1 text-[13px] text-slate-500">
            <span className="figure text-navy-900">{pct(rate)}</span> expected ultimate claim rate (history to M18 + tail judgment)
          </p>
        ) : null}
      </div>

      <dl className="border-t border-cloud-100 px-5 py-3.5 text-[13px]">
        {entitlement !== null ? (
          <Row label="Full Art. 7 entitlement if every passenger claims">
            <Money cents={entitlement} className="text-navy-900" />
          </Row>
        ) : null}
        {refunds !== null ? (
          <Row label="Refunds due">
            <Money cents={refunds} className="text-navy-900" />
          </Row>
        ) : null}
        {sample ? (
          <div className="pt-2">
            <dt className="text-slate-500">Distance band</dt>
            <dd className="mt-0.5 text-[13.5px] font-medium tabular-nums text-navy-900">{bandMarginText(sample)}</dd>
          </div>
        ) : null}
      </dl>

      {estimate ? (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-cloud-100 px-5 py-3 font-mono text-[11.5px] text-slate-500">
          {estimate.lines.map((l) => `${l.dr_cents ? "Dr" : "Cr"} ${l.account}`).join(" / ")}
          <span className="text-cloud-400">·</span>
          <Link to={`/trace?target=${encodeURIComponent(estimate.id)}`} className="text-metar-ink hover:underline">
            {estimate.id}
          </Link>
          <span className="text-cloud-400">·</span>
          <span className="micro text-[10px]">{estimate.status === "draft" ? "not yet posted" : estimate.status}</span>
        </p>
      ) : null}
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4 gap-y-0.5 py-1.5">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-right">{children}</dd>
    </div>
  );
}
