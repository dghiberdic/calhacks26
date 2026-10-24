// App fixtures: questions, rules, ledger, passengers. Mirrors the engine's shapes so the
// API adapter can swap them out without touching components.
import { FLIGHTS, NS31, tier } from "./scenario";

export type Role = "claims-lead" | "legal" | "controller" | "ops";
export const ROLES: { id: Role; name: string; initials: string; sees: string }[] = [
  { id: "claims-lead", name: "Claims Lead", initials: "CL", sees: "Passengers, payouts and voucher questions" },
  { id: "legal", name: "Legal", initials: "LG", sees: "New legal patterns and the rules they create" },
  { id: "controller", name: "Controller", initials: "CT", sees: "The provision, journal entries and releases" },
  { id: "ops", name: "Ops", initials: "OP", sees: "Flights and causes. No passenger data (GDPR)" },
];

export type Evidence = { source: string; when?: string; text: string; mono?: boolean };
export type Answer = { id: string; label: string; effect: string; delta?: number; rule?: RuleDraft };
export type RuleDraft = { id: string; version: number; sentence: string; highlight: string; scope: string; replay: string };

export type Question = {
  id: string;
  title: string;
  owner: Role;
  why: string;
  flight: string;
  subject: string;
  held: number;
  confidence: number | null;
  reason: "sources disagree" | "no precedent" | "needs approval";
  question: string;
  evidence: Evidence[];
  answers: Answer[];
};

export const QUESTIONS: Question[] = [
  {
    id: "Q-12",
    title: "Offset a gate voucher?",
    owner: "claims-lead",
    why: "Voucher disputes on EU-departing flights are yours.",
    flight: "NS31",
    subject: "Aoife Byrne",
    held: 600,
    confidence: 39,
    reason: "sources disagree",
    question: "The CRM says Aoife Byrne took a €300 voucher at the gate. Her claim says she never agreed. Offset the voucher against her €600?",
    evidence: [
      { source: "CRM, gate agent K. Walsh", when: "9 Dec 20:52Z", text: "VOUCHER €300 ISSUED · GATE B4 · NS31", mono: true },
      { source: "Claim email", when: "11 Dec 08:03Z", text: "“I never agreed to a voucher. I was handed a printout and told the flight was gone.”" },
      { source: "Signed acceptance", text: "None on file. Six earlier vouchers this year had one." },
    ],
    answers: [
      {
        id: "no-offset",
        label: "No signed acceptance, no offset.",
        effect: "Pay her the full €600.",
        delta: 0,
        rule: {
          id: "R-7",
          version: 1,
          sentence: "A gate voucher is offset against EU261 compensation only with a signed acceptance.",
          highlight: "only with a signed acceptance",
          scope: "Flights departing the EU",
          replay: "Changes 0 past decisions. Applies to 31 open cases.",
        },
      },
      { id: "offset", label: "Offset the voucher.", effect: "Pay €300.", delta: -300 },
      { id: "custom", label: "Something else.", effect: "Write the ruling in your own words." },
    ],
  },
  {
    id: "Q-13",
    title: "Crew out of hours after yesterday’s storm",
    owner: "legal",
    why: "A cause StormCheck has never seen goes to Legal once.",
    flight: "NS19",
    subject: "NS19 to Chicago, 10 Dec 07:10Z",
    held: 26400,
    confidence: 22,
    reason: "no precedent",
    question: "NS19 left a day late because its crew timed out flying the storm recovery. Is a crew time-out caused by yesterday’s storm extraordinary?",
    evidence: [
      { source: "Crew roster", when: "10 Dec 05:40Z", text: "CAPT/FO FDP EXCEEDED · RECOVERY SECTOR NS22 JFK-DUB", mono: true },
      { source: "Ops log", when: "10 Dec 06:02Z", text: "NO STANDBY CREW AVAILABLE DUB", mono: true },
      { source: "METAR", when: "10 Dec 06:00Z", text: "EIDW 100600Z 23015G30KT 210V270 9999 FEW014 09/05 Q1000 NOSIG", mono: true },
    ],
    answers: [
      { id: "not-extra", label: "Not extraordinary.", effect: "Crew planning is the airline’s risk. Pay 176 × €600.", delta: 0, rule: { id: "R-9", version: 1, sentence: "A crew time-out on a later day is not extraordinary, even when the storm caused it.", highlight: "not extraordinary", scope: "All routes", replay: "Changes 2 past decisions." } },
      { id: "extra", label: "Extraordinary.", effect: "Nothing owed for NS19.", delta: -26400 },
      { id: "custom", label: "Something else.", effect: "Write the ruling in your own words." },
    ],
  },
  {
    id: "Q-14",
    title: "Release the October provision?",
    owner: "controller",
    why: "Provision releases need the Controller’s approval.",
    flight: "Oct storms",
    subject: "EU261 claims provision, October",
    held: 18300,
    confidence: null,
    reason: "needs approval",
    question: "October’s storm provision is 12 months old with €18,300 unclaimed. Release it to income?",
    evidence: [
      { source: "Claim curve", text: "Claims filed: 31% of owed passengers after 12 months. Curve expects 35% by month 24." },
      { source: "Policy", text: "Provisions are released when further claims are no longer probable (IAS 37)." },
    ],
    answers: [
      { id: "hold", label: "Hold it. Claims can arrive for years.", effect: "Keep €18,300 provided.", delta: 0, rule: { id: "R-10", version: 1, sentence: "Release an EU261 provision only when the claim curve is flat for 6 months, never before 24 months.", highlight: "never before 24 months", scope: "All routes", replay: "Affects 3 open provisions." } },
      { id: "release", label: "Release it.", effect: "Credit €18,300 to income.", delta: -18300 },
    ],
  },
];

export type Rule = {
  id: string;
  version: number;
  title: string;
  sentence: string;
  source: "law" | "ruling" | "policy" | "learned";
  sourceLabel: string;
  scope: string;
  applied: number;
  asked: number;
  updated: string;
  history?: { version: number; when: string; change: string; by: string }[];
};

export const RULES: Rule[] = [
  { id: "R-1", version: 2, title: "Storm window", sentence: "A storm window is every hour the airport’s METAR shows gusts at or above 45 kt or crosswind above 35 kt.", source: "policy", sourceLabel: "Ops weather policy", scope: "All airports", applied: 2910, asked: 0, updated: "3 Dec 2024", history: [{ version: 1, when: "2 Mar 2024", change: "Gust limit 50 kt", by: "Ops" }, { version: 2, when: "3 Dec 2024", change: "Gust limit 45 kt; crosswind added", by: "Ops" }] },
  { id: "R-2", version: 1, title: "Trust order", sentence: "Tech log and METAR outrank the ops cause code, which outranks the gate note, which outranks the passenger’s account.", source: "policy", sourceLabel: "Claims policy", scope: "All evidence", applied: 2910, asked: 0, updated: "12 Mar 2024" },
  { id: "R-3", version: 2, title: "Technical faults", sentence: "A technical fault is not an extraordinary circumstance unless it comes from outside the airline’s control.", source: "law", sourceLabel: "CJEU C-549/07 Wallentin-Hermann · Legal", scope: "All routes", applied: 14, asked: 1, updated: "12 Mar 2026", history: [{ version: 1, when: "12 Mar 2024", change: "From the judgment", by: "Legal" }, { version: 2, when: "12 Mar 2026", change: "Bird strike and manufacturer recalls excluded", by: "Legal" }] },
  { id: "R-4", version: 1, title: "Compensation tiers", sentence: "€250 up to 1,500 km, €400 up to 3,500 km, €600 beyond.", source: "law", sourceLabel: "Reg. 261/2004 Art. 7(1)", scope: "EU-departing flights", applied: 2910, asked: 0, updated: "1 Jan 2024" },
  { id: "R-5", version: 1, title: "Rebooked within 4 hours", sentence: "Halve compensation when the passenger arrives within 4 hours of schedule on a long-haul reroute.", source: "law", sourceLabel: "Reg. 261/2004 Art. 7(2)", scope: "Flights over 3,500 km", applied: 61, asked: 0, updated: "1 Jan 2024" },
  { id: "R-6", version: 4, title: "Claim rate", sentence: "Provide for 35% of owed passengers on transatlantic routes, trued up monthly against the claim curve.", source: "learned", sourceLabel: "Learned from 2 years of claims", scope: "Transatlantic", applied: 18, asked: 0, updated: "1 Oct 2026" },
  { id: "R-8", version: 1, title: "Care costs", sentence: "Accrue hotel and meals at €140 per stranded passenger, trued up when the invoices land.", source: "learned", sourceLabel: "Learned from 18 storms", scope: "Stranded passengers", applied: 412, asked: 0, updated: "9 Feb 2026" },
];

export type JournalLine = { account: string; dr?: number; cr?: number };
export type Journal = { id: string; when: string; memo: string; status: "drafted" | "posted" | "held"; source: string; lines: JournalLine[] };

export const JOURNAL: Journal[] = [
  { id: "JE-2041", when: "10 Dec 09:00Z", memo: "NS31 recoded weather → technical. EU261 exposure at learned claim rate.", status: "held", source: "R-3 v2 · R-6 v4", lines: [{ account: "6410 Passenger compensation", dr: NS31.provision }, { account: "2350 EU261 claims provision", cr: NS31.provision }] },
  { id: "JE-2040", when: "10 Dec 09:00Z", memo: "Refunds for 13 weather cancellations (never revenue).", status: "drafted", source: "R-1 v2 · Art. 8", lines: [{ account: "2400 Air traffic liability", dr: 1_421_380 }, { account: "2410 Refunds payable", cr: 1_421_380 }] },
  { id: "JE-2039", when: "10 Dec 09:00Z", memo: "Vouchers accepted instead of cash, with expected breakage.", status: "drafted", source: "R-7 v1", lines: [{ account: "2400 Air traffic liability", dr: 41_700 }, { account: "2420 Voucher liability", cr: 41_700 }] },
  { id: "JE-2038", when: "10 Dec 09:00Z", memo: "Hotels and meals for stranded passengers, accrued.", status: "drafted", source: "R-8 v1", lines: [{ account: "6420 Passenger care", dr: 57_680 }, { account: "2360 Accrued care costs", cr: 57_680 }] },
];

/** Deterministic pseudo-passengers for the payouts table. */
const FIRST = ["Aoife", "Conor", "Siobhán", "Liam", "Niamh", "Cian", "Saoirse", "Darragh", "Ciara", "Oisín", "Emma", "Jack", "Grace", "Noah", "Ava", "James", "Sophie", "Daniel", "Maya", "Ethan", "Chloe", "Lucas", "Isla", "Ruairí"];
const LAST = ["Byrne", "Murphy", "Kelly", "O’Brien", "Walsh", "Ryan", "O’Sullivan", "Doyle", "McCarthy", "Gallagher", "Kennedy", "Lynch", "Murray", "Quinn", "Moore", "Carroll", "Chen", "Silva", "Novak", "Okafor", "Rossi", "Schmidt", "Dubois", "Kowalski"];

export type Payout = { id: string; name: string; flight: string; amount: number; status: "drafted" | "held" | "not owed" | "asked"; rule: string };

export function payouts(): Payout[] {
  const out: Payout[] = [];
  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  for (const f of FLIGHTS) {
    for (let i = 0; i < f.pax; i++) {
      const name = `${FIRST[Math.floor(rnd() * FIRST.length)]} ${LAST[Math.floor(rnd() * LAST.length)]}`;
      const tech = f.verdict === "technical";
      out.push({
        id: `${f.id}-${String(i + 1).padStart(3, "0")}`,
        name: f.id === "NS31" && i === 41 ? "Aoife Byrne" : name,
        flight: f.id,
        amount: tech ? tier(f.km) : 0,
        status: f.id === "NS31" && i === 41 ? "asked" : tech ? "held" : "not owed",
        rule: tech ? "R-3 v2" : "R-1 v2",
      });
    }
  }
  return out;
}
