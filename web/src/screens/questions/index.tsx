import { Empty, PageHeader } from "@/components/kit";

export default function QuestionsScreen() {
  return (
    <div className="mx-auto max-w-[1280px]">
      <PageHeader title="Questions">One question per pattern, to the right person.</PageHeader>
      <Empty title="Being built" className="mt-8">This screen lands with its work package.</Empty>
    </div>
  );
}
