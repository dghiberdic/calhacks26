import { useMemo } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ArrowRight } from "lucide-react";
import { useCfo, useStormRun, useStorms } from "@/api/queries";
import { mergeFeed, useLiveFeed } from "@/api/stream";
import { ErrorNote, Panel, Shimmer } from "@/components/kit";
import { RouteLegend, RouteMap } from "@/components/storm/RouteMap";
import { HERO_STORM } from "@/lib/storms";
import { Hero } from "./Hero";
import { FeedPanel, LearnsStrip, LiabilityTiles, QuestionsPreview } from "./Sections";

/** Storm Run (home): what StormCheck did overnight, and the 1% it asked about. */
export default function StormRunScreen() {
  const params = useParams();
  const storms = useStorms();
  const stormId = params.stormId ? decodeURIComponent(params.stormId) : (storms.data?.find((s) => s.id === HERO_STORM)?.id ?? storms.data?.[0]?.id);
  const run = useStormRun(stormId);
  const cfo = useCfo();
  const live = useLiveFeed((s) => s.events);
  const navigate = useNavigate();
  const openFlight = (id: string) => navigate(`/flights/${encodeURIComponent(id)}`);

  const feed = useMemo(() => mergeFeed(run.data?.feed ?? [], live), [run.data?.feed, live]);
  const recoded = run.data?.flights.find((r) => r.decision?.recoded)?.flight.number ?? null;

  if (run.isError || storms.isError) {
    return (
      <div className="mx-auto max-w-[1280px]">
        <ErrorNote error={run.error ?? storms.error} onRetry={() => void (run.refetch(), storms.refetch())} />
      </div>
    );
  }
  if (!run.data) {
    return (
      <div className="mx-auto flex max-w-[1280px] flex-col gap-3">
        <Shimmer className="h-[520px] rounded-2xl" />
        <div className="grid gap-3 md:grid-cols-3">
          <Shimmer className="h-40" />
          <Shimmer className="h-40" />
          <Shimmer className="h-40" />
        </div>
      </div>
    );
  }

  const data = run.data;
  return (
    <div className="mx-auto flex max-w-[1280px] flex-col gap-3">
      <Hero run={data} onSelectFlight={openFlight} />

      <LiabilityTiles run={data} cfo={cfo.data} recodedFlight={recoded} />

      <div className="grid gap-3 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <section className="rounded-xl bg-navy-900 p-4 text-cloud-50 shadow-[0_0_0_1px_var(--color-navy-800)]" aria-label="Routes">
          <div className="flex items-center justify-between gap-3 px-1">
            <h2 className="text-[14.5px] font-semibold">Every route leaves {data.station === "EIDW" ? "Dublin" : data.station}</h2>
            <RouteLegend tone="dark" />
          </div>
          <RouteMap run={data} tone="dark" onSelectFlight={openFlight} className="mt-2" />
        </section>
        <LearnsStrip run={data} />
      </div>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,6fr)_minmax(0,6fr)]">
        <Panel
          title="The 1% it asked about"
          actions={
            <Link to="/questions" className="inline-flex items-center gap-1 text-[12.5px] font-medium text-metar-ink hover:underline">
              Questions <ArrowRight className="size-3.5" aria-hidden="true" />
            </Link>
          }
        >
          <QuestionsPreview questions={data.questions} />
        </Panel>
        <FeedPanel events={feed} />
      </div>
    </div>
  );
}
