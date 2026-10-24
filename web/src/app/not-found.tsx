import type { Metadata } from "next";
import Link from "next/link";
import { FlapText } from "@/components/landing/SplitFlap";

export const metadata: Metadata = { title: "Diverted · StormCheck" };

/** One row of the departure board, flipping to DIVERTED. */
export default function NotFound() {
  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-12 bg-night px-5 text-[#eef1f4]">
      <div className="rounded-md bg-[#0d1117] px-4 py-5 font-mono text-[clamp(18px,3vw,30px)] md:px-7">
        {/* the columns are in the board's em, so only the labels get the small size */}
        <div className="mb-3 grid grid-cols-[5.2em_4.2em_8.2em] gap-x-[0.9em] px-1 text-[#8e9aa8] [&>span]:text-[12px] [&>span]:uppercase [&>span]:tracking-[0.1em]" aria-hidden="true">
          <span>Time</span>
          <span>Page</span>
          <span>Status</span>
        </div>
        <div className="grid grid-cols-[5.2em_4.2em_8.2em] items-center gap-x-[0.9em] px-1">
          <FlapText text="--:--" width={5} />
          <FlapText text="404" width={4} delay={120} />
          <FlapText text="DIVERTED" width={8} delay={260} className="flap-alert" />
        </div>
      </div>
      <div className="text-center">
        <h1 className="display text-[clamp(32px,4.4vw,60px)]">This page isn&rsquo;t on the board.</h1>
        <p className="mt-4 text-[17px] text-haze">The link may be old, or the page has moved.</p>
        <div className="mt-9 flex flex-wrap justify-center gap-3">
          <Link href="/" className="rounded-full bg-white px-5 py-2.5 text-[15px] font-medium text-ink transition-colors hover:bg-[#e2e6ea]">
            Back to the storm night
          </Link>
          <Link href="/app" className="rounded-full px-5 py-2.5 text-[15px] font-medium shadow-[inset_0_0_0_1.5px_currentColor] transition-colors hover:bg-white/10">
            Open the app
          </Link>
        </div>
      </div>
    </main>
  );
}
