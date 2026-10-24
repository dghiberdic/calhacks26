import { create } from "zustand";
import { api, setToken } from "@/api/client";
import type { Role } from "@/api/types";
import { ROLE_LABEL } from "@/lib/format";

/** The six seats a person can take in the demo (agents are principals too, but nobody logs in as one). */
export const PEOPLE: Role[] = ["claims_lead", "legal", "controller", "ops", "cfo", "judge"];

export const ROLE_BLURB: Record<string, string> = {
  claims_lead: "Approves payouts; rules on vouchers and claims",
  legal: "Rules on new legal patterns",
  controller: "Approves journals, closes periods",
  ops: "Flights and causes; no passenger data",
  cfo: "Liability and close, read-only",
  judge: "Read-only, plus the desk and injections",
};

type SessionState = {
  role: Role;
  name: string;
  token: string | null;
  switching: boolean;
  error: string | null;
  /** POST /api/session and keep the signed token for every later request. */
  signIn: (role: Role) => Promise<void>;
  restore: () => Promise<void>;
};

const KEY = "stormcheck.session";

export const useSession = create<SessionState>((set, get) => ({
  role: "judge",
  name: ROLE_LABEL.judge,
  token: null,
  switching: false,
  error: null,
  async signIn(role) {
    set({ switching: true, error: null });
    try {
      const name = ROLE_LABEL[role];
      const res = await api.session(role, name);
      setToken(res.token, role);
      set({ role, name, token: res.token, switching: false });
      try {
        sessionStorage.setItem(KEY, JSON.stringify({ role, name, token: res.token }));
      } catch {
        /* per-tab convenience only */
      }
    } catch (e) {
      set({ switching: false, error: e instanceof Error ? e.message : "Couldn't switch role." });
      throw e;
    }
  },
  async restore() {
    try {
      const raw = sessionStorage.getItem(KEY);
      if (!raw) return;
      const saved = JSON.parse(raw) as { role: Role; name: string; token: string };
      setToken(saved.token, saved.role);
      set({ role: saved.role, name: saved.name, token: saved.token });
    } catch {
      /* start as the judge */
    }
    void get;
  },
}));
