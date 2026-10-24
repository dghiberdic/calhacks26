"use client";

import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { CauseTimeline } from "@/components/app/CauseTimeline";
import { Card, Chip, Kbd } from "@/components/app/ui";
import { RollingNumber } from "@/components/motion/RollingNumber";
import { decide, classifyLog, type Window } from "@/lib/engine";
import { tier } from "@/data/scenario";
import { gibsImage } from "@/data/airports";
import { cn } from "@/lib/cn";

type Report = { t: string; raw: string; kt: number | null; gust: number | null; dir: number | null };
type MetarResponse = { station: string; date: string; reports: Report[]; windows: Window[]; error?: string };

const PRESETS = [
  { icao: "EIDW", name: "Dublin", date: "2025-12-09", note: "Storm Bram" },
  { icao: "EIDW", name: "Dublin", date: "2025-01-24", note: "Storm Éowyn" },
  { icao: "EGLL", name: "Heathrow", date: "2024-01-21", note: "Storm Isha" },
  { icao: "KBOS", name: "Boston", date: "2023-12-18", note: "Boston windstorm" },
  { icao: "KSFO", name: "San Francisco", date: "2023-03-21", note: "SF bomb cyclone" },
];

const LOGS = [
  { label: "Hydraulic leak", text: "07:55Z HYD G RSVR LO LVL. LEAK FOUND AT ENG 1 EDP CASE DRAIN LINE. A/C U/S PENDING PART." },
  { label: "Bird strike", text: "16:10Z BIRDSTRIKE ON APPROACH. ENG 2 FAN BLADE DAMAGE. A/C U/S FOR BORESCOPE." },
  { label: "Crew out of hours", text: "05:40Z CAPT/FO FDP EXCEEDED AFTER STORM RECOVERY SECTOR. NO STANDBY CREW." },
  { label: "Nothing logged", text: "" },
];

const ease = [0.16, 1, 0.3, 1] as const;

export default function Desk() {
  const [icao, setIcao] = useState("EIDW");
  const [date, setDate] = useState("2025-12-09");
  const [sched, setSched] = useState("21:30");
  const [pax, setPax] = useState(212);
  const [km, setKm] = useState(4802);
  const [log, setLog] = useState(LOGS[0].text);
  const [limitInput, setLimitInput] = useState("40");
  const [limit, setLimit] = useState(40);
  const [data, setData] = useState<MetarResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  // Debounce + clamp the limit so a half-typed number never asks for a 10 kt storm.
  useEffect(() => {
    const t = setTimeout(() => {
      const n = Number(limitInput);
      if (Number.isFinite(n) && n > 0) setLimit(Math.min(90, Math.max(15, Math.round(n))));
    }, 350);
    return () => clearTimeout(t);
  }, [limitInput]);

  // A new station or day clears the old chart instead of showing it under the new heading.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset when the query identity changes
    setData(null);
  }, [icao, date]);

  useEffect(() => {
    if (!/^[A-Z0-9]{3,4}$/.test(icao) || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return;
    const ctl = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- loading flag for the live METAR fetch
    setLoading(true);
    setFailed(null);
    fetch(`/api/metar?station=${icao}&date=${date}&limit=${limit}`, { signal: ctl.signal })
      .then(async (r) => {
        const j = (await r.json()) as MetarResponse & { error?: string };
        if (ctl.signal.aborted) return;
        if (!r.ok) {
          setFailed(j.error ?? `Request failed (${r.status})`);
          setData(null);
          return;
        }
        setData(j);
      })
      .catch(() => {
        if (!ctl.signal.aborted) setFailed("Couldn’t reach the METAR archive");
      })
      .finally(() => {
        if (!ctl.signal.aborted) setLoading(false);
      });
    return () => ctl.abort();
  }, [icao, date, limit]);

  const series = useMemo(() => {
    if (!data?.reports?.length) return undefined;
    const byHour = new Map<number, { kt: number; gust: number }>();
    for (const r of data.reports) {
      const h = Number(r.t.slice(0, 2));
      const cur = byHour.get(h) ?? { kt: 0, gust: 0 };
      byHour.set(h, { kt: Math.max(cur.kt, r.kt ?? 0), gust: Math.max(cur.gust, r.gust ?? r.kt ?? 0) });
    }
    return Array.from({ length: 24 }, (_, h) => ({ h, ...(byHour.get(h) ?? { kt: 0, gust: 0 }) }));
  }, [data]);

  const windows = data?.windows ?? [];
  const res = decide({ windows, sched, log });
  const fault = classifyLog(log);
  const perPax = tier(km);
  const exposure = res.owed ? pax * perPax : 0;
  const provision = Math.round(exposure * 0.35);
  const near = (t: string) => {
    if (!data?.reports?.length) return null;
    const m = (s: string) => Number(s.slice(0, 2)) * 60 + Number(s.slice(3, 5));
    return data.reports.reduce((a, b) => (Math.abs(m(b.t) - m(t)) < Math.abs(m(a.t) - m(t)) ? b : a));
  };
  const atSched = near(sched);
  const orbit = gibsImage(icao, date);
  const atFault = fault.time ? near(fault.time) : null;

  return (
    <div className="mx-auto max-w-[1280px]">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="display-tight text-[30px]">Judge&rsquo;s desk</h1>
          <p className="mt-1 max-w-[62ch] text-[15px] text-graphite">
            Pick any real airport and date. StormCheck pulls that day&rsquo;s METAR live, finds the storm window, and decides who is owed. Change the tech log and watch the money move.
          </p>
        </div>
        <span className="rounded-full bg-front-wash px-3 py-1.5 text-[13px] font-medium text-front">Sandbox · no real money</span>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-[380px_minmax(0,1fr)]">
        <Card className="flex flex-col gap-5 p-5">
          <div>
            <p className="mb-2 text-[13px] text-graphite">Try a real storm</p>
            <div className="flex flex-wrap gap-1.5">
              {PRESETS.map((p) => (
                <button
                  key={p.icao + p.date}
                  type="button"
                  onClick={() => (setIcao(p.icao), setDate(p.date))}
                  className={cn("rounded-full px-3 py-1.5 text-[13px] transition-colors", icao === p.icao && date === p.date ? "bg-ink text-chart" : "bg-chart hover:bg-fog")}
                >
                  {p.note}
                </button>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="text-[13px] text-graphite">
              Airport (ICAO)
              <input value={icao} onChange={(e) => setIcao(e.target.value.toUpperCase().slice(0, 4))} className="mt-1 w-full rounded-lg bg-chart px-3 py-2 font-mono text-[15px] text-ink outline-none focus:shadow-[0_0_0_1.5px_#2b59c3]" />
            </label>
            <label className="text-[13px] text-graphite">
              Date (UTC)
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="mt-1 w-full rounded-lg bg-chart px-3 py-2 font-mono text-[14px] text-ink outline-none focus:shadow-[0_0_0_1.5px_#2b59c3]" />
            </label>
            <label className="text-[13px] text-graphite">
              Departure (Z)
              <input value={sched} onChange={(e) => setSched(e.target.value)} className="mt-1 w-full rounded-lg bg-chart px-3 py-2 font-mono text-[15px] text-ink outline-none focus:shadow-[0_0_0_1.5px_#2b59c3]" />
            </label>
            <label className="text-[13px] text-graphite">
              Gust limit (kt)
              <input type="number" inputMode="numeric" value={limitInput} min={15} max={90} onChange={(e) => setLimitInput(e.target.value)} className="mt-1 w-full rounded-lg bg-chart px-3 py-2 font-mono text-[15px] text-ink outline-none focus:shadow-[0_0_0_1.5px_#2b59c3]" />
            </label>
            <label className="text-[13px] text-graphite">
              Passengers
              <input type="number" value={pax} onChange={(e) => setPax(Number(e.target.value))} className="mt-1 w-full rounded-lg bg-chart px-3 py-2 font-mono text-[15px] text-ink outline-none focus:shadow-[0_0_0_1.5px_#2b59c3]" />
            </label>
            <label className="text-[13px] text-graphite">
              Distance (km)
              <input type="number" value={km} onChange={(e) => setKm(Number(e.target.value))} className="mt-1 w-full rounded-lg bg-chart px-3 py-2 font-mono text-[15px] text-ink outline-none focus:shadow-[0_0_0_1.5px_#2b59c3]" />
            </label>
          </div>
          <div>
            <div className="mb-2 flex items-baseline justify-between">
              <label htmlFor="desk-log" className="text-[13px] text-graphite">
                Tech-log line
              </label>
              <span className="text-[12px] text-graphite">
                edit freely, <Kbd>HH:MMZ</Kbd> sets the time
              </span>
            </div>
            <textarea
              id="desk-log"
              value={log}
              onChange={(e) => setLog(e.target.value)}
              rows={4}
              placeholder="Nothing logged"
              className="w-full rounded-lg bg-chart p-3 font-mono text-[13px] leading-relaxed outline-none focus:shadow-[0_0_0_1.5px_#2b59c3]"
            />
            <div className="mt-2 flex flex-wrap gap-1.5">
              {LOGS.map((l) => (
                <button key={l.label} type="button" onClick={() => setLog(l.text)} className={cn("rounded-full px-3 py-1.5 text-[13px] transition-colors", log === l.text ? "bg-ink text-chart" : "bg-chart hover:bg-fog")}>
                  {l.label}
                </button>
              ))}
            </div>
          </div>
          {orbit && (
            <figure className="m-0">
              <div className="relative overflow-hidden rounded-lg bg-night">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img key={orbit.url} src={orbit.url} alt={`NASA MODIS Terra image around ${orbit.airport.name} on ${date}`} className="aspect-[16/10] w-full object-cover" loading="lazy" />
                <span className="pointer-events-none absolute left-1/2 top-1/2 h-7 w-7 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-[#ff7a5c]" aria-hidden="true" />
                <span className="pointer-events-none absolute left-1/2 top-1/2 h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[#ff7a5c]" aria-hidden="true" />
              </div>
              <figcaption className="mt-2 text-[12.5px] text-graphite">
                {orbit.airport.name} from orbit that day. NASA MODIS Terra, late-morning pass.
              </figcaption>
            </figure>
          )}
        </Card>

        <div className="flex flex-col gap-4">
          <Card className="p-5">
            <div className="mb-1 flex items-baseline justify-between gap-3">
              <h2 className="text-[15px] font-semibold">
                {icao} on {date}
              </h2>
              <span className="text-[13px] text-graphite">
                {loading ? "Pulling METAR…" : failed ? failed : data?.error ? data.error : `${data?.reports.length ?? 0} reports · ${data && "source" in data && String((data as { source?: string }).source).startsWith("bundled") ? "bundled copy of the IEM archive" : "Iowa Environmental Mesonet"}`}
              </span>
            </div>
            <CauseTimeline
              height={180}
              series={series}
              limit={limit}
              windowStart={windows[0]?.start ?? null}
              windowEnd={windows.length ? windows[windows.length - 1].end : null}
              marks={[...(fault.time ? [{ t: fault.time, kind: "fault" as const, label: `${fault.time} log` }] : []), { t: sched, kind: res.owed ? ("departure" as const) : ("weather" as const), label: "Flight" }]}
            />
            <div className="mt-3 space-y-1.5 font-mono text-[12.5px] leading-relaxed">
              {atFault && (
                <p>
                  <span className="text-owed-ink">at fault </span>
                  {atFault.raw}
                </p>
              )}
              {atSched && (
                <p>
                  <span className="text-graphite">at departure </span>
                  {atSched.raw}
                </p>
              )}
            </div>
          </Card>

          <AnimatePresence mode="wait">
            <motion.div key={res.verdict + res.confidence} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.3, ease }}>
              <Card className={cn("p-6", res.owed && "bg-[#fff8f6]")}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className={cn("display-tight text-[26px]", res.owed && "text-[#a32e19]")}>
                    {{ technical: "Technical fault. Owed.", weather: "Weather. Nothing owed.", extraordinary: "Extraordinary. Nothing owed.", review: `Asking ${res.routeTo ?? "a person"}.` }[res.verdict]}
                  </p>
                  <Chip kind={res.verdict === "technical" ? "technical" : res.verdict === "review" ? "review" : "weather"}>
                    {res.confidence}% · {res.rule}
                  </Chip>
                </div>
                <ul className="mt-4 space-y-1.5 text-[15px]">
                  {res.reasons.map((r) => (
                    <li key={r} className="flex gap-2.5">
                      <span className="mt-[9px] h-1 w-1 shrink-0 rounded-full bg-ink" />
                      {r}
                    </li>
                  ))}
                </ul>
              </Card>
            </motion.div>
          </AnimatePresence>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Card className="p-5">
              <p className="text-[13.5px] text-graphite">
                Exposure · {pax} × €{perPax}
              </p>
              <RollingNumber key={`e${exposure}`} value={exposure} prefix="€" trigger={null} className="display-tight mt-2 text-[34px]" />
            </Card>
            <Card className="p-5">
              <p className="text-[13.5px] text-graphite">Provision at 35% claim rate</p>
              <RollingNumber key={`p${provision}`} value={provision} prefix="€" trigger={null} className={cn("display-tight mt-2 text-[34px]", provision && "text-owed-ink")} />
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
