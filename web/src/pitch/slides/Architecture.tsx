import { Fragment, type ReactNode } from "react";
import { motion, useReducedMotion } from "motion/react";
import { cn } from "@/lib/utils";
import { ARCHITECTURE_HEADLINE } from "../copy";
import { EASE_OUT } from "../stage";
import { Chip, Reveal, SlideFrame } from "../ui";

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

/**
 * The flow builds left to right when the slide opens: a card, then the arrow out of it draws (shaft, then
 * head), then the next card. Seconds after the slide arrives.
 */
const FIRST_CARD = 0.3;
const CARD_EVERY = 0.34;
const cardAt = (i: number) => FIRST_CARD + i * CARD_EVERY;
const arrowAt = (i: number) => cardAt(i - 1) + 0.2; // the arrow into step i
const DOWN_AT = cardAt(STEPS.length - 1) + 0.25; // Trace → Drafts
const DRAFTS_AT = DOWN_AT + 0.3;
const LINE_AT = DRAFTS_AT + 0.25;

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

const ARROW = {
  right: { w: 40, h: 18, shaft: "M2 9h36", head: "M31 2l7 7-7 7" },
  down: { w: 18, h: 34, shaft: "M9 2v30", head: "M2 25l7 7 7-7" },
};

/** An arrow that draws itself at `at` seconds: the shaft, then the head. Still under reduced motion. */
function Arrow({ dir, at }: { dir: keyof typeof ARROW; at: number }) {
  const reduce = useReducedMotion();
  const a = ARROW[dir];
  const still = { duration: 0 };
  return (
    <svg aria-hidden="true" width={a.w} height={a.h} viewBox={`0 0 ${a.w} ${a.h}`} className="overflow-visible text-cloud-400">
      <motion.path
        d={a.shaft}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        initial={reduce ? false : { pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 1 }}
        transition={reduce ? still : { pathLength: { delay: at, duration: 0.32, ease: "easeInOut" }, opacity: { delay: at, duration: 0.01 } }}
      />
      <motion.path
        d={a.head}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={reduce ? false : { pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 1 }}
        transition={reduce ? still : { pathLength: { delay: at + 0.26, duration: 0.18, ease: "easeOut" }, opacity: { delay: at + 0.26, duration: 0.01 } }}
      />
    </svg>
  );
}

/** A piece of the flow that rises in on its own beat. */
function Beat({ at, className, children }: { at: number; className?: string; children: ReactNode }) {
  const reduce = useReducedMotion();
  return (
    <motion.div className={className} initial={reduce ? false : { opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: at, duration: 0.5, ease: EASE_OUT }}>
      {children}
    </motion.div>
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

      <div className="my-auto grid grid-cols-[1fr_52px_1fr_52px_1fr_52px_1fr_52px_1fr] pt-10" data-testid="architecture-flow">
        {STEPS.map((s, i) => (
          <Fragment key={s.name}>
            {i > 0 ? (
              <div className="flex justify-center pt-[22px]">
                <Arrow dir="right" at={arrowAt(i)} />
              </div>
            ) : null}
            <Beat at={cardAt(i)}>
              <Step {...s} />
            </Beat>
          </Fragment>
        ))}

        {/* The second Claude role writes the words from what the trace holds. */}
        <div className="col-start-9 flex justify-center py-3">
          <Arrow dir="down" at={DOWN_AT} />
        </div>
        <Beat at={LINE_AT} className="col-span-5 col-start-1 flex items-center pr-10">
          <p className="display-tight text-[40px] leading-[1.15] text-cloud-50">
            <span className="block">Claude reads the mess. </span>
            <span className="block text-cloud-300">It never decides who is owed.</span>
          </p>
        </Beat>
        <Beat at={DRAFTS_AT} className="col-span-3 col-start-7">
          <div className={cn("grid h-full grid-cols-[auto_minmax(0,1fr)] items-start gap-x-7 rounded-[24px] px-[26px] pb-[24px] pt-[22px]", CARD.claude)}>
            <div>
              <h3 className="display-tight text-[42px] leading-none text-cloud-50">Drafts</h3>
              <Chip size="sm" tone="outline" className="mt-4">
                Drafter · Claude
              </Chip>
            </div>
            <p className="pt-1 text-[21px] leading-[1.38] text-cloud-300 text-pretty">Rights notices, journal memos and every &ldquo;why?&rdquo; answer. A number it can&rsquo;t find in the evidence gets a template instead.</p>
          </div>
        </Beat>
      </div>
    </SlideFrame>
  );
}
