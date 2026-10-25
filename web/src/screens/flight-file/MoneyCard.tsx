import type { ReactNode } from "react";
import { Link } from "react-router";
import type { FlightFile } from "@/api/types";
import { MicroLabel } from "@/components/chips";
import { Explain, WhatsThis } from "@/components/explain";
import { Details, Money } from "@/components/kit";
import type { VerdictKind } from "@/components/verdict";
import { count, pct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { bandMarginText, breakdownText, capitalize, draftedLiability, reductionOf, summaryText } from "./lib";

const ENTITLEMENT_KEYS = ["full_entitlement_cents", "entitlement_cents", "compensation_cents"];
const LIABILITY_KEYS = ["drafted_liability_cents", "liability_drafted_cents", "liability_cents"];
const RATE_KEYS = ["claim_rate", "expected_claim_rate", "expected_ultimate_claim_rate", "ultimate_claim_rate"];
const REFUND_KEYS = ["refund_due_cents", "refunds_due_cents", "refund_cents"];

function pick(summary: Record<string, unknown>, keys: string[]): number | null {
  for (const k of keys) {
    const v = summary[k];
    if (typeof v === "number" && Number.isFinite(v)) return v;
  }
  return null;
}

/**
 * What the verdict costs, in one figure and one line: the EU261 compensation liability drafted, as the
 * expected ultimate claim rate × the full Art. 7 entitlement. How the entitlement is made up, the distance
 * band, the learned Art. 7(2) cut and the journal sit behind Details. Server wording first.
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
  const owesMoney = kind !== "weather" && kind !== "operated";
  const showLiability = owesMoney && liability !== null && liability > 0;

  if (!owesMoney) {
    return (
      <section aria-labelledby="money-title" className={cn("rounded-xl bg-card p-5 shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]", className)}>
        <h2 id="money-title">
          <MicroLabel>{kind === "operated" ? "Operated" : "No compensation"}</MicroLabel>
        </h2>
        <p className="mt-2 text-[14px] text-navy-900">
          {kind === "operated" ? (
            capitalize(summaryText(summary, "status_line") ?? "flew as scheduled; nothing to settle")
          ) : (
            <>
              No compensation; refunds and <Explain term="care">care</Explain> still due.
            </>
          )}
        </p>
      </section>
    );
  }

  return (
    <section aria-labelledby="money-title" className={cn("rounded-xl bg-card p-5 shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]", className)}>
      <h2 id="money-title" className="flex items-center gap-1.5">
        <MicroLabel>{kind === "held" ? "Accrued, held for a ruling" : "EU261 compensation liability"}</MicroLabel>
        <WhatsThis term={kind === "held" ? "held-for-legal" : "liability-2140"} className="text-slate-500" />
      </h2>
      {showLiability ? (
        <p className="display-tight mt-2 text-[34px] leading-none text-navy-900" data-testid="liability">
          <Money cents={liability} />
        </p>
      ) : null}
      <p className="mt-2 text-[13px] text-slate-500">{kind === "held" ? "accrued under the IFRS 15.56 constraint until the ruling" : "drafted, pending approval"}</p>
      {rate !== null && entitlement ? (
        <p className="mt-2 text-[13.5px] leading-snug text-slate-600">
          <span className="figure font-semibold text-navy-900">{pct(rate)}</span> <Explain term="claim-rate">expected to claim</Explain> × <Money cents={entitlement} className="font-semibold text-navy-900" />{" "}
          <Explain term="full-entitlement">if every passenger claims</Explain>.
        </p>
      ) : null}
      {showLiability ? (
        <Link to={`/trace?target=${encodeURIComponent(estimate?.id ?? file.flight.id)}`} className="mt-2.5 inline-block text-[12.5px] font-medium text-metar-ink hover:underline">
          Why this amount? € → entitlement → rule → evidence
        </Link>
      ) : null}

      <Details summary="How we got this" className="mt-3 border-t border-cloud-100 pt-3">
        <dl className="flex flex-col gap-2.5 text-[13px]">
          {entitlement !== null && entitlement > 0 ? (
            <Row label={capitalize(summaryText(summary, "full_entitlement_label")?.replace(/^€[\d,]+\s*/, "") ?? "full Art. 7 entitlement if every passenger claims")} value={<Money cents={entitlement} className="text-navy-900" />}>
              {breakdown ? <span className="tabular-nums">{breakdown}</span> : null}
            </Row>
          ) : null}
          {rate !== null ? <Row label={capitalize(summaryText(summary, "claim_rate_label")?.replace(/^\d+%\s*/, "") ?? "expected ultimate claim rate (history to M18 + tail judgment)")} value={<span className="figure text-navy-900">{pct(rate)}</span>} /> : null}
          {refunds !== null && refunds > 0 ? <Row label="Refunds elected" value={<Money cents={refunds} className="text-navy-900" />} /> : null}
          {band ? (
            <div>
              <dt className="text-slate-500">Distance band (sets €250, €400 or €600)</dt>
              <dd className="mt-0.5 text-[13px] font-medium tabular-nums text-navy-900">{band}</dd>
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
      </Details>

      {estimate ? (
        <p className="-mx-5 -mb-5 mt-4 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-cloud-100 px-5 py-3 font-mono text-[11.5px] text-slate-500">
          <Explain term="dr-cr">{estimate.lines.map((l) => `${l.dr_cents ? "Dr" : "Cr"} ${l.account}`).join(" / ")}</Explain>
          <span className="text-cloud-400">·</span>
          <Link to={`/close#${estimate.id}`} className="text-navy-900 hover:underline" title="Open the draft in Liability & Close">
            {estimate.id}
          </Link>
          <span className="text-cloud-400">·</span>
          <span className="micro text-[10px]">{estimate.status === "draft" ? "not yet posted · pending approval" : estimate.status === "approved" ? "approved · parked" : estimate.status}</span>
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
