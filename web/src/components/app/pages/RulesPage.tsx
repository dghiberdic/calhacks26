"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { useApp } from "@/lib/store";
import { QUESTIONS, type Rule } from "@/data/app";
import { Card } from "@/components/app/ui";
import { cn } from "@/lib/cn";

const ease = [0.16, 1, 0.3, 1] as const;

const SOURCE_LABEL: Record<Rule["source"], string> = { law: "Law", ruling: "Ruling", policy: "Policy", learned: "Learned" };

const REPLAY: Record<string, string> = Object.fromEntries(
  QUESTIONS.flatMap((q) => q.answers)
    .map((a) => a.rule)
    .filter((r): r is NonNullable<typeof r> => Boolean(r))
    .map((r): [string, string] => [r.id, r.replay]),
);

function statLine(rule: Rule) {
  const applied = rule.applied.toLocaleString("en-IE");
  if (rule.asked === 0) return `Applied ${applied}×`;
  return `Asked ${rule.asked === 1 ? "once" : `${rule.asked}×`} · applied ${applied}×`;
}

function RuleHistory({ rule }: { rule: Rule }) {
  const history = [...(rule.history ?? [])].sort((a, b) => b.version - a.version);
  const showCurrent = history.length === 0 || history[0]?.version !== rule.version;
  const replay = REPLAY[rule.id];
  return (
    <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.25, ease }} className="mt-4 border-t border-[#ecece7] pt-4">
      <ol className="relative">
        <span className="absolute bottom-2 left-[5px] top-2 w-px bg-[#deded8]" aria-hidden="true" />
        {showCurrent && (
          <li className="relative mb-4 pl-6">
            <span className="absolute left-0 top-1 h-[11px] w-[11px] rounded-full border-2 border-ink bg-paper" aria-hidden="true" />
            <p className="text-[13.5px]">
              <span className="font-mono font-medium">v{rule.version}</span> · current
            </p>
            <p className="text-[13px] text-graphite">
              {rule.sourceLabel} · {rule.updated}
            </p>
          </li>
        )}
        {history.map((h) => (
          <li key={h.version} className="relative mb-4 pl-6 last:mb-0">
            <span className="absolute left-[1px] top-1 h-[9px] w-[9px] rounded-full border-2 border-[#c9c9c2] bg-paper" aria-hidden="true" />
            <p className="text-[13.5px]">
              <span className="font-mono font-medium">v{h.version}</span> · {h.change}
            </p>
            <p className="text-[13px] text-graphite">
              {h.by} · {h.when}
            </p>
          </li>
        ))}
      </ol>
      <p className="text-[13px] text-graphite">Replay impact: {replay ?? `No change to ${rule.applied.toLocaleString("en-IE")} past decisions if this runs again.`}</p>
    </motion.div>
  );
}

function RuleCard({ rule, open, onToggle }: { rule: Rule; open: boolean; onToggle: () => void }) {
  const isNew = rule.updated === "just now";
  return (
    <div id={rule.id} className="scroll-mt-20">
      <Card className={cn("p-5", isNew && "bg-front-wash/40")}>
        <button type="button" onClick={onToggle} aria-expanded={open} className="flex w-full flex-col items-start gap-2 text-left">
          <div className="flex w-full flex-wrap items-center gap-2">
            <span className="font-mono text-[13px] text-graphite">
              {rule.id} · v{rule.version}
            </span>
            {isNew && <span className="rounded-full bg-front-wash px-2 py-[2px] text-[12px] font-medium text-front">New</span>}
            <span className="ml-auto text-[13px] text-graphite">{rule.updated}</span>
          </div>
          <h2 className="text-[15px] font-semibold">{rule.title}</h2>
          <p className="text-pretty text-[18px] leading-relaxed">{rule.sentence}</p>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-graphite">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-[#c9c9c2]" aria-hidden="true" />
              {SOURCE_LABEL[rule.source]}
            </span>
            <span>· {rule.sourceLabel}</span>
            <span>· Scope: {rule.scope}</span>
          </div>
          <p className="text-[13px] text-graphite">{statLine(rule)}</p>
        </button>
        <AnimatePresence initial={false}>{open && <RuleHistory rule={rule} />}</AnimatePresence>
      </Card>
    </div>
  );
}

export function RulesPage() {
  const { rules } = useApp();
  const [openIds, setOpenIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    const hash = window.location.hash.slice(1);
    if (!hash) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- sync the deep link's rule open once, on mount
    setOpenIds((s) => new Set(s).add(hash));
    const el = document.getElementById(hash);
    if (el) requestAnimationFrame(() => el.scrollIntoView({ block: "start", behavior: "smooth" }));
  }, []);

  const toggle = (id: string) =>
    setOpenIds((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="mx-auto max-w-[1280px]">
      <h1 className="display-tight text-[30px]">Rules</h1>
      <p className="mt-1 max-w-[62ch] text-[15px] text-graphite">Every rule StormCheck applies, versioned. Answer a question in the Inbox and it lands here first.</p>
      <div className="mt-6 flex max-w-[760px] flex-col gap-3">
        {rules.map((r) => (
          <RuleCard key={r.id} rule={r} open={openIds.has(r.id)} onToggle={() => toggle(r.id)} />
        ))}
      </div>
    </div>
  );
}
