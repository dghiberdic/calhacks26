import { Fragment } from "react";
import { cn } from "@/lib/utils";
import { ARCHITECTURE_HEADLINE } from "../copy";
import { Chip, Reveal, RevealGroup, SlideFrame } from "../ui";

type Kind = "data" | "claude" | "engine";

/** Feeds → Facts (Reader) → Policies → Run (engine) → Trace, as THREAD_JUSTIN J11 names them (plan §2). */
const STEPS: { name: string; tag: string; kind: Kind; body: string }[] = [
  { name: "Feeds", tag: "raw and messy", kind: "data", body: "METAR, schedule, OCC and tech logs, coupons, CRM, claims" },
  { name: "Facts", tag: "Reader · Claude", kind: "claude", body: "Each fact quotes its source and is re-checked against it" },
  { name: "Policies", tag: "learned · ruled", kind: "data", body: "From history, rulings, rejections and regulation. No rule editor" },
  { name: "Run", tag: "engine · deterministic", kind: "engine", body: "Cause, EU261 entitlement, liability, routing. Same input, same hash" },
  { name: "Trace", tag: "hashed commits", kind: "data", body: "Every fact, decision and LLM call. Any euro can be blamed" },
];

const CARD: Record<Kind, string> = {
  data: "bg-white/[0.035] shadow-[inset_0_0_0_1px_rgba(200,208,219,0.12)]",
  claude: "bg-white/[0.02] outline-dashed outline-2 -outline-offset-2 outline-cloud-300/70",
  engine: "bg-white/[0.08] shadow-[inset_0_0_0_2px_rgba(244,246,249,0.92),0_30px_80px_-30px_rgba(244,246,249,0.25)]",
};
const TAG = { data: "quiet", claude: "outline", engine: "bright" } as const;

function Step({ name, tag, kind, body }: { name: string; tag: string; kind: Kind; body: string }) {
  return (
    <div className={cn("flex h-full flex-col rounded-[24px] px-[26px] pb-[26px] pt-[22px]", CARD[kind])}>
      <h3 className="display-tight text-[42px] leading-none text-cloud-50">{name}</h3>
      <Chip size="sm" tone={TAG[kind]} className="mt-4 self-start">
        {tag}
      </Chip>
      <p className="mt-[18px] text-[21px] leading-[1.38] text-cloud-300 text-pretty">{body}</p>
    </div>
  );
}

const ARROW = { right: { w: 40, h: 18, d: "M2 9h36m-7-7 7 7-7 7" }, down: { w: 18, h: 34, d: "M9 2v30m-7-7 7 7 7-7" } };

function Arrow({ dir }: { dir: keyof typeof ARROW }) {
  const a = ARROW[dir];
  return (
    <svg aria-hidden="true" width={a.w} height={a.h} viewBox={`0 0 ${a.w} ${a.h}`} className="text-cloud-500">
      <path d={a.d} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const SYSTEMS = ["Altéa/Navitaire", "NetLine", "AMOS", "Accelya"];

/** THREAD_JUSTIN J11 slide 3. Who does what is drawn, not coloured: dashed = Claude, bright solid = the engine. */
export function Architecture() {
  return (
    <SlideFrame
      eyebrow="how it works"
      footer={
        <p className="flex flex-wrap items-center gap-x-3 gap-y-2 text-[25px] text-cloud-200" data-testid="sits-on-top">
          Sits on top of{" "}
          {SYSTEMS.map((name, i) => (
            <span key={name} className="inline-flex items-center">
              <span className="rounded-[8px] px-2.5 py-[5px] font-mono text-[19px] leading-none text-cloud-100 shadow-[inset_0_0_0_1.5px_rgba(200,208,219,0.22)]">{name}</span>
              {i < SYSTEMS.length - 1 ? "," : ";"}
            </span>
          ))}{" "}
          writes only parked journals.
        </p>
      }
    >
      <Reveal className="mt-10">
        <h2 className="display text-[92px] text-cloud-50" aria-label={`${ARCHITECTURE_HEADLINE}.`} data-testid="architecture-headline">
          2 Claude roles +<br /> 1 deterministic engine.
        </h2>
      </Reveal>

      <RevealGroup nested stagger={0.08} className="my-auto grid grid-cols-[1fr_52px_1fr_52px_1fr_52px_1fr_52px_1fr] pt-10">
        {STEPS.map((s, i) => (
          <Fragment key={s.name}>
            {i > 0 ? (
              <Reveal className="flex justify-center pt-[22px]">
                <Arrow dir="right" />
              </Reveal>
            ) : null}
            <Reveal>
              <Step {...s} />
            </Reveal>
          </Fragment>
        ))}

        {/* The second Claude role writes the words from what the trace holds. */}
        <Reveal className="col-start-9 flex justify-center py-3">
          <Arrow dir="down" />
        </Reveal>
        <Reveal className="col-span-5 col-start-1 flex items-center pr-10">
          <p className="display-tight text-[40px] leading-[1.15] text-cloud-50">
            <span className="block">Claude reads the mess. </span>
            <span className="block text-cloud-300">It never decides who is owed.</span>
          </p>
        </Reveal>
        <Reveal className="col-span-3 col-start-7">
          <div className={cn("grid h-full grid-cols-[auto_minmax(0,1fr)] items-start gap-x-7 rounded-[24px] px-[26px] pb-[24px] pt-[22px]", CARD.claude)}>
            <div>
              <h3 className="display-tight text-[42px] leading-none text-cloud-50">Drafts</h3>
              <Chip size="sm" tone="outline" className="mt-4">
                Drafter · Claude
              </Chip>
            </div>
            <p className="pt-1 text-[21px] leading-[1.38] text-cloud-300 text-pretty">Rights notices, journal memos and every &ldquo;why?&rdquo; answer. A number it can&rsquo;t find in the evidence gets a template instead.</p>
          </div>
        </Reveal>
      </RevealGroup>
    </SlideFrame>
  );
}
