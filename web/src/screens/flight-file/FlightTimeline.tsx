import { useEffect, useMemo, useState, type ReactElement } from "react";
import { scaleLinear, scaleUtc } from "d3-scale";
import { area, curveMonotoneX, line } from "d3-shape";
import type { Flight, MetarObs, StormWindow, TimelineMark } from "@/api/types";
import { gustThreshold } from "@/components/storm/model";
import { useWidth } from "@/components/storm/useWidth";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { VERDICT_COLOR, type VerdictKind } from "@/components/verdict";
import { zulu, zuluDay } from "@/lib/format";
import { cn } from "@/lib/utils";
import { placeLabels, toItems, when, type Item, type Tone } from "./timelineLayout";

const TONE_COLOR: Record<Exclude<Tone, "flight">, string> = {
  ink: "var(--color-navy-900)",
  metar: "var(--color-metar)",
  slate: "var(--color-slate-400)",
};

const colorOf = (it: Item, kind: VerdictKind) => (it.tone === "flight" ? VERDICT_COLOR[kind] : TONE_COLOR[it.tone]);

export function FlightTimeline({ marks, flight, kind, hub, windows = [], metar = [] }: { marks: TimelineMark[]; flight: Flight; kind: VerdictKind; hub: string; windows?: StormWindow[]; metar?: MetarObs[] }) {
  const items = useMemo(() => toItems(marks, flight, hub), [marks, flight, hub]);
  // Starts at 0 so nothing is drawn at a guessed width; the strip turns vertical wherever it is narrow.
  const [ref, width] = useWidth<HTMLDivElement>(0);
  if (!items.length) return <p className="text-[13.5px] text-slate-500">No timeline for this flight.</p>;
  const flightDate = flight.sched_dep.slice(0, 10);
  return (
    <div ref={ref}>
      {width === 0 ? (
        <div className="h-40" />
      ) : width >= 460 ? (
        <Track items={items} width={width} kind={kind} windows={windows} metar={metar} flightDate={flightDate} />
      ) : (
        <VerticalList items={items} kind={kind} windows={windows} flightDate={flightDate} />
      )}
    </div>
  );
}

// ---------- horizontal track ----------
const LANE_H = 50; // a time line plus up to two lines of label
const BAND_H = 64;
const AXIS_H = 28;

/** Re-measure once the web fonts are in: label widths depend on them. */
function useFontsReady() {
  const [ready, setReady] = useState(() => typeof document === "undefined" || document.fonts?.status === "loaded");
  useEffect(() => {
    if (ready || !document.fonts) return;
    let live = true;
    void document.fonts.ready.then(() => live && setReady(true));
    return () => {
      live = false;
    };
  }, [ready]);
  return ready;
}

function Track({ items, width, kind, windows, metar, flightDate }: { items: Item[]; width: number; kind: VerdictKind; windows: StormWindow[]; metar: MetarObs[]; flightDate: string }) {
  useFontsReady();
  const pad = 14;
  const t0 = items[0].at;
  const t1 = items[items.length - 1].at;
  const span = Math.max(t1 - t0, 3 * 3_600_000);
  const x = scaleUtc()
    .domain([new Date(t0 - span * 0.04), new Date(t1 + span * 0.04)])
    .range([pad, width - pad]);
  const [d0, d1] = x.domain().map((d) => d.getTime());

  const bands = windows.map((w) => ({ w, a: Math.max(d0, Date.parse(w.start)), b: Math.min(d1, Date.parse(w.end)) })).filter((b) => b.b > b.a);
  const main = [...bands].sort((p, q) => q.b - q.a - (p.b - p.a))[0];
  // Window marks are the band's own edges once the band is drawn.
  const shown = bands.length ? items.filter((i) => i.key !== "window") : items;

  // METAR gust trace inside the band; the window threshold is read from the window's own definition.
  const pts = metar
    .map((o) => ({ t: Date.parse(o.valid), v: o.gust ?? o.sknt }))
    .filter((p): p is { t: number; v: number } => p.t >= d0 && p.t <= d1 && typeof p.v === "number")
    .sort((a, b) => a.t - b.t);
  const nearestKt = (t: number) => pts.reduce<{ d: number; v: number } | null>((best, p) => (!best || Math.abs(p.t - t) < best.d ? { d: Math.abs(p.t - t), v: p.v } : best), null)?.v ?? null;

  const preliminary = placeLabels(
    shown.map((it) => ({ ...it, cx: x(new Date(it.at)), cy: 0 })),
    width,
    flightDate,
  );
  const lanes = Math.max(1, ...preliminary.placed.map((p) => p.lane + 1));
  const labelsH = lanes * LANE_H;
  const bandTop = labelsH + 10;
  const baseY = bandTop + BAND_H;
  const height = baseY + AXIS_H;
  const maxKt = Math.max(40, ...pts.map((p) => p.v));
  const y = scaleLinear().domain([0, maxKt * 1.12]).range([baseY - 2, bandTop + 8]);
  const gustLine = pts.length > 1 ? line<{ t: number; v: number }>().x((p) => x(new Date(p.t))).y((p) => y(p.v)).curve(curveMonotoneX)(pts) : null;
  const gustArea = pts.length > 1 ? area<{ t: number; v: number }>().x((p) => x(new Date(p.t))).y0(baseY).y1((p) => y(p.v)).curve(curveMonotoneX)(pts) : null;
  const threshold = gustThreshold(windows);
  // METAR marks sit on the gust curve; everything else on the baseline.
  const cyOf = (it: Item) => {
    if (it.key !== "metar") return baseY;
    const kt = nearestKt(it.at);
    return kt === null ? baseY : y(kt);
  };
  const placed = preliminary.placed.map((p) => ({ ...p, cy: cyOf(p.it) }));
  const unplaced = preliminary.unplaced.map((it) => ({ ...it, cy: cyOf(it) }));
  const ticks = x.ticks(width > 860 ? 8 : 5);

  return (
    <div className="relative select-none" style={{ height }} data-testid="flight-timeline">
      <svg width={width} height={height} className="absolute inset-0 overflow-visible" aria-hidden="true">
        <defs>
          <clipPath id="tl-band">
            <rect x={pad} y={bandTop} width={width - pad * 2} height={BAND_H} rx={6} />
          </clipPath>
        </defs>
        <rect x={pad} y={bandTop} width={width - pad * 2} height={BAND_H} rx={6} fill="var(--color-cloud-50)" />
        <g clipPath="url(#tl-band)">
          {bands.map(({ w, a, b }) => (
            <rect key={w.start} x={x(new Date(a))} y={bandTop} width={x(new Date(b)) - x(new Date(a))} height={BAND_H} fill="var(--color-metar-wash)" />
          ))}
          {gustArea ? <path d={gustArea} fill="var(--color-metar)" fillOpacity={0.12} /> : null}
          {gustLine ? <path d={gustLine} fill="none" stroke="var(--color-metar)" strokeWidth={1.4} strokeOpacity={0.9} /> : null}
          {threshold !== null && pts.length > 1 ? <line x1={main ? x(new Date(main.a)) : pad} x2={width - pad} y1={y(threshold)} y2={y(threshold)} stroke="var(--color-metar-ink)" strokeOpacity={0.35} strokeDasharray="3 3" /> : null}
        </g>
        {bands.map(({ w, a, b }) =>
          x(new Date(b)) - x(new Date(a)) > 170 ? (
            <text key={w.start} x={x(new Date(b)) - 7} y={bandTop + 14} textAnchor="end" className="fill-metar-ink text-[10.5px] font-medium tabular-nums" stroke="var(--color-metar-wash)" strokeWidth={3} paintOrder="stroke">
              Storm window {zulu(w.start)}–{zulu(w.end)}
            </text>
          ) : null,
        )}
        {threshold !== null && pts.length > 1 && main && x(new Date(main.a)) - pad > 34 ? (
          <text x={x(new Date(main.a)) - 5} y={y(threshold) + 3.5} textAnchor="end" className="fill-metar-ink text-[10px] tabular-nums" stroke="var(--color-cloud-50)" strokeWidth={3} paintOrder="stroke">
            {threshold} kt
          </text>
        ) : null}
        <line x1={pad} x2={width - pad} y1={baseY} y2={baseY} stroke="var(--color-cloud-300)" />
        {ticks.map((t) => {
          const midnight = t.getUTCHours() === 0 && t.getUTCMinutes() === 0;
          return (
            <g key={t.getTime()}>
              <line x1={x(t)} x2={x(t)} y1={baseY} y2={baseY + 4} stroke="var(--color-cloud-400)" />
              <text x={x(t)} y={baseY + 17} textAnchor="middle" className={cn("text-[10.5px] tabular-nums", midnight ? "fill-slate-600 font-semibold" : "fill-slate-400")}>
                {midnight ? zuluDay(t.toISOString()).split(" ").slice(0, 2).join(" ") : zulu(t.toISOString())}
              </text>
            </g>
          );
        })}
        {unplaced.map((it) => (
          <circle key={`u-${it.iso}-${it.label}`} cx={it.cx} cy={it.cy} r={3} fill={colorOf(it, kind)} fillOpacity={0.75} stroke="white" strokeWidth={1.2} />
        ))}
        {placed.map(({ it, cx, cy, lane }) => {
          const c = colorOf(it, kind);
          const top = labelsH - lane * LANE_H - 3;
          return (
            <g key={`${it.iso}-${it.label}`}>
              <line x1={cx} x2={cx} y1={top} y2={cy} stroke={c} strokeOpacity={it.tone === "flight" ? 0.7 : 0.4} />
              <circle cx={cx} cy={cy} r={it.tone === "flight" ? 5.5 : 4} fill={c} stroke="white" strokeWidth={1.5} />
            </g>
          );
        })}
      </svg>

      {placed.map(({ it, left, w, lane, meta }) => (
        <MarkTip key={`${it.iso}-${it.label}`} it={it} meta={meta}>
          <button
            type="button"
            className="absolute flex flex-col items-start rounded-md px-1.5 py-0.5 text-left outline-none transition-colors hover:bg-cloud-100 focus-visible:shadow-[0_0_0_2px_var(--color-metar)]"
            style={{ left, width: w, top: labelsH - (lane + 1) * LANE_H + 2 }}
          >
            <span className="w-full truncate whitespace-nowrap text-[11px] leading-tight text-slate-400 tabular-nums">{meta}</span>
            <span className={cn("line-clamp-2 w-full text-[12.5px] font-medium leading-[1.25]", it.tone === "flight" && kind === "notweather" ? "text-notweather-ink" : "text-navy-900")}>{it.label}</span>
          </button>
        </MarkTip>
      ))}
      {unplaced.map((it) => (
        <MarkTip key={`u-${it.iso}-${it.label}`} it={it} meta={`${when(it.iso, flightDate)} · ${it.kind}`}>
          <button type="button" aria-label={`${when(it.iso, flightDate)} ${it.kind}: ${it.label}`} className="absolute size-4 -translate-x-1/2 -translate-y-1/2 rounded-full outline-none focus-visible:shadow-[0_0_0_2px_var(--color-metar)]" style={{ left: it.cx, top: it.cy }} />
        </MarkTip>
      ))}
    </div>
  );
}

function MarkTip({ it, meta, children }: { it: Item; meta: string; children: ReactElement }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side="top" className="max-w-[360px] flex-col items-start gap-1 px-3 py-2 text-left">
        <span className="text-[11px] tabular-nums opacity-70">{meta}</span>
        <span className="text-[12.5px] font-medium leading-snug">{it.label}</span>
        {it.text ? <span className={cn("text-[12px] leading-snug opacity-90", it.machine && "font-mono text-[11px] leading-relaxed")}>{it.text}</span> : null}
      </TooltipContent>
    </Tooltip>
  );
}

// ---------- phones ----------
/** The same events top to bottom; the rail turns cool blue while the storm window is open. */
function VerticalList({ items, kind, windows, flightDate }: { items: Item[]; kind: VerdictKind; windows: StormWindow[]; flightDate: string }) {
  const ranges = windows.map((w) => [Date.parse(w.start), Date.parse(w.end)] as const);
  const inWindow = (t: number) => ranges.some(([a, b]) => t >= a && t < b);
  const first = items[0].at;
  const last = items[items.length - 1].at;
  const rows: (Item & { edge?: "close" })[] = [...items];
  // The window's edges, unless the timeline already carries them.
  if (!items.some((i) => i.key === "window")) {
    for (const w of windows) {
      const a = Date.parse(w.start);
      const b = Date.parse(w.end);
      if (a > first && a < last) rows.push({ at: a, iso: w.start, key: "window", kind: "Window", label: "Storm window opens", text: "", machine: false, tone: "metar" });
      if (b > first && b < last) rows.push({ at: b, iso: w.end, key: "window", kind: "Window", label: "Storm window closes", text: "", machine: false, tone: "metar", edge: "close" });
    }
  }
  rows.sort((p, q) => p.at - q.at);
  return (
    <ol className="flex flex-col" data-testid="flight-timeline">
      {rows.map((it, i) => {
        const open = inWindow(it.at) && it.edge !== "close";
        return (
          <li key={`${it.iso}-${it.label}-${i}`} className="grid grid-cols-[64px_14px_minmax(0,1fr)] gap-x-3">
            <span className="pt-0.5 text-right text-[11.5px] leading-tight text-slate-500 tabular-nums">
              {zulu(it.iso)}
              {it.iso.slice(0, 10) !== flightDate ? <span className="block text-[10.5px] text-slate-400">{zuluDay(it.iso).split(" ").slice(0, 2).join(" ")}</span> : null}
            </span>
            <span className="relative flex justify-center">
              <span className={cn("absolute w-[2px]", open ? "bg-metar/60" : "bg-cloud-200", i === 0 ? "top-2" : "top-0", i === rows.length - 1 ? "h-2" : "bottom-0")} aria-hidden="true" />
              <span className="relative mt-1 size-2.5 rounded-full ring-2 ring-white" style={{ background: colorOf(it, kind) }} aria-hidden="true" />
            </span>
            <span className="min-w-0 pb-4">
              <span className="block text-[13.5px] font-medium leading-snug text-navy-900">
                <span className="mr-1.5 text-[11px] font-normal uppercase tracking-[0.06em] text-slate-400">{it.kind}</span>
                {it.label}
              </span>
              {it.text ? <span className={cn("mt-0.5 line-clamp-3 break-words text-[12.5px] leading-relaxed text-slate-600", it.machine && "font-mono text-[11.5px]")}>{it.text}</span> : null}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
