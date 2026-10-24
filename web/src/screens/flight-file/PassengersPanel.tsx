import { Link } from "react-router";
import type { Entitlement, FlightFile } from "@/api/types";
import { MicroLabel, StatusChip } from "@/components/chips";
import { Money } from "@/components/kit";
import { entitlementChip } from "@/components/verdict";
import { count } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ELECTION_LABEL, electionsOf, featureLabel, statusesOf, summaryItems, type SummaryItem } from "./lib";

/** Figures the money card already shows; this panel shows how the cabin splits. */
const SHOWN_IN_MONEY = /^(full_entitlement|entitlement|compensation|drafted_liability|liability_drafted|liability|refund_due|refunds_due|refund)_cents$|rate$/;

/** "NS31@2025-01-24:14C" → "14C". */
const seat = (couponId: string) => couponId.split(":").slice(1).join(":") || couponId;

/** Flags the row's own reason doesn't already state. */
function notes(e: Entitlement): string[] {
  const said = e.reason.toLowerCase();
  const out: string[] = [];
  if (e.reduction === "art7_2_50pct" && !said.includes("7(2)")) out.push("Art. 7(2) 50% reduction");
  if (e.refund_already_initiated && !said.includes("already initiated")) out.push("refund already initiated, not repeated");
  if (e.voucher_offset_cents && !said.includes("offset")) out.push("voucher offset");
  return out;
}

export function PassengersPanel({ file }: { file: FlightFile }) {
  const elections = electionsOf(file.entitlements_summary);
  // The elections bar already states the coupon total.
  const items = summaryItems(file.entitlements_summary).filter((i) => !SHOWN_IN_MONEY.test(i.key) && !(elections.length && i.key === "coupons"));
  const sample = file.sample_entitlements ?? [];
  const total = file.flight.pax;
  if (!items.length && !sample.length && !elections.length) return null;
  return (
    <section aria-labelledby="pax-title" className="rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-5 pt-4">
        <h2 id="pax-title" className="text-[14.5px] font-semibold text-navy-900">
          Passengers
        </h2>
        <p className="text-[12.5px] text-slate-500">EU261 entitlement per coupon, worked out by the engine</p>
      </header>

      <Elections pairs={elections} />
      <Statuses pairs={statusesOf(file.entitlements_summary)} />
      {items.length ? <SummaryGrid items={items} /> : null}

      {sample.length ? (
        <div className="mt-4 border-t border-cloud-100">
          <div className="flex items-baseline justify-between px-5 pb-2 pt-3.5">
            <MicroLabel>
              Sample entitlements · {count(sample.length)} of {count(total)}
            </MicroLabel>
          </div>
          {/* table on md+, stacked cards on phones */}
          <table className="hidden w-full text-[13px] md:table">
            <thead>
              <tr className="micro text-slate-400">
                <th scope="col" className="w-16 px-5 pb-2 text-left font-normal">
                  Seat
                </th>
                <th scope="col" className="w-36 pb-2 text-left font-normal">
                  Status
                </th>
                <th scope="col" className="w-24 pb-2 pr-6 text-right font-normal">
                  Comp.
                </th>
                <th scope="col" className="pb-2 pr-5 text-left font-normal">
                  Why
                </th>
              </tr>
            </thead>
            <tbody>
              {sample.map((e) => (
                <EntitlementRow key={e.coupon_id} e={e} />
              ))}
            </tbody>
          </table>
          <ul className="md:hidden">
            {sample.map((e) => (
              <EntitlementCard key={e.coupon_id} e={e} />
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}

const SHADES = ["bg-navy-800", "bg-slate-500", "bg-slate-400", "bg-cloud-400", "bg-cloud-300"];

/** What the cabin chose (refund, voucher, rebooked, partner reroute), as one proportional bar. */
function Elections({ pairs }: { pairs: [string, number][] }) {
  if (!pairs.length) return null;
  const total = pairs.reduce((s, [, n]) => s + n, 0);
  return (
    <div className="px-5 pt-3">
      <div className="flex items-baseline justify-between">
        <MicroLabel>What passengers chose</MicroLabel>
        <span className="text-[12px] tabular-nums text-slate-400">{count(total)} coupons</span>
      </div>
      <div className="mt-2 flex h-2.5 w-full gap-[2px] overflow-hidden rounded-full" aria-hidden="true">
        {pairs.map(([k, n], i) => (
          <span key={k} className={SHADES[i % SHADES.length]} style={{ flexGrow: n, flexBasis: 0, minWidth: 4 }} />
        ))}
      </div>
      <ul className="mt-2.5 flex flex-wrap gap-x-5 gap-y-1.5 text-[12.5px] text-slate-600">
        {pairs.map(([k, n], i) => (
          <li key={k} className="inline-flex items-center gap-1.5">
            <span className={cn("size-2 rounded-full", SHADES[i % SHADES.length])} aria-hidden="true" />
            {ELECTION_LABEL[k] ?? featureLabel(k)}
            <span className="figure font-semibold text-navy-900">{count(n)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Entitlement status across the flight's coupons: "owed 171 · needs-ruling 1". */
function Statuses({ pairs }: { pairs: [string, number][] }) {
  if (!pairs.length) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 px-5 pt-3.5">
      <MicroLabel className="mr-1.5">Status</MicroLabel>
      {pairs.map(([status, n]) => {
        const chip = entitlementChip({ status: status as Entitlement["status"] });
        return (
          <StatusChip key={status} tone={chip.tone}>
            {chip.text}
            <span className="figure font-sans text-[12px] font-semibold">{count(n)}</span>
          </StatusChip>
        );
      })}
    </div>
  );
}

function SummaryGrid({ items }: { items: SummaryItem[] }) {
  return (
    <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-4 border-t border-cloud-100 px-5 pt-4 sm:grid-cols-3 xl:grid-cols-4">
      {items.map((i) => (
        <div key={i.key} className="min-w-0">
          <dt className="text-[12px] leading-snug text-slate-500">{i.label}</dt>
          <dd className="figure mt-0.5 text-[18px] font-semibold text-navy-900">{i.text}</dd>
        </div>
      ))}
    </dl>
  );
}

function asksRuling(e: Entitlement) {
  return e.status === "needs_ruling" || e.status === "held";
}

function EntitlementRow({ e }: { e: Entitlement }) {
  const chip = entitlementChip(e);
  const extra = notes(e);
  return (
    <tr className={cn("border-t border-cloud-100 align-top", asksRuling(e) && "bg-held-wash/40")}>
      <td className="px-5 py-2.5 font-mono text-[12.5px] font-bold text-navy-900">{seat(e.coupon_id)}</td>
      <td className="py-2.5">
        <StatusChip tone={chip.tone}>{chip.text}</StatusChip>
      </td>
      <td className="py-2.5 pr-6 text-right">
        {e.compensation_cents ? <Money cents={e.compensation_cents} className="text-navy-900" /> : <span className="text-slate-400">€0</span>}
      </td>
      <td className="py-2.5 pr-5 text-slate-600">
        <span className="leading-snug">{e.reason}</span>
        <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[12px] text-slate-400">
          <span>{e.article}</span>
          {extra.map((n) => (
            <span key={n}>· {n}</span>
          ))}
          {asksRuling(e) ? (
            <Link to="/questions" className="font-sans text-[12px] font-medium text-held-ink hover:underline">
              · open question
            </Link>
          ) : null}
        </span>
      </td>
    </tr>
  );
}

function EntitlementCard({ e }: { e: Entitlement }) {
  const chip = entitlementChip(e);
  const extra = notes(e);
  return (
    <li className={cn("border-t border-cloud-100 px-5 py-3", asksRuling(e) && "bg-held-wash/40")}>
      <div className="flex items-center justify-between gap-3">
        <span className="font-mono text-[13px] font-bold text-navy-900">{seat(e.coupon_id)}</span>
        <span className="flex items-center gap-2">
          {e.compensation_cents ? <Money cents={e.compensation_cents} className="text-[13.5px] text-navy-900" /> : null}
          <StatusChip tone={chip.tone}>{chip.text}</StatusChip>
        </span>
      </div>
      <p className="mt-1 text-[13px] leading-snug text-slate-600">{e.reason}</p>
      <p className="mt-0.5 text-[12px] text-slate-400">{[e.article, ...extra].join(" · ")}</p>
      {asksRuling(e) ? (
        <Link to="/questions" className="mt-1 inline-block text-[12.5px] font-medium text-held-ink hover:underline">
          Open question
        </Link>
      ) : null}
    </li>
  );
}
