"""`GET /api/blame?target=`: walk € → entitlement → rule@v → ruling → decision → facts → span → METAR obs.

Uses `engine.trace.blame` once it lands; until then it walks the server's own commit chain. Targets: a JE
(`JE-000001`) or JE line (`JE-000001:2`), a coupon (`NS31@2025-01-24:14C`), a flight (`NS31@2025-01-24`), a rule
(`R-LEG-1` or `R-LEG-1@1`), a question (`Q-1`). Unknown targets return an empty chain, never an error.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from contracts.models import Blame, BlameStep, Commit, Entitlement, FlightDecision, Rule, Ruling

from . import compose
from .impls import _module

if TYPE_CHECKING:
    from .runtime import Runtime

JE_RE = re.compile(r"^(JE-\d+)(?::(\d+))?$")
COUPON_RE = re.compile(r"^([A-Za-z0-9]+@\d{4}-\d{2}-\d{2}):([A-Za-z0-9]+)$")


def _last(commits: list[Commit]) -> Commit | None:
    return commits[-1] if commits else None


class Blamer:
    def __init__(self, rt: "Runtime"):
        self.rt = rt
        self.store = rt.store

    def blame(self, target: str) -> Blame:
        tr = _module("engine.trace")
        ext = getattr(tr, "blame", None) if tr else None
        if ext is not None and getattr(self.rt, "engine_trace", None) is not None:
            try:
                out = ext(self.rt.engine_trace, target)
                if isinstance(out, Blame):
                    return out
            except Exception:
                pass
        steps: list[BlameStep] = []
        try:
            self._walk(target.strip(), steps)
        except Exception:
            pass
        return Blame(target=target, steps=steps)

    # ------------------------------------------------------------------ walk
    def _walk(self, target: str, steps: list[BlameStep]) -> None:
        m = JE_RE.match(target)
        if m:
            return self._from_je(m.group(1), int(m.group(2)) if m.group(2) else None, steps)
        m = COUPON_RE.match(target)
        if m:
            return self._from_flight(m.group(1), steps, coupon=target)
        if self.store.get("decision", target) is not None:
            return self._from_flight(target, steps)
        if target.startswith("R-"):
            return self._from_rule(target, steps)
        if target.startswith("Q-"):
            c = _last(self.store.commits_for(target, ["question"]))
            if c is not None:
                q = self.store.commit_payload(c.hash) or {}
                steps.append(BlameStep(commit=c, label=f"Question {target} → {compose.label(q.get('routed_to'))} · "
                                                       f"{q.get('pattern', '')}", quote=q.get("why_flagged")))
                rf = self.store.get("ruling_for", target)
                if rf:
                    self._ruling(rf["ruling_id"], steps)
                for ref_ in (q.get("case_refs") or [])[:3]:
                    self._from_flight(COUPON_RE.match(ref_).group(1) if COUPON_RE.match(ref_) else ref_, steps)

    def _from_je(self, je_id: str, line_no: int | None, steps: list[BlameStep]) -> None:
        c = _last(self.store.commits_for(je_id, ["journal_event"]))
        if c is None:
            return
        je = self.store.commit_payload(c.hash) or {}
        lines = je.get("lines") or []
        if line_no is not None and 1 <= line_no <= len(lines):
            ln = lines[line_no - 1]
            side = f"Dr {ln['account']}" if ln.get("dr_cents") else f"Cr {ln['account']}"
            amt = ln.get("dr_cents") or ln.get("cr_cents") or 0
            label = f"{je_id}:{line_no} · {side} {ln.get('account_name', '')} {compose.eur(amt)} · drafted, pending " \
                    "approval"
        else:
            label = f"{je_id} · {je.get('kind', '')} · drafted, pending approval"
        steps.append(BlameStep(commit=c, label=label, quote=(je.get("memo") or "")[:240] or None))
        fid = None
        for ln in lines:
            fid = fid or (ln.get("dims") or {}).get("flight")
        src = je.get("source_decision_id")
        if src and self.store.commit_by_hash(src) is not None and not fid:
            fid = self.store.commit_by_hash(src).payload_ref
        if fid:
            self._from_flight(fid, steps)

    def _from_flight(self, fid: str, steps: list[BlameStep], coupon: str | None = None) -> None:
        dc = _last(self.store.commits_for(fid, ["decision"]))
        if dc is None:
            return
        d = FlightDecision.model_validate(self.store.commit_payload(dc.hash))
        ec = _last(self.store.commits_for(fid, ["entitlement"]))
        coupon_rules: list[str] = []
        if ec is not None:
            ents = [Entitlement.model_validate(e) for e in (self.store.commit_payload(ec.hash) or [])]
            if coupon:
                e = next((x for x in ents if x.coupon_id == coupon), None)
                if e is not None:
                    steps.append(BlameStep(commit=ec, label=f"Entitlement {coupon} · {e.status} · "
                                                            f"{compose.eur(e.compensation_cents)} · {e.article}",
                                           quote=e.reason))
                    coupon_rules = list(e.rules_applied)
            else:
                total = sum(e.compensation_cents for e in ents)
                by_band: dict[tuple[int, str], int] = {}
                for e in ents:
                    if e.compensation_cents:
                        by_band[(e.compensation_cents, e.reduction)] = by_band.get((e.compensation_cents, e.reduction),
                                                                                   0) + 1
                parts = " + ".join(f"{n} × {compose.eur(c)}" for (c, _), n in sorted(by_band.items(), reverse=True))
                steps.append(BlameStep(commit=ec, label=f"{fid.split('@')[0]} entitlement · "
                                                        f"{parts + ' = ' if parts else ''}{compose.eur(total)}",
                                       quote=ents[0].reason if ents else None))
                coupon_rules = sorted({r for e in ents for r in e.rules_applied})
        for r in dict.fromkeys([*coupon_rules, *d.rules_applied]):
            self._from_rule(r, steps, shallow=True)
        conf = d.confidence.score
        steps.append(BlameStep(commit=dc, label=f"Decision · {d.cause.value} · {d.extraordinary.value.replace('_', ' ')}"
                                                + (f" · recoded {d.recode_label}" if d.recoded else "")
                                                + (f" · cause-finding confidence {round(conf * 100)}%"
                                                   if conf is not None else " · uncalibrated"), quote=d.reason))
        ev = sorted(d.evidence, key=lambda e: (e.field.startswith(("metar.", "storm.")), e.struck, e.trust_tier))
        for e in ev:
            sc = _last(self.store.commits_for(e.source_id, ["fact"])) or dc
            what = "METAR obs" if e.field.startswith(("metar.", "storm.")) else f"Fact · {e.field}"
            label = f"{what} (tier {e.trust_tier})" + (" · struck: a higher-tier source wins" if e.struck else "")
            steps.append(BlameStep(commit=sc, label=label, quote=e.quote))

    def _from_rule(self, rule_ref: str, steps: list[BlameStep], shallow: bool = False) -> None:
        rid = rule_ref.split("@", 1)[0]
        data = self.store.get("rule", rid)
        if data is None:
            return
        rule = Rule.model_validate(data)
        rc = _last(self.store.commits_for(f"{rule.id}@{rule.version}", ["rule_event", "revert"])) or \
            _last(self.store.commits_for(rule_ref, ["rule_event", "revert"]))
        if rc is None:
            return
        support = f" · {rule.support}" if rule.support else ""
        steps.append(BlameStep(commit=rc, label=f"{rule.id}@{rule.version} · {rule.tier.replace('_', ' ')} · "
                                                f"{rule.status}{support}", quote=rule.title))
        if rule.origin_ruling_id:
            self._ruling(rule.origin_ruling_id, steps)

    def _ruling(self, ruling_id: str, steps: list[BlameStep]) -> None:
        c = _last(self.store.commits_for(ruling_id, ["ruling"]))
        if c is None:
            return
        r = Ruling.model_validate(self.store.commit_payload(c.hash))
        steps.append(BlameStep(commit=c, label=f"Ruling {r.id} · {compose.label(r.author_role)} ({r.author}) · "
                                               f"{r.kind}", quote=r.decision))


def audit(rt: "Runtime", je_id: str) -> dict[str, Any] | None:
    books = rt.books
    if books is None:
        return None
    try:
        out = dict(books.audit(je_id))
    except Exception:
        return None
    commits = []
    for h in out.get("decision_commits", []) or []:
        c = rt.store.commit_by_hash(h) if isinstance(h, str) else None
        commits.append(c.model_dump(mode="json") if c else h)
    out["decision_commits"] = commits
    je = out.get("je") or {}
    fids = {(ln.get("dims") or {}).get("flight") for ln in je.get("lines", [])} - {None}
    srcs = set()
    for fid in fids:
        d = rt.store.get("decision", fid)
        if d:
            srcs |= {e["source_id"] for e in d.get("evidence", [])}
    out["sources"] = sorted(srcs)
    out["blame_target"] = f"{je_id}:{max(1, len(je.get('lines', [])))}"
    out["je_commits"] = [c.model_dump(mode="json") for c in rt.store.commits_for(je_id)]
    return out
