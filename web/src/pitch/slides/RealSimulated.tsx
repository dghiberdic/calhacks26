import type { ReactNode } from "react";
import { motion, useReducedMotion } from "motion/react";
import { count, eur, pct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { HONEST_FRAMING } from "../copy";
import { monthRange, proofOf, type PitchData, type Proof } from "../data";
import { EASE_OUT } from "../stage";
import { Fig, Num, Reveal, RevealGroup, SlideFrame } from "../ui";

const WORDS = ["no", "one", "two", "three", "four", "five", "six"];
const spell = (n: number) => WORDS[n] ?? String(n);

/** THREAD_JUSTIN J11 slide 4: what is real, what is simulated, and how we know it works (plan §1.1, §5). */
export function RealSimulated({ data }: { data: PitchData }) {
  const rc = (data.run?.real_context ?? {}) as Record<string, unknown>;
  const departures = rc.eurocontrol_departures !== undefined ? count(Number(rc.eurocontrol_departures)) : null;
  const normal = rc.normal_departures !== undefined ? String(rc.normal_departures) : null;

  return (
    <SlideFrame eyebrow="real · simulated · how we know">
      <Reveal className="mt-10">
        <h2 className="display text-[96px] text-cloud-50">What&rsquo;s real, and how we know.</h2>
      </Reveal>
      <Reveal className="mt-6 max-w-[1500px]">
        <p className="text-[30px] leading-[1.38] text-cloud-200 text-pretty" data-testid="honest-framing">
          {HONEST_FRAMING}
        </p>
      </Reveal>

      <RevealGroup nested stagger={0.09} className="mt-auto grid grid-cols-[1fr_1fr_1.5fr] gap-6 pt-10">
        <Column title="Real" mark="solid">
          <Item title="Weather at Dublin">METAR from Iowa Environmental Mesonet and NOAA</Item>
          <Item title="Airport traffic">
            {departures ? (
              <>
                Eurocontrol: <Num>{departures}</Num> departures that day{normal ? <> vs {normal} normal</> : null}
              </>
            ) : (
              "Eurocontrol airport traffic"
            )}
          </Item>
          <Item title="Distances">OurAirports, great circle per Art. 7(4)</Item>
          <Item title="EU law">EU261 and CJEU case law</Item>
        </Column>
        <Column title="Simulated" mark="dashed">
          <Item title="Northstar Air">A fictional Irish carrier, about 65 aircraft</Item>
          <Item title="Its logs">Schedule, OCC, tech and MCC logs, coupons, CRM</Item>
          <Item title="Passengers and claims">Played by LLM personas; a person can take over</Item>
          <Item title="The mess">Planted errors, every one in an answer key</Item>
        </Column>
        <Proof data={data} />
      </RevealGroup>
    </SlideFrame>
  );
}

function Column({ title, mark, children }: { title: string; mark: "solid" | "dashed"; children: ReactNode }) {
  return (
    <Reveal className="rounded-[26px] bg-white/[0.035] px-[30px] pb-[28px] pt-[26px] shadow-[inset_0_0_0_1px_rgba(200,208,219,0.1)]">
      <p className="flex items-center gap-3 font-mono text-[17px] uppercase tracking-[0.16em] text-cloud-300">
        <span aria-hidden="true" className={cn("size-[14px] rounded-full", mark === "solid" ? "bg-cloud-50" : "outline-dashed outline-2 -outline-offset-2 outline-cloud-300")} />
        {title}
      </p>
      <ul className="mt-6 flex flex-col gap-[20px]">{children}</ul>
    </Reveal>
  );
}

function Item({ title, children }: { title: string; children: ReactNode }) {
  return (
    <li>
      <p className="text-[25px] leading-tight text-cloud-50">{title}</p>
      <p className="mt-1.5 text-[19px] leading-snug text-cloud-400 text-balance">{children}</p>
    </li>
  );
}

/** "Plain Claude, 3 runs: €a / €b / €c. StormCheck: €34,650 ×3, same hash." All from GET /eval. */
function Proof({ data }: { data: PitchData }) {
  const p = proofOf(data.evalReport);
  const learn = monthRange(p?.learn);
  const score = monthRange(p?.score);
  // No eval served (yet): say how it is measured, and claim no result.
  const noNumbers = !p && !!data.evalFailed;

  if (noNumbers) {
    // The method, from the plan (§5); results appear once GET /eval answers.
    return (
      <Reveal className="rounded-[26px] bg-white/[0.07] px-[34px] pb-[28px] pt-[26px] shadow-[inset_0_0_0_2px_rgba(244,246,249,0.92)]">
        <p className="font-mono text-[17px] uppercase tracking-[0.16em] text-cloud-300">How we know</p>
        <ul className="mt-6 flex flex-col gap-[20px]">
          <Item title="Storms it never saw">Learns on Jul 2023 – Dec 2024, scored on Jan – Jun 2025, &Eacute;owyn included</Item>
          <Item title="An answer key">Written from the generator&rsquo;s ground truth, never from the engine</Item>
          <Item title="Against plain Claude">Same raw documents, three runs each, compared to the euro and the hash</Item>
          <Item title="Replay">
            Every decision is a hashed commit; <span className="font-mono text-[17px] text-cloud-300">make verify</span> recomputes it offline
          </Item>
        </ul>
      </Reveal>
    );
  }

  return (
    <Reveal className="flex flex-col rounded-[26px] bg-white/[0.07] px-[34px] pb-[26px] pt-[26px] shadow-[inset_0_0_0_2px_rgba(244,246,249,0.92)]">
      <p className="font-mono text-[17px] uppercase tracking-[0.16em] text-cloud-300">How we know</p>
      <Runs proof={p} />

      <div className="mt-auto border-t border-white/15 pt-5">
        <p className="text-[21px] leading-[1.4] text-cloud-200">
          {learn && score ? (
            <>
              Learned on {learn}, scored on {score}, including &Eacute;owyn: a storm it never saw.
            </>
          ) : (
            <>Scored on storms it never saw, including &Eacute;owyn.</>
          )}{" "}
          Answer key from ground truth, never from the engine.
        </p>
        {p ? <Scorecard proof={p} /> : null}
        {p?.label ? <p className="mt-1.5 text-[16px] text-cloud-500">{p.label}</p> : null}
      </div>
    </Reveal>
  );
}

/** The runs build like a keynote: plain Claude's three land one at a time, then StormCheck's three together. */
const PLAIN_AT = 0.95;
const RUN_EVERY = 0.3;
const OURS_AT = PLAIN_AT + 3 * RUN_EVERY + 0.45;

/** A figure that lands on its own beat (seconds after the slide opens); in place at once with reduced motion. */
function Land({ at, children, className }: { at: number; children: ReactNode; className?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.span className={cn("inline-block", className)} initial={reduce ? false : { opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: at, duration: 0.45, ease: EASE_OUT }}>
      {children}
    </motion.span>
  );
}

/** Three runs each on the same documents: plain Claude's numbers differ, StormCheck's match to the hash. */
function Runs({ proof }: { proof: Proof | undefined }) {
  const distinct = proof ? new Set(proof.baselineEur).size : 0;
  const cells = (values: number[] | undefined, className: string, at: (i: number) => number) =>
    (values?.length ? values.map((v) => eur(v * 100)) : [null, null, null]).map((v, i) => (
      <p key={i} className={className}>
        <Land at={at(i)}>
          <Fig value={v} width="4.5ch" />
        </Land>
      </p>
    ));
  return (
    <>
      <p className="mt-4 text-[21px] text-cloud-300">Same raw documents, three runs each.</p>
      <div className="mb-7 mt-5 grid grid-cols-[auto_repeat(3,minmax(0,1fr))] items-baseline gap-x-6" data-testid="proof-runs">
        <p className="font-mono text-[17px] text-cloud-400">Plain Claude</p>
        {cells(proof?.baselineEur, "text-[32px] text-cloud-400", (i) => PLAIN_AT + i * RUN_EVERY)}
        <p className="col-span-3 col-start-2 mt-1 min-h-[24px] text-[18px] text-cloud-500">{distinct > 1 ? <Land at={PLAIN_AT + 3 * RUN_EVERY}>{`${spell(distinct)} different numbers`}</Land> : null}</p>
        <p className="mt-4 font-mono text-[17px] text-cloud-50">StormCheck</p>
        {cells(proof?.stormcheckEur, "mt-4 text-[32px] text-cloud-50", () => OURS_AT)}
        <p className="col-span-3 col-start-2 mt-1 min-h-[24px] text-[18px] text-cloud-100">
          {proof?.stormcheckSameHash ? (
            <Land at={OURS_AT + 0.35} className="inline-flex items-center gap-2.5">
              <span aria-hidden="true" className="size-[7px] rounded-full bg-cloud-50" />
              same number, same hash, every run
            </Land>
          ) : null}
        </p>
      </div>
    </>
  );
}

/** "98.7% straight-through · 11 of 12 miscodes caught · 0 repeat questions", whichever the eval reports. */
function Scorecard({ proof: p }: { proof: Proof }) {
  const parts = [
    p.straightThrough !== undefined ? (
      <>
        <Num className="text-cloud-100">{pct(p.straightThrough, p.straightThrough < 0.995 ? 1 : 0)}</Num> straight-through
      </>
    ) : null,
    p.miscodes ? (
      <>
        <Num className="text-cloud-100">{count(p.miscodes.caught)}</Num> of <Num>{count(p.miscodes.total)}</Num> miscodes caught
      </>
    ) : null,
    p.repeatQuestions !== undefined ? (
      <>
        <Num className="text-cloud-100">{count(p.repeatQuestions)}</Num> repeat questions
      </>
    ) : null,
  ].filter(Boolean);
  return (
    <p className="mt-2.5 text-[19px] text-cloud-400">
      {parts.map((part, i) => (
        <span key={i}>
          {i > 0 ? " · " : ""}
          {part}
        </span>
      ))}
    </p>
  );
}
