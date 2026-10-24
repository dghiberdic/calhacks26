"use client";

import { useMemo } from "react";
import { LAND_ATLANTIC } from "@/data/geo/land";
import { AIRPORTS, K, greatCircle, pathOf, toMap } from "@/lib/geo";
import { FLIGHTS } from "@/data/scenario";
import { cn } from "@/lib/cn";

/** Chart-paper map of the routes out of Dublin. Highlights follow the table. */
export function RouteMap({ active, onHover }: { active?: string | null; onHover?: (id: string | null) => void }) {
  const routes = useMemo(() => {
    const byDest = new Map<string, { dest: string; flights: string[]; owed: boolean; d: string }>();
    for (const f of FLIGHTS) {
      const a = AIRPORTS[f.dest];
      if (!a) continue;
      const r = byDest.get(f.dest) ?? { dest: f.dest, flights: [], owed: false, d: pathOf(greatCircle(AIRPORTS.DUB, a, 64)) };
      r.flights.push(f.id);
      r.owed ||= f.verdict === "technical";
      byDest.set(f.dest, r);
    }
    return [...byDest.values()].sort((a, b) => Number(a.owed) - Number(b.owed));
  }, []);
  const vb = { x: -127 * K, y: -66, w: 146 * K, h: 44 };
  const dub = toMap(AIRPORTS.DUB.lon, AIRPORTS.DUB.lat);
  const activeDest = FLIGHTS.find((f) => f.id === active)?.dest;

  return (
    <svg viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`} preserveAspectRatio="xMidYMid meet" className="h-full w-full" role="img" aria-label="Routes from Dublin to the cancelled flights' destinations">
      <defs>
        <pattern id="rm-grid" width={10 * K} height="10" patternUnits="userSpaceOnUse" x={0} y={0}>
          <path d={`M${10 * K} 0 L0 0 0 10`} fill="none" stroke="#121417" strokeOpacity="0.06" strokeWidth="0.12" />
        </pattern>
      </defs>
      <rect x={vb.x} y={vb.y} width={vb.w} height={vb.h} fill="url(#rm-grid)" />
      <path d={LAND_ATLANTIC} fill="#ecece6" stroke="#b9bab3" strokeWidth="0.12" />
      {routes.map((r) => {
        const on = activeDest === r.dest;
        return (
          <path
            key={r.dest}
            d={r.d}
            fill="none"
            stroke={r.owed ? "#e04a2f" : on ? "#121417" : "#7c8794"}
            strokeOpacity={r.owed || on ? 1 : 0.55}
            strokeWidth={r.owed ? 0.55 : on ? 0.5 : 0.3}
            strokeDasharray={r.owed ? undefined : "0.9 0.7"}
            className="cursor-pointer transition-[stroke-opacity] duration-300"
            onMouseEnter={() => onHover?.(r.flights[r.flights.length - 1])}
            onMouseLeave={() => onHover?.(null)}
          />
        );
      })}
      {routes.map((r) => {
        const a = AIRPORTS[r.dest];
        const [x, y] = toMap(a.lon, a.lat);
        return (
          <g key={r.dest} className={cn("transition-opacity", activeDest && activeDest !== r.dest && !r.owed && "opacity-40")}>
            <circle cx={x} cy={y} r="0.55" fill={r.owed ? "#e04a2f" : "#121417"} />
            <text x={x + 0.9} y={y - 0.7} fontSize="1.6" className="font-mono" fill={r.owed ? "#c2381f" : "#3e444b"}>
              {r.dest}
            </text>
          </g>
        );
      })}
      <circle cx={dub[0]} cy={dub[1]} r="0.8" fill="#121417" />
      <circle cx={dub[0]} cy={dub[1]} r="1.6" fill="none" stroke="#121417" strokeWidth="0.15" />
      <text x={dub[0] + 1.4} y={dub[1] + 2.4} fontSize="1.7" className="font-mono" fill="#121417">
        DUB
      </text>
    </svg>
  );
}
