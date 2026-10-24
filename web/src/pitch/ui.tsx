import type { ReactNode } from "react";
import { motion, useReducedMotion, type Variants } from "motion/react";
import { Logo } from "@/components/brand/Logo";
import { cn } from "@/lib/utils";
import { EASE_OUT } from "./stage";

// ---------- motion ----------
const ITEM: Variants = { hidden: { opacity: 0, y: 16 }, show: { opacity: 1, y: 0, transition: { duration: 0.55, ease: EASE_OUT } } };
const ITEM_STILL: Variants = { hidden: { opacity: 1 }, show: { opacity: 1 } };

/**
 * A group whose children rise into place one after another when the slide arrives.
 * `nested` groups inherit the parent's state, so a card grid staggers inside the slide's own stagger.
 */
export function RevealGroup({ children, className, stagger = 0.06, delay = 0.04, nested, as = "div" }: { children: ReactNode; className?: string; stagger?: number; delay?: number; nested?: boolean; as?: "div" | "span" | "ul" | "ol" }) {
  const reduce = useReducedMotion();
  const variants: Variants = { hidden: {}, show: { transition: reduce ? {} : { staggerChildren: stagger, delayChildren: delay } } };
  const Tag = as === "ul" ? motion.ul : as === "ol" ? motion.ol : as === "span" ? motion.span : motion.div;
  return nested ? (
    <Tag className={className} variants={variants}>
      {children}
    </Tag>
  ) : (
    <Tag className={className} variants={variants} initial="hidden" animate="show">
      {children}
    </Tag>
  );
}

/** `delay` places an item on its own beat (seconds after the slide arrives) instead of the group's stagger. */
export function Reveal({ children, className, as = "div", delay }: { children: ReactNode; className?: string; as?: "div" | "span" | "li" | "p"; delay?: number }) {
  const reduce = useReducedMotion();
  const Tag = as === "li" ? motion.li : as === "p" ? motion.p : as === "span" ? motion.span : motion.div;
  const variants = reduce ? ITEM_STILL : delay === undefined ? ITEM : { ...ITEM, show: { opacity: 1, y: 0, transition: { duration: 0.55, ease: EASE_OUT, delay } } };
  return (
    <Tag className={className} variants={variants}>
      {children}
    </Tag>
  );
}

// ---------- type and furniture ----------
/** Hyphenate-style micro-label at slide scale: "EXAMPLE · THE-BUSINESS". */
export function Eyebrow({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn("font-mono text-[18px] uppercase tracking-[0.16em] text-cloud-500", className)}>{children}</p>;
}

export function Brand({ size = "sm", className }: { size?: "sm" | "lg"; className?: string }) {
  return (
    <span className={cn("inline-flex items-center", size === "lg" ? "gap-4 text-cloud-50" : "gap-3 text-cloud-400", className)}>
      <Logo className={size === "lg" ? "h-[30px] w-auto" : "h-[19px] w-auto"} />
      <span className={cn("font-semibold tracking-[-0.01em] [font-stretch:112%]", size === "lg" ? "text-[36px]" : "text-[22px]")}>StormCheck</span>
    </span>
  );
}

/** Content slides: eyebrow and brand on top, the slide body, an optional ↻ footer (the deck draws the progress). */
export function SlideFrame({ eyebrow, children, footer, className }: { eyebrow: ReactNode; children: ReactNode; footer?: ReactNode; className?: string }) {
  return (
    <div className="relative h-full w-full overflow-hidden bg-navy-950">
      {/* storm light, decoration only */}
      <div aria-hidden="true" className="pointer-events-none absolute -right-[420px] -top-[520px] size-[1300px] rounded-full bg-[radial-gradient(closest-side,rgba(200,208,219,0.07),transparent)]" />
      <RevealGroup className={cn("relative flex h-full flex-col px-[112px] pb-[72px] pt-[76px]", className)}>
        <Reveal className="flex items-center justify-between">
          <Eyebrow>{eyebrow}</Eyebrow>
          <Brand />
        </Reveal>
        <div className="flex min-h-0 flex-1 flex-col">{children}</div>
        {footer ? <Reveal className="mt-8 min-h-[34px] pr-[300px]">{footer}</Reveal> : <div className="mt-8 min-h-[34px]" />}
      </RevealGroup>
    </div>
  );
}

/** "↻ Next storm: 31 voucher cases settled, ruling cited." */
export function LoopLine({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <p className={cn("flex items-baseline gap-3 text-[25px] text-cloud-300", className)}>
      <span aria-hidden="true" className="font-mono text-cloud-500">
        ↻
      </span>
      <span>{children}</span>
    </p>
  );
}

export type ChipTone = "outline" | "held" | "notweather" | "metar" | "bright" | "quiet";

const CHIP: Record<ChipTone, string> = {
  outline: "text-cloud-200 shadow-[inset_0_0_0_1.5px_rgba(200,208,219,0.22)]",
  quiet: "text-cloud-400 shadow-[inset_0_0_0_1.5px_rgba(200,208,219,0.14)]",
  held: "bg-held/15 text-held shadow-[inset_0_0_0_1.5px_rgba(226,161,42,0.45)]",
  notweather: "bg-notweather/15 text-[#ff8a75] shadow-[inset_0_0_0_1.5px_rgba(226,69,44,0.5)]",
  metar: "bg-metar/12 text-metar shadow-[inset_0_0_0_1.5px_rgba(79,159,224,0.4)]",
  bright: "bg-cloud-50 text-navy-950",
};

/** Mono kebab-case chip at slide scale: `self-learning`, `needs-review`, `5,292 passengers, one storm`. */
export function Chip({ children, tone = "outline", className, size = "md", wrap }: { children: ReactNode; tone?: ChipTone; className?: string; size?: "sm" | "md"; wrap?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-[10px] font-mono",
        wrap ? "min-h-[36px] py-[7px] leading-[1.3]" : "whitespace-nowrap leading-none",
        !wrap && (size === "sm" ? "h-[36px]" : "h-[46px]"),
        size === "sm" ? "px-3.5 text-[17px]" : "px-[18px] text-[21px]",
        CHIP[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/** A number in tabular figures: Archivo in prose, or the surrounding face when given `font-mono`. */
export function Num({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("figure font-sans", className)}>{children}</span>;
}

/** A figure from the API, or a quiet placeholder until it arrives. Slides never type a computed number. */
export function Fig({ value, className, width = "3.2ch" }: { value: ReactNode | null | undefined; className?: string; width?: string }) {
  if (value === null || value === undefined || value === "—") {
    return <span aria-label="loading" className={cn("inline-block h-[0.72em] animate-pulse rounded-[0.12em] bg-white/12 align-[-0.04em]", className)} style={{ width }} />;
  }
  return <Num className={className}>{value}</Num>;
}

export function Bullets({ items, className }: { items: ReactNode[]; className?: string }) {
  return (
    <ul className={cn("flex flex-col gap-3", className)}>
      {items.map((item, i) => (
        <li key={i} className="flex gap-3.5 text-[21px] leading-[1.38] text-cloud-300">
          <span aria-hidden="true" className="mt-[0.6em] size-[6px] shrink-0 rounded-full bg-cloud-500" />
          <span className="min-w-0 text-pretty">{item}</span>
        </li>
      ))}
    </ul>
  );
}

/** Initials avatar, as the app routes questions: CL / LG / CT. */
export function Initials({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("inline-flex size-[44px] shrink-0 items-center justify-center rounded-full bg-cloud-50 font-mono text-[16px] font-bold text-navy-950", className)}>{children}</span>;
}

// ---------- Hyphenate's 4-card grammar ----------
export type GrammarCard = {
  title: string;
  tag: string;
  lead: ReactNode;
  details: ReactNode;
  /** `held` = amber (it holds money for a person); `bright` = a plain bright outline, no colour meaning. */
  highlight?: "held" | "bright";
};

// The card's own column is minmax(0, 1fr): a long unbreakable word can never widen it past its neighbours.
const CARD_BASE = "row-span-3 grid grid-cols-[minmax(0,1fr)] grid-rows-subgrid rounded-[26px] px-[30px] pb-[30px] pt-[28px]";
const CARD_TONE = {
  none: "bg-white/[0.035] shadow-[inset_0_0_0_1px_rgba(200,208,219,0.1)]",
  held: "bg-[linear-gradient(180deg,rgba(226,161,42,0.12),rgba(226,161,42,0.04))] shadow-[inset_0_0_0_2px_rgba(226,161,42,0.85),0_30px_80px_-30px_rgba(226,161,42,0.35)]",
  bright: "bg-white/[0.07] shadow-[inset_0_0_0_2px_rgba(244,246,249,0.92),0_30px_80px_-30px_rgba(244,246,249,0.25)]",
};
const TAG_TONE = { none: "quiet", held: "held", bright: "bright" } as const;

/** Learns / Runs / Escalates / Improves: tag, title, one sentence, then the evidence. Rows line up across cards. */
export function GrammarCards({ cards, className }: { cards: GrammarCard[]; className?: string }) {
  return (
    <RevealGroup nested stagger={0.07} className={cn("grid grid-cols-4 gap-x-6 [grid-template-rows:auto_auto_1fr]", className)}>
      {cards.map((card) => {
        const tone = card.highlight ?? "none";
        return (
          <Reveal key={card.tag} className={cn(CARD_BASE, CARD_TONE[tone])}>
            <header>
              <Chip size="sm" tone={TAG_TONE[tone]}>
                {card.tag}
              </Chip>
              <h3 className="display-tight mt-[18px] text-[46px] leading-none text-cloud-50">{card.title}</h3>
            </header>
            <p className="pt-[18px] text-[24px] leading-[1.36] text-cloud-100 text-pretty">{card.lead}</p>
            <div className={cn("mt-6 border-t pt-[22px]", tone === "held" ? "border-held/30" : tone === "bright" ? "border-white/20" : "border-white/10")}>{card.details}</div>
          </Reveal>
        );
      })}
    </RevealGroup>
  );
}
