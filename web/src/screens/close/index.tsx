import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Check, Download, Lock } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/client";
import { invalidateAfterWrite, qk, useCfo, useCommits, useCurve, useEstimate, useInvariants, useJournal, useRollforward, useTrace } from "@/api/queries";
import { useLiveFeed } from "@/api/stream";
import type { CurveSegment, EstimateCard, MonthEndResponse, Role, Rollforward } from "@/api/types";
import { useSession } from "@/app/session";
import { MicroLabel, TiesChip } from "@/components/chips";
import { Empty, ErrorNote, PageHeader, RoleAvatar, Shimmer } from "@/components/kit";
import { eur, periodLabel, ROLE_LABEL } from "@/lib/format";
import { HERO_STORM, stormName } from "@/lib/storms";
import { CfoBridge } from "./bridge";
import { ClaimCurveChart, type CohortActual } from "./curve";
import { JournalDrafts } from "./drafts";
import { EstimateCardView } from "./estimate";
import { isSegment, journalTies, lockedPeriods, rollforwardCsv, rollforwardTotals, SEGMENTS } from "./model";
import { CloseRail, InvariantsPanel } from "./rail";
import { FootingNotes, RollforwardTable } from "./rollforward";
import { SectionHead, Segmented } from "./ui";

/** The demo's close periods (identifiers, not figures): January closes with 6 claims, February runs the BF true-up. */
const CLOSE_PERIODS = ["2025-01", "2025-02"] as const;
const DEFAULT_PERIOD = "2025-02";

/** Where the work is: the latest close period with drafts still pending (January on the stub, February after it closes). */
function workingPeriod(entries: { period: string; status: string }[] | undefined): string | undefined {
  return (entries ?? [])
    .filter((e) => e.status === "draft" && (CLOSE_PERIODS as readonly string[]).includes(e.period))
    .map((e) => e.period)
    .sort()
    .at(-1);
}

const PANEL = "rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]";

/** J6 · Liability & Close: the EU261 compensation liability for the Controller and the CFO. */
export default function CloseScreen() {
  const location = useLocation();
  const navigate = useNavigate();
  const params = new URLSearchParams(location.search);
  const asked = params.get("period") ?? "";
  const everyEntry = useQuery({ queryKey: qk.journal(undefined, undefined), queryFn: () => api.journal() });
  const period: string = (CLOSE_PERIODS as readonly string[]).includes(asked) ? asked : (workingPeriod(everyEntry.data) ?? DEFAULT_PERIOD);
  const role = useSession((s) => s.role);
  const canAct = role === "controller" || role === "cfo";

  const cfo = useCfo();
  const rf = useRollforward(period);
  const estimate = useEstimate(HERO_STORM);
  const journal = useJournal(period);
  const long = useCurve("long_haul_gt3500");
  const medium = useCurve("medium_1500_3500");
  const short = useCurve("short_le1500");
  const trace = useTrace();
  const commits = useCommits();
  const live = useLiveFeed((s) => s.events);

  const [localLocks, setLocalLocks] = useState<string[]>([]);
  const [monthEnd, setMonthEnd] = useState<MonthEndResponse | null>(null);
  const [segmentChoice, setSegmentChoice] = useState<CurveSegment | null>(null);

  const invariants = useInvariants();
  // The rollforward says so itself now (Rollforward.locked, #16); the trace and invariants cover older servers.
  const rfLocked = rf.data?.locked ? rf.data.period : null;
  const locked = useMemo(
    () => lockedPeriods([...(trace.data ?? []), ...live], commits.data, rfLocked ? [...localLocks, rfLocked] : localLocks, invariants.data),
    [trace.data, live, commits.data, localLocks, invariants.data, rfLocked],
  );
  const isLocked = locked.has(period);

  const curves = useMemo(() => ({ long_haul_gt3500: long.data, medium_1500_3500: medium.data, short_le1500: short.data }), [long.data, medium.data, short.data]);
  const est = estimate.data;
  const cohortSegment: CurveSegment = isSegment(est?.segment) ? est.segment : "long_haul_gt3500";
  const focus = segmentChoice ?? cohortSegment;
  const cohortCurve = curves[cohortSegment];
  const actual = useMemo(() => cohortActual(est, cohortCurve), [est, cohortCurve]);

  // A month-end already drafted (e.g. after a reload) shows from the journal: the BF true-up carries its estimate.
  const trueUps = (journal.data ?? []).filter((e) => (e.kind === "change_in_estimate" || e.ias8_class === "change_in_estimate") && e.estimate_ref);
  const monthEndView: MonthEndResponse | null =
    monthEnd && monthEnd.rollforward?.period === period ? monthEnd : trueUps.length && rf.data ? { entries: trueUps, rollforward: rf.data, estimate: est as EstimateCard } : null;
  const justRan = !!monthEnd && monthEnd.rollforward?.period === period;
  const ties = useMemo(() => (rf.data && journal.data ? journalTies(rf.data, journal.data) : {}), [rf.data, journal.data]);

  // The period lives in the URL; the hash (a journal entry, from the Flight File) survives a period switch.
  const setPeriod = useCallback(
    (p: string) => {
      const next = new URLSearchParams(location.search);
      next.set("period", p);
      navigate({ pathname: location.pathname, search: `?${next}`, hash: location.hash }, { replace: true });
    },
    [location.pathname, location.search, location.hash, navigate],
  );

  // /close#JE-000123: open the entry's period, then the journal scrolls to it.
  const focusId = /^#JE-[A-Za-z0-9:_-]+$/.test(location.hash) ? decodeURIComponent(location.hash.slice(1)) : null;
  const focusPeriod = focusId ? everyEntry.data?.find((e) => e.id === focusId)?.period : undefined;
  const jumped = useRef<string | null>(null);
  useEffect(() => {
    if (!focusId || !focusPeriod || jumped.current === focusId) return;
    jumped.current = focusId;
    if (focusPeriod !== period && (CLOSE_PERIODS as readonly string[]).includes(focusPeriod)) setPeriod(focusPeriod);
  }, [focusId, focusPeriod, period, setPeriod]);

  return (
    <div className="mx-auto flex max-w-[1280px] flex-col gap-3">
      <PageHeader
        className="mb-3"
        eyebrow={<MicroLabel>Controller · CFO</MicroLabel>}
        title="Liability & Close"
        actions={
          <Segmented
            label="Period"
            value={period}
            onChange={setPeriod}
            options={CLOSE_PERIODS.map((p) => ({ value: p, label: periodLabel(p), title: locked.has(p) ? `${periodLabel(p)} is locked` : `${periodLabel(p)} is open`, badge: locked.has(p) ? <Lock className="size-3 opacity-70" aria-label="locked" /> : null }))}
          />
        }
      >
        The EU261 compensation liability, a reduction of passenger revenue: drafted, rolled forward by cohort and tied to GL 2140.
      </PageHeader>

      {!canAct ? <ReadOnlyHint role={role} /> : null}

      {/* the CFO bridge */}
      {cfo.isError ? (
        <ErrorNote error={cfo.error} onRetry={() => void cfo.refetch()} />
      ) : !cfo.data ? (
        <Shimmer className="h-[318px] rounded-xl" />
      ) : !cfo.data.full_entitlement_cents && !cfo.data.drafted_liability_cents ? (
        <Empty title="No EU261 compensation liability drafted yet">When a storm run finds passengers owed, the bridge from cash basis to the full entitlement shows here.</Empty>
      ) : (
        <CfoBridge metrics={cfo.data} curve={cohortCurve} />
      )}

      <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-3 min-[87.5rem]:grid-cols-[minmax(0,1fr)_304px]">
        {/* 2140 rollforward */}
        <section aria-labelledby="rollforward-title" className={PANEL}>
          <div className="px-5 pt-4 md:px-6">
            <SectionHead
              id="rollforward-title"
              eyebrow={<MicroLabel>2140 · rollforward by cohort</MicroLabel>}
              title="EU261 compensation liability (estimated)"
              actions={rf.data?.rows.length ? <RollforwardChips rf={rf.data} /> : null}
            >
              {periodLabel(period)} · {isLocked ? "locked" : "open"} · € · negatives in parentheses
            </SectionHead>
          </div>
          <div className="px-5 pb-4 pt-4 md:px-6">
            {rf.isError ? (
              <ErrorNote error={rf.error} onRetry={() => void rf.refetch()} />
            ) : !rf.data ? (
              <Shimmer className="h-[400px]" />
            ) : !rf.data.rows.length ? (
              <Empty title={`No 2140 movements in ${periodLabel(period)}`}>Nothing was drafted to the EU261 compensation liability in this period.</Empty>
            ) : (
              <>
                <RollforwardTable rf={rf.data} highlight={justRan ? "change_in_estimate_cents" : null} ties={ties} segments={est ? { [est.cohort]: est.segment } : undefined} />
                <FootingNotes rf={rf.data} />
              </>
            )}
          </div>
          {rf.data?.rows.length ? (
            <RollforwardFooter period={period} locked={locked} cie={rollforwardTotals(rf.data).movements.change_in_estimate_cents}>
              <IntegrityLine rf={rf.data} ties={ties} />
            </RollforwardFooter>
          ) : null}
        </section>

        <CloseRail
          period={period}
          locked={isLocked}
          canAct={canAct}
          monthEnd={monthEndView}
          onMonthEnd={setMonthEnd}
          onLocked={(p) => setLocalLocks((l) => (l.includes(p) ? l : [...l, p]))}
          pendingDrafts={(journal.data ?? []).filter((e) => e.status === "draft").length}
          tiesToGl={rf.data ? rf.data.ties_to_gl : null}
        />
      </div>

      <InvariantsPanel />

      <div className="grid grid-cols-[minmax(0,1fr)] items-stretch gap-3 xl:grid-cols-2">
        {estimate.isError ? (
          <ErrorNote error={estimate.error} onRetry={() => void estimate.refetch()} />
        ) : !est ? (
          <Shimmer className="h-[440px] rounded-xl" />
        ) : (
          <EstimateCardView est={est} curve={cohortCurve} />
        )}

        <section aria-labelledby="curve-title" className={PANEL}>
          <div className="px-5 pt-4">
            <SectionHead
              id="curve-title"
              eyebrow={<MicroLabel>Claim curves · € basis</MicroLabel>}
              title="Expected vs actual, by segment"
              actions={
                <Segmented
                  label="Segment"
                  size="sm"
                  value={focus}
                  onChange={(s) => setSegmentChoice(s)}
                  options={SEGMENTS.map((s) => ({ value: s.id, label: s.name.replace(" haul", ""), title: `${s.name} · ${s.band}` }))}
                />
              }
            >
              Cumulative valid-claim rate by months since the event{curves[focus] ? ` · curve ${curves[focus]!.version}` : ""}
            </SectionHead>
          </div>
          <div className="px-5 pb-4 pt-4">
            {(() => {
              const q = { long_haul_gt3500: long, medium_1500_3500: medium, short_le1500: short }[focus];
              if (q.isError) return <ErrorNote error={q.error} onRetry={() => void q.refetch()} />;
              if (!q.data) return <Shimmer className="h-[300px]" />;
              if (!q.data.points.length) return <Empty title="No claim history for this segment" />;
              return <ClaimCurveChart curves={curves} focus={focus} actual={actual} />;
            })()}
          </div>
        </section>
      </div>

      <JournalDrafts
        period={period}
        entries={journal.data}
        loading={journal.isLoading}
        error={journal.isError ? journal.error : null}
        onRetry={() => void journal.refetch()}
        role={role}
        canAct={canAct}
        focusId={focusId}
      />
    </div>
  );
}

/** The cohort's actual development, placed off its curve: expected at M(k) × A/E. */
function cohortActual(est: EstimateCard | undefined, curve: { points: [number, number][] } | undefined): CohortActual | null {
  if (!est || !curve || est.actual_vs_expected === null || est.months_developed <= 0) return null;
  const expected = curve.points.find(([m]) => m === est.months_developed)?.[1];
  if (expected === undefined) return null;
  return { segment: est.segment, month: est.months_developed, expected, rate: expected * est.actual_vs_expected, ae: est.actual_vs_expected, label: stormName(est.cohort) ?? "Cohort" };
}

function RollforwardChips({ rf }: { rf: Rollforward }) {
  const download = () => {
    const blob = new Blob([rollforwardCsv(rf)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement("a"), { href: url, download: `2140-rollforward-${rf.period}.csv` });
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <>
      <button type="button" onClick={download} className="inline-flex h-6 items-center gap-1 rounded-md px-1.5 text-[12px] font-medium text-slate-500 transition-colors hover:bg-cloud-50 hover:text-navy-900" title="Download the rollforward as CSV">
        <Download className="size-3.5" aria-hidden="true" /> CSV
      </button>
      <span data-testid="ties-to-gl">
        <TiesChip ok={rf.ties_to_gl} />
      </span>
    </>
  );
}

/** "foots · cross-foots · J agrees to its journals": said only when true; FootingNotes says what isn't. */
function IntegrityLine({ rf, ties }: { rf: Rollforward; ties: ReturnType<typeof journalTies> }) {
  const t = rollforwardTotals(rf);
  const moving = (Object.entries(t.movements) as [keyof typeof ties, number][]).filter(([, v]) => v !== 0).map(([k]) => k);
  const allAgree = moving.length > 0 && moving.every((k) => ties[k]?.agrees);
  const parts = [t.everyRowFoots ? "foots" : null, t.crossFoots ? "cross-foots" : null, allAgree ? "J agrees to its journals" : null].filter(Boolean);
  if (!parts.length) return null;
  return (
    <p className="flex items-center gap-1.5 text-slate-500" title="Each cohort's movements add to its closing; the cohorts add to the total; each movement agrees to the journals of its kind">
      <Check className="size-3.5 text-slate-400" aria-hidden="true" />
      {parts.join(" · ")}
    </p>
  );
}

function RollforwardFooter({ period, locked, cie, children }: { period: string; locked: Set<string>; cie: number; children?: ReactNode }) {
  const isLocked = locked.has(period);
  const prior = [...locked].filter((p) => p < period).sort();
  const parts: string[] = [];
  if (isLocked) parts.push(`${periodLabel(period)} locked: never written again`);
  else if (cie) parts.push(`${eur(cie, { signed: true })} change in estimate, applied prospectively (IAS 8.36)`);
  if (prior.length) parts.push(`${prior.map(periodLabel).join(", ")} locked, untouched`);
  return (
    <div className="flex flex-col gap-1 border-t border-cloud-100 px-5 py-3 text-[12.5px] leading-relaxed text-slate-500 md:px-6">
      {parts.length ? <p className="text-navy-900">{parts.join(" · ")}</p> : null}
      {children}
      <p>Each cohort: reduce to the expected tail at M12; derecognise at limitation.</p>
    </div>
  );
}

/** Seats other than the Controller and the CFO read this screen; they don't act on it. */
function ReadOnlyHint({ role }: { role: Role }) {
  const signIn = useSession((s) => s.signIn);
  const switching = useSession((s) => s.switching);
  const view = async () => {
    try {
      await signIn("controller");
      await invalidateAfterWrite();
      toast(`Viewing as ${ROLE_LABEL.controller}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't switch role.");
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl bg-white px-4 py-2.5 text-[13px] text-slate-600 shadow-[inset_0_0_0_1px_var(--color-cloud-200)]" data-testid="read-only-hint">
      <RoleAvatar role={role} size="sm" />
      <span className="min-w-[min(100%,16rem)] flex-1">
        Viewing as {ROLE_LABEL[role]}: read-only. The Controller and the CFO approve journals; the Controller runs month-end and locks periods.
      </span>
      <button type="button" onClick={() => void view()} disabled={switching} className="inline-flex items-center gap-2 rounded-full px-2.5 py-1 text-[12.5px] font-medium text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-300)] transition-colors hover:bg-cloud-50 disabled:opacity-50">
        <RoleAvatar role="controller" size="sm" className="size-4 text-[7px]" />
        View as Controller
      </button>
    </div>
  );
}
