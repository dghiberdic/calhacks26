import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { useLocation } from "react-router";
import { useAccessLog, useAccessMatrix } from "@/api/queries";
import type { AccessCell, AccessDecision, AccessMatrix } from "@/api/types";
import { useSession } from "@/app/session";
import { Empty, ErrorNote, Panel, Shimmer } from "@/components/kit";
import { longDate, zulu } from "@/lib/format";
import { cn } from "@/lib/utils";
import { CELL_HINT, CELL_ORDER, denialTag, isAgent, orderPrincipals, principalLabel, principalRole } from "./model";
import { PiiMask } from "./PiiMask";
import { PrincipalAvatar } from "./parts";

/** J5 · Access: who (people and agents) can do what, every denial, and what a seat without PII rights sees. */
export function AccessTab() {
  const matrix = useAccessMatrix();
  const log = useAccessLog();
  const { hash } = useLocation();

  useEffect(() => {
    if (hash !== "#denied" || !log.data) return;
    document.getElementById("denied")?.scrollIntoView({ block: "start" });
  }, [hash, log.data]);

  return (
    <div className="flex flex-col gap-5">
      <Panel padded={false}>
        <div className="flex flex-wrap items-end justify-between gap-3 px-5 pt-4">
          <div>
            <h2 className="text-[14.5px] font-semibold text-navy-900">Who can do what</h2>
            <p className="mt-0.5 text-[13px] text-slate-500">People and agents are principals alike. Every request goes through the same broker.</p>
          </div>
          <CellLegend />
        </div>
        <div className="mt-3">
          {matrix.isLoading ? (
            <div className="px-5 pb-5">
              <Shimmer className="h-[360px]" />
            </div>
          ) : matrix.isError ? (
            <div className="px-5 pb-5">
              <ErrorNote error={matrix.error} onRetry={() => void matrix.refetch()} />
            </div>
          ) : matrix.data && matrix.data.principals.length ? (
            <Matrix matrix={matrix.data} />
          ) : (
            <div className="px-5 pb-5">
              <Empty title="No access matrix">The broker hasn&rsquo;t published one yet.</Empty>
            </div>
          )}
        </div>
      </Panel>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <DeniedLog log={log.data} loading={log.isLoading} error={log.isError ? log.error : null} onRetry={() => void log.refetch()} />
        <PiiMask matrix={matrix.data} />
      </div>
    </div>
  );
}

// ---------- matrix ----------
function Matrix({ matrix }: { matrix: AccessMatrix }) {
  const me = useSession((s) => s.role);
  const principals = useMemo(() => orderPrincipals(matrix.principals), [matrix.principals]);
  const firstAgent = principals.findIndex((p) => isAgent(p));
  return (
    <div className="relative overflow-x-auto overscroll-x-contain focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-metar-ink" style={SCROLL_SHADOWS} role="region" aria-label="Access matrix" tabIndex={0}>
      <table className="w-full min-w-[760px] border-separate border-spacing-0 text-[12.5px]">
        <caption className="sr-only">Access by principal and resource: approve, write, read, redacted or none</caption>
        <thead>
          <tr>
            <th scope="col" className="sticky left-0 z-10 bg-card px-5 pb-2.5 pt-1 text-left align-bottom font-normal">
              <span className="micro text-slate-400">principal</span>
            </th>
            {matrix.resources.map((r) => (
              <th key={r} scope="col" className="px-1.5 pb-2.5 pt-1 text-left align-bottom font-normal">
                <span className="font-mono block max-w-[96px] break-words text-[11px] leading-tight text-slate-500">{softBreaks(r)}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {principals.map((p, i) => {
            const mine = principalRole(p) === me;
            return (
              <tr key={p} className={cn("group", mine && "[&>*]:bg-cloud-50")}>
                <th
                  scope="row"
                  className={cn(
                    "sticky left-0 z-10 bg-card px-5 py-1.5 text-left font-normal",
                    i === firstAgent && "border-t border-cloud-200",
                    i === 0 && "border-t border-cloud-100",
                    i !== 0 && i !== firstAgent && "border-t border-cloud-100",
                  )}
                >
                  <span className="flex items-center gap-2 whitespace-nowrap">
                    <PrincipalAvatar principal={p} />
                    <span className="text-[13px] text-navy-900">{principalLabel(p)}</span>
                    {mine ? <span className="micro text-slate-400">you</span> : null}
                  </span>
                </th>
                {matrix.resources.map((r) => (
                  <td key={r} className={cn("px-1.5 py-1.5", i === firstAgent ? "border-t border-cloud-200" : "border-t border-cloud-100")}>
                    <Cell value={matrix.cells[p]?.[r] ?? "none"} />
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** Shadows at an edge only while there is more matrix to scroll that way (backgrounds attached to the content cover them at the ends). */
const SCROLL_SHADOWS: CSSProperties = {
  background:
    "linear-gradient(to right, var(--color-card) 40%, transparent) left center / 48px 100% no-repeat local, linear-gradient(to left, var(--color-card) 40%, transparent) right center / 48px 100% no-repeat local, radial-gradient(farthest-side at 0 50%, rgba(13,21,36,0.10), transparent) left center / 14px 100% no-repeat scroll, radial-gradient(farthest-side at 100% 50%, rgba(13,21,36,0.10), transparent) right center / 14px 100% no-repeat scroll",
};

/** Let long resource ids wrap after "_" and "." (zero-width spaces; the id itself is unchanged in the API). */
const softBreaks = (id: string) => id.replace(/([_.])/g, "$1\u200b");

const CELL_STYLE: Record<AccessCell, string> = {
  approve: "bg-navy-900 text-cloud-50",
  write: "bg-white text-navy-900 shadow-[inset_0_0_0_1px_var(--color-navy-700)]",
  read: "bg-cloud-100 text-slate-600",
  redacted: "text-slate-500 shadow-[inset_0_0_0_1px_var(--color-cloud-300)] bg-[repeating-linear-gradient(135deg,transparent,transparent_3px,var(--color-cloud-200)_3px,var(--color-cloud-200)_4.5px)]",
  none: "text-cloud-400",
};

function Cell({ value }: { value: AccessCell }) {
  if (value === "none")
    return (
      <span className="inline-flex h-6 items-center px-2 font-mono text-[11px] text-cloud-400" title={CELL_HINT.none}>
        <span aria-hidden="true">—</span>
        <span className="sr-only">none</span>
      </span>
    );
  return (
    <span title={CELL_HINT[value]} className={cn("inline-flex h-6 items-center rounded-md px-2 font-mono text-[11px]", CELL_STYLE[value])}>
      {value}
    </span>
  );
}

function CellLegend() {
  return (
    <ul className="flex flex-wrap items-center gap-1.5" aria-label="Legend">
      {CELL_ORDER.map((c) => (
        <li key={c} className="inline-flex items-center">
          <Cell value={c} />
          {c === "none" ? <span className="-ml-1 font-mono text-[11px] text-slate-400">none</span> : null}
        </li>
      ))}
    </ul>
  );
}

// ---------- denied log ----------
function DeniedLog({ log, loading, error, onRetry }: { log: AccessDecision[] | undefined; loading: boolean; error: unknown; onRetry: () => void }) {
  const [all, setAll] = useState(false);
  const sorted = useMemo(() => [...(log ?? [])].sort((a, b) => b.at.localeCompare(a.at)), [log]);
  const denied = sorted.filter((d) => !d.allowed);
  const shown = all ? sorted : denied;
  return (
    <section id="denied" className="scroll-mt-24 rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]" aria-labelledby="denied-title">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-4">
        <div>
          <h2 id="denied-title" className="text-[14.5px] font-semibold text-navy-900">
            Denied
          </h2>
          <p className="mt-0.5 text-[13px] text-slate-500">Every refusal is a commit. Agents are refused like anyone else.</p>
        </div>
        {sorted.length > denied.length ? (
          <button type="button" aria-pressed={all} onClick={() => setAll((v) => !v)} className="rounded-md px-2 py-1 text-[12.5px] font-medium text-metar-ink hover:bg-cloud-50">
            {all ? "Denied only" : `Show allowed too (${sorted.length - denied.length})`}
          </button>
        ) : null}
      </div>
      <div className="px-5 pb-4 pt-3">
        {loading ? (
          <div className="flex flex-col gap-2">
            <Shimmer className="h-12" />
            <Shimmer className="h-12" />
          </div>
        ) : error ? (
          <ErrorNote error={error} onRetry={onRetry} />
        ) : shown.length === 0 ? (
          <p className="py-6 text-center text-[13.5px] text-slate-500">Nothing denied yet.</p>
        ) : (
          <ol className="flex flex-col" data-testid="denied-log">
            {shown.map((d, i) => (
              <li key={`${d.at}-${i}`} className="grid grid-cols-[minmax(0,1fr)] gap-x-4 border-t border-cloud-100 py-3 first:border-t-0 sm:grid-cols-[92px_minmax(0,1fr)]">
                <span className="figure pt-0.5 text-[12px] text-slate-400">
                  <span className="sm:block">{longDate(d.at).slice(0, -5)}</span> {zulu(d.at)}
                </span>
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 font-mono text-[12.5px] text-navy-900">
                    <PrincipalAvatar principal={d.principal} />
                    <span className="font-mono">{d.principal}</span>
                    <span className="font-mono">{d.action}</span>
                    <span className="text-slate-400" aria-hidden="true">
                      →
                    </span>
                    {d.allowed ? (
                      <span className="inline-flex h-5 items-center rounded px-1.5 text-[10.5px] font-bold uppercase tracking-[0.06em] text-slate-600 shadow-[inset_0_0_0_1px_var(--color-cloud-300)]">allowed</span>
                    ) : (
                      <span className="inline-flex h-5 items-center rounded bg-navy-900 px-1.5 text-[10.5px] font-bold tracking-[0.04em] text-cloud-50">DENIED · {denialTag(d.reason)}</span>
                    )}
                  </p>
                  <p className="mt-1 text-[12.5px] leading-snug text-slate-500">
                    <span className="font-mono text-[11.5px] text-slate-600">{d.resource}</span> · {d.reason}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}

