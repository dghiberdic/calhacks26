"use client";

/** Inside the app the shell stays put; only the page area shows this. */
export default function AppError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="mx-auto flex max-w-[520px] flex-col items-start py-24">
      <p className="text-[13px] font-medium text-owed-ink">This page didn&rsquo;t load</p>
      <h1 className="display-tight mt-2 text-[30px]">Something went wrong here.</h1>
      <p className="mt-3 text-[15px] text-graphite">Nothing was approved, sent or changed. The rest of the app still works.</p>
      <button type="button" onClick={reset} className="mt-6 rounded-lg bg-ink px-4 py-2.5 text-[14px] font-semibold text-chart">
        Try again
      </button>
    </div>
  );
}
