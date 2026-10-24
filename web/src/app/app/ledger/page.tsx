import type { Metadata } from "next";
import { LedgerPage } from "@/components/app/pages/LedgerPage";

export const metadata: Metadata = { title: "Ledger" };

export default function Page() {
  return <LedgerPage />;
}
