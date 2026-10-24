"""D2 · What really caused a cancellation, decided deterministically from ranked evidence.

Priority (THREAD_DAVID D2):
1. AOG with no MEL relief, logged outside any storm window, internal root cause, flight not in a window at either
   end -> ``technical / not_extraordinary``. A recode needs this positive tier-1 evidence (the tech log).
2. AOG inside the window (or a no-go AOG while the flight sits in a window) -> ``concurrent / needs_legal``.
3. In a window at either end, no AOG -> ``weather / extraordinary``.
4. Return sector whose outbound (previous rotation) was cancelled for weather, out at both ends ->
   ``knock_on / needs_legal`` unless an active legal rule settles it (applied by the engine, not here).
5. ``unknown`` window -> ``unknown / needs_legal`` routed to Ops.
Then, out of window at both ends with no tier-1 cause: the OCC code is never trusted alone. A weather code
contradicted by METAR goes to Ops (sources disagree); other codes map to their IATA group.

Spares are never a feature or evidence for a technical cause (no Art. 5(3) reasonable-measures test applies).
Pure: no wall clock, no randomness, no LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from contracts.models import Cause, Evidence, Extraordinary, MetarObs, Role, SourceKind, StormWindow
from engine.case import FlightCase, find_source
from engine.timeline import EndPosition

# IATA delay-code groups (AHM 730)
WEATHER_CODES = {"71", "72", "73", "75", "76", "77"}
TECH_CODES = {"41", "42", "43", "44", "45", "46", "47", "48"}
CREW_CODES = {"61", "62", "63", "64", "65", "66", "67", "68", "69", "94", "95"}
ATC_CODES = {"81", "82", "83", "84", "85", "86", "87", "88", "89"}
ROTATION_CODES = {"91", "92", "93", "96"}
NEW_CODE = {Cause.TECHNICAL: "41", Cause.CREW: "64", Cause.ATC: "81", Cause.KNOCK_ON: "93"}

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
    "cause_unknown": [LB_ART53],
}


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


def metar_fact_id(o: MetarObs) -> str:
    return f"F-METAR-{o.station}-{o.valid:%Y%m%dT%H%MZ}"


def window_fact_id(w: StormWindow) -> str:
    return f"F-WINDOW-{w.station}@{w.start:%Y-%m-%d}T{w.start:%H%M}Z"


def _metar_ev(case: FlightCase, o: MetarObs, role: str) -> Evidence:
    sid, tier = find_source(case, SourceKind.METAR, o.raw, f"SRC-METAR-{o.station}")
    gust = o.gust if o.gust is not None else o.sknt
    return Evidence(fact_id=metar_fact_id(o), source_id=sid, field="metar.gust_kt", value=gust, quote=o.raw,
                    role=role, trust_tier=tier)


def _window_ev(case: FlightCase, w: StormWindow) -> Evidence:
    sid, tier = find_source(case, SourceKind.METAR, None, f"SRC-METAR-{w.station}")
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
    return Evidence(fact_id=f"F-OCC-{case.flight.number}-code", source_id=sid, field="flight.ops_cause_code",
                    value=code, quote=quote, role=role, trust_tier=tier, struck=struck)


def _aog_ev(case: FlightCase) -> list[Evidence]:
    a = case.aog
    if a is None:
        return []
    t = a.entry
    sid, tier = find_source(case, SourceKind.TECH_LOG, t.text[:60] or None, f"SRC-TECHLOG-{t.id}")
    base = f"F-TL-{t.aircraft}-{t.logged_at:%Y%m%dT%H%MZ}"
    mel_q = _clause(t.text, "MEL") or _clause(t.text, "AOG")
    kw = [k for k in ("LEAK", "FAIL", "FAULT", "INOP", "BIRD", "LIGHTNING", "HAIL", "FOD", "CRACK") if k in t.text]
    ata_q = next((c for k in kw if (c := _clause(t.text, k))), None)
    head = re.match(r"^\s*(\d{2}[A-Z]{3}\s+\d{2}:\d{2}Z\s+\S+(?:\s+[A-Z]{3})?)", t.text)
    ev = [
        Evidence(fact_id=f"{base}-aog", source_id=sid, field="aog.mel_relief", value=t.mel_relief, quote=mel_q,
                 role="supports", trust_tier=tier),
        Evidence(fact_id=f"{base}-ata", source_id=sid, field="aog.ata_chapter", value=t.ata, quote=ata_q,
                 role="supports", trust_tier=tier),
        Evidence(fact_id=f"{base}-logged", source_id=sid, field="aog.logged_at",
                 value=t.logged_at.isoformat().replace("+00:00", "Z"), quote=head.group(1) if head else None,
                 role="supports", trust_tier=tier),
    ]
    for m in case.mcc:
        eta = re.search(r"ETA\s+(\d{2}:\d{2}Z)", m.text)
        msid, mtier = find_source(case, SourceKind.MCC_LOG, m.text[:40], f"SRC-MCC-{m.id}")
        q = re.search(r"[^;:]*ETA\s+\d{2}:\d{2}Z", m.text)
        ev.append(Evidence(fact_id=f"F-MCC-{m.id}", source_id=msid, field="mcc.part_eta",
                           value=eta.group(1) if eta else None, quote=q.group(0).strip() if q else m.text,
                           role="supports", trust_tier=mtier))
    return ev


def _spares_ev(case: FlightCase) -> list[Evidence]:
    out = []
    for e in case.spares:
        sid, tier = find_source(case, SourceKind.SPARES, e.text[:40], f"SRC-SPARES-{e.id}")
        out.append(Evidence(fact_id=f"F-SPARES-{e.id}", source_id=sid, field="spare.available_within_h",
                            value=case.spare_within_h, quote=e.text, role="supports", trust_tier=tier))
    return out


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
    """Non-negative minutes to the nearest window edge at the end that decides (in-end first, else nearest out)."""
    ends = [case.dep, case.arr]
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

    # 1-2: a no-go AOG is positive tier-1 evidence
    if aog is not None and aog.decisive:
        if aog.inside_window or in_any:
            when = "inside" if aog.inside_window else "before"
            return Finding(
                Cause.CONCURRENT, Extraordinary.NEEDS_LEGAL, "concurrent_causes",
                f"Concurrent causes: AOG logged {dmy(aog.entry.logged_at)} {when} the storm window, and the flight "
                f"sits in the window at {'departure' if dep == 'in' else 'arrival' if arr == 'in' else 'neither end'}. "
                "Legal question.",
                route=Role.LEGAL, reason_tag="concurrent-causes",
                evidence=_aog_ev(case) + _end_ev(case, case.dep, "supports", "context")
                + _end_ev(case, case.arr, "supports", "context") + ([_window_ev(case, w)] if w else [])
                + [e for e in [_occ_ev(case, "context")] if e],
                legal_basis=LB["concurrent_causes"])
        recoded = code is not None and code not in TECH_CODES
        if aog.cls.internal:
            win_txt = (f"{case.origin.iata} window closed {hhmm(w.end)}, {deciding_margin(case)} min before STD"
                       if w and w.end <= f.sched_dep else "no storm window reaches the flight")
            return Finding(
                Cause.TECHNICAL, Extraordinary.NO, "technical_internal",
                f"Not weather: {aog.cls.defect} (ATA {aog.cls.chapter}) logged "
                f"{dmy(aog.entry.logged_at)} with no MEL relief, "
                f"{'before the storm' if aog.before_window else 'outside any storm window'}; {win_txt}.",
                recoded=recoded, new_code="41" if recoded else None,
                evidence=_aog_ev(case) + _end_ev(case, case.dep, "contradicts", "supports")
                + _end_ev(case, case.arr, "contradicts", "supports") + ([_window_ev(case, w)] if w else [])
                + [e for e in [_occ_ev(case, "contradicts", struck=recoded)] if e],
                legal_basis=LB["technical_internal"])
        return Finding(
            Cause.TECHNICAL, Extraordinary.NEEDS_LEGAL, "external_event",
            f"Not weather: AOG logged {dmy(aog.entry.logged_at)} before the storm, root cause "
            f"{aog.cls.category} ({', '.join(aog.cls.matched) or 'no ATA match'}). Legal question.",
            recoded=recoded, new_code="41" if recoded else None, route=Role.LEGAL, reason_tag="no-precedent",
            evidence=_aog_ev(case) + [e for e in [_occ_ev(case, "contradicts", struck=recoded)] if e]
            + ([_window_ev(case, w)] if w else []),
            legal_basis=LB["external_event"])

    # 3: weather at either end
    if in_any:
        end = case.dep if dep == "in" else case.arr
        st = case.dep_station if end.end == "dep" else case.arr_station
        o = _nearest(st.obs, end.at)
        where = case.origin.iata if end.end == "dep" else case.dest.iata
        gust = f"gusts {o.gust} kt" if o is not None and o.gust is not None else "storm conditions"
        wtxt = f", inside the {hhmm(w.start)}–{hhmm(w.end)} storm window" if w else ""
        disagree = code is not None and code not in WEATHER_CODES and code not in ROTATION_CODES
        return Finding(
            Cause.WEATHER, Extraordinary.YES, "weather",
            f"Weather: {where} {gust} near {'STD' if end.end == 'dep' else 'STA'} {hhmm(end.at)}{wtxt}.",
            evidence=_end_ev(case, case.dep, "supports", "context") + _end_ev(case, case.arr, "supports", "context")
            + ([_window_ev(case, w)] if w else []) + [e for e in [_occ_ev(case, "contradicts" if disagree else
                                                                         "supports")] if e],
            legal_basis=LB["weather"], sources_disagree=disagree,
            caps=["capped:sources-disagree"] if disagree else [])

    # 4: knock-on (previous rotation of the tail cancelled)
    prev = case.prev
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
        known_group = code in TECH_CODES | CREW_CODES | ATC_CODES | ROTATION_CODES
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
    return Finding(Cause.UNKNOWN, Extraordinary.NEEDS_LEGAL, "cause_unknown",
                   f"No cause evidence: OCC code {code or 'none'}; {calm}. Ops to confirm.",
                   route=Role.OPS, reason_tag="out-of-scope", evidence=metar + occ_contra,
                   legal_basis=LB["cause_unknown"], caps=["capped:no-tier1-evidence"])


def recode_label(old: str | None, new: str | None) -> str | None:
    if new is None:
        return None
    return f"{old or '—'} → {new}"
