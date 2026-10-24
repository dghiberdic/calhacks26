import { Empty, PageHeader } from "@/components/kit";

export default function CloseScreen() {
  return (
    <div className="mx-auto max-w-[1280px]">
      <PageHeader title="Liability & Close">The EU261 compensation liability, rolled forward and tied to GL 2140.</PageHeader>
      <Empty title="Being built" className="mt-8">This screen lands with its work package.</Empty>
    </div>
  );
}
