import { useState, type ReactNode } from "react";
import { Check, Copy } from "lucide-react";
import { toast } from "sonner";
import { RoleAvatar } from "@/components/kit";
import { cn } from "@/lib/utils";
import { principalLabel, principalRole } from "./model";

/**
 * Machine text in B612 Mono, with the advance after "." and ":" tightened: B612 sets them at the left of
 * a full cell, so "agent.engine" reads "agent. engine" and "CC6.1" reads "CC6. 1". Copied text is unchanged.
 */
export function Mono({ children, className }: { children: string; className?: string }) {
  const parts = children.split(/([.:])/);
  const out: ReactNode[] = parts.map((p, i) =>
    p === "." || p === ":" ? (
      <span key={i} className="tracking-[-0.28em]">
        {p}
      </span>
    ) : (
      p
    ),
  );
  return <span className={cn("font-mono", className)}>{out}</span>;
}

/** People and agents get their role avatar; anything else (books, parsers, the OCC duty manager) gets a quiet monogram. */
export function PrincipalAvatar({ principal, className }: { principal: string; className?: string }) {
  const role = principalRole(principal);
  const letters = principal.replace(/[^A-Za-z]/g, "").slice(0, 2).toUpperCase() || "··";
  // Decorative: a label always follows, so screen readers hear "Claims Lead", not "CL Claims Lead".
  return (
    <span aria-hidden="true" className="inline-flex shrink-0">
      {role ? (
        <RoleAvatar role={role} size="sm" className={className} />
      ) : (
        <span title={principal} className={cn("inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-transparent font-mono text-[8.5px] font-bold text-slate-500 shadow-[inset_0_0_0_1px_var(--color-cloud-300)]", className)}>
          {letters}
        </span>
      )}
    </span>
  );
}

/** Avatar + the principal as written (mono), with the role's name for people who read it. */
export function Principal({ principal, className, showLabel = false }: { principal: string; className?: string; showLabel?: boolean }) {
  const role = principalRole(principal);
  const name = principal.includes(":") && role && !role.startsWith("agent.") ? principal.split(":").slice(1).join(":") : null;
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-1.5", className)} title={principalLabel(principal)}>
      <PrincipalAvatar principal={principal} />
      <Mono className="min-w-0 truncate text-[11.5px] text-slate-600">{name ? (role ?? principal) : principal}</Mono>
      {showLabel && name ? <span className="truncate text-[12px] text-slate-400">{name}</span> : null}
    </span>
  );
}

/** Copy to the clipboard with a toast; never throws. */
async function copyText(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast(`${what} copied`);
    return true;
  } catch {
    toast.error(`Couldn't copy the ${what.toLowerCase()}.`);
    return false;
  }
}

export function CopyButton({ text, label, what, className }: { text: string; label: string; what: string; className?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        if (await copyText(text, what)) {
          setDone(true);
          window.setTimeout(() => setDone(false), 1800);
        }
      }}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-lg bg-white px-3 text-[13px] font-medium text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-300)] transition-colors hover:bg-cloud-50",
        className,
      )}
    >
      {done ? <Check className="size-3.5" aria-hidden="true" /> : <Copy className="size-3.5 text-slate-500" aria-hidden="true" />}
      {label}
    </button>
  );
}
