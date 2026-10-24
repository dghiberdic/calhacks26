import type { ReactNode } from "react";
import { motion, useReducedMotion } from "motion/react";
import type { CfoMetrics, ClaimCurve } from "@/api/types";
import { MicroLabel } from "@/components/chips";
import { count, eur, longDate, pct, zulu } from "@/lib/format";
import { cn } from "@/lib/utils";
import { asFraction, bridgeScale } from "./model";

const EASE = [0.16, 1, 0.3, 1] as const;

/**
 * The CFO bridge: "Cash basis €0 · full entitlement €99,000 · drafted €34,650 (±5pp ±€4,950)", and one
 * axis that shows why the drafted liability is neither end.
 */
export function CfoBridge({ metrics, curve }: { metrics: CfoMetrics; curve?: ClaimCurve }) {
  const m = metrics;
  const s = bridgeScale({ cash: m.cash_basis_cents, drafted: m.drafted_liability_cents, full: m.full_entitlement_cents, sensitivity: m.sensitivity_5pp_cents, range: m.method_range_cents });
  const reduce = useReducedMotion();
  const x = (v: number) => `${(s.at(v) * 100).toFixed(3)}%`;
  const drafted = s.at(m.drafted_liability_cents);
  // Keep the drafted tag inside the axis when the liability sits near an end.
  const tagAlign = drafted < 0.14 ? "left" : drafted > 0.86 ? "right" : "center";
  const refunds = asFraction(m.refunds_within_7d_pct);

  return (
    <section aria-labelledby="cfo-bridge" className="overflow-hidden rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]">
      <div className="px-5 pt-5 md:px-7 md:pt-6">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
          <MicroLabel>
            CFO bridge · EU261 compensation liability<span className="hidden sm:inline"> · reduction of passenger revenue</span>
          </MicroLabel>
          <span className="figure text-[12px] text-slate-400">
            as of {longDate(m.as_of)} · {zulu(m.as_of)}
          </span>
        </div>
        <h2 id="cfo-bridge" className="display-tight mt-3 text-[21px] leading-[1.18] text-pretty sm:text-[24px] md:text-[28px]">
          <span className="text-slate-400">
            Cash basis {eur(m.cash_basis_cents)} · full entitlement {eur(m.full_entitlement_cents)} ·{" "}
          </span>
          <span className="whitespace-nowrap text-navy-900">drafted {eur(m.drafted_liability_cents)}</span>{" "}
          <span className="whitespace-nowrap text-slate-500">(±5pp ±{eur(m.sensitivity_5pp_cents)})</span>
        </h2>
        <p className="mt-2 max-w-[78ch] text-[13.5px] leading-relaxed text-slate-500">
          {curve ? (
            <>
              <span className="text-navy-900">
                {pct(curve.ultimate)} expected ultimate claim rate (history to M{curve.observed_through_month} + tail judgment)
              </span>
              {" · "}
            </>
          ) : null}
          drafted, pending approval
        </p>
      </div>

      {/* One axis, €0 → the full entitlement. */}
      <figure className="relative mx-5 mb-1 mt-7 md:mx-7" aria-label={`Drafted ${eur(m.drafted_liability_cents)} on an axis from cash basis ${eur(m.cash_basis_cents)} to the full entitlement ${eur(m.full_entitlement_cents)}`}>
        <div className="relative h-[156px] sm:h-[122px]">
          {/* drafted tag */}
          <motion.div
            className={cn("absolute top-0 flex flex-col", tagAlign === "center" && "-translate-x-1/2 items-center", tagAlign === "right" && "-translate-x-full items-end")}
            style={{ left: x(m.drafted_liability_cents) }}
            initial={reduce ? false : { opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.55, ease: EASE }}
          >
            <span className="text-[16px] font-semibold leading-none text-navy-900 [font-stretch:108%]">{eur(m.drafted_liability_cents)}</span>
            <span className="mt-1 text-[11.5px] leading-none text-slate-500">drafted</span>
          </motion.div>

          {/* track: the unfilled part is the entitlement not expected to be claimed */}
          <div className="absolute inset-x-0 top-[40px] h-3.5 rounded-[3px] bg-cloud-100" aria-hidden="true">
            <motion.div
              className="h-full rounded-r-[3px] bg-navy-900"
              initial={reduce ? false : { width: "0%" }}
              animate={{ width: x(m.drafted_liability_cents) }}
              transition={{ duration: 0.9, ease: EASE }}
            />
          </div>
          {/* marker through the track */}
          <span className="absolute top-[30px] h-[34px] w-[2px] -translate-x-1/2 rounded-full bg-navy-900" style={{ left: x(m.drafted_liability_cents) }} aria-hidden="true" />
          {/* end anchors */}
          <span className="absolute left-0 top-[34px] h-[46px] w-px bg-cloud-400" aria-hidden="true" />
          <span className="absolute top-[34px] h-[46px] w-px -translate-x-full bg-cloud-400" style={{ left: x(m.full_entitlement_cents) }} aria-hidden="true" />

          {/* sensitivity and method range, as whiskers under the drafted end */}
          <motion.div initial={reduce ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4, delay: 0.75 }}>
            <Whisker from={x(s.band[0])} to={x(s.band[1])} top={62} tone="ink" label={`±5pp ±${eur(m.sensitivity_5pp_cents)}`} flip={s.at(s.band[1]) > 0.72} />
            {s.range ? <Whisker from={x(s.range[0])} to={x(s.range[1])} top={80} tone="quiet" label={`method range ${eur(s.range[0])}–${eur(s.range[1])}`} flip={s.at(s.range[1]) > 0.62} /> : null}
          </motion.div>

          {/* end captions */}
          <div className="absolute inset-x-0 bottom-0 flex items-end justify-between gap-4">
            <div className="max-w-[46%]">
              <div className="text-[15px] font-semibold leading-none text-slate-600 [font-stretch:108%]">{eur(m.cash_basis_cents)}</div>
              <div className="mt-1 text-[12px] leading-snug text-slate-500">
                Cash basis <span className="hidden text-slate-400 sm:inline">· recognised only when paid</span>
              </div>
            </div>
            <div className="max-w-[54%] text-right">
              <div className="text-[15px] font-semibold leading-none text-slate-600 [font-stretch:108%]">{eur(m.full_entitlement_cents)}</div>
              <div className="mt-1 text-[12px] leading-snug text-slate-500">Full Art. 7 entitlement if every passenger claims</div>
            </div>
          </div>
        </div>
      </figure>

      <dl className="mt-5 grid grid-cols-2 gap-px border-t border-cloud-100 bg-cloud-100 sm:grid-cols-3 lg:grid-cols-5">
        <Fact label="Held for Legal" tone={m.held_for_legal_cents > 0 ? "held" : undefined} sub={m.held_for_legal_cents > 0 ? "accrued under the IFRS 15.56 constraint" : "nothing held"}>
          {eur(m.held_for_legal_cents)}
        </Fact>
        <Fact label="Recoded" sub="cause corrected">
          {count(m.recodes_count)} · {eur(m.recodes_cents)}
        </Fact>
        <Fact label="Refunds within 7 days" sub="Art. 8">
          {refunds === null ? "—" : pct(refunds)}
        </Fact>
        <Fact label="Vouchers outstanding" sub="unredeemed">
          {eur(m.vouchers_outstanding_cents)}
        </Fact>
        <Fact label="Care" sub={`${eur(m.care_invoiced_cents)} invoiced`} className="col-span-2 lg:col-span-1">
          {eur(m.care_accrued_cents)} <span className="text-[12px] font-normal text-slate-500">accrued</span>
        </Fact>
      </dl>
    </section>
  );
}

function Whisker({ from, to, top, tone, label, flip }: { from: string; to: string; top: number; tone: "ink" | "quiet"; label: string; flip?: boolean }) {
  const ink = tone === "ink" ? "bg-navy-900" : "bg-slate-400";
  return (
    <div className="absolute h-3" style={{ left: from, right: `calc(100% - ${to})`, top }} aria-hidden="true">
      <span className={cn("absolute inset-x-0 top-1/2 h-px -translate-y-1/2", ink)} />
      <span className={cn("absolute left-0 top-0 h-full w-px", ink)} />
      <span className={cn("absolute right-0 top-0 h-full w-px", ink)} />
      <span
        className={cn(
          "figure absolute top-1/2 -translate-y-1/2 whitespace-nowrap text-[11.5px] leading-none",
          tone === "ink" ? "text-navy-900" : "text-slate-500",
          flip ? "right-full mr-2" : "left-full ml-2",
        )}
      >
        {label}
      </span>
    </div>
  );
}

function Fact({ label, sub, children, tone, className }: { label: string; sub?: string; children: ReactNode; tone?: "held"; className?: string }) {
  return (
    <div className={cn("bg-card px-5 py-3.5 md:px-7", className)}>
      <dt className="flex items-center gap-1.5 text-[12px] text-slate-500">
        {tone === "held" ? <span className="size-1.5 rounded-full bg-held" aria-hidden="true" /> : null}
        {label}
      </dt>
      <dd className={cn("mt-1 text-[15px] font-semibold leading-tight [font-stretch:108%]", tone === "held" ? "text-held-ink" : "text-navy-900")}>{children}</dd>
      {sub ? <dd className="mt-0.5 text-[11.5px] leading-snug text-slate-400">{sub}</dd> : null}
    </div>
  );
}
