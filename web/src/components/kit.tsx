import type { ReactNode } from "react";
import { AlertCircle, Loader2 } from "lucide-react";
import type { Cents, Confidence, Role, TraceEvent } from "@/api/types";
import { ApiError } from "@/api/client";
import { eur, pct, ROLE_INITIALS, ROLE_LABEL, routedTo, shortId, zulu } from "@/lib/format";
import { cn } from "@/lib/utils";
import { StatusChip, TraceChip } from "./chips";

// ---------- money ----------
/** Integer cents as euros in tabular Archivo; negatives in parentheses. */
export function Money({ cents, className, signed, withCents }: { cents: Cents | null | undefined; className?: string; signed?: boolean; withCents?: boolean }) {
  return <span className={cn("figure whitespace-nowrap", className)}>{eur(cents, { signed, cents: withCents })}</span>;
}

// ---------- confidence ----------
/** "cause-finding confidence 91% · fault logged before storm"; "uncalibrated" when there is no model for the kind. */
export function ConfidenceLine({ confidence, reason, className, showCaps = true }: { confidence: Confidence; reason?: string | null; className?: string; showCaps?: boolean }) {
  const score = confidence.score === null ? "uncalibrated" : pct(confidence.score);
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-x-1.5 gap-y-1 font-mono text-[12px] text-slate-600", className)}>
      <span>
        {confidence.label} <span className="font-bold text-navy-900">{score}</span>
        {reason ? <span className="text-slate-500"> · {reason}</span> : null}
      </span>
      {showCaps && (confidence.caps ?? []).map((cap) => <StatusChip key={cap} tone="outline" dot={false} className="h-5 text-[10.5px]">{cap}</StatusChip>)}
    </span>
  );
}

/** A thin bar for a 0–1 score; empty and hatched when uncalibrated. */
export function ScoreBar({ score, className }: { score: number | null; className?: string }) {
  return (
    <span className={cn("relative block h-1.5 w-full overflow-hidden rounded-full bg-cloud-200", className)} aria-hidden="true">
      {score === null ? (
        <span className="absolute inset-0 bg-[repeating-linear-gradient(45deg,transparent,transparent_3px,var(--color-cloud-300)_3px,var(--color-cloud-300)_5px)]" />
      ) : (
        <span className="absolute inset-y-0 left-0 rounded-full bg-navy-800" style={{ width: `${Math.max(0, Math.min(1, score)) * 100}%` }} />
      )}
    </span>
  );
}

// ---------- people ----------
/** Initials for a seat. `decorative` when the seat's name is written next to it, so screen readers say it once. */
export function RoleAvatar({ role, size = "md", className, decorative }: { role: Role; size?: "sm" | "md"; className?: string; decorative?: boolean }) {
  const agent = role.startsWith("agent.");
  return (
    <span
      title={decorative ? undefined : ROLE_LABEL[role]}
      aria-hidden={decorative || undefined}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full font-mono font-bold",
        size === "sm" ? "size-5 text-[8.5px]" : "size-7 text-[10px]",
        agent ? "bg-cloud-100 text-slate-600 shadow-[inset_0_0_0_1px_var(--color-cloud-300)]" : "bg-navy-850 text-cloud-50",
        className,
      )}
    >
      {ROLE_INITIALS[role]}
    </span>
  );
}

/** "Routed to the Claims Lead" + avatar + "Holds €600". */
export function RoutedTo({ role, holdsCents, className }: { role: Role; holdsCents?: Cents | null; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 text-[13px] text-slate-600", className)}>
      <RoleAvatar role={role} size="sm" decorative />
      <span>{routedTo(role)}</span>
      {holdsCents ? (
        <span className="text-held-ink">
          · Holds <Money cents={holdsCents} />
        </span>
      ) : null}
    </span>
  );
}

// ---------- feed ----------
/** Past-tense feed row ending `ID · €amount · STATUS`, with its time. */
export function FeedRow({ event, className, dark }: { event: TraceEvent; className?: string; dark?: boolean }) {
  return (
    <li className={cn("grid grid-cols-[52px_minmax(0,1fr)_auto] items-start gap-3 py-2.5", className)}>
      <span className={cn("pt-0.5 font-mono text-[11px] tabular-nums", dark ? "text-cloud-500" : "text-slate-400")}>{zulu(event.at)}</span>
      <span className="min-w-0">
        <span className={cn("block text-[13.5px] leading-snug", dark ? "text-cloud-100" : "text-navy-900")}>{event.summary}</span>
        <span className={cn("mt-0.5 block font-mono text-[11px]", dark ? "text-cloud-500" : "text-slate-400")}>
          {[event.ref ? shortId(event.ref) : null, event.amount_cents !== null && event.amount_cents !== undefined ? eur(event.amount_cents) : null, event.actor].filter(Boolean).join(" · ")}
        </span>
      </span>
      <TraceChip chip={event.chip} className={dark ? "shadow-[inset_0_0_0_1px_rgba(255,255,255,0.08)]" : undefined} />
    </li>
  );
}

// ---------- page furniture ----------
export function PageHeader({ eyebrow, title, children, actions, className }: { eyebrow?: ReactNode; title: ReactNode; children?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <header className={cn("flex flex-wrap items-end justify-between gap-x-6 gap-y-3", className)}>
      <div className="min-w-0">
        {eyebrow ? <div className="mb-2">{eyebrow}</div> : null}
        <h1 className="display-tight text-[28px] leading-tight text-navy-900 md:text-[32px]">{title}</h1>
        {children ? <div className="mt-1.5 max-w-[68ch] text-[14.5px] leading-relaxed text-slate-500">{children}</div> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </header>
  );
}

/** White surface on the cloud background. */
export function Panel({ children, className, title, actions, footer, padded = true }: { children: ReactNode; className?: string; title?: ReactNode; actions?: ReactNode; footer?: ReactNode; padded?: boolean }) {
  return (
    <section className={cn("rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]", className)}>
      {title || actions ? (
        <div className="flex items-center justify-between gap-3 px-5 pt-4">
          {title ? <h2 className="text-[14.5px] font-semibold text-navy-900">{title}</h2> : <span />}
          {actions}
        </div>
      ) : null}
      <div className={cn(padded && "p-5", padded && (title || actions) && "pt-3")}>{children}</div>
      {footer ? <div className="border-t border-cloud-100 px-5 py-3 text-[13px] text-slate-500">{footer}</div> : null}
    </section>
  );
}

/** "↻ Next storm: 31 voucher cases settled, ruling cited" footers. */
export function LoopFooter({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p className={cn("flex items-start gap-2 text-[13px] text-slate-500", className)}>
      <span aria-hidden="true" className="font-mono text-slate-400">↻</span>
      <span>{children}</span>
    </p>
  );
}

export function Loading({ label = "Loading", className }: { label?: string; className?: string }) {
  return (
    <div role="status" className={cn("flex items-center gap-2 py-10 text-[13.5px] text-slate-400", className)}>
      <Loader2 className="size-4 animate-spin" aria-hidden="true" />
      {label}…
    </div>
  );
}

/** Skeleton block for first loads. */
export function Shimmer({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-lg bg-cloud-100", className)} aria-hidden="true" />;
}

/** An API error said plainly. Never a stack trace. */
export function ErrorNote({ error, className, onRetry }: { error: unknown; className?: string; onRetry?: () => void }) {
  const message = error instanceof ApiError ? error.message : "Something didn't load.";
  return (
    <div role="alert" className={cn("flex items-start gap-3 rounded-lg bg-cloud-50 px-4 py-3 text-[13.5px] text-slate-600 shadow-[inset_0_0_0_1px_var(--color-cloud-200)]", className)}>
      <AlertCircle className="mt-0.5 size-4 shrink-0 text-slate-400" aria-hidden="true" />
      <div className="min-w-0 flex-1">{message}</div>
      {onRetry ? (
        <button type="button" onClick={onRetry} className="shrink-0 text-[13px] font-medium text-metar-ink hover:underline">
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function Empty({ title, children, className }: { title: ReactNode; children?: ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-xl px-6 py-12 text-center shadow-[inset_0_0_0_1px_var(--color-cloud-200)]", className)}>
      <p className="text-[15px] font-medium text-navy-900">{title}</p>
      {children ? <p className="mx-auto mt-1.5 max-w-[48ch] text-[13.5px] text-slate-500">{children}</p> : null}
    </div>
  );
}

/** Hyphenate's [Edit][Approve] pair. */
export function ActionPair({ onEdit, onApprove, approveLabel = "Approve", editLabel = "Edit", disabled, busy }: { onEdit?: () => void; onApprove?: () => void; approveLabel?: string; editLabel?: string; disabled?: boolean; busy?: boolean }) {
  return (
    <span className="inline-flex overflow-hidden rounded-lg shadow-[inset_0_0_0_1px_var(--color-cloud-300)]">
      <button type="button" onClick={onEdit} disabled={disabled || !onEdit} className="px-3 py-1.5 text-[13px] text-slate-600 transition-colors hover:bg-cloud-50 disabled:opacity-50">
        {editLabel}
      </button>
      <button type="button" onClick={onApprove} disabled={disabled || busy || !onApprove} className="bg-navy-900 px-3 py-1.5 text-[13px] font-semibold text-cloud-50 transition-colors hover:bg-navy-800 disabled:opacity-50">
        {busy ? "…" : approveLabel}
      </button>
    </span>
  );
}

/** Big number with a caption, for headline tiles. */
export function Stat({ label, children, sub, className }: { label: ReactNode; children: ReactNode; sub?: ReactNode; className?: string }) {
  return (
    <div className={cn("min-w-0", className)}>
      <div className="text-[12.5px] text-slate-500">{label}</div>
      <div className="display-tight mt-1 text-[26px] leading-none text-navy-900">{children}</div>
      {sub ? <div className="mt-1.5 text-[12.5px] text-slate-500">{sub}</div> : null}
    </div>
  );
}
