import { useEffect, useMemo, useRef, type ReactNode } from "react";
import { curveMonotoneX, line } from "d3-shape";
import type { ClaimCurve, LearnedItem } from "@/api/types";
import { JournalCard } from "@/components/journal";
import { count, eur, pct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useStory } from "../data/context";
import { gsap, MEDIA, PLOTTED, prefersReducedMotion, UNPLOTTED, useGSAP } from "../motion/gsap";
import { RollingNumber } from "../motion/RollingNumber";
import { Pending } from "../ui";

/** The learned curve (GET /books/curve): cumulative valid-claim rate by month after the storm, with its ultimate. */
function Curve({ curve }: { curve: ClaimCurve }) {
  const g = useMemo(() => {
    const last = Math.max(24, ...curve.points.map((p) => p[0]));
    const pts: [number, number][] = [[0, 0], ...curve.points.filter((p) => p[0] > 0)];
    const top = Math.max(curve.ultimate, ...pts.map((p) => p[1])) * 1.15;
    const x = (m: number) => 10 + (m / last) * 280;
    const y = (r: number) => 112 - (r / top) * 100;
    return { d: line<[number, number]>().x((p) => x(p[0])).y((p) => y(p[1])).curve(curveMonotoneX)(pts) ?? "", x, y, last, pts, top };
  }, [curve]);
  const pathRef = useRef<SVGPathElement>(null);
  const rider = useRef<SVGGElement>(null);
  // Claims arriving month by month: a reading rides the curve from the storm to the last month, then again.
  useEffect(() => {
    const path = pathRef.current;
    const el = rider.current;
    if (!path || !el || prefersReducedMotion()) return;
    const total = path.getTotalLength();
    const dot = el.querySelector("circle");
    const label = el.querySelector("text");
    const RIDE = 6500;
    const HOLD = 1600;
    let raf = 0;
    let t0 = performance.now();
    let shown = "";
    const loop = (now: number) => {
      raf = requestAnimationFrame(loop);
      const t = Math.min(1, ((now - t0) % (RIDE + HOLD)) / RIDE);
      const e = 1 - Math.pow(1 - t, 1.6);
      const p = path.getPointAtLength(e * total);
      dot?.setAttribute("cx", p.x.toFixed(2));
      dot?.setAttribute("cy", p.y.toFixed(2));
      const month = ((p.x - 10) / 280) * g.last;
      const rate = ((112 - p.y) / 100) * g.top;
      const text = `${month < 0.5 ? "storm" : `M${Math.round(month)}`} · ${pct(rate)}`;
      if (label && text !== shown) {
        label.textContent = text;
        shown = text;
      }
      label?.setAttribute("x", Math.min(262, p.x + 6).toFixed(2));
      label?.setAttribute("y", (p.y - 7).toFixed(2));
    };
    const io = new IntersectionObserver(([e]) => {
      cancelAnimationFrame(raf);
      if (e.isIntersecting) {
        t0 = performance.now();
        raf = requestAnimationFrame(loop);
      }
    });
    io.observe(path);
    return () => {
      cancelAnimationFrame(raf);
      io.disconnect();
    };
  }, [g]);
  return (
    <svg viewBox="0 0 300 130" className="w-full overflow-visible" role="img" aria-label={`Expected claims rise toward the ${pct(curve.ultimate)} expected ultimate claim rate (curve ${curve.version}).`}>
      <line x1="10" x2="290" y1="112" y2="112" stroke="#c8d0db" />
      <line x1="10" x2="290" y1={g.y(curve.ultimate)} y2={g.y(curve.ultimate)} stroke="#2565a3" strokeDasharray="3 4" strokeOpacity="0.7" />
      <path ref={pathRef} className="vd-curve-line" d={g.d} fill="none" stroke="#0d1524" strokeWidth="2" {...PLOTTED} />
      {g.pts.slice(1).map(([m, r]) => (
        <circle key={m} cx={g.x(m)} cy={g.y(r)} r="2.4" fill="#0d1524" />
      ))}
      <g ref={rider} aria-hidden="true" className="motion-reduce:hidden">
        <circle r="3.4" fill="#2565a3" stroke="#fff" strokeWidth="1.2" cx="10" cy="112" />
        <text className="tabular fill-metar-ink font-mono text-[6.5px]" x="16" y="105" />
      </g>
      <text x="290" y={g.y(curve.ultimate) - 6} textAnchor="end" className="tabular fill-metar-ink text-[7.5px]">
        ultimate {pct(curve.ultimate)}
      </text>
      {[0, 6, 12, 18, 24]
        .filter((m) => m <= g.last)
        .map((m) => (
          <text key={m} x={g.x(m)} y="126" textAnchor="middle" className="tabular fill-slate-500 text-[6.5px]">
            {m === 0 ? "storm" : `M${m}`}
          </text>
        ))}
    </svg>
  );
}

/** What StormCheck learned from Northstar's own history (StormRun.learned): the claim rate and the reroute cut. */
function Learned({ items }: { items: LearnedItem[] }) {
  // the claim-rate curve and the mined reroute cut, by the rule or curve version they back
  const shown = items.filter((i) => /^(LH-|R-MIN)/.test(i.rule_ref ?? "") || /claim rate/i.test(i.text)).slice(0, 2);
  if (!shown.length) return null;
  return (
    <ul className="flex flex-col divide-y divide-cloud-200">
      {shown.map((i) => (
        <li key={i.text} className="py-3.5 first:pt-0 last:pb-0">
          <p className="text-[14.5px] leading-snug text-navy-900">{i.text}</p>
          <p className="mt-1 font-mono text-[11px] text-slate-500">{[i.support, i.rule_ref].filter(Boolean).join(" · ")}</p>
        </li>
      ))}
    </ul>
  );
}

function Figure({ label, children, caption, struck, className }: { label: ReactNode; children: ReactNode; caption: ReactNode; struck?: boolean; className?: string }) {
  return (
    <figure className={cn("vd-figure min-w-0", className)}>
      <p className="micro text-slate-500">{label}</p>
      <div className={cn("relative mt-2 inline-block", struck && "text-slate-400")}>
        {children}
        {struck ? <span className="vd-strike absolute inset-x-[-0.06em] top-[54%] h-[3px] -translate-y-1/2 rounded-full bg-slate-400" aria-hidden="true" /> : null}
      </div>
      <figcaption className="mt-3 max-w-[34ch] text-[14.5px] leading-snug text-slate-600">{caption}</figcaption>
    </figure>
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
  const rate = m.claimRate ?? story.curve?.ultimate ?? null;

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add(MEDIA.motion, () => {
        gsap.from(".vd-reveal", { opacity: 0, y: 24, duration: 0.9, stagger: 0.12, ease: "power3.out", scrollTrigger: { trigger: root.current, start: "top 65%" } });
        gsap.from(".vd-figure", { opacity: 0, y: 30, duration: 0.9, stagger: 0.18, ease: "power3.out", scrollTrigger: { trigger: ".vd-bridge", start: "top 78%" } });
        gsap.from(".vd-strike", { scaleX: 0, transformOrigin: "left center", duration: 0.6, ease: "power2.inOut", stagger: 0.3, delay: 0.9, scrollTrigger: { trigger: ".vd-bridge", start: "top 78%" } });
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

  const big = "display-tight text-[clamp(40px,4.6vw,76px)] leading-none";
  return (
    <section ref={root} aria-label={`The verdict on ${f?.number ?? "the flight"}`} data-section="verdict" className="bg-cloud-50 px-5 py-28 text-navy-900 md:px-16 md:py-36">
      <div className="mx-auto max-w-[1280px]">
        <h2 className="text-balance display vd-reveal text-[clamp(46px,7.2vw,124px)]">
          Not weather.
          <br />
          <span className="text-notweather-ink">Broken plane.</span>
        </h2>
        <p className="vd-reveal mt-8 flex flex-wrap items-center gap-x-3 gap-y-2 font-mono text-[12.5px] text-slate-600 md:text-[13.5px]" data-testid="story-recode">
          <span className="rounded-md bg-notweather-wash px-2 py-1 text-notweather-ink">
            {f?.number ?? <Pending ch={4} tone="light" />} · {d ? `${d.cause.replace(/_/g, "-")} · owed` : <Pending ch={10} tone="light" />}
          </span>
          {d?.recode_label ? <span className="text-navy-900">recoded {d.recode_label}</span> : <Pending ch={12} tone="light" />}
          {d ? (
            <span>
              {d.confidence.label} <b className="text-navy-900">{score === null || score === undefined ? "uncalibrated" : pct(score)}</b>
              {d.reason ? ` · ${d.reason}` : ""}
            </span>
          ) : null}
        </p>

        <div className="vd-bridge mt-20 grid grid-cols-1 items-start gap-x-12 gap-y-14 md:mt-28 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.15fr)_minmax(0,1.3fr)]">
          <Figure label="Cash basis" struck caption="Nothing until a claim is paid.">
            <span className={big}>{m.cash !== null ? eur(m.cash) : <Pending ch={3} tone="light" />}</span>
          </Figure>
          <Figure
            label="Full Art. 7 entitlement"
            struck
            caption={
              <>
                If every passenger claims
                {f && m.band ? (
                  <>
                    : <span className="figure">{count(f.pax)}</span> passengers at <span className="figure">€{m.band}</span>
                    {m.distanceKm ? <> ({count(m.distanceKm)} km)</> : null}
                    {m.reduced ? <>, {count(m.reduced)} partner reroutes at half</> : null}
                  </>
                ) : null}
                .
              </>
            }
          >
            <span className={big}>{m.full !== null ? eur(m.full) : <Pending ch={6} tone="light" />}</span>
          </Figure>
          <Figure
            label="EU261 compensation liability, drafted"
            caption={
              <>
                {rate !== null ? <span className="figure">{pct(rate)}</span> : <Pending ch={3} tone="light" />} expected ultimate claim rate (history to M18 + tail judgment)
                {m.sensitivity !== null ? (
                  <>
                    {" "}
                    · ±5 pp = ±<span className="figure">{eur(m.sensitivity)}</span>
                  </>
                ) : null}
                .
              </>
            }
          >
            {m.drafted !== null ? <RollingNumber text={eur(m.drafted)} className="display text-[clamp(56px,6.6vw,112px)] leading-none text-navy-900" delay={0.5} /> : <Pending ch={6} tone="light" className="h-16" />}
          </Figure>
        </div>

        <div className="mt-20 grid grid-cols-1 gap-10 rounded-2xl bg-white p-4 shadow-[0_0_0_1px_var(--color-cloud-200),0_30px_60px_-40px_rgba(13,21,36,0.25)] sm:p-6 md:mt-24 md:p-10 lg:grid-cols-[1.05fr_1fr] lg:gap-14">
          <div className="vd-reveal flex min-w-0 flex-col gap-6">
            {m.je ? <JournalCard entry={m.je} dense className="shadow-[0_0_0_1px_var(--color-cloud-200)]" /> : <div className="h-[148px] animate-pulse rounded-xl bg-navy-900/5" aria-hidden="true" />}
            <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-6 gap-y-3 text-[14.5px]">
              <dt className="text-slate-500">Confidence</dt>
              <dd className="flex items-center gap-3">
                <span className="relative h-[6px] flex-1 overflow-hidden rounded-full bg-cloud-200">
                  <span className="vd-conf absolute inset-y-0 left-0 rounded-full bg-navy-900" style={{ width: `${(score ?? 0) * 100}%` }} />
                </span>
                <span className="font-mono text-[12.5px]">{score === null || score === undefined ? (d ? "uncalibrated" : "") : `cause-finding ${pct(score)}`}</span>
              </dd>
              <dt className="text-slate-500">Status</dt>
              <dd>{m.statusLine ?? (m.payouts !== null ? `${count(m.payouts)} payouts drafted, pending Claims Lead approval` : <Pending ch={24} tone="light" />)}</dd>
              <dt className="text-slate-500">Storm total</dt>
              <dd>
                {story.run ? <span className="figure">{eur(story.run.liability_drafted_cents)}</span> : <Pending ch={6} tone="light" />} EU261 compensation liability across {story.stormName ?? "the storm"}, held knock-on returns included
              </dd>
            </dl>
          </div>
          <figure className="vd-reveal vd-curve flex min-w-0 flex-col justify-between gap-6">
            {story.curve ? <Curve curve={story.curve} /> : story.curveMissing ? <Learned items={story.learned} /> : <div className="aspect-[300/130] w-full animate-pulse rounded-lg bg-navy-900/5" aria-hidden="true" />}
            <figcaption className="text-[14px] leading-relaxed text-slate-500">
              Claims keep arriving for years. Northstar&rsquo;s own claims history sets the rate{story.curve ? ` (curve ${story.curve.version})` : ""}, and the liability is trued up against it at every month-end.
            </figcaption>
          </figure>
        </div>
      </div>
    </section>
  );
}
