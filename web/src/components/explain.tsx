import { useState, type ReactNode } from "react";
import { CircleHelp } from "lucide-react";
import { GLOSSARY, type Term } from "@/lib/glossary";
import { cn } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "./ui/tooltip";

/**
 * The plain meaning of a word, on hover, keyboard focus or tap. The word keeps its own styling, with a dotted
 * underline: `<Explain term="metar">METAR</Explain>`, or `<Explain term="metar" />` for the glossary's own
 * spelling. Definitions live in lib/glossary.ts.
 */
export function Explain({ term, children, className }: { term: Term; children?: ReactNode; className?: string }) {
  return (
    <Meaning term={term}>
      <button type="button" className={cn("cursor-help text-left underline decoration-current/40 decoration-dotted underline-offset-[3px] hover:decoration-current", className)}>
        {children ?? GLOSSARY[term].term}
      </button>
    </Meaning>
  );
}

/** A small "What's this?" mark after a label, for when the label itself shouldn't be underlined. */
export function WhatsThis({ term, className }: { term: Term; className?: string }) {
  return (
    <Meaning term={term}>
      <button type="button" aria-label={`What's this? ${GLOSSARY[term].term}`} className={cn("inline-flex size-4 cursor-help items-center justify-center align-[-2px] text-current opacity-50 hover:opacity-100", className)}>
        <CircleHelp className="size-3.5" aria-hidden="true" />
      </button>
    </Meaning>
  );
}

/** The meanings written out, for a "How we got this" panel: `<Glossary terms={["cash-basis", "full-entitlement"]} />`. */
export function Glossary({ terms, className }: { terms: Term[]; className?: string }) {
  return (
    <dl className={cn("grid gap-2 text-[12.5px] leading-relaxed", className)}>
      {terms.map((t) => (
        <div key={t}>
          <dt className="inline font-semibold text-navy-900">{GLOSSARY[t].term}: </dt>
          <dd className="inline text-slate-500">{GLOSSARY[t].plain}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Hover and focus open it (Radix); a tap or click opens it too, so it works on a phone. */
function Meaning({ term, children }: { term: Term; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const entry = GLOSSARY[term];
  return (
    <Tooltip open={open} onOpenChange={setOpen}>
      <TooltipTrigger
        asChild
        onClick={(e) => {
          // Radix closes a tooltip on click, but a tap is the only way in on touch: keep it open instead.
          // A tap elsewhere or Escape closes it.
          e.preventDefault();
          setOpen(true);
        }}
      >
        {children}
      </TooltipTrigger>
      <TooltipContent side="top" sideOffset={6} className="block max-w-[320px] px-3 py-2 text-left text-[12.5px] leading-snug">
        <span className="font-semibold">{entry.term}</span>
        <span className="opacity-80">: {entry.plain}</span>
      </TooltipContent>
    </Tooltip>
  );
}
