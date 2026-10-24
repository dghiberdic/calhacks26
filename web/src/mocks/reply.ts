// Shared request/reply shapes for the mock router and its actions.
import type { Role, Session } from "@/api/types";

export type Reply = { status: number; body: unknown };
export type Req = { method: string; segs: string[]; query: URLSearchParams; body: unknown; session: Session; role: Role };

export const ok = (body: unknown, status = 200): Reply => ({ status, body });
export const fail = (status: number, code: string, message: string): Reply => ({ status, body: { error: { code, message } } });

export const PEOPLE: Role[] = ["claims_lead", "legal", "controller", "ops", "cfo", "judge"];
export const ROLES: Role[] = [...PEOPLE, "agent.reader", "agent.drafter", "agent.engine", "agent.crm_bot"];
export const ROLE_NAME: Record<Role, string> = {
  claims_lead: "Claims Lead",
  legal: "Legal",
  controller: "Controller",
  ops: "Ops",
  cfo: "CFO",
  judge: "Judge",
  "agent.reader": "Reader agent",
  "agent.drafter": "Drafter agent",
  "agent.engine": "Engine",
  "agent.crm_bot": "CRM bot",
};

/** Narrow an unknown JSON body to a record (arrays and primitives count as empty). */
export const bodyOf = (req: Req): Record<string, unknown> => (req.body && typeof req.body === "object" && !Array.isArray(req.body) ? (req.body as Record<string, unknown>) : {});
export const str = (v: unknown) => (typeof v === "string" ? v.trim() : "");
