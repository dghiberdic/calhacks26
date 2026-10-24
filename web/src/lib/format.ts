import type { Cents, Role } from "@/api/types";

const eurFormatter = new Intl.NumberFormat("en-IE", { maximumFractionDigits: 0 });
const eurFormatterCents = new Intl.NumberFormat("en-IE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** Integer euro cents → "€34,650". Negatives in parentheses, as accountants write them: "(€3,600)". */
export function eur(cents: Cents | null | undefined, opts: { cents?: boolean; signed?: boolean } = {}): string {
  if (cents === null || cents === undefined || Number.isNaN(cents)) return "—";
  const value = cents / 100;
  const abs = Math.abs(value);
  const body = `€${opts.cents ? eurFormatterCents.format(abs) : eurFormatter.format(Math.round(abs))}`;
  if (value < 0) return `(${body})`;
  if (opts.signed && value > 0) return `+${body}`;
  return body;
}

/** 5292 → "5,292". */
export const count = (n: number | null | undefined) => (n === null || n === undefined ? "—" : eurFormatter.format(n));

/** 0.91 → "91%". */
export const pct = (x: number | null | undefined, digits = 0) => (x === null || x === undefined ? "—" : `${(x * 100).toFixed(digits)}%`);

const pad = (n: number) => String(n).padStart(2, "0");
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** ISO → "21:40Z". */
export function zulu(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}Z`;
}

/** ISO → "23 Jan 21:40Z". */
export function zuluDay(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${zulu(iso)}`;
}

/** "2025-01-24" → "24 Jan 2025". */
export function longDate(isoDate: string | null | undefined): string {
  if (!isoDate) return "—";
  const [y, m, d] = isoDate.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return isoDate;
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/** Period "2025-02" → "Feb 2025". */
export function periodLabel(period: string): string {
  const [y, m] = period.split("-").map(Number);
  return y && m ? `${MONTHS[m - 1]} ${y}` : period;
}

/** "NS31@2025-01-24" → "NS31"; "NS31@2025-01-24:14C" → "NS31 · 14C". */
export function shortId(id: string | null | undefined): string {
  if (!id) return "—";
  const [head, coupon] = id.split(":");
  const flight = head.split("@")[0];
  return coupon && /^\d/.test(coupon) ? `${flight} · ${coupon}` : flight;
}

/** "2025-01-24" part of an ID like "NS31@2025-01-24". */
export const idDate = (id: string) => id.split("@")[1]?.slice(0, 10) ?? "";

export const ROLE_LABEL: Record<Role, string> = {
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

export const ROLE_INITIALS: Record<Role, string> = {
  claims_lead: "CL",
  legal: "LG",
  controller: "CT",
  ops: "OP",
  cfo: "CF",
  judge: "JD",
  "agent.reader": "RD",
  "agent.drafter": "DR",
  "agent.engine": "EN",
  "agent.crm_bot": "CB",
};

/** "Routed to the Claims Lead" — people get "the". */
/** "Routed to the Claims Lead", "Routed to Legal" (plan §2: departments and agents take no article). */
export const routedTo = (role: Role) => `Routed to ${role.startsWith("agent.") || role === "legal" || role === "ops" ? "" : "the "}${ROLE_LABEL[role]}`;

/** Minutes → "1 h 30 min". */
export function duration(min: number | null | undefined): string {
  if (min === null || min === undefined) return "—";
  const h = Math.floor(Math.abs(min) / 60);
  const m = Math.abs(min) % 60;
  return [h ? `${h} h` : "", m ? `${m} min` : h ? "" : "0 min"].filter(Boolean).join(" ");
}
