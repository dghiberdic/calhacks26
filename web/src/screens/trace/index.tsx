import { Empty, PageHeader } from "@/components/kit";

export default function TraceScreen() {
  return (
    <div className="mx-auto max-w-[1280px]">
      <PageHeader title="Trace">Commits, blame, access and controls.</PageHeader>
      <Empty title="Being built" className="mt-8">This screen lands with its work package.</Empty>
    </div>
  );
}
