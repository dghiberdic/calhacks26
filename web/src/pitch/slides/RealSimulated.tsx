import type { ReactNode } from "react";
import { count, eur, pct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { HONEST_FRAMING } from "../copy";
import { monthRange, proofOf, type PitchData } from "../data";
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
  const distinct = p ? new Set(p.baselineEur).size : 0;
  const learn = monthRange(p?.learn);
  const score = monthRange(p?.score);
  const runs = (values: number[] | undefined) => (values?.length ? values.map((v, i) => <Fig key={i} value={eur(v * 100)} />) : [0, 1, 2].map((i) => <Fig key={i} value={null} width="4.5ch" />));

  return (
    <Reveal className="flex flex-col rounded-[26px] bg-white/[0.07] px-[34px] pb-[26px] pt-[26px] shadow-[inset_0_0_0_2px_rgba(244,246,249,0.92)]">
      <p className="font-mono text-[17px] uppercase tracking-[0.16em] text-cloud-300">How we know</p>
      <p className="mt-4 text-[21px] text-cloud-300">Same raw documents, three runs each.</p>

      <div className="mb-7 mt-5 grid grid-cols-[auto_repeat(3,minmax(0,1fr))] items-baseline gap-x-6">
        <p className="font-mono text-[17px] text-cloud-400">Plain Claude</p>
        {runs(p?.baselineEur).map((n, i) => (
          <p key={i} className="text-[32px] text-cloud-400">
            {n}
          </p>
        ))}
        <p className="col-span-3 col-start-2 mt-1 min-h-[24px] text-[18px] text-cloud-500">{p && distinct > 1 ? `${spell(distinct)} different numbers` : null}</p>
        <p className="mt-4 font-mono text-[17px] text-cloud-50">StormCheck</p>
        {runs(p?.stormcheckEur).map((n, i) => (
          <p key={i} className="mt-4 text-[32px] text-cloud-50">
            {n}
          </p>
        ))}
        <p className="col-span-3 col-start-2 mt-1 min-h-[24px] text-[18px] text-cloud-100">
          {p?.stormcheckSameHash ? (
            <span className="inline-flex items-center gap-2.5">
              <span aria-hidden="true" className="size-[7px] rounded-full bg-cloud-50" />
              same number, same hash, every run
            </span>
          ) : null}
        </p>
      </div>

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
        {p ? (
          <p className="mt-2.5 text-[19px] text-cloud-400">
            {[
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
            ]
              .filter(Boolean)
              .map((part, i) => (
                <span key={i}>
                  {i > 0 ? " · " : ""}
                  {part}
                </span>
              ))}
          </p>
        ) : null}
        {p?.label ? <p className="mt-1.5 text-[16px] text-cloud-500">{p.label}</p> : null}
      </div>
    </Reveal>
  );
}
