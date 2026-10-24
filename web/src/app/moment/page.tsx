import type { Metadata } from "next";
import { MomentFilm } from "@/components/moment/MomentFilm";

export const metadata: Metadata = { title: "The moment · StormCheck" };

export default function MomentPage() {
  return <MomentFilm />;
}
