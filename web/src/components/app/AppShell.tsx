"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState, ViewTransition } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Logo } from "@/components/ui/Logo";
import { Kbd } from "./ui";
import { FlightSheet } from "./FlightSheet";
import { WhyDrawer } from "./WhyDrawer";
import { CommandPalette } from "./CommandPalette";
import { AgentRun } from "./AgentRun";
import { LetterDrawer } from "./LetterDrawer";
import { DemoGuide } from "./DemoGuide";
import { ReceiptFromUrl } from "./ReceiptFromUrl";
import { useApp } from "@/lib/store";
import { QUESTIONS, ROLES } from "@/data/app";
import { cn } from "@/lib/cn";

const NAV = [
  { href: "/app", label: "Overview" },
  { href: "/app/inbox", label: "Inbox" },
  { href: "/app/payouts", label: "Payouts" },
  { href: "/app/ledger", label: "Ledger" },
  { href: "/app/rules", label: "Rules" },
];

function useOutside<T extends HTMLElement>(open: boolean, close: () => void) {
  const ref = useRef<T>(null);
  useEffect(() => {
    if (!open) return;
    const on = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && close();
    const key = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("mousedown", on);
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("mousedown", on);
      window.removeEventListener("keydown", key);
    };
  }, [open, close]);
  return ref;
}

function RoleSwitcher() {
  const { role, setRole } = useApp();
  const [open, setOpen] = useState(false);
  const ref = useOutside<HTMLDivElement>(open, () => setOpen(false));
  const cur = ROLES.find((r) => r.id === role)!;
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex items-center gap-2 rounded-full bg-fog py-1 pl-1 pr-3 text-[14px] transition-colors hover:bg-[#e2e2dc]"
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-ink text-[11px] font-semibold text-chart">{cur.initials}</span>
        <span className="hidden sm:inline">View as {cur.name}</span>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            role="menu"
            initial={{ opacity: 0, y: -6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
            className="absolute right-0 top-11 z-50 w-[300px] origin-top-right rounded-xl bg-white p-1.5 shadow-[0_0_0_1px_#e6e6e0,0_16px_40px_rgba(18,20,23,0.12)]"
          >
            {ROLES.map((r) => (
              <button
                key={r.id}
                role="menuitemradio"
                aria-checked={r.id === role}
                type="button"
                onClick={() => {
                  setRole(r.id);
                  setOpen(false);
                }}
                className={cn("flex w-full items-start gap-3 rounded-lg p-2.5 text-left transition-colors hover:bg-chart", r.id === role && "bg-chart")}
              >
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink text-[11px] font-semibold text-chart">{r.initials}</span>
                <span>
                  <span className="block text-[14px] font-medium">{r.name}</span>
                  <span className="block text-[12.5px] leading-snug text-graphite">{r.sees}</span>
                </span>
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function StormSwitcher() {
  const [open, setOpen] = useState(false);
  const ref = useOutside<HTMLDivElement>(open, () => setOpen(false));
  const storms = [
    { name: "Storm Bram", when: "9 Dec 2025", note: "This storm" },
    { name: "Storm Éowyn", when: "24 Jan 2025", note: "Replay" },
    { name: "Storm Isha", when: "21 Jan 2024", note: "Replay" },
  ];
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex items-center gap-2.5 rounded-lg bg-fog px-3 py-[7px] text-[14px] transition-colors hover:bg-[#e2e2dc]"
      >
        <span className="font-semibold">Storm Bram</span>
        <span className="hidden text-graphite md:inline">9 Dec 2025 · DUB</span>
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
          <path d="M2 4 L5 7 L8 4" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.16 }}
            className="absolute left-0 top-11 z-50 w-[280px] rounded-xl bg-white p-1.5 shadow-[0_0_0_1px_#e6e6e0,0_16px_40px_rgba(18,20,23,0.12)]"
          >
            {storms.map((s, i) => (
              <button key={s.name} type="button" onClick={() => setOpen(false)} className={cn("flex w-full items-center justify-between rounded-lg p-2.5 text-left hover:bg-chart", i === 0 && "bg-chart")}>
                <span>
                  <span className="block text-[14px] font-medium">{s.name}</span>
                  <span className="block text-[12.5px] text-graphite">{s.when}, Dublin</span>
                </span>
                <span className="text-[12px] text-graphite">{s.note}</span>
              </button>
            ))}
            <Link href="/app/desk" className="mt-1 block rounded-lg p-2.5 text-[14px] text-front hover:bg-front-wash" onClick={() => setOpen(false)}>
              Check any airport and date…
            </Link>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { setPalette, answered, role, run, setRun } = useApp();
  const open = QUESTIONS.filter((q) => !answered[q.id]).length;
  const mine = QUESTIONS.filter((q) => !answered[q.id] && q.owner === role).length;

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette(true);
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [setPalette]);

  const desk = path.startsWith("/app/desk");
  const closeRun = useCallback(() => setRun(false), [setRun]);
  return (
    <div className={cn("flex min-h-svh flex-col bg-chart text-ink", desk && "bg-[#eef2f8]")}>
      <header className="sticky top-0 z-40 flex h-14 shrink-0 items-center gap-3 border-b border-[#e6e6e0] bg-chart/90 px-4 backdrop-blur-md md:gap-5 md:px-5">
        <Link href="/" className="flex w-auto items-center gap-2.5 md:w-[196px]" aria-label="StormCheck home">
          <ViewTransition name="brand-mark">
            <Logo className="h-[18px] w-auto" />
          </ViewTransition>
          <span className="hidden text-[16px] font-semibold tracking-[-0.01em] [font-stretch:112%] sm:inline">StormCheck</span>
        </Link>
        <StormSwitcher />
        <button
          type="button"
          onClick={() => setPalette(true)}
          className="hidden h-9 max-w-[420px] flex-1 items-center gap-2.5 rounded-lg bg-white px-3 text-[14px] text-graphite shadow-[inset_0_0_0_1px_#e2e2dc] transition-shadow hover:shadow-[inset_0_0_0_1px_#c9c9c2] md:flex"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
            <circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <path d="M9.5 9.5 L13 13" stroke="currentColor" strokeWidth="1.5" />
          </svg>
          Search flights, passengers, rules
          <span className="ml-auto">
            <Kbd>⌘K</Kbd>
          </span>
        </button>
        <div className="ml-auto flex items-center gap-4">
          <button
            type="button"
            onClick={() => setRun(true)}
            className="hidden items-center gap-2 rounded-full px-2.5 py-1.5 text-[14px] text-settled-ink transition-colors hover:bg-settled-wash lg:flex"
            title="See what StormCheck did at 09:00Z"
          >
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-settled opacity-40" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-settled" />
            </span>
            Re-checked <span className="font-mono">09:00Z</span>
          </button>
          <RoleSwitcher />
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <nav aria-label="Main" className="sticky top-14 hidden h-[calc(100svh-56px)] w-[216px] shrink-0 flex-col gap-0.5 px-3 py-4 md:flex">
          {NAV.map((n) => {
            const active = n.href === "/app" ? path === "/app" : path.startsWith(n.href);
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex items-center justify-between rounded-lg px-2.5 py-2 text-[14.5px] text-[#3e444b] transition-colors hover:bg-[#ececE6]",
                  active && "bg-[#e9e9e3] font-semibold text-ink",
                )}
              >
                {n.label}
                {n.label === "Inbox" && open > 0 && (
                  <span className={cn("min-w-5 rounded-full px-1.5 text-center text-[12px] font-semibold", mine ? "bg-review-wash text-[#7a4f00]" : "bg-fog text-graphite")}>{open}</span>
                )}
              </Link>
            );
          })}
          <div className="mx-2.5 my-3 h-px bg-[#e6e6e0]" />
          <Link
            href="/app/desk"
            className={cn("rounded-lg px-2.5 py-2 text-[14.5px] text-front transition-colors hover:bg-front-wash", desk && "bg-front-wash font-semibold")}
          >
            Judge&rsquo;s desk
          </Link>
          <div className="mt-auto rounded-lg p-2.5 text-[12.5px] leading-relaxed text-graphite">
            Drafts, never pays. Every payout waits for a person.
          </div>
        </nav>

        <main id="main" className="min-w-0 flex-1 px-4 pb-16 pt-6 md:px-7">
          {children}
        </main>
      </div>

      {/* mobile nav */}
      <nav aria-label="Main" className="fixed inset-x-3 bottom-3 z-40 flex justify-between rounded-2xl bg-ink/95 p-1.5 text-[13px] text-chart shadow-lg backdrop-blur md:hidden">
        {[...NAV.map((n) => (n.href === "/app" ? { ...n, label: "Home" } : n)), { href: "/app/desk", label: "Desk" }].map((n) => {
          const active = n.href === "/app" ? path === "/app" : path.startsWith(n.href);
          return (
            <Link key={n.href} href={n.href} className={cn("flex-1 rounded-xl py-2 text-center", active && "bg-white/15 font-semibold")}>
              {n.label}
            </Link>
          );
        })}
      </nav>

      <FlightSheet />
      <WhyDrawer />
      <CommandPalette />
      <AgentRun open={run} onClose={closeRun} />
      <LetterDrawer />
      <Suspense fallback={null}>
        <DemoGuide />
        <ReceiptFromUrl />
      </Suspense>
    </div>
  );
}
