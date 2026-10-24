import type { ReactNode } from "react";
import { ToggleGroup as ToggleGroupPrimitive } from "radix-ui";
import { ApiError } from "@/api/client";
import { cn } from "@/lib/utils";

/**
 * A segmented control in the shell's skin (white pill, hairline, ink selection). Local to J6/J8 until a
 * shared one exists in components/ (requested).
 */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  label,
  className,
  size = "md",
}: {
  value: T;
  onChange: (next: T) => void;
  options: { value: T; label: ReactNode; title?: string; badge?: ReactNode }[];
  label: string;
  className?: string;
  size?: "sm" | "md";
}) {
  return (
    <ToggleGroupPrimitive.Root
      type="single"
      value={value}
      onValueChange={(v) => v && onChange(v as T)}
      aria-label={label}
      className={cn("inline-flex max-w-full items-center gap-0.5 overflow-x-auto rounded-full bg-white p-0.5 shadow-[inset_0_0_0_1px_var(--color-cloud-200)]", className)}
    >
      {options.map((o) => (
        <ToggleGroupPrimitive.Item
          key={o.value}
          value={o.value}
          title={o.title}
          className={cn(
            "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full font-medium text-slate-500 transition-colors outline-none hover:text-navy-900 focus-visible:ring-2 focus-visible:ring-ring/50 data-[state=on]:bg-navy-900 data-[state=on]:text-cloud-50",
            size === "sm" ? "h-7 px-3 text-[12.5px]" : "h-8 px-3.5 text-[13px]",
          )}
        >
          {o.label}
          {o.badge}
        </ToggleGroupPrimitive.Item>
      ))}
    </ToggleGroupPrimitive.Root>
  );
}

/** Nil in an accounts table: an en dash, quiet. */
export function Nil() {
  return (
    <span className="text-cloud-400">
      <span aria-hidden="true">–</span>
      <span className="sr-only">nil</span>
    </span>
  );
}

/**
 * A refused write, said in place: `DENIED · SoD` for a segregation-of-duties 403, `DENIED` for any other
 * refusal, then the server's own plain message. Denials are ink, never red.
 */
export function Denied({ error, className }: { error: unknown; className?: string }) {
  const api = error instanceof ApiError ? error : null;
  const tag = api?.code === "sod_violation" ? "DENIED · SoD" : api && (api.status === 403 || api.code === "forbidden") ? "DENIED" : null;
  const message = api?.message ?? "That didn't go through. Nothing was changed.";
  return (
    <span role="status" className={cn("flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1", className)}>
      {tag ? (
        <span className="inline-flex h-6 shrink-0 items-center rounded-md bg-navy-900 px-2 font-mono text-[11px] font-bold tracking-[0.04em] text-cloud-50" data-testid="denied">
          {tag}
        </span>
      ) : null}
      <span className="min-w-0 text-[12.5px] leading-snug text-slate-600">{message}</span>
    </span>
  );
}

/** Heading inside a panel: micro-label eyebrow, title, one line of context, actions on the right. */
export function SectionHead({ eyebrow, title, children, actions, className, id }: { eyebrow?: ReactNode; title: ReactNode; children?: ReactNode; actions?: ReactNode; className?: string; id?: string }) {
  return (
    <div className={cn("flex flex-wrap items-start justify-between gap-x-4 gap-y-2", className)}>
      <div className="min-w-0">
        {eyebrow ? <div className="mb-1">{eyebrow}</div> : null}
        <h2 id={id} className="text-[15.5px] font-semibold leading-snug text-navy-900">
          {title}
        </h2>
        {children ? <div className="mt-0.5 text-[13px] leading-relaxed text-slate-500">{children}</div> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}
