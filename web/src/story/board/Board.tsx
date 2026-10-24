import { useMemo, useRef, useState } from "react";
import { count, eur } from "@/lib/format";
import { cn } from "@/lib/utils";
import { boardRows, occTime, type BoardRow } from "../data/model";
import { useStory } from "../data/context";
import { gsap, MEDIA, prefersReducedMotion, ScrollTrigger, useGSAP } from "../motion/gsap";
import { Pending } from "../ui";
import { FlapText } from "./SplitFlap";

type Phase = "blank" | "coded" | "checked";

/** What the CODE and Art. 7 columns read after the re-check. Weather keeps OCC's code, dimmed. */
function after(row: BoardRow, entitlementCents: number | null) {
  const wx = row.coded ? `WX ${row.coded}` : "WX";
  if (row.verdict === "notweather") return { code: row.after ? `TECH ${row.after}` : "TECH", owed: entitlementCents !== null ? eur(entitlementCents) : "" };
  if (row.verdict === "held") return { code: row.routedTo === "legal" ? "LEGAL" : "HELD", owed: "HELD" };
  return { code: wx, owed: "" };
}

// n cells are 0.8n − 0.08 em wide (0.72em cells, 0.08em gaps): 5 → 3.92, 3 → 2.32, 9 → 7.12, 7 → 5.52.
const COLS = "grid grid-cols-[3.92em_3.92em_2.32em_5.52em_5.52em] gap-x-[0.6em] md:grid-cols-[3.92em_3.92em_7.12em_5.52em_5.52em] md:gap-x-[0.9em]";

function FlapBoard({ title, rows, phase, entitlement, side }: { title: string; rows: BoardRow[]; phase: Phase; entitlement: number | null; side: "dep" | "arr" }) {
  const placeholders = rows.length ? rows : Array.from({ length: side === "dep" ? 14 : 13 }, () => null);
  return (
    <div className="w-fit min-w-0">
      <div className="mb-3 flex items-baseline justify-between gap-4 px-1">
        <span className="micro text-cloud-300">{title}</span>
        <span className="micro text-cloud-500">{side === "dep" ? "to" : "from"} · reason · art. 7</span>
      </div>
      <div className="rounded-lg bg-[#0a1220] p-2.5 shadow-[inset_0_0_0_1px_rgba(255,255,255,0.05),0_30px_60px_-30px_rgba(0,0,0,0.8)] md:p-4">
        <div className="flex flex-col gap-[0.3em]">
          {placeholders.map((row, i) => {
            const coded = row ? (row.coded ? `WX ${row.coded}` : "WX") : "";
            const shown = phase !== "blank" && row ? row : null;
            const checked = phase === "checked" && shown ? after(shown, entitlement) : null;
            const d = i * 70;
            return (
              <div
                key={row?.id ?? i}
                className={cn("flap-row items-center rounded-[3px] px-1 py-[0.08em] transition-colors duration-700", COLS, checked && row?.verdict === "notweather" && "bg-notweather/[0.14]")}
                data-tone={checked ? row?.verdict : undefined}
                data-flight={row?.number}
              >
                <FlapText text={shown?.time ?? ""} width={5} delay={d} />
                <FlapText text={shown?.number ?? ""} width={5} delay={d + 50} />
                <span className="md:hidden">
                  <FlapText text={shown?.iata ?? ""} width={3} delay={d + 100} />
                </span>
                <span className="hidden md:inline">
                  <FlapText text={shown?.city ?? ""} width={9} delay={d + 100} />
                </span>
                <FlapText text={checked ? checked.code : shown ? coded : ""} width={7} delay={checked ? 120 + (i % 7) * 40 : d + 160} />
                <FlapText text={checked?.owed ?? ""} width={7} delay={checked ? 380 : d + 200} />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/**
 * The cancellations as OCC coded them, on a Solari board at Dublin: every one "WX". Scroll on and
 * StormCheck's re-check flips them: weather settles grey, the knock-on returns go to Legal (amber),
 * and NS31 turns to TECH with its full Art. 7 entitlement. All rows, codes and euros come from the API.
 */
export function Board() {
  const story = useStory();
  const root = useRef<HTMLElement>(null);
  const [phase, setPhase] = useState<Phase>(() => (prefersReducedMotion() ? "checked" : "blank"));
  const { departures, arrivals } = useMemo(() => boardRows(story.run), [story.run]);
  const occAt = occTime(story.file);
  const cancelled = story.run?.counters.cancelled;
  const held = [...departures, ...arrivals].filter((r) => r.verdict === "held").length;

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add(MEDIA.motion, () => {
        ScrollTrigger.create({ trigger: ".board-boards", start: "top 78%", onEnter: () => setPhase((p) => (p === "blank" ? "coded" : p)) });
        // Flip when NS31's row (the last departure) is well on screen, so the change is seen, not missed.
        ScrollTrigger.create({
          trigger: ".board-dep",
          start: "bottom 72%",
          onEnter: () => setPhase("checked"),
          onLeaveBack: () => setPhase("coded"),
        });
        gsap.from(".board-head > *", { opacity: 0, y: 24, stagger: 0.1, duration: 0.9, scrollTrigger: { trigger: root.current, start: "top 70%" } });
      });
    },
    { scope: root },
  );

  return (
    <section ref={root} aria-label="The cancellations, as coded" className="relative bg-navy-950 px-5 pb-28 pt-32 md:px-16 md:pb-36 md:pt-40">
      <div className="board-head mx-auto max-w-[1180px]">
        <h2 className="display max-w-[15ch] text-[clamp(38px,5.4vw,88px)] text-cloud-50">
          All {cancelled !== undefined ? count(cancelled) : <Pending ch={2} />} coded weather.
        </h2>
        <p className="mt-6 max-w-[46ch] text-[16.5px] leading-relaxed text-cloud-400 md:text-[19px]">
          OCC&rsquo;s cancel list{occAt ? ` at ${occAt}` : ""} gave every flight the same reason. StormCheck checks each one against the airport&rsquo;s weather and the aircraft&rsquo;s own logs.
        </p>
      </div>

      <div className="board-boards mx-auto mt-14 grid max-w-[1180px] grid-cols-1 gap-8 text-[12.5px] min-[1180px]:grid-cols-2 min-[1180px]:text-[clamp(13px,1.12vw,16.5px)] md:mt-20 md:text-[15px]">
        <div className="board-dep">
          <FlapBoard title="Dublin departures · cancelled" rows={departures} phase={phase} entitlement={story.money.full} side="dep" />
        </div>
        <FlapBoard title="Dublin arrivals · cancelled" rows={arrivals} phase={phase} entitlement={story.money.full} side="arr" />
      </div>

      <div className="mx-auto mt-8 flex max-w-[1180px] flex-wrap gap-x-7 gap-y-2 text-[13px] text-cloud-400" aria-live="polite">
        <span className="flex items-center gap-2">
          <span className="size-2 rounded-full bg-weather" aria-hidden="true" />
          WX · weather: no compensation; refunds and care still due
        </span>
        <span className={cn("flex items-center gap-2 transition-opacity duration-700", phase === "checked" ? "opacity-100" : "opacity-0")}>
          <span className="size-2 rounded-full bg-held" aria-hidden="true" />
          LEGAL · {held ? `${count(held)} knock-on returns` : "knock-on returns"}, one question to Legal
        </span>
        <span className={cn("flex items-center gap-2 transition-opacity duration-700", phase === "checked" ? "opacity-100" : "opacity-0")}>
          <span className="size-2 rounded-full bg-notweather" aria-hidden="true" />
          TECH · not weather: full Art. 7 entitlement if every passenger claims
        </span>
      </div>
    </section>
  );
}
