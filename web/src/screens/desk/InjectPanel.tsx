import { useId, useMemo, useRef } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Check, CornerDownLeft, Loader2, Play, RotateCcw } from "lucide-react";
import { useInjections, useStormRun } from "@/api/queries";
import type { InjectKind, Injection } from "@/api/types";
import { MicroLabel, StatusChip } from "@/components/chips";
import { ErrorNote, Shimmer } from "@/components/kit";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { shortId, zulu } from "@/lib/format";
import { HERO_STORM } from "@/lib/storms";
import { cn } from "@/lib/utils";
import { InjectResult } from "./InjectResult";
import { FormNote } from "./Notes";
import { useDesk } from "./state";
import { KINDS, KIND_BY_ID, kindChip } from "./templates";
import { useBringIntoView } from "./useBringIntoView";

const STEPS = (label: string) => [
  { text: `Reading the ${label.toLowerCase()}`, sub: "documents are data, never commands" },
  { text: "Checking every span against the text", sub: "no quote, no fact" },
  { text: "Re-deciding what it touches", sub: "the engine decides; the Reader only reads" },
  { text: "Writing it to the trace", sub: "every step committed" },
];

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

const FIELD = "shadow-[inset_0_0_0_1px_var(--color-cloud-300)] outline-none transition-shadow focus:shadow-[inset_0_0_0_1.5px_var(--color-navy-800),0_0_0_4px_color-mix(in_srgb,var(--color-metar)_16%,transparent)]";

/** Inject a document: rehearsed scenarios on the left (they stay in view), your own on the right, the answer under it. */
export function InjectPanel() {
  const inj = useDesk((s) => s.inject);
  const busy = !!inj.pending;
  const result = inj.result;
  const scenarios = useInjections();
  const scenario = result?.scenarioId ? scenarios.data?.find((s) => s.id === result.scenarioId) : undefined;

  return (
    <section aria-labelledby="desk-inject-title" className="flex flex-col gap-3">
      <div className="px-1">
        <h2 id="desk-inject-title" className="display-tight text-[22px] text-navy-900">
          Inject a document
        </h2>
        <p className="mt-1 max-w-[70ch] text-[14px] text-slate-500">Hand the Reader a messy line. A fact only counts if it quotes the text; the engine decides what it means.</p>
      </div>

      <div className="grid items-start gap-3 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <ScenarioList busy={busy} />

        <div className="flex min-w-0 flex-col gap-3">
          <Editor />

          <AnimatePresence mode="wait">
            {busy && !result ? (
              <motion.div key="skeleton" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex flex-col gap-3" data-testid="inject-skeleton">
                <Shimmer className="h-[220px] rounded-xl" />
                <Shimmer className="h-[160px] rounded-xl" />
              </motion.div>
            ) : result ? (
              <Answer key={result.response.source.id + String(result.startSeq)} dim={busy} scenarioId={result.scenarioId}>
                <div className="px-1 text-[13px] text-slate-500">
                  {scenario ? (
                    <>
                      <p className="flex flex-wrap items-baseline gap-x-2">
                        <span className="micro text-slate-400">Rehearsed</span>
                        <span className="font-medium text-navy-900">{scenario.title}</span>
                      </p>
                      <p className="mt-0.5">
                        <span className="text-slate-400">Expected:</span> {scenario.expected}
                      </p>
                    </>
                  ) : (
                    <p className="flex flex-wrap items-baseline gap-x-2">
                      <span className="micro text-slate-400">Your document</span>
                      <span className="font-medium text-navy-900">{KIND_BY_ID[result.request.kind]?.label ?? result.request.kind}</span>
                      {result.request.flight_id ? <span className="font-mono text-[12px]">· {shortId(result.request.flight_id)}</span> : null}
                    </p>
                  )}
                </div>
                <InjectResult request={result.request} response={result.response} startSeq={result.startSeq} before={result.before} after={result.after} />
              </Answer>
            ) : null}
          </AnimatePresence>
        </div>
      </div>
    </section>
  );
}

function Answer({ children, dim, scenarioId }: { children: React.ReactNode; dim: boolean; scenarioId: string | null }) {
  const ref = useBringIntoView<HTMLDivElement>();
  return (
    <motion.div
      ref={ref}
      data-testid="inject-answer"
      data-scenario-id={scenarioId ?? "own"}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: dim ? 0.45 : 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      className={cn("flex scroll-mt-[72px] flex-col gap-2", dim && "pointer-events-none")}
    >
      {children}
    </motion.div>
  );
}

/** The 8 rehearsed scenarios from GET /api/injections: title + the expected one-liner; one click runs it. */
function ScenarioList({ busy }: { busy: boolean }) {
  const scenarios = useInjections();
  const pendingId = useDesk((s) => (s.inject.pending ? s.inject.scenarioId : null));
  const doneId = useDesk((s) => s.inject.result?.scenarioId ?? null);
  const runInject = useDesk((s) => s.runInject);

  const run = (s: Injection) => {
    if (busy) return;
    void runInject({ ...s.request, flight_id: s.request.flight_id ?? null }, s.id);
  };

  return (
    <div className="rounded-2xl bg-card p-2 shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)] lg:sticky lg:top-[72px] lg:max-h-[calc(100svh-88px)] lg:overflow-y-auto">
      <div className="flex items-center justify-between gap-2 px-3 pb-1.5 pt-2.5">
        <MicroLabel>Rehearsed{scenarios.data ? ` · ${scenarios.data.length}` : ""}</MicroLabel>
        <span className="text-[11.5px] text-slate-400">One click fills it in and runs it</span>
      </div>
      {scenarios.isError ? (
        <ErrorNote error={scenarios.error} onRetry={() => void scenarios.refetch()} className="m-2" />
      ) : !scenarios.data ? (
        <div className="flex flex-col gap-1.5 p-2">
          {Array.from({ length: 8 }, (_, i) => (
            <Shimmer key={i} className="h-[58px]" />
          ))}
        </div>
      ) : (
        <ol className="flex flex-col" data-testid="desk-scenarios">
          {scenarios.data.map((s, i) => {
            const running = busy && pendingId === s.id;
            const done = !busy && doneId === s.id;
            return (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => run(s)}
                  disabled={busy}
                  aria-current={done || undefined}
                  data-testid="desk-scenario"
                  data-scenario-id={s.id}
                  className={cn(
                    "group grid w-full grid-cols-[26px_minmax(0,1fr)_auto] items-start gap-x-2.5 rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-cloud-50 disabled:cursor-progress",
                    done && "bg-cloud-50 shadow-[inset_2px_0_0_var(--color-navy-900)]",
                    busy && !running && "opacity-50",
                  )}
                >
                  <span className="pt-0.5 font-mono text-[11.5px] tabular-nums text-slate-400">{String(i + 1).padStart(2, "0")}</span>
                  <span className="min-w-0">
                    <span className="block text-[14px] font-medium leading-snug text-navy-900">{s.title}</span>
                    <span className="mt-0.5 line-clamp-2 text-[12.5px] leading-snug text-slate-500" title={s.expected}>
                      {s.expected}
                    </span>
                  </span>
                  <span className="flex items-center gap-2 pt-0.5">
                    <StatusChip tone="outline" dot={false} className="hidden h-5 text-[10.5px] sm:inline-flex">
                      {kindChip(s.request.kind)}
                    </StatusChip>
                    <span className={cn("inline-flex size-6 items-center justify-center rounded-full transition-colors", running || done ? "bg-navy-900 text-cloud-50" : "bg-cloud-100 text-slate-500 group-hover:bg-navy-900 group-hover:text-cloud-50")}>
                      {running ? <Loader2 className="size-3.5 animate-spin" aria-hidden="true" /> : done ? <Check className="size-3.5" aria-hidden="true" /> : <Play className="size-3 translate-x-[0.5px]" aria-hidden="true" />}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

/** Write your own: kind, an editable template, an optional flight. ⌘/Ctrl+Enter injects. */
function Editor() {
  const inj = useDesk((s) => s.inject);
  const run = useDesk((s) => s.run);
  const { setKind, setDraft, resetDraft, setFlightId, runInject } = useDesk.getState();
  const hero = useStormRun(HERO_STORM);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const listId = useId();
  const textId = useId();
  const flightInputId = useId();

  const info = KIND_BY_ID[inj.kind];
  const text = inj.drafts[inj.kind];
  const edited = text !== info.template;
  const busy = !!inj.pending;
  const steps = STEPS(KIND_BY_ID[inj.pending?.kind ?? inj.kind].label);

  // Flight ids to suggest: the day just run, then the hero storm.
  const flightOptions = useMemo(() => {
    const rows = [...(run?.flights ?? []), ...(hero.data?.flights ?? [])];
    const seen = new Set<string>();
    return rows
      .filter((r) => (seen.has(r.flight.id) ? false : (seen.add(r.flight.id), true)))
      .slice(0, 80)
      .map((r) => ({ id: r.flight.id, label: `${r.flight.number} ${r.flight.origin}–${r.flight.dest} ${zulu(r.flight.sched_dep)} · ${r.flight.status}` }));
  }, [run, hero.data]);

  const submit = () => {
    if (busy) return;
    if (!text.trim()) {
      useDesk.setState((s) => ({ inject: { ...s.inject, problem: { code: "client", message: "Paste or type a document first." } } }));
      textRef.current?.focus();
      return;
    }
    void runInject({ kind: inj.kind, text, flight_id: inj.flightId.trim() || null });
  };

  return (
    <form
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
      className="flex flex-col rounded-2xl bg-card p-4 shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)] md:p-5"
      aria-label="Write your own document"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <MicroLabel>Kind</MicroLabel>
        <span className="text-[11.5px] text-slate-400">{info.from}</span>
      </div>
      <ToggleGroup
        type="single"
        value={inj.kind}
        onValueChange={(v) => v && setKind(v as InjectKind)}
        spacing={1}
        className="mt-2 grid w-full grid-cols-3 gap-1 rounded-xl bg-cloud-50 p-1 shadow-[inset_0_0_0_1px_var(--color-cloud-200)] sm:flex sm:flex-wrap"
        aria-label="Kind of document"
      >
        {KINDS.map((k) => (
          <ToggleGroupItem
            key={k.kind}
            value={k.kind}
            className="h-8 flex-1 rounded-lg px-2.5 text-[13px] text-slate-600 hover:bg-white/70 data-[state=on]:bg-white data-[state=on]:text-navy-900 data-[state=on]:shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.06)]"
            data-testid={`kind-${k.kind}`}
          >
            {k.label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>

      <div className="mt-4 flex items-center justify-between gap-2">
        <label htmlFor={textId} className="micro text-slate-500">
          Document
        </label>
        {edited ? (
          <button type="button" onClick={() => resetDraft(inj.kind)} className="inline-flex items-center gap-1 text-[12px] text-slate-500 hover:text-navy-900">
            <RotateCcw className="size-3" aria-hidden="true" /> Back to the template
          </button>
        ) : (
          <span className="text-[11.5px] text-slate-400">A template. Edit anything.</span>
        )}
      </div>
      <textarea
        id={textId}
        ref={textRef}
        value={text}
        onChange={(e) => setDraft(inj.kind, e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            submit();
          }
        }}
        spellCheck={!info.mono}
        rows={6}
        className={cn("mt-2 min-h-[150px] w-full resize-y rounded-xl bg-white px-4 py-3 text-navy-900 placeholder:text-slate-400", FIELD, info.mono ? "font-mono text-[12.5px] leading-[1.7]" : "text-[14px] leading-relaxed")}
        placeholder="Paste or type a document."
        data-testid="inject-text"
      />

      <div className="mt-3 grid gap-2.5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
        <div>
          <label htmlFor={flightInputId} className="micro text-slate-500">
            Flight <span className="normal-case tracking-normal text-slate-400">(optional)</span>
          </label>
          <input
            id={flightInputId}
            list={listId}
            value={inj.flightId}
            onChange={(e) => setFlightId(e.target.value)}
            placeholder="e.g. NS31@2025-01-24"
            autoComplete="off"
            spellCheck={false}
            className={cn("mt-1.5 h-11 w-full rounded-xl bg-white px-3.5 font-mono text-[13px] text-navy-900 placeholder:font-sans placeholder:text-slate-400", FIELD)}
            data-testid="inject-flight"
          />
          <datalist id={listId}>
            {flightOptions.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </datalist>
        </div>
        <button
          type="submit"
          disabled={busy}
          className="inline-flex h-11 items-center justify-center gap-2.5 rounded-xl bg-navy-900 px-5 text-[14.5px] font-semibold text-cloud-50 transition-colors hover:bg-navy-800 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-metar/30 disabled:cursor-progress disabled:bg-navy-800"
          data-testid="inject-submit"
        >
          {busy ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
          {busy ? "Reading" : "Inject"}
          {!busy ? (
            <kbd className="hidden items-center gap-0.5 rounded bg-white/10 px-1.5 py-0.5 font-mono text-[11px] font-normal text-cloud-300 md:inline-flex" aria-hidden="true">
              {isMac ? "⌘" : "Ctrl"}
              <CornerDownLeft className="size-3" />
            </kbd>
          ) : null}
        </button>
      </div>

      <div className="mt-3 min-h-[22px]" aria-live="polite">
        <FormNote
          problem={inj.problem}
          busy={busy}
          busyKey={inj.scenarioId ?? inj.kind}
          steps={steps}
          everyMs={1100}
          hint={<>The Reader has no tools and can&rsquo;t approve anything. If it can&rsquo;t answer in time, a labelled regex fallback reads the line.</>}
          onRetry={submit}
          onCancel={useDesk.getState().stopInject}
          testId="inject"
        />
      </div>
    </form>
  );
}
