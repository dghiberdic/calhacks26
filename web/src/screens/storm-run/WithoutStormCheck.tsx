import type { EffortEstimate } from "@/api/types";
import { MicroLabel } from "@/components/chips";
import { Explain } from "@/components/explain";
import { Details, Money, Panel } from "@/components/kit";
import { eur } from "@/lib/format";
import { plainIds } from "@/lib/plain";
import { hoursCell, roughEur, roughHours } from "./effort";

/**
 * "Without StormCheck": what the selected run would take done by hand, in one sentence. The lines, the errors
 * it caught and the assumptions sit behind "How we got this". Every figure is the API's; nothing is stored.
 */
export function WithoutStormCheck({ effort, noun = "storm" }: { effort: EffortEstimate; noun?: string }) {
  if (!(effort.manual_hours > 0)) return null;
  const sources = [...new Set(effort.lines.map((l) => l.source).filter((s): s is string => !!s))];
  return (
    <Panel>
      <div data-testid="without-stormcheck">
        <MicroLabel>Estimated review workload</MicroLabel>
        <p className="mt-2 max-w-[72ch] text-[17px] leading-snug text-navy-900" data-testid="effort-headline">
          Manual review of this {noun}: {roughHours(effort.manual_hours)}. With StormCheck: {roughHours(effort.with_stormcheck_hours)}.
        </p>
        <p className="mt-2 text-[12px] leading-relaxed text-slate-500">Modelled estimate, not measured airline savings.</p>
        <Details className="mt-3" summary="How we got this">
          <p className="mb-3 text-[13px] text-slate-500">Estimated manual cost:{" "}
          <Explain term="loaded-cost" className="figure">
            {roughEur(effort.manual_cost_cents)}
          </Explain>
          .
          </p>
          <div className="-mx-1 overflow-x-auto px-1">
            <table className="w-full min-w-[600px] border-collapse text-left text-[12.5px] leading-snug">
              <thead>
                <tr className="text-[11.5px] text-slate-400">
                  <th scope="col" className="py-1.5 pr-4 font-medium">Task</th>
                  <th scope="col" className="whitespace-nowrap py-1.5 pr-4 text-right font-medium">By hand → with StormCheck</th>
                  <th scope="col" className="py-1.5 pr-4 font-medium">Basis</th>
                  <th scope="col" className="py-1.5 font-medium">Who</th>
                </tr>
              </thead>
              <tbody>
                {effort.lines.map((l) => (
                  <tr key={l.task} className="border-t border-cloud-100 align-top">
                    <td className="py-2 pr-4 font-medium text-navy-900">{l.task}</td>
                    <td className="figure whitespace-nowrap py-2 pr-4 text-right text-navy-900">
                      {hoursCell(l.manual_hours)} → {hoursCell(l.with_stormcheck_hours)}
                    </td>
                    <td className="py-2 pr-4 text-slate-500">{l.basis}</td>
                    <td className="whitespace-nowrap py-2 text-slate-500">
                      {l.role} <span className="figure text-slate-400">· €{l.rate_eur_per_hour}/h</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {effort.errors_caught.length ? (
            <div className="mt-4">
              <p className="text-[12.5px] font-semibold text-navy-900">Errors flagged in this run</p>
              <ul className="mt-1.5 flex list-disc flex-col gap-1 pl-5 text-[12.5px] leading-relaxed text-slate-600" data-testid="errors-caught">
                {effort.errors_caught.map((e) => (
                  <li key={e.label}>
                    <span className="text-navy-900">{plainIds(e.label)}</span>
                    {/* The amount once: skip it when the server's detail already says it. */}
                    {e.amount_cents !== null && e.amount_cents !== undefined && !e.detail?.includes(eur(e.amount_cents)) ? (
                      <>
                        : <Money cents={e.amount_cents} className="font-medium text-navy-900" />
                      </>
                    ) : null}
                    {e.detail ? <>. {e.detail}</> : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="mt-4 flex flex-col gap-1 text-[11.5px] leading-relaxed text-slate-400">
            <p>
              {effort.assumptions_note} The sentence above rounds hours to the nearest 5 and euros to the nearest €100; each hour is priced at its role&rsquo;s <Explain term="loaded-cost">loaded cost</Explain>.
            </p>
            {sources.length ? (
              <ul className="flex flex-col gap-0.5">
                {sources.map((s) => (
                  <li key={s}>Source: {s}</li>
                ))}
              </ul>
            ) : null}
          </div>
        </Details>
      </div>
    </Panel>
  );
}
