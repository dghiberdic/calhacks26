import type { ClaimCurve, EstimateCard as Estimate } from "@/api/types";
import { MicroLabel, StatusChip } from "@/components/chips";
import { RoleAvatar } from "@/components/kit";
import { count, eur, pct, ROLE_LABEL } from "@/lib/format";
import { stormName } from "@/lib/storms";
import { cn } from "@/lib/utils";
import { IAS8_LABEL, preparerRole, segmentName } from "./model";

type MethodKey = Estimate["selected"];

const METHODS: { key: MethodKey; name: string; how: string; cents: (e: Estimate) => number }[] = [
  { key: "expected_loss", name: "Expected loss", how: "Ultimate rate × entitlement, less claims to date. Ignores experience.", cents: (e) => e.expected_loss_cents },
  { key: "bf", name: "Bornhuetter-Ferguson", how: "Claims to date, plus the curve's prior for what is still to come.", cents: (e) => e.bf_cents },
  { key: "chain_ladder", name: "Chain ladder", how: "Claims to date grossed up by the curve. Volatile this early.", cents: (e) => e.chain_ladder_cents },
];

/** Cumulative rate the curve expects at month m (exact point only; no interpolation is claimed). */
const expectedAt = (curve: ClaimCurve | undefined, m: number) => curve?.points.find(([month]) => month === m)?.[1] ?? null;

/** The estimate card: header facts, three methods with the selected one ruled in ink, A/E and z, notes, people. */
export function EstimateCardView({ est, curve }: { est: Estimate; curve?: ClaimCurve }) {
  const name = stormName(est.cohort);
  const ns = curve?.n_by_point ?? [];
  const nRange = ns.length ? `${count(Math.min(...ns))}–${count(Math.max(...ns))}` : null;
  const expected = expectedAt(curve, est.months_developed);
  // "(35% − 9%) × €99,000", shown only when it reproduces the BF figure to the euro.
  const bfFormula = curve && expected !== null && Math.abs(Math.round((curve.ultimate - expected) * est.entitlement_cents) - est.bf_cents) < 100 ? `(${pct(curve.ultimate)} − ${pct(expected)}) × ${eur(est.entitlement_cents)}` : null;
  const prep = preparerRole(est.preparer);
  const appr = preparerRole(est.approver);
  const ias8 = IAS8_LABEL[est.ias8_class];

  const header = [
    `${count(est.pax)} pax`,
    `entitlement ${eur(est.entitlement_cents)}`,
    `curve ${est.curve_version}`,
    curve?.basis === "eur" || !curve ? "€ basis" : `${curve.basis} basis`,
    curve ? `observed to M${curve.observed_through_month}` : null,
    nRange ? `n per point ${nRange}` : null,
  ].filter(Boolean);

  return (
    <section aria-labelledby="estimate-card" className="flex h-full flex-col rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]">
      <div className="px-5 pt-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <MicroLabel>Estimate · {segmentName(est.segment)} cohort</MicroLabel>
          {ias8 ? (
            <StatusChip tone="outline" dot={false}>
              {ias8}
            </StatusChip>
          ) : null}
        </div>
        <h2 id="estimate-card" className="mt-1.5 text-[15.5px] font-semibold text-navy-900">
          {name ?? est.cohort} <span className="font-mono text-[12px] font-normal text-slate-400">{est.cohort}</span>
        </h2>
        <p className="figure mt-1 text-[12.5px] leading-relaxed text-slate-500">
          {header.map((h, i) => (
            <span key={h}>
              {i ? " · " : ""}
              <span className="whitespace-nowrap">{h}</span>
            </span>
          ))}
        </p>
      </div>

      <div className="px-5 pt-4">
        <div className="flex items-baseline justify-between gap-3">
          <h3 className="text-[13px] font-semibold text-navy-900">{est.months_developed > 0 ? `Three methods, developed to M${est.months_developed}` : "Three methods, day 1 (no development yet)"}</h3>
          <span className="font-mono text-[11.5px] text-slate-400">remaining liability</span>
        </div>
        <ol className="mt-2 grid gap-2 sm:grid-cols-3">
          {METHODS.map((m) => {
            const selected = est.selected === m.key;
            return (
              <li
                key={m.key}
                className={cn(
                  "relative flex flex-col rounded-lg px-3.5 pb-3 pt-3",
                  selected ? "bg-white shadow-[inset_0_0_0_2px_var(--color-navy-900)]" : "bg-cloud-25 shadow-[inset_0_0_0_1px_var(--color-cloud-200)]",
                )}
                aria-current={selected ? "true" : undefined}
              >
                {selected ? <span className="absolute -top-2 left-3 rounded bg-navy-900 px-1.5 py-[3px] font-mono text-[9.5px] font-bold uppercase leading-none tracking-[0.08em] text-cloud-50">selected</span> : null}
                <span className={cn("text-[12.5px] font-semibold leading-tight", selected ? "text-navy-900" : "text-slate-500")}>{m.name}</span>
                <span className={cn("display-tight mt-2 text-[22px] leading-none", selected ? "text-navy-900" : "text-slate-500")}>{eur(m.cents(est))}</span>
                {selected && m.key === "bf" && bfFormula ? <span className="figure mt-1.5 text-[12px] text-navy-900">{bfFormula}</span> : null}
                <span className="mt-1.5 text-[11.5px] leading-snug text-slate-500">{m.how}</span>
              </li>
            );
          })}
        </ol>
      </div>

      <dl className="mx-5 mt-4 grid grid-cols-2 gap-x-4 gap-y-3 border-t border-cloud-100 pt-3.5 sm:grid-cols-3">
        <div>
          <dt className="text-[12px] text-slate-500">Actual vs expected</dt>
          <dd className="mt-0.5 text-[15px] font-semibold text-navy-900 [font-stretch:108%]">
            {est.actual_vs_expected === null ? "—" : `A/E ${est.actual_vs_expected.toFixed(2)}`} <span className="text-[11.5px] font-normal text-slate-400">€-weighted</span>
          </dd>
        </div>
        <div>
          <dt className="text-[12px] text-slate-500">Credibility</dt>
          <dd className="mt-0.5 text-[15px] font-semibold text-navy-900 [font-stretch:108%]">{est.credibility_z === null ? "—" : `z ${est.credibility_z.toFixed(2)}`}</dd>
        </div>
        <div className="col-span-2 sm:col-span-1">
          <dt className="text-[12px] text-slate-500">Sensitivity on the ultimate</dt>
          <dd className="mt-0.5 text-[15px] font-semibold text-navy-900 [font-stretch:108%]">
            ±{eur(est.sensitivity_5pp_cents)} <span className="text-[11.5px] font-normal text-slate-400">per ±5pp</span>
          </dd>
        </div>
      </dl>

      <dl className="mx-5 mt-3.5 flex flex-col gap-2.5 border-t border-cloud-100 pt-3.5 text-[12.5px] leading-relaxed">
        <div className="grid gap-0.5 sm:grid-cols-[92px_minmax(0,1fr)] sm:gap-3">
          <dt className="text-slate-400">Constraint</dt>
          <dd className="text-slate-600">{est.constraint_note}</dd>
        </div>
        {curve ? (
          <div className="grid gap-0.5 sm:grid-cols-[92px_minmax(0,1fr)] sm:gap-3">
            <dt className="text-slate-400">Tail</dt>
            <dd className="text-slate-600">
              <span className="text-navy-900">
                {pct(curve.ultimate)} ultimate · tail factor {curve.tail_factor.toFixed(2)}
              </span>
              {curve.tail_note ? <> · {curve.tail_note}</> : null}
            </dd>
          </div>
        ) : null}
      </dl>

      <div className="mt-auto flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-cloud-100 px-5 py-3 text-[12.5px] text-slate-500">
        <span className="inline-flex items-center gap-2">
          {prep ? <RoleAvatar role={prep} size="sm" /> : null}
          Prepared by{" "}
          <span className="text-navy-900" title={est.preparer}>
            {prep ? ROLE_LABEL[prep] : est.preparer}
          </span>
        </span>
        <span className="inline-flex items-center gap-2">
          {appr ? <RoleAvatar role={appr} size="sm" /> : <span className="inline-flex size-5 items-center justify-center rounded-full shadow-[inset_0_0_0_1px_var(--color-cloud-300)]" aria-hidden="true" />}
          {est.approver ? (
            <>
              Approved by{" "}
              <span className="text-navy-900" title={est.approver}>
                {appr ? ROLE_LABEL[appr] : est.approver}
              </span>
            </>
          ) : (
            <>Approver pending · not the preparer</>
          )}
        </span>
      </div>
    </section>
  );
}
