import { useEffect, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { AlertCircle, WifiOff } from "lucide-react";
import { type DeskProblem, useSteps } from "./state";

export type Step = { text: string; sub: string };

/**
 * The one line under a form: what went wrong, what the server is doing, or what the inputs mean.
 * Errors are said plainly and stay next to the inputs (never toast-only); a lost connection keeps
 * the form usable and offers a retry.
 */
export function FormNote({
  problem,
  busy,
  busyKey,
  steps,
  everyMs,
  hint,
  onRetry,
  onCancel,
  testId,
}: {
  problem: DeskProblem | null;
  busy: boolean;
  busyKey: string | number;
  steps: Step[];
  everyMs?: number;
  hint: ReactNode;
  onRetry?: () => void;
  /** Offered once a request has run unusually long: stop waiting (a late answer is ignored). */
  onCancel?: () => void;
  testId: string;
}) {
  return (
    <AnimatePresence mode="wait" initial={false}>
      {problem ? (
        <motion.div
          key={`problem-${problem.code}-${problem.message}`}
          initial={{ opacity: 0, y: -3 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.14 }}
          role="alert"
          data-testid={`${testId}-error`}
          data-code={problem.code}
          className="flex flex-wrap items-start gap-x-2.5 gap-y-1.5 rounded-lg bg-cloud-50 px-3 py-2 text-[13.5px] text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-200)]"
        >
          {problem.network ? <WifiOff className="mt-0.5 size-4 shrink-0 text-slate-500" aria-hidden="true" /> : <AlertCircle className="mt-0.5 size-4 shrink-0 text-slate-500" aria-hidden="true" />}
          <span className="min-w-0 flex-1">
            {problem.message}
            {problem.network ? <span className="text-slate-500"> Nothing was lost; the form still works.</span> : null}
          </span>
          {problem.network && onRetry ? (
            <button type="button" onClick={onRetry} className="shrink-0 text-[13px] font-medium text-metar-ink hover:underline">
              Try again
            </button>
          ) : null}
        </motion.div>
      ) : busy ? (
        <StepLine key={`busy-${busyKey}`} steps={steps} everyMs={everyMs} onCancel={onCancel} testId={`${testId}-progress`} />
      ) : (
        <motion.p key="hint" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.12 }} className="px-1 text-[12.5px] leading-relaxed text-slate-500">
          {hint}
        </motion.p>
      )}
    </AnimatePresence>
  );
}

const SLOW_MS = 15_000;

function StepLine({ steps, everyMs, onCancel, testId }: { steps: Step[]; everyMs?: number; onCancel?: () => void; testId: string }) {
  const step = useSteps(steps.length, everyMs);
  const current = steps[step];
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const t = window.setTimeout(() => setSlow(true), SLOW_MS);
    return () => window.clearTimeout(t);
  }, []);
  return (
    <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.12 }} className="flex flex-wrap items-center gap-x-2 gap-y-1 px-1 text-[13.5px] text-navy-900" data-testid={testId}>
      <span className="relative flex size-2" aria-hidden="true">
        <span className="absolute inline-flex size-full animate-ping rounded-full bg-metar opacity-60" />
        <span className="relative inline-flex size-2 rounded-full bg-metar" />
      </span>
      <AnimatePresence mode="wait" initial={false}>
        <motion.span key={step} initial={{ opacity: 0, y: 3 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -3 }} transition={{ duration: 0.2 }}>
          {current.text}…
        </motion.span>
      </AnimatePresence>
      <span className="font-mono text-[11.5px] text-slate-400">{slow ? "still working · this source can be slow" : current.sub}</span>
      {slow && onCancel ? (
        <button type="button" onClick={onCancel} className="text-[12.5px] font-medium text-metar-ink hover:underline">
          Stop waiting
        </button>
      ) : null}
    </motion.p>
  );
}
