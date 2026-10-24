import { useMemo, useRef, useState } from "react";
import { Command as Cmdk } from "cmdk";
import { CornerDownLeft } from "lucide-react";
import { cn } from "@/lib/utils";
import { type AirportChoice, type AirportRow, ICAO_SHAPE, airportByIcao, airportLabel, choiceLabel, resolveAirport, searchAirports } from "./airports";

const FREE = "__typed__";

/**
 * Airport autocomplete: type IATA, ICAO or a city; arrows + Enter pick, Escape closes. A 4-letter
 * ICAO code that isn't in the list can still be used as typed: the server says whether it knows it.
 */
export function AirportField({
  value,
  text,
  onChange,
  onPicked,
  onSubmit,
  invalid,
  describedBy,
  className,
}: {
  value: AirportChoice | null;
  text: string;
  onChange: (choice: AirportChoice | null, text: string) => void;
  /** After a pick: the form moves focus on to the date. */
  onPicked?: (choice: AirportChoice) => void;
  /** Enter with the list closed runs the form. */
  onSubmit?: () => void;
  invalid?: boolean;
  describedBy?: string;
  className?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [focused, setFocused] = useState(false);
  const [highlight, setHighlight] = useState("");

  // While a pick is shown, the query is empty: the list offers the suggestions.
  const query = value && text === choiceLabel(value) ? "" : text;
  const results = useMemo(() => searchAirports(query, 8), [query]);
  const code = query.trim().toUpperCase();
  const offerTyped = ICAO_SHAPE.test(code) && !airportByIcao(code);

  const pick = (choice: AirportChoice) => {
    onChange(choice, choiceLabel(choice));
    setOpen(false);
    onPicked?.(choice);
  };

  const showRich = !!value && !focused && text === choiceLabel(value);

  return (
    <Cmdk
      shouldFilter={false}
      loop
      value={highlight}
      onValueChange={setHighlight}
      label="Airport"
      className={cn("relative", className)}
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.preventDefault();
          e.stopPropagation();
          setOpen(false);
        } else if (e.key === "Enter" && !open) {
          // The list is closed: Enter belongs to the form.
          e.preventDefault();
          onSubmit?.();
        } else if ((e.key === "ArrowDown" || e.key === "ArrowUp") && !open) {
          setOpen(true);
        }
      }}
    >
      <div
        className={cn(
          "group relative flex h-[62px] flex-col justify-center rounded-xl bg-white px-4 shadow-[inset_0_0_0_1px_var(--color-cloud-300)] transition-shadow",
          "focus-within:shadow-[inset_0_0_0_1.5px_var(--color-navy-800),0_0_0_4px_color-mix(in_srgb,var(--color-metar)_16%,transparent)]",
          invalid && "shadow-[inset_0_0_0_1.5px_var(--color-navy-900)]",
        )}
        onMouseDown={(e) => {
          if (e.target !== inputRef.current) {
            e.preventDefault();
            inputRef.current?.focus();
          }
        }}
      >
        <span className="flex items-center justify-between gap-2" aria-hidden="true">
          <span className="micro cursor-text text-slate-500">Airport</span>
          {!focused ? <kbd className="hidden h-[18px] items-center rounded border border-cloud-200 px-1.5 font-mono text-[10.5px] leading-none text-slate-400 md:inline-flex">/</kbd> : null}
        </span>
        <div className="relative mt-1">
          <Cmdk.Input
            ref={inputRef}
            value={text}
            onValueChange={(next) => {
              // A pick holds only while the text is still exactly its label.
              onChange(value && next === choiceLabel(value) ? value : null, next);
              setOpen(true);
            }}
            onFocus={(e) => {
              setFocused(true);
              setOpen(true);
              e.currentTarget.select();
            }}
            onBlur={() => {
              setFocused(false);
              setOpen(false);
              // Leaving the field with a clear match counts as picking it.
              if (!value) {
                const resolved = resolveAirport(text);
                if (resolved) onChange(resolved, choiceLabel(resolved));
              }
            }}
            placeholder="City, IATA or ICAO"
            autoComplete="off"
            spellCheck={false}
            aria-invalid={invalid || undefined}
            aria-describedby={describedBy}
            className={cn(
              "w-full bg-transparent text-[17px] leading-6 text-navy-900 outline-none placeholder:text-slate-400",
              showRich && "text-transparent caret-transparent selection:bg-transparent",
            )}
          />
          {showRich && value ? (
            <span className="pointer-events-none absolute inset-0 flex items-center gap-2 truncate text-[17px] leading-6" aria-hidden="true">
              {value.airport ? (
                <>
                  <span className="font-mono text-[14px] text-slate-500">
                    {value.airport.iata} · {value.airport.icao} ·
                  </span>
                  <span className="truncate text-navy-900">{value.airport.name}</span>
                </>
              ) : (
                <>
                  <span className="font-mono text-[14px] text-navy-900">{value.icao}</span>
                  <span className="truncate text-[13px] text-slate-500">ICAO, as typed</span>
                </>
              )}
            </span>
          ) : null}
        </div>
      </div>

      {open ? (
        <div
          className="absolute inset-x-0 top-[calc(100%+6px)] z-40 overflow-hidden rounded-xl bg-white shadow-[0_0_0_1px_var(--color-cloud-200),0_12px_32px_-8px_rgba(13,21,36,0.18)]"
          onMouseDown={(e) => e.preventDefault()}
        >
          <Cmdk.List className="max-h-[332px] overflow-y-auto overscroll-contain p-1.5">
            {!query ? <div className="micro px-2.5 pb-1 pt-1.5 text-slate-400">Suggested</div> : null}
            {results.map((a) => (
              <AirportItem key={a.icao} airport={a} query={query} onSelect={() => pick({ icao: a.icao, airport: a })} selected={value?.icao === a.icao} />
            ))}
            {offerTyped ? (
              <Cmdk.Item
                value={FREE}
                onSelect={() => pick({ icao: code })}
                className="flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2 data-[selected=true]:bg-cloud-50"
              >
                <span className="inline-flex h-6 min-w-[46px] items-center justify-center rounded-md bg-cloud-100 font-mono text-[12px] text-navy-900">{code}</span>
                <span className="min-w-0 flex-1 text-[13.5px] text-navy-900">
                  Use {code} as typed
                  <span className="block text-[12px] text-slate-500">Not in this list. The server says whether it has METAR for it.</span>
                </span>
              </Cmdk.Item>
            ) : null}
            {!results.length && !offerTyped ? (
              <div className="px-3 py-4 text-[13px] leading-relaxed text-slate-500">
                No airport matches &ldquo;{query.trim()}&rdquo;. Type its 4-letter ICAO code, like <span className="font-mono text-navy-900">EGPH</span>.
              </div>
            ) : null}
          </Cmdk.List>
          <div className="flex items-center gap-3 border-t border-cloud-100 px-3 py-1.5 text-[11.5px] text-slate-400">
            <span>
              <kbd className="font-mono">↑↓</kbd> move
            </span>
            <span className="inline-flex items-center gap-1">
              <CornerDownLeft className="size-3" aria-hidden="true" /> pick
            </span>
            <span>
              <kbd className="font-mono">esc</kbd> close
            </span>
          </div>
        </div>
      ) : null}
    </Cmdk>
  );
}

function AirportItem({ airport: a, query, onSelect, selected }: { airport: AirportRow; query: string; onSelect: () => void; selected: boolean }) {
  return (
    <Cmdk.Item
      value={a.icao}
      onSelect={onSelect}
      className="flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2 data-[selected=true]:bg-cloud-50"
      aria-label={airportLabel(a)}
    >
      <span className={cn("inline-flex h-6 min-w-[46px] items-center justify-center rounded-md font-mono text-[12px]", selected ? "bg-navy-900 text-cloud-50" : "bg-cloud-100 text-navy-900")}>
        <Hit text={a.iata} query={query} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[14px] text-navy-900">
          <Hit text={a.name} query={query} />
        </span>
        <span className="block truncate text-[12px] text-slate-500">
          {a.city !== a.name ? `${a.city} · ` : ""}
          {a.country} · {a.tz}
        </span>
      </span>
      <span className="font-mono text-[12px] text-slate-500">
        <Hit text={a.icao} query={query} />
      </span>
    </Cmdk.Item>
  );
}

/** Bold the typed prefix where it starts a word, so the eye finds why a row matched. */
function Hit({ text, query }: { text: string; query: string }) {
  const q = query.trim();
  if (!q) return <>{text}</>;
  const fold = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const hay = fold(text);
  const needle = fold(q.split(/\s+/)[0]);
  let at = -1;
  for (let i = hay.indexOf(needle); i >= 0; i = hay.indexOf(needle, i + 1)) {
    if (i === 0 || /[^a-z0-9]/.test(hay[i - 1])) {
      at = i;
      break;
    }
  }
  if (at < 0 || !needle) return <>{text}</>;
  return (
    <>
      {text.slice(0, at)}
      <span className="font-semibold">{text.slice(at, at + needle.length)}</span>
      {text.slice(at + needle.length)}
    </>
  );
}
