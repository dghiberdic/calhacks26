import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { useReducedMotion } from "motion/react";
import { ArrowRight, Check, CircleSlash, Timer } from "lucide-react";
import { useLiveFeed } from "@/api/stream";
import type { Fact, InjectRequest, InjectResponse, TraceEvent } from "@/api/types";
import { MicroLabel, StatusChip } from "@/components/chips";
import { TIER_NAME } from "@/components/evidence";
import { FeedRow, Panel } from "@/components/kit";
import { verdictChip } from "@/components/verdict";
import { count, eur, pct, shortId, zuluDay } from "@/lib/format";
import { cn } from "@/lib/utils";
import { placeSpans } from "./spans";
import { type FlightSnapshot, flightOf } from "./state";
import { KIND_BY_ID, kindChip } from "./templates";

/** "flight:NS31@2025-01-24" → "NS31"; "coupon:NS31@2025-01-24:14C" → "NS31 · 14C". */
const subjectLabel = (subject: string) => {
  const [type, ...rest] = subject.split(":");
  const id = rest.join(":");
  return id ? `${type === "flight" || type === "coupon" ? "" : `${type} `}${shortId(id)}` : subject;
};

function valueText(field: string, value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number" && /_cents$/.test(field)) return eur(value);
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value)) return zuluDay(value);
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map((v) => valueText(field, v)).join(", ");
  if (typeof value === "object") {
    const o = value as Record<string, unknown>;
    // Money as written in the document: { currency, amount_cents }.
    if (typeof o.amount_cents === "number") {
      const cur = typeof o.currency === "string" ? o.currency.toUpperCase() : "EUR";
      return cur === "EUR" ? eur(o.amount_cents, { cents: o.amount_cents % 100 !== 0 }) : `${cur === "GBP" ? "£" : `${cur} `}${(o.amount_cents / 100).toLocaleString("en-IE", { minimumFractionDigits: o.amount_cents % 100 ? 2 : 0 })}`;
    }
    return Object.entries(o)
      .map(([k, v]) => `${k.replace(/_/g, " ")} ${valueText(k, v)}`)
      .join(" · ");
  }
  return String(value);
}

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);

export function InjectResult({
  request,
  response,
  startSeq,
  before,
  after,
}: {
  request: InjectRequest;
  response: InjectResponse;
  startSeq: number;
  before: Record<string, FlightSnapshot | null>;
  after: Record<string, FlightSnapshot | null> | null;
}) {
  const [hot, setHot] = useState<number | null>(null);
  const text = response.source.text ?? request.text;
  const facts = response.facts;
  const { segments, unplaced, placed } = useMemo(() => placeSpans(text, facts), [text, facts]);
  const mono = KIND_BY_ID[request.kind]?.mono ?? true;
  const extractors = [...new Set(facts.map((f) => f.extractor))];
  const fallback = !!response.fallback_used;
  const dropped = response.dropped_unverifiable;

  // The last segment of each fact's first range carries its number.
  const markerAt = useMemo(() => {
    const out = new Map<number, number[]>();
    const seen = new Set<number>();
    segments.forEach((seg, i) => {
      for (const k of seg.keys) {
        const next = segments[i + 1];
        if (!seen.has(k) && !(next && next.keys.includes(k))) {
          seen.add(k);
          out.set(i, [...(out.get(i) ?? []), k]);
        }
      }
    });
    return out;
  }, [segments]);

  return (
    <div className="@container flex flex-col gap-3" data-testid="inject-result" data-source-id={response.source.id}>
      <Panel padded={false}>
        <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
          <div className="min-w-0">
            <MicroLabel>
              Read by {fallback ? "the labelled regex fallback" : "the Reader"} · {count(facts.length)} {plural(facts.length, "fact", "facts")} kept
            </MicroLabel>
            <h3 className="mt-1 text-[16px] font-semibold text-navy-900">{response.message ?? response.source.title}</h3>
            {response.message && response.source.title ? <p className="mt-0.5 text-[12.5px] text-slate-500">{response.source.title}</p> : null}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <StatusChip tone="outline" dot={false}>
              {kindChip(response.source.kind)}
            </StatusChip>
            <StatusChip tone={response.source.trust_tier === 1 ? "ink" : "slate"} dot={false} title={TIER_NAME[response.source.trust_tier]}>
              T{response.source.trust_tier}
              {TIER_NAME[response.source.trust_tier] ? ` · ${TIER_NAME[response.source.trust_tier].split(" · ")[0]}` : ""}
            </StatusChip>
            <StatusChip tone="outline" dot={false} title={response.source.sha256}>
              sha256 {response.source.sha256.slice(0, 8)}
            </StatusChip>
            {(response.source.acl_tags ?? []).map((t) => (
              <StatusChip key={t} tone="outline" dot={false}>
                {t}
              </StatusChip>
            ))}
          </div>
        </div>

        {fallback ? (
          <p className="mx-5 mt-3 flex items-center gap-2 rounded-lg bg-cloud-50 px-3 py-2 text-[13px] text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-200)]" data-testid="inject-fallback">
            <Timer className="size-4 shrink-0 text-slate-500" aria-hidden="true" />
            Reader timed out; used the labelled regex fallback.
            <span className="font-mono text-[11.5px] text-slate-500">{extractors.find((e) => e.startsWith("fallback")) ?? "fallback:regex@1"}</span>
          </p>
        ) : null}

        <div className="grid gap-0 @3xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
          {/* The document, with every quoted span lit. */}
          <div className="min-w-0 px-5 pb-5 pt-4">
            <div className="flex items-center justify-between gap-2">
              <MicroLabel>The document</MicroLabel>
              <span className="text-[11.5px] text-slate-400">Lit: the words each fact quotes</span>
            </div>
            <div
              className={cn(
                "mt-2 max-h-[360px] overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-cloud-25 px-4 py-3 text-navy-900 shadow-[inset_0_0_0_1px_var(--color-cloud-200)]",
                mono ? "font-mono text-[12.5px] leading-[1.75]" : "text-[14px] leading-[1.7]",
              )}
              data-testid="inject-document"
            >
              {segments.map((seg, i) =>
                seg.keys.length ? (
                  <mark
                    key={i}
                    onPointerEnter={() => setHot(seg.keys[0])}
                    onPointerLeave={() => setHot(null)}
                    className={cn(
                      "rounded-[3px] px-[1px] text-navy-900 transition-colors",
                      seg.keys.length > 1 ? "bg-metar/30" : "bg-metar/[0.17]",
                      "shadow-[inset_0_-2px_0_var(--color-metar)]",
                      hot !== null && seg.keys.includes(hot) && "bg-metar/40 shadow-[inset_0_-2px_0_var(--color-metar-ink)]",
                      hot !== null && !seg.keys.includes(hot) && "opacity-60",
                    )}
                    data-span-for={seg.keys.join(" ")}
                  >
                    {seg.text}
                    {(markerAt.get(i) ?? []).map((k) => (
                      <sup key={k} className="ml-[1px] select-none font-mono text-[9px] font-bold text-metar-ink" aria-hidden="true">
                        {k + 1}
                      </sup>
                    ))}
                  </mark>
                ) : (
                  <span key={i}>{seg.text}</span>
                ),
              )}
            </div>
            <p className={cn("mt-2.5 flex items-start gap-2 text-[13px]", dropped ? "text-navy-900" : "text-slate-500")} data-testid="inject-dropped">
              {dropped ? <CircleSlash className="mt-0.5 size-4 shrink-0 text-slate-500" aria-hidden="true" /> : <Check className="mt-0.5 size-4 shrink-0 text-slate-400" aria-hidden="true" />}
              {dropped
                ? `${count(dropped)} ${plural(dropped, "fact", "facts")} didn't quote the text verbatim and ${plural(dropped, "was", "were")} dropped.`
                : "Every fact kept quotes the text word for word."}
            </p>
          </div>

          {/* The facts, each tied to its span. */}
          <div className="min-w-0 border-t border-cloud-100 px-5 pb-5 pt-4 @3xl:border-l @3xl:border-t-0">
            <MicroLabel>Facts kept · {count(facts.length)}</MicroLabel>
            {facts.length ? (
              <ol className="mt-2 flex flex-col" data-testid="inject-facts">
                {facts.map((f, i) => (
                  <FactRow key={f.id} fact={f} n={i + 1} hot={hot === i} dim={hot !== null && hot !== i} placed={placed.has(i)} unplaced={unplaced.includes(i)} onHover={(on) => setHot(on ? i : null)} />
                ))}
              </ol>
            ) : (
              <p className="mt-2 text-[13px] leading-relaxed text-slate-500">Nothing in the text could be tied to a span, so nothing was recorded. Instructions inside documents are content, never commands.</p>
            )}
            {extractors.length ? (
              <p className="mt-3 font-mono text-[11px] leading-relaxed text-slate-400">
                extractor {extractors.join(" · ")}
              </p>
            ) : null}
          </div>
        </div>
      </Panel>

      <WhatChanged response={response} startSeq={startSeq} before={before} after={after} />
    </div>
  );
}

function FactRow({ fact, n, hot, dim, unplaced, onHover }: { fact: Fact; n: number; hot: boolean; dim: boolean; placed: boolean; unplaced: boolean; onHover: (on: boolean) => void }) {
  return (
    <li
      onPointerEnter={() => onHover(true)}
      onPointerLeave={() => onHover(false)}
      className={cn("grid grid-cols-[22px_minmax(0,1fr)] gap-2 border-t border-cloud-100 py-2.5 transition-opacity first:border-t-0", dim && "opacity-55")}
    >
      <span className={cn("mt-0.5 inline-flex size-[18px] items-center justify-center rounded font-mono text-[10px] font-bold", hot ? "bg-metar-ink text-white" : "bg-metar-wash text-metar-ink")}>{n}</span>
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="font-mono text-[12px] text-slate-500">{fact.field}</span>
          <span className="text-[13.5px] font-medium text-navy-900">{valueText(fact.field, fact.value)}</span>
        </div>
        <div className="mt-0.5 flex flex-wrap items-baseline gap-x-2 text-[12px] text-slate-500">
          <span className="font-mono text-[11.5px] text-slate-400">{subjectLabel(fact.subject)}</span>
          {fact.span ? <span className="break-words font-mono text-[11.5px] text-slate-600">&ldquo;{fact.span}&rdquo;</span> : <span className="text-slate-400">no span</span>}
          {fact.extract_conf !== null && fact.extract_conf !== undefined ? <span className="font-mono text-[11px] text-slate-400">conf {pct(fact.extract_conf)}</span> : null}
        </div>
        {unplaced ? <p className="mt-0.5 text-[11.5px] text-slate-400">The quoted span isn&rsquo;t in the text as shown.</p> : null}
      </div>
    </li>
  );
}

/**
 * What changed, as it arrives: the response's events first, then any later event on the live feed
 * that touches this source, its facts or what it affected. Rows land one at a time.
 */
function WhatChanged({ response, startSeq, before, after }: { response: InjectResponse; startSeq: number; before: Record<string, FlightSnapshot | null>; after: Record<string, FlightSnapshot | null> | null }) {
  const live = useLiveFeed((s) => s.events);
  const reduce = useReducedMotion();
  const events = useMemo(() => {
    const keys = new Set<string>([response.source.id, ...response.facts.map((f) => f.id), ...response.affected]);
    for (const a of response.affected) {
      const fl = flightOf(a);
      if (fl) keys.add(fl);
    }
    const own = new Map(response.events.map((e) => [e.seq, e]));
    // Only what happened after this injection's own events: a stream still replaying history must not
    // slip an older event about the same flight into the diff.
    const after = Math.max(startSeq, ...response.events.map((e) => e.seq));
    const later = live.filter((e) => e.seq > after && !own.has(e.seq) && !!e.ref && (keys.has(e.ref) || keys.has(flightOf(e.ref) ?? "")));
    return [...own.values(), ...later].sort((a, b) => a.seq - b.seq);
  }, [response, live, startSeq]);

  const [revealed, setRevealed] = useState(0);
  useEffect(() => {
    if (reduce || revealed >= events.length) return;
    const t = window.setTimeout(() => setRevealed((s) => s + 1), revealed === 0 ? 120 : 260);
    return () => window.clearTimeout(t);
  }, [revealed, events.length, reduce]);
  const shown = reduce ? events.length : revealed;

  const flights = [...new Set(response.affected.map(flightOf).filter((x): x is string => !!x))];
  const streaming = shown < events.length;

  return (
    <Panel
      title={
        <span className="flex items-center gap-2">
          What changed
          <span className="inline-flex items-center gap-1.5 font-mono text-[11px] font-normal text-slate-400" aria-live="polite">
            <span className={cn("size-1.5 rounded-full", streaming ? "animate-pulse bg-metar" : "bg-cloud-300")} aria-hidden="true" />
            {streaming ? "streaming" : `${count(events.length)} ${plural(events.length, "event", "events")}`}
          </span>
        </span>
      }
      padded={false}
    >
      <div className="grid @3xl:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <div className="min-w-0 px-5 pb-3">
          {events.length ? (
            <ol aria-live="polite" data-testid="inject-events">
              {events.slice(0, shown).map((e) => (
                <EventRow key={e.seq} event={e} />
              ))}
            </ol>
          ) : (
            <p className="pb-2 text-[13px] text-slate-500">Nothing changed downstream: no decision, entitlement or journal moved.</p>
          )}
        </div>
        <div className="min-w-0 border-t border-cloud-100 px-5 pb-5 pt-3 @3xl:border-l @3xl:border-t-0 @3xl:pt-0">
          <MicroLabel>Affected · {count(response.affected.length)}</MicroLabel>
          {response.affected.length ? (
            <ul className="mt-2 flex flex-wrap gap-1.5" data-testid="inject-affected">
              {response.affected.map((id) => {
                const fl = flightOf(id);
                const to = fl ? `/flights/${encodeURIComponent(fl)}` : id.startsWith("Q-") ? "/questions" : null;
                const label = shortId(id);
                return (
                  <li key={id}>
                    {to ? (
                      <Link to={to} className="inline-flex h-6 items-center gap-1 rounded-md bg-cloud-100 px-2 font-mono text-[11.5px] text-navy-900 transition-colors hover:bg-cloud-200" title={id}>
                        {label}
                        <ArrowRight className="size-3 text-slate-400" aria-hidden="true" />
                      </Link>
                    ) : (
                      <span className="inline-flex h-6 items-center rounded-md bg-cloud-100 px-2 font-mono text-[11.5px] text-navy-900" title={id}>
                        {label}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="mt-2 text-[13px] text-slate-500">No flight or passenger moved.</p>
          )}
          {flights.length && after ? <VerdictDiff flights={flights} before={before} after={after} /> : null}
        </div>
      </div>
    </Panel>
  );
}

function EventRow({ event }: { event: TraceEvent }) {
  return <FeedRow event={event} className="border-t border-cloud-100 animate-in fade-in-0 slide-in-from-top-1 duration-300 first:border-t-0" />;
}

/** Before → after for each affected flight the API can show: verdict, recode, confidence, routing. */
function VerdictDiff({ flights, before, after }: { flights: string[]; before: Record<string, FlightSnapshot | null>; after: Record<string, FlightSnapshot | null> }) {
  const rows = flights.map((id) => ({ id, b: before[id] ?? null, a: after[id] ?? null })).filter((r) => r.a);
  if (!rows.length) return null;
  return (
    <ul className="mt-4 flex flex-col gap-2.5" data-testid="inject-diff">
      {rows.map(({ id, a, b }) => {
        const now = verdictChip(a!.decision);
        const was = b ? verdictChip(b.decision) : null;
        const changed = was && was.text !== now.text;
        return (
          <li key={id} className="rounded-lg bg-cloud-25 px-3 py-2.5 shadow-[inset_0_0_0_1px_var(--color-cloud-200)]">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-[12.5px] font-bold text-navy-900">{shortId(id)}</span>
              <span className="text-[11.5px] text-slate-400">{was ? (changed ? "verdict changed" : "verdict stands") : "now"}</span>
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              {was && changed ? (
                <>
                  <StatusChip tone={was.tone} className="h-5 text-[10.5px] line-through decoration-1 opacity-70">
                    {was.text}
                  </StatusChip>
                  <span className="text-slate-400" aria-label="became">
                    →
                  </span>
                </>
              ) : null}
              <StatusChip tone={now.tone} className="h-5 text-[10.5px]">
                {now.text}
              </StatusChip>
              {a!.decision.recode_label ? (
                <StatusChip tone={now.tone === "notweather" ? "notweather" : "outline"} dot={false} className="h-5 text-[10.5px]">
                  {a!.decision.recode_label}
                </StatusChip>
              ) : null}
            </div>
            <p className="mt-1.5 font-mono text-[11.5px] text-slate-500">
              {a!.decision.confidence.label}{" "}
              {b && b.decision.confidence.score !== a!.decision.confidence.score ? (
                <>
                  <span className="text-slate-400 line-through">{b.decision.confidence.score === null ? "uncalibrated" : pct(b.decision.confidence.score)}</span> →{" "}
                </>
              ) : null}
              <span className="font-bold text-navy-900">{a!.decision.confidence.score === null ? "uncalibrated" : pct(a!.decision.confidence.score)}</span>
            </p>
          </li>
        );
      })}
    </ul>
  );
}
