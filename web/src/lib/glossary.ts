/**
 * Plain-English meanings for the words an airline accountant uses and a visitor doesn't, in one place.
 * `<Explain term="metar">` (components/explain.tsx) shows them on hover, focus or tap.
 *
 * Wording follows plan §9: "EU261 compensation liability", "drafted, pending approval", "reduction of
 * passenger revenue". No figures from the demo world: those come from the API.
 */
export type GlossaryEntry = { term: string; plain: string };

export const GLOSSARY = {
  eu261: {
    term: "EU261",
    plain: "The EU rule on cancelled flights. Each passenger is owed €250, €400 or €600 in cash, depending on distance, unless the cause was extraordinary. Refunds or rebooking, and care, are owed either way.",
  },
  extraordinary: {
    term: "Extraordinary circumstance",
    plain: "A cause the airline couldn't control, such as a storm or a national power cut. It removes the cash compensation, not refunds, rerouting or care. A broken plane isn't extraordinary: keeping planes fit to fly is the airline's job.",
  },
  metar: {
    term: "METAR",
    plain: "The official airport weather report, issued every hour or half hour: wind, gusts, visibility. StormCheck reads the real reports for the day.",
  },
  "storm-window": {
    term: "Storm window",
    plain: "The hours the airport's weather reports show storm conditions (gusts of 35 kt or more, snow, ice, thunder). Worked out from the reports, never typed in. A flight is only 'weather' if it was due to leave or land inside it.",
  },
  "grid-outage": {
    term: "Grid outage window",
    plain: "The hours an airport had no mains power, taken from the grid operator's and the airport's own notices rather than from the weather. A flight due to leave or land inside it was stopped by the outage; one cancelled after power came back is judged on its own logs.",
  },
  "tech-log": {
    term: "Tech log",
    plain: "The aircraft's maintenance record. Engineers write down each fault and each fix, with the time.",
  },
  aog: {
    term: "AOG",
    plain: "Aircraft on ground: the plane can't fly until it's repaired.",
  },
  "no-mel-relief": {
    term: "No MEL relief",
    plain: "The Minimum Equipment List says which faults a plane may still fly with for a few days. 'No MEL relief' means this fault isn't on it: the plane wasn't allowed to fly.",
  },
  "delay-codes": {
    term: "Delay codes",
    plain: "IATA reason codes on a cancellation. 71 is weather at the departure airport, 72 weather at the destination, 41 a defect on the aircraft. Recoding 71 → 41 means the real cause was the plane, not the storm.",
  },
  "knock-on": {
    term: "Knock-on (return) flight",
    plain: "The return leg of a flight the storm cancelled. The plane never got out, so it couldn't fly back, even though both airports were calm by then. Whether that counts as extraordinary is a question of law (CJEU C-74/19), so Legal decides.",
  },
  "voucher-in-lieu": {
    term: "Voucher in lieu",
    plain: "A voucher offered instead of the cash compensation. It only replaces the cash if the passenger signed to accept it (Art. 7(3)). Without a signature, the cash is still owed.",
  },
  "cash-basis": {
    term: "Cash basis",
    plain: "Book nothing until claims are paid: €0 on the day. It understates what the airline owes.",
  },
  "full-entitlement": {
    term: "Full entitlement",
    plain: "The full Art. 7 entitlement if every passenger claims. It overstates what the airline owes: many passengers never claim.",
  },
  "drafted-liability": {
    term: "Drafted liability",
    plain: "What StormCheck books: the full entitlement × the expected claim rate. Drafted, pending approval: a person approves the entry before it posts.",
  },
  "claim-rate": {
    term: "Claim rate",
    plain: "The share of owed passengers expected to claim in the end: the expected ultimate claim rate, learned from the airline's own claims history (to month 18, plus a judgment for the tail).",
  },
  "liability-2140": {
    term: "EU261 compensation liability (2140)",
    plain: "The balance-sheet account for compensation the airline expects to pay. It goes up when a storm is booked, and down as claims are paid or the estimate changes.",
  },
  "dr-cr": {
    term: "Dr / Cr",
    plain: "Debit and credit, the two equal sides of every journal entry. Dr 4090 / Cr 2140 means passenger revenue goes down and the EU261 compensation liability goes up by the same amount.",
  },
  ifrs15: {
    term: "IFRS 15 variable consideration",
    plain: "The accounting rule that treats expected compensation as a reduction of passenger revenue, estimated on the day and updated as claims arrive, rather than an expense when it's paid.",
  },
  "held-for-legal": {
    term: "Held for Legal",
    plain: "Flights waiting on a ruling. They're still accrued at the expected claim rate, so the books aren't understated while Legal decides (the IFRS 15.56 constraint).",
  },
  "change-in-estimate": {
    term: "Change in estimate",
    plain: "An update to the liability when new information arrives, such as claims running ahead of the curve. Booked in the open month (IAS 8.36); closed months aren't touched.",
  },
  "bornhuetter-ferguson": {
    term: "Bornhuetter-Ferguson",
    plain: "How StormCheck re-estimates at month-end when claims come in faster or slower than the curve expected: it keeps the expected claims still to come, (ultimate claim rate − rate expected by now) × entitlement, rather than chasing early claims up or down.",
  },
  "prior-period-error": {
    term: "Prior-period error",
    plain: "A mistake in a month that's already closed. If it's immaterial it's corrected in the open month (IAS 8), and the closed month stays as it was. Not the same as a change in estimate, which is new information, not a mistake.",
  },
  "period-lock": {
    term: "Period lock",
    plain: "Once a month is closed it's locked: nothing, StormCheck included, can post into it. Corrections go in the open month.",
  },
  atl: {
    term: "Air traffic liability (2100)",
    plain: "Ticket money for flights not yet flown. It becomes revenue when the passenger flies, or goes back to them as a refund.",
  },
  care: {
    term: "Care (hotels, meals)",
    plain: "Meals, hotels and transport for stranded passengers (Art. 9). Owed even when the cause was extraordinary (CJEU C-12/11 McDonagh), so it's booked either way.",
  },
  "ties-to-gl": {
    term: "Ties to GL",
    plain: "The cohort-by-cohort balances add up to exactly what the general ledger account holds.",
  },
  confidence: {
    term: "Confidence",
    plain: "How sure the engine is about the cause, from how well the sources agree. It decides on its own only at 90% or more, and under €50,000; anything else goes to a person.",
  },
  "sources-disagree": {
    term: "Sources disagree",
    plain: "Two records say different things, for example the CRM says a voucher was accepted and the passenger's claim says it wasn't. The engine won't pick one, so it asks.",
  },
  "no-precedent": {
    term: "No precedent",
    plain: "No earlier ruling or rule covers this pattern. A person decides it once, and the answer becomes policy.",
  },
  "rule-scope": {
    term: "Rule scope",
    plain: "Which cases a rule covers, written as conditions (for example: voucher unsigned and the flight leaves the EU). A case outside the scope is asked again.",
  },
  "rule-precedence": {
    term: "Rule precedence",
    plain: "When rules disagree, the stronger source wins: hard controls, then regulation, then Legal, the Controller, the Claims Lead, and last what was learned from history.",
  },
  blame: {
    term: "Blame",
    plain: "Walks a number back to where it came from: the amount, the entitlement, the rule and version, the ruling's words, the facts, the log line and the weather report.",
  },
  trace: {
    term: "Hash-chained trace",
    plain: "Every step StormCheck takes is written to an append-only log, each entry carrying the hash of the one before. Change anything in the past and the chain no longer checks out.",
  },
  "judges-desk": {
    term: "Judge's Desk",
    plain: "Pick any airport and date: StormCheck fetches the real weather reports for it, simulates the airline's flights on that weather and runs the same engine.",
  },
  "loaded-cost": {
    term: "Loaded cost",
    plain: "What an hour of a person's time costs the airline: salary plus about 30% on top for employer taxes, pension and a desk, over 1,700 working hours a year. Rates from Irish salary surveys.",
  },
  "preparer-approver": {
    term: "Preparer ≠ approver",
    plain: "Segregation of duties: whoever drafts an entry can never approve it, person or agent. Enforced in code, not by habit.",
  },
} as const satisfies Record<string, GlossaryEntry>;

export type Term = keyof typeof GLOSSARY;
