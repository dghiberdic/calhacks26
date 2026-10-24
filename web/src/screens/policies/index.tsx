import { Empty, PageHeader } from "@/components/kit";

export default function PoliciesScreen() {
  return (
    <div className="mx-auto max-w-[1280px]">
      <PageHeader title="Policies">Learned, ruled, rejected and regulation.</PageHeader>
      <Empty title="Being built" className="mt-8">This screen lands with its work package.</Empty>
    </div>
  );
}
