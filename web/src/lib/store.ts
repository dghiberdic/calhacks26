"use client";

import { create } from "zustand";
import { QUESTIONS, RULES, type Role, type Rule } from "@/data/app";

export type WhyTarget = { kind: "provision" | "payout" | "exposure"; flight: string; passenger?: string; amount: number };

type State = {
  role: Role;
  setRole: (r: Role) => void;
  sheet: string | null; // flight id
  openSheet: (id: string | null) => void;
  why: WhyTarget | null;
  openWhy: (t: WhyTarget | null) => void;
  palette: boolean;
  setPalette: (v: boolean) => void;
  run: boolean;
  setRun: (v: boolean) => void;
  letter: { name: string; flight: string; amount: number } | null;
  openLetter: (l: { name: string; flight: string; amount: number } | null) => void;
  answered: Record<string, string>; // question id → answer id
  answer: (q: string, a: string) => void;
  rules: Rule[];
  addRule: (r: Rule) => void;
};

export const useApp = create<State>((set) => ({
  role: "claims-lead",
  setRole: (role) => set({ role }),
  sheet: null,
  openSheet: (sheet) => set({ sheet }),
  why: null,
  openWhy: (why) => set({ why }),
  palette: false,
  setPalette: (palette) => set({ palette }),
  run: false,
  setRun: (run) => set({ run }),
  letter: null,
  openLetter: (letter) => set({ letter }),
  answered: {},
  answer: (q, a) =>
    set((s) => {
      const question = QUESTIONS.find((x) => x.id === q);
      const ans = question?.answers.find((x) => x.id === a);
      const rules = ans?.rule && !s.rules.some((r) => r.id === ans.rule!.id)
        ? [
            {
              id: ans.rule.id,
              version: ans.rule.version,
              title: question!.title.replace(/\?$/, ""),
              sentence: ans.rule.sentence,
              source: "ruling" as const,
              sourceLabel: `${question!.owner === "legal" ? "Legal" : question!.owner === "controller" ? "Controller" : "Claims Lead"} ruling, ${question!.id}`,
              scope: ans.rule.scope,
              applied: ans.rule.settles ?? 0,
              asked: 1,
              updated: "just now",
            },
            ...s.rules,
          ]
        : s.rules;
      return { answered: { ...s.answered, [q]: a }, rules };
    }),
  rules: RULES,
  addRule: (r) => set((s) => ({ rules: [r, ...s.rules] })),
}));
