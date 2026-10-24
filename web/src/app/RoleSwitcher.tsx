import { Check, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import { invalidateAfterWrite } from "@/api/queries";
import type { Role } from "@/api/types";
import { RoleAvatar } from "@/components/kit";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { ROLE_LABEL } from "@/lib/format";
import { cn } from "@/lib/utils";
import { PEOPLE, ROLE_BLURB, useSession } from "./session";

/** "View as" a seat: POST /api/session, keep the signed token, refetch what that role can see. */
export function RoleSwitcher({ className }: { className?: string }) {
  const { role, switching, signIn } = useSession();

  const choose = async (next: Role) => {
    if (next === role) return;
    try {
      await signIn(next);
      await invalidateAfterWrite();
      toast(`Viewing as ${ROLE_LABEL[next]}`, { description: ROLE_BLURB[next] });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't switch role.");
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className={cn(
          "inline-flex h-9 items-center gap-2 rounded-full bg-white py-1 pl-1 pr-3 text-[13.5px] text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-200)] transition-colors hover:bg-cloud-50 disabled:opacity-60",
          className,
        )}
        disabled={switching}
        aria-label={`Viewing as ${ROLE_LABEL[role]}. Change role`}
        data-testid="role-switcher"
      >
        <RoleAvatar role={role} />
        <span className="hidden sm:inline">
          <span className="text-slate-400">View as</span> {ROLE_LABEL[role]}
        </span>
        <ChevronDown className="size-3.5 text-slate-400" aria-hidden="true" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[300px] p-1.5">
        <DropdownMenuLabel className="micro px-2 pb-1 pt-1.5 text-slate-400">View as</DropdownMenuLabel>
        {PEOPLE.map((r) => (
          <DropdownMenuItem key={r} onSelect={() => void choose(r)} className="items-start gap-3 rounded-lg px-2 py-2" data-testid={`role-${r}`}>
            <RoleAvatar role={r} />
            <span className="min-w-0 flex-1">
              <span className="block text-[13.5px] font-medium text-navy-900">{ROLE_LABEL[r]}</span>
              <span className="block text-[12px] leading-snug text-slate-500">{ROLE_BLURB[r]}</span>
            </span>
            {r === role ? <Check className="mt-1 size-4 text-navy-900" aria-hidden="true" /> : null}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <p className="px-2 py-1.5 text-[11.5px] leading-snug text-slate-400">Each seat sees only what it may. Agents are principals too, with their own limits.</p>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
