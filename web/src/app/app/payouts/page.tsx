import { Suspense } from "react";
import { PayoutsPage } from "@/components/app/pages/PayoutsPage";

function PayoutsFallback() {
  return (
    <div className="mx-auto max-w-[1280px]">
      <div className="h-8 w-40 animate-pulse rounded bg-fog" />
      <div className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-[76px] animate-pulse rounded-xl bg-white shadow-[0_0_0_1px_#e6e6e0]" />
        ))}
      </div>
      <div className="mt-3 h-[420px] animate-pulse rounded-xl bg-white shadow-[0_0_0_1px_#e6e6e0]" />
    </div>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<PayoutsFallback />}>
      <PayoutsPage />
    </Suspense>
  );
}
