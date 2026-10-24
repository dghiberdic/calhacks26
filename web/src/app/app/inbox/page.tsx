"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "motion/react";
import { QUESTIONS, ROLES, payouts, type Question } from "@/data/app";
import { useApp } from "@/lib/store";
import { dialogOpen } from "@/lib/useDialog";
import { Card, Kbd } from "@/components/app/ui";
import { RollingNumber } from "@/components/motion/RollingNumber";
import { cn } from "@/lib/cn";

const ease = [0.16, 1, 0.3, 1] as const;

function RulePreview({ q, answerId }: { q: Question; answerId: string }) {
  const a = q.answers.find((x) => x.id === answerId);
  if (!a?.rule) return null;
  const [before, after] = a.rule.sentence.split(a.rule.highlight);
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.3, ease }} className="rounded-xl bg-chart p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-[14px] font-semibold">
          This becomes rule <span className="font-mono">{a.rule.id} v{a.rule.version}</span>
        </p>
        <p className="text-[13px] text-graphite">{a.rule.replay}</p>
      </div>
      <p className="mt-2 text-[17px] leading-relaxed">
        {before}
        <mark className="rounded-[3px] bg-settled-wash px-1 text-settled-ink">{a.rule.highlight}</mark>
        {after}
      </p>
      <p className="mt-2 text-[13px] text-graphite">Scope: {a.rule.scope}. Every field comes from your answer; nothing is guessed.</p>
    </motion.div>
  );
}

const SETTLED = payouts()
  .filter((p) => p.flight === "NS31" && p.name !== "Aoife Byrne")
  .slice(0, 6)
  .map((p, i) => ({ name: p.name, outcome: i % 4 === 2 ? "Offset, signed" : "No offset", amount: i % 4 === 2 ? 300 : 600 }));

function Resolved({ q, answerId, onNext }: { q: Question; answerId: string; onNext: () => void }) {
  const a = q.answers.find((x) => x.id === answerId)!;
  const applied = a.rule?.settles ?? 0;
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, ease }} className="flex flex-col gap-6">
      <div className="flex items-center gap-3 text-settled-ink">
        <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
          <circle cx="11" cy="11" r="10" fill="#dfefe7" />
          <path d="M6.5 11.5 L9.5 14.5 L15.5 8" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="ink-path" pathLength={1} />
        </svg>
        <span className="text-[15px] font-semibold">Ruled: {a.label}</span>
      </div>
      {a.rule ? (
        <>
          <div className="flex items-baseline gap-4">
            <RollingNumber value={applied} className="display text-[72px]" trigger={null} />
            <p className="max-w-[30ch] text-[17px] leading-snug text-graphite">open cases settled with {a.rule.id} v1. StormCheck won&rsquo;t ask this again.</p>
          </div>
          {q.id === "Q-12" && (
            <ul className="divide-y divide-[#f0f0eb] rounded-xl bg-chart px-4 text-[14px]">
              {SETTLED.map((c, i) => (
                <motion.li
                  key={c.name}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.5 + i * 0.12, duration: 0.35, ease }}
                  className="flex items-center justify-between gap-3 py-2.5"
                >
                  <span>{c.name}</span>
                  <span className="text-graphite">{c.outcome}</span>
                  <span className="figure">€{c.amount}</span>
                  <span className="rounded-full bg-settled-wash px-2 py-[2px] font-mono text-[12px] text-settled-ink">R-7 v1</span>
                </motion.li>
              ))}
              <li className="py-2.5 text-[13px] text-graphite">and 25 more, none of them asked</li>
            </ul>
          )}
          <p className="text-[15px]">
            Saved as <span className="font-mono">{a.rule.id} v1</span>.{" "}
            <Link href={`/app/rules#${a.rule.id}`} className="text-front underline-offset-4 hover:underline">
              See it in Rules
            </Link>
          </p>
        </>
      ) : (
        <p className="text-[16px] text-graphite">Applied to this case only. No rule was created, so a similar case will come back to you.</p>
      )}
      <div>
        <button type="button" onClick={onNext} className="rounded-lg bg-ink px-4 py-2.5 text-[14px] font-semibold text-chart">
          Next question
        </button>
      </div>
    </motion.div>
  );
}

export default function Inbox() {
  const { role, setRole, answered, answer } = useApp();
  const [scope, setScope] = useState<"mine" | "all">("all");
  const list = useMemo(() => QUESTIONS.filter((q) => scope === "all" || q.owner === role), [scope, role]);
  const [sel, setSel] = useState<string>(QUESTIONS[0].id);
  const [pick, setPick] = useState<Record<string, string>>({});
  const [custom, setCustom] = useState("");
  const q = QUESTIONS.find((x) => x.id === sel)!;
  const owner = ROLES.find((r) => r.id === q.owner)!;
  const canAnswer = role === q.owner;
  const chosen = pick[q.id] ?? q.answers[0].id;
  const done = answered[q.id];

  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      const typing = !!el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable);
      if (done || !canAnswer || dialogOpen()) return;
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
        if (chosen === "custom" && !custom.trim()) return;
        e.preventDefault();
        answer(q.id, chosen);
        return;
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
      const n = Number(e.key);
      if (n >= 1 && n <= q.answers.length) setPick((p) => ({ ...p, [q.id]: q.answers[n - 1].id }));
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [q, done, canAnswer, chosen, custom, answer]);

  const next = () => {
    const rest = QUESTIONS.filter((x) => !answered[x.id] && x.id !== q.id);
    if (rest[0]) setSel(rest[0].id);
  };

  return (
    <div className="mx-auto grid max-w-[1280px] grid-cols-1 gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
      <section aria-label="Questions" className="flex flex-col gap-2">
        <div className="flex items-end justify-between px-1">
          <h1 className="display-tight text-[30px]">Inbox</h1>
          <div className="flex gap-1 rounded-lg bg-[#ebebe5] p-1 text-[13px]" role="tablist" aria-label="Whose questions">
            {(["all", "mine"] as const).map((s) => (
              <button key={s} type="button" role="tab" aria-selected={scope === s} onClick={() => setScope(s)} className={cn("rounded-md px-2.5 py-1", scope === s ? "bg-white font-medium shadow-[0_0_0_1px_#e6e6e0]" : "text-graphite")}>
                {s === "all" ? "Everyone" : "Mine"}
              </button>
            ))}
          </div>
        </div>
        <p className="px-1 pb-2 text-[14px] text-graphite">StormCheck handled the rest. These are the cases where the evidence disagrees or there&rsquo;s no precedent.</p>
        {list.length === 0 && <p className="rounded-xl bg-white p-4 text-[14px] text-graphite shadow-[0_0_0_1px_#e6e6e0]">Nothing waiting on you.</p>}
        {list.map((x) => {
          const isSel = x.id === sel;
          const isDone = !!answered[x.id];
          const own = ROLES.find((r) => r.id === x.owner)!;
          return (
            <button
              key={x.id}
              type="button"
              onClick={() => setSel(x.id)}
              aria-current={isSel}
              className={cn(
                "rounded-xl p-4 text-left transition-[background,box-shadow]",
                isSel ? "bg-white shadow-[0_0_0_1.5px_#121417]" : "hover:bg-white/70",
                isDone && "opacity-60",
              )}
            >
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[14.5px] font-semibold leading-snug">{x.title}</span>
                <span className={cn("shrink-0 font-mono text-[13px]", isDone ? "text-settled-ink" : x.confidence === null ? "text-graphite" : "text-review-ink")}>
                  {isDone ? "ruled" : x.confidence === null ? "—" : `${x.confidence}%`}
                </span>
              </div>
              <p className="mt-1 text-[13px] text-graphite">
                <span className="font-mono">{x.flight}</span> · {own.name}
                {x.held ? ` · €${x.held.toLocaleString("en-IE")} held` : ""}
              </p>
            </button>
          );
        })}
      </section>

      <Card className="min-h-[640px] p-6 md:p-8">
        <AnimatePresence mode="wait">
          <motion.div key={q.id + (done ? "-done" : "")} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.3, ease }} className="flex flex-col gap-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-[14px] text-graphite">
                {canAnswer ? (
                  <>
                    To you, the {owner.name}. {q.why}
                  </>
                ) : (
                  <>
                    Routed to the {owner.name}. {q.why}
                  </>
                )}
              </p>
              <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[13px]", q.reason === "needs approval" ? "bg-fog text-ink" : "bg-review-wash text-[#7a4f00]")}>
                <span className={cn("h-1.5 w-1.5 rounded-full", q.reason === "needs approval" ? "bg-ink" : "bg-review")} />
                {q.confidence !== null && `${q.confidence}% · `}
                {q.reason}
              </span>
            </div>

            {done ? (
              <Resolved q={q} answerId={done} onNext={next} />
            ) : (
              <>
                <h2 className="max-w-[34ch] text-[clamp(22px,2.2vw,30px)] font-semibold leading-[1.25] tracking-[-0.015em] [font-stretch:106%]">{q.question}</h2>

                <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                  {q.evidence.map((e, i) => (
                    <motion.figure key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 * i + 0.1, duration: 0.35, ease }} className="m-0 rounded-xl bg-[#f7f7f4] p-4">
                      <figcaption className="mb-2 text-[13px] text-graphite">
                        {e.source}
                        {e.when && <span className="font-mono"> · {e.when}</span>}
                      </figcaption>
                      <p className={cn("text-[14px] leading-relaxed", e.mono && "font-mono text-[12.5px]")}>{e.text}</p>
                    </motion.figure>
                  ))}
                </div>

                <fieldset disabled={!canAnswer} className="flex flex-col gap-2.5">
                  <legend className="mb-2.5 text-[14px] font-semibold">Your answer</legend>
                  {q.answers.map((a, i) => {
                    const on = chosen === a.id;
                    return (
                      <label
                        key={a.id}
                        className={cn(
                          "grid cursor-pointer grid-cols-[20px_1fr_auto] items-center gap-3 rounded-xl px-4 py-3.5 transition-shadow",
                          on ? "bg-white shadow-[0_0_0_1.5px_#121417]" : "shadow-[0_0_0_1px_#e2e2dc] hover:shadow-[0_0_0_1px_#b9b9b2]",
                          !canAnswer && "cursor-not-allowed opacity-60",
                        )}
                      >
                        <input type="radio" name={q.id} checked={on} onChange={() => setPick((p) => ({ ...p, [q.id]: a.id }))} className="accent-[#121417]" />
                        <span className="text-[15px]">
                          <span className="font-semibold">{a.label}</span> <span className="text-graphite">{a.effect}</span>
                        </span>
                        <Kbd>{i + 1}</Kbd>
                      </label>
                    );
                  })}
                  {chosen === "custom" && (
                    <textarea
                      value={custom}
                      onChange={(e) => setCustom(e.target.value)}
                      rows={3}
                      placeholder="Write the ruling the way you'd say it to a new hire."
                      aria-label="Your ruling"
                      className="rounded-xl bg-[#f7f7f4] p-4 text-[15px] outline-none focus:shadow-[0_0_0_1.5px_#121417]"
                    />
                  )}
                </fieldset>

                <AnimatePresence>{canAnswer && <RulePreview key={chosen} q={q} answerId={chosen} />}</AnimatePresence>

                <div className="mt-auto flex flex-wrap items-center gap-2.5">
                  {canAnswer ? (
                    <>
                      <button type="button" onClick={() => answer(q.id, chosen)} disabled={chosen === "custom" && !custom.trim()} className="rounded-lg bg-ink px-4 py-2.5 text-[14px] font-semibold text-chart disabled:opacity-40">
                        {q.answers.find((a) => a.id === chosen)?.rule ? `Rule and save ${q.answers.find((a) => a.id === chosen)!.rule!.id}` : "Rule on this case"}
                      </button>
                      <span className="text-[13px] text-graphite">
                        <Kbd>1</Kbd>–<Kbd>{q.answers.length}</Kbd> to pick, <Kbd>⌘</Kbd>
                        <Kbd>↵</Kbd> to rule
                      </span>
                    </>
                  ) : (
                    <button type="button" onClick={() => setRole(q.owner)} className="rounded-lg bg-chart px-4 py-2.5 text-[14px] font-medium shadow-[inset_0_0_0_1px_#c9c9c2]">
                      View as {owner.name} to answer
                    </button>
                  )}
                </div>
              </>
            )}
          </motion.div>
        </AnimatePresence>
      </Card>
    </div>
  );
}
