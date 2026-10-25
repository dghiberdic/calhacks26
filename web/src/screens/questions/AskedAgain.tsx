import { useState } from "react";
import { Loader2, Repeat2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/client";
import { invalidateAfterWrite } from "@/api/queries";
import type { Question, Rule } from "@/api/types";
import { Explain } from "@/components/explain";
import { ErrorNote } from "@/components/kit";
import { ROLE_LABEL } from "@/lib/format";
import { plainIds } from "@/lib/plain";
import { cn } from "@/lib/utils";
import { widenLabel } from "./lib";
import { useViewAs } from "./viewAs";

/**
 * The "asks again" beat, said out loud: a rule covers this pattern, but this case is outside its scope, so
 * StormCheck asks instead of stretching the ruling. One click widens the rule by one rung (POST
 * /rules/{id}/widen); the answer form below stays as the alternative.
 */
export function AskedAgainBanner({ question, canAnswer, className, boxed }: { question: Question; canAnswer: boolean; className?: string; boxed?: boolean }) {
  const again = question.asked_again;
  const { viewAs, busy: switching } = useViewAs();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  if (!again) return null;
  const widen = again.widen ?? null;
  const label = widenLabel(question);

  const run = async () => {
    if (!widen || busy) return;
    setBusy(true);
    setError(null);
    try {
      let rule: Rule = (await api.widen(widen.rule_id)).rule;
      // A server that only proposes the wider version: the rule's own authority confirms it in the same click.
      if (rule.status === "proposed" || rule.status === "shadow") rule = (await api.confirm(rule.id)).rule;
      await invalidateAfterWrite();
      toast(`Widened to ${rule.id}@${rule.version}`, { description: "This case settles under the wider rule, with it cited." });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-label="Asked again" data-testid="asked-again" className={cn(boxed ? "rounded-xl bg-held-wash/60 px-4 py-3.5" : "border-b border-held/30 bg-held-wash/60 px-5 py-4 md:px-6", className)}>
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 max-w-[78ch]">
          <p className="flex items-center gap-2 text-[13px] font-semibold text-held-ink">
            <Repeat2 className="size-4 shrink-0" aria-hidden="true" />
            <span>
              Asked again · <Explain term="rule-scope">outside your rule&rsquo;s scope</Explain>
            </span>
          </p>
          <p className="mt-1.5 text-[14px] leading-relaxed text-navy-900">{plainIds(again.reason)}</p>
          <p className="mt-1 text-[12.5px] text-slate-500">
            <span className="font-mono font-bold text-navy-900">{again.rule_ref}</span> · {again.rule_title}
          </p>
        </div>
        {widen ? (
          canAnswer ? (
            <button
              type="button"
              onClick={() => void run()}
              disabled={busy}
              className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-lg bg-navy-900 px-4 text-[14px] font-semibold text-cloud-50 transition-colors hover:bg-navy-800 disabled:cursor-not-allowed disabled:opacity-45"
            >
              {busy ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
              {busy ? "Widening the rule" : label}
            </button>
          ) : (
            <div className="flex max-w-[34ch] flex-col items-start gap-2">
              <p className="text-[12.5px] leading-snug text-slate-500">Only the {ROLE_LABEL[question.routed_to]} can widen {again.rule_ref.split("@")[0]}.</p>
              <button
                type="button"
                disabled={!!switching}
                onClick={() => void viewAs(question.routed_to)}
                className="inline-flex h-9 items-center justify-center gap-2 rounded-lg bg-white px-3.5 text-[13px] font-semibold text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-300)] transition-colors hover:bg-cloud-50 disabled:opacity-50"
              >
                {switching ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
                View as {ROLE_LABEL[question.routed_to]} to widen
              </button>
            </div>
          )
        ) : null}
      </div>
      {canAnswer && widen ? <p className="mt-2 text-[12.5px] text-slate-500">Or rule on this case alone with the form below; the rule stays as it is.</p> : null}
      {error ? <ErrorNote error={error} className="mt-3" /> : null}
    </section>
  );
}
