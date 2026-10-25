"""D2 · What really caused a cancellation, decided deterministically from ranked evidence.

Priority (THREAD_DAVID D2):
1. A no-go AOG (no MEL relief, tier-1 tech log, logged before the cancellation, not back in service by STD) on the
   flight's own station, flight out of window at both ends -> internal root ``technical / not_extraordinary``;
   external/weather root (lightning, hail, bird...) -> ``external_event`` Legal. A recode needs this positive tier-1
   evidence. An AOG logged during an earlier storm window does not make an out-of-window flight concurrent.
2. The same AOG while the flight itself sits in a window at either end -> ``concurrent / needs_legal`` (Legal).
   An AOG at another station (the tail never got here) on a return whose outbound was cancelled is a knock-on.
3. An AOG claimed only below tier 1 (an e-mail, a claim, an OCC note) -> ``aog_unverified``: Ops verifies it.
4. In a window at either end, no AOG -> ``weather / extraordinary`` (a rotation code is recoded to 71). An OCC
   technical, crew, ATC or airport code there with no tech-log line -> ``occ_code_in_window``: sources disagree, Ops.
4b. In an external event's window (a grid outage) at either end, no decisive AOG -> ``external_event`` /
   ``external_event_window``: no precedent, Legal. A decisive AOG there is concurrent causes (2).
4c. Cancelled after an event window closed (< 24 h) and the carrier's own OCC/MCC log names crew out of duty hours or
   the aircraft out of position -> ``crew`` / ``technical``, not extraordinary (``internal_cause_logged``, owed).
5. Return sector whose outbound (previous rotation) was cancelled for weather, out at both ends ->
   ``knock_on / needs_legal`` unless an active legal rule settles it (applied by the engine, not here).
6. ``unknown`` window -> ``unknown / needs_legal`` routed to Ops.
Then, out of window at both ends with no tier-1 cause: the OCC code is never trusted alone. A weather code
contradicted by METAR goes to Ops (sources disagree); other codes map to their IATA group. Security, customs and
airport-facility codes (85/86/87/89) are not ATC: Ops confirms them.

Spares are never a feature or evidence for a technical cause (no Art. 5(3) reasonable-measures test applies).
Pure: no wall clock, no randomness, no LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from contracts.models import Cause, Evidence, Extraordinary, MetarObs, OpsLogEntry, Role, SourceKind, StormWindow
from contracts import normalize as nz
from engine.case import EVENT_KIND_LABEL, EventWindow, FlightCase, find_source, provenance
from engine.timeline import EndPosition

# IATA delay-code groups (AHM 730)
WEATHER_CODES = {"71", "72", "73", "75", "76", "77"}
TECH_CODES = {"41", "42", "43", "44", "45", "46", "47", "48"}
CREW_CODES = {"61", "62", "63", "64", "65", "66", "67", "68", "69", "94", "95"}
ATC_CODES = {"81", "82", "83", "84", "88"}          # ATFM en route / at destination, airport restrictions (ATC)
AIRPORT_CODES = {"85", "86", "87", "89"}            # security, immigration/customs, airport facilities, departure
ROTATION_CODES = {"91", "92", "93", "96"}
NEW_CODE = {Cause.TECHNICAL: "41", Cause.CREW: "64", Cause.ATC: "81", Cause.KNOCK_ON: "93", Cause.WEATHER: "71"}
CODE_GROUP = {**{c: "technical" for c in TECH_CODES}, **{c: "crew" for c in CREW_CODES},
              **{c: "ATC" for c in ATC_CODES}, **{c: "security/airport" for c in AIRPORT_CODES}}

LB_ART53 = "EU261 Art.5(3)"
LB = {
    "weather": [LB_ART53, "EU261 Recital 14", "CJEU C-549/07"],
    "technical_internal": [LB_ART53, "CJEU C-549/07", "CJEU C-257/14"],
    "external_event": [LB_ART53, "CJEU C-549/07", "CJEU C-257/14"],
    "concurrent_causes": [LB_ART53, "CJEU C-74/19", "CJEU C-549/07"],
    "knock_on_return": [LB_ART53, "CJEU C-74/19", "CJEU C-549/07"],
    "knock_on_internal": [LB_ART53, "CJEU C-74/19", "CJEU C-549/07"],
    "window_unknown": [LB_ART53],
    "weather_code_contradicted": [LB_ART53, "EU261 Recital 14"],
    "technical_unverified": [LB_ART53, "CJEU C-549/07"],
    "crew": [LB_ART53, "CJEU C-549/07"],
    "atc": [LB_ART53, "EU261 Recital 15"],
    "airport_restriction": [LB_ART53, "EU261 Recital 14"],
    "occ_code_in_window": [LB_ART53, "EU261 Recital 14", "CJEU C-549/07"],
    "aog_unverified": [LB_ART53, "CJEU C-549/07"],
    "cause_unknown": [LB_ART53],
    # care and re-routing stay owed in extraordinary circumstances (C-12/11 McDonagh)
    "external_event_window": [LB_ART53, "EU261 Recital 14", "CJEU C-549/07", "CJEU C-12/11"],
    "internal_cause_logged": [LB_ART53, "CJEU C-549/07"],
}
# the carrier's own OCC/MCC log naming an internal cause after an external event closed
CREW_DUTY = re.compile(r"\bCREW\b[^.;]*?\b(?:OUT OF (?:DUTY |FDP|HOURS)|FDP|DUTY (?:HOURS|TIME|LIMITS?)|TIMED OUT)|"
                       r"\bOUT OF FDP\b|\bFDP (?:EXCEEDED|LIMIT)", re.I)
POSITIONING = re.compile(r"\b(?:OUT OF|NOT IN) POSITION\b|\bNO TAIL AT\b|\bA/C STUCK\b|\bSTRANDED AT\b", re.I)


@dataclass
class Finding:
    cause: Cause
    extraordinary: Extraordinary
    pattern: str
    reason: str
    recoded: bool = False
    new_code: str | None = None
    route: Role | None = None              # who must decide if it cannot be automatic
    reason_tag: str | None = None          # Question.reason_tag if escalated
    evidence: list[Evidence] = field(default_factory=list)
    legal_basis: list[str] = field(default_factory=list)
    sources_disagree: bool = False
    caps: list[str] = field(default_factory=list)


def hhmm(t: datetime) -> str:
    return t.strftime("%H:%MZ")


def dmy(t: datetime) -> str:
    return f"{t.day} {t:%b} {hhmm(t)}"


# ---------- evidence helpers ----------

def _nearest(obs: list[MetarObs], t: datetime) -> MetarObs | None:
    return min(obs, key=lambda o: (abs(o.valid - t), o.valid), default=None)


def metar_fact_id(o: MetarObs, field: str = "metar.gust_kt") -> str:
    """The contracts.normalize id of this obs' fact, so the citation links to the recorded METAR fact."""
    return nz.metar_fact_id(o, field)


def window_fact_id(w: StormWindow) -> str:
    return f"F-WINDOW-{w.station}@{w.start:%Y-%m-%d}T{w.start:%H%M}Z"


def _metar_ev(case: FlightCase, o: MetarObs, role: str) -> Evidence:
    sid, tier = find_source(case, SourceKind.METAR, o.raw, f"SRC-METAR-{o.station}", on=o.valid)
    # cite the gust when the obs reports one, else the sustained wind (each is its own normalize fact)
    field, value = ("metar.gust_kt", o.gust) if o.gust is not None else ("metar.sknt", o.sknt)
    return Evidence(fact_id=metar_fact_id(o, field), source_id=sid, field=field, value=value, quote=o.raw,
                    role=role, trust_tier=tier)


def _window_ev(case: FlightCase, w: StormWindow) -> Evidence:
    sid, tier = find_source(case, SourceKind.METAR, None, f"SRC-METAR-{w.station}", on=w.start)
    return Evidence(fact_id=window_fact_id(w), source_id=sid, field="storm.window",
                    value={"start": w.start.isoformat().replace("+00:00", "Z"),
                           "end": w.end.isoformat().replace("+00:00", "Z"), "peak_gust_kt": w.peak_gust_kt},
                    quote=None, role="context", trust_tier=tier)


def _clause(text: str, *needles: str) -> str | None:
    """The verbatim clause of an AMOS/OCC line containing all needles."""
    parts = [p.strip() for p in re.split(r"(?<=\.)\s+", text) if p.strip()]
    for p in parts:
        if all(n in p for n in needles):
            return p
    return None


def _occ_ev(case: FlightCase, role: str, struck: bool = False) -> Evidence | None:
    code = case.ops_code
    if code is None:
        return None
    text = case.occ.text if case.occ else None
    quote = None
    if text:
        m = [p.strip() for p in re.split(r"\.\s+", text) if re.search(rf"\bRSN\s*{re.escape(code)}\b", p)]
        quote = m[0] if m else None
    sid, tier = find_source(case, SourceKind.OCC_LOG, (text or "")[:40] or None,
                            f"SRC-OCC-{case.occ.id}" if case.occ else "SRC-OCC")
    return Evidence(fact_id=nz.flight_fact_id(case.flight.id, "flight.ops_cause_code"), source_id=sid,
                    field="flight.ops_cause_code",
                    value=code, quote=quote, role=role, trust_tier=tier, struck=struck)


def _aog_ev(case: FlightCase) -> list[Evidence]:
    a = case.aog
    if a is None:
        return []
    t = a.entry
    src = find_source(case, SourceKind.TECH_LOG, t.text[:60] or None, f"SRC-TECHLOG-{t.id}")
    mel_q = _clause(t.text, "MEL") or _clause(t.text, "AOG")
    kw = [k for k in ("LEAK", "FAIL", "FAULT", "INOP", "BIRD", "LIGHTNING", "HAIL", "FOD", "CRACK") if k in t.text]
    ata_q = next((c for k in kw if (c := _clause(t.text, k))), None)
    head = re.match(r"^\s*(\d{2}[A-Z]{3}\s+\d{2}:\d{2}Z\s+\S+(?:\s+[A-Z]{3})?)", t.text)

    def ev_(fld: str, value, quote) -> Evidence:
        # an overlaid line cites the fact and source it came from, at their tier (blame reaches the injection)
        fid, sid, tier = provenance(case, t.id, fld, nz.techlog_fact_id(t.id, fld), src)
        return Evidence(fact_id=fid, source_id=sid, field=fld, value=value, quote=quote, role="supports",
                        trust_tier=tier)
    ev = [ev_("aog.mel_relief", t.mel_relief, mel_q), ev_("aog.ata_chapter", t.ata, ata_q),
          ev_("aog.logged_at", t.logged_at.isoformat().replace("+00:00", "Z"), head.group(1) if head else None)]
    for m in case.mcc:
        eta = re.search(r"ETA\s+(\d{2}:\d{2}Z)", m.text)
        msid, mtier = find_source(case, SourceKind.MCC_LOG, m.text[:40], f"SRC-MCC-{m.id}")
        q = re.search(r"[^;:]*ETA\s+\d{2}:\d{2}Z", m.text)
        ev.append(Evidence(fact_id=nz.ops_fact_id(m.id, case.flight.id, "mcc.part_eta"), source_id=msid,
                           field="mcc.part_eta",
                           value=eta.group(1) if eta else None, quote=q.group(0).strip() if q else m.text,
                           role="supports", trust_tier=mtier))
    return ev


def _spares_ev(case: FlightCase) -> list[Evidence]:
    out = []
    for e in case.spares:
        src = find_source(case, SourceKind.SPARES, e.text[:40], f"SRC-SPARES-{e.id}")
        fid, sid, tier = provenance(case, e.id, "spare.available_within_h",
                                    nz.ops_fact_id(e.id, case.flight.id, "spare.available_within_h"), src)
        out.append(Evidence(fact_id=fid, source_id=sid, field="spare.available_within_h",
                            value=case.spare_within_h, quote=e.text, role="supports", trust_tier=tier))
    return out


def _claim_ev(case: FlightCase) -> list[Evidence]:
    out = []
    for c in case.aog_claims:
        for fld in sorted(c.facts):
            out.append(Evidence(fact_id=c.facts[fld], source_id=c.source_id, field=fld,
                                value=c.logged_at.isoformat().replace("+00:00", "Z") if fld == "aog.logged_at"
                                else None, quote=c.text or None, role="context", trust_tier=c.tier))
    return out


def _sentence(text: str | None, *needles: str) -> str | None:
    """The first sentence of ``text`` holding a needle (tried in order), verbatim; else its first sentence."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text or "") if p.strip()]
    for n in needles:
        hit = next((p for p in parts if n and n.lower() in p.lower()), None)
        if hit is not None:
            return hit
    return parts[0] if parts else None


def _iso(t: datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def _kind(e: EventWindow) -> str:
    """'grid outage'."""
    return EVENT_KIND_LABEL.get(e.event.kind, e.event.kind.replace("_", " ")).lower()


def event_window_text(e: EventWindow) -> str:
    """'10:33Z–22:00Z (end approximate)'."""
    w = e.window
    end = hhmm(w.end) if w.end.date() == w.start.date() else dmy(w.end)
    return f"{hhmm(w.start)}–{end}" + (" (end approximate)" if e.approximate else "")


def _event_ev(case: FlightCase, role: str = "supports", end_role: str = "context") -> list[Evidence]:
    """The event as its operator notice states it: kind and window start quote the notice; the window (with the
    event's title, for the question) is engine context."""
    e = case.event
    if e is None:
        return []
    ev, a = e.event, e.airport
    src = next((case.sources[s] for s in ev.source_ids if s in case.sources), None)
    sid, tier = (src.id, src.trust_tier) if src is not None else (ev.source_ids[0] if ev.source_ids else "SRC-EVENT",
                                                                 4)
    text = src.text if src is not None else None
    kind_words = (ev.kind, ev.kind.replace("_", " "), "blackout", "outage", "power")
    return [
        Evidence(fact_id=nz.event_fact_id(ev.id, "event.kind"), source_id=sid, field="event.kind", value=ev.kind,
                 quote=_sentence(text, *kind_words), role=role, trust_tier=tier),
        Evidence(fact_id=nz.event_fact_id(ev.id, "event.window_start", a.icao), source_id=sid,
                 field="event.window_start", value=_iso(a.start),
                 quote=_sentence(text, hhmm(a.start), f"{a.start:%H:%M}", *kind_words), role=role, trust_tier=tier),
        Evidence(fact_id=nz.event_fact_id(ev.id, "event.window_end", a.icao), source_id=sid, field="event.window_end",
                 value=_iso(a.end), quote=None, role=end_role, trust_tier=tier),
        Evidence(fact_id=f"F-EVENT-WINDOW-{ev.id}:{a.icao}", source_id=sid, field="event.window",
                 value={"event_id": ev.id, "kind": ev.kind, "title": ev.title, "label": e.window.label,
                        "start": _iso(a.start), "end": _iso(a.end), "note": a.note},
                 quote=None, role="context", trust_tier=tier),
    ]


def _logged_internal(case: FlightCase) -> tuple[bool, OpsLogEntry, str] | None:
    """(crew?, line, verbatim clause): the carrier's own OCC/MCC line naming a crew-duty or positioning cause. A crew
    line wins over a positioning one; then the latest."""
    hits = []
    for line in sorted([*case.occ_lines, *case.mcc], key=lambda e: (e.at, e.id)):
        for crew, rx in ((True, CREW_DUTY), (False, POSITIONING)):
            m = rx.search(line.text)
            if m:
                hits.append((crew, line.at, line, _sentence(line.text, m.group(0)) or line.text))
    if not hits:
        return None
    crew, _, line, quote = max(hits, key=lambda h: (h[0], h[1], h[2].id))
    return crew, line, quote


def _end_ev(case: FlightCase, end: EndPosition, role_in: str, role_out: str) -> list[Evidence]:
    st = case.dep_station if end.end == "dep" else case.arr_station
    o = _nearest(st.obs, end.at)
    if o is None or end.position == "unknown":
        return []
    return [_metar_ev(case, o, role_in if end.position == "in" else role_out)]


def main_window(case: FlightCase) -> StormWindow | None:
    """The window the flight relates to: one it sits in, else the nearest at either end."""
    return case.window


def deciding_margin(case: FlightCase) -> int | None:
    """Non-negative minutes to the nearest window edge at the end that decides (in-end first, else nearest out).
    Storm and external-event windows both count (with no event, the event ends carry no margin)."""
    ends = [e for e in (case.dep, case.arr, case.dep_event, case.arr_event) if e is not None]
    ins = [e for e in ends if e.position == "in" and e.margin_min is not None]
    if ins:
        return max(abs(e.margin_min) for e in ins)
    outs = [e.margin_min for e in ends if e.position == "out" and e.margin_min is not None]
    return min(outs) if outs else None


# ---------- the decision ----------

def find_cause(case: FlightCase, prev_finding: Finding | None = None) -> Finding:
    f = case.flight
    dep, arr = case.positions
    in_any = "in" in (dep, arr)
    unknown_any = "unknown" in (dep, arr)
    code = case.ops_code
    aog = case.aog
    w = main_window(case)
    prev = case.prev
    # an AOG logged at another station (the tail never got here) on a return whose outbound was cancelled: the
    # outbound's cause travels with the rotation (knock-on below), not this AOG
    elsewhere = (aog is not None and aog.station is not None and aog.station != case.origin.icao
                 and prev is not None and prev.status == "cancelled" and prev_finding is not None)

    # 1-2: a no-go AOG is positive tier-1 evidence; concurrent only when the flight itself sits in a window
    if aog is not None and aog.decisive and not elsewhere:
        if not in_any and case.event_in and case.event is not None:
            ew = case.event
            when = "inside" if ew.window.start <= aog.entry.logged_at <= ew.window.end else "before"
            at_end = "departure" if case.dep_event is not None and case.dep_event.position == "in" else "arrival"
            return Finding(
                Cause.CONCURRENT, Extraordinary.NEEDS_LEGAL, "concurrent_causes",
                f"Concurrent causes: AOG logged {dmy(aog.entry.logged_at)} {when} the {_kind(ew)} window "
                f"({ew.event.title}, {event_window_text(ew)}), and the flight sits in it at {at_end}. Legal question.",
                route=Role.LEGAL, reason_tag="concurrent-causes",
                evidence=_aog_ev(case) + _event_ev(case) + _end_ev(case, case.dep, "context", "context")
                + _end_ev(case, case.arr, "context", "context") + [e for e in [_occ_ev(case, "context")] if e],
                legal_basis=LB["concurrent_causes"])
        if in_any:
            when = "inside" if aog.inside_window else "before"
            return Finding(
                Cause.CONCURRENT, Extraordinary.NEEDS_LEGAL, "concurrent_causes",
                f"Concurrent causes: AOG logged {dmy(aog.entry.logged_at)} {when} the storm window, and the flight "
                f"sits in the window at {'departure' if dep == 'in' else 'arrival'}. Legal question.",
                route=Role.LEGAL, reason_tag="concurrent-causes",
                evidence=_aog_ev(case) + _end_ev(case, case.dep, "supports", "context")
                + _end_ev(case, case.arr, "supports", "context") + ([_window_ev(case, w)] if w else [])
                + [e for e in [_occ_ev(case, "context")] if e],
                legal_basis=LB["concurrent_causes"])
        recoded = code is not None and code not in TECH_CODES
        if aog.cls.internal:
            win_txt = (f"{case.origin.iata} window closed {hhmm(w.end)}, {deciding_margin(case)} min before STD"
                       if w and w.end <= f.sched_dep else "no storm window reaches the flight")
            when = ("before the storm" if aog.before_window else "during an earlier storm window"
                    if aog.inside_window else "outside any storm window")
            return Finding(
                Cause.TECHNICAL, Extraordinary.NO, "technical_internal",
                f"Not weather: {aog.cls.defect} (ATA {aog.cls.chapter}) logged "
                f"{dmy(aog.entry.logged_at)} with no MEL relief, {when}; {win_txt}.",
                recoded=recoded, new_code="41" if recoded else None,
                evidence=_aog_ev(case) + _end_ev(case, case.dep, "contradicts", "supports")
                + _end_ev(case, case.arr, "contradicts", "supports") + ([_window_ev(case, w)] if w else [])
                + [e for e in [_occ_ev(case, "contradicts", struck=recoded)] if e],
                legal_basis=LB["technical_internal"])
        when = "before the storm" if aog.before_window else "during an earlier storm window"
        return Finding(
            Cause.TECHNICAL, Extraordinary.NEEDS_LEGAL, "external_event",
            f"Not weather: AOG logged {dmy(aog.entry.logged_at)} {when}, root cause "
            f"{aog.cls.category} ({', '.join(aog.cls.matched) or 'no ATA match'}). Legal question.",
            recoded=recoded, new_code="41" if recoded else None, route=Role.LEGAL, reason_tag="no-precedent",
            evidence=_aog_ev(case) + [e for e in [_occ_ev(case, "contradicts", struck=recoded)] if e]
            + ([_window_ev(case, w)] if w else []),
            legal_basis=LB["external_event"])

    # 3: an AOG asserted only below tier 1 is a claim to verify, never a cause
    if case.aog_claims and not (aog is not None and aog.decisive):
        c = case.aog_claims[-1]
        return Finding(
            Cause.UNKNOWN, Extraordinary.NEEDS_LEGAL, "aog_unverified",
            f"An AOG on {f.aircraft} ({dmy(c.logged_at)}) is claimed by {c.source_id} (tier {c.tier}) but no tech-log "
            "or MCC entry confirms it. Ops to verify before the cause is decided.",
            route=Role.OPS, reason_tag="sources-disagree", sources_disagree=True,
            evidence=_claim_ev(case) + _end_ev(case, case.dep, "context", "context")
            + _end_ev(case, case.arr, "context", "context") + [e for e in [_occ_ev(case, "context")] if e],
            legal_basis=LB["aog_unverified"], caps=["capped:no-tier1-evidence"])

    # 4: weather at either end
    if in_any:
        end = case.dep if dep == "in" else case.arr
        st = case.dep_station if end.end == "dep" else case.arr_station
        o = _nearest(st.obs, end.at)
        where = case.origin.iata if end.end == "dep" else case.dest.iata
        gust = f"gusts {o.gust} kt" if o is not None and o.gust is not None else "storm conditions"
        wtxt = f", inside the {hhmm(w.start)}–{hhmm(w.end)} storm window" if w else ""
        metar_ev = (_end_ev(case, case.dep, "supports", "context") + _end_ev(case, case.arr, "supports", "context")
                    + ([_window_ev(case, w)] if w else []))
        if code in CODE_GROUP:
            # OCC names a non-weather cause the logs don't confirm, inside a storm window: sources disagree
            return Finding(
                Cause.UNKNOWN, Extraordinary.NEEDS_LEGAL, "occ_code_in_window",
                f"OCC coded {CODE_GROUP[code]} ({code}), but {where} had {gust} near "
                f"{'STD' if end.end == 'dep' else 'STA'} {hhmm(end.at)}{wtxt}, and no tech-log entry confirms a "
                "defect. Ops to confirm the cause.",
                route=Role.OPS, reason_tag="sources-disagree", sources_disagree=True,
                evidence=metar_ev + [e for e in [_occ_ev(case, "contradicts")] if e],
                legal_basis=LB["occ_code_in_window"], caps=["capped:sources-disagree"])
        recoded = code is not None and code not in WEATHER_CODES
        return Finding(
            Cause.WEATHER, Extraordinary.YES, "weather",
            f"Weather: {where} {gust} near {'STD' if end.end == 'dep' else 'STA'} {hhmm(end.at)}{wtxt}.",
            recoded=recoded, new_code=NEW_CODE[Cause.WEATHER] if recoded else None,
            evidence=metar_ev + [e for e in [_occ_ev(case, "contradicts" if recoded else "supports",
                                                     struck=recoded)] if e],
            legal_basis=LB["weather"])

    # 4b: inside an external event's window (a grid outage) at either end, no decisive AOG: a new pattern for Legal
    if case.event_in and case.event is not None:
        ew = case.event
        dep_in = case.dep_event is not None and case.dep_event.position == "in"
        where, at = (case.origin.iata, f"STD {hhmm(f.sched_dep)}") if dep_in else (case.dest.iata,
                                                                                   f"STA {hhmm(f.sched_arr)}")
        return Finding(
            Cause.EXTERNAL_EVENT, Extraordinary.NEEDS_LEGAL, "external_event_window",
            f"{ew.event.title}: {where} inside the {_kind(ew)} window {event_window_text(ew)} at {at}, and no "
            "aircraft defect grounds the flight. No precedent for this event: Legal question.",
            route=Role.LEGAL, reason_tag="no-precedent",
            evidence=_event_ev(case) + _end_ev(case, case.dep, "context", "context")
            + _end_ev(case, case.arr, "context", "context") + [e for e in [_occ_ev(case, "context")] if e],
            legal_basis=LB["external_event_window"])

    # 4c: cancelled after an event window closed: judged on its own evidence. The carrier's own OCC/MCC log naming
    # crew out of duty hours or an aircraft out of position is an internal cause (owed); else on to the knock-on.
    logged = _logged_internal(case) if case.after_event and case.event is not None and not in_any else None
    if logged is not None:
        crew, line, quote = logged
        ew = case.event
        group, new = (CREW_CODES, NEW_CODE[Cause.CREW]) if crew else (ROTATION_CODES | TECH_CODES, "93")
        recoded = code is not None and code not in group
        closed_at = ew.window.station == case.origin.icao and ew.window.end <= f.sched_dep
        at = f"STD {hhmm(f.sched_dep)}" if closed_at else f"STA {hhmm(f.sched_arr)}"
        log_field = "occ.text" if line.kind == "occ" else "mcc.text"
        sid, tier = find_source(case, SourceKind.OCC_LOG if line.kind == "occ" else SourceKind.MCC_LOG,
                                line.text[:40], f"SRC-{line.id}")
        return Finding(
            Cause.CREW if crew else Cause.TECHNICAL, Extraordinary.NO, "internal_cause_logged",
            f"Not the {ew.event.title}: the {_kind(ew)} window at {ew.window.station} had closed "
            f"({event_window_text(ew)}) before {at}; the OCC log records "
            f"{'crew out of duty hours' if crew else 'the aircraft out of position'}: \"{quote}\". Compensation owed.",
            recoded=recoded, new_code=new if recoded else None,
            evidence=[Evidence(fact_id=nz.ops_fact_id(line.id, f.id, log_field), source_id=sid, field=log_field,
                               value=line.text, quote=quote, role="supports", trust_tier=tier)]
            + _event_ev(case, role="context", end_role="supports")
            + _end_ev(case, case.dep, "contradicts", "supports") + _end_ev(case, case.arr, "contradicts", "supports")
            + [e for e in [_occ_ev(case, "contradicts", struck=recoded)] if e],
            legal_basis=LB["internal_cause_logged"])

    # 5: knock-on (previous rotation of the tail cancelled)
    if prev is not None and prev.status == "cancelled" and prev_finding is not None:
        rot = [Evidence(fact_id=f"F-ROT-{f.number}-prev", source_id="SRC-SCHEDULE", field="rotation.prev_cancelled",
                        value=True, quote=f"{prev.number} {prev.origin}-{prev.dest} {hhmm(prev.sched_dep)} CNL",
                        role="supports", trust_tier=2)]
        calm = (f"{case.origin.iata} {'calm' if dep == 'out' else 'no METAR'} at STD, "
                f"{case.dest.iata} {'calm' if arr == 'out' else 'no METAR'} at STA")
        if prev_finding.extraordinary == Extraordinary.YES:
            return Finding(
                Cause.KNOCK_ON, Extraordinary.NEEDS_LEGAL, "knock_on_return",
                f"Knock-on: {prev.number} was cancelled for {prev_finding.cause.value}, so {f.aircraft} never "
                f"reached {case.origin.iata}; {calm}. Legal question (C-74/19).",
                route=Role.LEGAL, reason_tag="no-precedent",
                evidence=rot + _end_ev(case, case.dep, "contradicts", "context")
                + _end_ev(case, case.arr, "contradicts", "context") + _spares_ev(case)
                + ([_window_ev(case, w)] if w else []) + [e for e in [_occ_ev(case, "context")] if e],
                legal_basis=LB["knock_on_return"],
                caps=["capped:window-unknown"] if unknown_any else [])
        if prev_finding.extraordinary == Extraordinary.NO:
            recoded = code is not None and code not in ROTATION_CODES and code not in TECH_CODES | CREW_CODES
            return Finding(
                Cause.KNOCK_ON, Extraordinary.NO, "knock_on_internal",
                f"Knock-on of an internal cause: {prev.number} was cancelled ({prev_finding.cause.value}), so "
                f"{f.aircraft} never reached {case.origin.iata}; {calm}.",
                recoded=recoded, new_code="93" if recoded else None,
                evidence=rot + [e for e in [_occ_ev(case, "contradicts", struck=recoded)] if e],
                legal_basis=LB["knock_on_internal"])
        # previous rotation itself undecided: follow it to the same person
        return Finding(
            Cause.KNOCK_ON, Extraordinary.NEEDS_LEGAL, "knock_on_return",
            f"Knock-on: {prev.number} was cancelled ({prev_finding.cause.value}, undecided), so {f.aircraft} never "
            f"reached {case.origin.iata}; {calm}.",
            route=prev_finding.route or Role.LEGAL, reason_tag=prev_finding.reason_tag or "no-precedent",
            evidence=rot + [e for e in [_occ_ev(case, "context")] if e], legal_basis=LB["knock_on_return"])

    # 5: no METAR at an end. With one end known calm, a weather code naming that end is contradicted, and a
    # non-weather code is taken at its word below (weather at the unseen end is not what OCC claimed).
    if unknown_any:
        coded_end = arr if code == "72" else dep
        known_group = code in TECH_CODES | CREW_CODES | ATC_CODES | AIRPORT_CODES | ROTATION_CODES
        if "out" not in (dep, arr):
            gap = True
        elif code in WEATHER_CODES:
            gap = coded_end != "out"
        else:
            gap = not known_group
    else:
        gap = False
    if gap:
        miss = " and ".join(st for st, p in ((f"{case.origin.iata} at STD", dep), (f"{case.dest.iata} at STA", arr))
                            if p == "unknown")
        return Finding(
            Cause.UNKNOWN, Extraordinary.NEEDS_LEGAL, "window_unknown",
            f"No METAR within 60 min for {miss}; OCC code {code or 'none'} cannot be checked. Ops to confirm.",
            route=Role.OPS, reason_tag="out-of-scope",
            evidence=_end_ev(case, case.dep, "supports", "context") + _end_ev(case, case.arr, "supports", "context")
            + [e for e in [_occ_ev(case, "context")] if e],
            legal_basis=LB["window_unknown"], caps=["capped:window-unknown"])

    # out of window at both ends, no tier-1 cause
    calm = (f"{case.origin.iata} calm at STD {hhmm(f.sched_dep)}, {case.dest.iata} calm at STA "
            f"{hhmm(f.sched_arr)}" + (f" (window {hhmm(w.start)}–{hhmm(w.end)})" if w else ""))
    occ_contra = [e for e in [_occ_ev(case, "contradicts")] if e]
    metar = _end_ev(case, case.dep, "supports", "contradicts") + _end_ev(case, case.arr, "supports", "contradicts")
    if code in WEATHER_CODES:
        return Finding(
            Cause.UNKNOWN, Extraordinary.NEEDS_LEGAL, "weather_code_contradicted",
            f"OCC coded weather ({code}) but METAR is calm: {calm}; no tech-log cause found. Ops to confirm.",
            route=Role.OPS, reason_tag="sources-disagree", sources_disagree=True,
            evidence=metar + ([_window_ev(case, w)] if w else []) + occ_contra,
            legal_basis=LB["weather_code_contradicted"], caps=["capped:sources-disagree"])
    occ_sup = [e for e in [_occ_ev(case, "supports")] if e]
    if code in TECH_CODES:
        return Finding(Cause.TECHNICAL, Extraordinary.NO, "technical_unverified",
                       f"Technical per OCC code {code}; {calm}. No tech-log entry found to confirm.",
                       route=Role.OPS, reason_tag="out-of-scope", evidence=metar + occ_sup,
                       legal_basis=LB["technical_unverified"], caps=["capped:no-tier1-evidence"])
    if code in CREW_CODES:
        return Finding(Cause.CREW, Extraordinary.NO, "crew", f"Crew per OCC code {code}; {calm}.",
                       route=Role.OPS, reason_tag="out-of-scope", evidence=metar + occ_sup, legal_basis=LB["crew"])
    if code in ATC_CODES:
        return Finding(Cause.ATC, Extraordinary.YES, "atc", f"ATC restriction per OCC code {code}; {calm}.",
                       route=Role.OPS, reason_tag="out-of-scope", evidence=metar + occ_sup, legal_basis=LB["atc"])
    if code in AIRPORT_CODES:
        # like ATC: an extraordinary event the OCC claims and the logs can't confirm, so Ops confirms it and the
        # entitlements stay held meanwhile (eu261) — but it is not an ATC restriction
        return Finding(Cause.UNKNOWN, Extraordinary.YES, "airport_restriction",
                       f"Security, customs or airport restriction per OCC code {code} (not ATC); {calm}. "
                       "Ops to confirm.",
                       route=Role.OPS, reason_tag="out-of-scope", evidence=metar + occ_sup,
                       legal_basis=LB["airport_restriction"], caps=["capped:no-tier1-evidence"])
    return Finding(Cause.UNKNOWN, Extraordinary.NEEDS_LEGAL, "cause_unknown",
                   f"No cause evidence: OCC code {code or 'none'}; {calm}. Ops to confirm.",
                   route=Role.OPS, reason_tag="out-of-scope", evidence=metar + occ_contra,
                   legal_basis=LB["cause_unknown"], caps=["capped:no-tier1-evidence"])


def recode_label(old: str | None, new: str | None) -> str | None:
    if new is None:
        return None
    return f"{old or '—'} → {new}"
