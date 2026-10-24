import { forwardRef, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { Popover, PopoverAnchor, PopoverContent } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { WEEKDAY_SHORT, addDays, addMonths, dayLabel, editLabel, monthGrid, monthName, parseDate, parts, weekday, type IsoDate } from "./dates";

/**
 * The local date at the airport. Type it any common way ("24 Jan 2025", "2025-01-24", "24/01/25",
 * "yesterday") or open the calendar. Enter runs. Days after today at that airport are dimmed in the
 * calendar; a typed future date still goes to the server, which answers with a plain message.
 */
export const DateField = forwardRef<
  HTMLInputElement,
  {
    value: IsoDate | null;
    text: string;
    onChange: (value: IsoDate | null, text: string) => void;
    today: IsoDate;
    onSubmit?: () => void;
    onPicked?: () => void;
    invalid?: boolean;
    describedBy?: string;
    className?: string;
  }
>(function DateField({ value, text, onChange, today, onSubmit, onPicked, invalid, describedBy, className }, ref) {
  const [focused, setFocused] = useState(false);
  const [open, setOpen] = useState(false);
  const showRich = !!value && !focused && text === editLabel(value);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverAnchor asChild>
        <div
          className={cn(
            "group relative flex h-[62px] items-center gap-2 rounded-xl bg-white pl-4 pr-2 shadow-[inset_0_0_0_1px_var(--color-cloud-300)] transition-shadow",
            "focus-within:shadow-[inset_0_0_0_1.5px_var(--color-navy-800),0_0_0_4px_color-mix(in_srgb,var(--color-metar)_16%,transparent)]",
            invalid && "shadow-[inset_0_0_0_1.5px_var(--color-navy-900)]",
            className,
          )}
        >
          <label className="flex min-w-0 flex-1 cursor-text flex-col justify-center">
            <span className="micro text-slate-500">Local date</span>
            <span className="relative mt-1 block">
              <input
                ref={ref}
                value={text}
                onChange={(e) => onChange(parseDate(e.target.value, today), e.target.value)}
                onFocus={(e) => {
                  setFocused(true);
                  e.currentTarget.select();
                }}
                onBlur={() => {
                  setFocused(false);
                  // Tidy "21/01/2024" into "21 Jan 2024"; an unchanged field leaves any message standing.
                  if (value && text !== editLabel(value)) onChange(value, editLabel(value));
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    // Show exactly which day is about to run ("21/01/2024" → "21 Jan 2024").
                    if (value && text !== editLabel(value)) onChange(value, editLabel(value));
                    onSubmit?.();
                  } else if (e.key === "ArrowDown" && e.altKey) {
                    e.preventDefault();
                    setOpen(true);
                  }
                }}
                placeholder="24 Jan 2025"
                autoComplete="off"
                spellCheck={false}
                aria-invalid={invalid || undefined}
                aria-describedby={describedBy}
                className={cn("w-full bg-transparent text-[17px] leading-6 text-navy-900 outline-none placeholder:text-slate-400", showRich && "text-transparent caret-transparent")}
              />
              {showRich && value ? (
                <span className="pointer-events-none absolute inset-0 flex items-center gap-1.5 text-[17px] leading-6" aria-hidden="true">
                  <span className="text-slate-500">{dayLabel(value).slice(0, 3)}</span>
                  <span className="figure text-navy-900">{editLabel(value)}</span>
                </span>
              ) : null}
            </span>
          </label>
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-label="Open the calendar"
            aria-expanded={open}
            className="inline-flex size-10 shrink-0 items-center justify-center rounded-lg text-slate-500 transition-colors hover:bg-cloud-50 hover:text-navy-900"
          >
            <CalendarDays className="size-[18px]" aria-hidden="true" />
          </button>
        </div>
      </PopoverAnchor>
      <PopoverContent align="end" sideOffset={8} className="w-[316px] rounded-xl p-3 shadow-[0_0_0_1px_var(--color-cloud-200),0_12px_32px_-8px_rgba(13,21,36,0.18)] ring-0">
        <Calendar
          value={value}
          today={today}
          onPick={(iso) => {
            onChange(iso, editLabel(iso));
            setOpen(false);
            onPicked?.();
          }}
        />
      </PopoverContent>
    </Popover>
  );
});

const LONG_DAY = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const longLabel = (iso: IsoDate) => {
  const { y, m, d } = parts(iso);
  return `${LONG_DAY[weekday(iso)]} ${d} ${monthName(m)} ${y}`;
};

/** Month grid with roving focus: arrows move a day/week, PageUp/PageDown a month (Shift: a year). */
function Calendar({ value, today, onPick }: { value: IsoDate | null; today: IsoDate; onPick: (iso: IsoDate) => void }) {
  const [focus, setFocus] = useState<IsoDate>(value && value <= today ? value : today);
  const { y, m } = parts(focus);
  const grid = monthGrid(y, m);
  const gridRef = useRef<HTMLDivElement>(null);
  const moved = useRef(false);

  useEffect(() => {
    // Opening (and every keyboard move) puts focus on the active day.
    const el = gridRef.current?.querySelector<HTMLButtonElement>(`[data-day="${focus}"]`);
    if (el && (moved.current || !gridRef.current?.contains(document.activeElement))) el.focus();
    moved.current = false;
  }, [focus]);

  const go = (next: IsoDate) => {
    moved.current = true;
    setFocus(next);
  };

  const onKey = (e: KeyboardEvent) => {
    const map: Record<string, () => IsoDate> = {
      ArrowLeft: () => addDays(focus, -1),
      ArrowRight: () => addDays(focus, 1),
      ArrowUp: () => addDays(focus, -7),
      ArrowDown: () => addDays(focus, 7),
      PageUp: () => addMonths(focus, e.shiftKey ? -12 : -1),
      PageDown: () => addMonths(focus, e.shiftKey ? 12 : 1),
      Home: () => addDays(focus, -((weekday(focus) + 6) % 7)),
      End: () => addDays(focus, 6 - ((weekday(focus) + 6) % 7)),
    };
    const fn = map[e.key];
    if (!fn) return;
    e.preventDefault();
    go(fn());
  };

  const years: number[] = [];
  for (let yr = parts(today).y; yr >= 1995; yr--) years.push(yr);

  return (
    <div>
      <div className="mb-2 flex items-center gap-1">
        <button type="button" onClick={() => setFocus(addMonths(focus, -1))} aria-label="Previous month" className="inline-flex size-8 items-center justify-center rounded-md text-slate-500 hover:bg-cloud-50 hover:text-navy-900">
          <ChevronLeft className="size-4" aria-hidden="true" />
        </button>
        <div className="flex flex-1 items-center justify-center gap-1">
          <label className="sr-only" htmlFor="desk-cal-month">
            Month
          </label>
          <select
            id="desk-cal-month"
            value={m}
            onChange={(e) => setFocus(clampDay(y, Number(e.target.value), parts(focus).d))}
            className="h-8 cursor-pointer rounded-md bg-transparent px-1.5 text-[14px] font-semibold text-navy-900 outline-none hover:bg-cloud-50 focus-visible:ring-2 focus-visible:ring-metar/40"
          >
            {Array.from({ length: 12 }, (_, i) => (
              <option key={i} value={i + 1}>
                {monthName(i + 1)}
              </option>
            ))}
          </select>
          <label className="sr-only" htmlFor="desk-cal-year">
            Year
          </label>
          <select
            id="desk-cal-year"
            value={y}
            onChange={(e) => setFocus(clampDay(Number(e.target.value), m, parts(focus).d))}
            className="figure h-8 cursor-pointer rounded-md bg-transparent px-1.5 text-[14px] font-semibold text-navy-900 outline-none hover:bg-cloud-50 focus-visible:ring-2 focus-visible:ring-metar/40"
          >
            {years.map((yr) => (
              <option key={yr} value={yr}>
                {yr}
              </option>
            ))}
          </select>
        </div>
        <button type="button" onClick={() => setFocus(addMonths(focus, 1))} aria-label="Next month" className="inline-flex size-8 items-center justify-center rounded-md text-slate-500 hover:bg-cloud-50 hover:text-navy-900">
          <ChevronRight className="size-4" aria-hidden="true" />
        </button>
      </div>
      <div role="grid" aria-label={`${monthName(m)} ${y}`} ref={gridRef} onKeyDown={onKey}>
        <div role="row" className="grid grid-cols-7">
          {WEEKDAY_SHORT.map((w) => (
            <span key={w} role="columnheader" className="micro py-1 text-center text-slate-400">
              {w}
            </span>
          ))}
        </div>
        {grid.map((week, i) => (
          <div role="row" key={i} className="grid grid-cols-7">
            {week.map((iso, j) =>
              iso ? (
                <span role="gridcell" key={iso} className="p-0.5">
                  <button
                    type="button"
                    data-day={iso}
                    tabIndex={iso === focus ? 0 : -1}
                    disabled={iso > today}
                    aria-label={`${longLabel(iso)}${iso === today ? ", today" : ""}${iso > today ? ", not yet" : ""}`}
                    aria-pressed={iso === value}
                    onClick={() => onPick(iso)}
                    onFocus={() => iso !== focus && setFocus(iso)}
                    className={cn(
                      "figure relative flex h-9 w-full items-center justify-center rounded-lg text-[13.5px] text-navy-900 transition-colors hover:bg-cloud-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-metar/50",
                      iso === value && "bg-navy-900 font-semibold text-cloud-50 hover:bg-navy-800",
                      iso > today && "cursor-not-allowed text-cloud-400 hover:bg-transparent",
                    )}
                  >
                    {parts(iso).d}
                    {iso === today ? <span className={cn("absolute bottom-1 size-1 rounded-full", iso === value ? "bg-cloud-50" : "bg-metar")} aria-hidden="true" /> : null}
                  </button>
                </span>
              ) : (
                <span role="gridcell" key={`pad-${i}-${j}`} aria-hidden="true" />
              ),
            )}
          </div>
        ))}
      </div>
      <p className="mt-2 border-t border-cloud-100 px-1 pt-2 text-[11.5px] leading-snug text-slate-400">The date at that airport. Arrows move, PageUp/PageDown change month.</p>
    </div>
  );
}

function clampDay(y: number, m: number, d: number): IsoDate {
  const max = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return `${y}-${String(m).padStart(2, "0")}-${String(Math.min(d, max)).padStart(2, "0")}`;
}
