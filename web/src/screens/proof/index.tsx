import { Empty, PageHeader } from "@/components/kit";

export default function ProofScreen() {
  return (
    <div className="mx-auto max-w-[1280px]">
      <PageHeader title="Proof">How we know it works.</PageHeader>
      <Empty title="Being built" className="mt-8">This screen lands with its work package.</Empty>
    </div>
  );
}
