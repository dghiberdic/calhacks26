import { Empty, PageHeader } from "@/components/kit";

export default function DeskScreen() {
  return (
    <div className="mx-auto max-w-[1280px]">
      <PageHeader title="Judge's Desk">Your airport, your date, real METAR.</PageHeader>
      <Empty title="Being built" className="mt-8">This screen lands with its work package.</Empty>
    </div>
  );
}
