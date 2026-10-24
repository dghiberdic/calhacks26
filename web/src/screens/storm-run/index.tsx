import { useMemo } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ArrowRight } from "lucide-react";
import { useCfo, useStormRun, useStorms } from "@/api/queries";
import { ErrorNote, Panel, Shimmer } from "@/components/kit";
import { RouteLegend, RouteMap } from "@/components/storm/RouteMap";
import { airport, iataOf } from "@/lib/airports";
import { HERO_STORM } from "@/lib/storms";
import { Hero } from "./Hero";
import { FeedPanel, LearnsStrip, LiabilityTiles, QuestionsPreview } from "./Sections";

const airportName = (station: string) => airport(iataOf(station))?.name.replace(/ Airport$/, "") ?? station;

/** Storm Run (home): what StormCheck did overnight, and the 1% it asked about. */
export default function StormRunScreen() {
  const params = useParams();
  const storms = useStorms();
  const stormId = params.stormId ? decodeURIComponent(params.stormId) : (storms.data?.find((s) => s.id === HERO_STORM)?.id ?? storms.data?.[0]?.id);
  const run = useStormRun(stormId);
  const cfo = useCfo();
  const navigate = useNavigate();
  const openFlight = (id: string) => navigate(`/flights/${encodeURIComponent(id)}`);

  // The storm's own feed, scoped by the server. The stream refetches it as things happen; the whole live trace
  // (every storm) belongs on Trace.
  const feed = useMemo(() => [...(run.data?.feed ?? [])].sort((a, b) => b.seq - a.seq), [run.data?.feed]);
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

      <LearnsStrip run={data} />

      <div className="grid gap-3 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
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

      <section className="rounded-2xl bg-navy-900 p-4 text-cloud-50 shadow-[0_0_0_1px_var(--color-navy-800)] md:p-6" aria-label="Routes">
        <div className="flex flex-wrap items-end justify-between gap-3 px-1">
          <div>
            <h2 className="text-[15px] font-semibold">Every route leaves {airportName(data.station)}</h2>
            <p className="mt-0.5 text-[12.5px] text-cloud-500">Great-circle distance from the hub, the one Art. 7(4) measures. Hover a route for its flights.</p>
          </div>
          <RouteLegend tone="dark" />
        </div>
        <RouteMap run={data} tone="dark" onSelectFlight={openFlight} className="mt-3" />
      </section>
    </div>
  );
}
