import { useMemo } from "react";
import { Link } from "react-router";
import { ArrowRight } from "lucide-react";
import { useControls } from "@/api/queries";
import { Empty, ErrorNote, Shimmer } from "@/components/kit";
import { compareFrameworkRef, evidenceTarget } from "./model";

/** J5 · Controls: SOC 2 is the floor. A mapping of each control to the code and evidence behind it; not a certification. */
export function ControlsTab() {
  const controls = useControls();
  const rows = useMemo(() => [...(controls.data ?? [])].sort((a, b) => compareFrameworkRef(a.framework_ref, b.framework_ref)), [controls.data]);

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div>
          <h2 className="display-tight text-[24px] leading-tight text-navy-900">SOC 2 is the floor</h2>
          <p className="mt-1 max-w-[62ch] text-[14px] text-slate-500">Each control, the code that enforces it, and the evidence you can open.</p>
        </div>
        <span className="inline-flex h-7 items-center rounded-md px-2.5 font-mono text-[11.5px] text-slate-600 shadow-[inset_0_0_0_1px_var(--color-cloud-300)]">mapping · not a certification</span>
      </div>

      <div className="mt-5">
        {controls.isLoading ? (
          <div className="flex flex-col gap-px overflow-hidden rounded-xl">
            {Array.from({ length: 5 }, (_, i) => (
              <Shimmer key={i} className="h-[76px] rounded-none" />
            ))}
          </div>
        ) : controls.isError ? (
          <ErrorNote error={controls.error} onRetry={() => void controls.refetch()} />
        ) : rows.length === 0 ? (
          <Empty title="No controls mapped">The control mapping hasn&rsquo;t been published.</Empty>
        ) : (
          <ol className="overflow-hidden rounded-xl bg-card shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]" aria-label="Control mapping">
            {rows.map((c) => {
              const target = evidenceTarget(c.evidence_endpoint);
              return (
                <li key={`${c.framework_ref}-${c.control}`} className="grid gap-x-6 gap-y-2 border-t border-cloud-100 px-5 py-4 first:border-t-0 md:grid-cols-[88px_minmax(0,1fr)_minmax(0,220px)] md:items-center md:py-5">
                  <span className="figure inline-flex h-7 w-fit items-center rounded-md bg-navy-900 px-2.5 text-[13px] font-semibold tracking-[0.01em] text-cloud-50">{c.framework_ref}</span>
                  <div className="min-w-0">
                    <p className="text-[15px] font-medium leading-snug text-navy-900">{c.control}</p>
                    <p className="mt-1 break-words text-[11.5px] leading-relaxed text-slate-500">
                      <span className="font-mono">{c.implemented_by}</span>
                    </p>
                  </div>
                  <div className="min-w-0 md:text-right">
                    <span className="micro block text-slate-400">evidence</span>
                    <span className="font-mono mt-0.5 block break-all text-[11.5px] text-slate-600">{c.evidence_endpoint}</span>
                    {target ? (
                      <Link to={target.to} aria-label={`Evidence for ${c.framework_ref}: ${target.label}`} className="mt-1 inline-flex items-center gap-1 text-[13px] font-medium text-metar-ink hover:underline">
                        {target.label}
                        <ArrowRight className="size-3.5" aria-hidden="true" />
                      </Link>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </div>
  );
}
