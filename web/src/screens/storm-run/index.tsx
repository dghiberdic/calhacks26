import { useMemo } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ArrowRight } from "lucide-react";
import { useCfo, useEffort, useFlightFile, useLearning, useQuestions, useStormRun, useStorms } from "@/api/queries";
import { useSession } from "@/app/session";
import { ErrorNote, Panel, Shimmer } from "@/components/kit";
import { RouteLegend, RouteMap } from "@/components/storm/RouteMap";
import { isOutage, mainWindowOf } from "@/components/storm/model";
import { airport, iataOf } from "@/lib/airports";
import { count } from "@/lib/format";
import { HERO_STORM } from "@/lib/storms";
import { AskedAgainBanner } from "@/screens/questions/AskedAgain";
import { reuseFor } from "./effort";
import { Hero } from "./Hero";
import { FeedPanel, LearnsStrip, LiabilityTiles, QuestionsPreview } from "./Sections";
import { WithoutStormCheck } from "./WithoutStormCheck";
import { draftedLiability } from "@/screens/flight-file/lib";

const airportName = (station: string) => airport(iataOf(station))?.name.replace(/ Airport$/, "") ?? station;

/** Storm Run: results first, then the cases needing a human decision. */
export default function StormRunScreen() {
  const params = useParams();
  const storms = useStorms();
  const stormId = params.stormId ? decodeURIComponent(params.stormId) : (storms.data?.find((s) => s.id === HERO_STORM)?.id ?? storms.data?.[0]?.id);
  const run = useStormRun(stormId);
  const recodedRow = run.data?.flights.find((row) => row.decision?.recoded);
  const focusFile = useFlightFile(recodedRow?.flight.id);
  const cfo = useCfo();
  // Pitch insights (additive routes): a server or recording without them answers 404 and they stay hidden.
  const effort = useEffort(run.data && !run.data.effort ? run.data.id : undefined);
  const learning = useLearning();
  const navigate = useNavigate();
  const role = useSession((s) => s.role);
  const openQs = useQuestions("open");
  // Asked again past a rule's scope: said here too, with the one-click widen, while it is still open. The open
  // list is this seat's; another seat's question shows from the run (with a "View as" to widen it).
  const askedAgain = useMemo(() => {
    const open = new Map((openQs.data ?? []).map((q) => [q.id, q]));
    return (run.data?.questions ?? []).flatMap((q) => {
      const live = open.get(q.id);
      if (live?.asked_again) return [live];
      if (!live && q.asked_again && q.routed_to !== role && q.status !== "answered") return [q];
      return [];
    });
  }, [run.data?.questions, openQs.data, role]);
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
  const estimate = data.effort ?? effort.data ?? null;
  return (
    <div className="mx-auto flex max-w-[1280px] flex-col gap-3">
      <Hero run={data} onSelectFlight={openFlight} reuse={reuseFor(learning.data, data.id)} focusLiability={focusFile.data ? draftedLiability(focusFile.data.journal_preview ?? []) : null} />

      <LiabilityTiles run={data} cfo={cfo.data} recodedFlight={recoded} />

      {estimate ? <WithoutStormCheck effort={estimate} noun={isOutage(mainWindowOf(data.windows)) ? "power cut" : "storm"} /> : null}

      <LearnsStrip run={data} />

      <div className="grid gap-3 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <Panel
          title="Needs a human decision"
          actions={
            <Link to="/questions" className="inline-flex items-center gap-1 text-[12.5px] font-medium text-metar-ink hover:underline">
              Review questions <ArrowRight className="size-3.5" aria-hidden="true" />
            </Link>
          }
        >
          <p className="-mt-1 mb-3 text-[13px] text-slate-500">
            {count(data.questions.length)} {data.questions.length === 1 ? "question" : "questions"} routed to Claims, Legal or Finance. Their approved rulings can be reused for matching cases.
          </p>
          {askedAgain.map((q) => (
            <AskedAgainBanner key={q.id} question={q} canAnswer={role === q.routed_to} boxed className="mb-3" />
          ))}
          <QuestionsPreview questions={data.questions} />
        </Panel>
        <FeedPanel events={feed} />
      </div>

      <section className="rounded-2xl bg-navy-900 p-4 text-cloud-50 shadow-[0_0_0_1px_var(--color-navy-800)] md:p-6" aria-label="Routes">
        <div className="flex flex-wrap items-end justify-between gap-3 px-1">
          <div>
            <h2 className="text-[15px] font-semibold">Routes connected to {airportName(data.station)}</h2>
            <p className="mt-0.5 text-[12.5px] text-cloud-500">Great-circle routes, not recorded flight paths. Select a route to inspect its flights.</p>
          </div>
          <RouteLegend tone="dark" />
        </div>
        <RouteMap run={data} tone="dark" onSelectFlight={openFlight} className="mt-3" />
      </section>
    </div>
  );
}
