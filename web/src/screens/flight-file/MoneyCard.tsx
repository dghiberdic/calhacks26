import type { ReactNode } from "react";
import { Link } from "react-router";
import type { FlightFile } from "@/api/types";
import { MicroLabel } from "@/components/chips";
import { Money } from "@/components/kit";
import type { VerdictKind } from "@/components/verdict";
import { count, pct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { bandMarginText, breakdownText, capitalize, draftedLiability, reductionOf, summaryText } from "./lib";

const ENTITLEMENT_KEYS = ["full_entitlement_cents", "entitlement_cents", "compensation_cents"];
const LIABILITY_KEYS = ["drafted_liability_cents", "liability_drafted_cents", "liability_cents"];
const RATE_KEYS = ["claim_rate", "expected_claim_rate", "ultimate_claim_rate"];
const REFUND_KEYS = ["refund_due_cents", "refunds_due_cents", "refund_cents"];

function pick(summary: Record<string, unknown>, keys: string[]): number | null {
  for (const k of keys) {
    const v = summary[k];
    if (typeof v === "number" && Number.isFinite(v)) return v;
  }
  return null;
}

/**
 * What the verdict costs, in the plan's words: the EU261 compensation liability drafted (not €0, not the
 * full entitlement), the full Art. 7 entitlement if every passenger claims and how it is made up, the
 * expected ultimate claim rate, the distance band margin and any learned Art. 7(2) cut. Server wording first.
 */
export function MoneyCard({ file, kind, className }: { file: FlightFile; kind: VerdictKind; className?: string }) {
  const summary = file.entitlements_summary ?? {};
  const liability = draftedLiability(file.journal_preview ?? []) ?? pick(summary, LIABILITY_KEYS);
  const entitlement = pick(summary, ENTITLEMENT_KEYS);
  const rate = pick(summary, RATE_KEYS);
  const refunds = pick(summary, REFUND_KEYS);
  const sample = file.sample_entitlements?.[0];
  const band = summaryText(summary, "band_label") ?? (sample ? bandMarginText(sample) : null);
  const breakdown = breakdownText(summary);
  const cut = reductionOf(summary);
  const estimate = file.journal_preview?.find((j) => j.kind === "compensation_estimate");
  const showLiability = kind !== "weather" && kind !== "operated" && liability !== null && liability > 0;

  const headline =
    kind === "operated"
      ? { label: "Operated", note: capitalize(summaryText(summary, "status_line") ?? "flew as scheduled; nothing to settle") }
      : kind === "weather"
      ? { label: "No compensation", note: "No compensation; refunds and care still due" }
      : kind === "held"
        ? { label: "Accrued, held for a ruling", note: "under the IFRS 15.56 constraint, at the segment's claim rate" }
        : { label: "EU261 compensation liability", note: "drafted, pending approval" };
  const rateLine = summaryText(summary, "claim_rate_label") ?? (rate !== null ? `${pct(rate)} expected ultimate claim rate (history to M18 + tail judgment)` : null);

  return (
    <section aria-labelledby="money-title" className={cn("rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]", className)}>
      <div className="p-5">
        <h2 id="money-title">
          <MicroLabel>{headline.label}</MicroLabel>
        </h2>
        {showLiability ? (
          <p className="display-tight mt-2 text-[34px] leading-none text-navy-900" data-testid="liability">
            <Money cents={liability} />
          </p>
        ) : null}
        <p className={cn(showLiability ? "mt-2 text-[13px] text-slate-500" : "mt-2 text-[14px] text-navy-900")}>{headline.note}</p>
        {rateLine && kind !== "weather" && kind !== "operated" ? <p className="mt-1 text-[13px] leading-snug text-slate-500">{capitalize(rateLine)}</p> : null}
      </div>

      <dl className="flex flex-col gap-2.5 border-t border-cloud-100 px-5 py-3.5 text-[13px]">
        {entitlement !== null && entitlement > 0 ? (
          <Row label={capitalize(summaryText(summary, "full_entitlement_label") ?? "full Art. 7 entitlement if every passenger claims")} value={<Money cents={entitlement} className="text-navy-900" />}>
            {breakdown ? <span className="tabular-nums">{breakdown}</span> : null}
          </Row>
        ) : null}
        {refunds !== null && refunds > 0 ? <Row label="Refunds elected" value={<Money cents={refunds} className="text-navy-900" />} /> : null}
        {band ? (
          <div>
            <dt className="text-slate-500">Distance band</dt>
            <dd className="mt-0.5 text-[13.5px] font-medium tabular-nums text-navy-900">{band}</dd>
          </div>
        ) : null}
        {cut ? (
          <div>
            <dt className="text-slate-500">Learned from history</dt>
            <dd className="mt-0.5 text-[13px] leading-snug text-navy-900">
              {capitalize(cut.label)}
              <span className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-[12px] text-slate-500">
                {cut.coupons !== null ? <span>{count(cut.coupons)} coupons</span> : null}
                {cut.support ? <span>· {cut.support} in history</span> : null}
                {cut.ruleRef ? (
                  <Link to={`/policies#${encodeURIComponent(cut.ruleRef.split("@")[0])}`} className="font-mono text-[11.5px] text-metar-ink hover:underline">
                    · {cut.ruleRef}
                  </Link>
                ) : null}
              </span>
            </dd>
          </div>
        ) : null}
      </dl>

      {estimate ? (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-cloud-100 px-5 py-3 font-mono text-[11.5px] text-slate-500">
          {estimate.lines.map((l) => `${l.dr_cents ? "Dr" : "Cr"} ${l.account}`).join(" / ")}
          <span className="text-cloud-400">·</span>
          <span className="text-navy-900">{estimate.id}</span>
          <span className="text-cloud-400">·</span>
          <span className="micro text-[10px]">{estimate.status === "draft" ? "not yet posted" : estimate.status}</span>
        </p>
      ) : null}
    </section>
  );
}

function Row({ label, value, children }: { label: string; value: ReactNode; children?: ReactNode }) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-right">{value}</dd>
      {children ? <dd className="col-span-2 mt-0.5 text-[12px] text-slate-500">{children}</dd> : null}
    </div>
  );
}
