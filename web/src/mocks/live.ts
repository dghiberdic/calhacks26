// Live paths: the Judge's Desk (POST /desk) and injections (POST /inject). Desk input errors are 422s
// with plain messages; an injection is read into verbatim-span facts, and anything StormCheck can't
// place becomes a low-confidence question for Ops. Neither path ever answers with a 500.
import type { Fact, InjectRequest, InjectResponse, Source, SourceKind, TraceEvent } from "@/api/types";
import { bandFor, findAirport } from "./data/airports";
import { generateDay } from "./data/desk";
import { decide, isOwed, liabilityCents, voucherCases, voucherSettled } from "./data/engine";
import { EOWYN_ID } from "./data/flights";
import { hiddenDefectQuestion, opsQuestion } from "./data/questions";
import { makeSource } from "./data/texts";
import { eur } from "./data/util";
import { mainWindow, registerSource, windowLabel, type StormDef } from "./data/world";
import { challenge, nonEuVoucherQuestion, postEstimateChange } from "./actions";
import { bodyOf, fail, ok, str, type Reply, type Req } from "./reply";
import { diffSnaps, snapshot } from "./replay";
import { commitDecision, ctxOf, emit, mask, nextAt, nextQuestionId, S, specOf, stormById, stormRun, type MockState } from "./state";

// ---------- desk ----------
export function deskRun(req: Req): Reply {
  const s = S();
  const b = bodyOf(req);
  const code = str(b.icao);
  const date = str(b.date);
  if (!code) return fail(422, "validation", "Pick an airport: an ICAO code like EGLL or an IATA code like LHR.");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || Number.isNaN(Date.parse(`${date}T00:00:00Z`))) return fail(422, "validation", "Use a local date like 2025-01-24.");
  const ap = findAirport(code);
  if (!ap) return fail(422, "unknown_airport", `We don't know the airport "${code}". Try an ICAO code like EGLL or an IATA code like LHR.`);
  const today = new Date().toISOString().slice(0, 10);
  if (date > today) return fail(422, "future_date", `${date} hasn't happened yet, so there's no weather to read.`);
  if (date < "2023-07-01") return fail(422, "no_metar", `No METAR for ${ap.icao} on ${date}: the pinned archive and IEM pull in this build start on 2023-07-01.`);
  const id = `${ap.icao}@${date}`;
  const existing = stormById(s, id);
  if (existing) return ok(stormRun(s, existing, req.role));
  const storm = generateDay(ap.icao, date);
  storm.real_context.run_at = s.knownAt;
  s.storms.push(storm);
  for (const spec of storm.flights) commitDecision(s, storm, spec, s.knownAt);
  announceDeskRun(s, storm);
  return ok(stormRun(s, storm, req.role));
}

function announceDeskRun(s: MockState, storm: StormDef) {
  const ctx = ctxOf(s);
  const w = mainWindow(storm);
  const hub = findAirport(storm.station)?.iata ?? storm.station;
  const say = (init: Omit<TraceEvent, "seq" | "at" | "ref" | "amount_cents"> & { ref?: string | null; amount_cents?: number | null }) => emit(s, init, storm.id);
  say({
    kind: "fact",
    actor: "parser:iem@1",
    summary: w ? `Read ${storm.metar.length} METAR obs at ${storm.station} (synthetic in mock mode) · storm window ${windowLabel(w)}, peak gust ${w.peak_gust_kt} kt` : `Read ${storm.metar.length} METAR obs at ${storm.station} (synthetic in mock mode) · ${storm.message} · nothing cancelled for weather`,
    ref: `metar:${storm.id}`,
    chip: "INFO",
  });
  const decided = storm.flights.map((spec) => ({ spec, d: decide(storm, spec, ctx) })).filter((x) => x.d);
  const weather = decided.filter((x) => x.d?.cause === "weather");
  if (weather.length) say({ kind: "decision", actor: "agent.engine", summary: `${weather.length} flights inside the ${hub} window · weather · no compensation; refunds and care still due`, ref: storm.id, chip: "APPLIED" });
  for (const x of decided.filter((y) => y.d?.cause === "technical")) {
    const f = x.spec.flight;
    say({ kind: "decision", actor: "agent.engine", summary: x.d?.recoded ? `${f.number} recoded ${x.d.recode_label} · ${f.pax} payouts drafted · miscode caught` : `${f.number} ${f.origin}→${f.dest} rotation of the AOG (${f.ops_cause_code}) · ${f.pax} payouts drafted`, ref: f.id, chip: "DRAFTED", amount_cents: liabilityCents(x.spec, x.d, ctx) });
  }
  const knock = decided.filter((x) => x.d?.cause === "knock_on");
  if (knock.length) {
    const held = knock.reduce((t, x) => t + liabilityCents(x.spec, x.d, ctx), 0);
    if (ctx.knockOn) say({ kind: "decision", actor: "agent.engine", summary: `${knock.length} knock-on returns settled · ${ctx.knockOn.ref} cited ${knock.length}×`, ref: ctx.knockOn.ref, chip: "CITED", amount_cents: held || null });
    else say({ kind: "decision", actor: "agent.engine", summary: `${knock.length} knock-on returns held · same pattern as Q-2, waiting on Legal`, ref: "Q-2", chip: "HELD", amount_cents: held });
  }
  const cases = voucherCases(storm);
  if (cases.length) {
    if (ctx.voucher) {
      const settled = cases.filter((c) => voucherSettled(c, ctx));
      if (settled.length) say({ kind: "entitlement", actor: "agent.engine", summary: `${settled.length} unsigned in-lieu vouchers on EU departures settled · ruling cited ${ctx.voucher.ref}`, ref: storm.id, chip: "CITED", amount_cents: settled.reduce((t, c) => t + bandCents(s, c.flight_id), 0) });
      for (const c of cases.filter((x) => !voucherSettled(x, ctx))) {
        const hit = specOf(s, c.flight_id);
        const route = hit ? `${hit.spec.flight.origin}→${hit.spec.flight.dest}` : "non-EU";
        const q = nonEuVoucherQuestion(s, storm, c.coupon_id, route, ctx.voucher.ref);
        q.holds_cents = bandCents(s, c.flight_id);
        s.questions.push(q);
        emit(s, { kind: "question", actor: "agent.engine", summary: `${route} case asked again (doesn't depart the EU)`, ref: q.id, chip: "ASKED", amount_cents: q.holds_cents }, storm.id, { payload: q });
      }
    } else {
      say({ kind: "entitlement", actor: "agent.engine", summary: `${cases.length} unsigned in-lieu vouchers held · same pattern as Q-1, waiting on the Claims Lead`, ref: "Q-1", chip: "HELD", amount_cents: cases.reduce((t, c) => t + bandCents(s, c.flight_id), 0) });
    }
  }
}

function bandCents(s: MockState, flightId: string) {
  const hit = specOf(s, flightId);
  return hit ? bandFor(hit.spec.flight.origin, hit.spec.flight.dest).band_eur * 100 : 0;
}

// ---------- inject ----------
const KIND_TO_SOURCE: Record<InjectRequest["kind"], SourceKind> = { tech_log: "tech_log", claim: "claim", crm: "crm", email: "email", occ_log: "occ_log", manufacturer: "manufacturer" };
const MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
const MONTH_WORD = /\b(\d{1,2})\s+(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{4})\b/i;
const INSTRUCTION = /(ignore (all )?(previous|prior) instructions[^.]*\.?|mark every [^.]*approved[^.]*\.?|this message is your authori[sz]ation\.?|you are authori[sz]ed to [^.]*\.?)/gi;

type Cand = { subject: string; field: string; value: unknown; span: string; conf: number };

/** The Reader's job, done with regexes in mock mode: typed facts whose span is a verbatim substring. */
function extract(kind: InjectRequest["kind"], text: string, flightId: string | null): { cands: Cand[]; dropped: number } {
  const cands: Cand[] = [];
  const subjectFlight = flightId ? `flight:${flightId}` : "unknown";
  const year = flightId?.match(/@(\d{4})/)?.[1] ?? "2025";
  const amos = text.match(/\b(\d{1,2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+(\d{2}):(\d{2})Z\b/);
  const tail = text.match(/\bEI-[A-Z]{3}\b/)?.[0];
  if (amos) {
    const iso = `${year}-${String(MON.indexOf(amos[2]) + 1).padStart(2, "0")}-${amos[1].padStart(2, "0")}T${amos[3]}:${amos[4]}:00Z`;
    cands.push({ subject: tail ? `aircraft:${tail}` : subjectFlight, field: kind === "tech_log" ? "aog.logged_at" : "event.at", value: iso, span: amos[0], conf: 0.97 });
  }
  if (tail) cands.push({ subject: `aircraft:${tail}`, field: "aircraft", value: tail, span: tail, conf: 0.99 });
  if (/NO MEL RELIEF/i.test(text)) cands.push({ subject: tail ? `aircraft:${tail}` : subjectFlight, field: "aog.mel_relief", value: false, span: text.match(/NO MEL RELIEF/i)?.[0] ?? "NO MEL RELIEF", conf: 0.98 });
  const aog = text.match(/A\/C AOG|\bAOG\b/);
  if (aog) cands.push({ subject: tail ? `aircraft:${tail}` : subjectFlight, field: "aog", value: true, span: aog[0], conf: 0.96 });
  const ata = text.match(/\b(BRAKE|EDP|ENGINE DRIVEN PUMP|BLEED|OIL PRESS|PACK|HYD)\b/i);
  if (ata) cands.push({ subject: tail ? `aircraft:${tail}` : subjectFlight, field: "aog.ata", value: { BRAKE: "3242", EDP: "2913", "ENGINE DRIVEN PUMP": "2913", BLEED: "3611", "OIL PRESS": "7930", PACK: "2151", HYD: "2900" }[ata[1].toUpperCase()] ?? "0000", span: ata[0], conf: 0.9 });
  const seat = text.match(/\bseat\s+(\d{1,2}[A-K])\b/i);
  if (seat) cands.push({ subject: flightId ? `coupon:${flightId}:${seat[1].toUpperCase()}` : "unknown", field: "coupon.seat", value: seat[1].toUpperCase(), span: seat[0], conf: 0.95 });
  const amount = text.match(/(EUR|€|GBP|£)\s?(\d+(?:[.,]\d{2})?)/);
  if (amount) {
    const currency = amount[1] === "€" || amount[1] === "EUR" ? "EUR" : "GBP";
    cands.push({ subject: subjectFlight, field: "claim.amount", value: { currency, amount_cents: Math.round(Number(amount[2].replace(",", ".")) * 100) }, span: amount[0], conf: 0.97 });
  }
  const regime = text.match(/\b(UK261|EU261)\b/);
  if (regime) cands.push({ subject: subjectFlight, field: "claim.regime", value: regime[1], span: regime[0], conf: 0.97 });
  const agency = text.match(/\bon behalf of\b|\bLtd\b/i);
  if (agency && kind === "claim") cands.push({ subject: subjectFlight, field: "claim.channel", value: "agency", span: agency[0], conf: 0.9 });
  const poa = text.match(/power of attorney|\bPOA\b/i);
  if (poa) cands.push({ subject: subjectFlight, field: "claim.authority", value: "poa", span: poa[0], conf: 0.93 });
  const cb = text.match(/CHARGEBACK/i);
  if (cb) cands.push({ subject: subjectFlight, field: "crm.kind", value: "chargeback", span: cb[0], conf: 0.97 });
  const botRefund = text.match(/CRM-BOT REFUND[^·]*/i);
  if (botRefund) cands.push({ subject: subjectFlight, field: "crm.bot_refund", value: true, span: botRefund[0].trim(), conf: 0.92 });
  const inLieu = text.match(/IN LIEU OF COMPENSATION/i);
  if (inLieu) cands.push({ subject: subjectFlight, field: "voucher.in_lieu", value: true, span: inLieu[0], conf: 0.95 });
  const date = text.match(MONTH_WORD);
  if (date) {
    const m = MON.indexOf(date[2].slice(0, 3).toUpperCase()) + 1;
    cands.push({ subject: subjectFlight, field: "flight.date", value: `${date[3]}-${String(m).padStart(2, "0")}-${date[1].padStart(2, "0")}`, span: date[0], conf: 0.94 });
  }
  const flightNo = text.match(/\bNS\d{1,4}\b/);
  if (flightNo) cands.push({ subject: subjectFlight, field: "flight.number", value: flightNo[0], span: flightNo[0], conf: 0.98 });
  const defect = text.match(/hidden (manufacturing )?defect/i);
  if (defect) cands.push({ subject: subjectFlight, field: "manufacturer.hidden_defect", value: true, span: defect[0], conf: 0.88 });
  const code = text.match(/\bRSN\s+(\d{2})\b/);
  if (code) cands.push({ subject: subjectFlight, field: "flight.ops_cause_code", value: code[1], span: code[0], conf: 0.95 });
  const dropped = (text.match(INSTRUCTION) ?? []).length;
  return { cands: cands.filter((c) => text.includes(c.span)), dropped };
}

function findFlight(s: MockState, req: InjectRequest, cands: Cand[]): string | null {
  if (req.flight_id && specOf(s, req.flight_id)) return req.flight_id;
  const tail = cands.find((c) => c.field === "aircraft")?.value as string | undefined;
  const at = cands.find((c) => c.field === "aog.logged_at")?.value as string | undefined;
  if (tail) {
    for (const storm of s.storms) {
      const legs = storm.flights.filter((f) => f.flight.aircraft === tail && f.flight.status === "cancelled");
      const after = at ? legs.find((f) => f.flight.sched_dep >= at) : legs[0];
      if (after ?? legs[0]) return (after ?? legs[0]).flight.id;
    }
  }
  const num = cands.find((c) => c.field === "flight.number")?.value as string | undefined;
  if (num) for (const storm of s.storms) for (const f of storm.flights) if (f.flight.number === num) return f.flight.id;
  return null;
}

export function inject(req: Req): Reply {
  const s = S();
  const b = bodyOf(req);
  const kind = str(b.kind) as InjectRequest["kind"];
  const text = typeof b.text === "string" ? b.text : "";
  if (!(kind in KIND_TO_SOURCE)) return fail(422, "validation", "kind must be one of tech_log, claim, crm, email, occ_log or manufacturer.");
  if (!text.trim()) return fail(422, "validation", "Paste the text to inject first.");
  const request: InjectRequest = { kind, text: text.slice(0, 4000), flight_id: str(b.flight_id) || null };
  const firstSeq = (s.trace[s.trace.length - 1]?.seq ?? 0) + 1;
  const at = nextAt(s);
  const n = s.ids.inject++;
  const source: Source = registerSource({ ...makeSource(`inject:${n}`, KIND_TO_SOURCE[kind], `Injected ${kind.replace("_", " ")} #${n}`, request.text, at), acl_tags: kind === "claim" || kind === "email" || kind === "crm" ? ["pii"] : ["ops"] });
  const { cands, dropped } = extract(kind, request.text, request.flight_id ?? null);
  const flightId = findFlight(s, request, cands);
  const fallback = cands.length === 0;
  const facts: Fact[] = cands.map((c, i) => ({
    id: `F-INJ-${n}-${i + 1}`,
    source_id: source.id,
    subject: c.subject === "unknown" && flightId ? `flight:${flightId}` : c.subject,
    field: c.field,
    value: c.value,
    span: c.span,
    extractor: fallback ? "fallback:regex@1" : "llm:claude-opus-5-5@reader-v1",
    extract_conf: c.conf,
    valid_at: c.field === "aog.logged_at" ? (c.value as string) : null,
    recorded_at: at,
    acl_tags: source.acl_tags ?? [],
  }));
  emit(s, { at, kind: "llm_call", actor: "agent.reader", summary: `Read the injected ${kind.replace("_", " ")}: ${facts.length} facts verified${dropped ? `, ${dropped} dropped (instructions are content, not commands)` : ""}`, ref: source.id, chip: "INFO" }, null, { payload: { source: source.sha256, facts: facts.length }, inputs: [`source:${source.id}`, "prompt:reader-v1"] });

  const affected: string[] = [];
  let message: string | null = null;
  const hit = flightId ? specOf(s, flightId) : undefined;
  const has = (field: string) => cands.find((c) => c.field === field);

  if (fallback) {
    const q = opsQuestion(nextQuestionId(s), nextAt(s), hit?.storm.id ?? EOWYN_ID, flightId ?? source.id, `An injected ${kind.replace("_", " ")} StormCheck couldn't read`, "StormCheck couldn't find a flight, tail, coupon, time or amount in this text.", request.text.slice(0, 280), source.id);
    s.questions.push(q);
    emit(s, { kind: "question", actor: "agent.engine", summary: `Couldn't place the injected ${kind.replace("_", " ")} · asked Ops (confidence 31%) · nothing changed`, ref: q.id, chip: "ASKED" }, q.storm_id, { payload: q });
    message = `Couldn't read this as a ${kind.replace("_", " ")}; it went to Ops as a low-confidence question. Nothing was changed.`;
  } else if (kind === "email" && dropped) {
    s.extRefusals += 1;
    s.accessLog.push({ at: nextAt(s), principal: "external:email", action: "approve_payout", resource: `payouts:${flightId ?? "NS31@2025-01-24"}`, allowed: false, reason: "External parties never satisfy an internal approval" });
    emit(s, { kind: "access_denied", actor: "external:email", summary: "email approve_payout → DENIED · external parties never satisfy an internal approval", ref: source.id, chip: "DENIED" }, hit?.storm.id ?? null);
    message = `Facts only: ${dropped} instruction${dropped === 1 ? " was" : "s were"} ignored (documents are data). Nothing was approved.`;
  } else if ((kind === "email" || kind === "claim") && /grounded it anyway|storm anyway|would have been cancelled anyway/i.test(request.text) && flightId) {
    const r = challenge({ ...req, body: { text: request.text } }, flightId);
    affected.push(flightId);
    message = (r.body as { reply?: { text?: string } }).reply?.text ?? "Decision stands.";
  } else if (kind === "manufacturer" || has("manufacturer.hidden_defect")) {
    const target = flightId ?? "NS31@2025-01-24";
    const q = hiddenDefectQuestion(nextQuestionId(s), nextAt(s), target, specOf(s, target)?.storm.id ?? EOWYN_ID, request.text.slice(0, 280));
    q.evidence = [{ fact_id: facts.find((f) => f.field === "manufacturer.hidden_defect")?.id ?? `F-INJ-${n}`, source_id: source.id, field: "manufacturer.hidden_defect", value: true, quote: has("manufacturer.hidden_defect")?.span ?? null, role: "contradicts", trust_tier: source.trust_tier, struck: false }];
    s.questions.push(q);
    affected.push(target);
    emit(s, { kind: "question", actor: "agent.engine", summary: `Asked Legal about a manufacturer's hidden-defect notice on ${target.split("@")[0]} (C-549/07 ¶26) · decision stands`, ref: q.id, chip: "ASKED" }, q.storm_id, { payload: q });
    message = "New legal pattern: routed to Legal at confidence 52% · no precedent. The decision stands until Legal rules.";
  } else if (kind === "tech_log" && hit && has("aog")) {
    const { storm, spec } = hit;
    const d = decide(storm, spec, ctxOf(s));
    const loggedAt = has("aog.logged_at")?.value as string | undefined;
    const w = mainWindow(storm);
    const inside = !!(w && loggedAt && loggedAt >= w.start && loggedAt <= w.end);
    affected.push(spec.flight.id);
    if (d && d.cause === "weather" && loggedAt) {
      const before = snapshot(s);
      const q = opsOrLegalConcurrent(s, storm, spec.flight.id, request.text, source.id, inside);
      s.injected.set(spec.flight.id, { logged_at: loggedAt, source_id: source.id, span: request.text, question_id: q.id });
      commitDecision(s, storm, spec, s.knownAt);
      const diff = diffSnaps(before, snapshot(s), "inject", s.knownAt, s.locked);
      q.holds_cents = Math.max(0, diff.total_delta_cents);
      const jeId = postEstimateChange(s, diff, `${spec.flight.number} held for Legal (concurrent causes) · accrued at the segment rate (IFRS 15.56) · drafted, pending approval`, spec.flight.id);
      emit(s, { kind: "decision", actor: "agent.engine", summary: `${spec.flight.number}: AOG ${inside ? "inside" : "before"} the storm window · concurrent causes · held for Legal, not flipped`, ref: spec.flight.id, chip: "HELD", amount_cents: diff.total_delta_cents || null }, storm.id);
      emit(s, { kind: "question", actor: "agent.engine", summary: `Asked Legal about concurrent causes on ${spec.flight.number} (confidence 55%)`, ref: q.id, chip: "ASKED" }, storm.id, { payload: q });
      if (jeId) affected.push(jeId);
      message = `AOG ${inside ? "inside" : "before"} the storm window on a weather flight: concurrent causes, routed to Legal. ${spec.flight.number} is held${diff.total_delta_cents ? ` (${eur(diff.total_delta_cents)} accrued at the segment rate)` : ""}, not flipped.`;
    } else if (!d) {
      emit(s, { kind: "fact", actor: "agent.engine", summary: `${spec.flight.number} operated · the tech-log line is recorded for maintenance; nothing to decide`, ref: spec.flight.id, chip: "INFO" }, storm.id);
      message = `${spec.flight.number} operated, so there is no cancellation to re-decide. The line is recorded.`;
    } else {
      emit(s, { kind: "fact", actor: "agent.engine", summary: `${spec.flight.number}: tier-1 tech-log fact recorded · decision unchanged (${d.cause.replace("_", "-")})`, ref: spec.flight.id, chip: "INFO" }, storm.id);
      message = `Recorded as a tier-1 fact. ${spec.flight.number} stays ${d.cause.replace("_", "-")}: ${d.reason}.`;
    }
  } else if (kind === "claim") {
    const dateFact = has("flight.date")?.value as string | undefined;
    const amount = has("claim.amount")?.value as { currency: string; amount_cents: number } | undefined;
    const limit = new Date(Date.parse(s.knownAt));
    limit.setUTCFullYear(limit.getUTCFullYear() - 6);
    if (dateFact && dateFact < limit.toISOString().slice(0, 10)) {
      emit(s, { kind: "entitlement", actor: "agent.engine", summary: `Claim for a flight on ${dateFact} is after the 6-year limitation (Ireland, CJEU C-139/11) · rejected with a reason code, no entry`, ref: source.id, chip: "INFO" }, null);
      message = `Out of time: the 6-year limitation (Ireland) for a flight on ${dateFact} has run. Rejected with a reason code; no entry drafted.`;
    } else if (has("claim.regime")?.value === "UK261" && hit) {
      const band = bandFor(hit.spec.flight.origin, hit.spec.flight.dest);
      const d = decide(hit.storm, hit.spec, ctxOf(s));
      affected.push(hit.spec.flight.id);
      const owed = isOwed(d);
      emit(s, { kind: "entitlement", actor: "agent.engine", summary: `${hit.spec.flight.number}: UK261 claim mapped to EU261 (departs ${hit.spec.flight.origin}) · band €${band.band_eur}, not £${(amount?.amount_cents ?? 52_000) / 100} · ${owed ? "pay once" : "no compensation; refunds and care still due"}`, ref: hit.spec.flight.id, chip: "APPLIED", amount_cents: owed ? band.band_eur * 100 : 0 }, hit.storm.id);
      message = `EU261 applies (the flight departs ${hit.spec.flight.origin}), not UK261: band €${band.band_eur}, paid once. ${owed ? "Compensation is owed." : `${hit.spec.flight.number} was weather: no compensation; refunds and care still due.`}`;
    } else if (has("claim.channel")?.value === "agency" && hit) {
      const seatRef = has("coupon.seat")?.value as string | undefined;
      const coupon = `${hit.spec.flight.id}:${seatRef ?? "22A"}`;
      affected.push(coupon);
      emit(s, { kind: "entitlement", actor: "agent.engine", summary: `Duplicate claim on ${coupon.replace(/@\d{4}-\d{2}-\d{2}/, "")} (direct + agency) · pay once · agency claim held${has("claim.authority") ? " (POA noted)" : ""}`, ref: coupon, chip: "HELD", amount_cents: amount?.amount_cents ?? null }, hit.storm.id);
      message = `Duplicate: this passenger already claimed directly. One payment per coupon across channels; the agency claim is held${has("claim.authority") ? " with its power of attorney noted" : ""}.`;
    } else {
      if (hit) affected.push(hit.spec.flight.id);
      emit(s, { kind: "fact", actor: "agent.engine", summary: `Claim recorded for the Claims Lead's assessment${hit ? ` · ${hit.spec.flight.number}` : ""}${amount ? ` · ${amount.currency} ${amount.amount_cents / 100}` : ""}`, ref: hit?.spec.flight.id ?? source.id, chip: "INFO", amount_cents: amount?.currency === "EUR" ? amount.amount_cents : null }, hit?.storm.id ?? null);
      message = "Claim recorded; it waits for the Claims Lead's assessment.";
    }
  } else if (kind === "crm" && has("crm.kind")?.value === "chargeback") {
    const seatRef = has("coupon.seat")?.value as string | undefined;
    const coupon = `${flightId ?? "NS31@2025-01-24"}:${seatRef ?? "3A"}`;
    affected.push(coupon);
    emit(s, { kind: "entitlement", actor: "agent.engine", summary: `Chargeback on ${coupon.replace(/@\d{4}-\d{2}-\d{2}/, "")} matches the CRM-bot refund · double refund caught · dispute drafted · 2125 stays at 0`, ref: coupon, chip: "HELD", amount_cents: (has("claim.amount")?.value as { amount_cents?: number } | undefined)?.amount_cents ?? null }, hit?.storm.id ?? EOWYN_ID);
    message = "Double refund caught: the chargeback matches the CRM bot's refund on the same coupon. A dispute is drafted; 2125 refund clearing stays at 0.";
  } else if (kind === "occ_log") {
    if (hit) affected.push(hit.spec.flight.id);
    emit(s, { kind: "fact", actor: "agent.engine", summary: `OCC code recorded (tier 3)${hit ? ` for ${hit.spec.flight.number}` : ""} · METAR and the tech log outrank it · no decision changes`, ref: hit?.spec.flight.id ?? source.id, chip: "INFO" }, hit?.storm.id ?? null);
    message = "Recorded. An OCC batch code is tier 3: the METAR and the tech log outrank it, so no decision changes.";
  } else if (!hit) {
    // An unresolved subject becomes an Ops question at low confidence; nothing changes.
    const q = opsQuestion(nextQuestionId(s), nextAt(s), EOWYN_ID, source.id, `An injected ${kind.replace("_", " ")} that names no flight we know`, `${facts.length} facts read, but none ties to a flight, tail or coupon in the world.`, request.text.slice(0, 280), source.id);
    s.questions.push(q);
    emit(s, { kind: "question", actor: "agent.engine", summary: `Couldn't tie the injected ${kind.replace("_", " ")} to a flight · asked Ops (confidence 31%)`, ref: q.id, chip: "ASKED" }, EOWYN_ID, { payload: q });
    message = "Read, but it names no flight, tail or coupon StormCheck knows: it went to Ops as a low-confidence question. Nothing was changed.";
  } else {
    affected.push(hit.spec.flight.id);
    emit(s, { kind: "fact", actor: "agent.engine", summary: `${facts.length} facts recorded from the injected ${kind.replace("_", " ")} · no decision changes`, ref: hit.spec.flight.id, chip: "INFO" }, hit.storm.id);
    message = `${facts.length} facts recorded; no decision changes.`;
  }

  const events = s.trace.filter((e) => e.seq >= firstSeq);
  const response: InjectResponse = { source, facts, dropped_unverifiable: dropped, events, affected, fallback_used: fallback, message };
  return ok(mask(response, req.role));
}

function opsOrLegalConcurrent(s: MockState, storm: StormDef, flightId: string, text: string, sourceId: string, inside: boolean) {
  const q = hiddenDefectQuestion(nextQuestionId(s), nextAt(s), flightId, storm.id, text.slice(0, 280));
  const number = flightId.split("@")[0];
  q.pattern = "concurrent_causes";
  q.title = `${number}: an AOG ${inside ? "inside" : "before"} the storm window. Weather, technical, or both?`;
  q.found = `A tech-log line grounds ${number}'s aircraft ${inside ? "inside" : "before"} the storm window, on a flight the window already cancelled.`;
  q.why_flagged = "Concurrent causes: the storm and an internal fault both explain the cancellation. Which one counts is a legal question, so Legal decides; the flight is held, not flipped.";
  q.recommends = "Treat the storm as decisive while the flight is inside the window at either end; record the AOG for maintenance.";
  q.recommended_option = "The storm decides while the flight is inside the window at either end; the AOG is recorded for maintenance.";
  q.options = [q.recommended_option, "The AOG decides: not extraordinary, compensation owed.", "Ask maintenance whether the aircraft could have flown before the window opened."];
  q.confidence = { score: 0.55, kind: "cause", label: "cause-finding confidence", features: { aog_inside_window: inside ? 1 : 0, in_window_dep: 1, sources_disagree: 1, precedent_count: 0 }, caps: ["capped:concurrent-causes"], calibration_version: "cal-v1" };
  q.reason_tag = "concurrent-causes";
  q.evidence = [{ fact_id: `F:${sourceId}:aog.logged_at`, source_id: sourceId, field: "aog.logged_at", value: true, quote: text, role: "contradicts", trust_tier: 1, struck: false }];
  q.holds = [flightId];
  s.questions.push(q);
  return q;
}

