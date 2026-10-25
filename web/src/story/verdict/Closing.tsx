import { useMemo, useRef } from "react";
import { Link } from "react-router";
import { ArrowRight } from "lucide-react";
import { Logo } from "@/components/brand/Logo";
import { count } from "@/lib/format";
import era5Json from "../data/eowyn-era5-12z.json";
import { useStory } from "../data/context";
import { viewFor } from "../data/geo";
import { COAST } from "../data/geo-lines";
import { buildChart, type Era5 } from "../hero/synoptic";
import { gsap, MEDIA, useGSAP } from "../motion/gsap";
import { Pending } from "../ui";

/** The hero's chart again, in ink on paper: Éowyn at 12:00Z on the 24th, drifting slowly behind the numbers. */
function InkChart() {
  const chart = useMemo(() => buildChart(era5Json as Era5), []);
  const v = viewFor(-30, 4, 47, 64, 1.5);
  const h = v.w / 1.5;
  return (
    <svg className="story-ink pointer-events-none absolute inset-y-0 right-0 h-full w-[min(1100px,100%)] opacity-[0.085]" viewBox={`${v.cx - v.w / 2} ${v.cy - h / 2} ${v.w} ${h}`} preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <g fill="none" stroke="#0d1524" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke">
        <path d={COAST} strokeWidth={1} vectorEffect="non-scaling-stroke" />
        {chart.isobars.map((b, i) => (
          <path key={i} d={b.d} strokeWidth={b.hpa % 20 === 0 ? 1.8 : 1} vectorEffect="non-scaling-stroke" />
        ))}
      </g>
    </svg>
  );
}

/** The run in four numbers (from the API), the seats line, and the ways into the product. */
export function Closing() {
  const story = useStory();
  const root = useRef<HTMLElement>(null);
  const c = story.run?.counters;
  const stat = (n: number | undefined) => (n !== undefined ? count(n) : <Pending ch={3} tone="light" />);

  useGSAP(
    () => {
      const mm = gsap.matchMedia();
      mm.add(MEDIA.motion, () => {
        gsap.from(".cl-reveal", { opacity: 0, y: 24, duration: 0.9, stagger: 0.1, ease: "power3.out", scrollTrigger: { trigger: root.current, start: "top 70%" } });
      });
    },
    { scope: root },
  );

  return (
    <section ref={root} aria-label="What StormCheck does" data-section="closing" data-testid="story-closing" className="relative overflow-hidden bg-cloud-50 px-5 pb-14 pt-28 text-navy-900 md:px-16 md:pt-36">
      <InkChart />
      <div className="relative mx-auto max-w-[1280px]">
        <div className="grid grid-cols-1 gap-16 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
          <div>
            <h2 className="text-balance cl-reveal display max-w-[17ch] text-[clamp(38px,4.8vw,84px)]">The case is ready for review.</h2>
            <p className="cl-reveal mt-6 max-w-[52ch] text-[16.5px] leading-relaxed text-slate-600 md:text-[19px]">
              Claims and finance teams get the cause, the evidence and draft amounts in one place. The Claims Lead approves payouts; finance reviews the journal drafts. StormCheck does not release payments.
            </p>
            <div className="cl-reveal mt-10 flex flex-wrap gap-3">
              <Link to="/" className="inline-flex items-center gap-2 rounded-full bg-navy-900 px-6 py-3.5 text-[15.5px] font-medium text-cloud-50 transition-colors hover:bg-navy-800">
                Open the results <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
              <Link to="/pitch" className="rounded-full px-6 py-3.5 text-[15.5px] font-medium shadow-[inset_0_0_0_1.5px_var(--color-navy-900)] transition-colors hover:bg-cloud-100">
                See the pitch
              </Link>
              <Link to="/desk" className="rounded-full px-6 py-3.5 text-[15.5px] font-medium text-slate-600 transition-colors hover:bg-cloud-100 hover:text-navy-900">
                Test a scenario
              </Link>
            </div>
          </div>
          <dl className="cl-reveal grid grid-cols-2 content-start gap-x-8 gap-y-10 lg:pt-4">
            <div>
              <dt className="display-tight text-[clamp(32px,3.4vw,52px)]">{stat(c?.passengers)}</dt>
              <dd className="mt-2 text-[14.5px] text-slate-500">passengers, each assessed under EU261</dd>
            </div>
            <div>
              <dt className="display-tight text-[clamp(32px,3.4vw,52px)]">{stat(c?.cancelled)}</dt>
              <dd className="mt-2 text-[14.5px] text-slate-500">cancellations re-checked against weather and logs</dd>
            </div>
            <div>
              <dt className="display-tight text-[clamp(32px,3.4vw,52px)]">{stat(c?.questions)}</dt>
              <dd className="mt-2 text-[14.5px] text-slate-500">questions for {c?.people !== undefined ? count(c.people) : "the relevant"} reviewers</dd>
            </div>
            <div>
              <dt className="display-tight text-[clamp(32px,3.4vw,52px)]">{stat(c?.repeat_questions)}</dt>
              <dd className="mt-2 text-[14.5px] text-slate-500">repeat questions in this run</dd>
            </div>
          </dl>
        </div>

        <footer className="mt-32 grid grid-cols-1 gap-10 border-t border-cloud-200 pt-10 text-[13.5px] leading-relaxed text-slate-500 md:grid-cols-[auto_1fr_1fr]">
          <div className="flex items-center gap-3 text-navy-900">
            <Logo className="h-6 w-auto" />
            <span className="text-[17px] font-semibold [font-stretch:112%]">StormCheck</span>
          </div>
          <div className="space-y-1">
            <p className="text-navy-900">Real</p>
            <p>Dublin weather: METAR, Iowa Environmental Mesonet. Pressure and wind: ERA5 reanalysis (Copernicus/ECMWF) via Open-Meteo. Satellite: Meteosat infrared 10.8 µm, © EUMETSAT 2025.</p>
            <p>Airport traffic: Eurocontrol. Distances: great circle, Art. 7(4). Law: Regulation (EC) 261/2004 and the CJEU.</p>
          </div>
          <div className="space-y-1">
            <p className="text-navy-900">Simulated</p>
            <p>Northstar Air is fictional. Its schedule, logs, passengers and claims are simulated, including conflicting records and missing signatures.</p>
            <p className="pt-2">Built at Cal Hacks 13.0.</p>
          </div>
        </footer>
      </div>
    </section>
  );
}
