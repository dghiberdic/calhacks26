import { useMemo, useState, type ReactNode } from "react";
import { MotionConfig } from "motion/react";
import { Loader2 } from "lucide-react";
import { useQuestions, useStormRun, useStorms } from "@/api/queries";
import type { Question, Role } from "@/api/types";
import { useSession } from "@/app/session";
import { MicroLabel } from "@/components/chips";
import { ErrorNote, Money, PageHeader, RoleAvatar, Shimmer } from "@/components/kit";
import { count, ROLE_LABEL } from "@/lib/format";
import type { Flow } from "./AnswerFlow";
import { QuestionCard } from "./QuestionCard";
import { seatPhrase } from "./lib";
import { useViewAs } from "./viewAs";

const START: Flow = { step: "answer" };
/** Seats that never rule: they see questions read-only, so "waiting on" would be the wrong words. */
const READ_ONLY: Role[] = ["judge", "cfo"];

/** Questions are role-scoped by the server; a new seat starts with a clean slate. */
export default function QuestionsScreen() {
  const role = useSession((s) => s.role);
  return (
    <MotionConfig reducedMotion="user">
      <QuestionsForRole key={role} role={role} />
    </MotionConfig>
  );
}

type Held = { question: Question; flow: Flow };

function QuestionsForRole({ role }: { role: Role }) {
  const open = useQuestions("open");
  // A card mid-ruling keeps the question as it was when the ruling started: the refetch after a write
  // drops it from "open", and the person should still see the preview and the saved state.
  const [held, setHeld] = useState<Record<string, Held>>({});
  const cards = useMemo(() => {
    const live = open.data ?? [];
    const liveIds = new Set(live.map((q) => q.id));
    const list: Held[] = live.map((q) => ({ question: q, flow: held[q.id]?.flow ?? START }));
    for (const h of Object.values(held)) if (!liveIds.has(h.question.id) && h.flow.step !== "answer") list.push(h);
    // Oldest first: the question waiting longest leads.
    return list.sort((a, b) => a.question.asked_at.localeCompare(b.question.asked_at) || a.question.id.localeCompare(b.question.id));
  }, [open.data, held]);

  const openIds = new Set((open.data ?? []).map((q) => q.id));
  const openNow = cards.map((c) => c.question).filter((q) => openIds.has(q.id));
  const holding = openNow.filter((q) => q.routed_to === role).reduce((s, q) => s + (q.holds_cents ?? 0), 0);
  const mine = openNow.filter((q) => q.routed_to === role).length;

  const header = (
    <PageHeader
      eyebrow={<MicroLabel>Viewing as {ROLE_LABEL[role]}</MicroLabel>}
      title="Questions"
      actions={
        open.data && mine ? (
          <p className="text-right text-[13px] text-slate-500" data-testid="questions-summary">
            <span className="figure font-semibold text-navy-900">{count(mine)}</span> open for {seatPhrase(role)}
            {holding ? (
              <>
                {" "}
                · holding <Money cents={holding} className="font-semibold text-navy-900" />
              </>
            ) : null}
          </p>
        ) : null
      }
    >
      One question per pattern, to the person who can rule on it. A ruling becomes a policy, so the same question is never asked twice.
    </PageHeader>
  );

  if (open.isError) {
    return (
      <Frame>
        {header}
        <ErrorNote className="mt-8" error={open.error} onRetry={() => void open.refetch()} />
      </Frame>
    );
  }
  if (!open.data) {
    return (
      <Frame>
        {header}
        <div className="mt-8" role="status" aria-label="Loading questions">
          <div className="grid overflow-hidden rounded-2xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200)] lg:grid-cols-[minmax(0,1fr)_440px]">
            <div className="flex flex-col gap-3 p-6">
              <Shimmer className="h-4 w-56" />
              <Shimmer className="h-7 w-[28rem] max-w-full" />
              <Shimmer className="h-4 w-72" />
              <Shimmer className="mt-4 h-16 w-full" />
              <Shimmer className="h-16 w-full" />
              <Shimmer className="h-16 w-full" />
            </div>
            <div className="flex flex-col gap-3 bg-cloud-25 p-6">
              <Shimmer className="h-12 w-full" />
              <Shimmer className="h-12 w-full" />
              <Shimmer className="h-28 w-full" />
              <Shimmer className="h-10 w-full" />
            </div>
          </div>
        </div>
      </Frame>
    );
  }

  return (
    <Frame>
      {header}
      {cards.length ? (
        <div className="mt-8 flex flex-col gap-6">
          {cards.map(({ question, flow }) => (
            <QuestionCard key={question.id} question={question} role={role} flow={flow} onFlow={(f) => setHeld((prev) => ({ ...prev, [question.id]: { question, flow: f } }))} />
          ))}
        </div>
      ) : (
        <NothingRouted role={role} />
      )}
      <OtherSeats role={role} shown={cards.map((c) => c.question)} />
    </Frame>
  );
}

function Frame({ children }: { children: ReactNode }) {
  return <div className="mx-auto max-w-[1240px]">{children}</div>;
}

/** Who else is holding open questions, read from the storm run (counts from the API). */
function useOtherSeats(role: Role, shown: Question[]) {
  const storms = useStorms();
  const run = useStormRun(storms.data?.[0]?.id);
  return useMemo(() => {
    const ids = new Set(shown.map((q) => q.id));
    const by = new Map<Role, number>();
    for (const q of run.data?.questions ?? []) {
      if (q.routed_to === role || ids.has(q.id) || q.status === "answered") continue;
      by.set(q.routed_to, (by.get(q.routed_to) ?? 0) + 1);
    }
    return [...by.entries()];
  }, [run.data, role, shown]);
}

function NothingRouted({ role }: { role: Role }) {
  const others = useOtherSeats(role, []);
  return (
    <div className="mt-8 rounded-2xl bg-card px-6 py-12 text-center shadow-[0_0_0_1px_var(--color-cloud-200)] md:py-16" data-testid="questions-empty">
      <p className="display-tight text-[22px] text-navy-900">{READ_ONLY.includes(role) ? "No open questions." : `Nothing is waiting on ${seatPhrase(role)}.`}</p>
      <p className="mx-auto mt-2 max-w-[52ch] text-[14px] leading-relaxed text-slate-500">
        StormCheck asks only where the evidence disagrees or there is no precedent, and only the person who can rule on it.
        {others.length ? " The open questions are with:" : ""}
      </p>
      {others.length ? <SeatButtons seats={others} className="mt-5 justify-center" /> : null}
    </div>
  );
}

function OtherSeats({ role, shown }: { role: Role; shown: Question[] }) {
  const others = useOtherSeats(role, shown);
  if (!shown.length || !others.length) return null;
  return (
    <div className="mt-8 flex flex-wrap items-center gap-3 border-t border-cloud-200 pt-5">
      <span className="text-[13px] text-slate-500">Also open, for other seats</span>
      <SeatButtons seats={others} />
    </div>
  );
}

function SeatButtons({ seats, className }: { seats: [Role, number][]; className?: string }) {
  const { viewAs, busy } = useViewAs();
  return (
    <div className={`flex flex-wrap gap-2 ${className ?? ""}`}>
      {seats.map(([r, n]) => (
        <button
          key={r}
          type="button"
          disabled={!!busy}
          onClick={() => void viewAs(r)}
          className="inline-flex h-9 items-center gap-2 rounded-full bg-white py-1 pl-1 pr-3.5 text-[13px] text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-300)] transition-colors hover:bg-cloud-50 disabled:opacity-50"
        >
          {busy === r ? <Loader2 className="mx-1 size-4 animate-spin text-slate-400" aria-hidden="true" /> : <RoleAvatar role={r} />}
          View as {ROLE_LABEL[r]}
          <span className="figure text-slate-400">{count(n)}</span>
        </button>
      ))}
    </div>
  );
}
