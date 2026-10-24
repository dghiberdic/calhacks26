import { useEffect, useState } from "react";
import { animate, motion, useMotionValue, useReducedMotion, useTransform } from "motion/react";
import type { CfoMetrics } from "@/api/types";
import { eur, pct } from "@/lib/format";
import { claimRate, recodedRow, type PitchData } from "../data";
import { EASE_OUT } from "../stage";
import { Fig, Num, Reveal, SlideFrame } from "../ui";

const TRACK_W = 1696;

/**
 * THREAD_JUSTIN J11 slide 5: "Cash basis €0 · full entitlement €99,000 · drafted €34,650 (±5pp ±€4,950)",
 * drawn to scale from GET /books/cfo, then who doesn't need it.
 */
export function CfoLine({ data }: { data: PitchData }) {
  const { cfo, run } = data;
  const flight = recodedRow(run)?.flight.number;

  return (
    <SlideFrame eyebrow="the cfo line" footer={<p className="text-[25px] text-cloud-300">It drafts. It never pays.</p>}>
      <Reveal className="mt-12">
        {/* The headline is made of the two numbers it rejects; until they arrive it is just the slide's name. */}
        <h2 className="display text-[124px] text-cloud-50">
          {cfo ? (
            <>
              Not <Num>{eur(cfo.cash_basis_cents)}</Num>. Not <Num>{eur(cfo.full_entitlement_cents)}</Num>.
            </>
          ) : (
            "The CFO line."
          )}
        </h2>
      </Reveal>
      <Reveal className="mt-7">
        <p className="text-[34px] leading-tight text-cloud-200">
          {flight ? `${flight}’s` : "The"} EU261 compensation liability, drafted the morning after.
        </p>
      </Reveal>

      <Reveal className="mt-auto">
        <Bridge cfo={cfo} />
      </Reveal>

      <Reveal className="mt-16 grid grid-cols-2 gap-6 border-t border-white/10 pt-8">
        <div>
          <p className="font-mono text-[17px] uppercase tracking-[0.16em] text-cloud-500">Who doesn&rsquo;t need it</p>
          <p className="mt-3 text-[32px] leading-[1.3] text-cloud-50">A three-route charter that rarely cancels.</p>
        </div>
        <div>
          <p className="font-mono text-[17px] uppercase tracking-[0.16em] text-cloud-500">Where it goes next</p>
          <p className="mt-3 text-[28px] leading-[1.35] text-cloud-200">
            The same seat, more causes: three-hour delays, strikes and ATC as new evidence feeds; UK261, Canada and the 2027 EU261 rules as dated rule packs.
          </p>
        </div>
      </Reveal>
    </SlideFrame>
  );
}

/** When the marker leaves €0 (s after the slide opens), and how long it takes to reach the drafted figure. */
const SLIDE_DELAY = 0.85;
const SLIDE_FOR = 1.7;

/**
 * €0 ─── €34,650 (±5 pp) ───────── €99,000, to scale. When the slide opens the marker leaves €0 and slides to
 * the drafted figure, the line filling behind it and the figure counting with it; then the ±5 pp band opens
 * and the method appears under it. Transforms only, so nothing on the slide reflows while it plays.
 */
function Bridge({ cfo }: { cfo: CfoMetrics | undefined }) {
  const reduce = useReducedMotion();
  const rate = claimRate(cfo);
  const ready = !!cfo && rate !== undefined;
  // Until the numbers arrive the line is drawn bare, centred labels and all: no marker at an assumed rate.
  const at = ready ? Math.max(0, Math.min(1, rate)) : 0.5;
  const band = ready && cfo.full_entitlement_cents > 0 ? cfo.sensitivity_5pp_cents / cfo.full_entitlement_cents : 0;
  const x = at * TRACK_W;
  const drafted = cfo?.drafted_liability_cents ?? 0;

  // 0 → 1 along the marker's way from €0 to the drafted figure; with reduced motion it starts at the end.
  const progress = useMotionValue(reduce ? 1 : 0);
  const [arrived, setArrived] = useState(false);
  const landed = !!reduce || arrived;
  useEffect(() => {
    if (!ready) return;
    if (reduce) {
      progress.set(1);
      return;
    }
    const run = animate(progress, 1, { delay: SLIDE_DELAY, duration: SLIDE_FOR, ease: [0.65, 0, 0.35, 1], onComplete: () => setArrived(true) });
    return () => run.stop();
  }, [ready, reduce, progress]);
  const markerX = useTransform(progress, (p) => p * x);
  const filled = useTransform(progress, (p) => p * at);
  // Whole euros on the way, the API's figure at the end. It appears as the marker leaves, so the line never
  // reads "€0 … €0".
  const figure = useTransform(progress, (p) => eur(p >= 1 ? drafted : Math.round((p * drafted) / 100) * 100));
  const figureOpacity = useTransform(progress, [0, 0.12], [0, 1]);

  return (
    <div className="relative" style={{ width: TRACK_W }} data-testid="cfo-bridge">
      {/* the three numbers, above their places on the line */}
      <div className="relative h-[124px]">
        <p className="absolute bottom-0 left-0 text-[64px] leading-none text-cloud-400">
          <Fig value={ready ? eur(cfo.cash_basis_cents) : null} width="2ch" />
        </p>
        {/* A fixed box centred where the marker lands: the figure counts up in place while the marker travels. */}
        <p className="display absolute bottom-0 w-[720px] text-center text-[118px] leading-none text-cloud-50" style={{ left: Math.max(0, Math.min(TRACK_W - 720, x - 360)) }} data-testid="cfo-drafted">
          {ready ? (
            <>
              <span className="sr-only">{eur(drafted)}</span>
              <motion.span aria-hidden="true" className="figure font-sans" style={{ opacity: figureOpacity }}>
                {figure}
              </motion.span>
            </>
          ) : (
            <Fig value={null} width="5ch" />
          )}
        </p>
        <p className="absolute bottom-0 right-0 text-[64px] leading-none text-cloud-400">
          <Fig value={ready ? eur(cfo.full_entitlement_cents) : null} width="4.5ch" />
        </p>
      </div>

      {/* the line */}
      <div className="relative mt-7 h-[34px]">
        <div className="absolute inset-x-0 top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-white/15" />
        {ready ? <motion.div className="absolute inset-x-0 top-1/2 -mt-[2.5px] h-[5px] rounded-full bg-cloud-50" style={{ scaleX: filled, originX: 0 }} /> : null}
        {band > 0 ? (
          <motion.div
            className="absolute top-0 h-full rounded-[8px] bg-white/12 shadow-[inset_0_0_0_1px_rgba(244,246,249,0.25)]"
            style={{ left: (at - band) * TRACK_W, width: band * 2 * TRACK_W }}
            initial={false}
            animate={{ opacity: landed ? 1 : 0, scaleX: landed ? 1 : 0.15 }}
            transition={{ duration: reduce ? 0 : 0.55, ease: EASE_OUT }}
          />
        ) : null}
        <span className="absolute left-0 top-1/2 size-[18px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-navy-950 shadow-[inset_0_0_0_3px_var(--color-cloud-400)]" />
        {ready ? (
          <motion.span
            className="absolute left-0 top-1/2 -ml-[15px] -mt-[15px] size-[30px] rounded-full bg-cloud-50 shadow-[0_0_0_8px_rgba(244,246,249,0.12)]"
            style={{ x: markerX }}
            data-testid="cfo-marker"
          />
        ) : null}
        <span className="absolute right-0 top-1/2 size-[18px] translate-x-1/2 -translate-y-1/2 rounded-full bg-navy-950 shadow-[inset_0_0_0_3px_var(--color-cloud-400)]" />
      </div>

      {/* what each one is, in plan §9 words */}
      <div className="relative mt-6 h-[118px]">
        <div className="absolute left-0 top-0 max-w-[300px]">
          <p className="font-mono text-[17px] uppercase tracking-[0.16em] text-cloud-400">Cash basis</p>
        </div>
        <motion.div
          className="absolute top-0 w-[560px] text-center"
          style={{ left: Math.max(0, Math.min(TRACK_W - 560, x - 280)) }}
          initial={false}
          animate={{ opacity: landed || !ready ? 1 : 0, y: landed || !ready ? 0 : 10 }}
          transition={{ duration: reduce ? 0 : 0.5, ease: EASE_OUT, delay: landed && !reduce ? 0.15 : 0 }}
        >
          <p className="font-mono text-[17px] uppercase tracking-[0.16em] text-cloud-50">Drafted, pending approval</p>
          <p className="mt-2.5 text-[22px] leading-[1.35] text-cloud-300 text-balance">
            <Fig value={rate === undefined ? null : pct(rate)} width="2.5ch" className="text-cloud-50" /> expected ultimate claim rate (history to M18 + tail judgment)
          </p>
          {cfo?.sensitivity_5pp_cents ? (
            <p className="mt-1.5 text-[19px] text-cloud-400">
              ±5 pp = ±<Num>{eur(cfo.sensitivity_5pp_cents)}</Num>
            </p>
          ) : null}
        </motion.div>
        <div className="absolute right-0 top-0 max-w-[340px] text-right">
          <p className="font-mono text-[17px] uppercase tracking-[0.16em] text-cloud-400">Full entitlement</p>
          <p className="mt-2.5 text-[22px] leading-[1.35] text-cloud-300 text-balance">full Art. 7 entitlement if every passenger claims</p>
        </div>
      </div>
    </div>
  );
}
