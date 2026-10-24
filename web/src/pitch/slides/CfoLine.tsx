import type { CfoMetrics } from "@/api/types";
import { eur, pct } from "@/lib/format";
import { claimRate, recodedRow, type PitchData } from "../data";
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

/** €0 ─── €34,650 (±5 pp) ───────── €99,000, to scale. */
function Bridge({ cfo }: { cfo: CfoMetrics | undefined }) {
  const rate = claimRate(cfo);
  const ready = !!cfo && rate !== undefined;
  // Until the numbers arrive the line is drawn bare, centred labels and all: no marker at an assumed rate.
  const at = ready ? Math.max(0, Math.min(1, rate)) : 0.5;
  const band = ready && cfo.full_entitlement_cents > 0 ? cfo.sensitivity_5pp_cents / cfo.full_entitlement_cents : 0;
  const x = at * TRACK_W;

  return (
    <div className="relative" style={{ width: TRACK_W }} data-testid="cfo-bridge">
      {/* the three numbers, above their places on the line */}
      <div className="relative h-[124px]">
        <p className="absolute bottom-0 left-0 text-[64px] leading-none text-cloud-400">
          <Fig value={ready ? eur(cfo.cash_basis_cents) : null} width="2ch" />
        </p>
        <p className="display absolute bottom-0 text-[118px] leading-none text-cloud-50" style={{ left: x, transform: "translateX(-50%)" }}>
          <Fig value={ready ? eur(cfo.drafted_liability_cents) : null} width="5ch" />
        </p>
        <p className="absolute bottom-0 right-0 text-[64px] leading-none text-cloud-400">
          <Fig value={ready ? eur(cfo.full_entitlement_cents) : null} width="4.5ch" />
        </p>
      </div>

      {/* the line */}
      <div className="relative mt-7 h-[34px]">
        <div className="absolute inset-x-0 top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-white/15" />
        {ready ? <div className="absolute left-0 top-1/2 h-[5px] -translate-y-1/2 rounded-full bg-cloud-50" style={{ width: x }} /> : null}
        {band > 0 ? <div className="absolute top-0 h-full rounded-[8px] bg-white/12 shadow-[inset_0_0_0_1px_rgba(244,246,249,0.25)]" style={{ left: (at - band) * TRACK_W, width: band * 2 * TRACK_W }} /> : null}
        <span className="absolute left-0 top-1/2 size-[18px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-navy-950 shadow-[inset_0_0_0_3px_var(--color-cloud-400)]" />
        {ready ? <span className="absolute top-1/2 size-[30px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-cloud-50 shadow-[0_0_0_8px_rgba(244,246,249,0.12)]" style={{ left: x }} /> : null}
        <span className="absolute right-0 top-1/2 size-[18px] translate-x-1/2 -translate-y-1/2 rounded-full bg-navy-950 shadow-[inset_0_0_0_3px_var(--color-cloud-400)]" />
      </div>

      {/* what each one is, in plan §9 words */}
      <div className="relative mt-6 h-[118px]">
        <div className="absolute left-0 top-0 max-w-[300px]">
          <p className="font-mono text-[17px] uppercase tracking-[0.16em] text-cloud-400">Cash basis</p>
        </div>
        <div className="absolute top-0 w-[560px] text-center" style={{ left: x, transform: "translateX(-50%)" }}>
          <p className="font-mono text-[17px] uppercase tracking-[0.16em] text-cloud-50">Drafted, pending approval</p>
          <p className="mt-2.5 text-[22px] leading-[1.35] text-cloud-300 text-balance">
            <Fig value={rate === undefined ? null : pct(rate)} width="2.5ch" className="text-cloud-50" /> expected ultimate claim rate (history to M18 + tail judgment)
          </p>
          {cfo?.sensitivity_5pp_cents ? (
            <p className="mt-1.5 text-[19px] text-cloud-400">
              ±5 pp = ±<Num>{eur(cfo.sensitivity_5pp_cents)}</Num>
            </p>
          ) : null}
        </div>
        <div className="absolute right-0 top-0 max-w-[340px] text-right">
          <p className="font-mono text-[17px] uppercase tracking-[0.16em] text-cloud-400">Full entitlement</p>
          <p className="mt-2.5 text-[22px] leading-[1.35] text-cloud-300 text-balance">full Art. 7 entitlement if every passenger claims</p>
        </div>
      </div>
    </div>
  );
}
