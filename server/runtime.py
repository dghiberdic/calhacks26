"""The server's runtime: boot pipeline (world → engine → books), clock, trace, documents, reset.

Boot (fresh every process start; see server/DECISIONS.md):
1. Load the golden world if `STORMCHECK_WORLD` (default contracts/fixtures/golden/world.json) exists; otherwise
   serve the stub fixtures through the same document store ("stub" pipeline).
2. Rules: the engine miner when it exists, else the stub's rule cards (incl. active R-MINED-REDUCE).
3. Every storm day whose `meta.storms[].known_at` (else the morning after) is ≤ the boot clock is run by the
   engine's `run_storm` (real `engine.Engine`, else FakeEngine, else composed from the engine modules that exist).
4. Sources, METAR, facts, rules, decisions, entitlements, journals and questions are committed to
   `engine.trace.TraceStore` (the hash chain blame and replay walk); Books drafts the journals.
5. The whole DB (server + trace + books tables, one SQLite file) is snapshotted to baseline.db; `/api/reset`
   copies it back.
"""
from __future__ import annotations

import concurrent.futures as cf
import logging
import os
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from contracts.models import (
    AccessDecision, ClockMark, Draft, Entitlement, Fact, FlightDecision, FlightFile, JournalEntry, Question, Role, Rule,
    Session, StormRun, StormSummary, TraceAnchor, TraceEvent, World,
)

from . import compose, scenario
from .config import ROOT, Settings
from .impls import Impls, _module, call, find, instantiate, select
from .store import Store, TraceWriteError, iso

log = logging.getLogger("stormcheck.server")
DEMO_START = datetime(2025, 1, 25, 6, 0, tzinfo=UTC)     # "the morning after" Éowyn
MORNING_AFTER = timedelta(days=1, hours=6)
RESET_OFFSET = timedelta(hours=3)                         # POST /reset lands at boot + 3 h (09:00Z)
RULING_TIERS = ("legal_ruling", "controller_ruling", "claims_lead_ruling")


def _git_sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                             timeout=5)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


class ServerClock:
    """Forward-only clock (CONTRACTS §2 Clock) persisted in sc_clock; Books, the trace and the broker get it."""

    def __init__(self, store: Store, start: datetime):
        self._store = store
        self._start = start
        self._lock = threading.Lock()
        self._cached: datetime | None = None

    def now(self) -> datetime:
        with self._lock:
            if self._cached is None:
                self._cached = self._store.clock() or self._start
            return self._cached

    def set(self, t: datetime, actor: str) -> datetime:
        with self._lock:
            cur = self._cached or self._store.clock() or self._start
            if t < cur:
                raise ValueError(f"The clock only moves forward (now {iso(cur)}).")
            self._store.set_clock(t, actor)
            self._cached = t
            return t

    def invalidate(self) -> None:
        with self._lock:
            self._cached = None


@dataclass
class RunResult:
    run: StormRun
    decisions: list[FlightDecision]
    ents: dict[str, list[Entitlement]]
    journal: list[JournalEntry] = field(default_factory=list)


class Runtime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.lock = threading.RLock()
        self._fresh_db()
        self.store = Store(settings.db_path)
        self.world: World | None = self._load_world()
        self.base_world = self.world                 # what reset returns to (a scenario merges into `world`)
        self.clock = ServerClock(self.store, self._boot_known_at())
        # STORMCHECK_MODE=live|cache|offline sets the LLM client's mode unless LLM_MODE is given explicitly
        os.environ.setdefault("LLM_MODE", settings.mode)
        self.impls: Impls = select(settings.impl, clock=self.clock)
        self.engine_sha = _git_sha()
        self.bind_engine()
        self.books = self._make_books()
        self.pipeline = "golden" if self.world is not None else "stub"
        self.boot_error: str | None = None
        self.trace_failures: list[str] = []          # trace writes that failed since boot / reset (GET /health)
        self.trace = self._open_trace()
        acl = _module("engine.acl")
        self.broker = acl.Broker(clock=self.clock, trace=self.trace) if acl is not None else None
        if self.broker is not None and self.world is not None:
            self.broker.register_sources(self.world.sources)
        from .auth import Signer
        from .blame import Blamer
        from .lifecycle import Lifecycle
        from .live import Live
        self.signer = Signer(settings.secret)
        self.lifecycle = Lifecycle(self)
        self.blamer = Blamer(self)
        self.live = Live(self)

    # ------------------------------------------------------------------ setup
    def _fresh_db(self) -> None:
        p = Path(self.settings.db_path)
        for suffix in ("", "-wal", "-shm"):
            q = Path(str(p) + suffix)
            if q.exists():
                q.unlink()

    def _load_world(self) -> World | None:
        path = Path(self.settings.world_path)
        if not path.exists():
            return None
        loader = None
        if self.settings.impl.get("world") == "fake":
            fw = _module("contracts.fakes")
            fake = getattr(fw, "FakeWorld", None) if fw else None
            loader = getattr(fake(), "load", None) if fake else None
        try:
            if loader is not None:
                return loader(str(path))
            return World.model_validate_json(path.read_bytes())
        except Exception as exc:
            log.error("world %s did not load (%s); serving stub fixtures", path, exc)
            return None

    def _boot_known_at(self) -> datetime:
        meta = self.world.meta if self.world else {}
        for k in ("known_at", "demo_start", "as_of"):
            v = meta.get(k)
            if isinstance(v, str):
                try:
                    return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(UTC)
                except ValueError:
                    pass
        return DEMO_START

    def _make_books(self) -> Any:
        cls = self.impls.books_cls
        if cls is None:
            return None
        return instantiate(cls, db_path=str(self.settings.db_path), clock=self.clock)

    def adopt_world(self, world: World | None) -> None:
        """Make `world` the one every later decision, replay and claims batch reads (a scenario merged in, or the
        base world again on reset). Caches derived from the old world are dropped; the mined rules carry over when
        the history is unchanged."""
        if world is self.world:
            return
        mined = getattr(self, "_mined_cache", None)
        self.world = world
        eng = self.impls.engine
        if eng is not None and world is not None and hasattr(eng, "world"):
            eng.world = world
        self._norm_index = None
        if mined is not None and world is not None and mined[0].history_cases == world.history_cases:
            self._mined_cache = (world, mined[1])

    def bind_engine(self) -> None:
        eng = self.impls.engine
        if eng is not None and self.world is not None and getattr(eng, "world", False) is None:
            eng.world = self.world
        if eng is not None and hasattr(eng, "engine_version"):
            eng.engine_version = f"engine@{self.engine_sha}"

    @property
    def cal_version(self) -> str:
        v = getattr(self.impls.engine, "calibration_version", None)
        return str(v) if v else compose.CAL_VERSION

    def _open_trace(self) -> Any:
        tr = _module("engine.trace")
        if tr is None:
            from .store import LocalTrace
            return LocalTrace(self.store)
        return tr.TraceStore(str(self.settings.db_path), engine_sha=self.engine_sha, cal_version=self.cal_version)

    @property
    def now(self) -> datetime:
        return self.clock.now()

    def emit(self, kind: str, actor: str, summary: str, chip: str, ref: str | None = None,
             amount: int | None = None, at: datetime | None = None) -> TraceEvent:
        return self.store.emit(at=at or self.now, kind=kind, actor=actor, summary=summary, chip=chip, ref=ref,
                               amount_cents=amount)

    def record(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """A trace commit. A failed write is logged, counted (`/health` turns `ok: false`) and raised as
        `TraceWriteError`, so the request answers 503 instead of reporting a change the record does not hold."""
        try:
            return getattr(self.trace, method)(*args, **kwargs)
        except Exception as exc:
            log.error("trace.%s failed: %s: %s", method, type(exc).__name__, exc)
            self.trace_failures.append(f"{iso(self.now)} trace.{method}: {type(exc).__name__}")
            raise TraceWriteError(f"The trace could not record this change (trace.{method}: {type(exc).__name__}),"
                                  " so it was not saved as done. Reset the demo, or retry.") from exc

    def anchor(self) -> TraceAnchor | None:
        """The chain's published head ("head <sha> · N commits"; `scripts/verify.py --expect-head` checks it)."""
        fn = getattr(self.trace, "anchor", None)
        if fn is None:
            return None
        a = fn()
        return TraceAnchor(head=a.head, count=a.count, text=a.text())

    # ------------------------------------------------------------------ access
    def deny(self, principal: str, action: str, resource: str, reason: str, *, committed: bool = False) -> None:
        """A denial is an access-log row, an `access_denied` commit and a DENIED trace event."""
        d = AccessDecision(at=self.now, principal=principal, action=action, resource=resource, allowed=False,
                           reason=reason)
        self.store.access(d)
        if not committed:
            self.record("record_access_denied", d)
        tag = reason.split(":", 1)[0].strip() if ":" in reason else reason
        self.emit("access_denied", principal, f"{principal} {action} → DENIED · {tag}", "DENIED", resource)

    def allow(self, principal: str, action: str, resource: str, reason: str) -> None:
        self.store.access(AccessDecision(at=self.now, principal=principal, action=action, resource=resource,
                                         allowed=True, reason=reason))

    def seed_denial(self) -> None:
        """Plan §3 Access tab: the Drafter tries to approve NS31's payout → DENIED · SoD (the real ACL check)."""
        if self.books is None:
            return
        try:
            jes = list(self.books.journal())
        except Exception:
            return
        recoded = {k for k in self.store.keys("decision") if (self.store.get("decision", k) or {}).get("recoded")}
        je = next((j for j in jes if any(line.dims.get("flight") in recoded for line in j.lines)),
                  jes[0] if jes else None)
        if je is None:
            return
        drafter = Session(principal=Role.DRAFTER.value, role=Role.DRAFTER, name="Drafter", issued_at=self.now)
        if self.broker is not None:
            d = self.broker.check(drafter, "approve_payout", je.id, preparer=je.preparer)
            if not d.allowed:
                self.deny(d.principal, d.action, d.resource, d.reason, committed=True)
            return
        self.deny(drafter.principal, "approve_payout", je.id, "SoD: agents never approve payouts")

    # ------------------------------------------------------------------ boot
    def boot(self) -> None:
        with self.lock:
            self.store.set_clock(self.clock.now(), "boot")
            self.store.put("boot", "info", {"pipeline": self.pipeline, "known_at": iso(self.now),
                                            "impl": self.impls.describe(), "engine_sha": self.engine_sha}, self.now)
            if self.world is None:
                self._boot_stub()
            else:
                try:
                    self._boot_world(self.world)
                except Exception as exc:   # a half-landed piece must not leave the demo dark
                    log.exception("real pipeline failed; serving stub fixtures")
                    self.boot_error = f"{type(exc).__name__}: {exc}"
                    self.pipeline = "stub"
                    self._boot_stub()
            self.store.snapshot(self.settings.baseline)

    def reset(self) -> None:
        with self.lock:
            close = getattr(self.trace, "close", None)
            if close is not None:
                close()
            self.store.restore(self.settings.baseline)
            self.adopt_world(self.base_world)            # the baseline holds no scenario
            self.clock.invalidate()
            self.trace = self._open_trace()
            self.trace_failures.clear()
            if self.broker is not None:
                self.broker.trace = self.trace
                self.broker.log.clear()
            if self.world is not None:
                # Justin Q-b: the demo starts 3 h after the morning run, so Q1 already reads "Waiting on Claims
                # Lead 3h · reminder sent" with no scrub (claims wait for the 18:00Z batch; day-1 numbers hold)
                self.advance(self._boot_known_at() + RESET_OFFSET, "reset")

    def _boot_stub(self) -> None:
        from contracts import stub_app as stub
        now = self.now
        self.commit_rules(list(stub.RULES))
        for run in stub.STORM_RUNS.values():
            self.store.put("storm_run", run.id, run.model_copy(update={"feed": []}), now)
        for fid, ff in stub.FLIGHT_FILES.items():
            self.store.put("flight_file", fid, ff, now)
            self.store.put("decision", fid, ff.decision, now)
        for q in stub.QUESTIONS:
            self.store.put("question", q.id, q, now)
        for ev in stub.TRACE:
            self.store.emit(at=ev.at, kind=ev.kind, actor=ev.actor, summary=ev.summary, chip=ev.chip, ref=ev.ref,
                            amount_cents=ev.amount_cents)

    # rules ------------------------------------------------------------
    def commit_rules(self, rules: list[Rule]) -> None:
        for r in rules:
            self.store.put("rule", r.id, r, self.now)
            self.record("record_rule", r, "agent.engine", self.now, event=r.status,
                        reason=r.support or r.tier.replace("_", " "))

    def mined(self, world: World) -> Any:
        """`engine.miner.mine(world)` once per world (None when the miner is missing or there is no history)."""
        cache = getattr(self, "_mined_cache", None)
        if cache is not None and cache[0] is world:
            return cache[1]
        miner = _module("engine.miner")
        out = None
        if miner is not None and hasattr(miner, "mine") and world.history_cases:
            try:
                out = miner.mine(world)
            except Exception as exc:
                log.warning("miner failed: %s", exc)
        self._mined_cache = (world, out)
        return out

    def boot_rules(self, world: World) -> list[Rule]:
        """Rule cards from the stub (display) + the mined policy from `engine.miner` (D7). A mined rule in `shadow`
        is activated at onboarding (it drives day 1's 50% reroute cut); one a written policy contradicts stays
        `proposed` (no_conflict=False) and its Controller question is asked instead. With no history to mine, the
        stub's R-MINED-REDUCE card stands in."""
        from contracts import stub_app as stub
        rules: dict[str, Rule] = {r.id: r for r in stub.RULES}
        m = self.mined(world)
        if m is not None:
            rules = {k: r for k, r in rules.items() if r.tier != "mined"}
            for p in m.proposals:
                rules[p.rule.id] = p.rule             # shadow (or proposed when a written policy disagrees)
        return list(rules.values())

    ONBOARDING = Session(principal="claims_lead:onboarding", role=Role.CLAIMS_LEAD, name="Claims Lead (onboarding)",
                         issued_at=DEMO_START)

    def activate_rule(self, rule: Rule, session: Session, reason: str) -> Rule:
        """A rule becomes active only on the say-so of a principal who holds the authority it automates (hard
        control); anyone else is DENIED (access log, `access_denied` commit, DENIED event)."""
        need = rule.authority_required
        ref = f"{rule.id}@{rule.version}"
        if session.role != need or session.role in (Role.JUDGE,) or session.principal.startswith(("agent.",
                                                                                                  "persona:")):
            self.deny(session.principal, "activate_rule", ref, f"Least privilege: {ref} automates the "
                      f"{compose.label(need)}'s authority; {session.principal} cannot activate it")
            raise PermissionError(f"{session.principal} may not activate {ref}")
        active = rule.model_copy(update={"status": "active"})
        self.store.put("rule", rule.id, active, self.now)
        self.record("record_rule", active, session.principal, self.now, event="active", reason=reason)
        self.allow(session.principal, "activate_rule", ref, reason)
        return active

    def onboard_mined(self, rules: list[Rule]) -> None:
        """Mined at onboarding: the seeded Claims Lead seat approves each clean shadow rule (support + exceptions on
        the record), so blame shows who switched on the 50% reroute cut."""
        for r in rules:
            if r.tier != "mined" or r.status != "shadow":
                continue
            exc = ""
            if r.origin_example and "exception" in r.origin_example:
                exc = " · " + r.origin_example.split(";", 1)[-1].strip(" )")
            seat = self.ONBOARDING.model_copy(update={"issued_at": self.now})
            self.activate_rule(r, seat, f"onboarding approval by the Claims Lead · support {r.support}{exc}")

    def mined_questions(self, world: World) -> list[Question]:
        miner = _module("engine.miner")
        m = self.mined(world)
        if miner is None or m is None or not hasattr(miner, "contradictions"):
            return []
        try:
            return list(miner.contradictions(world, asked_at=self.now, mined=m))
        except Exception as exc:
            log.warning("miner contradictions failed: %s", exc)
            return []

    def learned(self, world: World, rules: list[Rule], run_id: str) -> list[Any]:
        """The Learns strip: `engine.miner.learned_items` (curves from Books when it has them)."""
        miner = _module("engine.miner")
        m = self.mined(world)
        if miner is not None and m is not None and hasattr(miner, "learned_items"):
            lookup = getattr(self.books, "curve", None)
            try:
                return list(miner.learned_items(world, curve_lookup=lookup, mined=m))
            except Exception as exc:
                log.warning("learned_items failed: %s", exc)
        from contracts import stub_app as stub
        stub_run = stub.STORM_RUNS.get(run_id)
        return list(stub_run.learned) if stub_run is not None else compose.default_learned(rules)

    def rules(self) -> list[Rule]:
        return [Rule.model_validate(x) for x in self.store.all("rule")]

    @staticmethod
    def engine_rules(rules: list[Rule]) -> list[Rule]:
        """What the engine evaluates: every rule doc except static cards (display only; the hard-control cards are
        static and the engine implements those controls in code). Same set `scripts/verify.py` replays with."""
        return [r for r in rules if not r.static_card]

    # facts ------------------------------------------------------------
    def commit_world(self, world: World) -> None:
        """Sources and METAR obs go on the chain at boot. The structured feeds are the engine's base world, so their
        normalize facts are not re-committed (73k facts; replay would only overlay them back onto themselves). The
        facts a decision cites are committed with it (`commit_evidence`), injected facts when they arrive."""
        now = self.now
        for s in world.sources:
            self.record("record_source", s, "agent.reader", now)
        for key, obs in world.metar.items():
            self.record("record_metar", obs, "agent.reader", now, source_id=f"SRC-METAR-{key}")

    # storm run --------------------------------------------------------
    @staticmethod
    def hub(world: World) -> str:
        hub = str(world.meta.get("hub_icao") or world.meta.get("hub") or "EIDW")
        if len(hub) == 3:
            a = compose.airport_by(world, hub)
            hub = a.icao if a else "EIDW"
        return hub

    def storm_days(self, world: World) -> list[tuple[str, date]]:
        return compose.storm_days(world, self.hub(world))

    @staticmethod
    def storm_run_at(world: World, station: str, day: date) -> datetime:
        """When a storm day is run: `meta.storms[id].known_at`, else the morning after (day + 1 d 06:00Z)."""
        info = compose.storm_meta(world, f"{station}@{day.isoformat()}")
        k = info.get("known_at")
        if isinstance(k, str):
            try:
                return datetime.fromisoformat(k.replace("Z", "+00:00")).astimezone(UTC)
            except ValueError:
                pass
        return datetime(day.year, day.month, day.day, tzinfo=UTC) + MORNING_AFTER

    def _boot_world(self, world: World) -> None:
        now = self.now
        rules = self.boot_rules(world)
        self.commit_rules(rules)
        self.onboard_mined(rules)
        self.commit_world(world)
        ran = 0
        for station, day in self.storm_days(world):
            run_at = self.storm_run_at(world, station, day)
            if run_at > now:
                self.store.put("pending_storm", f"{station}@{day.isoformat()}",
                               {"station": station, "date": day.isoformat(), "run_at": iso(run_at)}, now)
                continue
            self.run_and_store(world, station, day, now, source="boot")
            ran += 1
        if world.opening_balances and self.books is not None:
            try:
                self.books.post_opening_balances(world.opening_balances, now)
            except Exception as exc:
                log.warning("opening balances not posted: %s", exc)
        if not ran:
            log.warning("golden world has no storm day before %s", iso(now))
        for q in self.mined_questions(world):       # written policy vs established practice → the Controller
            self.live.ask(q, [])
        self.seed_denial()
        self.persona_round()

    # ------------------------------------------------------------------ personas (unattended runs only)
    def persona_round(self) -> int:
        """STORMCHECK_PERSONAS=1: simulated people (`persona:<role>`) answer the open questions routed to them and
        confirm the rule their ruling drafts. Their principal is passed through unchanged; they never approve or
        pay (the ACL refuses persona principals on every approval)."""
        personas = _module("llm.personas")
        if personas is None or not personas.enabled() or self.world is None:
            return 0
        n = 0
        bench = personas.PersonaBench()
        for q in self.questions():
            if q.status not in ("open", "reminded"):
                continue
            try:
                pr = bench.answer(q)
            except Exception as exc:
                log.info("persona skipped %s: %s", q.id, exc)
                continue
            if getattr(pr, "record", None) is not None:
                self.commit_llm(pr.record)
            req = pr.request if hasattr(pr, "request") else pr[0]
            try:
                _, proposal = self.lifecycle.answer(q, pr.role, pr.principal, pr.principal, req.decision,
                                                    req.explanation)
                if proposal is not None and proposal.rule.authority_required == pr.role:
                    self.lifecycle.confirm(proposal.rule.id, pr.principal)
                n += 1
            except Exception as exc:
                log.warning("persona ruling on %s failed: %s", q.id, exc)
        return n

    @staticmethod
    def last_record(agent: Any, draft_id: str | None = None) -> Any:
        """The LlmCallRecord behind an agent's output: `record_for(draft_id)` (Drafter), `.last.record` (Reader),
        `.last_record`, or the newest of `.records`."""
        if draft_id is not None and hasattr(agent, "record_for"):
            rec = agent.record_for(draft_id)
            if rec is not None:
                return rec
        last = getattr(agent, "last", None)
        rec = getattr(last, "record", None) if last is not None else None
        if rec is None:
            rec = getattr(agent, "last_record", None)
        return rec

    def commit_draft(self, draft: Draft, agent: Any) -> Draft:
        """A Drafter output: its llm_call commit (when it called the LLM), then the Draft itself citing it."""
        h = self.commit_llm(self.last_record(agent, draft.id))
        if h is not None and draft.llm_commit is None:
            draft = draft.model_copy(update={"llm_commit": h})
        self.record("commit", "fact", draft, "agent.drafter", [h] if h else [], self.now, ref=draft.id,
                    message=f"draft {draft.kind} {draft.id}" + (" · template" if draft.template_fallback else ""))
        return draft

    def commit_llm(self, record: Any, *, outputs: list[str] | None = None) -> str | None:
        """Plan §2 rule 2: every LLM call is an `llm_call` commit (prompt hash, response.model, request id,
        principal, input facts). Its outputs are committed separately, citing this hash."""
        if record is None:
            return None
        payload = record.model_dump(mode="json") if hasattr(record, "model_dump") else dict(record)
        c = self.record("record_llm_call", payload, str(payload.get("principal") or "agent.reader"), self.now,
                        ref=str(payload.get("id") or "llm"),
                        message=f"{payload.get('role', 'llm')} · {payload.get('model') or payload.get('model_requested')}"
                                f" · {payload.get('mode', '')}{' · cache hit' if payload.get('cache_hit') else ''}")
        return c.hash if c is not None else None

    def engine_run(self, world: World, station: str, day: date, rules: list[Rule], known_at: datetime) -> StormRun | None:
        eng = self.impls.engine
        if eng is None or not hasattr(eng, "run_storm"):
            return None
        try:
            return call(eng.run_storm, world, station, day, self.engine_rules(rules), known_at)
        except Exception as exc:
            log.warning("engine run_storm(%s@%s) failed (%s); composing", station, day, exc)
            return None

    def decide_all(self, world: World, flights: list, known_at: datetime, curated: bool) -> list[FlightDecision]:
        from contracts import stub_app as stub
        out = []
        for f in flights:
            if f.status != "cancelled":
                continue
            ff = stub.FLIGHT_FILES.get(f.id) if curated else None
            entry = compose.expected_entries().get(f.id) if curated else None
            if ff is not None:
                out.append(compose.rebase_decision(ff.decision, known_at))
            elif entry is not None:
                out.append(compose.expected_decision(f, world, entry, known_at))
            else:
                out.append(compose.provisional_decision(f, world, known_at))
        return out

    def entitlements(self, d: FlightDecision, world: World, rules: list[Rule], known_at: datetime) -> list[Entitlement]:
        return compose.entitlements_for(d, world, self.engine_rules(rules), known_at, self.impls.engine)

    def explain(self, d: FlightDecision, *, now: bool = False) -> Draft:
        """The "Why?" text. At boot a template (never wait on an LLM at boot); the Drafter's version is drafted on
        the flight file's first view (`now=True`, 8 s timeout, template on any failure) and stored."""
        drafter = self.impls.drafter
        fn = getattr(drafter, "explain", None) if drafter is not None else None
        if fn is None or not now:
            return compose.template_explanation(d)
        from .live import timed
        try:
            out = timed(fn, self.settings.reader_timeout_s, d)
        except Exception:
            return compose.template_explanation(d)
        return self.commit_draft(out, drafter) if isinstance(out, Draft) else compose.template_explanation(d)

    def normalize_fact(self, fact_id: str) -> Fact | None:
        """The real `contracts.normalize` fact when an evidence id is a normalize id (`F:…`); built lazily, once."""
        if not fact_id.startswith("F:") or self.world is None:
            return None
        index = getattr(self, "_norm_index", None)
        if index is None:
            norm = _module("contracts.normalize")
            try:
                index = {f.id: f for f in norm.world_to_facts(self.world)} if norm is not None else {}
            except Exception:
                index = {}
            self._norm_index = index
        return index.get(fact_id)

    def commit_evidence(self, d: FlightDecision, at: datetime) -> None:
        """Record each cited evidence item as a Fact (span = its verbatim quote) so the decision links to it, and
        through it to its source and, for a raw METAR line, to the observation. The engine's evidence ids are not
        `normalize` ids, so without this blame would stop at the decision."""
        new = []
        for e in d.evidence:
            # a fact already on the chain (cited before, or injected) is linked by the decision commit, never
            # re-recorded: the trace reads the latest version of a fact id
            if any(self.store.get(kind, e.fact_id) is not None for kind in ("ev_fact", "injected_fact")):
                continue
            self.store.put("ev_fact", e.fact_id, {"flight": d.flight_id}, at)
            real = self.normalize_fact(e.fact_id)
            new.append(real or Fact(id=e.fact_id, source_id=e.source_id, subject=f"flight:{d.flight_id}",
                                    field=e.field, value=e.value, span=e.quote, extractor="engine:evidence@1",
                                    recorded_at=at))
        if new:
            self.record("record_facts", new, "agent.engine", at)

    def commit_decision(self, d: FlightDecision, actor: str, at: datetime, inputs: list[str] | None = None
                        ) -> FlightDecision:
        self.commit_evidence(d, at)
        c = self.record("record_decision", d, actor, at, inputs=list(inputs or []))
        return d.model_copy(update={"commit": c.hash}) if c is not None else d

    def commit_journal(self, jes: list[JournalEntry], actor: str, at: datetime, *, event: str = "drafted",
                       inputs: list[str] | None = None) -> list[JournalEntry]:
        """Record JE events once per (JE, event); returns the ones that were new."""
        new = []
        for je in jes:
            key = f"{je.id}|{event}"
            if self.store.get("je_event", key) is not None:
                continue
            self.store.put("je_event", key, {"at": iso(at)}, at)
            self.record("record_journal", je, actor, at, event=event, inputs=list(inputs or []))
            new.append(je)
        return new

    def scratch_books(self) -> Any:
        """An in-memory Books for desk days: the judge's scenario is priced, the demo ledger is never written."""
        cls = self.impls.books_cls
        return instantiate(cls, db_path=":memory:", clock=self.clock) if cls is not None else None

    def run_and_store(self, world: World, station: str, day: date, known_at: datetime, *, source: str,
                      rules: list[Rule] | None = None, curated: bool = True, desk: bool = False) -> RunResult:
        """Run one storm day end to end and store run, flight files, decisions, entitlements, questions, trace.

        `desk=True`: priced in a scratch Books, decisions kept apart from the demo's (docs `desk_*`), journals not
        put on the chain (their ids belong to the scratch ledger), questions kept in the run only."""
        from contracts import stub_app as stub
        rules = rules if rules is not None else self.rules()
        books = self.scratch_books() if desk else self.books
        run_id = f"{station}@{day.isoformat()}"
        iata = compose.iata_of(world, station)
        obs = compose.station_obs(world, station, day)
        windows = compose.storm_windows(obs)
        engine_run = self.engine_run(world, station, day, rules, known_at)
        if engine_run is not None:
            flights = [r.flight for r in engine_run.flights]
            decisions = [r.decision for r in engine_run.flights if r.decision is not None]
            windows = engine_run.windows or windows
            obs = engine_run.metar or obs
        else:
            flights = compose.run_flights(world, iata, day, station)
            decisions = self.decide_all(world, flights, known_at, curated)
        ents: dict[str, list[Entitlement]] = {d.flight_id: self.entitlements(d, world, rules, known_at)
                                              for d in decisions}

        # trace: decision → entitlements (what blame and replay walk)
        committed = []
        for d in decisions:
            d = self.commit_decision(d, "agent.engine", known_at)
            committed.append(d)
            if ents[d.flight_id]:
                self.record("record_entitlements", ents[d.flight_id], "agent.engine", known_at)
        decisions = committed

        journal: list[JournalEntry] = []
        if books is not None:
            all_ents = [e for d in decisions for e in ents[d.flight_id]]
            try:
                journal = list(books.post_storm(run_id, world, decisions, all_ents, known_at))
            except Exception as exc:
                log.warning("books.post_storm(%s) failed: %s", run_id, exc)
        if not desk:
            self.commit_journal(journal, "agent.books", known_at)
        liability = sum(line.cr_cents - line.dr_cents for je in journal for line in je.lines
                        if line.account == "2140" and je.kind == "compensation_estimate")

        if engine_run is not None:
            questions = list(engine_run.questions)
        else:
            extra = [ob.cohort for ob in world.opening_balances] if source == "boot" else []
            questions = compose.group_questions(run_id, decisions, ents, known_at,
                                                curated=stub.QUESTIONS if curated else (), extra_case_refs=extra)
        # a cohort question the boot run already asked is not asked again by a later storm
        questions = [q for q in questions if not (q.pattern == "cohort_release"
                                                  and self.store.get("question", q.id) is not None)]
        if engine_run is not None and engine_run.learned:
            learned = list(engine_run.learned)
        else:
            learned = self.learned(self.world if (self.world is not None and not desk) else world, rules, run_id)

        if engine_run is not None:
            dec_by = {d.flight_id: d for d in decisions}
            run = engine_run.model_copy(update={
                "flights": [r.model_copy(update={"decision": dec_by.get(r.flight.id, r.decision)})
                            for r in engine_run.flights],
                "liability_drafted_cents": liability if books is not None else engine_run.liability_drafted_cents,
                "questions": questions, "learned": learned, "feed": []})
        else:
            run = compose.compose_run(world=world, station=station, day=day, flights=flights, decisions=decisions,
                                      ents=ents, questions=questions, learned=learned,
                                      liability_drafted_cents=liability, obs=obs, windows=windows)
        if desk:
            run = run.model_copy(update={"real_context": {**run.real_context, "desk": True}})
        self._store_run(world, run, decisions, ents, journal, obs, windows, questions, known_at, desk=desk,
                        books=books)
        self._emit_run(run, decisions, ents, journal, questions, self.now if desk else known_at, source)
        return RunResult(run=run, decisions=decisions, ents=ents, journal=journal)

    def _store_run(self, world: World, run: StormRun, decisions: list[FlightDecision],
                   ents: dict[str, list[Entitlement]], journal: list[JournalEntry], obs: list, windows: list,
                   questions: list[Question], known_at: datetime, *, desk: bool = False, books: Any = None) -> None:
        flights = {r.flight.id: r.flight for r in run.flights}
        books_journal = journal
        books = books if books is not None else self.books
        if books is not None:
            try:
                books_journal = list(books.journal())
            except Exception:
                pass
        at = self.now if desk else known_at
        prefix = "desk_" if desk else ""
        for d in decisions:
            f = flights.get(d.flight_id)
            if f is None:
                continue
            fe = ents.get(d.flight_id, [])
            ff = compose.flight_file(world, f, d, fe, books_journal, obs, windows, self.explain(d))
            self.store.put(prefix + "decision", d.flight_id, d, at)
            self.store.put(prefix + "entitlements", d.flight_id, fe, at)
            self.store.put("flight_file", d.flight_id, ff, at)
            self.store.put("flight_run", d.flight_id, {"run": run.id}, at)
        if not desk:
            for q in questions:
                self.store.put("question", q.id, q, known_at)
                self.record("record_question", q, "agent.engine", known_at, event="asked")
        self.store.put("storm_run", run.id, run, at)

    def _emit_run(self, run: StormRun, decisions: list[FlightDecision], ents: dict[str, list[Entitlement]],
                  journal: list[JournalEntry], questions: list[Question], known_at: datetime, source: str) -> None:
        mw = compose.main_window(run.windows)
        what = (f"storm window {compose.hhmm(mw.start)[:-1]}–{compose.hhmm(mw.end)} · peak gust {mw.peak_gust_kt} kt"
                if mw else (run.message or "no storm window"))
        self.emit("info", "agent.engine", f"Read {len(run.metar)} METAR obs at {run.station} · {what}", "INFO",
                  run.id, at=known_at)
        occ = [r.flight for r in run.flights if r.flight.status == "cancelled"]
        if occ:
            coded = sum(1 for f in occ if f.ops_cause_code in ("71", "72"))
            self.emit("fact", "agent.reader", f"Read the OCC cancel list · {len(occ)} cancellations · {coded} coded "
                      "weather (RSN 71/72)", "INFO", run.id, at=known_at)
        weather = [d for d in decisions if d.cause.value == "weather" and d.outcome == "auto"]
        if weather:
            self.emit("decision", "agent.engine", f"{len(weather)} flights confirmed weather · no compensation; "
                      "refunds and care still due", "APPLIED", run.id, at=known_at)
        for d in decisions:
            fe = ents.get(d.flight_id, [])
            num = d.flight_id.split("@")[0]
            if d.recoded:
                drafted = sum(1 for e in fe if e.status in ("owed", "needs_ruling") and e.compensation_cents > 0)
                self.emit("decision", "agent.engine", f"{num} recoded {d.recode_label or ''} · {drafted} payouts "
                          "drafted", "APPLIED", d.flight_id, at=known_at)
            reduced = sum(1 for e in fe if e.reduction != "none")
            if reduced:
                rule = next((r for e in fe for r in e.rules_applied if "REDUCE" in r), None)
                self.emit("rule", "agent.engine", f"Cited {rule or 'the Art. 7(2) policy'} · {reduced} reroutes on "
                          f"{num} reduced 50%", "CITED", rule or d.flight_id, at=known_at)
            owed = sum(e.compensation_cents for e in fe if e.status in ("owed", "needs_ruling"))
            if owed and d.outcome == "auto":
                self.emit("entitlement", "agent.engine", f"{num} entitlements drafted · {compose.eur(owed)} full Art. 7 "
                          "entitlement · pending Claims Lead approval", "DRAFTED", d.flight_id, owed, at=known_at)
            refunds = sum(1 for e in fe if e.refund_already_initiated)
            if refunds and owed:
                self.emit("info", "agent.engine", f"CRM bot already initiated {refunds} {num} refunds · not repeated",
                          "INFO", d.flight_id, at=known_at)
        ruled = {f"{r.id}@{r.version}": r for r in self.rules() if r.tier in RULING_TIERS and r.status == "active"}
        for rref, rule in ruled.items():
            n_flights = sum(1 for d in decisions if rref in d.rules_applied)
            n_coupons = sum(1 for d in decisions for e in ents.get(d.flight_id, [])
                            if rref in e.rules_applied and rref not in d.rules_applied)
            if n_flights or n_coupons:
                asks = sum(len(q.case_refs) for q in questions if q.pattern == "voucher_in_lieu_unsigned"
                           and rule.kind == "voucher")
                what = f"{n_coupons} cases" if n_coupons else f"{n_flights} flights"
                self.emit("rule", "agent.engine", f"↻ {what} settled under {rref}, ruling cited"
                          + (f" · {asks} asks again (outside the rule's scope)" if asks else ""), "CITED", rref,
                          at=known_at)
        held_ids = {d.flight_id for d in decisions if d.outcome != "auto"}
        held_total = 0
        for je in journal:
            amt = sum(line.cr_cents for line in je.lines if line.account == "2140")
            fid = next((line.dims.get("flight") for line in je.lines if line.dims.get("flight")), None)
            if fid in held_ids:
                held_total += amt
                continue
            self.emit("journal", "agent.books", f"Drafted Dr 4090 / Cr 2140 {compose.eur(amt)} for "
                      f"{(fid or run.id).split('@')[0]} · drafted, pending approval", "DRAFTED", je.id, amt, at=known_at)
        if held_total:
            self.emit("journal", "agent.books", f"Held {compose.eur(held_total)} for {len(held_ids)} flights pending "
                      "a ruling (IFRS 15.56 constraint, segment rates)", "HELD", run.id, held_total, at=known_at)
        for q in questions:
            score = q.confidence.score
            conf = f"confidence {round(score * 100)}%" if score is not None else "uncalibrated"
            self.emit("question", "agent.engine", f"Asked {compose.label(q.routed_to)}: {q.title} · {conf} · "
                      f"{q.reason_tag.replace('-', ' ')}", "ASKED", q.id, q.holds_cents or None, at=known_at)

    # ------------------------------------------------------------------ time
    def advance(self, t: datetime, actor: str) -> datetime:
        """Move the forward-only clock and process what became due (storms, claims, reminders)."""
        with self.lock:
            if t.tzinfo is None:
                t = t.replace(tzinfo=UTC)
            t = t.astimezone(UTC)
            prev = self.now
            self.clock.set(t, actor)
            if t > prev:
                self.record("commit", "clock", {"from": iso(prev), "to": iso(t)}, actor, [], t, ref="clock",
                            message=f"clock {iso(prev)} → {iso(t)}")
                self.process_due()
            return t

    def process_due(self) -> None:
        with self.lock:
            self._run_pending_storms()
            self._run_due_scenarios()
            self._process_claims()
            self._remind()

    def marks(self) -> list[ClockMark]:
        """The named moments the demo moves through (`GET /api/clock`), in time order."""
        return scenario.marks(self.base_world, self.storm_run_at)

    def _run_due_scenarios(self) -> None:
        if self.base_world is None or not self.base_world.meta.get("golden_version"):
            return
        for sc in scenario.SCENARIOS:
            if sc.at <= self.now and self.store.get("scenario", sc.id) is None:
                self.run_scenario(sc)

    def run_scenario(self, sc: scenario.Scenario) -> list[str]:
        """Load the scenario's World slice, merge it into the world, commit its sources and METAR, and run its
        days like a storm run. Runs once (reset restores the baseline, where it has not run). A missing or failing
        loader is recorded and reported, never raised: the clock move itself succeeded."""
        now = self.now
        loader = find([sc.loader])
        if loader is None:
            self.store.put("scenario", sc.id, {"ran": False, "reason": f"{'.'.join(sc.loader)} is missing"}, now)
            self.emit("info", "agent.engine", f"{sc.label}: not available on this server ({sc.loader[0]} has not "
                      "landed)", "INFO", sc.id)
            return []
        try:
            part = loader()
        except Exception as exc:
            log.exception("scenario %s did not load", sc.id)
            self.store.put("scenario", sc.id, {"ran": False, "reason": type(exc).__name__}, now)
            self.emit("info", "agent.engine", f"{sc.label}: could not be loaded ({type(exc).__name__})", "INFO", sc.id)
            return []
        base = self.world
        have = {s.id for s in base.sources}
        self.adopt_world(scenario.merge_worlds(base, part))
        new_sources = [s for s in part.sources if s.id not in have]
        self.commit_world(part.model_copy(update={
            "sources": new_sources, "metar": {k: v for k, v in part.metar.items() if k not in base.metar}}))
        if self.broker is not None:
            self.broker.register_sources(new_sources)
        event = scenario.event_of(part)
        cancelled = sum(1 for f in part.flights if f.status == "cancelled")
        self.emit("info", "agent.reader", f"Read {sc.label}: {getattr(event, 'title', sc.label)} · "
                  f"{len(part.flights)} flights, {cancelled} cancelled · {len(new_sources)} sources", "INFO", sc.id)
        ran = []
        for station, day in scenario.runs(part, self.hub(base)):
            res = self.run_and_store(self.world, station, day, now, source="scenario")
            run = scenario.decorate(res.run, part, self.world)
            if run is not res.run:
                self.store.put("storm_run", run.id, run, now)
            ran.append(run.id)
        self.store.put("scenario", sc.id, {"ran": True, "runs": ran}, now)
        return ran

    def _run_pending_storms(self) -> None:
        if self.world is None:
            return
        for key in self.store.keys("pending_storm"):
            info = self.store.get("pending_storm", key)
            if info.get("done") or datetime.fromisoformat(info["run_at"].replace("Z", "+00:00")) > self.now:
                continue
            self.run_and_store(self.world, info["station"], date.fromisoformat(info["date"]), self.now,
                               source="clock")
            self.store.put("pending_storm", key, {**info, "done": True}, self.now)

    CLAIMS_BATCH_HOUR = 18          # claims are assessed in a daily 18:00Z batch, not the moment they arrive

    def claims_batch_at(self) -> datetime:
        """The latest daily claims batch at or before now."""
        now = self.now
        b = now.replace(hour=self.CLAIMS_BATCH_HOUR, minute=0, second=0, microsecond=0)
        return b if b <= now else b - timedelta(days=1)

    def _process_claims(self) -> None:
        """Claims received before the latest daily batch are assessed at face value (Books drafts; the Claims Lead
        approves). On day 1 (25 Jan 06:00Z-18:00Z) the 6 overnight claims are still unassessed (plan §1.3)."""
        if self.world is None or self.books is None:
            return
        batch = self.claims_batch_at()
        for claim in sorted(self.world.claims, key=lambda c: (c.received_at, c.id)):
            if claim.received_at > batch:
                continue
            state = self.store.get("claim_state", claim.id)
            if state is not None and state.get("state") != "held":
                continue
            fid = claim.coupon_id.rsplit(":", 1)[0]
            ent = next((Entitlement.model_validate(e) for e in (self.store.get("entitlements", fid) or [])
                        if e["coupon_id"] == claim.coupon_id), None)
            if ent is None:
                continue
            if ent.status in ("held", "needs_ruling"):
                if state is None:
                    self.store.put("claim_state", claim.id, {"state": "held", "status": ent.status}, self.now)
                continue
            try:
                jes = list(self.books.post_claim(claim, ent, claim.received_at))
            except Exception as exc:
                log.warning("post_claim %s failed: %s", claim.id, exc)
                continue
            self.store.put("claim_state", claim.id, {"state": "approved" if jes else "rejected",
                                                     "je_ids": [j.id for j in jes]}, self.now)
            self.commit_journal(jes, "agent.books", self.now)
            if jes:
                amt = sum(line.dr_cents for je in jes if je.kind == "claim_approved" for line in je.lines
                          if line.account == "2140")
                self.emit("journal", "agent.books", f"Claim {claim.id} on {fid.split('@')[0]} assessed at face value "
                          f"{compose.eur(amt)} · drafted, pending Claims Lead approval", "DRAFTED", claim.id, amt)

    def _remind(self) -> None:
        for q in self.questions():
            if q.status != "reminded" or self.store.get("reminded", q.id) is not None:
                continue
            hours = int((self.now - q.asked_at).total_seconds() // 3600)
            others = sum(1 for k in self.store.keys("decision")
                         if (self.store.get("decision", k) or {}).get("outcome") == "auto")
            self.store.put("reminded", q.id, {"at": iso(self.now)}, self.now)
            self.record("record_question", q, "agent.engine", self.now, event="reminded")
            self.emit("reminder", "agent.engine", f"Waiting on {compose.label(q.routed_to)} {hours}h · reminder sent · "
                      f"{others} others settled", "INFO", q.id)

    # ------------------------------------------------------------------ views
    def storm_run(self, run_id: str) -> StormRun | None:
        data = self.store.get("storm_run", run_id)
        if data is None:
            return None
        run = StormRun.model_validate(data)
        ids = {x.id for x in run.questions}
        refs = {r.flight.id for r in run.flights}
        live = {q.id: q for q in self.questions()}
        qs = [live.get(x.id, x) for x in run.questions]          # desk questions live in their run only
        qs += [q for q in live.values() if q.id not in ids and set(q.case_refs) & refs]
        return run.model_copy(update={"questions": qs, "feed": self.store.trace()})

    def storm_summaries(self) -> list[StormSummary]:
        out = []
        qs = self.questions()
        for key in self.store.keys("storm_run"):
            run = StormRun.model_validate(self.store.get("storm_run", key))
            live = {q.id: q for q in qs}
            open_q = sum(1 for x in run.questions if live.get(x.id, x).status != "answered")
            out.append(StormSummary(id=run.id, station=run.station, date=run.date,
                                    cancelled=run.counters.get("cancelled", 0), questions=open_q,
                                    liability_drafted_cents=run.liability_drafted_cents))
        return out

    def flight_file(self, flight_id: str) -> FlightFile | None:
        data = self.store.get("flight_file", flight_id)
        if data is None:
            return None
        ff = FlightFile.model_validate(data)
        if ff.explanation is not None and ff.explanation.id.startswith("DRAFT-EXPL-") and \
                self.impls.drafter is not None:
            with self.lock:                          # first view: the Drafter writes the "Why?" (stored once)
                draft = self.explain(ff.decision, now=True)
                if not draft.id.startswith("DRAFT-EXPL-"):
                    ff = ff.model_copy(update={"explanation": draft})
                    self.store.put("flight_file", flight_id, ff, self.now)
                else:
                    ff = ff.model_copy(update={"explanation": draft.model_copy(update={"id": f"DRAFT-T-{flight_id}"})})
                    self.store.put("flight_file", flight_id, ff, self.now)
        return ff

    def known_flight(self, flight_id: str) -> bool:
        for key in self.store.keys("storm_run"):
            run = self.store.get("storm_run", key)
            if any(r["flight"]["id"] == flight_id for r in run["flights"]):
                return True
        return False

    def question_status(self, q: Question) -> str:
        if self.store.get("ruling_for", q.id) is not None:
            return "answered"
        if q.remind_at is not None and self.now >= q.remind_at:
            return "reminded"
        return "open"

    def questions(self) -> list[Question]:
        out = []
        for data in self.store.all("question"):
            q = Question.model_validate(data)
            out.append(q.model_copy(update={"status": self.question_status(q)}))
        return out

    def health_impl(self) -> dict[str, str]:
        d = self.impls.describe()
        d["pipeline"] = self.pipeline
        d["trace"] = type(self.trace).__module__.split(".")[0] + "." + type(self.trace).__name__
        d["sessions"] = self.signer.kind
        if self.pipeline == "stub":
            d["engine"] = "stub"
        if self.world is None:
            d["world"] = "stub"
        if self.books is None:
            d["books"] = "stub"
        if self.boot_error:
            d["boot_error"] = self.boot_error[:200]
        return d
