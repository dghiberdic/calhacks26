"use client";

import { useCallback, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { motion, AnimatePresence } from "motion/react";
import { useApp } from "@/lib/store";
import { payouts, type Payout } from "@/data/app";
import { FLIGHTS } from "@/data/scenario";
import { Card, Chip, Money } from "@/components/app/ui";
import { RollingNumber } from "@/components/motion/RollingNumber";
import { cn } from "@/lib/cn";

const PAGE_SIZE = 50;
const ease = [0.16, 1, 0.3, 1] as const;

type StatusFilter = "all" | "held" | "asked" | "not owed";
type RowStatus = Payout["status"] | "approved";

const pseudonym = (p: Payout) => `Passenger ${p.id.split("-").pop()}`;

export function PayoutsPage() {
  const searchParams = useSearchParams();
  const flightParam = searchParams.get("flight");
  const { role, openWhy } = useApp();

  const all = useMemo(() => payouts(), []);
  const heldIds = useMemo(() => all.filter((p) => p.status === "held").map((p) => p.id), [all]);

  const [flight, setFlight] = useState<string>(() => (flightParam && FLIGHTS.some((f) => f.id === flightParam) ? flightParam : "all"));
  const [status, setStatus] = useState<StatusFilter>("all");
  const [page, setPage] = useState(0);
  const [approved, setApproved] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState(false);

  const rowStatus = useCallback((p: Payout): RowStatus => (approved.has(p.id) ? "approved" : p.status), [approved]);

  const byFlight = useMemo(() => all.filter((p) => flight === "all" || p.flight === flight), [all, flight]);
  const counts = useMemo(
    () => ({
      all: byFlight.length,
      held: byFlight.filter((p) => rowStatus(p) === "held").length,
      asked: byFlight.filter((p) => rowStatus(p) === "asked").length,
      "not owed": byFlight.filter((p) => rowStatus(p) === "not owed").length,
    }),
    [byFlight, rowStatus],
  );
  const filtered = useMemo(() => byFlight.filter((p) => status === "all" || rowStatus(p) === status), [byFlight, status, rowStatus]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const pageRows = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);

  const owedCount = useMemo(() => all.filter((p) => p.status === "held" || p.status === "asked").length, [all]);
  const totalDrafted = useMemo(() => all.reduce((s, p) => (p.status === "held" || p.status === "asked" ? s + p.amount : s), 0), [all]);
  const notOwedCount = useMemo(() => all.filter((p) => p.status === "not owed").length, [all]);
  const heldCount = heldIds.filter((id) => !approved.has(id)).length;

  const canApprove = role === "claims-lead";

  const updateFlight = (v: string) => {
    setFlight(v);
    setPage(0);
  };
  const updateStatus = (v: StatusFilter) => {
    setStatus(v);
    setPage(0);
  };

  const confirmApprove = () => {
    setApproved((prev) => {
      const next = new Set(prev);
      heldIds.forEach((id) => next.add(id));
      return next;
    });
    setConfirming(false);
  };

  const kpis: { label: string; value: React.ReactNode }[] = [
    { label: "Owed passengers", value: <RollingNumber value={owedCount} trigger={null} /> },
    { label: "Total drafted", value: <RollingNumber value={totalDrafted} prefix="€" trigger={null} className="text-owed-ink" /> },
    { label: "Held for Claims Lead", value: <RollingNumber value={heldCount} trigger={null} className={heldCount === 0 ? "text-settled-ink" : "text-owed-ink"} /> },
    { label: "Not owed", value: <RollingNumber value={notOwedCount} trigger={null} className="text-graphite" /> },
  ];

  return (
    <div className="mx-auto max-w-[1280px]">
      <div>
        <h1 className="display-tight text-[30px]">Payouts</h1>
        <p className="mt-1 max-w-[62ch] text-[15px] text-graphite">
          Every passenger StormCheck priced for Storm Bram, traced back to a rule. Nothing here pays until a person approves it.
        </p>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {kpis.map((k, i) => (
          <motion.div key={k.label} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05, duration: 0.4, ease }}>
            <Card className="px-4 py-3.5">
              <p className="text-[13.5px] text-graphite">{k.label}</p>
              <p className="display-tight mt-1.5 text-[26px]">{k.value}</p>
            </Card>
          </motion.div>
        ))}
      </div>

      <Card className="mt-3 flex flex-wrap items-center justify-between gap-4 p-5">
        <div>
          <p className="text-[15px] font-semibold">{heldCount > 0 ? `${heldCount} payout${heldCount === 1 ? "" : "s"} ready for approval` : "All held payouts are approved"}</p>
          <p className="mt-0.5 text-[13.5px] text-graphite">
            {heldCount > 0 ? "Priced from the tech log and Reg. 261/2004. Approving releases them to the payments team." : "Nothing is waiting on the Claims Lead right now."}
          </p>
        </div>
        <div className="min-h-[40px]">
          <AnimatePresence mode="wait" initial={false}>
            {confirming ? (
              <motion.div
                key="confirm"
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.2, ease }}
                className="flex flex-wrap items-center gap-3 rounded-xl bg-chart p-3"
              >
                <p className="max-w-[36ch] text-[13.5px] text-graphite">
                  This sends {heldCount} payouts to the payments team&rsquo;s queue. No money moves — Payments still has to run the batch.
                </p>
                <div className="flex gap-2">
                  <button type="button" onClick={() => setConfirming(false)} className="rounded-lg px-3 py-2 text-[13.5px] text-graphite hover:bg-fog">
                    Cancel
                  </button>
                  <button type="button" onClick={confirmApprove} className="rounded-lg bg-ink px-3.5 py-2 text-[13.5px] font-semibold text-chart">
                    Confirm
                  </button>
                </div>
              </motion.div>
            ) : (
              <motion.div key="button" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}>
                {canApprove ? (
                  <button
                    type="button"
                    disabled={heldCount === 0}
                    onClick={() => setConfirming(true)}
                    className="rounded-lg bg-ink px-4 py-2.5 text-[14px] font-semibold text-chart transition-colors hover:bg-[#2a2f36] disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    Approve {heldCount} payout{heldCount === 1 ? "" : "s"}
                  </button>
                ) : (
                  <span title="Only the Claims Lead approves payouts">
                    <button type="button" disabled aria-disabled="true" className="cursor-not-allowed rounded-lg bg-ink px-4 py-2.5 text-[14px] font-semibold text-chart opacity-40">
                      Approve {heldCount} payout{heldCount === 1 ? "" : "s"}
                    </button>
                  </span>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </Card>

      <Card className="mt-3 overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5">
          <h2 className="text-[15px] font-semibold">All payouts</h2>
          <div className="flex flex-wrap items-center gap-2.5">
            <label className="sr-only" htmlFor="payouts-flight">
              Filter by flight
            </label>
            <select
              id="payouts-flight"
              value={flight}
              onChange={(e) => updateFlight(e.target.value)}
              className="rounded-lg bg-chart px-2.5 py-1.5 text-[13.5px] shadow-[inset_0_0_0_1px_#e2e2dc] outline-none focus-visible:shadow-[inset_0_0_0_1.5px_#121417]"
            >
              <option value="all">All flights</option>
              {FLIGHTS.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.id} to {f.city}
                </option>
              ))}
            </select>
            <div className="flex gap-1 rounded-lg bg-chart p-1 text-[13.5px]" role="tablist" aria-label="Filter by status">
              {(
                [
                  ["all", `All ${counts.all}`],
                  ["held", `Held ${counts.held}`],
                  ["asked", `Asked ${counts.asked}`],
                  ["not owed", `Not owed ${counts["not owed"]}`],
                ] as [StatusFilter, string][]
              ).map(([k, l]) => (
                <button
                  key={k}
                  role="tab"
                  aria-selected={status === k}
                  type="button"
                  onClick={() => updateStatus(k)}
                  className={cn("rounded-md px-3 py-1.5 transition-colors", status === k ? "bg-white font-medium shadow-[0_0_0_1px_#e6e6e0]" : "text-graphite hover:text-ink")}
                >
                  {l}
                </button>
              ))}
            </div>
          </div>
        </div>

        {role === "ops" && <p className="border-y border-[#f0f0eb] bg-chart px-5 py-2 text-[13px] text-graphite">Names hidden for Ops (GDPR).</p>}

        <div className="overflow-x-auto" data-lenis-prevent>
          <table className="w-full min-w-[720px] border-collapse text-[14px]">
            <thead>
              <tr className="text-left text-[13px] text-graphite">
                <th scope="col" className="px-5 pb-2.5 font-medium">
                  Passenger
                </th>
                <th scope="col" className="px-2 pb-2.5 font-medium">
                  Flight
                </th>
                <th scope="col" className="px-2 pb-2.5 text-right font-medium">
                  Amount
                </th>
                <th scope="col" className="px-2 pb-2.5 font-medium">
                  Status
                </th>
                <th scope="col" className="px-2 pb-2.5 font-medium">
                  Rule
                </th>
                <th scope="col" className="px-5 pb-2.5 font-medium">
                  <span className="sr-only">Why</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {pageRows.map((p) => {
                const rs = rowStatus(p);
                const name = role === "ops" ? pseudonym(p) : p.name;
                return (
                  <motion.tr
                    key={p.id}
                    initial={false}
                    animate={{ backgroundColor: rs === "approved" ? "#eef6f1" : "#ffffff" }}
                    transition={{ duration: 0.5, ease }}
                    className="border-t border-[#f0f0eb]"
                  >
                    <td className="px-5 py-3">{name}</td>
                    <td className="px-2 py-3 font-mono text-graphite">{p.flight}</td>
                    <td className="px-2 py-3 text-right">{rs === "not owed" ? <Money value={0} className="text-graphite" /> : <Money value={p.amount} className="text-owed-ink" />}</td>
                    <td className="px-2 py-3">
                      {rs === "held" && <Chip kind="technical">Held</Chip>}
                      {rs === "asked" && <Chip kind="asked" />}
                      {rs === "not owed" && <Chip kind="weather">Not owed</Chip>}
                      {rs === "approved" && <Chip kind="settled">Approved</Chip>}
                    </td>
                    <td className="px-2 py-3">
                      <span className="rounded-full bg-fog px-2 py-[2px] font-mono text-[12px] text-graphite">{p.rule}</span>
                    </td>
                    <td className="px-5 py-3 text-right">
                      {rs === "held" || rs === "approved" ? (
                        <button
                          type="button"
                          onClick={() => openWhy({ kind: "payout", flight: p.flight, passenger: name, amount: p.amount })}
                          className="text-[13px] text-front underline-offset-4 hover:underline"
                        >
                          Why?
                        </button>
                      ) : (
                        <span className="text-[13px] text-graphite">—</span>
                      )}
                    </td>
                  </motion.tr>
                );
              })}
              {pageRows.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-5 py-10 text-center text-[14px] text-graphite">
                    No payouts match this filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#f0f0eb] px-5 py-3">
          <p className="text-[13px] text-graphite">
            {filtered.length === 0
              ? "0 of 0"
              : `${safePage * PAGE_SIZE + 1}–${Math.min(filtered.length, safePage * PAGE_SIZE + PAGE_SIZE)} of ${filtered.length.toLocaleString("en-IE")}`}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={safePage <= 0}
              onClick={() => setPage((v) => Math.max(0, v - 1))}
              className="rounded-lg px-3 py-1.5 text-[13.5px] shadow-[inset_0_0_0_1px_#e2e2dc] disabled:cursor-not-allowed disabled:opacity-40"
            >
              Prev
            </button>
            <button
              type="button"
              disabled={safePage >= pageCount - 1}
              onClick={() => setPage((v) => Math.min(pageCount - 1, v + 1))}
              className="rounded-lg px-3 py-1.5 text-[13.5px] shadow-[inset_0_0_0_1px_#e2e2dc] disabled:cursor-not-allowed disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      </Card>
    </div>
  );
}
