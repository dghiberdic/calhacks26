import { useState } from "react";
import { toast } from "sonner";
import { invalidateAfterWrite } from "@/api/queries";
import type { Role } from "@/api/types";
import { ROLE_BLURB, useSession } from "@/app/session";
import { ROLE_LABEL } from "@/lib/format";

/** Take another seat (POST /api/session) and refetch what it may see: the RoleSwitcher's action, callable from a card. */
export function useViewAs() {
  const signIn = useSession((s) => s.signIn);
  const [busy, setBusy] = useState<Role | null>(null);
  const viewAs = async (role: Role) => {
    setBusy(role);
    try {
      await signIn(role);
      await invalidateAfterWrite();
      toast(`Viewing as ${ROLE_LABEL[role]}`, { description: ROLE_BLURB[role] });
      return true;
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't switch role.");
      return false;
    } finally {
      setBusy(null);
    }
  };
  return { viewAs, busy };
}
