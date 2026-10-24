import type { ReactNode } from "react";
import { motion, useReducedMotion } from "motion/react";
import { Check } from "lucide-react";
import type { Cents, Rollforward } from "@/api/types";
import { Money } from "@/components/kit";
import { eur, longDate, periodLabel } from "@/lib/format";
import { stormName } from "@/lib/storms";
import { cn } from "@/lib/utils";
import { cohortName, cohortParts, footRow, isNilLine, type journalTies, monthBounds, MOVEMENTS, movementCents, rollforwardTotals, segmentName, type MovementKey } from "./model";
import { Nil } from "./ui";

const cell = "px-3 py-[7px] text-right align-baseline md:px-4";
const label = "sticky left-0 z-[1] min-w-[156px] bg-card py-[7px] pl-5 pr-3 text-left align-baseline font-normal md:pl-6";

function Amount({ cents, strong, quiet }: { cents: Cents; strong?: boolean; quiet?: boolean }) {
  if (!cents) return <Nil />;
  return <Money cents={cents} className={cn("text-[13.5px]", strong ? "font-semibold text-navy-900" : quiet ? "text-slate-500" : "text-navy-900")} />;
}

type Ties = ReturnType<typeof journalTies>;

/** Tick mark for "agrees to its journals", in a fixed slot so the total column stays aligned. */
function Tick({ tie }: { tie?: { ids: string[]; agrees: boolean } }) {
  const on = tie?.agrees;
  return (
    <span className="inline-block w-4 pl-1 text-left font-mono text-[9.5px] leading-none text-slate-400" title={on ? `Agrees to ${tie!.ids.join(", ")}` : undefined} aria-label={on ? `agrees to ${tie!.ids.join(", ")}` : undefined}>
      {on ? "J" : ""}
    </span>
  );
}

/** A total ruled off the way accounts are: a single rule above the figure, a double rule below. */
function Ruled({ children }: { children: ReactNode }) {
  return <span className="inline-block w-full border-t border-b-[3px] border-double border-t-navy-900/60 border-b-navy-900/60 pb-1 pt-1.5 [border-top-style:solid] [border-top-width:1px]">{children}</span>;
}

/** "EIDW@2025-01-24:medium_1500_3500" → Storm Éowyn / medium haul; a cohort without a segment shows its date. */
function CohortHead({ cohort, segment }: { cohort: string; segment?: string | null }) {
  const p = cohortParts(cohort);
  const name = stormName(p.base);
  const seg = p.segment ?? segment ?? null;
  return (
    <span title={`${cohort}${p.date ? ` · ${p.station} · ${longDate(p.date)}` : ""}`}>
      <span className="block whitespace-nowrap text-[13px] font-semibold text-navy-900">{name ?? p.base}</span>
      <span className="mt-0.5 block whitespace-nowrap font-mono text-[10.5px] font-normal text-slate-400">{seg ? segmentName(seg).toLowerCase() : p.date ? longDate(p.date) : cohort}</span>
    </span>
  );
}

/**
 * The 2140 rollforward as an accounts note: movements down, cohorts across, total on the right;
 * closing ruled off (single rule above, double below), then the GL balance and a memo line.
 */
export function RollforwardTable({ rf, highlight, ties = {}, segments = {} }: { rf: Rollforward; highlight?: MovementKey | null; ties?: Ties; segments?: Record<string, string> }) {
  const totals = rollforwardTotals(rf);
  const { first, last } = monthBounds(rf.period);
  const reduce = useReducedMotion();
  const cols = rf.rows.length + 2;

  return (
    <div className="-mx-5 overflow-x-auto md:-mx-6" role="region" aria-label={`2140 rollforward, ${periodLabel(rf.period)}`} tabIndex={0}>
      <table className="w-full min-w-[560px] border-collapse text-[13.5px]">
        <caption className="sr-only">
          2140 EU261 compensation liability rollforward by cohort, {periodLabel(rf.period)}. Negatives in parentheses.
        </caption>
        <thead>
          <tr className="border-b border-cloud-200">
            <th scope="col" className={cn(label, "pb-2.5 pt-1 align-bottom")}>
              <span className="micro whitespace-nowrap text-slate-400">€ · movement</span>
            </th>
            {rf.rows.map((r) => (
              <th key={r.cohort} scope="col" className={cn(cell, "pb-2.5 pt-1 align-bottom font-normal")}>
                <CohortHead cohort={r.cohort} segment={segments[r.cohort]} />
              </th>
            ))}
            <th scope="col" className={cn(cell, "pb-2.5 pt-1 align-bottom")}>
              <span className="block pr-4 text-[13px] font-semibold text-navy-900">Total</span>
              <span className="mt-0.5 block pr-4 font-mono text-[10.5px] font-normal text-slate-400">GL 2140</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th scope="row" className={cn(label, "pt-3 text-navy-900")}>
              At {longDate(first)} <span className="ml-1 text-[11.5px] text-slate-400">opening</span>
            </th>
            {rf.rows.map((r) => (
              <td key={r.cohort} className={cn(cell, "pt-3")}>
                <Amount cents={r.opening_cents} />
              </td>
            ))}
            <td className={cn(cell, "pt-3")}>
              <Amount cents={totals.opening} />
              <Tick />
            </td>
          </tr>
          {MOVEMENTS.map((m) => {
            const nil = isNilLine(rf, m.key);
            const flash = highlight === m.key && !reduce;
            return (
              <motion.tr
                key={m.key}
                initial={false}
                animate={flash ? { backgroundColor: ["rgba(13,21,36,0.07)", "rgba(13,21,36,0)"] } : undefined}
                transition={{ duration: 2.6, ease: "easeOut" }}
              >
                <th scope="row" className={cn(label, "max-w-[212px]", nil ? "text-slate-400" : "text-navy-900")}>
                  <span className="block leading-snug">{m.label}</span>
                  {m.note && !nil ? <span className="block text-[11.5px] leading-snug text-slate-400">{m.note}</span> : null}
                </th>
                {rf.rows.map((r) => (
                  <td key={r.cohort} className={cell}>
                    <Amount cents={movementCents(r, m.key)} />
                  </td>
                ))}
                <td className={cell}>
                  <Amount cents={totals.movements[m.key]} />
                  <Tick tie={totals.movements[m.key] ? ties[m.key] : undefined} />
                </td>
              </motion.tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row" className={cn(label, "pt-2.5 font-semibold text-navy-900")}>
              At {longDate(last)} <span className="ml-1 text-[11.5px] font-normal text-slate-400">closing</span>
            </th>
            {rf.rows.map((r) => (
              <td key={r.cohort} className={cn(cell, "pt-1")}>
                <Ruled>
                  <Amount cents={r.closing_cents} strong />
                </Ruled>
              </td>
            ))}
            <td className={cn(cell, "pt-1")}>
              <Ruled>
                <Amount cents={rf.closing_total_cents} strong />
                <Tick />
              </Ruled>
            </td>
          </tr>
          <tr>
            <th scope="row" className={cn(label, "pt-3 text-slate-600")}>
              GL 2140 balance
            </th>
            <td colSpan={cols - 2} className={cn(cell, "pt-3")} />
            <td className={cn(cell, "pt-3")}>
              <span className="inline-flex items-center justify-end gap-1.5">
                {rf.ties_to_gl ? <Check className="size-3.5 text-tie" aria-label="ties" /> : null}
                <Money cents={rf.gl_balance_cents} className={cn("text-[13.5px]", rf.ties_to_gl ? "text-navy-900" : "font-semibold text-navy-900")} />
                <Tick />
              </span>
            </td>
          </tr>
          <tr>
            <th scope="row" className={cn(label, "pb-1 pt-4 text-[12.5px] text-slate-500")}>
              Memo: unclaimed entitlement
            </th>
            {rf.rows.map((r) => (
              <td key={r.cohort} className={cn(cell, "pb-1 pt-4")}>
                <Amount cents={r.unclaimed_entitlement_cents} quiet />
              </td>
            ))}
            <td className={cn(cell, "pb-1 pt-4")}>
              <Amount cents={totals.unclaimed} quiet />
              <Tick />
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

/** Plain integrity notes under the table: what doesn't foot, by how much. Silent when everything does. */
export function FootingNotes({ rf }: { rf: Rollforward }) {
  const totals = rollforwardTotals(rf);
  const broken = rf.rows.map((r) => ({ r, f: footRow(r) })).filter((x) => !x.f.foots);
  const notes: string[] = broken.map(({ r, f }) => `${cohortName(r.cohort, null, stormName)} doesn't foot: closing is ${eur(f.difference, { signed: true })} off its movements.`);
  if (!totals.crossFoots) notes.push(`Cohorts sum to ${eur(totals.closing)}; the closing total says ${eur(rf.closing_total_cents)}.`);
  if (!rf.ties_to_gl) notes.push(`Closing ${eur(rf.closing_total_cents)} doesn't tie to GL 2140 ${eur(rf.gl_balance_cents)}: ${eur(rf.gl_balance_cents - rf.closing_total_cents, { signed: true })}.`);
  if (!notes.length) return null;
  return (
    <ul className="mt-3 flex flex-col gap-1 text-[13px] text-navy-900">
      {notes.map((n) => (
        <li key={n} className="flex gap-2">
          <span className="font-mono text-slate-400" aria-hidden="true">
            !
          </span>
          {n}
        </li>
      ))}
    </ul>
  );
}

