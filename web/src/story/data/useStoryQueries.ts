import { useMemo } from "react";
import { useBlame, useCfo, useCurve, useFlightFile, useQuestions, useRules, useStormRun, useStorms } from "@/api/queries";
import { HERO_STORM, stormName } from "@/lib/storms";
import { aircraftType, chainFromBlame, chainFromFile, focusRow, HERO_FLIGHT, mainWindow, money, NEXT_STORM, ruleFrom, techLog, voucherQuestion } from "./model";

/** One place that asks the API for everything the story shows; sections read from it. */
export function useStoryQueries() {
  const storms = useStorms();
  const stormId = storms.data?.find((s) => s.id === HERO_STORM)?.id ?? HERO_STORM;
  const run = useStormRun(stormId);
  const focus = focusRow(run.data);
  const file = useFlightFile(focus?.flight.id ?? HERO_FLIGHT);
  const cfo = useCfo();
  const curve = useCurve("long_haul_gt3500");
  const questions = useQuestions("all");
  const rules = useRules();
  // The next storm the server lists (Herminia in the demo world); a server that lists none isn't asked for one.
  const later = (storms.data ?? []).filter((s) => s.id !== stormId && s.id.split("@")[0] === stormId?.split("@")[0] && s.id > (stormId ?? ""));
  const nextId = later.find((s) => s.id === NEXT_STORM)?.id ?? later.sort((a, b) => a.id.localeCompare(b.id))[0]?.id;
  const next = useStormRun(nextId);
  const je = file.data?.journal_preview.find((j) => j.kind === "compensation_estimate") ?? file.data?.journal_preview[0];
  const blame = useBlame(je?.id ?? (file.data ? file.data.flight.id : undefined));

  // /blame when the server has it; until it answers, nothing; if it can't, the Flight File's own chain.
  const blameSettled = !!blame.data || blame.isError || blame.fetchStatus === "idle";

  return useMemo(() => {
    const q1 = voucherQuestion(questions.data);
    const m = money(file.data, cfo.data);
    const fromBlame = chainFromBlame(blame.data);
    return {
      stormId,
      stormName: stormName(stormId),
      run: run.data,
      runError: run.error,
      focus,
      file: file.data,
      cfo: cfo.data,
      curve: curve.data,
      curveMissing: curve.isError,
      window: mainWindow(run.data?.windows),
      log: techLog(file.data, run.data),
      aircraftType: aircraftType(file.data),
      money: m,
      chain: fromBlame.length ? fromBlame : blameSettled ? chainFromFile(file.data, rules.data, m) : [],
      chainSource: fromBlame.length ? ("blame" as const) : ("flight-file" as const),
      learned: run.data?.learned ?? [],
      q1,
      questionsLoaded: !!questions.data,
      rule: ruleFrom(rules.data, q1),
      next: next.data,
      nextName: stormName(nextId),
    };
  }, [stormId, nextId, run.data, run.error, focus, file.data, cfo.data, curve.data, curve.isError, questions.data, rules.data, next.data, blame.data, blameSettled]);
}
