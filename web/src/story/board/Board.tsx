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

/** The re-check's pace down the board: it reaches a row every SCAN_ROW ms (board-scan in story.css matches). */
const SCAN_LEAD = 120;
const SCAN_ROW = 90;

// n cells are 0.8n − 0.08 em wide (0.72em cells, 0.08em gaps): 5 → 3.92, 3 → 2.32, 9 → 7.12, 7 → 5.52.
const COLS = "grid grid-cols-[3.92em_3.92em_2.32em_5.52em_5.52em] gap-x-[0.6em] md:grid-cols-[3.92em_3.92em_7.12em_5.52em_5.52em] md:gap-x-[0.9em]";

function FlapBoard({ title, rows, phase, entitlement, side }: { title: string; rows: BoardRow[]; phase: Phase; entitlement: number | null; side: "dep" | "arr" }) {
  const placeholders = rows.length ? rows : Array.from({ length: side === "dep" ? 14 : 13 }, () => null);
  return (
    <div className="w-fit min-w-0">
      <p className="micro mb-3 px-1 text-cloud-300">{title}</p>
      <div className="relative overflow-hidden rounded-lg bg-[#0a1220] p-2.5 shadow-[inset_0_0_0_1px_rgba(255,255,255,0.05),0_30px_60px_-30px_rgba(0,0,0,0.8)] md:p-4">
        {/* the hall's light moving across the flaps (motion only) */}
        <span className="board-sheen" aria-hidden="true" />
        <div className={cn(COLS, "mb-2 px-1 text-[0.6em] uppercase tracking-[0.06em] text-cloud-500")} aria-hidden="true">
          <span>{side === "dep" ? "STD" : "STA"}</span>
          <span>Flight</span>
          <span>{side === "dep" ? "To" : "From"}</span>
          <span>Code</span>
          <span>Art. 7</span>
        </div>
        <div className="relative flex flex-col gap-[0.3em]">
          {/* the re-check runs down the board line by line; each row flips as it passes */}
          <span className="board-scan" data-run={phase === "checked" && rows.length > 0 ? "true" : undefined} style={{ ["--rows" as string]: placeholders.length }} aria-hidden="true" />
          {placeholders.map((row, i) => {
            const coded = row ? (row.coded ? `WX ${row.coded}` : "WX") : "";
            const shown = phase !== "blank" && row ? row : null;
            const checked = phase === "checked" && shown ? after(shown, entitlement) : null;
            const d = i * 70;
            return (
              <div
                key={row?.id ?? i}
                className={cn("flap-row items-center rounded-[3px] px-1 py-[0.08em] transition-colors delay-[var(--d)] duration-700", COLS, checked && row?.verdict === "notweather" && "bg-notweather/[0.14]")}
                data-tone={checked ? row?.verdict : undefined}
                data-flight={row?.number}
                // the row takes its colour when the re-check line reaches it
                style={{ ["--d" as string]: `${SCAN_LEAD + i * SCAN_ROW}ms` }}
              >
                <FlapText text={shown?.time ?? ""} width={5} delay={d} />
                <FlapText text={shown?.number ?? ""} width={5} delay={d + 50} />
                <span className="flex md:hidden">
                  <FlapText text={shown?.iata ?? ""} width={3} delay={d + 100} />
                </span>
                <span className="hidden md:flex">
                  <FlapText text={shown?.city ?? ""} width={9} delay={d + 100} />
                </span>
                <FlapText text={checked ? checked.code : shown ? coded : ""} width={7} delay={checked ? SCAN_LEAD + i * SCAN_ROW : d + 160} />
                <FlapText text={checked?.owed ?? ""} width={7} delay={checked ? SCAN_LEAD + 160 + i * SCAN_ROW : d + 200} />
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
          start: "bottom 86%",
          onEnter: () => setPhase("checked"),
          onLeaveBack: () => setPhase("coded"),
        });
        gsap.from(".board-head > *", { opacity: 0, y: 24, stagger: 0.1, duration: 0.9, scrollTrigger: { trigger: root.current, start: "top 70%" } });
      });
    },
    { scope: root },
  );

  return (
    <section ref={root} aria-label="The cancel list, as coded" data-section="board" className="relative bg-navy-950 px-5 pb-28 pt-32 md:px-16 md:pb-36 md:pt-40">
      <div className="board-head mx-auto max-w-[1180px]">
        <h2 className="text-balance display max-w-[15ch] text-[clamp(38px,5.4vw,88px)] text-cloud-50">
          OCC coded all {cancelled !== undefined ? count(cancelled) : <Pending ch={2} />} as weather.
        </h2>
        <p className="mt-6 max-w-[46ch] text-[16.5px] leading-relaxed text-cloud-400 md:text-[19px]">
          Operations control (OCC) sent the cancel list{occAt ? ` at ${occAt}` : ""} with the same reason on every line. StormCheck checks each flight against Dublin&rsquo;s METAR and the aircraft&rsquo;s own logs.
        </p>
      </div>

      <div className="board-boards mx-auto mt-14 grid max-w-[1180px] grid-cols-1 justify-between gap-x-10 gap-y-8 text-[12.5px] min-[390px]:text-[13px] min-[1180px]:grid-cols-[auto_auto] min-[1180px]:text-[clamp(14px,1.2vw,18px)] md:mt-20 md:text-[16px]">
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
          LEGAL · {held ? `${count(held)} knock-on returns` : "knock-on returns"}, held for one ruling
        </span>
        <span className={cn("flex items-center gap-2 transition-opacity duration-700", phase === "checked" ? "opacity-100" : "opacity-0")}>
          <span className="size-2 rounded-full bg-notweather" aria-hidden="true" />
          TECH · not weather: full Art. 7 entitlement if every passenger claims
        </span>
      </div>
    </section>
  );
}
