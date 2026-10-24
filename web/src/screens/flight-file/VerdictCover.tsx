import { useId, useState } from "react";
import { Link } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import { ChevronDown, ChevronLeft } from "lucide-react";
import type { FlightFile } from "@/api/types";
import { MicroLabel, StatusChip } from "@/components/chips";
import { RoleAvatar } from "@/components/kit";
import { VERDICT_COLOR, verdictChip, type VerdictKind } from "@/components/verdict";
import { count, duration, longDate, routedTo, zulu } from "@/lib/format";
import { cn } from "@/lib/utils";
import { cityOf, consequence, splitRecode, summaryText, VERDICT_HEADLINE } from "./lib";
import { Recode } from "./Recode";

const HEADLINE_INK: Record<VerdictKind, string> = {
  notweather: "text-notweather-ink",
  held: "text-held-ink",
  weather: "text-weather-ink",
  operated: "text-slate-600",
  pending: "text-slate-500",
};

/** Payout count for the "N payouts drafted" line, from whichever key the summary carries. */
function payoutsDrafted(summary: Record<string, unknown>): number | null {
  for (const key of ["payouts_drafted", "owed", "payouts"]) {
    const v = summary[key];
    if (typeof v === "number" && v > 0) return v;
  }
  return null;
}

function windowChip(file: FlightFile): string | null {
  const d = file.decision;
  const margin = d.window_margin_min;
  if (d.in_window_dep === "unknown") return "no METAR within 60 min of departure";
  if (d.in_window_dep === "in") return d.in_window_arr === "in" ? "inside the storm window at both ends" : "departure inside the storm window";
  if (d.in_window_arr === "in") return "arrival inside the storm window";
  return margin !== null && margin !== undefined ? `outside the storm window · ${duration(Math.abs(margin))} clear` : "outside the storm window at both ends";
}

export function VerdictCover({ file, kind, stormLabel, stormId }: { file: FlightFile; kind: VerdictKind; stormLabel: string | null; stormId?: string }) {
  const { flight, decision } = file;
  // An operated flight has nothing to decide; key off its status, never off a placeholder decision.
  const chip = kind === "operated" ? { text: "operated", tone: "slate" as const } : verdictChip(decision);
  const recode = decision.recoded ? splitRecode(decision.recode_label, decision) : null;
  const payouts = kind === "notweather" ? payoutsDrafted(file.entitlements_summary ?? {}) : null;
  // The server's own status line first ("172 payouts drafted, pending Claims Lead approval"), else the plan's wording.
  const effect = summaryText(file.entitlements_summary, "status_line") ?? (kind === "notweather" ? (payouts ? `${count(payouts)} payouts drafted, pending Claims Lead approval` : null) : consequence(kind));
  const window = kind === "operated" ? null : windowChip(file);

  return (
    <header>
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-[13px] text-slate-500">
        <Link to={stormId ? `/flights?storm=${encodeURIComponent(stormId)}` : "/flights"} className="-ml-1 inline-flex items-center gap-0.5 rounded px-1 py-0.5 hover:bg-cloud-100 hover:text-navy-900">
          <ChevronLeft className="size-3.5" aria-hidden="true" />
          Flight File
        </Link>
        {stormLabel ? (
          <>
            <span aria-hidden="true" className="text-cloud-400">
              /
            </span>
            <span>{stormLabel}</span>
          </>
        ) : null}
      </nav>

      <h1 className="display-tight mt-3 flex flex-wrap items-baseline gap-x-3 text-[34px] leading-[1.05] text-navy-900 md:text-[40px]">
        <span>{flight.number}</span>
        <span className="text-[22px] font-medium text-slate-400 [font-stretch:100%] md:text-[26px]">
          {cityOf(flight.origin)} → {cityOf(flight.dest)}
        </span>
      </h1>
      <p className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[13.5px] text-slate-500">
        <span className="font-medium tabular-nums text-slate-600">
          {flight.origin} {zulu(flight.sched_dep)} → {flight.dest} {zulu(flight.sched_arr)}
        </span>
        <Dot />
        <span>{longDate(flight.date)}</span>
        {flight.aircraft ? (
          <>
            <Dot />
            <span className="font-mono text-[12.5px]">{flight.aircraft}</span>
          </>
        ) : null}
        <Dot />
        <span>
          <span className="figure text-navy-900">{count(flight.pax)}</span> passengers
        </span>
        <Dot />
        <span>{flight.status.charAt(0).toUpperCase() + flight.status.slice(1)}</span>
      </p>

      <section aria-label="Verdict" className="mt-6 overflow-hidden rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]">
        <div className="relative px-5 pb-5 pt-4 md:px-6">
          <span className="absolute inset-y-0 left-0 w-[3px]" style={{ background: VERDICT_COLOR[kind] }} aria-hidden="true" />
          <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
            <div className="min-w-0 flex-1">
              <MicroLabel className={cn("flex items-center gap-2 font-bold", HEADLINE_INK[kind])}>
                <span className="size-1.5 rounded-full" style={{ background: VERDICT_COLOR[kind] }} aria-hidden="true" />
                {VERDICT_HEADLINE[kind]}
              </MicroLabel>
              <p className="display-tight mt-2 max-w-[44ch] text-[22px] leading-snug text-navy-900 md:text-[24px]">{sentence(decision.reason)}</p>
            </div>
            {recode ? <Recode from={recode.from} to={recode.to} size="lg" className="shrink-0" /> : null}
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-2">
            <StatusChip tone={chip.tone}>{chip.text}</StatusChip>
            {window ? (
              <StatusChip tone="metar" dot={false}>
                {window}
              </StatusChip>
            ) : null}
            {decision.routed_to && kind === "held" ? (
              <Link to="/questions" className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-[13px] text-slate-600 hover:bg-cloud-50">
                <RoleAvatar role={decision.routed_to} size="sm" />
                {routedTo(decision.routed_to)}
              </Link>
            ) : null}
          </div>

          <Why file={file} effect={effect} />
        </div>

        {file.handoff ? <Handoff handoff={file.handoff} /> : null}
      </section>
    </header>
  );
}

const Dot = () => (
  <span aria-hidden="true" className="text-cloud-400">
    ·
  </span>
);

/** "fault logged before storm" → "Fault logged before storm." */
function sentence(text: string) {
  const t = text.trim();
  if (!t) return t;
  const head = t.charAt(0).toUpperCase() + t.slice(1);
  return /[.!?]$/.test(head) ? head : `${head}.`;
}

/** The consequence line, and the Drafter's plain-language explanation behind a "Why?" disclosure. */
function Why({ file, effect }: { file: FlightFile; effect: string | null }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const draft = file.explanation;
  return (
    <div className="mt-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {effect ? <p className="text-[14px] text-slate-600">{effect.charAt(0).toUpperCase() + effect.slice(1)}</p> : null}
        {draft ? (
          <button
            type="button"
            aria-expanded={open}
            aria-controls={id}
            onClick={() => setOpen((v) => !v)}
            className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[13.5px] font-semibold text-metar-ink hover:bg-metar-wash"
          >
            Why?
            <ChevronDown className={cn("size-3.5 transition-transform", open && "rotate-180")} aria-hidden="true" />
          </button>
        ) : null}
      </div>
      <AnimatePresence initial={false}>
        {draft && open ? (
          <motion.div
            id={id}
            key="why"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.28, ease: [0.25, 1, 0.5, 1] }}
            className="overflow-hidden"
          >
            <div className="mt-3 rounded-lg bg-cloud-50 px-4 py-3.5 shadow-[inset_0_0_0_1px_var(--color-cloud-200)]">
              <p className="max-w-[72ch] whitespace-pre-line text-[14.5px] leading-relaxed text-navy-900">{draft.text}</p>
              <p className="mt-2.5 font-mono text-[11px] text-slate-400">
                {draft.template_fallback
                  ? "template wording · a drafted number didn't match the evidence"
                  : draft.numbers_verified
                    ? "drafted by the Drafter agent · every number checked against the evidence"
                    : "drafted by the Drafter agent · numbers not yet checked"}
              </p>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

/** The CRM bot already refunded some passengers at 06:02: show that nothing is repeated and who saw what. */
function Handoff({ handoff }: { handoff: NonNullable<FlightFile["handoff"]> }) {
  const refunds = typeof handoff.refunds_already_initiated === "number" ? handoff.refunds_already_initiated : null;
  const notices = typeof handoff.rights_notices_drafted === "number" ? handoff.rights_notices_drafted : null;
  const pii = typeof handoff.drafter_pii_seen === "number" ? handoff.drafter_pii_seen : null;
  const parts: { text: string; strong?: boolean }[] = [];
  if (refunds !== null) parts.push({ text: `${count(refunds)} refunds already initiated` });
  if (handoff.not_repeated) parts.push({ text: "not repeated", strong: true });
  if (notices !== null) parts.push({ text: `${count(notices)} corrected rights notices drafted` });

  if (!parts.length && pii === null) return null;
  return (
    <div className="flex flex-col gap-2 border-t border-cloud-100 bg-cloud-25 px-5 py-3 sm:flex-row sm:items-center sm:gap-3 md:px-6" data-testid="handoff">
      <span className="flex shrink-0 items-center gap-2">
        <RoleAvatar role="agent.crm_bot" size="sm" />
        <MicroLabel>CRM bot handoff</MicroLabel>
      </span>
      <p className="flex flex-col items-start gap-x-2 gap-y-1 font-mono text-[12px] text-slate-600 sm:flex-row sm:flex-wrap sm:items-center">
        {parts.map((p, i) => (
          <span key={p.text} className="inline-flex items-center gap-2">
            {i > 0 ? <span className="hidden text-cloud-400 sm:inline">·</span> : null}
            <span className={cn(p.strong && "font-bold text-navy-900")}>{p.text}</span>
          </span>
        ))}
        {pii !== null ? (
          <StatusChip tone={pii === 0 ? "outline" : "held"} dot={false} className="h-6 text-[11px] sm:ml-1">
            Drafter saw {count(pii)} PII{pii === 0 ? " · names merged in code" : ""}
          </StatusChip>
        ) : null}
      </p>
    </div>
  );
}
