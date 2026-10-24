import type { Cents, Role } from "@/api/types";
import { Money, RoleAvatar } from "@/components/kit";
import { cn } from "@/lib/utils";
import { routedPhrase } from "./lib";

/** "Routed to the Claims Lead · Holds €600" with the seat's initials. Same look as the kit's RoutedTo, with "Routed to Legal". */
export function RoutedLine({ role, holdsCents, className }: { role: Role; holdsCents?: Cents | null; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 text-[13px] text-slate-600", className)}>
      <RoleAvatar role={role} size="sm" />
      <span>{routedPhrase(role)}</span>
      {holdsCents ? (
        <span className="text-held-ink">
          · Holds <Money cents={holdsCents} />
        </span>
      ) : null}
    </span>
  );
}
