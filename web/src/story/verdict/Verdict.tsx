import { useMemo, useRef } from "react";
import { curveMonotoneX, line } from "d3-shape";
import type { ClaimCurve } from "@/api/types";
import { JournalCard } from "@/components/journal";
import { count, eur, pct } from "@/lib/format";
import { useStory } from "../data/context";
import { gsap, MEDIA, PLOTTED, UNPLOTTED, useGSAP } from "../motion/gsap";
import { RollingNumber } from "../motion/RollingNumber";
import { Pending } from "../ui";

/** The learned curve: cumulative valid-claim rate by month after the storm, with its ultimate. */
function Curve({ curve }: { curve: ClaimCurve | undefined }) {
  const g = useMemo(() => {
    if (!curve?.points.length) return null;
    const last = Math.max(24, ...curve.points.map((p) => p[0]));
    const pts: [number, number][] = [[0, 0], ...curve.points.filter((p) => p[0] > 0)];
    const top = Math.max(curve.ultimate, ...pts.map((p) => p[1])) * 1.15;
    const x = (m: number) => 10 + (m / last) * 280;
    const y = (r: number) => 112 - (r / top) * 100;
    return { d: line<[number, number]>().x((p) => x(p[0])).y((p) => y(p[1])).curve(curveMonotoneX)(pts) ?? "", x, y, last, pts };
  }, [curve]);
  if (!curve || !g) return <div className="aspect-[300/130] w-full animate-pulse rounded-lg bg-navy-900/5" aria-hidden="true" />;
  return (
    <svg viewBox="0 0 300 130" className="w-full overflow-visible" role="img" aria-label={`Expected claims rise toward the ${pct(curve.ultimate)} expected ultimate claim rate (curve ${curve.version}).`}>
      <line x1="10" x2="290" y1="112" y2="112" stroke="#c8d0db" />
      <line x1="10" x2="290" y1={g.y(curve.ultimate)} y2={g.y(curve.ultimate)} stroke="#2565a3" strokeDasharray="3 4" strokeOpacity="0.7" />
      <path className="vd-curve-line" d={g.d} fill="none" stroke="#0d1524" strokeWidth="2" {...PLOTTED} />
      {g.pts.slice(1).map(([m, r]) => (
        <circle key={m} cx={g.x(m)} cy={g.y(r)} r="2.4" fill="#0d1524" />
      ))}
      <text x="290" y={g.y(curve.ultimate) - 6} textAnchor="end" className="fill-metar-ink font-mono text-[9px]">
        ultimate {pct(curve.ultimate)}
      </text>
      {[0, 6, 12, 18, 24].filter((m) => m <= g.last).map((m) => (
        <text key={m} x={g.x(m)} y="126" textAnchor="middle" className="fill-slate-500 font-mono text-[8px]">
          {m === 0 ? "storm" : `M${m}`}
        </text>
      ))}
    </svg>
  );
}

/** The euros, in the order a controller would check them: not €0, not the full entitlement, the drafted estimate. */
export function Verdict() {
  const story = useStory();
  const root = useRef<HTMLElement>(null);
  const d = story.focus?.decision ?? story.file?.decision ?? null;
  const f = story.focus?.flight ?? story.file?.flight ?? null;
  const m = story.money;
  const score = d?.confidence.score;

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add(MEDIA.motion, () => {
        gsap.from(".vd-reveal", { opacity: 0, y: 24, duration: 0.9, stagger: 0.12, ease: "power3.out", scrollTrigger: { trigger: root.current, start: "top 65%" } });
        gsap.from(".vd-figure", { opacity: 0, y: 30, duration: 0.9, stagger: 0.18, ease: "power3.out", scrollTrigger: { trigger: ".vd-bridge", start: "top 75%" } });
        gsap.from(".vd-strike", { scaleX: 0, transformOrigin: "left center", duration: 0.6, ease: "power2.inOut", stagger: 0.3, delay: 1.1, scrollTrigger: { trigger: ".vd-bridge", start: "top 75%" } });
        gsap.from(".vd-conf", { scaleX: 0, transformOrigin: "left center", duration: 1.2, ease: "power3.inOut", scrollTrigger: { trigger: ".vd-conf", start: "top 90%" } });
      });
    },
    { scope: root },
  );
  // The curve plots once its data exists (it arrives after the section mounts).
  useGSAP(
    () => {
      if (!story.curve) return;
      const mm = gsap.matchMedia();
      mm.add(MEDIA.motion, () => {
        gsap.from(".vd-curve-line", { ...UNPLOTTED, duration: 1.8, ease: "power2.inOut", scrollTrigger: { trigger: ".vd-curve", start: "top 85%" } });
      });
    },
    { scope: root, dependencies: [!!story.curve] },
  );

  return (
    <section ref={root} aria-label="The verdict" className="bg-cloud-50 px-5 py-28 text-navy-900 md:px-16 md:py-36">
      <div className="mx-auto max-w-[1280px]">
        <h2 className="display vd-reveal text-[clamp(46px,7.2vw,124px)]">
          Not weather.
          <br />
          <span className="text-notweather-ink">Broken plane.</span>
        </h2>
        <p className="vd-reveal mt-8 flex flex-wrap items-center gap-x-3 gap-y-2 font-mono text-[13px] text-slate-600 md:text-[14px]" data-testid="story-recode">
          <span className="rounded-md bg-notweather-wash px-2 py-1 text-notweather-ink">{f?.number ?? <Pending ch={4} tone="light" />} · {d ? `${d.cause.replace(/_/g, "-")} · owed` : <Pending ch={10} tone="light" />}</span>
          {d?.recode_label ? <span className="text-navy-900">recoded {d.recode_label}</span> : <Pending ch={12} tone="light" />}
          {d ? (
            <span>
              {d.confidence.label} <b className="text-navy-900">{score === null || score === undefined ? "uncalibrated" : pct(score)}</b>
              {d.reason ? ` · ${d.reason}` : ""}
            </span>
          ) : null}
        </p>

        <div className="vd-bridge mt-20 grid grid-cols-1 items-end gap-x-10 gap-y-12 md:mt-28 md:grid-cols-[1fr_1fr_1.35fr]">
          <figure className="vd-figure">
            <p className="relative inline-block text-[clamp(36px,4.2vw,68px)] text-slate-400">
              <span className="display-tight">Not {m.cash !== null ? eur(m.cash) : <Pending ch={3} tone="light" />}</span>
              <span className="vd-strike absolute inset-x-0 top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-slate-400" aria-hidden="true" />
            </p>
            <figcaption className="mt-3 max-w-[26ch] text-[14.5px] leading-snug text-slate-500">Cash basis: nothing until a claim is paid.</figcaption>
          </figure>
          <figure className="vd-figure">
            <p className="relative inline-block text-[clamp(36px,4.2vw,68px)] text-slate-400">
              <span className="display-tight">Not {m.full !== null ? eur(m.full) : <Pending ch={6} tone="light" />}</span>
              <span className="vd-strike absolute inset-x-0 top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-slate-400" aria-hidden="true" />
            </p>
            <figcaption className="mt-3 max-w-[30ch] text-[14.5px] leading-snug text-slate-500">
              Full Art. 7 entitlement if every passenger claims
              {f && m.band ? (
                <>
                  : <span className="figure">{count(f.pax)}</span> × <span className="figure">€{m.band}</span>
                  {m.distanceKm ? <> ({count(m.distanceKm)} km)</> : null}
                  {m.reduced ? <>, {count(m.reduced)} partner reroutes at 50%</> : null}
                </>
              ) : null}
              .
            </figcaption>
          </figure>
          <figure className="vd-figure">
            <p className="micro text-slate-500">EU261 compensation liability, drafted</p>
            {m.drafted !== null ? <RollingNumber text={eur(m.drafted)} className="display mt-2 text-[clamp(56px,7vw,120px)] text-navy-900" delay={0.4} /> : <Pending ch={6} tone="light" className="mt-4 h-16" />}
            <figcaption className="mt-3 max-w-[36ch] text-[14.5px] leading-snug text-slate-600">
              {m.claimRate !== null ? <span className="figure">{pct(m.claimRate)}</span> : story.curve ? <span className="figure">{pct(story.curve.ultimate)}</span> : <Pending ch={3} tone="light" />} expected ultimate claim rate (history to M18 + tail judgment)
              {m.sensitivity !== null ? (
                <>
                  {" "}
                  · ±5 pp = ±<span className="figure">{eur(m.sensitivity).replace("€", "€")}</span>
                </>
              ) : null}
              .
            </figcaption>
          </figure>
        </div>

        <div className="mt-20 grid grid-cols-1 gap-10 rounded-2xl bg-white p-6 shadow-[0_0_0_1px_var(--color-cloud-200),0_30px_60px_-40px_rgba(13,21,36,0.25)] md:mt-24 md:grid-cols-[1.05fr_1fr] md:gap-14 md:p-10">
          <div className="vd-reveal flex flex-col gap-6">
            {m.je ? <JournalCard entry={m.je} dense className="shadow-[0_0_0_1px_var(--color-cloud-200)]" /> : <div className="h-[148px] animate-pulse rounded-xl bg-navy-900/5" aria-hidden="true" />}
            <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-3 text-[14.5px]">
              <dt className="text-slate-500">Confidence</dt>
              <dd className="flex items-center gap-3">
                <span className="relative h-[6px] flex-1 overflow-hidden rounded-full bg-cloud-200">
                  <span className="vd-conf absolute inset-y-0 left-0 rounded-full bg-navy-900" style={{ width: `${(score ?? 0) * 100}%` }} />
                </span>
                <span className="font-mono text-[13px]">{score === null || score === undefined ? (d ? "uncalibrated" : "") : pct(score)}</span>
              </dd>
              <dt className="text-slate-500">Status</dt>
              <dd>{m.payouts !== null ? <span className="figure">{count(m.payouts)}</span> : <Pending ch={3} tone="light" />} payouts drafted, pending Claims Lead approval</dd>
              <dt className="text-slate-500">Storm total</dt>
              <dd>
                {story.run ? <span className="figure">{eur(story.run.liability_drafted_cents)}</span> : <Pending ch={6} tone="light" />} EU261 compensation liability drafted across {story.stormName ?? "the storm"}
              </dd>
            </dl>
          </div>
          <figure className="vd-reveal vd-curve flex flex-col justify-between gap-6">
            <Curve curve={story.curve} />
            <figcaption className="text-[14px] leading-relaxed text-slate-500">
              Claims arrive for years. Northstar&rsquo;s own history sets the curve{story.curve ? ` (${story.curve.version})` : ""}, and the liability is trued up against it every month-end.
            </figcaption>
          </figure>
        </div>
      </div>
    </section>
  );
}
