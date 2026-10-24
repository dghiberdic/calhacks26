"""The server's runtime: boot pipeline (world → engine → books), clock, documents, reset.

Boot (fresh every process start; see server/DECISIONS.md):
1. Load the golden world if `STORMCHECK_WORLD` (default contracts/fixtures/golden/world.json) exists; otherwise
   serve the stub fixtures through the same document store ("stub" pipeline).
2. Rules: the engine miner when it exists, else the stub's rule cards (incl. active R-MINED-REDUCE).
3. Every storm day in the world whose morning-after is ≤ the boot clock is run: the engine's `run_storm` when one
   is importable (real Engine, else FakeEngine), else `compose` from the engine modules that exist.
4. Decisions, entitlements, journals and questions are committed (hash chain) and posted to Books.
5. The whole DB (server + books tables) is snapshotted to baseline.db; `/api/reset` copies it back.
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

from pydantic import TypeAdapter

from contracts.models import (
    Draft, Entitlement, FlightDecision, FlightFile, JournalEntry, LearnedItem, Question, Role, Rule, Source,
    StormRun, StormSummary, TraceEvent, World,
)

from . import compose
from .config import ROOT, Settings
from .impls import Impls, _module, call, select
from .store import Store, iso

log = logging.getLogger("stormcheck.server")
DEMO_START = datetime(2025, 1, 25, 6, 0, tzinfo=UTC)     # "the morning after" Éowyn
MORNING_AFTER = timedelta(days=1, hours=6)
ENTS = TypeAdapter(list[Entitlement])


def _git_sha() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                             timeout=5)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


class ServerClock:
    """Forward-only clock (CONTRACTS §2 Clock) persisted in sc_clock; Books and the engine get this object."""

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
        start = self._boot_known_at()
        self.clock = ServerClock(self.store, start)
        self.impls: Impls = select(settings.impl, clock=self.clock)
        self.books = self._make_books()
        self.engine_sha = _git_sha()
        self.pipeline = "golden" if self.world is not None else "stub"
        self.boot_error: str | None = None

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
        from .impls import instantiate
        return instantiate(cls, db_path=str(self.settings.db_path), clock=self.clock)

    @property
    def now(self) -> datetime:
        return self.clock.now()

    def inputs(self, *extra: str) -> list[str]:
        return [*extra, f"engine@{self.engine_sha}", f"cal@{compose.CAL_VERSION}"]

    def emit(self, kind: str, actor: str, summary: str, chip: str, ref: str | None = None,
             amount: int | None = None, at: datetime | None = None) -> TraceEvent:
        return self.store.emit(at=at or self.now, kind=kind, actor=actor, summary=summary, chip=chip, ref=ref,
                               amount_cents=amount)

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
            self.store.restore(self.settings.baseline)
            self.clock.invalidate()

    def _boot_stub(self) -> None:
        from contracts import stub_app as stub
        now = self.now
        for r in stub.RULES:
            self.store.put("rule", r.id, r, now)
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
    def boot_rules(self, world: World) -> list[Rule]:
        from contracts import stub_app as stub
        rules: dict[str, Rule] = {}
        for r in stub.RULES:          # rule cards: regulation, hard controls, the static Reg 2026/2202 card
            rules[r.id] = r
        miner = _module("engine.miner")
        mine = getattr(miner, "mine_rules", None) if miner else None
        if mine is None and self.impls.engine is not None:
            mine = getattr(self.impls.engine, "mine_rules", None)
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

    # storm run --------------------------------------------------------
    def storm_days(self, world: World) -> list[tuple[str, date]]:
        hub = str(world.meta.get("hub_icao") or world.meta.get("hub") or "EIDW")
        if len(hub) == 3:
            a = compose.airport_by(world, hub)
            hub = a.icao if a else "EIDW"
        return compose.storm_days(world, hub)

    def _boot_world(self, world: World) -> None:
        now = self.now
        for r in self.boot_rules(world):
            self.store.put("rule", r.id, r, now)
        for s in world.sources:
            self.store.commit(kind="fact", actor="agent.reader", at=now, payload=s, payload_ref=s.id,
                              message=f"source · {s.kind.value} · {s.title} (tier {s.trust_tier})",
                              inputs=self.inputs(s.sha256))
        ran = 0
        for station, day in self.storm_days(world):
            run_at = datetime(day.year, day.month, day.day, tzinfo=UTC) + MORNING_AFTER
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

    def engine_run(self, world: World, station: str, day: date, rules: list[Rule], known_at: datetime) -> StormRun | None:
        eng = self.impls.engine
        if eng is None or not hasattr(eng, "run_storm"):
            return None
        try:
            return call(eng.run_storm, world, station, day, rules, known_at)
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
            if ff is not None:
                out.append(compose.rebase_decision(ff.decision, known_at))
            else:
                out.append(compose.provisional_decision(f, world, known_at))
        return out

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
            flights = compose.run_flights(world, iata, day)
            decisions = self.decide_all(world, flights, known_at, curated)
        ents: dict[str, list[Entitlement]] = {}
        for d in decisions:
            ents[d.flight_id] = compose.entitlements_for(d, world, rules, known_at, self.impls.engine)

        # commits: decision → entitlements (the hash chain the trace and blame walk)
        committed = []
        for d in decisions:
            c = self.store.commit(kind="decision", actor="agent.engine", at=known_at, payload=d,
                                  payload_ref=d.flight_id, inputs=self.inputs(),
                                  message=f"{d.flight_id.split('@')[0]} · {d.cause.value} · "
                                          f"{d.extraordinary.value}" + (f" · recoded {d.recode_label}"
                                                                        if d.recoded else ""))
            committed.append(d.model_copy(update={"commit": c.hash}))
            fe = ents[d.flight_id]
            if fe:
                self.store.commit(kind="entitlement", actor="agent.engine", at=known_at, payload=fe,
                                  payload_ref=d.flight_id, inputs=self.inputs(c.hash),
                                  message=f"{d.flight_id.split('@')[0]} · {len(fe)} entitlements · "
                                          f"{compose.eur(sum(e.compensation_cents for e in fe))} full Art. 7 "
                                          "entitlement")
        decisions = committed

        journal: list[JournalEntry] = []
        if self.books is not None:
            all_ents = [e for d in decisions for e in ents[d.flight_id]]
            try:
                journal = list(self.books.post_storm(run_id, world, decisions, all_ents, known_at))
            except Exception as exc:
                log.warning("books.post_storm(%s) failed: %s", run_id, exc)
        for je in journal:
            self.store.commit(kind="journal_event", actor="agent.books", at=known_at, payload=je, payload_ref=je.id,
                              inputs=self.inputs(*(x for x in [je.source_decision_id] if x)),
                              message=f"{je.id} drafted · {je.kind} · "
                                      f"{compose.eur(sum(line.cr_cents for line in je.lines if line.account == '2140'))}")
        liability = sum(line.cr_cents - line.dr_cents for je in journal for line in je.lines
                        if line.account == "2140" and je.kind == "compensation_estimate")

        if engine_run is not None and engine_run.questions:
            questions = list(engine_run.questions)
        else:
            extra = [ob.cohort for ob in world.opening_balances] if source == "boot" else []
            questions = compose.group_questions(run_id, decisions, ents, known_at,
                                                curated=stub.QUESTIONS if curated else (), extra_case_refs=extra)
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
                "liability_drafted_cents": liability or engine_run.liability_drafted_cents,
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
        for q in questions:
            self.store.put("question", q.id, q, known_at)
            self.store.commit(kind="question", actor="agent.engine", at=known_at, payload=q, payload_ref=q.id,
                              inputs=self.inputs(), message=f"{q.id} → {q.routed_to.value} · {q.pattern} · "
                              f"{q.confidence.score if q.confidence.score is not None else 'uncalibrated'}")
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
        weather = [d for d in decisions if d.cause.value == "weather"]
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

    # ------------------------------------------------------------------ views
    def storm_run(self, run_id: str) -> StormRun | None:
        data = self.store.get("storm_run", run_id)
        if data is None:
            return None
        run = StormRun.model_validate(data)
        qs = [q for q in self.questions() if set(q.case_refs) & self._run_refs(run) or q.id in {x.id for x in
                                                                                                run.questions}]
        return run.model_copy(update={"questions": qs, "feed": self.store.trace()})

    @staticmethod
    def _run_refs(run: StormRun) -> set[str]:
        return {r.flight.id for r in run.flights}

    def storm_summaries(self) -> list[StormSummary]:
        out = []
        for key in self.store.keys("storm_run"):
            run = StormRun.model_validate(self.store.get("storm_run", key))
            open_q = sum(1 for q in self.questions() if q.id in {x.id for x in run.questions}
                         and q.status != "answered")
            out.append(StormSummary(id=run.id, station=run.station, date=run.date,
                                    cancelled=run.counters.get("cancelled", 0), questions=open_q,
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
        if self.pipeline == "stub":
            d["engine"] = "stub"
        if self.world is None:
            d["world"] = "stub"
        if self.books is None:
            d["books"] = "stub"
        if self.boot_error:
            d["boot_error"] = self.boot_error[:200]
        return d


def source_tier(kind: str) -> int:
    return {"tech_log": 1, "mcc_log": 1, "metar": 1, "manufacturer": 2, "schedule": 2, "occ_log": 3, "crm": 3}.get(
        kind, 4)


__all__ = ["Runtime", "ServerClock", "RunResult", "Source", "LearnedItem", "Role", "source_tier"]
