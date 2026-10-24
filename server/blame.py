"""`GET /api/blame?target=` and `GET /api/audit/{je_id}` over `engine.trace.TraceStore`.

Blame walks € → entitlement → decision → rule@v → ruling (author + quote) → question → facts (span) → source →
METAR obs (the trace's stored links). Quotes are redacted per viewer with `acl.Broker.redact` (the trace itself does
not redact). An unknown target is an empty chain, never an error.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from contracts.models import Blame, Session

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
        b = b.model_copy(update={"target": target})
        broker = self.rt.broker
        if broker is not None and viewer is not None and not broker.sees_pii(viewer):
            b = broker.redact(viewer, b)
        return b


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
