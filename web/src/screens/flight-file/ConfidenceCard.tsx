import type { ReactNode } from "react";
import type { Confidence } from "@/api/types";
import { MicroLabel, StatusChip } from "@/components/chips";
import { Explain, WhatsThis } from "@/components/explain";
import { Details, ScoreBar } from "@/components/kit";
import type { Term } from "@/lib/glossary";
import { pct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { featureLabel } from "./lib";

const CAP_TERM: Record<string, Term> = { "no-precedent": "no-precedent", "sources-disagree": "sources-disagree" };

/** The few inputs that moved the score most, in words: contributions when the model sends them, else the flags that are on. */
function topDrivers(confidence: Confidence, n = 3): string[] {
  const ranked = confidence.contributions
    ? Object.entries(confidence.contributions)
        .filter(([, v]) => typeof v === "number" && v > 0)
        .sort((a, b) => b[1] - a[1])
        .map(([k]) => k)
    : Object.entries(confidence.features ?? {})
        .filter(([, v]) => v === 1)
        .map(([k]) => k);
  return ranked.slice(0, n).map(featureLabel);
}

/**
 * How sure the engine is, said plainly: the score bar, the two or three things that drove it, and any cap.
 * Every input and the calibration version sit behind Details. No model for the kind → "uncalibrated", hatched.
 */
export function ConfidenceCard({ confidence, className }: { confidence: Confidence; className?: string }) {
  const caps = confidence.caps ?? [];
  const drivers = topDrivers(confidence);
  return (
    <section aria-labelledby="confidence-title" className={cn("rounded-xl bg-card p-5 shadow-[0_0_0_1px_var(--color-cloud-200),0_1px_2px_rgba(13,21,36,0.04)]", className)}>
      <h2 id="confidence-title" className="flex items-center gap-1.5">
        <MicroLabel>How sure it is</MicroLabel>
        <WhatsThis term="confidence" className="text-slate-500" />
      </h2>
      {/* The score itself sits by the verdict; this bar shows it, and the lines below say why. */}
      <ScoreBar score={confidence.score} className="mt-3 h-2" />
      <span className="sr-only">{confidence.score === null ? "uncalibrated" : pct(confidence.score)}</span>
      {confidence.score === null ? <p className="mt-2 text-[12.5px] text-slate-500">No calibrated model for {confidence.kind} decisions yet, so no score is claimed.</p> : null}
      {drivers.length ? (
        <p className="mt-3 text-[13px] leading-relaxed text-slate-600">
          Mostly from: {drivers.map((d, i) => <Driver key={d} text={d} last={i === drivers.length - 1} />)}
        </p>
      ) : null}
      {caps.length ? (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="text-[12.5px] text-slate-500">Held down by</span>
          {caps.map((cap) => {
            const word = cap.replace(/^capped:/, "");
            const term = CAP_TERM[word];
            return (
              <StatusChip key={cap} tone="outline" dot={false} className="h-5 text-[10.5px]">
                {term ? <Explain term={term}>{word.replace(/-/g, " ")}</Explain> : word.replace(/-/g, " ")}
              </StatusChip>
            );
          })}
        </div>
      ) : null}
      <Details summary="Every input" className="mt-3">
        <FeatureBars features={confidence.features} />
        <p className="mt-3 font-mono text-[10.5px] text-slate-400">calibration {confidence.calibration_version}</p>
      </Details>
    </section>
  );
}

function Driver({ text, last }: { text: string; last: boolean }) {
  return (
    <>
      <span className="font-medium text-navy-900">{text.charAt(0).toLowerCase() + text.slice(1)}</span>
      {last ? "." : ", "}
    </>
  );
}

function fmt(v: number, signed: boolean) {
  const abs = Math.abs(v);
  const body = Number.isInteger(abs) ? String(abs) : abs < 10 ? abs.toFixed(2).replace(/0$/, "") : abs.toFixed(1);
  if (!signed) return body;
  return v > 0 ? `+${body}` : v < 0 ? `−${body}` : body;
}

/** Units for the raw measures among the calibration features. */
const UNIT: Record<string, string> = { window_margin_h: "h", window_margin_min: "min", months_since_last_claim: "mo", cohort_age_months: "mo" };
const MEASURE = /(_h|_min|_count|_months?|_km|_days?|_kt)$|^precedent/;

/**
 * Feature bars. Two encodings, picked from the values themselves:
 * - weights or contributions (a negative, or a fraction): bars by magnitude, growing left (against) or right (for);
 * - raw model inputs: flags as full or empty bars with yes/no, measures as their value with a unit.
 */
function FeatureBars({ features, className }: { features: Record<string, number>; className?: string }) {
  const entries = Object.entries(features ?? {}).filter(([, v]) => typeof v === "number" && Number.isFinite(v));
  if (!entries.length) return null;
  const weighted = entries.some(([, v]) => v < 0) || entries.some(([k, v]) => v > 0 && v < 1 && !MEASURE.test(k));
  return (
    <div className={className}>
      {weighted && entries.some(([, v]) => v < 0) ? (
        <p className="text-right text-[11px] text-slate-400">
          against · <span className="text-navy-900">for</span>
        </p>
      ) : null}
      {weighted ? <Weighted entries={entries} /> : <Inputs entries={entries} />}
    </div>
  );
}

function Row({ name, bar, value, muted }: { name: string; bar: ReactNode; value: string; muted?: boolean }) {
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_76px_44px] items-center gap-3 text-[12.5px]">
      <span className={cn("min-w-0 truncate", muted ? "text-slate-400" : "text-slate-600")} title={name}>
        {name}
      </span>
      <span className="relative h-1.5 rounded-full bg-cloud-100" aria-hidden="true">
        {bar}
      </span>
      <span className={cn("text-right text-[12px] tabular-nums", muted ? "text-slate-400" : "font-medium text-navy-900")}>{value}</span>
    </li>
  );
}

function Weighted({ entries }: { entries: [string, number][] }) {
  const diverging = entries.some(([, v]) => v < 0);
  const max = Math.max(...entries.map(([, v]) => Math.abs(v)), 1e-9);
  const sorted = [...entries].sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]) || a[0].localeCompare(b[0]));
  return (
    <ul className="mt-2 flex flex-col gap-2">
      {sorted.map(([key, v]) => {
        const share = Math.min(1, Math.abs(v) / max);
        return (
          <Row
            key={key}
            name={featureLabel(key)}
            muted={v === 0}
            value={fmt(v, diverging)}
            bar={
              diverging ? (
                <>
                  <span className="absolute inset-y-[-3px] left-1/2 w-px bg-cloud-300" />
                  <span className={cn("absolute inset-y-0 rounded-full", v >= 0 ? "left-1/2 bg-navy-800" : "right-1/2 bg-slate-400")} style={{ width: `${share * 50}%` }} />
                </>
              ) : (
                <span className="absolute inset-y-0 left-0 rounded-full bg-navy-800" style={{ width: `${share * 100}%` }} />
              )
            }
          />
        );
      })}
    </ul>
  );
}

function Inputs({ entries }: { entries: [string, number][] }) {
  const flags = entries.filter(([k, v]) => !MEASURE.test(k) && (v === 0 || v === 1));
  const measures = entries.filter((e) => !flags.includes(e));
  const on = flags.filter(([, v]) => v === 1).sort(([a], [b]) => a.localeCompare(b));
  const off = flags.filter(([, v]) => v === 0).sort(([a], [b]) => a.localeCompare(b));
  return (
    <ul className="mt-2 flex flex-col gap-2">
      {on.map(([key]) => (
        <Row key={key} name={featureLabel(key)} value="yes" bar={<span className="absolute inset-0 rounded-full bg-navy-800" />} />
      ))}
      {measures.map(([key, v]) => (
        <Row key={key} name={featureLabel(key)} value={`${fmt(v, false)}${UNIT[key] ? ` ${UNIT[key]}` : ""}`} bar={<span className="absolute inset-0 rounded-full bg-[repeating-linear-gradient(90deg,var(--color-cloud-300)_0_2px,transparent_2px_5px)]" />} />
      ))}
      {off.map(([key]) => (
        <Row key={key} name={featureLabel(key)} value="no" muted bar={null} />
      ))}
    </ul>
  );
}
