import { useEffect, useRef } from "react";
import { CornerDownLeft, Loader2 } from "lucide-react";
import { stormName } from "@/lib/storms";
import { cn } from "@/lib/utils";
import { AirportField } from "./AirportField";
import { type AirportChoice, airportByIcao, choiceLabel, resolveAirport } from "./airports";
import { DateField } from "./DateField";
import { dayLabel, editLabel, parseDate, todayIn, utcOffsetLabel } from "./dates";
import { FormNote } from "./Notes";
import { useDesk } from "./state";

/**
 * Quick picks keep the live demo fast. Labels and inputs only: what each day holds comes from the
 * run. Storm names are names (CONTRACTS has no name field yet; see lib/storms).
 */
const PICKS: { icao: string; date: string; label: string }[] = [
  { icao: "EIDW", date: "2025-01-24", label: stormName("EIDW@2025-01-24") ?? "Dublin" },
  { icao: "EIDW", date: "2025-01-26", label: stormName("EIDW@2025-01-26") ?? "Dublin" },
  { icao: "EGLL", date: "2024-01-21", label: "Storm Isha" },
  { icao: "EIDW", date: "2024-07-14", label: "A calm day" },
];

const STEPS = (icao: string) => [
  { text: `Pulling METAR for ${icao}`, sub: "pinned → IEM → AWC" },
  { text: "Finding the storm windows", sub: "at both ends of every flight" },
  { text: "Deciding each cancellation", sub: "the engine decides facts" },
  { text: "Drafting entitlements and the liability", sub: "drafts only, nothing posted" },
];

export function DayForm() {
  const s = useDesk();
  const dateRef = useRef<HTMLInputElement>(null);
  const runRef = useRef<HTMLButtonElement>(null);
  const airportBoxRef = useRef<HTMLDivElement>(null);

  const tz = s.airport?.airport?.tz;
  const today = todayIn(tz);
  const busy = !!s.pending;
  const steps = STEPS(s.pending?.icao ?? s.airport?.icao ?? "");
  const problem = s.problem;

  const focusAirport = () => airportBoxRef.current?.querySelector("input")?.focus();

  // "/" from anywhere on the page (outside a text field) goes to the airport: the fastest way in.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.closest("input, textarea, select, [contenteditable=true]") || t.isContentEditable)) return;
      e.preventDefault();
      airportBoxRef.current?.querySelector("input")?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const run = (override?: { icao: string; date: string }) => {
    if (busy && !override) return;
    if (override) {
      const a = airportByIcao(override.icao);
      const choice: AirportChoice = { icao: override.icao, airport: a };
      s.setAirport(choice, choiceLabel(choice));
      s.setDate(override.date, editLabel(override.date));
      void s.runDay(override.icao, override.date, a);
      return;
    }
    const airport = s.airport ?? resolveAirport(s.airportText);
    if (!airport) {
      useDesk.setState({
        problem: s.airportText.trim()
          ? { code: "client", field: "airport", message: `Pick “${s.airportText.trim()}” from the list, or type its 4-letter ICAO code.` }
          : { code: "client", field: "airport", message: "Name an airport first." },
      });
      focusAirport();
      return;
    }
    if (!s.airport) s.setAirport(airport, choiceLabel(airport));
    const date = s.date ?? parseDate(s.dateText, todayIn(airport.airport?.tz));
    if (!date) {
      useDesk.setState({
        problem: s.dateText.trim()
          ? { code: "client", field: "date", message: `“${s.dateText.trim()}” isn't a date. Try 24 Jan 2025.` }
          : { code: "client", field: "date", message: "Pick the local date at that airport." },
      });
      dateRef.current?.focus();
      return;
    }
    if (!s.date) s.setDate(date, editLabel(date));
    void s.runDay(airport.icao, date, airport.airport);
  };

  const offset = s.date ? utcOffsetLabel(tz, s.date) : null;
  const hint = s.airport?.airport
    ? `${s.airport.airport.name} local date${offset ? ` · ${offset} that day` : ""} · the timeline reads UTC`
    : "The date at the airport, not yours. Every time on the run is UTC (Z).";

  return (
    <section aria-label="Run a day" className="rounded-2xl bg-card p-4 shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)] md:p-5">
      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          run();
        }}
        className="grid gap-2.5 md:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)_auto]"
      >
        <div ref={airportBoxRef}>
          <AirportField
            value={s.airport}
            text={s.airportText}
            onChange={(choice, text) => s.setAirport(choice, text)}
            onPicked={() => window.requestAnimationFrame(() => dateRef.current?.focus())}
            onSubmit={() => run()}
            invalid={problem?.field === "airport"}
            describedBy="desk-day-note"
          />
        </div>
        <DateField
          ref={dateRef}
          value={s.date}
          text={s.dateText}
          onChange={(date, text) => s.setDate(date, text)}
          today={today}
          onSubmit={() => run()}
          onPicked={() => window.requestAnimationFrame(() => runRef.current?.focus())}
          invalid={problem?.field === "date"}
          describedBy="desk-day-note"
        />
        <button
          ref={runRef}
          type="submit"
          disabled={busy}
          className="group inline-flex h-[62px] items-center justify-center gap-2.5 rounded-xl bg-navy-900 px-6 text-[15px] font-semibold text-cloud-50 transition-colors hover:bg-navy-800 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-metar/30 disabled:cursor-progress disabled:bg-navy-800"
          data-testid="desk-run"
        >
          {busy ? <Loader2 className="size-4 animate-spin" aria-hidden="true" /> : null}
          {busy ? "Running" : "Run the day"}
          {!busy ? (
            <kbd className="hidden items-center rounded bg-white/10 px-1.5 py-0.5 font-mono text-[11px] font-normal text-cloud-300 md:inline-flex" aria-hidden="true">
              <CornerDownLeft className="size-3" />
            </kbd>
          ) : null}
        </button>
      </form>

      {/* One line under the inputs: what they mean, what the server is doing, or what went wrong. */}
      <div id="desk-day-note" className="mt-3 min-h-[22px]" aria-live="polite">
        <FormNote problem={problem} busy={busy} busyKey={s.token} steps={steps} hint={hint} onRetry={() => run()} onCancel={s.stopDay} testId="desk" />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-cloud-100 pt-3">
        <span className="micro mr-0.5 text-slate-400">Quick picks</span>
        {PICKS.map((p) => {
          const a = airportByIcao(p.icao);
          const active = s.ranFor?.icao === p.icao && s.ranFor?.date === p.date;
          return (
            <button
              key={`${p.icao}-${p.date}`}
              type="button"
              disabled={busy}
              onClick={() => run({ icao: p.icao, date: p.date })}
              className={cn(
                "group inline-flex h-9 items-center gap-2 rounded-lg px-2.5 text-[13px] transition-colors disabled:opacity-50",
                active ? "bg-navy-900 text-cloud-50" : "bg-cloud-50 text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-200)] hover:bg-cloud-100",
              )}
              title={`${a ? a.name : p.icao} · ${dayLabel(p.date)}`}
            >
              <span className={cn("font-mono text-[11.5px]", active ? "text-cloud-400" : "text-slate-500")}>{a?.iata ?? p.icao}</span>
              <span className="font-medium">{p.label}</span>
              <span className={cn("figure text-[12px]", active ? "text-cloud-400" : "text-slate-500")}>{editLabel(p.date)}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
