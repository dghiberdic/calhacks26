"""Pick implementations by env (`ENGINE_IMPL`, `BOOKS_IMPL`, `READER_IMPL`, `DRAFTER_IMPL`, `WORLD_IMPL`; fake|real).

Other lanes land their pieces while the server runs, so everything here is discovered, never assumed:
- `real` uses the real module when it exists on main, else the fake from `contracts/fakes.py`, else `None`
  (the caller then falls back to the stub's canned behaviour).
- `fake` uses the fake when it exists, else the real module.

`describe()` reports what was actually chosen per component for `/api/health`.
"""
from __future__ import annotations

import importlib
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("stormcheck.server")


def _module(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except ImportError:
        return None
    except Exception as exc:   # noqa: BLE001  (a half-landed module must never take the server down)
        log.warning("import %s failed: %s", name, exc)
        return None


def find(candidates: list[tuple[str, str]]) -> Any:
    """First `module.attr` that imports, e.g. find([("engine.api", "Engine"), ("engine", "run_storm")])."""
    for mod_name, attr in candidates:
        mod = _module(mod_name)
        if mod is not None and hasattr(mod, attr):
            return getattr(mod, attr)
    return None


def instantiate(obj: Any, **kwargs: Any) -> Any:
    """Instantiate a class with whichever of `kwargs` its constructor accepts; return non-classes unchanged."""
    if not inspect.isclass(obj):
        return obj
    try:
        params = inspect.signature(obj).parameters
    except (TypeError, ValueError):
        params = {}
    accepted = {k: v for k, v in kwargs.items() if k in params}
    try:
        return obj(**accepted)
    except Exception as exc:   # noqa: BLE001  (an impl that can't start degrades to stub behaviour)
        log.warning("could not instantiate %s: %s", obj, exc)
        return None


def call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call `fn` with the keyword arguments it accepts (positional ones always passed)."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn(*args, **kwargs)
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return fn(*args, **kwargs)
    return fn(*args, **{k: v for k, v in kwargs.items() if k in params})


# ---------------------------------------------------------------- candidate locations
FAKES = "contracts.fakes"
ENGINE_CANDIDATES = [("engine.api", "Engine"), ("engine.engine", "Engine"), ("engine.storm", "Engine"),
                     ("engine.run", "Engine"), ("engine", "Engine"), ("engine.api", "RealEngine"),
                     ("engine", "RealEngine")]
RUN_STORM_CANDIDATES = [("engine.storm", "run_storm"), ("engine.run", "run_storm"), ("engine.api", "run_storm"),
                        ("engine.pipeline", "run_storm"), ("engine", "run_storm")]
READER_CANDIDATES = [("llm.reader", "Reader"), ("llm.reader", "RealReader"), ("llm", "Reader")]
DRAFTER_CANDIDATES = [("llm.drafter", "Drafter"), ("llm.drafter", "RealDrafter"), ("llm", "Drafter")]
GENERATE_DAY_CANDIDATES = [("world.generate", "generate_day"), ("world.generator", "generate_day"),
                           ("world.day", "generate_day"), ("world", "generate_day")]


@dataclass
class Impls:
    """What the server runs on. Any of these may be None: callers degrade to stub behaviour."""
    engine: Any = None            # object with run_storm/decide/entitlements/mine_rules (EngineAPI), or None
    engine_kind: str = "stub"     # real | fake | mixed | stub
    engine_parts: dict[str, str] = field(default_factory=dict)
    fake_engine: Any = None
    books_cls: Any = None
    books_kind: str = "stub"
    reader: Any = None
    reader_kind: str = "stub"
    fallback_reader: Any = None   # FakeReader (regex) when it exists
    drafter: Any = None
    drafter_kind: str = "stub"
    generate_day: Callable[..., Any] | None = None
    world_kind: str = "stub"
    world_error: type[Exception] | None = None

    def describe(self) -> dict[str, str]:
        out = {"engine": self.engine_kind, "books": self.books_kind, "reader": self.reader_kind,
               "drafter": self.drafter_kind, "world": self.world_kind}
        out.update({f"engine.{k}": v for k, v in sorted(self.engine_parts.items())})
        return out


def _fake(name: str, **kw: Any) -> Any:
    cls = find([(FAKES, name)])
    return instantiate(cls, **kw) if cls is not None else None


def _pick(want: str, real: Callable[[], Any], fake: Callable[[], Any]) -> tuple[Any, str]:
    order = [("real", real), ("fake", fake)] if want == "real" else [("fake", fake), ("real", real)]
    for kind, make in order:
        obj = make()
        if obj is not None:
            return obj, kind
    return None, "stub"


def engine_parts() -> dict[str, str]:
    """Which engine modules exist on this checkout (for /health and DECISIONS)."""
    parts = {}
    for mod in ("timeline", "cause", "eu261", "confidence", "routing", "rules", "lifecycle", "trace", "acl", "miner"):
        parts[mod] = "real" if _module(f"engine.{mod}") is not None else "missing"
    return parts


def select(impl: dict[str, str], *, clock: Any = None) -> Impls:
    out = Impls()
    out.fake_engine = _fake("FakeEngine", clock=clock)

    def real_engine() -> Any:
        obj = find(ENGINE_CANDIDATES)
        if obj is not None:
            return instantiate(obj, clock=clock)
        fn = find(RUN_STORM_CANDIDATES)
        return _FnEngine(fn) if fn is not None else None

    eng, kind = _pick(impl.get("engine", "real"), real_engine, lambda: out.fake_engine)
    out.engine = eng
    out.engine_parts = engine_parts()
    # "mixed": no full run_storm on main yet, the server composes it from engine modules (see pipeline.compose_run)
    out.engine_kind = kind if eng is not None else ("mixed" if out.engine_parts.get("eu261") == "real" else "stub")

    def real_books() -> Any:
        return find([("books", "Books")])

    out.books_cls, out.books_kind = _pick(impl.get("books", "real"), real_books, lambda: find([(FAKES, "FakeBooks")]))

    out.fallback_reader = _fake("FakeReader")
    out.reader, out.reader_kind = _pick(impl.get("reader", "real"),
                                        lambda: instantiate(find(READER_CANDIDATES)) if find(READER_CANDIDATES)
                                        else None, lambda: out.fallback_reader)
    out.drafter, out.drafter_kind = _pick(impl.get("drafter", "real"),
                                          lambda: instantiate(find(DRAFTER_CANDIDATES)) if find(DRAFTER_CANDIDATES)
                                          else None, lambda: _fake("FakeDrafter"))

    def real_gen() -> Any:
        return find(GENERATE_DAY_CANDIDATES)

    def fake_gen() -> Any:
        fw = _fake("FakeWorld")
        return getattr(fw, "generate_day", None) if fw is not None else None

    if impl.get("world", "real") == "fake":
        out.generate_day, out.world_kind = _pick("fake", real_gen, fake_gen)
    else:
        # real: WorldAPI.generate_day when it lands, else the server's adapter over world.generator (desk.py),
        # else FakeWorld (golden storm days only)
        out.generate_day = real_gen()
        if out.generate_day is not None:
            out.world_kind = "real"
        elif _module("world.generator") is not None:
            out.world_kind = "real:generator"
        else:
            out.generate_day, out.world_kind = _pick("fake", real_gen, fake_gen)
    out.world_error = find([("world.errors", "WorldError")])
    return out


class _FnEngine:
    """Adapter for a module-level `run_storm` (EngineAPI's other methods are composed by the server)."""

    def __init__(self, fn: Callable[..., Any]):
        self.run_storm = fn
