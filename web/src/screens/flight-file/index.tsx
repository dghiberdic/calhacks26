import { Empty, PageHeader } from "@/components/kit";

export default function FlightFileScreen() {
  return (
    <div className="mx-auto max-w-[1280px]">
      <PageHeader title="Flight File">Why each flight got its verdict.</PageHeader>
      <Empty title="Being built" className="mt-8">This screen lands with its work package.</Empty>
    </div>
  );
}
