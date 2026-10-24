import { SmoothScroll } from "@/components/motion/SmoothScroll";
import { DepartureBoard } from "@/components/landing/DepartureBoard";
import { StormWindow } from "@/components/landing/StormWindow";
import { StormMap } from "@/components/landing/hero/StormMap";

export default function Home() {
  return (
    <SmoothScroll>
      <main className="bg-night text-[#eef1f4]">
        <StormMap />

        <section className="px-5 py-32 md:px-16">
          <p className="label mb-10 text-mist">01 · the morning after</p>
          <h2 className="display mb-14 max-w-[16ch] text-[clamp(36px,5.6vw,92px)]">14 flights cancelled. All coded weather.</h2>
          <DepartureBoard />
        </section>

        <section className="px-5 md:px-16">
          <StormWindow />
        </section>

        <section className="h-[80vh]" />
      </main>
    </SmoothScroll>
  );
}
