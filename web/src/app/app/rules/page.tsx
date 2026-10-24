import type { Metadata } from "next";
import { RulesPage } from "@/components/app/pages/RulesPage";

export const metadata: Metadata = { title: "Rules" };

export default function Page() {
  return <RulesPage />;
}
