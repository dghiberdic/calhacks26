import { Empty, PageHeader } from "@/components/kit";

export default function StormRunScreen() {
  return (
    <div className="mx-auto max-w-[1280px]">
      <PageHeader title="Storm Run">What StormCheck did overnight, and the 1% it asked about.</PageHeader>
      <Empty title="Being built" className="mt-8">This screen lands with its work package.</Empty>
    </div>
  );
}
