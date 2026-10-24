import { useMemo, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { geoAzimuthalEquidistant, geoGraticule10, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";
import landTopo from "world-atlas/land-110m.json";
import type { StormRun } from "@/api/types";
import { airport as referenceAirport, iataOf } from "@/lib/airports";
import { cn } from "@/lib/utils";
import type { VerdictKind } from "../verdict";
import { stormFacts } from "./model";
import { useWidth } from "./useWidth";

// Natural Earth 110m land, bundled: no tiles, no network, nothing to fail offline (plan §2 Stack).
const topo = landTopo as unknown as Topology;
const LAND = feature(topo, topo.objects.land as GeometryCollection);

const COLOR: Record<VerdictKind, string> = {
  notweather: "var(--color-notweather)",
  held: "var(--color-held)",
  weather: "var(--color-weather)",
  operated: "var(--color-slate-400)",
  pending: "var(--color-cloud-400)",
};
const RANK: Record<VerdictKind, number> = { notweather: 4, held: 3, weather: 2, operated: 1, pending: 0 };

type Box = { x0: number; y0: number; x1: number; y1: number };
type Label = { x: number; y: number; anchor: "start" | "middle" | "end" };
const overlaps = (a: Box, b: Box) => a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;
const CHAR_W = 6.2; // Geist Mono at 10px

/**
 * Greedy label placement: the most serious verdicts and the farthest airports pick first (right, left, above,
 * below their dot); a label that fits nowhere is left to the hover card, so the Europe cluster stays legible.
 */
function placeLabels(points: { code: string; x: number; y: number }[], hub: [number, number], obstacles: Box[], W: number, H: number) {
  const placed = [...obstacles, ...points.map((p) => ({ x0: p.x - 3, y0: p.y - 3, x1: p.x + 3, y1: p.y + 3 }))];
  const out = new Map<string, Label>();
  for (const p of points) {
    const w = p.code.length * CHAR_W;
    const candidates: (Label & { box: Box; dir: [number, number] })[] = [
      { x: p.x + 6, y: p.y + 3.5, anchor: "start", dir: [1, 0], box: { x0: p.x + 5, y0: p.y - 5.5, x1: p.x + 7 + w, y1: p.y + 5.5 } },
      { x: p.x - 6, y: p.y + 3.5, anchor: "end", dir: [-1, 0], box: { x0: p.x - 7 - w, y0: p.y - 5.5, x1: p.x - 5, y1: p.y + 5.5 } },
      { x: p.x, y: p.y - 7, anchor: "middle", dir: [0, -1], box: { x0: p.x - w / 2 - 1, y0: p.y - 16.5, x1: p.x + w / 2 + 1, y1: p.y - 5 } },
      { x: p.x, y: p.y + 14, anchor: "middle", dir: [0, 1], box: { x0: p.x - w / 2 - 1, y0: p.y + 5, x1: p.x + w / 2 + 1, y1: p.y + 16.5 } },
    ];
    // Away from the hub first: the route's own line runs towards it.
    const len = Math.hypot(hub[0] - p.x, hub[1] - p.y) || 1;
    const toHub = [(hub[0] - p.x) / len, (hub[1] - p.y) / len];
    candidates.sort((a, b) => a.dir[0] * toHub[0] + a.dir[1] * toHub[1] - (b.dir[0] * toHub[0] + b.dir[1] * toHub[1]));
    const fit = candidates.find((c) => c.box.x0 > 2 && c.box.x1 < W - 2 && c.box.y0 > 2 && c.box.y1 < H - 2 && !placed.some((b) => overlaps(b, c.box)));
    if (!fit) continue;
    placed.push(fit.box);
    out.set(p.code, { x: fit.x, y: fit.y, anchor: fit.anchor });
  }
  return out;
}

type Props = { run: StormRun; compact?: boolean; tone?: "dark" | "light"; className?: string; animate?: boolean; onSelectFlight?: (flightId: string) => void };

/**
 * Every arc leaves the hub, so an azimuthal-equidistant projection centred on it draws each route as
 * the straight great-circle line the Art. 7(4) distance is measured along.
 */
export function RouteMap({ run, compact, tone = "dark", className, animate = true, onSelectFlight }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>(560);
  const reduce = useReducedMotion();
  const play = animate && !reduce;
  const [hover, setHover] = useState<string | null>(null);
  const facts = useMemo(() => stormFacts(run), [run]);
  // Coordinates from the API (StormRun.airports, D0a) first; the bundled reference table covers older servers.
  const served = useMemo(() => new Map((run.airports ?? []).map((a) => [a.iata, a])), [run.airports]);
  const airport = (code: string) => served.get(code) ?? referenceAirport(code);
  const hub = airport(facts.hub) ?? airport(iataOf(run.station));

  // One arc per destination; its colour is the most serious verdict among the flights on that route.
  const routes = useMemo(() => {
    const by = new Map<string, { code: string; verdict: VerdictKind; flights: { id: string; number: string; verdict: VerdictKind }[]; pax: number }>();
    for (const t of facts.ticks) {
      const f = t.row.flight;
      const other = f.origin === facts.hub ? f.dest : f.origin;
      const cur = by.get(other) ?? { code: other, verdict: t.verdict, flights: [], pax: 0 };
      cur.flights.push({ id: f.id, number: f.number, verdict: t.verdict });
      cur.pax += f.pax;
      if (RANK[t.verdict] > RANK[cur.verdict]) cur.verdict = t.verdict;
      by.set(other, cur);
    }
    return [...by.values()].filter((r) => airport(r.code)).sort((a, b) => RANK[a.verdict] - RANK[b.verdict]);
  }, [facts]);

  const H = compact ? 240 : Math.round(Math.min(480, Math.max(300, width < 720 ? width * 0.7 : width * 0.42)));
  const W = Math.max(width, 280);

  const { path, project, graticule } = useMemo(() => {
    if (!hub) return { path: null, project: null, graticule: "" };
    const pts = routes.map((r) => airport(r.code)!).concat(hub);
    const projection = geoAzimuthalEquidistant().rotate([-hub.lon, -hub.lat]).clipAngle(150);
    projection.fitExtent(
      [
        [28, 28],
        [W - 28, H - 28],
      ],
      { type: "MultiPoint", coordinates: pts.map((p) => [p.lon, p.lat]) },
    );
    const p = geoPath(projection);
    return { path: p, project: (lon: number, lat: number) => projection([lon, lat]) as [number, number], graticule: p(geoGraticule10()) ?? "" };
  }, [hub, routes, W, H]);

  if (!hub || !path || !project) return <div ref={ref} className={cn("h-[240px] w-full", className)} />;
  const [hx, hy] = project(hub.lon, hub.lat);
  const land = path(LAND) ?? "";
  const dark = tone === "dark";
  const hubLabel: Box = { x0: hx - 11, y0: hy - 19, x1: hx + 12 + hub.iata.length * 6.8, y1: hy + 11 };
  const labels = placeLabels(
    [...routes]
      .map((r) => {
        const a = airport(r.code)!;
        const [x, y] = project(a.lon, a.lat);
        return { code: r.code, x, y, rank: RANK[r.verdict], far: Math.hypot(x - hx, y - hy) };
      })
      .sort((a, b) => b.rank - a.rank || b.far - a.far),
    [hx, hy],
    [hubLabel],
    W,
    H,
  );

  return (
    <div ref={ref} className={cn("relative w-full", className)}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Routes from ${hub.name}, coloured by verdict`} className="block">
        <path d={graticule} fill="none" stroke={dark ? "rgba(200,208,219,0.06)" : "rgba(13,21,36,0.05)"} />
        <path d={land} fill={dark ? "#152035" : "#e4e9f0"} stroke={dark ? "#22314b" : "#d3dae4"} strokeWidth={0.6} />
        {routes.map((r, i) => {
          const a = airport(r.code)!;
          const [ax, ay] = project(a.lon, a.lat);
          const active = hover === r.code;
          const strong = r.verdict === "notweather";
          return (
            <g key={r.code} onPointerEnter={() => setHover(r.code)} onPointerLeave={() => setHover(null)} onClick={() => onSelectFlight?.(r.flights[0].id)} className={onSelectFlight ? "cursor-pointer" : undefined}>
              <motion.line
                x1={hx}
                y1={hy}
                x2={ax}
                y2={ay}
                stroke={COLOR[r.verdict]}
                strokeWidth={strong ? 2.4 : active ? 2 : 1.3}
                strokeOpacity={strong || active ? 1 : 0.75}
                strokeLinecap="round"
                initial={{ pathLength: play ? 0 : 1 }}
                animate={{ pathLength: 1 }}
                transition={{ delay: play ? 0.4 + i * 0.05 : 0, duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
              />
              {strong ? <circle cx={ax} cy={ay} r={9} fill="var(--color-notweather)" opacity={0.18} /> : null}
              <circle cx={ax} cy={ay} r={strong ? 3.6 : 2.6} fill={COLOR[r.verdict]} />
              {labels.get(r.code) || active ? (
                <text
                  x={labels.get(r.code)?.x ?? ax + 6}
                  y={labels.get(r.code)?.y ?? ay + 3.5}
                  textAnchor={labels.get(r.code)?.anchor ?? "start"}
                  fontSize={10}
                  className="font-mono"
                  fill={strong ? "var(--color-notweather)" : active ? (dark ? "#eef2f7" : "var(--color-navy-900)") : dark ? "var(--color-cloud-400)" : "var(--color-slate-500)"}
                  fontWeight={strong || active ? 700 : 400}
                >
                  {r.code}
                </text>
              ) : null}
              {/* generous hit target */}
              <line x1={hx} y1={hy} x2={ax} y2={ay} stroke="transparent" strokeWidth={12} />
            </g>
          );
        })}
        <circle cx={hx} cy={hy} r={5} fill={dark ? "#eef2f7" : "var(--color-navy-900)"} />
        <circle cx={hx} cy={hy} r={10} fill="none" stroke={dark ? "rgba(238,242,247,0.35)" : "rgba(13,21,36,0.25)"} />
        <text x={hx + 12} y={hy - 9} fontSize={10.5} className="font-mono" fontWeight={700} fill={dark ? "#eef2f7" : "var(--color-navy-900)"}>
          {hub.iata}
        </text>
      </svg>
      {hover ? (
        <div className={cn("pointer-events-none absolute left-3 top-3 rounded-lg px-3 py-2 text-[12px] shadow-lg", dark ? "bg-navy-950/95 text-cloud-100 ring-1 ring-white/10" : "bg-white text-navy-900 ring-1 ring-cloud-200")}>
          {(() => {
            const r = routes.find((x) => x.code === hover);
            if (!r) return null;
            return (
              <>
                <div className="font-mono text-[11.5px] font-bold">
                  {hub.iata}–{r.code} · {airport(r.code)?.name}
                </div>
                <div className="mt-0.5 font-mono text-[11px] opacity-75">{r.flights.map((f) => f.number).join(" · ")}</div>
              </>
            );
          })()}
        </div>
      ) : null}
    </div>
  );
}

/** The map's key, in the plan's words. */
export function RouteLegend({ tone = "dark", className }: { tone?: "dark" | "light"; className?: string }) {
  const items: [VerdictKind, string][] = [
    ["notweather", "not weather"],
    ["held", "held"],
    ["weather", "weather"],
    ["operated", "operated"],
  ];
  return (
    <ul className={cn("flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px]", tone === "dark" ? "text-cloud-500" : "text-slate-500", className)}>
      {items.map(([k, label]) => (
        <li key={k} className="flex items-center gap-1.5">
          <span className="h-[2px] w-4 rounded-full" style={{ background: COLOR[k] }} aria-hidden="true" />
          {label}
        </li>
      ))}
    </ul>
  );
}
