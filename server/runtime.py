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
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from contracts.models import (
    AccessDecision, Draft, Entitlement, Fact, FlightDecision, FlightFile, JournalEntry, Question, Role, Rule, Session,
    StormRun, StormSummary, TraceEvent, World,
)

from . import compose
from .config import ROOT, Settings
from .impls import Impls, _module, call, instantiate, select
from .store import Store, iso

log = logging.getLogger("stormcheck.server")
DEMO_START = datetime(2025, 1, 25, 6, 0, tzinfo=UTC)     # "the morning after" Éowyn
MORNING_AFTER = timedelta(days=1, hours=6)
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
        self.clock = ServerClock(self.store, self._boot_known_at())
        self.impls: Impls = select(settings.impl, clock=self.clock)
        self.engine_sha = _git_sha()
        self.bind_engine()
        self.books = self._make_books()
        self.pipeline = "golden" if self.world is not None else "stub"
        self.boot_error: str | None = None
        self.trace = self._open_trace()
        acl = _module("engine.acl")
        self.broker = acl.Broker(clock=self.clock, trace=self.trace) if acl is not None else None
        if self.broker is not None and self.world is not None:
            self.broker.register_sources(self.world.sources)
        from .auth import Signer
        from .blame import Blamer
        from .lifecycle import Lifecycle
        self.signer = Signer(settings.secret)
        self.lifecycle = Lifecycle(self)
        self.blamer = Blamer(self)

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
        """A trace commit that never takes the pipeline down (returns None on failure, logged)."""
        try:
            return getattr(self.trace, method)(*args, **kwargs)
        except Exception as exc:
            log.warning("trace.%s failed: %s", method, exc)
            return None

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
            self.clock.invalidate()
            self.trace = self._open_trace()
            if self.broker is not None:
                self.broker.trace = self.trace
                self.broker.log.clear()

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

    def boot_rules(self, world: World) -> list[Rule]:
        from contracts import stub_app as stub
        rules: dict[str, Rule] = {r.id: r for r in stub.RULES}   # cards + the mined 50% reroute cut
        miner = _module("engine.miner")
        mine = getattr(miner, "mine_rules", None) if miner else None
        if mine is not None:
            try:
                for p in call(mine, world):
                    rule = getattr(p, "rule", p)
                    # mined at onboarding: active from the boot clock (plan §3 Learns strip)
                    rules[rule.id] = rule.model_copy(update={"status": "active"}) if rule.status == "shadow" \
                        else rule
            except Exception as exc:
                log.warning("miner failed (%s); using the stub's mined rule", exc)
        return list(rules.values())

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
    def storm_days(self, world: World) -> list[tuple[str, date]]:
        hub = str(world.meta.get("hub_icao") or world.meta.get("hub") or "EIDW")
        if len(hub) == 3:
            a = compose.airport_by(world, hub)
            hub = a.icao if a else "EIDW"
        return compose.storm_days(world, hub)

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
        self.commit_rules(self.boot_rules(world))
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
        self.seed_denial()

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

    def explain(self, d: FlightDecision) -> Draft:
        drafter = self.impls.drafter
        fn = getattr(drafter, "explain", None) if drafter is not None else None
        if fn is None or self.settings.mode == "offline":
            return compose.template_explanation(d)
        with cf.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(fn, d)
            try:
                out = fut.result(timeout=self.settings.reader_timeout_s)
                return out if isinstance(out, Draft) else compose.template_explanation(d)
            except Exception:
                return compose.template_explanation(d)

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
            if self.store.get("ev_fact", e.fact_id) is not None:
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

    def run_and_store(self, world: World, station: str, day: date, known_at: datetime, *, source: str,
                      rules: list[Rule] | None = None, curated: bool = True) -> RunResult:
        """Run one storm day end to end and store run, flight files, decisions, entitlements, questions, trace."""
        from contracts import stub_app as stub
        rules = rules if rules is not None else self.rules()
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
        if self.books is not None:
            all_ents = [e for d in decisions for e in ents[d.flight_id]]
            try:
                journal = list(self.books.post_storm(run_id, world, decisions, all_ents, known_at))
            except Exception as exc:
                log.warning("books.post_storm(%s) failed: %s", run_id, exc)
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
            stub_run = stub.STORM_RUNS.get(run_id)
            learned = list(stub_run.learned) if stub_run is not None else compose.default_learned(rules)

        if engine_run is not None:
            dec_by = {d.flight_id: d for d in decisions}
            run = engine_run.model_copy(update={
                "flights": [r.model_copy(update={"decision": dec_by.get(r.flight.id, r.decision)})
                            for r in engine_run.flights],
                "liability_drafted_cents": liability if self.books is not None else engine_run.liability_drafted_cents,
                "questions": questions, "learned": learned, "feed": []})
        else:
            run = compose.compose_run(world=world, station=station, day=day, flights=flights, decisions=decisions,
                                      ents=ents, questions=questions, learned=learned,
                                      liability_drafted_cents=liability, obs=obs, windows=windows)
        self._store_run(world, run, decisions, ents, journal, obs, windows, questions, known_at)
        self._emit_run(run, decisions, ents, journal, questions, known_at, source)
        return RunResult(run=run, decisions=decisions, ents=ents, journal=journal)

    def _store_run(self, world: World, run: StormRun, decisions: list[FlightDecision],
                   ents: dict[str, list[Entitlement]], journal: list[JournalEntry], obs: list, windows: list,
                   questions: list[Question], known_at: datetime) -> None:
        flights = {r.flight.id: r.flight for r in run.flights}
        books_journal = journal
        if self.books is not None:
            try:
                books_journal = list(self.books.journal())
            except Exception:
                pass
        for d in decisions:
            f = flights.get(d.flight_id)
            if f is None:
                continue
            fe = ents.get(d.flight_id, [])
            ff = compose.flight_file(world, f, d, fe, books_journal, obs, windows, self.explain(d))
            self.store.put("decision", d.flight_id, d, known_at)
            self.store.put("entitlements", d.flight_id, fe, known_at)
            self.store.put("flight_file", d.flight_id, ff, known_at)
            self.store.put("flight_run", d.flight_id, {"run": run.id}, known_at)
        for q in questions:
            self.store.put("question", q.id, q, known_at)
            self.record("record_question", q, "agent.engine", known_at, event="asked")
        self.store.put("storm_run", run.id, run, known_at)

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
        held_ids = {d.flight_id for d in decisions if d.outcome == "escalated"}
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
            self._process_claims()
            self._remind()

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

    def _process_claims(self) -> None:
        """Claims received by now are assessed at face value (Books drafts; the Claims Lead approves)."""
        if self.world is None or self.books is None:
            return
        for claim in sorted(self.world.claims, key=lambda c: (c.received_at, c.id)):
            if claim.received_at > self.now:
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
        qs = [q for q in self.questions() if q.id in ids or set(q.case_refs) & refs]
        return run.model_copy(update={"questions": qs, "feed": self.store.trace()})

    def storm_summaries(self) -> list[StormSummary]:
        out = []
        qs = self.questions()
        for key in self.store.keys("storm_run"):
            run = StormRun.model_validate(self.store.get("storm_run", key))
            ids = {x.id for x in run.questions}
            out.append(StormSummary(id=run.id, station=run.station, date=run.date,
                                    cancelled=run.counters.get("cancelled", 0),
                                    questions=sum(1 for q in qs if q.id in ids and q.status != "answered"),
                                    liability_drafted_cents=run.liability_drafted_cents))
        return out

    def flight_file(self, flight_id: str) -> FlightFile | None:
        data = self.store.get("flight_file", flight_id)
        return FlightFile.model_validate(data) if data is not None else None

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
