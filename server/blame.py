"""`GET /api/blame?target=` and `GET /api/audit/{je_id}` over `engine.trace.TraceStore`.

Blame walks € → entitlement → decision → rule@v → ruling (author + quote) → question → facts (span) → source →
METAR obs (the trace's stored links). Quotes are redacted per viewer with `acl.Broker.redact` (the trace itself does
not redact). An unknown target is an empty chain, never an error.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from contracts.models import Blame, BlameStep, Session

from . import ledger

if TYPE_CHECKING:
    from .runtime import Runtime


class Blamer:
    def __init__(self, rt: "Runtime"):
        self.rt = rt

    def blame(self, target: str, viewer: Session | None = None) -> Blame:
        try:
            b = self.rt.trace.blame(target.strip())
        except Exception:
            return Blame(target=target, steps=[])
        if not isinstance(b, Blame):
            return Blame(target=target, steps=[])
        b = b.model_copy(update={"target": target, "steps": self.money_first(target, b.steps)})
        broker = self.rt.broker
        if broker is not None and viewer is not None and not broker.sees_pii(viewer):
            b = broker.redact(viewer, b)
        return b


    def money_first(self, target: str, steps: list[BlameStep]) -> list[BlameStep]:
        """A journal step's label leads with its amount and its Dr / Cr accounts (read back from Books)."""
        books = self.rt.books
        if books is None or not hasattr(books, "journal_entry"):
            return steps
        out, jes = [], {}
        for s in steps:
            je_id = s.commit.payload_ref
            if s.commit.kind == "journal_event" and je_id not in jes:
                try:
                    jes[je_id] = books.journal_entry(je_id)
                except Exception:
                    jes[je_id] = None
            je = jes.get(je_id) if s.commit.kind == "journal_event" else None
            if je is None:
                out.append(s)
                continue
            line = target.strip()[len(je_id) + 1:] if target.strip().startswith(f"{je_id}:") else ""
            out.append(s.model_copy(update={"label": ledger.blame_label(je, int(line) if line.isdigit() else None)}))
        return out


def audit(rt: "Runtime", je_id: str) -> dict[str, Any] | None:
    """Books' audit (JE, events, register rows, claims) + the decision commits resolved + the JE's own commits."""
    books = rt.books
    if books is None:
        return None
    try:
        out = dict(books.audit(je_id))
    except Exception:
        return None
    commits = []
    for h in out.get("decision_commits", []) or []:
        try:
            commits.append(rt.trace.get(h).model_dump(mode="json"))
        except Exception:
            commits.append(h)
    out["decision_commits"] = commits
    je = out.get("je") or {}
    if je.get("kind"):
        locked = je.get("period") in ledger.locked_periods(books)
        je = out["je"] = {**je, "approver_role": ledger.approver_role(je["kind"]).value, "period_locked": locked}
    fids = {(ln.get("dims") or {}).get("flight") for ln in je.get("lines", [])} - {None}
    srcs: set[str] = set()
    for fid in fids:
        d = rt.store.get("decision", fid)
        if d:
            srcs |= {e["source_id"] for e in d.get("evidence", [])}
    out["sources"] = sorted(srcs)
    out["blame_target"] = f"{je_id}:{max(1, len(je.get('lines', [])))}"
    try:
        out["je_commits"] = [c.model_dump(mode="json") for c in rt.trace.log(None, kind="journal_event")
                             if c.payload_ref == je_id]
    except Exception:
        out["je_commits"] = []
    return out
