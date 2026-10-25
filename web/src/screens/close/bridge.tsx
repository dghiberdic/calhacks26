import type { ReactNode } from "react";
import { Check } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import type { CfoMetrics, ClaimCurve } from "@/api/types";
import { MicroLabel } from "@/components/chips";
import { Explain } from "@/components/explain";
import { Details } from "@/components/kit";
import { count, eur, longDate, pct, zulu } from "@/lib/format";
import { stormName } from "@/lib/storms";
import { cn } from "@/lib/utils";
import { asFraction, bridgeScale, bridgeToGl, cohortTitle, isRateTimesEntitlement, newStorms } from "./model";

const EASE = [0.16, 1, 0.3, 1] as const;

/**
 * The CFO bridge, said as a story: "What we owe after Storm Éowyn: €34,650 drafted. Not €0 (cash basis),
 * and not €99,000 (if every passenger claimed)." Then the one axis, the three numbers in words, and the
 * tie-out to GL 2140, and care (owed even when extraordinary). The storm's other balances wait behind Details.
 */
export function CfoBridge({ metrics, curve, tiesToGl }: { metrics: CfoMetrics; curve?: ClaimCurve; tiesToGl?: boolean | null }) {
  const m = metrics;
  const gl = bridgeToGl(m);
  // "after Storm Éowyn" when one storm is new in the bridge; a month with none new carries several in.
  const storms = newStorms(m.liability_bridge, (b) => cohortTitle(b, stormName));
  const after = storms.length === 1 ? (storms[0] === "Iberian blackout" ? "the Iberian blackout" : storms[0]) : "the storms";
  const rate = curve?.ultimate ?? null;
  const formula = isRateTimesEntitlement(m.drafted_liability_cents, m.full_entitlement_cents, rate);

  return (
    <section aria-labelledby="cfo-bridge" className="overflow-hidden rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]">
      <div className="px-5 pt-5 md:px-7 md:pt-6">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
          <MicroLabel>EU261 compensation liability</MicroLabel>
          <span className="figure text-[12px] text-slate-400">
            as of {longDate(m.as_of)} · {zulu(m.as_of)}
          </span>
        </div>
        <h2 id="cfo-bridge" className="display-tight mt-3 max-w-[40ch] text-[22px] leading-[1.2] text-pretty sm:text-[25px] md:text-[28px]" data-testid="cfo-headline">
          <span className="text-navy-900">
            What we owe after {after}: <span className="whitespace-nowrap">{eur(m.drafted_liability_cents)} drafted.</span>
          </span>{" "}
          <span className="text-slate-400">
            Not {eur(m.cash_basis_cents)} (cash basis), and not {eur(m.full_entitlement_cents)} (if every passenger claimed).
          </span>
        </h2>
        {m.held_for_legal_cents > 0 || tiesToGl !== null ? (
          <p className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[15px] leading-snug text-slate-600">
            {m.held_for_legal_cents > 0 ? (
              <span>
                <span className="font-semibold text-held-ink">{eur(m.held_for_legal_cents)} more</span> is <Explain term="held-for-legal">held until Legal rules</Explain>.
              </span>
            ) : null}
            {tiesToGl ? (
              <a href="#bridge-to-gl" className="inline-flex items-center gap-1 font-medium text-tie-ink hover:underline">
                <Check className="size-4" aria-hidden="true" /> The ledger ties.
              </a>
            ) : tiesToGl === false ? (
              <span className="font-medium text-held-ink">The ledger doesn't tie yet.</span>
            ) : null}
          </p>
        ) : null}
      </div>

      <BridgeAxis m={m} />

      {/* The three numbers, in words. */}
      <dl className="mt-5 grid grid-cols-[minmax(0,1fr)] gap-px border-t border-cloud-100 bg-cloud-100 sm:grid-cols-3">
        <Explained figure={eur(m.cash_basis_cents)} label="Cash basis">
          Compensation booked only once it is paid. Too low: the passengers are owed now, and have six years to claim.
        </Explained>
        <Explained figure={eur(m.drafted_liability_cents)} label="Drafted, pending approval" strong>
          {formula && rate !== null ? (
            <>
              The full entitlement × the <Explain term="claim-rate">{pct(rate)} expected ultimate claim rate</Explain> (history to M18 + tail judgment).
            </>
          ) : (
            <>
              Each storm's entitlement times its <Explain term="claim-rate">expected ultimate claim rate</Explain>, less claims already approved.
            </>
          )}{" "}
          A reduction of passenger revenue, as <Explain term="ifrs15">IFRS 15 variable consideration</Explain>. The bracket is ±5 points on that rate.
        </Explained>
        <Explained figure={eur(m.full_entitlement_cents)} label="Full Art. 7 entitlement if every passenger claims">
          Too high: most passengers never claim.
        </Explained>
      </dl>

      {gl ? (
        <p id="bridge-to-gl" className="figure scroll-mt-24 border-t border-cloud-100 px-5 py-3.5 text-[13.5px] leading-relaxed text-slate-600 md:px-7" data-testid="bridge-to-gl">
          <span className="font-medium text-navy-900">The ledger:</span> EU261 compensation liability (<Explain term="liability-2140">account 2140</Explain>) holds{" "}
          <a href="#rollforward-title" className="font-semibold text-navy-900 hover:underline" title="The 2140 rollforward">
            {eur(gl.total)}
          </a>{" "}
          = {eur(gl.drafted)} drafted
          {gl.held ? <> + <span className="text-held-ink">{eur(gl.held)} held until Legal rules</span></> : null}
          {gl.other ? <> + {eur(gl.other)} from {gl.earlier.length ? gl.earlier.map((c) => cohortTitle(c, stormName)).join(", ") : "other cohorts"}</> : null}.
          {tiesToGl ? (
            <span className="ml-2 inline-flex items-center gap-1 whitespace-nowrap font-medium text-tie-ink">
              <Check className="size-3.5" aria-hidden="true" /> ties to GL 2140
            </span>
          ) : null}
        </p>
      ) : null}

      {m.care_accrued_cents ? (
        <p className="figure border-t border-cloud-100 px-5 py-3.5 text-[13.5px] leading-relaxed text-slate-600 md:px-7" data-testid="bridge-care">
          <span className="font-medium text-navy-900">
            <Explain term="care">Care</Explain> for stranded passengers (hotels, meals):
          </span>{" "}
          {eur(m.care_accrued_cents)} accrued in 2150{m.care_invoiced_cents ? `, ${eur(m.care_invoiced_cents)} invoiced so far` : ""}. Owed even when the cause is extraordinary, so it's booked for every cancelled flight.
        </p>
      ) : null}

      <div className="border-t border-cloud-100 px-5 py-3 md:px-7">
        <Details summary="Other balances: recodes, refunds and vouchers">
          <OtherBalances m={m} />
        </Details>
      </div>
    </section>
  );
}

/** One axis, €0 → the full entitlement: why the drafted liability is neither end. */
function BridgeAxis({ m }: { m: CfoMetrics }) {
  const s = bridgeScale({ cash: m.cash_basis_cents, drafted: m.drafted_liability_cents, full: m.full_entitlement_cents, sensitivity: m.sensitivity_5pp_cents });
  const reduce = useReducedMotion();
  const x = (v: number) => `${(s.at(v) * 100).toFixed(3)}%`;
  const drafted = s.at(m.drafted_liability_cents);
  // Keep the drafted tag inside the axis when the liability sits near an end.
  const tagAlign = drafted < 0.14 ? "left" : drafted > 0.86 ? "right" : "center";
  return (
    <figure className="relative mx-5 mb-1 mt-6 md:mx-7" aria-label={`Drafted ${eur(m.drafted_liability_cents)} on an axis from cash basis ${eur(m.cash_basis_cents)} to the full entitlement ${eur(m.full_entitlement_cents)}`}>
      <div className="relative h-[92px]">
        <motion.div
          className={cn("absolute top-0 flex flex-col", tagAlign === "center" && "-translate-x-1/2 items-center", tagAlign === "right" && "-translate-x-full items-end")}
          style={{ left: x(m.drafted_liability_cents) }}
          initial={reduce ? false : { opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.55, ease: EASE }}
        >
          <span className="text-[15px] font-semibold leading-none text-navy-900 [font-stretch:108%]">{eur(m.drafted_liability_cents)}</span>
          <span className="mt-1 text-[11.5px] leading-none text-slate-500">drafted</span>
        </motion.div>

        {/* track: the unfilled part is the entitlement not expected to be claimed */}
        <div className="absolute inset-x-0 top-[38px] h-3 rounded-[3px] bg-cloud-100" aria-hidden="true">
          <motion.div className="h-full rounded-r-[3px] bg-navy-900" initial={reduce ? false : { width: "0%" }} animate={{ width: x(m.drafted_liability_cents) }} transition={{ duration: 0.9, ease: EASE }} />
        </div>
        <span className="absolute top-[30px] h-[28px] w-[2px] -translate-x-1/2 rounded-full bg-navy-900" style={{ left: x(m.drafted_liability_cents) }} aria-hidden="true" />
        <span className="absolute left-0 top-[32px] h-[40px] w-px bg-cloud-400" aria-hidden="true" />
        <span className="absolute top-[32px] h-[40px] w-px -translate-x-full bg-cloud-400" style={{ left: x(m.full_entitlement_cents) }} aria-hidden="true" />

        {/* ±5pp on the ultimate, as a bracket under the drafted end */}
        <motion.div initial={reduce ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4, delay: 0.75 }}>
          <Whisker from={x(s.band[0])} to={x(s.band[1])} top={58} label={`±${eur(m.sensitivity_5pp_cents)} at ±5pp`} flip={s.at(s.band[1]) > 0.72} />
        </motion.div>

        <div className="absolute inset-x-0 bottom-0 flex items-end justify-between gap-4 text-[12px] text-slate-500">
          <span>{eur(m.cash_basis_cents)}</span>
          <span>{eur(m.full_entitlement_cents)}</span>
        </div>
      </div>
    </figure>
  );
}

function Whisker({ from, to, top, label, flip }: { from: string; to: string; top: number; label: string; flip?: boolean }) {
  return (
    <div className="absolute h-3" style={{ left: from, right: `calc(100% - ${to})`, top }} aria-hidden="true">
      <span className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-navy-900" />
      <span className="absolute left-0 top-0 h-full w-px bg-navy-900" />
      <span className="absolute right-0 top-0 h-full w-px bg-navy-900" />
      <span className={cn("figure absolute top-1/2 -translate-y-1/2 whitespace-nowrap text-[11.5px] leading-none text-navy-900", flip ? "right-full mr-2" : "left-full ml-2")}>{label}</span>
    </div>
  );
}

function Explained({ figure, label, strong, children }: { figure: string; label: string; strong?: boolean; children: ReactNode }) {
  return (
    <div className="bg-card px-5 py-4 md:px-7">
      <dt>
        <span className={cn("block text-[20px] font-semibold leading-none [font-stretch:108%]", strong ? "text-navy-900" : "text-slate-500")}>{figure}</span>
        <span className={cn("mt-1.5 block text-[13px] font-medium leading-snug", strong ? "text-navy-900" : "text-slate-600")}>{label}</span>
      </dt>
      <dd className="mt-1 text-[12.5px] leading-relaxed text-slate-500">{children}</dd>
    </div>
  );
}

/** The storm's balances around 2140: recodes, refunds and vouchers, each named before its account. */
function OtherBalances({ m }: { m: CfoMetrics }) {
  const refunds = asFraction(m.refunds_within_7d_pct);
  return (
    <dl className="-mx-5 grid grid-cols-[minmax(0,1fr)] gap-px border-t border-cloud-100 bg-cloud-100 sm:grid-cols-3 md:-mx-7">
      <Fact label="Flights recoded" sub="cause corrected; already in the liability above">
        {count(m.recodes_count)} · {eur(m.recodes_cents)}
      </Fact>
      <Fact label="Refunds paid within 7 days" sub="EU261 Art. 8 · refunds payable (2120)">
        {refunds === null ? "—" : pct(refunds)}
      </Fact>
      <Fact label="Vouchers not yet redeemed" sub="refund (2131) and compensation (2132) vouchers">
        {eur(m.vouchers_outstanding_cents)}
      </Fact>
    </dl>
  );
}

function Fact({ label, sub, children }: { label: string; sub: string; children: ReactNode }) {
  return (
    <div className="bg-card px-5 py-3.5 md:px-7">
      <dt className="text-[12px] text-slate-500">{label}</dt>
      <dd className="mt-1 text-[15px] font-semibold leading-tight text-navy-900 [font-stretch:108%]">{children}</dd>
      <dd className="mt-0.5 text-[11.5px] leading-snug text-slate-400">{sub}</dd>
    </div>
  );
}
