import type { ReactNode } from "react";
import { duration, zulu, zuluDay } from "@/lib/format";
import type { WeatherDefence } from "./defence";
import { ELECTION_LABEL, markText } from "./lib";

/**
 * "Defence prepared · Art. 5(3)": what the airline would answer a compensation claim on this weather
 * cancellation, row by row, each from the file's own evidence. It argues this flight, not the storm:
 * the airport kept running, and a claimant can see that too.
 */
export function WeatherDefenceRows({ defence: d }: { defence: WeatherDefence }) {
  const scheduled = d.end === "dep" ? "STD" : "STA";
  const rows: { term: string; body: ReactNode }[] = [
    {
      term: "The circumstance",
      body: (
        <>
          Meteorological conditions incompatible with the operation of the flight <span className="text-slate-400">(Reg. (EC) 261/2004, Art. 5(3) and recital 14)</span>.
        </>
      ),
    },
    {
      term: "This flight",
      body: (
        <>
          {d.station} inside the storm window at {scheduled} {zulu(d.at)}
          {d.window ? (
            <span className="text-slate-500">
              {" "}
              (window {zulu(d.window.start)}–{zulu(d.window.end)}, computed from METAR)
            </span>
          ) : null}
          .{d.metar ? <span className="mt-1.5 block break-words font-mono text-[12px] leading-relaxed text-navy-900">{d.metar}</span> : null}
        </>
      ),
    },
  ];

  if (d.minutesToClose !== null && d.window)
    rows.push({
      term: "The alternative",
      body: (
        <>
          The window closed {duration(d.minutesToClose)} after {scheduled}. Delaying past {zulu(d.window.end)} was the alternative to cancelling; that is the question to answer.
        </>
      ),
    });

  if (d.known.length || d.occ)
    rows.push({
      term: "Known before deciding",
      body: (
        <ul className="flex flex-col gap-1">
          {d.known.map((m, i) => (
            <li key={i}>
              <span className="font-mono text-[12px] text-slate-500">{zuluDay(m.at!)}</span> {markText(m)}
            </li>
          ))}
          {d.occ ? (
            <li>
              <span className="font-mono text-[12px] text-slate-500">{zulu(d.occ.at!)}</span> OCC&rsquo;s batch cancel list, checked against the METAR above rather than taken on trust.
            </li>
          ) : null}
        </ul>
      ),
    });

  if (d.warnings.length) rows.push({ term: "Warnings that day", body: <>Met Éireann: {d.warnings.join(" · ")}.</> });

  if (d.departures)
    rows.push({
      term: "Against us",
      body: <>The airport never closed: {d.departures}. So the defence rests on this flight&rsquo;s own weather, not on Dublin shutting.</>,
    });

  rows.push({
    term: "Still owed",
    body: (
      <>
        {d.stillOwed ?? "Refunds and care are still due"} <span className="text-slate-400">(Arts 8–9; C-12/11 McDonagh)</span>.
        {d.elections.length ? (
          <span className="mt-1 block text-slate-500">
            {d.elections.map(([k, n], i) => (
              <span key={k}>
                {i > 0 ? " · " : ""}
                {ELECTION_LABEL[k] ?? k} <span className="figure font-medium text-navy-900">{n.toLocaleString("en-US")}</span>
              </span>
            ))}
          </span>
        ) : null}
      </>
    ),
  });

  return (
    <dl className="grid gap-x-6 gap-y-3 text-[13.5px] leading-relaxed text-slate-600 sm:grid-cols-[150px_minmax(0,1fr)]">
      {rows.map(({ term, body }) => (
        <div key={term} className="contents">
          <dt className="pt-px font-medium text-navy-900">{term}</dt>
          <dd className="min-w-0">{body}</dd>
        </div>
      ))}
    </dl>
  );
}
