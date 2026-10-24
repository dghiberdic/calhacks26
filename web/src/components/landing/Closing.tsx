import Link from "next/link";
import { Logo } from "@/components/ui/Logo";

export function Closing() {
  return (
    <div className="mx-auto max-w-[1400px]">
      <div className="grid grid-cols-1 gap-16 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <div>
          <h2 className="display text-[clamp(44px,6vw,104px)] text-ink">Two seats, filled by 9&nbsp;AM.</h2>
          <p className="mt-6 max-w-[46ch] text-[17px] leading-relaxed text-graphite md:text-[19px]">
            StormCheck works as Northstar&rsquo;s Passenger Claims Accountant and Revenue Accountant. It drafts every payout and the provision. It never pays. The Claims Lead, Legal and the Controller stay human.
          </p>
          <div className="mt-10 flex flex-wrap gap-3">
            <Link href="/app" className="rounded-full bg-ink px-6 py-3.5 text-[16px] font-medium text-chart transition-colors hover:bg-[#2a2f36]">
              Open the storm night
            </Link>
            <Link href="/app/desk" className="rounded-full px-6 py-3.5 text-[16px] font-medium text-ink shadow-[inset_0_0_0_1.5px_var(--color-ink)] transition-colors hover:bg-fog">
              Bring your own storm
            </Link>
          </div>
        </div>
        <dl className="grid grid-cols-2 content-start gap-x-8 gap-y-10 lg:pt-6">
          {[
            ["2,910", "passengers sorted by 09:00Z"],
            ["13 of 14", "cancellations confirmed as weather"],
            ["1", "question asked, to the right person"],
            ["100%", "of drafted euros traced to evidence"],
          ].map(([v, l]) => (
            <div key={l}>
              <dt className="display-tight text-[clamp(32px,3.4vw,52px)] text-ink">{v}</dt>
              <dd className="mt-2 text-[15px] text-graphite">{l}</dd>
            </div>
          ))}
        </dl>
      </div>

      <footer className="mt-40 grid grid-cols-1 gap-10 border-t border-rule pt-10 text-[14px] text-graphite md:grid-cols-[auto_1fr_1fr]">
        <div className="flex items-center gap-3 text-ink">
          <Logo className="h-6 w-auto" />
          <span className="text-[17px] font-semibold [font-stretch:112%]">StormCheck</span>
        </div>
        <div className="space-y-1">
          <p className="text-ink">Real data</p>
          <p>Pressure and wind: ERA5 reanalysis (Copernicus/ECMWF) via Open-Meteo.</p>
          <p>Imagery: EUMETSAT MTG GeoColour and true colour (contains modified EUMETSAT data, 2025).</p>
          <p>Airport weather: METAR archive, Iowa Environmental Mesonet.</p>
          <p>Law: Regulation (EC) 261/2004; CJEU C-549/07.</p>
        </div>
        <div className="space-y-1">
          <p className="text-ink">Simulated</p>
          <p>Northstar Air is fictional. Its passengers, tech logs and claims are simulated, played by language-model personas. A person can take over any of them.</p>
          <p className="pt-3">Built at Cal Hacks 13.0, San Francisco.</p>
        </div>
      </footer>
    </div>
  );
}
