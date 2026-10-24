"use client";

import Link from "next/link";

/** If something on the page throws, say so plainly and offer a way on — never a blank screen. */
export default function Error({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="flex min-h-svh flex-col items-center justify-center bg-night px-5 text-center text-[#eef1f4]">
      <p className="label text-[#ff9a80]">Unscheduled stop</p>
      <h1 className="display mt-4 text-[clamp(32px,4.4vw,60px)]">Something on this page failed to load.</h1>
      <p className="mt-4 text-[17px] text-haze">Nothing was changed. Try again, or go on to the app.</p>
      <div className="mt-9 flex flex-wrap justify-center gap-3">
        <button type="button" onClick={reset} className="rounded-full bg-white px-5 py-2.5 text-[15px] font-medium text-ink transition-colors hover:bg-[#e2e6ea]">
          Try again
        </button>
        <Link href="/app" className="rounded-full px-5 py-2.5 text-[15px] font-medium shadow-[inset_0_0_0_1.5px_currentColor] transition-colors hover:bg-white/10">
          Open the app
        </Link>
      </div>
    </main>
  );
}
