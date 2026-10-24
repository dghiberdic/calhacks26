import type { AccessMatrix } from "@/api/types";
import { MicroLabel } from "@/components/chips";
import { orderPrincipals, piiResource, principalLabel } from "./model";
import { PrincipalAvatar } from "./parts";

/** "View as Ops": who sees passenger PII in the clear, who sees it masked, and who can't open it. */
export function PiiMask({ matrix }: { matrix: AccessMatrix | undefined }) {
  const resource = piiResource(matrix);
  if (!matrix || !resource) return null;
  const by = (cell: string) => orderPrincipals(matrix.principals).filter((p) => (matrix.cells[p]?.[resource] ?? "none") === cell);
  const groups = [
    { label: "Sees it", list: [...by("approve"), ...by("write"), ...by("read")] },
    { label: "Masked", list: by("redacted") },
    { label: "No access", list: by("none") },
  ];
  return (
    <section className="rounded-xl bg-card px-5 py-4 shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]" aria-labelledby="pii-title">
      <h2 id="pii-title" className="text-[14.5px] font-semibold text-navy-900">
        Passenger PII
      </h2>
      <p className="mt-0.5 text-[13px] text-slate-500">
        <span className="font-mono text-[12px] text-slate-600">{resource}</span>, as the broker serves it to each seat.
      </p>
      <dl className="mt-3 flex flex-col">
        {groups.map((g) => (
          <div key={g.label} className="grid grid-cols-[92px_minmax(0,1fr)] gap-3 border-t border-cloud-100 py-2.5 first:border-t-0">
            <dt className="pt-0.5">
              <MicroLabel>{g.label}</MicroLabel>
            </dt>
            <dd className="flex flex-wrap gap-x-3 gap-y-1.5">
              {g.list.length ? (
                g.list.map((p) => (
                  <span key={p} className="inline-flex items-center gap-1.5 text-[13px] text-navy-900">
                    <PrincipalAvatar principal={p} />
                    {principalLabel(p)}
                  </span>
                ))
              ) : (
                <span className="text-[13px] text-slate-400">nobody</span>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
