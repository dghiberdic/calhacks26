import { useMemo, useState } from "react";
import { Lock } from "lucide-react";
import { toast } from "sonner";
import { invalidateAfterWrite, useQuestions } from "@/api/queries";
import type { AccessCell, AccessMatrix, Role } from "@/api/types";
import { useSession } from "@/app/session";
import { RoleAvatar, Shimmer } from "@/components/kit";
import { ROLE_LABEL, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";
import { MaskedText } from "@/components/evidence";
import { REDACTED, findPiiRecord, piiResource, principalRole, splitPii, type PiiRecord } from "./model";

/** The seat that reads passenger PII in the clear, and the one the demo masks. */
const CLEAR: Role = "claims_lead";
const MASKED: Role = "ops";

/**
 * "View as Ops": one real passenger record (the question that carries her name), as the Claims Lead gets
 * it and as Ops gets it. The broker masks PII before a response leaves the server, so this page only
 * ever holds what the current seat was given; switching seat is a real session switch.
 */
export function PiiMask({ matrix }: { matrix: AccessMatrix | undefined }) {
  const role = useSession((s) => s.role);
  const signIn = useSession((s) => s.signIn);
  const [switching, setSwitching] = useState(false);
  const questions = useQuestions("all");
  const record = useMemo(() => findPiiRecord(questions.data), [questions.data]);
  const resource = piiResource(matrix);
  const cell = (seat: Role): AccessCell | null => {
    if (!matrix || !resource) return null;
    const key = matrix.principals.find((p) => principalRole(p) === seat);
    return key ? (matrix.cells[key]?.[resource] ?? "none") : null;
  };
  const target = role === CLEAR ? MASKED : CLEAR;

  const switchTo = async (seat: Role) => {
    setSwitching(true);
    try {
      await signIn(seat);
      await invalidateAfterWrite();
      toast(`Viewing as ${ROLE_LABEL[seat]}`);
    } catch {
      toast.error("Couldn't switch seat.");
    } finally {
      setSwitching(false);
    }
  };

  return (
    <section className="rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]" aria-labelledby="pii-title">
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
        <div className="min-w-0">
          <h2 id="pii-title" className="text-[14.5px] font-semibold text-navy-900">
            PII mask
          </h2>
          <p className="mt-0.5 text-[13px] text-slate-500">The broker masks passenger fields before a response leaves the server.</p>
        </div>
        <button
          type="button"
          disabled={switching}
          onClick={() => void switchTo(target)}
          className="inline-flex h-8 shrink-0 items-center gap-2 rounded-full bg-white py-1 pl-1 pr-3 text-[12.5px] font-medium text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-300)] transition-colors hover:bg-cloud-50 disabled:opacity-50"
        >
          <span aria-hidden="true" className="inline-flex">
            <RoleAvatar role={target} size="sm" />
          </span>
          View as {ROLE_LABEL[target]}
        </button>
      </div>
      <div className="flex flex-col gap-2.5 px-5 pb-5 pt-4">
        {questions.isLoading ? (
          <>
            <Shimmer className="h-24" />
            <Shimmer className="h-24" />
          </>
        ) : !record ? (
          <p className="rounded-lg px-4 py-6 text-center text-[13.5px] text-slate-500 shadow-[inset_0_0_0_1px_var(--color-cloud-200)]">
            {ROLE_LABEL[role]} isn&rsquo;t served any record with passenger data.
          </p>
        ) : (
          <>
            <Seat seat={CLEAR} cell={cell(CLEAR)} resource={resource} record={record} viewer={role} />
            <Seat seat={MASKED} cell={cell(MASKED)} resource={resource} record={record} viewer={role} />
          </>
        )}
      </div>
    </section>
  );
}

/** One seat's view of the record. Clear text appears only when this browser was actually given it. */
function Seat({ seat, cell, resource, record, viewer }: { seat: Role; cell: AccessCell | null; resource: string | null; record: PiiRecord; viewer: Role }) {
  // The matrix decides; without a PII column, the Claims Lead is the seat that reads PII (plan §2) and the
  // record's values still come only from the server.
  const clearSeat = cell ? cell === "read" || cell === "write" || cell === "approve" : seat === CLEAR;
  const noAccess = cell === "none";
  const haveClear = record.values.length > 0;
  const showClear = clearSeat && haveClear;
  const sentence = firstSentenceWithPii(record);
  return (
    <article className={cn("rounded-lg px-4 py-3", viewer === seat ? "bg-cloud-50 shadow-[inset_0_0_0_1px_var(--color-cloud-300)]" : "shadow-[inset_0_0_0_1px_var(--color-cloud-200)]")} aria-label={`${ROLE_LABEL[seat]}'s view`}>
      <header className="flex flex-wrap items-center gap-2">
        <span aria-hidden="true" className="inline-flex">
          <RoleAvatar role={seat} size="sm" />
        </span>
        <span className="text-[13px] font-medium text-navy-900">{ROLE_LABEL[seat]}</span>
        {cell ? <span className="font-mono text-[11px] text-slate-400">{resource ? `${resource} · ${cell}` : cell}</span> : null}
        {viewer === seat ? <span className="micro text-slate-400">you</span> : null}
        <span className="ml-auto font-mono text-[11px] text-slate-400">{[record.question.id, ...record.question.case_refs.map(shortId)].join(" · ")}</span>
      </header>
      {noAccess ? (
        <p className="mt-2 text-[13px] text-slate-500">Can&rsquo;t open passenger records.</p>
      ) : !sentence ? null : (
        <>
          <p className="mt-2 text-[13.5px] leading-relaxed text-navy-900">
            {splitPii(sentence, record.values).map((run, i) => (run.pii ? showClear ? <Clear key={i}>{run.text}</Clear> : <Masked key={i} /> : <span key={i}>{run.text}</span>))}
          </p>
          <dl className="mt-2 flex flex-col gap-1">
            {record.fields.map((f) => (
              <div key={f.field} className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <dt className="text-[11.5px] text-slate-400">
                  <span className="font-mono">{f.field}</span>
                </dt>
                <dd className="text-[13px]">{showClear ? <Clear>{f.value}</Clear> : <Masked />}</dd>
              </div>
            ))}
          </dl>
          {clearSeat && !haveClear ? (
            <p className="mt-2 flex items-center gap-1.5 text-[12px] text-slate-500">
              <Lock className="size-3" aria-hidden="true" />
              Masked for you too, as {ROLE_LABEL[viewer]}.
            </p>
          ) : null}
        </>
      )}
    </article>
  );
}

function Clear({ children }: { children: string }) {
  return <span className="rounded-sm bg-cloud-100 px-0.5 font-medium text-navy-900 [box-decoration-break:clone]">{children}</span>;
}

/** The same quiet "hidden" mark the evidence lists use for what the broker removed. */
function Masked() {
  return <MaskedText text={REDACTED} />;
}

/** The sentence of the question's finding that names the passenger (or shows where the name was removed). */
function firstSentenceWithPii(record: PiiRecord): string | null {
  const sentences = record.text.split(/(?<=[.!?])\s+/);
  return sentences.find((s) => splitPii(s, record.values).some((r) => r.pii)) ?? null;
}
