"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";
import { useApp } from "@/lib/store";
import { FLIGHTS } from "@/data/scenario";
import { cn } from "@/lib/cn";

type Item = { id: string; group: string; label: string; hint?: string; run: () => void };

export function CommandPalette() {
  const { palette, setPalette, openSheet, rules } = useApp();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  const items = useMemo<Item[]>(() => {
    const go = (href: string) => () => router.push(href);
    const all: Item[] = [
      ...FLIGHTS.map((f) => ({ id: f.id, group: "Flights", label: `${f.id} to ${f.city}`, hint: `${f.sched}Z · ${f.verdict === "technical" ? "owed" : "weather"}`, run: () => openSheet(f.id) })),
      ...rules.map((r) => ({ id: r.id, group: "Rules", label: `${r.id} ${r.title}`, hint: `v${r.version}`, run: go(`/app/rules#${r.id}`) })),
      { id: "p-inbox", group: "Go to", label: "Inbox", run: go("/app/inbox") },
      { id: "p-payouts", group: "Go to", label: "Payouts", run: go("/app/payouts") },
      { id: "p-ledger", group: "Go to", label: "Ledger", run: go("/app/ledger") },
      { id: "p-desk", group: "Go to", label: "Judge’s desk", hint: "any airport, any date", run: go("/app/desk") },
    ];
    const t = q.trim().toLowerCase();
    return t ? all.filter((x) => (x.label + " " + (x.hint ?? "")).toLowerCase().includes(t)) : all.slice(0, 9);
  }, [q, rules, router, openSheet]);

  useEffect(() => {
    if (palette) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reset the query each time the palette opens
      setQ("");
      setI(0);
      setTimeout(() => input.current?.focus(), 20);
    }
  }, [palette]);

  const close = () => setPalette(false);
  const pick = (it?: Item) => {
    if (!it) return;
    close();
    it.run();
  };

  return (
    <AnimatePresence>
      {palette && (
        <>
          <motion.div key="cp-s" className="fixed inset-0 z-[70] bg-ink/20" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={close} />
          <motion.div
            key="cp"
            role="dialog"
            aria-modal="true"
            aria-label="Search"
            initial={{ opacity: 0, y: -8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -6, scale: 0.98 }}
            transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
            className="fixed inset-x-3 top-[12svh] z-[70] mx-auto max-w-[600px] overflow-hidden rounded-2xl bg-white shadow-[0_0_0_1px_#e6e6e0,0_30px_80px_rgba(18,20,23,0.25)]"
          >
            <input
              ref={input}
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setI(0);
              }}
              onKeyDown={(e) => {
                if (e.key === "Escape") close();
                if (e.key === "ArrowDown") (e.preventDefault(), setI((v) => Math.min(items.length - 1, v + 1)));
                if (e.key === "ArrowUp") (e.preventDefault(), setI((v) => Math.max(0, v - 1)));
                if (e.key === "Enter") pick(items[i]);
              }}
              placeholder="Search flights, rules, pages"
              aria-label="Search"
              className="w-full border-b border-[#ecece7] bg-transparent px-5 py-4 text-[16px] outline-none placeholder:text-graphite"
            />
            <ul className="max-h-[50svh] overflow-y-auto p-1.5" role="listbox" data-lenis-prevent>
              {items.length === 0 && <li className="px-4 py-6 text-center text-[14px] text-graphite">Nothing matches “{q}”.</li>}
              {items.map((it, k) => (
                <li key={it.id} role="option" aria-selected={k === i}>
                  <button
                    type="button"
                    onMouseEnter={() => setI(k)}
                    onClick={() => pick(it)}
                    className={cn("flex w-full items-center justify-between rounded-lg px-3.5 py-2.5 text-left text-[14.5px]", k === i && "bg-chart")}
                  >
                    <span>
                      <span className="mr-3 text-[12px] text-graphite">{it.group}</span>
                      {it.label}
                    </span>
                    {it.hint && <span className="text-[12.5px] text-graphite">{it.hint}</span>}
                  </button>
                </li>
              ))}
            </ul>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
