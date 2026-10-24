// A deterministic stand-in for the cause engine, used by the Judge's desk until the real
// engine's API is wired. Same contract: facts in, verdict + reasons + confidence out.
// The LLM never decides; this function does.

export type Window = { start: string; end: string };
export type FaultKind = "technical" | "bird" | "crew" | "none";
export type DeskVerdict = "technical" | "weather" | "extraordinary" | "review";

export type DeskResult = {
  verdict: DeskVerdict;
  owed: boolean;
  confidence: number;
  reasons: string[];
  rule: string;
  routeTo?: "Legal" | "Claims Lead";
};

export const toMin = (t: string) => {
  const m = t.match(/(\d{1,2}):?(\d{2})/);
  return m ? Number(m[1]) * 60 + Number(m[2]) : NaN;
};
export const fmtMin = (m: number) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(Math.round(m % 60)).padStart(2, "0")}`;

export function classifyLog(text: string): { kind: FaultKind; time: string | null } {
  const time = text.match(/\b([01]\d|2[0-3]):?([0-5]\d)Z?\b/);
  const t = time ? `${time[1]}:${time[2]}` : null;
  if (!text.trim()) return { kind: "none", time: null };
  if (/BIRD/i.test(text)) return { kind: "bird", time: t };
  if (/CREW|FDP|DUTY|OUT OF HOURS|TIMED? OUT/i.test(text)) return { kind: "crew", time: t };
  if (/HYD|LEAK|ENG|EDP|U\/S|INOP|FAULT|ATA|BRAKE|GEAR|AVIONIC|CRACK|APU|PACK|BLEED|FUEL/i.test(text)) return { kind: "technical", time: t };
  return { kind: "none", time: t };
}

export function decide(args: { windows: Window[]; sched: string; log: string }): DeskResult {
  const { windows, sched, log } = args;
  const s = toMin(sched);
  const inWin = windows.find((w) => s >= toMin(w.start) - 30 && s <= toMin(w.end) + 30);
  const firstStart = windows.length ? Math.min(...windows.map((w) => toMin(w.start))) : Infinity;
  const lastEnd = windows.length ? Math.max(...windows.map((w) => toMin(w.end))) : -Infinity;
  const { kind, time } = classifyLog(log);
  const f = time ? toMin(time) : NaN;

  if (kind === "bird")
    return {
      verdict: "extraordinary",
      owed: false,
      confidence: 84,
      reasons: ["A bird strike is outside the airline’s control (CJEU C-315/15, Pešková).", "Care costs still apply under Art. 9."],
      rule: "R-11 v1",
    };

  if (kind === "crew")
    return {
      verdict: "review",
      owed: false,
      confidence: 22,
      reasons: ["A crew time-out is a new pattern for this storm. No precedent in the rules.", "Routed to Legal once; the answer becomes a rule."],
      rule: "—",
      routeTo: "Legal",
    };

  if (kind === "technical") {
    const before = Number.isFinite(f) && f < firstStart;
    const margin = Number.isFinite(f) && Number.isFinite(firstStart) ? (firstStart - f) / 60 : 0;
    if (inWin && !before)
      return {
        verdict: "review",
        owed: false,
        confidence: 46,
        reasons: [`Fault logged at ${time}Z, inside the storm window.`, "Weather and the fault both explain the cancellation. Sources disagree."],
        rule: "R-2 v1",
        routeTo: "Claims Lead",
      };
    const conf = Math.min(97, Math.round(70 + Math.min(18, margin * 6) + (inWin ? -12 : 9)));
    return {
      verdict: "technical",
      owed: true,
      confidence: conf,
      reasons: [
        time ? `Fault logged at ${time}Z${Number.isFinite(firstStart) ? `, ${margin >= 0 ? fmtMin(margin * 60) + " before" : "after"} the storm window opened` : ""}.` : "Technical fault in the log.",
        inWin ? "Departure falls inside the storm window, so confidence drops." : `Departure at ${sched}Z is outside every storm window.`,
        "Technical faults are not extraordinary (CJEU C-549/07).",
      ],
      rule: "R-3 v2",
    };
  }

  if (inWin)
    return {
      verdict: "weather",
      owed: false,
      confidence: 93,
      reasons: [`Departure at ${sched}Z falls inside the storm window ${inWin.start}–${inWin.end}Z.`, "No open tech-log items. Nothing owed under Art. 7."],
      rule: "R-1 v2",
    };

  return {
    verdict: windows.length && s > lastEnd ? "review" : "technical",
    owed: !(windows.length && s > lastEnd),
    confidence: windows.length && s > lastEnd ? 55 : 72,
    reasons: windows.length
      ? [`Departure at ${sched}Z is after the storm window closed at ${fmtMin(lastEnd)}Z.`, "No logged cause. Asking the Claims Lead what happened."]
      : ["No storm window in that day’s METAR.", "Weather can’t explain the cancellation, so compensation is owed."],
    rule: windows.length ? "R-2 v1" : "R-1 v2",
    routeTo: windows.length && s > lastEnd ? "Claims Lead" : undefined,
  };
}
