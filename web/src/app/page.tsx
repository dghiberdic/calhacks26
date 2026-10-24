import { SmoothScroll } from "@/components/motion/SmoothScroll";
import { DepartureBoard } from "@/components/landing/DepartureBoard";
import { StormWindow } from "@/components/landing/StormWindow";
import { StormDay } from "@/components/landing/hero/StormDay";
import { AircraftBlueprint } from "@/components/landing/AircraftBlueprint";
import { Verdict } from "@/components/landing/Verdict";
import { Trace } from "@/components/landing/Trace";
import { AskOnce } from "@/components/landing/AskOnce";
import { Closing } from "@/components/landing/Closing";
import { SiteNav } from "@/components/landing/SiteNav";
import { MorningAfter } from "@/components/landing/MorningAfter";

export default function Home() {
  return (
    <SmoothScroll>
      <SiteNav />
      <main id="main" className="bg-night text-[#eef1f4]">
        <StormDay />

        <section className="px-5 pb-28 pt-36 md:px-16">
          <h2 className="display mb-6 max-w-[16ch] text-[clamp(36px,5.6vw,92px)]">14 flights cancelled. All coded weather.</h2>
          <p className="mb-16 max-w-[44ch] text-[17px] leading-relaxed text-haze md:text-[19px]">
            The morning after, the cause codes say nobody is owed anything. StormCheck checks every one against the weather and the aircraft&rsquo;s logs.
          </p>
          <DepartureBoard />
        </section>

        <section className="px-5 pt-24 md:px-16">
          <h2 className="display max-w-[15ch] text-[clamp(36px,5.6vw,92px)]">Weather has a window.</h2>
          <p className="mt-6 max-w-[46ch] text-[17px] leading-relaxed text-haze md:text-[19px]">
            Hour by hour, the airport&rsquo;s own METAR reports say when the gusts were above limits. Thirteen departures fall inside. One doesn&rsquo;t.
          </p>
          <StormWindow />
        </section>

        <AircraftBlueprint />

        <MorningAfter />

        <div className="bg-chart text-ink">
          <section className="px-5 py-36 md:px-16">
            <Verdict />
          </section>
          <section className="px-5 py-36 md:px-16">
            <Trace />
          </section>
          <section className="px-5 py-36 md:px-16">
            <AskOnce />
          </section>
          <section className="px-5 pb-16 pt-36 md:px-16">
            <Closing />
          </section>
        </div>
      </main>
    </SmoothScroll>
  );
}
